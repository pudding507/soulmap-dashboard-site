-- 🛑 本卡**不拆天**(没有 date 列):A/B 实验按臂 × 长度段整段合计,看的是分布形状。按天拆分布就散了。(2026-11-20 补记)
-- 能量定价实验 · 对话长度分布与第 30 条附近换角色 · Energy Pricing A/B — Conversation Length
--
-- 2026-11-18 新建。计划第 6 节看板「在第 30 条附近换角色的比例」。
--   D-594 从第 30 条开始涨价,而换角色会让条数从第 1 条重新数 ⇒ 用户可能在第 30 条附近换角色避价。
--   一行一个「最终聊了多少条」的档位,看 26-30 这一档有没有异常堆积。
--
-- 🔴 **实测现在(还没有任何涨价)26-30 档就已经高于两边**:21-25 档 4.2% · **26-30 档 5.1%** ·
--    31-35 档 2.4%。原因几乎可以肯定是**免费额度正好是 30 条**(注册送 20 + 第一次用完送 10)。
--    🛑 **这意味着 D-594 的涨价点和免费额度耗尽点重合在同一条消息上。**
--    B 组用户在第 30 条会同时撞上「免费额度没了」和「每条变贵」两件事,
--    **这张卡读出的堆积分不清是哪一件造成的**,要分开只能靠和 A 组比同一个档位的占比差。
--
-- 🛑 一个用户可以有多个角色对话 ⇒ conversations 的和大于 users,不要拿 conversations 当人数。--
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
, conversation_length AS (
    SELECT
        chat.user_id                 AS user_key,
        chat.host_id                 AS host_id,
        COUNT(*)                     AS messages_in_conversation,
        MAX(chat.add_on)             AS last_message_at
    FROM soul_map.soulmap_chat_history chat
    INNER JOIN experiment_users ON experiment_users.user_key = chat.user_id
    WHERE chat.role = 'user'
      AND chat.add_on >= (SELECT experiment_start_date FROM experiment_window)
      AND chat.host_id IS NOT NULL AND chat.host_id <> ''
    GROUP BY chat.user_id, chat.host_id
),
banded AS (
    SELECT
        experiment_users.arm AS arm,
        conversation_length.user_key,
        CASE WHEN messages_in_conversation <= 10 THEN '1-10'
             WHEN messages_in_conversation <= 20 THEN '11-20'
             WHEN messages_in_conversation <= 25 THEN '21-25'
             WHEN messages_in_conversation <= 30 THEN '26-30'
             WHEN messages_in_conversation <= 35 THEN '31-35'
             WHEN messages_in_conversation <= 50 THEN '36-50'
             ELSE '51+' END AS final_length_band,
        CASE WHEN messages_in_conversation <= 10 THEN 1 WHEN messages_in_conversation <= 20 THEN 2
             WHEN messages_in_conversation <= 25 THEN 3 WHEN messages_in_conversation <= 30 THEN 4
             WHEN messages_in_conversation <= 35 THEN 5 WHEN messages_in_conversation <= 50 THEN 6
             ELSE 7 END AS band_order
    FROM conversation_length
    JOIN experiment_users ON experiment_users.user_key = conversation_length.user_key
)
SELECT
    banded.arm                                           AS arm,
    banded.final_length_band                             AS final_length_band,
    COUNT(*)                                             AS conversations,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY banded.arm), 1) AS pct_of_conversations,
    COUNT(DISTINCT banded.user_key)                      AS users
FROM banded
GROUP BY banded.arm, banded.final_length_band, banded.band_order
ORDER BY banded.arm, banded.band_order
