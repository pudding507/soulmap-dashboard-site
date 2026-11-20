-- 软墙转化 · India Soft Wall
-- 【展示形式】**表格**。一行 = 一天 × 第几次弹(第10条 / 第20条)。
--   不画折线:要并排读「曝光 / 关掉 / 点订阅 / 开收银台 / 成交 / 失败」六个口径,
--   而且两档弹窗要对比,折线表达不了。
--
-- 2026-10-22 新建。起因:**软墙已经是第三大付费入口**(近 3 天 paywall_shown 按 trigger:
--   启动墙 1,476 次 / 额度硬墙 1,293 次 / **软墙 378 次 225 人** / me_upgrade 112 次),
--   但 10-20 17:18 刚开那天实测 10 次曝光全被关掉、0 人点订阅,停留中位数约 2.3 秒。
--   量起来了,必须看它到底转不转化。
--
-- **软墙是什么**:印度非会员聊到**第 10、20 条**时弹的**可关掉**的 Plus 弹窗,
--   照常有回复、关掉继续聊、不出邀请第二屏。只给安卓 **build ≥ 211(3.7.2)**。
--
-- 输出形状:date | soft_wall_index | shown_events | shown_devices | dismissed
--          | dismiss_rate_pct | sub_tapped | sheet_opened | completed | failed
--
-- ═══ 🔴 2026-10-28 提速 + 修一个 bug(两件同一个根因)═══
--   **症状**:10-28 全量抓数这张卡 **504 网关超时**,看板上是空的。实测 **102.6s**。
--   **根因**:`attributed` 的 last-touch 归因用的是**相关子查询** ——
--     `s.ts = (SELECT MAX(s2.ts) FROM soft_wall_shown s2 WHERE s2.device_id = d.device_id
--              AND s2.ts <= d.ts)`
--     每条下游事件都要回头把曝光表扫一遍。
--   **改法**:曝光流和下游流 UNION 成一条按时间排的流,用
--     `SUM(is_shown) OVER (PARTITION BY device_id ORDER BY ts, is_shown DESC
--                          ROWS UNBOUNDED PRECEDING)`
--     给每行打上「这是该设备第几次曝光之后的事」,再按 (设备, 第几次) 挂回去。
--     ⏱ **102.6s → 1.3s**。
--   **顺带修好的 bug**:原版 2026-10-24「第10条」**曝光 80、关掉 81、关掉率 101.3%** ——
--     同一微秒上有两条曝光时,相关子查询会把同一条下游事件**归给两条曝光**、重复计数。
--     窗口函数版每条下游只属于一个 (设备, 第几次),天然不会重复。
--     ⇒ 新版 关掉 79、98.8%。
--   **验证**:两版 16 行、键集合完全相同,**128 个格子只差 2 格**,就是上面这个 bug。
--   🛑 和卡 437 是**同一类问题**(相关子查询 → 窗口函数,53s → 13.8s)。
--      以后看到「每行回头扫一遍另一张表」的写法,先怀疑这个。
--      ⚠️ 但**别当成通则** —— 437 那次先试过「子查询改 JOIN」,53.0s → 53.4s,**没有用**;
--         真正起作用的是**消掉逐行重扫**,不是换个写法。
--
-- ═══ 🛑 本卡的去留:保留,用来做前后对比(2026-10-28 定)═══
--   倡议书 §二 建议「**印度软墙在今天的新版本里直接用能量系统的内联首充卡替换**」
--   (₹49 = 1,000 能量)。替换之后软墙的曝光会归零。
--   **决定:本卡不摘牌**,留着看替换前后的差 —— 旧机制 3 天 244 次曝光 / 成交 0,
--   新机制至少要比这个好,没有本卡就没有基线。
--   🛑 **替换的具体时点现在还没定**(倡议书是给 Javier 的建议,能量系统进的是 3.9.0)。
--      确认之后**三处都要记上日期**,否则前后对比会把两套机制混在同一行里:
--      ① 这里的卡头 ② `render_dashboard.py` 的 `CUTOVERS` ③ 台账 §2.0 切点总表。
--   🛑 起点 `event_date >= '20261020'` 是**固定起点,不是滚动窗口** ——
--      前后对比要的就是全历史,**不要为了提速改成 CURDATE() - INTERVAL N DAY**。
--
-- ═══ 🛑 为什么必须走 Firebase,不能用服务端 ═══
--   `soft_wall_index`(1 = 第 10 条 / 2 = 第 20 条)**只挂在客户端 `paywall_viewed` 上**。
--   实测服务端 `soulmap_interaction_event.paywall_shown` 的 payload **没有这个参数**,
--   只有 `trigger='quota_soft_wall'`。⇒ 要拆两次弹窗只能用 `host.firebase_event`(**T+1**)。
--   (已请服务端补,见跨团队 167。)
--
-- ═══ 🛑🛑 三个会静默出错的坑(2026-10-22 实测,与需求文档正文不符,以实测为准)═══
--   ① **`soft_wall_index` 取出来是 `'1.0'` / `'2.0'`,不是 `'1'` / `'2'`** —— JSON 里存的是浮点。
--      写 `params->>'$.soft_wall_index' = '1'` 会**一行都匹配不到,而且不报错**。
--      ⇒ 必须 `CAST(... AS UNSIGNED)`。
--   ② **下游四个事件现在一个都没带 `soft_wall_index`**。需求文档说 3.8.0(10-22 起)
--      给 paywall_dismissed / purchase_started / billing_sheet_opened / purchase_failed
--      也加了,但**实测近 3 天全是 NULL**。⇒ **四个下游事件全部走 last-touch 归因**,
--      不是只有 purchase_completed 需要。(purchase_completed 确实没有,Firebase 25 参数上限。)
--   ③ **`event_timestamp` 是微秒 epoch,列类型是 `mediumtext`** —— 比较前必须
--      `CAST(... AS UNSIGNED)`,否则按**字符串**比大小,**结果是错的且不报错**。
--
-- ═══ 🛑 关掉率怎么算 ═══
--   实测 `dismiss_method` 近 3 天六个值:x 168 · backdrop 35 · android_back 22 · swipe 14
--   · storekit_cancelled 3 · unknown 2。
--   · **`superseded`(被硬墙顶掉,不是用户关的)目前一条都没有**,但 3.8.0 会开始写,
--     所以这里先排掉 —— 现在是空操作,以后自动生效。10-22 之前这种记成 `unknown`。
--   · **`storekit_cancelled` 也排掉** —— 那是在收银台取消付款,**不是「关掉软墙」**,
--     算进主动关掉率会虚高。
--
-- ═══ 🛑 两个不能相加的地方 ═══
--   · **index 行的设备数不能相加当去重人数** —— 同一天同一设备可能先后撞到第 10 条和第 20 条。
--     要合计请另算,不要把两行的 shown_devices 加起来。
--   · **两边先各自聚合再拼**(见 agg_shown / agg_down)。直接 LEFT JOIN 之后 COUNT(*)
--     会被下游事件放大 —— 一次曝光可能对应多条下游。
--
-- ⚠️ `event_date` 是 **YYYYMMDD 的字符串**,用 '%Y-%m-%d' 去比恒为真,要用 '%Y%m%d'。
-- ⚠️ firebase 是 **T+1 入库**,最后一天天然偏低。
-- ⚠️ 起点 **2026-10-20 17:18**(服务端 447 确认生效),再往前没有软墙。
--
-- ═══ 验收 ═══
--   能分开看第 10 条和第 20 条两次弹窗的转化。
--   **2026-10-22 实测近 3 天:曝光 244 次(第10条 150 / 第20条 94)→ 244 次全被关掉
--   → 3 人点订阅 → 3 人开收银台 → 3 人付款失败 → 成交 0。**
--   曝光数和关掉数**精确相等**,关掉率 100%。

WITH soft_wall_shown AS (                 -- 软墙曝光,只有这个事件带 soft_wall_index
  SELECT e.event_date                                            AS event_date,
         e.user_pseudo_id                                        AS device_id,
         CAST(e.event_timestamp AS UNSIGNED)                     AS ts,
         CAST(e.params ->> '$.soft_wall_index' AS UNSIGNED)      AS soft_wall_index
  FROM host.firebase_event AS e
  WHERE e.event_name = 'paywall_viewed'
    AND e.event_date >= '20261020'
    AND e.params ->> '$.trigger' = 'quota_soft_wall'
),
downstream AS (                           -- 下游事件,一律不带 index,靠 last-touch 归因
  SELECT e.event_name                                            AS event_name,
         e.user_pseudo_id                                        AS device_id,
         CAST(e.event_timestamp AS UNSIGNED)                     AS ts,
         e.params ->> '$.dismiss_method'                         AS dismiss_method
  FROM host.firebase_event AS e
  WHERE e.event_name IN ('paywall_dismissed', 'purchase_started',
                         'billing_sheet_opened', 'purchase_completed', 'purchase_failed')
    AND e.event_date >= '20261020'
    AND e.params ->> '$.trigger' = 'quota_soft_wall'
),
stream AS (                               -- 曝光和下游事件并成一条按时间排的流
  SELECT device_id, ts, 1 AS is_shown, event_date, soft_wall_index,
         NULL AS event_name, NULL AS dismiss_method
  FROM soft_wall_shown
  UNION ALL
  SELECT device_id, ts, 0, NULL, NULL, event_name, dismiss_method
  FROM downstream
),
grouped AS (                              -- 每行记「它前面(含自己)已经发生过几次曝光」
  -- 🛑 `ORDER BY ts, is_shown DESC`:同一微秒上曝光排在下游前面,
  --    与原版 `s.ts <= d.ts`(同刻归给这次曝光)语义一致。
  SELECT device_id, ts, is_shown, event_date, soft_wall_index, event_name, dismiss_method,
         SUM(is_shown) OVER (PARTITION BY device_id ORDER BY ts, is_shown DESC
                             ROWS UNBOUNDED PRECEDING)          AS touch_no
  FROM stream
),
anchor AS (                               -- 每个 (设备, 第几次曝光) 的那条曝光是哪天、哪一档
  SELECT device_id, touch_no,
         MAX(CASE WHEN is_shown = 1 THEN event_date END)        AS event_date,
         MAX(CASE WHEN is_shown = 1 THEN soft_wall_index END)   AS soft_wall_index
  FROM grouped WHERE touch_no > 0
  GROUP BY device_id, touch_no
),
attributed AS (                           -- 下游事件挂到它所属的那次曝光上(last-touch)
  -- touch_no = 0 表示这条下游事件发生在该设备任何一次软墙曝光之前 ⇒ 归不上,丢弃
  -- (原版用 `s.ts <= d.ts` 的 JOIN 也会把这种丢掉,行为一致)
  SELECT a.event_date                                           AS event_date,
         a.soft_wall_index                                      AS soft_wall_index,
         g.event_name                                           AS event_name,
         g.dismiss_method                                       AS dismiss_method
  FROM grouped AS g
  JOIN anchor AS a
    ON a.device_id = g.device_id AND a.touch_no = g.touch_no
  WHERE g.is_shown = 0 AND g.touch_no > 0
),
agg_shown AS (
  SELECT event_date                                              AS event_date,
         soft_wall_index                                         AS soft_wall_index,
         COUNT(*)                                                AS shown_events,
         COUNT(DISTINCT device_id)                               AS shown_devices
  FROM soft_wall_shown GROUP BY event_date, soft_wall_index
),
agg_down AS (
  SELECT event_date                                              AS event_date,
         soft_wall_index                                         AS soft_wall_index,
         -- 🛑 主动关掉:排掉 superseded(被硬墙顶掉)和 storekit_cancelled(收银台取消)
         SUM(event_name = 'paywall_dismissed'
             AND COALESCE(dismiss_method, '') NOT IN ('superseded', 'storekit_cancelled'))
                                                                 AS dismissed,
         SUM(event_name = 'purchase_started')                    AS sub_tapped,
         SUM(event_name = 'billing_sheet_opened')                AS sheet_opened,
         SUM(event_name = 'purchase_completed')                  AS completed,
         SUM(event_name = 'purchase_failed')                     AS failed
  FROM attributed GROUP BY event_date, soft_wall_index
)
SELECT STR_TO_DATE(s.event_date, '%Y%m%d')                       AS date,
       CASE s.soft_wall_index WHEN 1 THEN '1 · 第10条'
                              WHEN 2 THEN '2 · 第20条'
                              ELSE CONCAT('9 · 未知(', COALESCE(s.soft_wall_index, 'null'), ')')
       END                                                       AS soft_wall_index,
       s.shown_events                                            AS shown_events,
       s.shown_devices                                           AS shown_devices,
       COALESCE(a.dismissed, 0)                                  AS dismissed,
       ROUND(100.0 * COALESCE(a.dismissed, 0) / NULLIF(s.shown_events, 0), 1) AS dismiss_rate_pct,
       COALESCE(a.sub_tapped, 0)                                 AS sub_tapped,
       COALESCE(a.sheet_opened, 0)                               AS sheet_opened,
       COALESCE(a.completed, 0)                                  AS completed,
       COALESCE(a.failed, 0)                                     AS failed
FROM agg_shown AS s
LEFT JOIN agg_down AS a
       ON a.event_date = s.event_date AND a.soft_wall_index <=> s.soft_wall_index
ORDER BY date DESC, soft_wall_index;

