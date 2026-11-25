-- 能量 · 全公司逐日毛利 · Energy — Company Margin Daily
--
-- 2026-11-18 新建。计划第 6 节看板「全公司毛利」。
--   一行一天:成交笔数 · 标价 · 到手 · 服务成本(拆聊天 / 语音 / 其它)· 毛利 · 毛利率。
--
-- 🛑 四个口径:
--   1. **毛利 = 到手收入 − 服务成本,不含广告花费、不含人力。** 它只回答「这些对话本身赚不赚」。
--   2. 到手 = `price_usd × takehome_percentage`(现固定 0.85)。
--   3. 成本是 `soulmap_cost_call` 全部五个组件,**11-06 12:28~13:56 才全部开始记**(口径 24.21)
--      ⇒ 11-05 及更早的成本是偏低的,那几天的毛利率会虚高。
--   4. 当天没有任何成交的日子也出一行(收入 0、毛利为负的成本额),不跳过 ——
--      跳过会让毛利率的趋势看起来比实际好。
--
-- 🔴 实测 11-12~11-18 七天里有六天毛利为负,只有 11-16 是正的(+36.6%)。
--    这是现价下的基线,D-594 要改的就是这个。

WITH revenue_daily AS (
    SELECT DATE(event_at) AS activity_date,
           SUM(price_usd)                                   AS gross_usd,
           SUM(price_usd * COALESCE(takehome_percentage, 0)) AS takehome_usd,
           COUNT(*)                                          AS purchases,
           COUNT(DISTINCT user_id)                           AS paying_users
    FROM soul_map.subscription_event_log
    WHERE environment = 'PRODUCTION'
      AND event_type IN ('NON_RENEWING_PURCHASE','INITIAL_PURCHASE','RENEWAL')
      AND price_usd > 0
      AND event_at >= CURRENT_DATE - INTERVAL 20 DAY
    GROUP BY activity_date
),
cost_daily AS (
    SELECT DATE(call_at) AS activity_date,
           SUM(usd)                                                        AS cost_usd,
           SUM(CASE WHEN cost_column = 'chat_llm'      THEN usd ELSE 0 END) AS cost_chat_usd,
           SUM(CASE WHEN cost_column IN ('voice_message','voice_call') THEN usd ELSE 0 END) AS cost_voice_usd,
           SUM(CASE WHEN cost_column IN ('chat_regen','host_create')   THEN usd ELSE 0 END) AS cost_other_usd
    FROM soul_map.soulmap_cost_call
    WHERE status = 'ok'
      AND call_at >= CURRENT_DATE - INTERVAL 20 DAY
    GROUP BY activity_date
)
SELECT
    COALESCE(revenue_daily.activity_date, cost_daily.activity_date) AS activity_date,
    COALESCE(revenue_daily.purchases, 0)                            AS purchases,
    COALESCE(revenue_daily.paying_users, 0)                         AS paying_users,
    ROUND(COALESCE(revenue_daily.gross_usd, 0), 2)                  AS gross_usd,
    ROUND(COALESCE(revenue_daily.takehome_usd, 0), 2)               AS takehome_usd,
    ROUND(COALESCE(cost_daily.cost_usd, 0), 2)                      AS cost_usd,
    ROUND(COALESCE(cost_daily.cost_chat_usd, 0), 2)                 AS cost_chat_usd,
    ROUND(COALESCE(cost_daily.cost_voice_usd, 0), 2)                AS cost_voice_usd,
    ROUND(COALESCE(cost_daily.cost_other_usd, 0), 2)                AS cost_other_usd,
    ROUND(COALESCE(revenue_daily.takehome_usd, 0)
          - COALESCE(cost_daily.cost_usd, 0), 2)                    AS margin_usd,
    CASE WHEN COALESCE(revenue_daily.takehome_usd, 0) <= 0 THEN NULL
         ELSE ROUND(100.0 * (revenue_daily.takehome_usd - COALESCE(cost_daily.cost_usd, 0))
                    / revenue_daily.takehome_usd, 1) END            AS margin_pct
FROM revenue_daily
LEFT JOIN cost_daily ON cost_daily.activity_date = revenue_daily.activity_date
UNION
SELECT cost_daily.activity_date, 0, 0, 0, 0,
       ROUND(cost_daily.cost_usd, 2), ROUND(cost_daily.cost_chat_usd, 2),
       ROUND(cost_daily.cost_voice_usd, 2), ROUND(cost_daily.cost_other_usd, 2),
       ROUND(-cost_daily.cost_usd, 2), NULL
FROM cost_daily
LEFT JOIN revenue_daily ON revenue_daily.activity_date = cost_daily.activity_date
WHERE revenue_daily.activity_date IS NULL
ORDER BY activity_date DESC

