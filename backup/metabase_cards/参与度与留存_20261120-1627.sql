-- 能量定价实验 · 参与度与留存 · Energy Pricing A/B — Engagement & Retention
--
-- 2026-11-18 新建。计划第 6 节看板「每人消息数和第 7 天留存」。
--   涨价最直接的副作用是「用户少聊了」,这张卡就是看这个。
--
-- 🔴 **这里的第 7 天留存不是主看板那张 `Retention_d7` 的口径,两张卡的数不要互相对。**
--    主看板按**设备**(firebase 的 user_pseudo_id + session_start)算,因为它要和装机对齐;
--    本实验按**账号**分组,只能按账号算,这里用的是「注册后第 7 天还在发消息」。
--    两种口径实测接近(app_launch 判到 27 人、消息判到 29 人),但定义不同,分开读。
--
-- 🛑 `active_days_per_chatter` 实测只有 1.29 天 —— 绝大多数新用户只来一天。
--    第 7 天留存 2.2% 低是这个结构决定的,不是算错。--
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
, messages_per_user AS (
    -- 只聚合实验用户的消息(见 01 卡同一处注释)
    SELECT
        chat.user_id                                     AS user_id,
        COUNT(*)                                         AS user_message_count,
        COUNT(DISTINCT DATE(chat.add_on))                AS active_days,
        MIN(DATE(chat.add_on))                           AS first_message_date,
        MAX(DATE(chat.add_on))                           AS last_message_date
    FROM soul_map.soulmap_chat_history chat
    INNER JOIN experiment_users ON experiment_users.user_key = chat.user_id
    WHERE chat.role = 'user' AND chat.add_on >= (SELECT experiment_start_date FROM experiment_window)
    GROUP BY chat.user_id
)
SELECT
    experiment_users.arm                                                         AS arm,
    COUNT(*)                                                                     AS users_total,
    SUM(CASE WHEN messages_per_user.user_message_count >= 1  THEN 1 ELSE 0 END)  AS sent_1_plus,
    SUM(CASE WHEN messages_per_user.user_message_count >= 10 THEN 1 ELSE 0 END)  AS sent_10_plus,
    ROUND(100.0 * SUM(CASE WHEN messages_per_user.user_message_count >= 10 THEN 1 ELSE 0 END)
          / NULLIF(COUNT(*), 0), 1)                                              AS sent_10_plus_pct,
    SUM(CASE WHEN messages_per_user.user_message_count >= 30 THEN 1 ELSE 0 END)  AS sent_30_plus,
    ROUND(100.0 * SUM(CASE WHEN messages_per_user.user_message_count >= 30 THEN 1 ELSE 0 END)
          / NULLIF(COUNT(*), 0), 1)                                              AS sent_30_plus_pct,
    ROUND(COALESCE(SUM(messages_per_user.user_message_count), 0)
          / NULLIF(COUNT(*), 0), 1)                                              AS messages_per_user,
    ROUND(AVG(messages_per_user.active_days), 2)                                 AS active_days_per_chatter,
    SUM(CASE WHEN experiment_users.signup_date <= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
             THEN 1 ELSE 0 END)                                                  AS day7_denominator,
    SUM(CASE WHEN experiment_users.signup_date <= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
                  AND messages_per_user.last_message_date
                      >= DATE_ADD(experiment_users.signup_date, INTERVAL 7 DAY)
             THEN 1 ELSE 0 END)                                                  AS still_messaging_day7,
    ROUND(100.0 * SUM(CASE WHEN experiment_users.signup_date <= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
                                AND messages_per_user.last_message_date
                                    >= DATE_ADD(experiment_users.signup_date, INTERVAL 7 DAY)
                           THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN experiment_users.signup_date <= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
                            THEN 1 ELSE 0 END), 0), 1)                           AS still_messaging_day7_pct
FROM experiment_users
LEFT JOIN messages_per_user ON messages_per_user.user_id = experiment_users.user_key
GROUP BY experiment_users.arm
ORDER BY experiment_users.arm

