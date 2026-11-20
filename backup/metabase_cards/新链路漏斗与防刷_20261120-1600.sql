-- 邀请链路漏斗与防刷 · Invite — Funnel and Abuse Guards
--
-- 2026-11-17 新建。WW49 第 3 件「邀请看板」。
--   一张卡覆盖两段:①~⑥ 是邀请漏斗,⑦~⑨ 是防刷判定。
--   窗口从 2026-11-13 16:02 起 —— 新邀请链路的第一条记录,更早的是旧版规则,不并进来。
--
-- 🛑 三个必须知道的口径:
--   1. **`soulmap_invite_send.opened_at` 不是「朋友点开了」** —— 它和 `send_reward` 一样,
--      是邀请人自己点「发送」那一刻就写的。311 条里 302 条非空(97%),拿它当点开率会得出假数。
--      真正的点开只能用 `clicks > 0`,或 `soulmap_invite_click` 表。
--   2. **点开数只从 2026-11-16 18:18 起才可信** —— 落地页 `/g/` 在那之前一直是 404,
--      点击一次也没记下。⇒ 跨 11-16 18:18 比点开率,比的是「有没有在记」不是「有没有人点」。
--   3. 一个人可以建多张卡、一张卡可以发多条 ⇒ **第 1 步和第 2 步之间不是转化关系**,
--      `pct_of_previous` 从第 3 步才开始有意义。
--   4. 🔴 **`soulmap_invite_binding.same_ip` 这一列存的不是同 IP,是同国家**(代码里叫 `sameGeo`,
--      `signals` 里写 `same_geo`)—— 列名起错了,liwen 580(2026-11-17)确认。
--      同国家本来就该占多数,**它不是防刷信号**,别拿它当「同 IP 刷量」读。
--      真正的同 IP 判定在 `user_ip_log`(两个账号登录过完全相同的 IP),不在这张表里。
--
-- 分子 < 10 的步骤一律输出「读不出 / not readable」,不给百分比(全项目口径)。
--
-- 🔴 2026-11-19 修:表名补 `soul_map.` 前缀。
--    这张卡自 11-17 建好起**一次都没抓成功过** —— Metabase 那条连接的默认库是 `di`,
--    不带库前缀就报 `Table 'di.soulmap_invite_card' doesn't exist`,
--    每轮都被记成「留待下轮」,线上一直显示不出来。
--    本地 pymysql 连接指定了 database,所以本地跑得通、Metabase 跑不通,两边不一致。

WITH invite_send_in_window AS (
    SELECT
        link_id,
        card_id,
        inviter_user_id,
        invitee_user_id,
        clicks,
        bound_at,
        joined_at,
        friend_gift
    FROM soul_map.soulmap_invite_send
    WHERE created_at >= '2026-11-13'
),
invite_card_in_window AS (
    SELECT card_id, user_id
    FROM soul_map.soulmap_invite_card
    WHERE created_at >= '2026-11-13'
),
invite_binding_in_window AS (
    SELECT same_device, same_ip, revoked_at
    FROM soul_map.soulmap_invite_binding
    WHERE bound_at >= '2026-11-13'
),
funnel_counts AS (
    SELECT
        (SELECT COUNT(*) FROM invite_card_in_window)                                AS cards_created,
        (SELECT COUNT(*) FROM invite_send_in_window)                                AS invites_sent,
        (SELECT COUNT(*) FROM invite_send_in_window WHERE clicks > 0)               AS invites_clicked,
        (SELECT COUNT(*) FROM invite_send_in_window WHERE bound_at IS NOT NULL)     AS friends_bound,
        (SELECT COUNT(*) FROM invite_send_in_window WHERE joined_at IS NOT NULL)    AS friends_started_chatting,
        (SELECT COUNT(*) FROM invite_send_in_window WHERE friend_gift > 0)          AS rewards_to_friend,
        (SELECT COUNT(*) FROM invite_binding_in_window)                             AS bindings_total,
        (SELECT COUNT(*) FROM invite_binding_in_window WHERE same_ip = 1)           AS bindings_same_ip,
        (SELECT COUNT(*) FROM invite_binding_in_window WHERE same_device = 1)       AS bindings_same_device,
        (SELECT COUNT(*) FROM invite_binding_in_window WHERE revoked_at IS NOT NULL) AS bindings_revoked
    FROM DUAL
),
funnel_steps AS (
    SELECT 1 AS step_no,
           '① 建了邀请卡 / Cards created'                   AS step_name,
           cards_created                                     AS step_count,
           NULL                                              AS previous_count,
           '一个人可以建多张卡'                               AS step_note
    FROM funnel_counts
    UNION ALL
    SELECT 2, '② 发出邀请 / Invites sent',
           invites_sent, NULL,
           '一张卡可发多条 ⇒ 与①不是转化关系'
    FROM funnel_counts
    UNION ALL
    SELECT 3, '③ 朋友点开了链接 / Opened by friend',
           invites_clicked, invites_sent,
           '只从 11-16 18:18 起可信(此前落地页 404)。不要用 opened_at'
    FROM funnel_counts
    UNION ALL
    SELECT 4, '④ 朋友绑定 / Friend bound',
           friends_bound, invites_clicked,
           '绑定即给朋友 30 条'
    FROM funnel_counts
    UNION ALL
    SELECT 5, '⑤ 朋友开始聊 / Friend started chatting',
           friends_started_chatting, friends_bound,
           '邀请人要等到这一步才拿到 30 条'
    FROM funnel_counts
    UNION ALL
    SELECT 6, '⑥ 朋友侧奖励已发 / Reward granted to friend',
           rewards_to_friend, friends_bound,
           ''
    FROM funnel_counts
    UNION ALL
    SELECT 7, '⑦ 防刷:绑定总数 / Guard: bindings',
           bindings_total, NULL,
           '以下三行的分母'
    FROM funnel_counts
    UNION ALL
    SELECT 8, '⑧ 同国家的绑定 / Same country (NOT same IP)',
           bindings_same_ip, bindings_total,
           '列名叫 same_ip,存的其实是同国家(代码里是 sameGeo)。不是防刷信号'
    FROM funnel_counts
    UNION ALL
    SELECT 9, '⑨ 防刷:同一台机器 / Guard: same device',
           bindings_same_device, bindings_total,
           ''
    FROM funnel_counts
    UNION ALL
    SELECT 10, '⑩ 防刷:已撤销 / Guard: revoked',
           bindings_revoked, bindings_total,
           ''
    FROM funnel_counts
)
SELECT
    step_no,
    step_name,
    step_count,
    CASE
        WHEN previous_count IS NULL OR previous_count = 0 THEN NULL
        -- 0 是确定的事实(一条都没有),照常给 0.0%;只有 1~9 这种小分子才不给率
        WHEN step_count BETWEEN 1 AND 9 THEN NULL
        ELSE ROUND(100.0 * step_count / previous_count, 1)
    END AS pct_of_previous,
    CASE
        WHEN previous_count IS NULL OR previous_count = 0 THEN ''
        WHEN step_count BETWEEN 1 AND 9 THEN CONCAT(step_count, ' / ', previous_count, ' · 读不出(分子<10)')
        ELSE CONCAT(step_count, ' / ', previous_count)
    END AS numerator_over_denominator,
    step_note
FROM funnel_steps
ORDER BY step_no;

