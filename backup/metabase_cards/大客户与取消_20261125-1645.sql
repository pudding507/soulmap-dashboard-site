-- 能量 · 大客户与取消 · Energy — Top Spenders & Cancellations
--
-- 2026-11-18 新建。计划第 6 节看板「前 3 名」,以及「退款和骂价格」里能做的那一半。
--   计划第 2 节:这次改价最坏的情况不是少赚,而是丢掉现在的大客户 ⇒ 前几名要每周单独看。
--   近 30 天窗口,按到手收入排名取前 20。
--
-- 🔴 **「退款」现在没有数据源。** `subscription_event_log` 里没有 REFUND 这一类事件,
--    只有 `CANCELLATION`(关掉自动续费)和 `UNCANCELLATION`。本卡的 cancellations 列是前者,
--    **它不是退款** —— 用户关掉续费时这一期的钱并没有退回去。
--    一次性能量包的退款在这张表里完全看不到。要真做退款,得另外接商店的退款回执。
--    「骂价格」(应用商店差评、客服工单)同样没有数据源,本卡做不了。
--
-- 🛑 两个口径:
--   1. `pct_of_all_takehome` 的分母是**近 30 天全部到手收入**,不是前 20 名的和。
--   2. `net_usd` = 这个人的到手收入 − 这个人的服务成本。**会出现负数,那不是算错** ——
--      实测排第 3 的大客户 30 天聊了 18,931 条,成本 $45.54 高于他付的 $29.75,净 −$15.79。
--      🛑 **这正是 D-594 针对的那类人:买得不少,但聊得更多。**
--
-- 2026-11-19 修:user_id 转成字符串,否则显示成「72,740」(Metabase 对数值列自动加千分位)。

WITH spend_by_user AS (
    SELECT sel.user_id                                              AS user_id,
           SUM(sel.price_usd)                                       AS gross_usd,
           SUM(sel.price_usd * COALESCE(sel.takehome_percentage,0)) AS takehome_usd,
           COUNT(*)                                                 AS purchases,
           MIN(sel.event_at)                                        AS first_purchase_at,
           MAX(sel.event_at)                                        AS last_purchase_at
    FROM soul_map.subscription_event_log sel
    WHERE sel.environment = 'PRODUCTION'
      AND sel.event_type IN ('NON_RENEWING_PURCHASE','INITIAL_PURCHASE','RENEWAL')
      AND sel.price_usd > 0
      AND sel.event_at >= CURRENT_DATE - INTERVAL 30 DAY
    GROUP BY sel.user_id
),
cost_by_user AS (
    SELECT user_id, SUM(usd) AS cost_usd
    FROM soul_map.soulmap_cost_call
    WHERE status = 'ok' AND call_at >= CURRENT_DATE - INTERVAL 30 DAY
    GROUP BY user_id
),
messages_by_user AS (
    SELECT user_id, COUNT(*) AS user_messages, MAX(DATE(add_on)) AS last_message_date
    FROM soul_map.soulmap_chat_history
    WHERE role = 'user' AND add_on >= CURRENT_DATE - INTERVAL 30 DAY
    GROUP BY user_id
),
cancellations AS (
    SELECT user_id, COUNT(*) AS cancellations
    FROM soul_map.subscription_event_log
    WHERE event_type = 'CANCELLATION' AND event_at >= CURRENT_DATE - INTERVAL 30 DAY
    GROUP BY user_id
),
ranked AS (
    SELECT spend_by_user.*,
           ROW_NUMBER() OVER (ORDER BY spend_by_user.takehome_usd DESC) AS spend_rank,
           SUM(spend_by_user.takehome_usd) OVER ()                      AS takehome_usd_all_users
    FROM spend_by_user
)
SELECT
    ranked.spend_rank                                        AS spend_rank,
    -- 🛑 必须转成字符串:Metabase 的 query/json 会把 >=1000 的**数值**列返回成
    --    带千分位逗号的字符串("72,740"),列按 text 渲染就会原样显示成 72,740。
    --    用户 ID 不是量,不能带千分位。
    CAST(ranked.user_id AS CHAR)                             AS user_id,
    u.country_code                                           AS country_code,
    ranked.purchases                                         AS purchases,
    ROUND(ranked.takehome_usd, 2)                            AS takehome_usd,
    ROUND(100.0 * ranked.takehome_usd
          / NULLIF(ranked.takehome_usd_all_users, 0), 1)     AS pct_of_all_takehome,
    ROUND(COALESCE(cost_by_user.cost_usd, 0), 2)             AS cost_usd,
    ROUND(ranked.takehome_usd - COALESCE(cost_by_user.cost_usd, 0), 2) AS net_usd,
    COALESCE(messages_by_user.user_messages, 0)              AS user_messages,
    messages_by_user.last_message_date                       AS last_message_date,
    DATE(ranked.last_purchase_at)                            AS last_purchase_date,
    COALESCE(cancellations.cancellations, 0)                 AS cancellations
FROM ranked
LEFT JOIN soul_map.user u                ON u.id = ranked.user_id
LEFT JOIN cost_by_user          ON cost_by_user.user_id    = CAST(ranked.user_id AS CHAR) COLLATE utf8mb4_unicode_ci
LEFT JOIN messages_by_user      ON messages_by_user.user_id = CAST(ranked.user_id AS CHAR) COLLATE utf8mb4_unicode_ci
LEFT JOIN cancellations         ON cancellations.user_id    = ranked.user_id
WHERE ranked.spend_rank <= 20
ORDER BY ranked.spend_rank

