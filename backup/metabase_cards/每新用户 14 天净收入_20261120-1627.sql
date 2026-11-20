-- 能量定价实验 · 主指标:每新用户 14 天净收入 · Energy Pricing A/B — Net Revenue per User (14d)
--
-- 2026-11-18 新建。计划第 1 节的**判定主指标**:每个新用户注册后 14 天,到手收入减去服务成本。
--   判定用单人封顶 $50 的版本(takehome_usd_capped50),不封顶的一起列出。
--
-- 🔴 **这张卡今天只有 7 天那一档有数,14 天那一档是空的,不是 bug。**
--    `soulmap_cost_call` 的五个组件 11-06 12:28~13:56 才全部开始记账(口径 24.21),
--    更早注册的队列拿不到完整成本、净额会虚高,所以 SQL 里硬性下限 11-06。
--    11-06 + 14 天 = 11-20,**第一个 14 天完整队列 11-20 才出现**。
--    7 天那一列是为了空跑期能对账才加的,不是判定口径。
--
-- 🛑 cohort_maturity 这一列必须显示:把「还没满 14 天的人」和「满了的人」混在一个分母里,
--    会让净收入系统性偏低(晚注册的人还没来得及买)。--
-- 🛑 全部能量实验卡共用的四条口径:
--   1. **分组来源是 `soulmap_energy_pricing_arm`**(user_id 一行一个,arm 取 A / B)。
--      2026-11-18 16:42 服务端新建,**不是** `experiment_assignment_v1` —— 这个实验不走那张通用分组表。
--      写入逻辑 liwen 排期 11-21~23 上线,在那之前表是空的,所有人落在 `unassigned` 一行,
--      卡照常出数,这就是计划里说的「看板空跑对账」。
--   2. 这张分组表的 `user_id` 排序规则是 `utf8mb4_unicode_ci`,**和能量 / 聊天 / 成本各表一致**,
--      join 不需要特殊处理(旧的 `experiment_assignment_v1` 是 `0900_ai_ci`,那个才要 COLLATE 转换)。
--   3. 🔴 **必须排 CityPLX**(口径 23.1):VivoCity 游戏的角色对话也走 SoulMap,每个玩家一个
--      guest 账号、`user.app_source='city'`。近 14 天有 2,659 个,全在 SG、几乎不消耗能量、零付费。
--      不排的话分母虚高近一倍 —— 实测首购率会从 3.69% 被稀释成 1.95%。app 用户这个字段是空的。
--   4. 比率的分子 < 10 一律输出「读不出」,不给百分比(全项目口径)。
--
-- 🔴 2026-11-18 16:42 改:分组表换成服务端新建的 `soulmap_energy_pricing_arm`
--    (原来读 `experiment_assignment_v1` 的占位实验,那个实验永远不会有数据)。
--    影响:实验开跑后才有差别;现在表是空的,所有人仍落在 unassigned 一行,数字不变。

WITH experiment_window AS (
    SELECT COALESCE(
               -- 2026-11-18 16:42 起改读服务端新建的专用分组表
               (SELECT DATE(MIN(assigned_at)) FROM soul_map.soulmap_energy_pricing_arm),
               DATE(CURRENT_DATE - INTERVAL 41 DAY)
           ) AS experiment_start_date,
           -- soulmap_cost_call 的五个组件 11-06 12:28~13:56 才全部开始记账(口径 24.21)。
           -- 更早注册的队列拿不到完整成本,算出来的净额会虚高,所以这里硬性下限 11-06。
           DATE('2026-11-06') AS cost_data_start_date
),
mature_users AS (
    SELECT
        u.id                                          AS user_id_int,
        CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_key,
        COALESCE(assignment.arm, 'unassigned')        AS arm,
        u.create_time                                 AS signed_up_at,
        u.create_time + INTERVAL 14 DAY               AS window_end_at,
        u.create_time + INTERVAL 7  DAY               AS window_end_at_7d
    FROM soul_map.user u
    CROSS JOIN experiment_window w
    LEFT JOIN soul_map.soulmap_energy_pricing_arm assignment
           ON assignment.user_id = CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci
    WHERE DATE(u.create_time) >= GREATEST(w.experiment_start_date, w.cost_data_start_date)
      -- 🛑 排 CityPLX(口径 23.1),理由同其它卡
      AND (u.app_source IS NULL OR u.app_source = '')
      AND u.create_time + INTERVAL 7 DAY <= NOW()
),
revenue_14d AS (
    SELECT mature_users.user_id_int,
           SUM(sel.price_usd * COALESCE(sel.takehome_percentage, 0)) AS takehome_usd,
           SUM(CASE WHEN sel.event_at < mature_users.window_end_at_7d
                    THEN sel.price_usd * COALESCE(sel.takehome_percentage, 0) ELSE 0 END) AS takehome_usd_7d,
           MAX(CASE WHEN mature_users.window_end_at <= NOW() THEN 1 ELSE 0 END) AS is_mature_14d
    FROM mature_users
    JOIN soul_map.subscription_event_log sel
      ON sel.user_id = mature_users.user_id_int
     AND sel.event_at >= mature_users.signed_up_at
     AND sel.event_at <  mature_users.window_end_at
    WHERE sel.environment = 'PRODUCTION'
      AND sel.event_type IN ('NON_RENEWING_PURCHASE','INITIAL_PURCHASE','RENEWAL')
      AND sel.price_usd > 0
    GROUP BY mature_users.user_id_int
),
cost_14d AS (
    SELECT mature_users.user_id_int, SUM(cost.usd) AS cost_usd,
           SUM(CASE WHEN cost.call_at < mature_users.window_end_at_7d THEN cost.usd ELSE 0 END) AS cost_usd_7d
    FROM mature_users
    JOIN soul_map.soulmap_cost_call cost
      ON cost.user_id = mature_users.user_key
     AND cost.call_at >= mature_users.signed_up_at
     AND cost.call_at <  mature_users.window_end_at
    WHERE cost.status = 'ok'
    GROUP BY mature_users.user_id_int
)
SELECT
    mature_users.arm                                                    AS arm,
    CASE WHEN mature_users.window_end_at <= NOW() THEN '14d 已成熟 mature'
         ELSE '仅 7d 可读 7d only' END                                   AS cohort_maturity,
    COUNT(*)                                                            AS users,
    ROUND(COALESCE(SUM(revenue_14d.takehome_usd), 0), 2)                AS takehome_usd,
    ROUND(COALESCE(SUM(LEAST(revenue_14d.takehome_usd, 50)), 0), 2)     AS takehome_usd_capped50,
    ROUND(COALESCE(SUM(cost_14d.cost_usd), 0), 2)                       AS cost_usd,
    ROUND(COALESCE(SUM(revenue_14d.takehome_usd), 0)
          - COALESCE(SUM(cost_14d.cost_usd), 0), 2)                     AS net_usd,
    ROUND((COALESCE(SUM(revenue_14d.takehome_usd), 0)
           - COALESCE(SUM(cost_14d.cost_usd), 0)) / NULLIF(COUNT(*), 0), 4) AS net_usd_per_user,
    ROUND((COALESCE(SUM(LEAST(revenue_14d.takehome_usd, 50)), 0)
           - COALESCE(SUM(cost_14d.cost_usd), 0)) / NULLIF(COUNT(*), 0), 4) AS net_usd_per_user_capped50,
    SUM(CASE WHEN revenue_14d.takehome_usd > 0 THEN 1 ELSE 0 END)       AS buyers,
    SUM(CASE WHEN revenue_14d.takehome_usd > 50 THEN 1 ELSE 0 END)      AS buyers_over_50usd,
    ROUND((COALESCE(SUM(revenue_14d.takehome_usd_7d), 0)
           - COALESCE(SUM(cost_14d.cost_usd_7d), 0)) / NULLIF(COUNT(*), 0), 4) AS net_usd_per_user_7d
FROM mature_users
LEFT JOIN revenue_14d ON revenue_14d.user_id_int = mature_users.user_id_int
LEFT JOIN cost_14d    ON cost_14d.user_id_int    = mature_users.user_id_int
GROUP BY mature_users.arm, cohort_maturity
ORDER BY mature_users.arm, cohort_maturity

