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
WITH server_intro AS (           -- 应发:真实的 0.99 首购
  SELECT DATE(CONVERT_TZ(event_at, '+00:00', '+08:00'))            AS d,
         COUNT(*)                                                  AS should_send
  FROM soul_map.subscription_event_log
  WHERE environment = 'PRODUCTION' AND event_type = 'INITIAL_PURCHASE'
    AND period_type = 'INTRO'
    AND event_at >= CURDATE() - INTERVAL 30 DAY
  GROUP BY 1
),
adjust_day AS (                  -- 实发 + 失败分类
  SELECT DATE(CONVERT_TZ(event_at, '+00:00', '+08:00'))            AS d,
         SUM(kind = 'INTRO_PURCHASE'    AND status = 'SENT')       AS sent_intro,
         SUM(kind = 'TRIAL_START'       AND status = 'SENT')       AS sent_trial_start,
         SUM(kind = 'TRIAL_CONVERSION'  AND status = 'SENT')       AS sent_trial_conv,
         SUM(status = 'SKIPPED_NO_DEVICE_ID')                      AS skipped_no_device,
         SUM(status = 'FAILED')                                    AS failed
  FROM soul_map.adjust_s2s_send_log
  WHERE event_at >= CURDATE() - INTERVAL 30 DAY
  GROUP BY 1
)
SELECT COALESCE(s.d, a.d)                                          AS date,
       COALESCE(s.should_send, 0)                                  AS intro_should_send,
       COALESCE(a.sent_intro, 0)                                   AS intro_sent,
       COALESCE(a.sent_intro, 0) - COALESCE(s.should_send, 0)      AS intro_gap,
       COALESCE(a.sent_trial_start, 0)                             AS trial_start_sent,
       COALESCE(a.sent_trial_conv, 0)                              AS trial_conversion_sent,
       COALESCE(a.skipped_no_device, 0)                            AS skipped_no_device_id,
       COALESCE(a.failed, 0)                                       AS failed
FROM server_intro AS s
LEFT JOIN adjust_day AS a ON a.d = s.d
UNION
SELECT a.d, COALESCE(s.should_send, 0), a.sent_intro,
       a.sent_intro - COALESCE(s.should_send, 0),
       a.sent_trial_start, a.sent_trial_conv, a.skipped_no_device, a.failed
FROM adjust_day AS a LEFT JOIN server_intro AS s ON s.d = a.d
ORDER BY date DESC;

