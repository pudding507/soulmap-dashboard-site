-- 能力漏斗 · 按能力一行 · 宽表
-- 🐞 2026-09-08 修一处会在看板上显得像坏了的缺陷:**5 个能力的历史送达率算出 >100%**
--    (star_conversation 3260.9% · discover_feed 2837.8% · first_message 2777.0% ·
--     expert_discovery 1000.0% · expert_recommendation 125.2%)。
--    根因:**不是所有能力都走 `surfaced` 这一阶段。** 实测 first_message 在 08-19 前的分布是
--      candidate 7,878 → selected 7,878 → delivered 7,609,而 surfaced 只有 274(仅 1 天有)。
--    ⇒ `delivered / surfaced` 假设 surfaced 是通用分母,对这批能力不成立,比值是垃圾数。
--    处理:`delivered_pre > surfaced_pre` 时 **送达率输出 NULL**(不可计算),
--    同时 `readability` 新增一档 `surfaced_underreported` —— **让「不可计算」显式可见,
--    而不是留一个空格让人以为是没数据**。
--    ⚠️ 本卡未改动 surfaced 的用法本身;若要给这批能力算送达率,需先确认它们的入口阶段
--    (candidate 还是 selected),那是算法侧才知道的事。
-- 输出形状:一个 capability 一行,列里同时给「近期活跃度」「历史送达率」「现在还能不能测」
-- 源:soul_map.soulmap_capability_funnel_daily（服务端 V87 日汇总表，已回填到 2026-07-29）
--
-- ⚠️ 2026-09-02 新建。与 `Capability_funnel 30d` 的分工:
--     30d          长表,一行一个 (日 × 能力 × 分组 × 阶段),给筛选和透视用
--     本卡（宽表）  一行一个能力,给「一眼看出哪个能力该关注」用
--
-- ══════════════════════════════════════════════════════════════════════════
-- 🛑 为什么把「送达率」拆成两段,而不是给一个数
-- ══════════════════════════════════════════════════════════════════════════
-- 2026-08-19 起约 34 个 capability 停止上报 `delivered` / `replied`,
-- 而 `surfaced` 一点没掉(3.1 万 ~ 5.5 万/天)。
-- ⇒ **这是「送出去这件事不再被记录」,不是「东西送不出去了」。**
--
-- 如果只给一个「近 30 天送达率」,那批断掉的能力会全部显示成接近 0 ——
-- 数据侧就是这么栽的:用 14 天窗口(整个落在断点后)把 `small_treat` 读成「送达率 2.1%」
-- 并写进文档当作砍功能的依据,而它断点前是**连续 20 天 100%**。
--
-- ⇒ 本卡把它拆成三列,让「测不到」和「真的低」在表上长得不一样:
--     delivery_rate_before_0819  08-19 之前的历史基线  —— 这才是产品事实
--     delivered_7d               现在还有没有在报      —— 0 = 测不到,不是产品坏了
--     readability                上面两列的结论        —— 直接给判断,不让人自己推
--
--   readability 的四个取值:
--     readable                   近 7 天仍在报 delivered,可以正常读
--     unmeasurable_since_0819    断点前报过、之后归零 —— **测不到,不是产品变差**
--     never_reported_delivered   从来没报过 delivered,与本次断点无关
--     no_traffic_7d              近 7 天没有 surfaced,能力本身没在跑
--
-- ⚠️ **readability = unmeasurable_since_0819 的那些,不要拿
--    delivery_rate_before_0819 去做当期决策** —— 那是 8 月中旬的事实,不代表今天。
--    它只用来判断「这个能力历史上健康吗」。
--
-- ══════════════════════════════════════════════════════════════════════════
-- 🔒 冻结口径
-- ══════════════════════════════════════════════════════════════════════════
--   五层:candidate → selected / suppressed → surfaced → delivered
--                  → opened / dismissed / replied → accepted / completed / expired / failed
--   `suppressed` 是 `selected` 的**兄弟不是下游**,不并入任何一层。
--   `unknown` 是「没测到」不是「测了、是零」,单列不进分母。
--
-- ⚠️ 用 `interventions` 不用 `events` 算比率 —— 同一次干预可能发多个事件。
-- ⚠️ 本卡不按 arm / interaction_mode 拆:`observation` 占 99.5%、
--    `interaction_mode` 八成是 unknown(该字段 08-28 才开始写),拆了得不到信息。
--    要拆请用 `Capability_funnel 30d` 那张长表。
WITH src AS (
  SELECT * FROM soul_map.soulmap_capability_funnel_daily
  WHERE log_date >= CURDATE() - INTERVAL 30 DAY
    AND log_date <  CURDATE()
),
per_cap AS (
  SELECT capability,
         -- 近 7 天:现在还活不活跃
         SUM(CASE WHEN log_date >= CURDATE() - INTERVAL 7 DAY
                   AND stage = 'surfaced'  THEN interventions ELSE 0 END) AS surfaced_7d,
         SUM(CASE WHEN log_date >= CURDATE() - INTERVAL 7 DAY
                   AND stage = 'delivered' THEN interventions ELSE 0 END) AS delivered_7d,
         SUM(CASE WHEN log_date >= CURDATE() - INTERVAL 7 DAY
                   AND stage = 'unknown'   THEN interventions ELSE 0 END) AS unknown_7d,
         -- 断点前:历史基线
         SUM(CASE WHEN log_date < '2026-08-19'
                   AND stage = 'surfaced'  THEN interventions ELSE 0 END) AS surfaced_pre,
         SUM(CASE WHEN log_date < '2026-08-19'
                   AND stage = 'delivered' THEN interventions ELSE 0 END) AS delivered_pre,
         -- 用户侧反应(同样受断点影响,一并给出以便对照)
         SUM(CASE WHEN log_date < '2026-08-19'
                   AND stage = 'replied'   THEN interventions ELSE 0 END) AS replied_pre
  FROM src
  GROUP BY capability
),
top_reason AS (            -- 每个能力 unknown 里占比最大的那个原因
  SELECT capability, reason, rn FROM (
    SELECT capability,
           COALESCE(NULLIF(reason, ''), '(未给原因)') AS reason,
           ROW_NUMBER() OVER (PARTITION BY capability
                              ORDER BY SUM(interventions) DESC) AS rn
    FROM src WHERE stage = 'unknown'
    GROUP BY capability, reason) x
  WHERE rn = 1
)
SELECT p.capability                                        AS capability,
       p.surfaced_7d                                       AS surfaced_7d,
       p.delivered_7d                                      AS delivered_7d,
       p.unknown_7d                                        AS unknown_7d,
       COALESCE(r.reason, '')                              AS unknown_top_reason,
       p.surfaced_pre                                      AS surfaced_before_0819,
       p.delivered_pre                                     AS delivered_before_0819,
       CASE WHEN p.surfaced_pre = 0                  THEN NULL
            WHEN p.delivered_pre > p.surfaced_pre    THEN NULL   -- 见头部:该能力不走 surfaced,比值无意义
            ELSE ROUND(100 * p.delivered_pre / p.surfaced_pre, 1) END
                                                           AS delivery_rate_before_0819,
       CASE WHEN p.delivered_pre = 0 THEN NULL
            ELSE ROUND(100 * p.replied_pre / p.delivered_pre, 1) END
                                                           AS reply_rate_before_0819,
       CASE
         WHEN p.delivered_pre > p.surfaced_pre THEN 'surfaced_underreported'
         WHEN p.surfaced_7d  = 0  THEN 'no_traffic_7d'
         WHEN p.delivered_7d > 0  THEN 'readable'
         WHEN p.delivered_pre > 0 THEN 'unmeasurable_since_0819'
         ELSE                          'never_reported_delivered'
       END                                                 AS readability
FROM per_cap p
LEFT JOIN top_reason r ON r.capability = p.capability
ORDER BY p.surfaced_7d DESC, p.surfaced_pre DESC;

