-- 🛑 本卡**不拆天**(没有 date 列):A/B 实验按臂 × 国家整段合计。再按天拆每格只剩几个人。(2026-11-20 补记)
-- 能量定价实验 · 分国家每能量到手 · Energy Pricing A/B — Revenue per Energy by Country
--
-- 2026-11-18 新建。计划第 6 节看板「分国家每能量到手」。
--   每能量到手 = 该国用户的到手收入 ÷ 该国用户消耗的能量。它衡量「这个国家的一能量值多少钱」——
--   同样消耗 1 能量,印度用户贡献 $0.0053、美国 $0.0031、英国 $0.0023(实测,现价)。
--
-- 🛑 三个口径:
--   1. **国家取 `user.country_code`(注册国家),不是商店国家。**
--      `soulmap_energy_order.store_country` 86 行全空,用不了;`subscription_event_log.country_code`
--      只有买过的人才有,拿它当分母会把没买的人全漏掉。两种国家口径不要混着读。
--   2. 分母 < 100 能量的国家标「读不出」,不给单价 —— 小分母上这个比值跳得没有意义。
--   3. `net_usd`(到手减成本)**不含广告花费**,不是真正的赚赔。--
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
--    同时排掉 `source='manual_adjust'`(后台手工改余额)。
--    影响:实验开跑后才有差别;现在表是空的,所有人仍落在 unassigned 一行,数字不变。

-- 2026-11-25 修:到手收入的空值兜底从 0 改成 0.85。`subscription_event_log.takehome_percentage`
--   2026-11-04 09:52:27 才开始有值,之前全是 NULL(近 30 天窗口里占 132 行 / gross 的 22%)。
--   原来的 COALESCE(...,0) 会把那一段的到手收入全部算成 0。见口径 24.32。
WITH experiment_window AS (
    SELECT COALESCE(
               -- 2026-11-18 16:42 服务端建好了专用分组表,不再用 experiment_assignment_v1。
               (SELECT DATE(MIN(assigned_at)) FROM soul_map.soulmap_energy_pricing_arm),
               DATE(CURRENT_DATE - INTERVAL 13 DAY)
           ) AS experiment_start_date
),
experiment_users AS (
    SELECT
        u.id                                          AS user_id_int,
        CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_key,
        COALESCE(assignment.arm, 'unassigned')        AS arm,
        u.country_code                                AS country_code,
        DATE(u.create_time)                           AS signup_date
    FROM soul_map.user u
    CROSS JOIN experiment_window w
    LEFT JOIN soul_map.soulmap_energy_pricing_arm assignment
           ON assignment.user_id = CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci
    WHERE DATE(u.create_time) >= w.experiment_start_date
      -- 🛑 排 CityPLX(口径 23.1):VivoCity 游戏里的角色对话也走 SoulMap,每个玩家一个 guest 账号,
      --    user.app_source='city'。近 14 天有 2,659 个,全在 SG、几乎不消耗能量、零付费。
      --    不排的话分母虚高近一倍,首购率会被稀释到实际值的一半。app 用户这个字段是空的。
      AND (u.app_source IS NULL OR u.app_source = '')
)
, energy_consumed_by_user AS (
    SELECT txn.user_id AS user_id, SUM(txn.amount) AS energy_consumed
    FROM soul_map.soulmap_energy_txn txn
    INNER JOIN experiment_users ON experiment_users.user_key = txn.user_id
    WHERE txn.op = 'consume'
      AND txn.source <> 'manual_adjust'   -- 后台手工改余额,见 liwen 588 §1 第 7 项
      AND txn.created_at >= (SELECT experiment_start_date FROM experiment_window)
    GROUP BY txn.user_id
),
takehome_by_user AS (
    SELECT sel.user_id AS user_id_int,
           SUM(sel.price_usd * COALESCE(sel.takehome_percentage, 0.85)) AS takehome_usd
    FROM soul_map.subscription_event_log sel
    WHERE sel.environment = 'PRODUCTION'
      AND sel.event_type IN ('NON_RENEWING_PURCHASE','INITIAL_PURCHASE','RENEWAL')
      AND sel.price_usd > 0
      AND sel.event_at >= (SELECT experiment_start_date FROM experiment_window)
    GROUP BY sel.user_id
),
cost_by_user AS (
    SELECT cost.user_id AS user_id, SUM(cost.usd) AS cost_usd
    FROM soul_map.soulmap_cost_call cost
    INNER JOIN experiment_users ON experiment_users.user_key = cost.user_id
    WHERE cost.status = 'ok' AND cost.call_at >= (SELECT experiment_start_date FROM experiment_window)
    GROUP BY cost.user_id
)
SELECT
    experiment_users.country_code                                        AS country_code,
    experiment_users.arm                                                 AS arm,
    COUNT(*)                                                             AS users,
    SUM(CASE WHEN takehome_by_user.takehome_usd > 0 THEN 1 ELSE 0 END)   AS buyers,
    COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0)            AS energy_consumed,
    ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0), 2)            AS takehome_usd,
    ROUND(COALESCE(SUM(cost_by_user.cost_usd), 0), 2)                    AS cost_usd,
    CASE WHEN COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0) < 100 THEN NULL
         ELSE ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0)
                    / NULLIF(SUM(energy_consumed_by_user.energy_consumed), 0), 6) END
                                                                         AS takehome_usd_per_energy,
    CASE WHEN COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0) < 100
         THEN CONCAT(COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0), ' 能量 · 读不出(分母<100)')
         ELSE CONCAT(ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0), 2), ' USD / ',
                     COALESCE(SUM(energy_consumed_by_user.energy_consumed), 0), ' 能量') END
                                                                         AS numerator_over_denominator,
    ROUND(COALESCE(SUM(takehome_by_user.takehome_usd), 0)
          - COALESCE(SUM(cost_by_user.cost_usd), 0), 2)                  AS net_usd
FROM experiment_users
LEFT JOIN energy_consumed_by_user ON energy_consumed_by_user.user_id = experiment_users.user_key
LEFT JOIN takehome_by_user        ON takehome_by_user.user_id_int    = experiment_users.user_id_int
LEFT JOIN cost_by_user            ON cost_by_user.user_id            = experiment_users.user_key
GROUP BY experiment_users.country_code, experiment_users.arm
HAVING users >= 20
ORDER BY energy_consumed DESC
