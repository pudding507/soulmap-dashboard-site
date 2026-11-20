-- 🔴 2026-11-04:A/B 类不再把**用户自建角色**算进去(产品判断,2026-11-04 定)。
--    用户自建角色(`roster_batch='user-created'`、`review_status='draft'`)的 `character_type`
--    也是 `fictional`,原来会整批落进 B 类。现在**单独成一类「用户自建」**。
--    🛑 它们不是异常数据,所以不并进「未分类」——单列一行,可见但不混入 A/B。
--    实测影响(10-19 用户自建角色上线至今):**B 类人数 −9.7%、消息 −4.7%;A 类完全不受影响**。
--    🛑 **跨 2026-10-19 比 B 类的任何比率会出现台阶。**
--    🛑 判据用 `review_status` / `roster_batch`,新增别的 draft 批次会落进「(未上线)」而不是 A/B。
-- 沉默提醒按档位与角色类型 · Silence Nudge by Ladder & Character Class
-- 【展示形式】**表格**。一行 = 一天 × 一个档位 × A/B 类。
--   不画折线:要并排读「尝试 / 实发 / 四种拒绝原因」六个口径,折线表达不了;
--   而且这张卡是看 10-22 切点前后的结构变化,不是看单条趋势。
--
-- 2026-10-22 新建。起因:**10-21 18:19 服务端上线、10-22 算法侧打开**,B 类沉默提醒
--   现在能走到 3h 档。原来的问题:下一档按「这段沉默里已发成功几条」决定
--   (0 → 3m、1 → 3h、2 → 24h),而 **B 类在 3m 被算法拒了 ⇒ 计数还是 0 ⇒
--   窗口一过再也选不中,永远到不了 3h**。
--   ⇒ **推送量会从 10-22 起跳涨**,而现有「推送发送与送达」那张卡不分档位,看不出这件事。
--   开关:`nudge.ladder.type_b_advance_on_decline`(sys_config,缺省开)。
--
-- 输出形状:date | tier | char_class | attempts | sent_n | sent_pct
--          | declined_empty | declined_quiet_hours | declined_no_timezone | declined_non200
--
-- ═══ 🛑 口径陷阱 ═══
--   ① **「尝试」和「实发」必须分成两列**。算法侧打开之前,B 类的 3h 行全是 `declined_empty`
--      —— **不是没触发,是触发了被拒**。只看实发会以为功能根本没上。
--   ② **拒绝原因有五个值,不止 `declined_empty`**。实测近 21 天:
--        declined_empty 13,641 · declined_quiet_hours 6,827 · sent 1,093
--        · declined_no_timezone 680 · declined_non200 46
--      **`declined_quiet_hours`(夜间静默)量是第二大,拆原因必须带上它。**
--   ③ **实发率天然到不了 100%** —— 夜间静默、10% 对照组、每日上限照旧生效。
--      这张卡的实发率是「结构占比」,**不是健康度指标,低不等于坏**。
--   ④ **`pushed` 这一列不要用** —— 实测它和 `outcome='sent'` 完全等价(pushed=1 ⇔ sent),
--      两个都放会让人以为是两个口径。本卡只用 outcome。
--   ⑤ **`created_at` 是 SGT**(实测 MAX(created_at) 与 DB 的 NOW() 同分钟),
--      和 subscription_event_log.event_at 那种 UTC 列不是一回事,**这里不要 CONVERT_TZ**。
--
-- ═══ 🛑 A/B 类怎么判,以及这里为什么必须写 COLLATE ═══
--   A 类 = `soulmap_host_info.character_type = 'realistic'`;B 类 = `'fictional'`。
--   口径与「Chat_character type AB funnel」那张卡一致。⚠️ `host_type='ai_expert'` **不是** A 类。
--   join 键是 **`host_key`**(不是 `host_id`,host_info 里没有这个列名),
--   而 nudge 日志里的 host_id 带 `original:` 前缀,要 REPLACE 掉。
--
--   🛑 **`soulmap_host_info` 整表是 `utf8mb4_unicode_ci`,和库里其它表的 `utf8mb4_0900_ai_ci`
--      不一样**,所以这个 join **必须显式 COLLATE**,否则报
--      `Illegal mix of collations ... for operation '='`。
--   🛑 **COLLATE 要加在 `REPLACE(...)` 这一侧,不能加在 `h.host_key` 上** ——
--      加在列上会把列变成表达式、索引失效(卡 409 就是这么慢了 51.7 秒的)。
--
-- ═══ 验收 ═══
--   10-22 起 B 类的 `3h` 档 **attempts 明显上升**;
--   打开前后 B 类 3m 的 `declined_empty` 占比应该掉下来。

SELECT DATE(n.created_at)                                          AS date,
       n.tier                                                      AS tier,
      CASE WHEN h.roster_batch  = 'user-created'  THEN '用户自建'
           WHEN h.review_status <> 'approved'     THEN '(未上线)'
           WHEN h.character_type = 'realistic'    THEN 'A 类 Realistic'
           WHEN h.character_type = 'fictional'    THEN 'B 类 Fictional'
           ELSE '(查不到角色)' END                  AS char_class,
       COUNT(*)                                                    AS attempts,
       SUM(n.outcome = 'sent')                                     AS sent_n,
       ROUND(100.0 * SUM(n.outcome = 'sent') / COUNT(*), 1)        AS sent_pct,
       SUM(n.outcome = 'declined_empty')                           AS declined_empty,
       SUM(n.outcome = 'declined_quiet_hours')                     AS declined_quiet_hours,
       SUM(n.outcome = 'declined_no_timezone')                     AS declined_no_timezone,
       SUM(n.outcome = 'declined_non200')                          AS declined_non200
FROM soul_map.soulmap_silence_nudge_log AS n
LEFT JOIN soul_map.soulmap_host_info AS h
       -- 🛑 COLLATE 加在这一侧,见卡头「A/B 类怎么判」
       ON h.host_key = REPLACE(n.host_id, 'original:', '') COLLATE utf8mb4_unicode_ci
WHERE n.created_at >= CURDATE() - INTERVAL 21 DAY
GROUP BY date, n.tier, char_class
-- 档位按 3m → 3h → 24h 的自然阅读序,不按字母序(字母序会排成 24h/3h/3m)
ORDER BY date DESC, FIELD(n.tier, '3m', '3h', '24h'), char_class;

