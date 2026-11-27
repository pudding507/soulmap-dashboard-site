-- 分国家每能量到手 · Revenue per Energy by Country
--
-- 2026-11-26 新建。接替同名的实验卡(原卡 474,当天随能量定价实验 D-594 的七张分组卡一起下线,
--   SQL 存在 `old/下线的卡/能量定价实验_分国家每能量到手.sql`)。
--   **去掉了 arm 维度**,并把人群从「实验期注册的新用户」放开到**全部活跃用户** ——
--   这个指标问的是「这个国家的一能量值多少钱」,老用户才是收入主力,只看新用户会读偏。
--
-- 🛑 本卡**不拆天**:按国家整段合计。按天拆每国每天的能量消耗掉到读不出。
--
-- ═══ 🛑 五个必须知道的口径 ═══
--
-- ① **每能量到手 = 该国用户的到手收入 ÷ 该国用户消耗的能量。**
--    免费发的能量也在分母里 ⇒ 这是**实际变现率,不是标价**。
--
-- ② **分母是「谁消耗的能量」,分子是「谁付的钱」,两边不是同一批人** ——
--    绝大多数消耗能量的人从来没付过钱。这正是这个指标要回答的:
--    一个国家的用户平均要白用多少能量,才换来一块钱。
--
-- ③ 🔴 **人群 = 窗口内有能量消耗、或有购买的用户**(两边取并集),不是该国全部注册用户。
--    拿全部注册用户当分母会把从不活跃的号算进去,`active_users` 这一列就没法读。
--
-- ④ 到手收入的空值兜底是 **0.85**,不是 0。`subscription_event_log.takehome_percentage`
--    2026-11-04 09:52:27 才开始有值,用 0 兜底会把前段的到手收入全算成 0。见口径 24.32。
--
-- ⑤ **窗口 14 天**,和「分条数段的每条毛利」保持一致:成本从 2026-11-06 中午才记齐,
--    滚动 14 天的下界永远落在那之后。
--
-- 🛑 `soulmap_energy_txn.source = 'manual_adjust'` 是后台手工改余额,不算消耗(liwen 588 §1 第 7 项)。
-- 🛑 排 CityPLX(口径 23.1),**但保留 `app_source='web'`** —— 这是全产品口径的单位经济,
--    不按端切。网页 2026-11-23 20:48 起开始写 `app_source='web'`,见口径 24.36。
-- 🛑 **两道「读不出」的闸,任一不过就不给比率**(那一列会写明是哪一道):
--    ① 能量消耗 < 100 —— 分母太小。
--    ② 🔴 **买家 < 10 人** —— 分子太小。这一道是实测逼出来的:
--       澳洲 14 天只有 4 个买家,其中**一个人就占 $404**(11-19~11-26 全平台第一),
--       每能量到手因此显示 $0.0089、全场最高。那不是「澳洲用户值钱」,
--       是一个人撑起了一整行。不加这道闸,这张卡最容易被读错的就是这种格子。
-- 🛑 `HAVING active_users >= 20`:人数太少的国家不单独成行,避免一两个人决定一个国家的读数。
WITH window_start AS (
    SELECT DATE(CURRENT_DATE - INTERVAL 14 DAY) AS t0
),
energy_consumed_by_user AS (
    SELECT txn.user_id AS user_key, SUM(txn.amount) AS energy_consumed
    FROM soul_map.soulmap_energy_txn AS txn
    CROSS JOIN window_start
    WHERE txn.op = 'consume'
      AND txn.source <> 'manual_adjust'      -- 见卡头
      AND txn.created_at >= window_start.t0
    GROUP BY txn.user_id
),
takehome_by_user AS (
    SELECT sel.user_id AS user_id_int,
           SUM(sel.price_usd * COALESCE(sel.takehome_percentage, 0.85)) AS takehome_usd
    FROM soul_map.subscription_event_log AS sel
    CROSS JOIN window_start
    WHERE sel.environment = 'PRODUCTION'
      AND sel.event_type IN ('NON_RENEWING_PURCHASE','INITIAL_PURCHASE','RENEWAL')
      AND sel.price_usd > 0
      AND sel.event_at >= window_start.t0
    GROUP BY sel.user_id
),
active_user_keys AS (
    -- 见口径 ③:消耗过能量的 ∪ 付过钱的
    SELECT user_key FROM energy_consumed_by_user
    UNION
    SELECT CAST(user_id_int AS CHAR) COLLATE utf8mb4_unicode_ci FROM takehome_by_user
),
scoped_users AS (
    SELECT u.id                                          AS user_id_int,
           CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_key,
           u.country_code                                AS country_code
    FROM soul_map.`user` AS u
    INNER JOIN active_user_keys
            ON active_user_keys.user_key = CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci
    WHERE COALESCE(u.app_source, '') <> 'city'
),
cost_by_user AS (
    SELECT cost.user_id AS user_key, SUM(cost.usd) AS cost_usd
    FROM soul_map.soulmap_cost_call AS cost
    CROSS JOIN window_start
    INNER JOIN scoped_users ON scoped_users.user_key = cost.user_id
    WHERE cost.status = 'ok' AND cost.call_at >= window_start.t0
    GROUP BY cost.user_id
)
SELECT
    scoped_users.country_code                                            AS country_code,
    COUNT(*)                                                             AS active_users,
    SUM(CASE WHEN takehome_by_user.takehome_usd > 0 THEN 1 ELSE 0 END)   AS buyers,
    COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0)            AS energy_consumed,
    ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0), 2)            AS takehome_usd,
    ROUND(COALESCE(SUM(cost_by_user.cost_usd), 0), 2)                    AS cost_usd,
    -- 两道闸:能量 < 100 或 买家 < 10 都不给比率,见卡头
    CASE WHEN COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0) < 100
            OR SUM(CASE WHEN takehome_by_user.takehome_usd > 0 THEN 1 ELSE 0 END) < 10
         THEN NULL
         ELSE ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0)
                    / NULLIF(SUM(energy_consumed_by_user.energy_consumed), 0), 6) END
                                                                         AS takehome_usd_per_energy,
    CASE WHEN COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0) < 100
         THEN CONCAT(COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0), ' 能量 · 读不出(分母<100)')
         WHEN SUM(CASE WHEN takehome_by_user.takehome_usd > 0 THEN 1 ELSE 0 END) < 10
         THEN CONCAT(ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0), 2), ' USD / ',
                     COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0), ' 能量 · 读不出(买家 ',
                     SUM(CASE WHEN takehome_by_user.takehome_usd > 0 THEN 1 ELSE 0 END), ' 人 <10)')
         ELSE CONCAT(ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0), 2), ' USD / ',
                     COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0), ' 能量') END
                                                                         AS numerator_over_denominator,
    ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0)
          - COALESCE(SUM(cost_by_user.cost_usd), 0), 2)                  AS net_usd
FROM scoped_users
LEFT JOIN energy_consumed_by_user ON energy_consumed_by_user.user_key  = scoped_users.user_key
LEFT JOIN takehome_by_user        ON takehome_by_user.user_id_int      = scoped_users.user_id_int
LEFT JOIN cost_by_user            ON cost_by_user.user_key             = scoped_users.user_key
GROUP BY scoped_users.country_code
HAVING active_users >= 20
ORDER BY energy_consumed DESC

