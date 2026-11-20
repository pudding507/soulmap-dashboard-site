-- 邀请 · 被邀请人侧(装上并绑定这一段) · Invite — Invitee Side
-- 【展示形式】表格。五行是一条真漏斗,但**最后一行换了数据源**,所以仍逐行读、不画漏斗图。
--
-- 2026-10-14 新建。起因:2026-10-13 报告里这一段整条是错的,更正后线上没有卡。
--
-- 输出形状:seq | step | step_en | source | users | note
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑🛑 `invite_step · referrer` **每次装机都发**,不是「带邀请进来」        ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   2026-10-13 踩过:直接拿 `step='referrer'` 的人数当「带邀请信息启动 App」,
--   报成 759 人。实测它用 `params.result` 区分结果,10-08 起 1,000 人里:
--     `none`           994 人  ← 装机时**没有**带回任何邀请码
--     **`code`           4 人**  ← **真正带回了邀请码**
--     `not_supported`    2 人 · `read_failed` 1 人
--   ⇒ **必须带 `result='code'`**。不带这个条件,这一行等于当期全部装机。
--
-- ═══ 🛑 最后一行来自服务端,和上面四行不是同一个数据源 ═══
--   前四行是客户端埋点(`host.firebase_event`),**缺 2026-10-11 一整天**;
--   「服务端真的绑上」来自 `soul_map.soulmap_invite_binding`,**不缺那天**
--   (10-11 当天有 8 条绑定)。
--   ⇒ **服务端那一行比客户端几行大是正常的**,不是数据矛盾。
--   ⇒ 实测 27 条绑定里 **9 条是用户手动输码**(`redeem` 的 `via='manual'`)、
--      走链接的只有 5 条 —— **深链接基本没工作**,这是这张卡最该看的一行。
--
-- ⚠️ **本卡不出百分比列。** 第 1 行(装机带回了邀请码)只有个位数,拿它当分母会算出
--   125% / 675% 这种数,读的人一眼就会误读。**绝对数本身才是这张卡的结论。**
--   等量上来、分母过得了 10 再加比率列。
-- ⚠️ 分子小于 10 的行读不出,不要据它下结论。
-- ⚠️ 窗口固定从 2026-10-08(开关当天)起,不要改成滚动窗口。
WITH client_steps AS (
  SELECT JSON_UNQUOTE(JSON_EXTRACT(params, '$.step'))   AS step,
         JSON_UNQUOTE(JSON_EXTRACT(params, '$.result')) AS result,
         JSON_UNQUOTE(JSON_EXTRACT(params, '$.via'))    AS via,
         uid
  FROM host.firebase_event
  WHERE event_name = 'invite_step'
    AND event_date >= '20261008'
),
arrived AS (            -- 🛑 必须带 result='code',见卡头
  SELECT COUNT(DISTINCT uid) AS users
  FROM client_steps WHERE step = 'referrer' AND result = 'code'
)
SELECT 1 AS seq, '装机时带回了邀请码'  AS step, 'install carried a code' AS step_en,
       '客户端埋点' AS source,
       (SELECT users FROM arrived) AS users,
       CONCAT('分母，仅 ', (SELECT users FROM arrived), ' 人 ⇒ 下面几行不作比率') AS note
UNION ALL
SELECT 2, '看到确认弹窗', 'saw confirm dialog', '客户端埋点',
       (SELECT COUNT(DISTINCT uid) FROM client_steps WHERE step = 'incoming_shown'), '⚠️ 分子个位数，读不出'
UNION ALL
SELECT 3, '确认绑定', 'confirmed binding', '客户端埋点',
       (SELECT COUNT(DISTINCT uid) FROM client_steps WHERE step = 'incoming_confirm'), '⚠️ 分子个位数，读不出'
UNION ALL
SELECT 4, '客户端记到兑换 · 走链接', 'redeemed via link', '客户端埋点',
       (SELECT COUNT(DISTINCT uid) FROM client_steps WHERE step = 'redeem' AND via = 'referrer'), '⚠️ 分子个位数，读不出'
UNION ALL
SELECT 5, '客户端记到兑换 · 手动输码', 'redeemed by typing code', '客户端埋点',
       (SELECT COUNT(DISTINCT uid) FROM client_steps WHERE step = 'redeem' AND via = 'manual'), '⚠️ 分子个位数，读不出'
UNION ALL
SELECT 6, '服务端真的绑上', 'bound on server', '服务端表(不缺 10-11)',
       (SELECT COUNT(DISTINCT invitee_user_id) FROM soul_map.soulmap_invite_binding), '🔴 其中 9 条靠手动输码，走链接仅 5 条'
ORDER BY seq;

