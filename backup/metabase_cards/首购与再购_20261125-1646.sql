-- 🛑 本卡**不拆天**(没有 date 列):A/B 实验按臂整段合计。按天拆每臂每天的首购人数是个位数,转化率读不出。(2026-11-20 补记)
-- 能量定价实验 · 首购与再购 · Energy Pricing A/B — Purchase Funnel
--
-- 2026-11-18 新建。对应计划第 6 节看板的三项:首购率 · 第一次用完时买的比例 · 又买比例。
--   这三个也是第 1 节早停规则看的指标(B 组比 A 组低 30% 以上且 95% 把握就停)。
--
-- 🛑 三个口径:
--   1. **「买」= `subscription_event_log` 里 price_usd > 0 的成交**,不是 `soulmap_energy_order`。
--      订单表 86 行全是服务端 Google Play 回调补记的,`price_micros` / `store_country` 全空,算不了钱。
--   2. **到手收入 = `price_usd × takehome_percentage`**(商店抽成后,现在固定 0.85),不是标价。
--   3. `bought_after_runout` 是「拿过首次用完赠送(txn source='first_out')之后买过」——
--      不是「在用完那一刻买」。现在分子只有 12,读不出,放着等实验期量起来。--
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
, purchases_per_user AS (
    SELECT
        sel.user_id                                              AS user_id_int,
        COUNT(*)                                                 AS purchase_count,
        MIN(sel.event_at)                                        AS first_purchase_at,
        ROUND(SUM(sel.price_usd * COALESCE(sel.takehome_percentage, 0)), 4) AS takehome_usd
    FROM soul_map.subscription_event_log sel
    WHERE sel.environment = 'PRODUCTION'
      AND sel.event_type IN ('NON_RENEWING_PURCHASE', 'INITIAL_PURCHASE', 'RENEWAL')
      AND sel.price_usd > 0
      AND sel.event_at >= (SELECT experiment_start_date FROM experiment_window)
    GROUP BY sel.user_id
),
first_runout_per_user AS (
    SELECT user_id, MIN(created_at) AS first_runout_at
    FROM soul_map.soulmap_energy_txn
    WHERE op = 'grant' AND source = 'first_out'
      AND created_at >= (SELECT experiment_start_date FROM experiment_window)
    GROUP BY user_id
)
SELECT
    experiment_users.arm                                                   AS arm,
    COUNT(*)                                                               AS users_total,

    SUM(CASE WHEN purchases_per_user.purchase_count > 0 THEN 1 ELSE 0 END) AS buyers,
    ROUND(100.0 * SUM(CASE WHEN purchases_per_user.purchase_count > 0 THEN 1 ELSE 0 END)
          / NULLIF(COUNT(*), 0), 2)                                        AS first_purchase_pct,

    SUM(CASE WHEN first_runout_per_user.first_runout_at IS NOT NULL THEN 1 ELSE 0 END) AS hit_first_runout,
    SUM(CASE WHEN first_runout_per_user.first_runout_at IS NOT NULL
                  AND purchases_per_user.first_purchase_at >= first_runout_per_user.first_runout_at
             THEN 1 ELSE 0 END)                                            AS bought_after_runout,
    ROUND(100.0 * SUM(CASE WHEN first_runout_per_user.first_runout_at IS NOT NULL
                                AND purchases_per_user.first_purchase_at >= first_runout_per_user.first_runout_at
                           THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN first_runout_per_user.first_runout_at IS NOT NULL THEN 1 ELSE 0 END), 0), 2)
                                                                           AS bought_after_runout_pct,

    SUM(CASE WHEN purchases_per_user.purchase_count >= 2 THEN 1 ELSE 0 END) AS repeat_buyers,
    ROUND(100.0 * SUM(CASE WHEN purchases_per_user.purchase_count >= 2 THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN purchases_per_user.purchase_count > 0 THEN 1 ELSE 0 END), 0), 2)
                                                                           AS repeat_purchase_pct,

    ROUND(COALESCE(SUM(purchases_per_user.takehome_usd), 0), 2)            AS takehome_usd_total,
    ROUND(COALESCE(SUM(purchases_per_user.takehome_usd), 0)
          / NULLIF(COUNT(*), 0), 4)                                        AS takehome_usd_per_user
FROM experiment_users
LEFT JOIN purchases_per_user    ON purchases_per_user.user_id_int = experiment_users.user_id_int
LEFT JOIN first_runout_per_user ON first_runout_per_user.user_id  = experiment_users.user_key
GROUP BY experiment_users.arm
ORDER BY experiment_users.arm
