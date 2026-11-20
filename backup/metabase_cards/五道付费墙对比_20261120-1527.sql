-- 付费墙_五道墙并排 · Paywall — Triggers Side by Side
--
-- ═══ 🛑 2026-10-27:卡名由「四道墙」改成「五道墙」,SQL 一行没动 ═══
--   本卡从建卡起就是**按 `trigger` 动态分组**、没有白名单,所以第五道墙
--   `first_message_gate` 一出现就自动有行,不需要「加一行」。改的只是卡名和下面这段口径。
--
-- ═══ 🛑 第五道墙 `first_message_gate`:不是 10-22 才有的,是 10-10 之后基本关掉了 ═══
--   实测全量(服务端 `paywall_shown` + `payload->>'$.trigger'='first_message_gate'`):
--     **344 次 / 126 人,最早 2026-10-01 01:49,最后 2026-10-25 00:45**,
--     且 **344 次全部是 `variant='v4'` + `wall='chat'`**(没有别的取值)。
--   逐日:10-01 51次/17人 · 10-02 127次/44人 · 10-08 100次/35人 · 10-09 38次/18人,
--        之后每天只剩 1~5 次;10-22 之后合计只有 **6 次 / 2 人**。
--   ⇒ 🛑 **「目前只有 2 人 6 次」那个数只是「10-22 起」的切片,不是这道墙的全部。**
--     它在 10-01~10-09 有过真实量级,**是后来被关掉了**。读这一行之前先确认它当时开没开,
--     否则会把「关掉了」误读成「没人撞上」。
--   客户端 207 更正过它是什么:**不是「打开 host 就弹」的 V4 组件(那个开关默认关)**,
--     而是两处**发送前拦截**(中东先订阅组 / A 臂 0 额度),**每发一次拦一次**。
--   ⚠️ 客户端建议这一维按「**是否在 `trialFirst=treat` 组**」标,比按「见没见过这道墙」稳 ——
--     那一组人每一次发送都会被拦。**现在还没这么标**,要标得先把分组接进来。
--
-- 2026-10-20 新建。起因:3.7.2 起 `wall='chat'` 里混了**额度硬墙**(message_quota)和
--   **软墙**(quota_soft_wall),「wall='chat' = 撞上额度被挡住」这个老等式不成立了。
--   原来的付费漏斗卡把 wall 当唯一维度,读不出是哪道墙。本卡按 `trigger` 并排拆开。
--
-- 【展示形式】**表格**,一行 = 一天 × 一道墙。三个理由:
--   ① 五道墙的量级差 50 倍(message_quota 2,090 人 vs quota_soft_wall 3 人),画在一张图上看不见小的;
--   ② 每道墙的分母各自独立、每天都在动,比率画成折线会把分母变化藏起来;
--   ③ 要同时读人数和三级比率,折线叠不下。与看板 24 其余各卡一致。
--
-- ═══ 🛑 五个必须知道的口径点 ═══
-- ① `occurred_at` 是 **UTC**(实测:最大值 09:33 而 DB NOW() 是 17:33,差 8 小时)。
--    分天前必须 CONVERT_TZ 到 SGT,否则跨日的会归错天。
-- ② **成交按 `period_type` 拆成「免费试用」和「0.99」两列,不合成一个「付款」** ——
--    10-14 之前全是试用、10-19 之后全是 0.99,合在一起的任何跨期比较都不成立。
--    period_type 不在付费墙事件里,要去 `subscription_event_log` 按 (用户, SGT 日) 对。
-- ③ **一个用户一天可能撞多道墙** ⇒ 各行人数**不能跨 trigger 相加**,合计会重复计人。
-- ④ 🛑 **分母缺两类**:`trigger=sp_locked`(点锁住的照片)和 `sp_vision_quota`(看图额度)
--    **不进服务端这四个事件**,只有客户端 `paywall_viewed` 有。所以本卡不是全部付费入口。
-- ⑤ `quota_soft_wall` 起点 **2026-10-20 17:20**,现在全库只有 3 人。
--    **三天内不要读它的比率** —— 分子<10 读不出。
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑 2026-10-22 修:排序规则 —— 本卡自建卡起就没在 Metabase 里跑通过          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   报错:`Illegal mix of collations (utf8mb4_unicode_ci,IMPLICIT)
--         and (utf8mb4_0900_ai_ci,IMPLICIT) for operation '='`
--
--   **出在 `LEFT JOIN purchase_kind p ON p.user_id = w.user_id` 这一步**:
--     · `soulmap_interaction_event.user_id` 是 VARCHAR,列排序规则 **utf8mb4_0900_ai_ci**
--     · `subscription_event_log.user_id` 是 **INT**,所以要 `CAST(... AS CHAR)`,
--       而 **CAST 出来的排序规则取的是「连接」的默认值,不是表的**
--
--   🛑🛑 **本地复现不出来,别在本地验完就当没事**:
--     用 pymysql 连上去,`collation_connection` 是 utf8mb4_0900_ai_ci,CAST 出来正好对得上,查询照跑;
--     **Metabase 的连接是 utf8mb4_unicode_ci**,CAST 出来就对不上了,报上面那个错。
--     ⇒ 验证办法:连上去先 `SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci`,再跑。
--
--   ⇒ 修法:**把 COLLATE 显式写死**,不依赖连接默认值:
--       `CAST(user_id AS CHAR) COLLATE utf8mb4_0900_ai_ci`
--     GROUP BY 里那一处也要一起改,否则分组键和 SELECT 的不是同一个表达式。
--
--   ⚠️ 这个错以前被看板吞掉了:Metabase 查询出错时返回的是 **HTTP 200 + 一个错误对象**,
--      抓数脚本当成行数组收下,卡上只显示「渲染失败: 0」,看不出到底怎么了。
--      fetch_metabase.py 10-21 已加类型检查,现在会把错误原文打出来。
--
--   ⚠️ 其余 23 张用了 `CAST(... AS CHAR)` 的卡本次抓数**全部成功**,不用跟着改 ——
--      它们没拿 CAST 的结果去比 `soulmap_interaction_event` 这类列排序规则的列。


WITH wall_event AS (             -- 四个付费墙事件,按 (SGT 日, trigger, 用户) 收敛到人
  SELECT DATE(CONVERT_TZ(occurred_at, '+00:00', '+08:00'))          AS d,
         COALESCE(NULLIF(payload ->> '$.trigger', ''), '(无)')       AS trig,
         user_id                                                     AS user_id,
         MAX(event_name = 'paywall_shown')                           AS saw,
         MAX(event_name = 'paywall_subscribe_tapped')                AS tapped,
         MAX(event_name = 'paywall_billing_opened')                  AS opened,
         MAX(event_name = 'paywall_billing_succeeded')               AS succeeded
  FROM soul_map.soulmap_interaction_event
  WHERE event_name IN ('paywall_shown', 'paywall_subscribe_tapped',
                       'paywall_billing_opened', 'paywall_billing_succeeded')
    AND occurred_at >= CURDATE() - INTERVAL 30 DAY
  GROUP BY d, trig, user_id
),
purchase_kind AS (               -- 同一 SGT 日里这个人买的是 0.99 还是免费试用
  -- 🛑 event_at 同样是 UTC,两边都转 SGT 再比,不能一边转一边不转
  SELECT DATE(CONVERT_TZ(event_at, '+00:00', '+08:00'))              AS d,
         -- 🛑 见卡头「排序规则」一节:COLLATE 必须显式写,不能靠连接默认值
         CAST(user_id AS CHAR) COLLATE utf8mb4_0900_ai_ci             AS user_id,
         MAX(period_type = 'INTRO')                                  AS is_intro,
         MAX(period_type = 'TRIAL')                                  AS is_trial
  FROM soul_map.subscription_event_log
  WHERE environment = 'PRODUCTION' AND event_type = 'INITIAL_PURCHASE'
    AND event_at >= CURDATE() - INTERVAL 31 DAY
  GROUP BY d, CAST(user_id AS CHAR) COLLATE utf8mb4_0900_ai_ci
)
SELECT w.d                                                           AS date,
       w.trig                                                        AS trigger_key,
       CASE w.trig WHEN 'launch_prompt'      THEN '启动墙'
                   WHEN 'message_quota'      THEN '额度硬墙'
                   WHEN 'quota_soft_wall'    THEN '软墙(印度·可关)'
                   WHEN 'me_upgrade'         THEN 'Me 页'
                   WHEN 'first_message_gate' THEN '首条消息门'
                   ELSE w.trig END                                   AS trigger_cn,
       COUNT(DISTINCT CASE WHEN w.saw       THEN w.user_id END)      AS shown_users,
       COUNT(DISTINCT CASE WHEN w.tapped    THEN w.user_id END)      AS tapped_users,
       ROUND(COUNT(DISTINCT CASE WHEN w.tapped THEN w.user_id END)
             / NULLIF(COUNT(DISTINCT CASE WHEN w.saw THEN w.user_id END), 0), 4) AS tapped_rate,
       COUNT(DISTINCT CASE WHEN w.opened    THEN w.user_id END)      AS opened_users,
       COUNT(DISTINCT CASE WHEN w.succeeded THEN w.user_id END)      AS succeeded_users,
       -- 成交拆两类(见口径点 ②)
       COUNT(DISTINCT CASE WHEN w.succeeded AND p.is_intro THEN w.user_id END) AS succeeded_intro,
       COUNT(DISTINCT CASE WHEN w.succeeded AND p.is_trial THEN w.user_id END) AS succeeded_trial,
       ROUND(COUNT(DISTINCT CASE WHEN w.succeeded THEN w.user_id END)
             / NULLIF(COUNT(DISTINCT CASE WHEN w.saw THEN w.user_id END), 0), 4) AS succeeded_rate
FROM wall_event AS w
LEFT JOIN purchase_kind AS p ON p.d = w.d AND p.user_id = w.user_id
GROUP BY w.d, w.trig
HAVING shown_users > 0
ORDER BY w.d DESC, shown_users DESC;

