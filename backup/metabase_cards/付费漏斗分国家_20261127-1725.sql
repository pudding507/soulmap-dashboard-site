--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-10-29:`soul_map.subscription` 里混着**沙盒订阅**,本卡此前全算进去了 ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   这张表**没有 `environment` 列**(和 `subscription_event_log` 不一样),
--   但 `raw_payload` 里有 `subscriptions.<product_id>.is_sandbox`。
--   实测(按本卡原来的过滤 `product_id NOT LIKE '%admin_test%'`):
--     算进来、不是沙盒 786 行 / 613 人 · **算进来、是沙盒 97 行 / 15 人** · 被 admin_test 排掉 28 行 / 4 人
--   近 14 天命中:10-29 `plus.energy` 1 人 · 10-22 / 10-21 / 10-18 各 1 人(`plus.monthly`)。
--   🛑 **全库只占 2.4%,但落在命中那几天就是当天 6~17 人里的 1 个**,
--      右半边的订阅列(试用生效 / 0.99 / 付费 / Apple / Google)都会多算。
--   ⇒ 本卡读 `soul_map.subscription` 的**两处**都加 `raw_payload NOT LIKE '%"is_sandbox":true%'`。
--   🛑 改后 10-18 / 10-21 / 10-22 / 10-29 的订阅数各少 1 人,**是修正不是掉量**。
--   🛑 沙盒行的特征是「同一人同一商品、每行只活约 5 分钟」(加速续订),
--      认它**不要靠这个特征去猜**,直接读 `is_sandbox`。
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑 2026-10-29:商店里多了三类非订阅商品,付费口径必须按 product_id 限定      ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【两个断点】
--     · **2026-10-22** 「买 3 天」通行证开始有真实购买(服务端 10-19 就绪)
--     · **2026-10-28 14:32:20** 能量系统上线(能量包 L1~L6 + 能量版 Plus 订阅)
--   三类商品**和月订阅共用 `purchase_started` / `purchase_completed` 两个事件**,
--   也**一起进 `soul_map.subscription_event_log`** —— 不加限定就会被算成订阅。
--
--   【2026-10-29 实测,全时段】
--     purchase_started    : plus.monthly 4,299 · (无 product_id) 99(04-15~09-28,老客户端)
--                           pass.3day 15 · one.monthly 10(已停用) · energy.l2 3
--                           · plus.energy:monthly 1 · energy.l1 1 · energy.l6 1
--     purchase_completed  : plus.monthly 485 · pass.3day 7 · energy.l2 1
--     purchase_recovered  : 只有 plus.monthly 12 笔,**不受影响**
--     subscription_event_log(全时段,按 event_type):
--       🛑 **按 `environment` 拆开看**(2026-10-29 复核补):
--       pass.3day        NON_RENEWING_PURCHASE  PRODUCTION 6 笔 $6.53(10-24~10-28)· SANDBOX 2 笔(10-23)
--       energy.l1        NON_RENEWING_PURCHASE  PRODUCTION 1 笔 $0.51(10-28)
--       energy.l2        NON_RENEWING_PURCHASE  **SANDBOX** 1 笔 $0.99(10-28)
--       plus.energy:monthly  **9 笔全部 SANDBOX**(10-28 19:07~19:43)—— 生产一笔都没有
--       ⇒ `price_usd > 0` 的行只有三种 event_type:INITIAL_PURCHASE / RENEWAL / NON_RENEWING_PURCHASE。
--         所以「排掉 NON_RENEWING_PURCHASE」和「只留前两种」在当前数据上**等价**;
--         本卡用前者(黑名单),将来多一种付费 event_type 时不会被静默漏掉。
--
--   🛑 **不能靠 `is_trial` 或 `period_type` 区分** —— 非订阅商品是
--      `is_trial=false` / `period_type=NORMAL`,但月订阅的「当场付清」(0.99 和全价)
--      也是 `is_trial=false`。**只能靠 `product_id`(埋点)或 `event_type`(服务端)。**
--
--   🛑 **两张表的 product_id 写法不一样**:`subscription_event_log` 写
--      `com.soulmap.plus.energy:monthly`,`soul_map.subscription` 写
--      `com.soulmap.plus.energy`(无 `:monthly`)。**按 product_id join 两张表会静默漏行。**
--
-- ═══ 🔴 2026-11-11:`clicked_subscribe` 补上月卡族 ═══
--   改了什么:`purchase_started` 的 product_id 条件补 `LIKE 'com.soulmap.plus.energy%'`。
--   为什么:原条件只认 `= 'com.soulmap.plus.monthly'`,月卡
--     (`com.soulmap.plus.energy:prepaid-1m`)点了订阅却被算成没点。
--   三种拼法:`:prepaid-1m`(现行预付)· `:monthly`(安卓续费)· `.monthly`(iOS 续费,**点号**)。
--   🔴 据服务端 550(2026-11-11),康确认两商店上架后 liwen 改配置即切、**不发版**,
--      切换时点我们事先不知道 ⇒ **用前缀匹配,不要改回等号。**
--   影响:`clicked_subscribe` 会比改前高一点(多收月卡点击);改前改后这一列不可比。
--   不受影响的:本卡 `has_paid` 取自 `soul_map.subscription`,不按 product_id 分类。
--
--   🛑 跨 10-22 / 10-28 和更早的数据比时,**旧数里这三类是混着的**,不是本卡改坏了。
--   【本卡改动】`clicked_subscribe` 用的 `purchase_started` 加同样限定。
--     本卡混进来的比 395 多:**21 笔**(通行证 15 + 能量包 5 + 能量版 Plus 1)。
--     🛑 本卡下界是 `GREATEST('20260912', 今天-30天)`,现在算出来是 20260929,
--        而 `product_id IS NULL` 的 99 笔到 09-28 为止 —— **只差一天**,
--        所以 `OR IS NULL` 那一支必须留着,窗口一旦放宽就立刻用得上。
--
-- ═══ 🛑 2026-10-19:「付费」口径修正(只改口径,不加列) ═══
--   实测:买过 0.99 的 43 人在 soul_map.subscription 里 **100% 是 in_trial=1**,一个 0 都没有;
--   对照免费试用 460 人里 439 人 in_trial=1、只有 21 人是 0。
--   ⇒ in_trial=0 的真实含义是「已走过首期、按原价续上了」,全库只有 21 人,
--     原写法把**全部 0.99 买家漏在外面** —— 他们明明付了钱。
--   改动:付费判定补 `OR 买过 INTRO`(period_type='INTRO',不能靠 product_id)。
--   🛑 **不新增列**:本卡是**漏斗图**,has_paid 是漏斗最后一级。加列会多出一级、
--      破坏「严格嵌套」的读法。修正后该级的数会变大(补回 0.99),结构不变。
--   与看板 24 的 400 `has_paid` 完全同口径。
-- 【展示形式】**图形**(漏斗图),这是本看板少数适合画漏斗的卡。理由:
--   七级**是严格嵌套**的:装机 ⊇ 开口 ⊇ 累计20句 ⊇ 撞墙 ⊇ 点订阅 ⊇ 试用生效 ⊇ 真实付费,
--   每一级都是上一级的子集,漏斗图正好表达这个包含关系,逐级流失一眼可见。
--   🛑 **所以本卡修口径时不加列** —— 加列会多出一级、破坏嵌套,
--      2026-10-20 补 0.99 时只把最后一级的判定改对,级数没变。
--   分国家可切换,各国分母独立。
WITH firebase_scan AS (          -- 单次扫描 firebase_event,条件聚合,不拆多 CTE 各扫一遍
  SELECT user_pseudo_id                                                         AS device,
         MIN(CASE WHEN event_name = 'first_open' THEN event_date END)           AS install_date,
         MIN(CASE WHEN event_name = 'first_open' THEN country    END)           AS install_country,
         MAX(CASE WHEN uid REGEXP '^[0-9]+$'     THEN uid        END)           AS account_id,
         COUNT(CASE WHEN event_name = 'message_send_result'
                     AND params ->> '$.result'  = 'ok'
                     AND params ->> '$.host_id' NOT LIKE 'reception%'
                    THEN 1 END)                                                 AS ok_messages,
         MAX(CASE WHEN event_name = 'paywall_viewed'
                   AND params ->> '$.source'  = 'plus_sheet'
                   AND params ->> '$.trigger' = 'message_quota' THEN 1 ELSE 0 END) AS saw_quota_paywall,
         -- 🔴 2026-10-29 新增 product_id 限定(见卡头断点说明)。
         --    🛑 `IS NULL` 那一支是给 2026-09-28 以前的老客户端留的(那时没有这个字段)。
         --    本卡下界现在是 GREATEST('20260912', 今天-30天) = 够不着那段,但窗口一动就会碰上。
         -- 🔴 2026-11-11 补一支:月卡 / 订阅制能量(`plus.energy` 族)此前不在这个条件里,
         --    它们的 `purchase_started` 被当成「没点订阅」丢掉了。前缀匹配一次盖住
         --    `:prepaid-1m` / `:monthly` / `.monthly` 三种拼法,见卡头同日说明。
         MAX(CASE WHEN event_name = 'purchase_started'
                   AND (params ->> '$.product_id' = 'com.soulmap.plus.monthly'
                        OR params ->> '$.product_id' LIKE 'com.soulmap.plus.energy%'
                                     OR params ->> '$.product_id' IS NULL) THEN 1 ELSE 0 END) AS clicked_subscribe
  FROM host.firebase_event
  WHERE event_name IN ('first_open','message_send_result','paywall_viewed','purchase_started')
    -- 见头部:09-12 是额度墙上线日,GREATEST 防止窗口滑到它之前
    AND event_date >= GREATEST('20260912', DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d'))
  GROUP BY user_pseudo_id
  HAVING install_date IS NOT NULL          -- 只保留窗口内装机的设备
),
post_launch_user AS (            -- 付费功能 2026-09-11 上线,此前的订阅行是上线前测试。见头部
  SELECT user_id
  FROM (SELECT user_id, trial_started_at AS related_at
          FROM soul_map.subscription_user_state WHERE trial_used = 1
        UNION ALL
        SELECT user_id, start_time       AS related_at
          FROM soul_map.subscription
          WHERE product_id NOT LIKE '%admin_test%'
            AND raw_payload NOT LIKE '%"is_sandbox":true%') AS related
  GROUP BY user_id
  HAVING MIN(related_at) >= '2026-09-11'
),
subscription_account AS (
  SELECT CAST(s.user_id AS CHAR)                                          AS account_id,
         MAX(1)                                                           AS has_subscription,
         -- 2026-10-19:补 0.99。原写法只认 in_trial=0,把买 0.99 的人整批漏掉
         MAX((s.in_trial = 0 AND s.status <> 'EXPIRED')
             OR intro.user_id IS NOT NULL)                                AS has_paid
  FROM soul_map.subscription AS s
  JOIN post_launch_user AS p ON p.user_id = s.user_id
  LEFT JOIN (SELECT DISTINCT user_id FROM soul_map.subscription_event_log
             WHERE environment = 'PRODUCTION' AND period_type = 'INTRO') AS intro
         ON intro.user_id = s.user_id
  WHERE s.product_id NOT LIKE '%admin_test%'
    AND s.raw_payload NOT LIKE '%"is_sandbox":true%'   -- 🔴 2026-10-29 新增:沙盒订阅,见卡头
  GROUP BY s.user_id
),
cohort AS (
  SELECT f.device,
         CASE WHEN f.install_country IN ('United States','United Kingdom','Canada','Australia')
                   THEN '1_英美加澳'
              WHEN f.install_country IN ('India','Pakistan','Bangladesh','Sri Lanka','Nepal')
                   THEN '2_南亚'
              ELSE '3_其它' END                                           AS country_group,
         f.ok_messages,
         f.saw_quota_paywall,
         f.clicked_subscribe,
         COALESCE(a.has_subscription, 0)                                  AS reached_trial,
         COALESCE(a.has_paid,         0)                                  AS reached_paid
  FROM firebase_scan AS f
  -- ⚠️ 必须显式 COLLATE:firebase_event.uid 是 utf8mb4_general_ci,
  --    CAST(subscription.user_id AS CHAR) 出来是 utf8mb4_0900_ai_ci,直接 = 会报 1267。
  LEFT JOIN subscription_account AS a
    ON a.account_id COLLATE utf8mb4_general_ci = f.account_id
),
-- ⚠️ 下面用 step_list × group_list 做笛卡尔积再 LEFT JOIN,不直接 GROUP BY 计数 ——
--    直接计数时「该组该环节 0 人」会输出成**缺行**,漏斗图上表现为线断掉,
--    读的人分不出「是 0」还是「没数据」。本卡最关键的一格(英美加澳的 7_付费)恰好是 0。
--    项目规矩:0 就是 0,显式写出来。
step_list (step) AS (
            SELECT '1_装机'
  UNION ALL SELECT '2_开口'        UNION ALL SELECT '3_累计20句'
  UNION ALL SELECT '4_撞墙'  UNION ALL SELECT '5_点订阅'
  UNION ALL SELECT '6_试用生效'    UNION ALL SELECT '7_真实付费'
),
group_list (country_group) AS (
  SELECT '1_英美加澳' UNION ALL SELECT '2_南亚' UNION ALL SELECT '3_其它'
),
reached AS (
            SELECT country_group, '1_装机'       AS step FROM cohort
  UNION ALL SELECT country_group, '2_开口'             FROM cohort WHERE ok_messages >= 1
  UNION ALL SELECT country_group, '3_累计20句'         FROM cohort WHERE ok_messages >= 20
  UNION ALL SELECT country_group, '4_撞墙'       FROM cohort WHERE saw_quota_paywall = 1
  UNION ALL SELECT country_group, '5_点订阅'           FROM cohort WHERE clicked_subscribe = 1
  UNION ALL SELECT country_group, '6_试用生效'         FROM cohort WHERE reached_trial = 1
  UNION ALL SELECT country_group, '7_真实付费'             FROM cohort WHERE reached_paid  = 1
),
counted AS (
  SELECT step, country_group, COUNT(*) AS users FROM reached GROUP BY step, country_group
)
SELECT sl.step              AS step,
       gl.country_group     AS grp,
       COALESCE(c.users, 0) AS users
FROM step_list AS sl
CROSS JOIN group_list AS gl
LEFT JOIN counted AS c ON c.step = sl.step AND c.country_group = gl.country_group
-- ⚠️ 行序有含义(漏斗自上而下 × 组内固定顺序),看板注册表里**不要写 sort**。
ORDER BY sl.step, gl.country_group;
