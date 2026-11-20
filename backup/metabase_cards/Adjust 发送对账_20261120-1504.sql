-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-11-20:对账对象补能量包 + kind 枚举兜底                           ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【为什么改】订阅线 2026-11-10 彻底停售 —— 最后一笔 0.99(INTRO)和最后一笔
--   免费试用都在 11-10。这张卡盯的 `intro_should_send` / `intro_sent` 从此恒为 0,
--   **而现在每天仍有约 20 人成交(全部是能量包)**,一笔都不在对账范围内。
--   ⇒ 对账对象必须跟着商品走,否则这张卡只会一直报「平」。
--
--   【查库实测(2026-11-20)】`adjust_s2s_send_log` **全历史只有四个 kind**:
--     TRIAL_START 369 · INTRO_PURCHASE 149 · TRIAL_CONVERSION 41 · INTRO_CONVERSION 27
--   **没有任何一条能量包回传记录。** 服务端侧已接入能量包事件,
--   所以新增的 `energy_should_send` / `energy_sent` 两列会把真实状态直接显出来:
--   应发有数、实发为 0,就是这一路没通;两边都有数且相等,就是通了。
--   🛑 **不要因为 `energy_sent` 是 0 就以为这两列没用** —— 那正是它要报的东西。
--
--   【顺带修的两个枚举漏项】
--   ① `INTRO_CONVERSION`(27 条,0.99 转全价)原来**没有任何一列**,一直静默不计。
--   ② 新增 `sent_other_kind` 兜底:不在已知 kind 里的 SENT 都落这里。
--      服务端加新 kind 时,这一列会立刻有数,而不是无声消失。
--
--   【结构改动】原来用两条 SELECT 做 UNION 模拟全外连接,加一列要改两处、容易漏。
--   改成 `all_day` 先把两边日期并起来,再各 LEFT JOIN 一次,列只写一遍。
--
-- 回传_Adjust 发送对账 · Attribution — Adjust S2S Reconciliation
--
-- ═══ 🛑 为什么要有这张卡 ═══
--   3.7.2 起同一笔 0.99 最多有**三条路**到 Meta,其中两路**没有共享 event_id、Meta 去重不了**:
--     ① 客户端 FB SDK 的 `Subscribe`(3.7.2 起)—— ✅ 已生效
--     ② RC webhook → Adjust S2S `099purchase` —— ✅ 一直在发(本卡盯的就是这一路)
--     ③ RevenueCat 后台的 Meta 集成 —— ⚠️ 开没开待确认
--   **三个数应该相等;不等就是漏了或双算了。**
--   🛑 第 ③ 路要去 Meta Events Manager 对,**看板里放不进来** —— 本卡只覆盖 ① 之外的服务端两侧。
--
--   要做的事(不是看板):Adjust 后台不能再把 `099purchase` 映射到 Meta;
--   RC 后台的 Meta 集成打开前,先定每类事件只留哪一路。
--
-- 【展示形式】**表格**,一行一天。要并排读「应发 / 实发 / 差」三个数再加失败分类,
--   折线读不出差值;而且量只有每天几笔到十几笔,画线没有意义。
--
-- 🛑 口径
-- ① 两张表的 `event_at` **都是 UTC**(实测 adjust_s2s_send_log 最大值 09:37 而 NOW() 是 17:50)。
--    两边都 CONVERT_TZ 到 SGT,转换一致所以差值不受影响;转是为了和看板其余各卡同一个日历。
-- ② 「应发」= subscription_event_log 里 period_type='INTRO' 的 INITIAL_PURCHASE(= 真实 0.99 首购)。
-- ③ 「实发」只数 status='SENT';`SKIPPED_NO_DEVICE_ID` 和 `FAILED` 单独成列 ——
--    它们是**真的没发出去**,不能算进实发,否则对账永远是平的。
-- ④ TRIAL_START / TRIAL_CONVERSION 一并列出:它们也走同一条回传路,也可能双算。
--    🛑 但它们的「应发」口径和 INTRO 不同,本卡**不给它们配应发数**,只看发送量和失败。
WITH server_purchase AS (        -- 应发:服务端真实成交,按商品族拆
  -- 2026-11-20:原来 WHERE 里就写死了 period_type='INTRO',放开成条件聚合,
  -- 这样一次扫描同时拿到 0.99 和能量两族的应发数。
  SELECT DATE(CONVERT_TZ(event_at, '+00:00', '+08:00'))            AS d,
         SUM(event_type = 'INITIAL_PURCHASE'
             AND period_type = 'INTRO')                            AS intro_should_send,
         -- 🛑 能量判据只能用 `%energy%`:商品有 energy.lN / plus.energy:prepaid-1m /
         --    plus.energy:monthly 三种形态,写 `com.soulmap.energy.%` 会漏掉后两种。
         --    也不能拿 NON_RENEWING_PURCHASE 当判据 —— 通行证 pass.* 也是它。
         SUM(product_id LIKE '%energy%'
             AND event_type IN ('INITIAL_PURCHASE', 'NON_RENEWING_PURCHASE'))
                                                                   AS energy_should_send
  FROM soul_map.subscription_event_log
  WHERE environment = 'PRODUCTION'
    AND event_at >= CURDATE() - INTERVAL 30 DAY
  GROUP BY 1
),
adjust_day AS (                  -- 实发 + 失败分类
  SELECT DATE(CONVERT_TZ(event_at, '+00:00', '+08:00'))            AS d,
         SUM(kind = 'INTRO_PURCHASE'    AND status = 'SENT')       AS sent_intro,
         SUM(kind = 'INTRO_CONVERSION'  AND status = 'SENT')       AS sent_intro_conv,
         SUM(kind = 'TRIAL_START'       AND status = 'SENT')       AS sent_trial_start,
         SUM(kind = 'TRIAL_CONVERSION'  AND status = 'SENT')       AS sent_trial_conv,
         SUM(kind LIKE '%ENERGY%'       AND status = 'SENT')       AS sent_energy,
         -- 兜底:服务端加了新 kind 时这一列会立刻有数,不会无声消失
         SUM(status = 'SENT'
             AND kind NOT IN ('INTRO_PURCHASE', 'INTRO_CONVERSION',
                              'TRIAL_START', 'TRIAL_CONVERSION')
             AND kind NOT LIKE '%ENERGY%')                         AS sent_other_kind,
         SUM(status = 'SKIPPED_NO_DEVICE_ID')                      AS skipped_no_device,
         SUM(status = 'FAILED')                                    AS failed
  FROM soul_map.adjust_s2s_send_log
  WHERE event_at >= CURDATE() - INTERVAL 30 DAY
  GROUP BY 1
),
all_day AS (                     -- 两边的日期并集。2026-11-20 起用它取代原来的 UNION 双写
  SELECT d FROM server_purchase
  UNION
  SELECT d FROM adjust_day
)
SELECT all_day.d                                                   AS date,
       COALESCE(server_purchase.intro_should_send, 0)              AS intro_should_send,
       COALESCE(adjust_day.sent_intro, 0)                          AS intro_sent,
       COALESCE(adjust_day.sent_intro, 0)
         - COALESCE(server_purchase.intro_should_send, 0)          AS intro_gap,
       COALESCE(server_purchase.energy_should_send, 0)             AS energy_should_send,
       COALESCE(adjust_day.sent_energy, 0)                         AS energy_sent,
       COALESCE(adjust_day.sent_energy, 0)
         - COALESCE(server_purchase.energy_should_send, 0)         AS energy_gap,
       COALESCE(adjust_day.sent_intro_conv, 0)                     AS intro_conversion_sent,
       COALESCE(adjust_day.sent_trial_start, 0)                    AS trial_start_sent,
       COALESCE(adjust_day.sent_trial_conv, 0)                     AS trial_conversion_sent,
       COALESCE(adjust_day.sent_other_kind, 0)                     AS sent_other_kind,
       COALESCE(adjust_day.skipped_no_device, 0)                   AS skipped_no_device_id,
       COALESCE(adjust_day.failed, 0)                              AS failed
FROM all_day
LEFT JOIN server_purchase ON server_purchase.d = all_day.d
LEFT JOIN adjust_day      ON adjust_day.d      = all_day.d
ORDER BY date DESC;
