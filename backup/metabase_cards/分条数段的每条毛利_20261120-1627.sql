-- 能量定价实验 · 按条数分段的每条毛利 · Energy Pricing A/B — Margin by Message Number
--
-- 2026-11-18 新建。计划第 6 节看板「按条数分段的每条毛利」—— 这是 D-594 涨价理由的直接验证。
--
-- 怎么算出「这个用户和这个角色的第几条」:`soulmap_cost_call` 里一条用户消息会产生多行
--   (回复、记忆、理解各一次调用),同一条消息共享同一组 (session_id, turn)。
--   所以先按 (user_id, host_id, session_id, turn) 聚合 = 一条消息及其全部 LLM 成本,
--   再按 (user_id, host_id) 用 ROW_NUMBER 排序得到序号。
--
-- 🛑 四个必须知道的:
--   1. **host_id / session_id / turn 各有 12~15% 为空,这些行整行排除。** 分母是「三样都齐」的消息。
--   2. `avg_energy_if_d594` 和 `margin_pct_if_d594` 是**静态模拟** —— 按现在这批消息,
--      如果改用 D-594 曲线会收多少能量。**它假设用户行为完全不变**,而涨价本来就会让人少聊。
--      🛑 **不能拿它当「改了之后就能赚这么多」读**,它只说明曲线本身的形状。
--   3. 每条收入 = 该段消耗的能量 × 每能量到手美元(全窗口到手收入 ÷ 全窗口消耗能量)。
--      免费发的能量也在分母里,所以这个单价已经被免费额度稀释过,是实际变现率不是标价。
--   4. D-594 曲线:前 30 条每条 1 能量,之后 1 + 2.5 × (1 − e^(−(n−30)/30)),上限约 3.5。--
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
               DATE(CURRENT_DATE - INTERVAL 13 DAY)
           ) AS experiment_start_date
),
experiment_users AS (
    SELECT
        CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_key,
        COALESCE(assignment.arm, 'unassigned')        AS arm
    FROM soul_map.user u
    CROSS JOIN experiment_window w
    LEFT JOIN soul_map.soulmap_energy_pricing_arm assignment
           ON assignment.user_id = CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci
    WHERE DATE(u.create_time) >= w.experiment_start_date
      -- 🛑 排 CityPLX(口径 23.1):VivoCity 游戏里的角色对话也走 SoulMap,每个玩家一个 guest 账号,
      --    user.app_source='city'。近 14 天有 2,659 个,全在 SG、几乎不消耗能量、零付费。
      --    不排的话分母虚高近一倍,首购率会被稀释到实际值的一半。app 用户这个字段是空的。
      AND (u.app_source IS NULL OR u.app_source = '')
),
takehome_per_energy AS (
    SELECT
        (SELECT COALESCE(SUM(price_usd * COALESCE(takehome_percentage, 0)), 0)
           FROM soul_map.subscription_event_log
          WHERE environment = 'PRODUCTION'
            AND event_type IN ('NON_RENEWING_PURCHASE','INITIAL_PURCHASE','RENEWAL')
            AND price_usd > 0
            AND event_at >= (SELECT experiment_start_date FROM experiment_window))
        /
        NULLIF((SELECT SUM(amount) FROM soul_map.soulmap_energy_txn
                 WHERE op = 'consume'
                   AND created_at >= (SELECT experiment_start_date FROM experiment_window)), 0)
        AS usd_per_energy_consumed
),
chat_turns AS (
    SELECT soulmap_cost_call.user_id AS user_id, host_id, session_id, turn,
           experiment_users.arm AS arm,
           MIN(call_at) AS turn_at,
           SUM(usd)     AS turn_cost_usd
    FROM soul_map.soulmap_cost_call
    INNER JOIN experiment_users ON experiment_users.user_key = soulmap_cost_call.user_id
    WHERE call_at >= (SELECT experiment_start_date FROM experiment_window)
      AND status = 'ok' AND cost_column = 'chat_llm'
      AND host_id    IS NOT NULL AND host_id    <> ''
      AND session_id IS NOT NULL AND session_id <> ''
      AND turn       IS NOT NULL
    GROUP BY soulmap_cost_call.user_id, host_id, session_id, turn, experiment_users.arm
),
numbered_messages AS (
    SELECT user_id, arm, host_id, turn_at, turn_cost_usd,
           ROW_NUMBER() OVER (PARTITION BY user_id, host_id
                              ORDER BY turn_at, session_id, turn) AS message_no
    FROM chat_turns
),
banded AS (
    SELECT
        CASE WHEN message_no <=  10 THEN '1-10'
             WHEN message_no <=  20 THEN '11-20'
             WHEN message_no <=  30 THEN '21-30'
             WHEN message_no <=  50 THEN '31-50'
             WHEN message_no <= 100 THEN '51-100'
             ELSE '101+' END AS message_band,
        CASE WHEN message_no <=  10 THEN 1 WHEN message_no <=  20 THEN 2
             WHEN message_no <=  30 THEN 3 WHEN message_no <=  50 THEN 4
             WHEN message_no <= 100 THEN 5 ELSE 6 END AS band_order,
        -- 现价:每条聊天 1 能量。D-594 曲线:前 30 条 1,之后 1 + 2.5 × (1 − e^(−(n−30)/30))
        1.0 AS energy_now,
        CASE WHEN message_no <= 30 THEN 1.0
             ELSE 1.0 + 2.5 * (1 - EXP(-(message_no - 30) / 30.0)) END AS energy_d594,
        user_id, arm, turn_cost_usd
    FROM numbered_messages
)
SELECT
    banded.arm                                                 AS arm,
    banded.message_band                                        AS message_band,
    COUNT(*)                                                   AS messages,
    COUNT(DISTINCT banded.user_id)                             AS users,
    ROUND(SUM(banded.turn_cost_usd), 2)                        AS cost_usd,
    ROUND(SUM(banded.turn_cost_usd) / NULLIF(COUNT(*), 0), 6)  AS cost_per_message_usd,
    ROUND(SUM(banded.energy_now) * takehome_per_energy.usd_per_energy_consumed
          / NULLIF(COUNT(*), 0), 6)                            AS revenue_per_message_now_usd,
    ROUND((SUM(banded.energy_now) * takehome_per_energy.usd_per_energy_consumed
           - SUM(banded.turn_cost_usd)) / NULLIF(COUNT(*), 0), 6) AS margin_per_message_now_usd,
    ROUND(100.0 * (SUM(banded.energy_now) * takehome_per_energy.usd_per_energy_consumed
                   - SUM(banded.turn_cost_usd))
          / NULLIF(SUM(banded.energy_now) * takehome_per_energy.usd_per_energy_consumed, 0), 1)
                                                               AS margin_pct_now,
    ROUND(AVG(banded.energy_d594), 2)                          AS avg_energy_if_d594,
    ROUND(SUM(banded.energy_d594) * takehome_per_energy.usd_per_energy_consumed
          / NULLIF(COUNT(*), 0), 6)                            AS revenue_per_message_d594_usd,
    ROUND(100.0 * (SUM(banded.energy_d594) * takehome_per_energy.usd_per_energy_consumed
                   - SUM(banded.turn_cost_usd))
          / NULLIF(SUM(banded.energy_d594) * takehome_per_energy.usd_per_energy_consumed, 0), 1)
                                                               AS margin_pct_if_d594
FROM banded
CROSS JOIN takehome_per_energy
GROUP BY banded.arm, banded.message_band, banded.band_order, takehome_per_energy.usd_per_energy_consumed
ORDER BY banded.arm, banded.band_order

