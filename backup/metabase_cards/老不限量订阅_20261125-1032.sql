-- 老订阅_不限量与迁移 · Legacy Unlimited — Status & Migration
-- 2026-11-12 新建。出处:需求文档 `01_看板/卡片需求_2026-11-12.md` §4.4(团队包看板 5)。
--
-- ═══ 这张卡回答什么 ═══
--   老的「不限量」订阅还剩多少人、还在不在卖、他们每天花掉多少服务成本,
--   以及过渡月(每天 100 能量)有没有真的开始。一行一天,近 30 天。
--
-- ═══ 🔴 两个现在就能读出的结论 ═══
--   ① **「老商品新开数」目标是 0,实际没有停。** 实测 2026-10-28 ~ 11-12:
--      `com.soulmap.plus.monthly` 系列 `INITIAL_PURCHASE` **38 笔 / 38 人**(最近一笔 11-10),
--      `com.soulmap.pass.3day` 另有 **6 笔 / 5 人**。⇒ 商店里这两个商品还买得到。
--   ② 【2026-11-13 改】**迁移已经开始了,建卡当天写的「现在必然是 0」已经过期。**
--      当天分两批跑完:**12:07:42 九人**(`soulmap_energy_txn.source='oldplus_multi'`,
--      6 人拿 100、3 人拿 950)、**17:33:15 七十九人**(`source='oldplus_switch'`,950)。
--      到 11-13 晚 `soulmap_energy_legacy` 共 **158 人,其中 88 人 `migrated_at` 非空**。
--      🛑 **走的不是「每天 100 的过渡月」,是直接切每月 950** —— `soulmap_energy_daily_plan`
--         到现在仍是 **0 行**。⇒ `entered_transition` 这一列读到的是「当天切过去的人数」,
--         不是「当天在过渡月里的人数」,引用时要说清。
--      🛑 `notice_acked_at` 只有 **2 人** ⇒ **点「Got it」不是迁移的前置条件**,
--         建卡当天推断的「先点 Got it、再等满 30 天后第一次续费」那条链路不成立。
--
-- ═══ 🛑 口径 ═══
--   ① **老商品是两个商品族,不是一个**:`com.soulmap.plus.monthly`(含 `:monthly` 后缀)
--      和 `com.soulmap.pass.3day`,前缀匹配。
--      🛑 **不要把 `com.soulmap.plus.energy%` 收进来** —— 那是新的月卡,是迁移的去处不是来源。
--   ② 「新开」判据是 `INITIAL_PURCHASE`(订阅)或 `NON_RENEWING_PURCHASE`(3 天通行证),
--      **不看 `product_id` 之外的东西**;续费是 `RENEWAL`。
--   ③ 「碰到每日额度」= 当天影子消耗触到 **100**(过渡月每天 100,当天有效、不累积;
--      过渡月之后每月 950)。🛑 2026-11-13 起实际走的是直接切 950(见卡头 ②),
--      过渡月没启用 ⇒ **`hit_daily_cap_users` 这一列现在读不出业务含义**,只当成
--      「当天影子消耗 ≥100 的人数」看,不要读成「被额度挡住的人」。影子消耗 = `soulmap_energy_shadow_charge`,
--      它记的是「如果这个人走能量制,这一轮要扣多少」,**不真的扣**,正好就是服务成本的口径。
--   ④ 队列 = `soulmap_energy_legacy`(服务端自己圈的老订阅名单,11-12 为 141 人、
--      11-13 为 158 人,会继续涨),
--      不自己再推一遍 —— 推法和服务端不一致会得出两个数。
--   ⑤ `event_at` 是 **UTC**,分天前 CONVERT_TZ 到 SGT。
--   ⑥ 2026-11-12 起 CityPLX 不再剔除,改成 `app_line` 一列并列(D-563);
--      实测老订阅名单里 CityPLX 0 人,这一列目前恒为 SoulMap。
--
-- ═══ 🛑 服务成本只给能量,不折美元 ═══
--   本卡的 `shadow_energy` 是**能量单位**。折成美元要一个「每能量多少钱」的汇率,
--   定稿里没有给(§4.1 那个 $0.0066 是**看广告送出的 coin 成本**,不是服务成本)。
--   ⇒ 要美元口径请用「每条回复成本」那条线(走内网成本看板),不要在这里自己乘。
--
-- ═══ 停止线(定稿)═══
--   碰到额度的人续费率比其余老订阅低 **30 个点以上**,或总续费收入一周掉 **20% 以上**
--   → 当天报 Michael。🛑 2026-11-13 88 人刚切过去,**切换前后的续费率还没有一个完整周期**,
--      这条线要等这批人走到各自的下一个续费日才读得出来,在那之前只立基线。
--
-- 【展示形式】**表格**,一行一天。三个理由:
--   ① 五个数量纲完全不同(人数 / 笔数 / 能量),折线叠不下;
--   ② 多数列是个位数,画图会让人读出不存在的趋势;
--   ③ 「新开数」要能一眼看见哪天不是 0,表格最直接。
WITH
legacy_cohort AS (          -- 队列:服务端圈的老订阅名单,见口径 ④
  SELECT CAST(l.user_id AS CHAR) COLLATE utf8mb4_general_ci          AS user_key,
         CAST(l.user_id AS UNSIGNED)                                 AS user_id,
         CASE WHEN u.app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line,
         DATE(l.migrated_at)                                         AS migrated_date,
         DATE(l.notice_acked_at)                                     AS acked_date
  FROM   soul_map.soulmap_energy_legacy AS l
  LEFT JOIN soul_map.`user` AS u ON u.id = CAST(l.user_id AS UNSIGNED)
  WHERE  CAST(l.user_id AS UNSIGNED) NOT IN (62412, 72048, 72382, 72462, 74640,
                                             74377, 74592, 71693, 71826)
),
day_axis AS (               -- 近 30 天的日期轴,保证没有事件的那天也出行
  SELECT DATE(CURDATE() - INTERVAL seq DAY) AS `date`
  FROM   (SELECT 0 AS seq UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
          UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7
          UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
          UNION ALL SELECT 12 UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15
          UNION ALL SELECT 16 UNION ALL SELECT 17 UNION ALL SELECT 18 UNION ALL SELECT 19
          UNION ALL SELECT 20 UNION ALL SELECT 21 UNION ALL SELECT 22 UNION ALL SELECT 23
          UNION ALL SELECT 24 UNION ALL SELECT 25 UNION ALL SELECT 26 UNION ALL SELECT 27
          UNION ALL SELECT 28 UNION ALL SELECT 29) AS s
),
legacy_event AS (           -- 老商品的订阅事件,见口径 ①②⑤
  -- 🛑 这一段**不限于上面那 141 人** —— 「新开」按定义就不在名单里,
  --    续费 / 到期也要看全部老商品订阅者,才是 `renew_pct` 该有的分母。
  SELECT DATE(CONVERT_TZ(e.event_at, '+00:00', '+08:00'))            AS `date`,
         CASE WHEN u.app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line,
         e.user_id                                                   AS user_id,
         e.event_type                                                AS event_type,
         e.price_usd                                                 AS price_usd
  FROM   soul_map.subscription_event_log AS e
  LEFT JOIN soul_map.`user` AS u ON u.id = e.user_id
  WHERE  e.environment = 'PRODUCTION'
    AND  (e.product_id LIKE 'com.soulmap.plus.monthly%'
       OR e.product_id LIKE 'com.soulmap.pass.3day%')
    AND  e.event_at >= CONVERT_TZ(CURDATE() - INTERVAL 30 DAY, '+08:00', '+00:00')
),
shadow_per_user_day AS (    -- 老订阅每人每天的影子消耗,见口径 ③
  SELECT DATE(sc.charged_at)                                         AS `date`,
         lc.app_line                                                 AS app_line,
         sc.user_id                                                  AS user_key,
         SUM(sc.amount)                                              AS energy,
         COUNT(*)                                                    AS turns
  FROM   soul_map.soulmap_energy_shadow_charge AS sc
  JOIN   legacy_cohort AS lc ON lc.user_key = sc.user_id
  WHERE  sc.charged_at >= CURDATE() - INTERVAL 30 DAY
  GROUP  BY DATE(sc.charged_at), lc.app_line, sc.user_id
)
-- 🛑 没有任何老商品事件的那一天也要留一行,所以 NULL 归到 SoulMap;
--    实测订阅表和老订阅名单里 CityPLX 都是 0 人,这一列目前恒为 SoulMap。
SELECT day_axis.`date`                                               AS `date`,
       COALESCE(legacy_event.app_line, 'SoulMap')                    AS app_line,
       -- 🔴 目标是 0。不是 0 就说明商店里还买得到,见卡头 ①
       COALESCE(SUM(legacy_event.event_type IN ('INITIAL_PURCHASE','NON_RENEWING_PURCHASE')), 0)
                                                                     AS new_legacy_buys,
       COALESCE(SUM(legacy_event.event_type = 'RENEWAL'), 0)         AS renewed_users,
       COALESCE(SUM(legacy_event.event_type = 'EXPIRATION'), 0)      AS expired_users,
       COALESCE(SUM(legacy_event.event_type = 'BILLING_ISSUE'), 0)   AS billing_issue_users,
       -- 🛑 分子 <10 读不出,比率留空
       CASE WHEN COALESCE(SUM(legacy_event.event_type = 'RENEWAL'), 0)
               + COALESCE(SUM(legacy_event.event_type = 'EXPIRATION'), 0) >= 10
            THEN ROUND(100.0 * SUM(legacy_event.event_type = 'RENEWAL')
                 / (SUM(legacy_event.event_type = 'RENEWAL')
                  + SUM(legacy_event.event_type = 'EXPIRATION')), 1) END AS renew_pct,
       ROUND(COALESCE(SUM(CASE WHEN legacy_event.event_type IN ('RENEWAL','INITIAL_PURCHASE')
                               THEN legacy_event.price_usd END), 0), 2) AS revenue_usd,
       -- 过渡月:见卡头 ②,现在必然是 0
       (SELECT COUNT(*) FROM legacy_cohort
         WHERE legacy_cohort.migrated_date = day_axis.`date`
           AND legacy_cohort.app_line = COALESCE(legacy_event.app_line, 'SoulMap'))         AS entered_transition,
       (SELECT COUNT(*) FROM legacy_cohort
         WHERE legacy_cohort.acked_date    = day_axis.`date`
           AND legacy_cohort.app_line = COALESCE(legacy_event.app_line, 'SoulMap'))         AS acked_notice,
       -- 服务成本(能量口径,不折美元,见卡头)
       (SELECT COUNT(*) FROM shadow_per_user_day AS s
         WHERE s.`date` = day_axis.`date` AND s.app_line = COALESCE(legacy_event.app_line, 'SoulMap'))                            AS active_legacy_users,
       (SELECT COUNT(*) FROM shadow_per_user_day AS s
         WHERE s.`date` = day_axis.`date` AND s.app_line = COALESCE(legacy_event.app_line, 'SoulMap')
           AND s.energy >= 100)        AS hit_daily_cap_users,
       (SELECT COALESCE(SUM(s.energy), 0) FROM shadow_per_user_day AS s
         WHERE s.`date` = day_axis.`date` AND s.app_line = COALESCE(legacy_event.app_line, 'SoulMap'))                            AS shadow_energy,
       (SELECT ROUND(COALESCE(SUM(s.energy), 0)
                   / NULLIF(COUNT(*), 0), 1) FROM shadow_per_user_day AS s
         WHERE s.`date` = day_axis.`date` AND s.app_line = COALESCE(legacy_event.app_line, 'SoulMap'))                            AS shadow_energy_per_user
FROM       day_axis
LEFT JOIN  legacy_event ON legacy_event.`date` = day_axis.`date`
GROUP BY   day_axis.`date`, COALESCE(legacy_event.app_line, 'SoulMap')
ORDER BY   day_axis.`date` DESC, app_line;

