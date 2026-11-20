-- 邀请 · 30 条消息奖励的发放 · Invite — 30-Message Bonus Grants
-- 【展示形式】表格。四行(两个规则版本 × 两侧)，一行一个独立口子、**不是漏斗**，不要画图。
--   量级是个位到二十几，趋势图没有意义；要读的是 granted_pct 和 lag_p50_min 两列。
--
-- 2026-10-16 新建。起因：`413 邀请_奖励发放` 读的是 `soulmap_invite_reward_grant`
--   (会员月奖励，带 kind / month_index)，**30 条消息奖励不在那张表里**，看板上一直读不到。
--
-- 输出形状：seq | policy_version | side | side_en | bindings | granted | granted_pct
--           | lag_p50_min | lag_max_min | invitee_sent_msg | sandbox_invitee | note
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑🛑 30 条记在 `invitee_bonus_at` / `inviter_bonus_at`，**不看 reward_state** ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   实测 47 条绑定里 `reward_state` 只有 **NONE 44 · LOCKED 2 · PENDING 1**，
--   而 `invitee_bonus_at` 非空的有 **21 条**。两者对不上 ——
--   `reward_state` 跟踪的是会员月那条线，**不是 30 条消息**。
--   ⇒ 判断「发没发 30 条」只能看两个 `*_bonus_at` 时间列是否非空。
--
-- ═══ 🛑 两个版本是两套行为，必须按 policy_version 分开看 ═══
--   · **被邀请人侧**：**v1 一条都不发**(0 / 26)，**v2 全发**(21 / 21)，
--     且 bound_at → invitee_bonus_at **全部为 0 分钟**（绑定当时即发）。
--     ⇒ 🛑 **「v1 漏发」这个说法不成立** —— v1 没有被邀请人侧奖励，这是 v2 新增的功能。
--   · **邀请人侧**：v1 2/26 · v2 8/21。
--     **v2 的 8 条基本也是即时的** —— 实测延迟为 0/0/1/1/2/3/20/2933 分钟，
--     **7 条在 20 分钟内**，只有 1 条 2933 分钟是离群。
--     **v1 那 2 条分别延迟 2847 / 4525 分钟**，发放时刻是 10-14 21:38 与 10-15 01:35 ——
--     **都落在 v2 上线之后**，形态像是 v2 上线时对历史绑定的一次补发。
--
--   🛑 **所以不要把邀请人侧概括成「延迟发放」** —— 按发放日分组去算平均延迟会得出
--      「10~25 小时」这种数，那是被 v1 的补发行和一条 v2 离群行拉出来的。
--      **按版本看中位数，v2 两侧都接近即时。**
--   ⇒ 本卡同时出 `lag_p50_min` 与 `lag_max_min` 两列，就是为了让这个长尾显形；
--     **只看其中一列都会读错。**
--
-- ═══ 🛑 邀请人侧的发放条件尚未完全确定 ═══
--   实测拿到奖励的 10 条，被邀请人 **10/10 都发过消息、且发放时刻全部在首条消息之后**；
--   **但没拿到的 37 条里有 21 条被邀请人也发过消息**。
--   ⇒ 「被邀请人发出第一条消息」是**必要条件，但不充分**。
--   ⇒ 本卡出 `invitee_sent_msg` 一列，就是为了让「发过消息却仍未发放」这批显形。
--     **不要据此把它当成已确认的触发规则。**
--
-- ═══ 🛑 沙盒：不删行，单独标出来(同 413 的做法)═══
--   实测 3 个**被邀请人**是沙盒账号(邀请人侧 0 个)。
--   删了之后和服务端自己的计数对不上，读的人会以为我们漏发。
--   ⇒ 出 `sandbox_invitee` 一列，让人看见每组里有几条是测试触发的。
--
-- ═══ 口径 ═══
--   `bound_at` / `invitee_bonus_at` / `inviter_bonus_at` **都是 SGT**
--   (实测最晚绑定与最晚被邀请人发放同为 2026-10-16 14:23:58，同一时区)。
--   🛑 和 `subscription_event_log.event_at` 不同 —— 那一张是 UTC，跨表比较要 CONVERT_TZ。
--   🛑 跨表 join 必须显式 COLLATE：本表三个 id 列是 `utf8mb4_0900_ai_ci`，
--      `soulmap_chat_history.user_id` 是 `utf8mb4_unicode_ci`，不写会报 1267。
--
--   `lag_p50_min` 用的是**中位数**，写法与 `415 语音_等待与漏回_服务端` 一致
--   (`AVG(CASE WHEN rn IN (FLOOR((cnt+1)/2), FLOOR((cnt+2)/2)) THEN x END)`)，
--   **不用均值** —— 发放延迟是长尾的，均值会被个别很晚的行拉走。
--
-- ⚠️ 窗口固定从 **2026-10-08**(邀请开关打开当天)起，**不要改成滚动窗口**
--   (同 411 / 412 / 413)。开关之前没有这个功能。
-- ⚠️ **邀请人侧两个版本的分子都 < 10**(v1 2 · v2 8)，`granted_pct` 这一列读不出，
--   `note` 已标。**不要据它比较两个版本的邀请人侧发放率。**
-- ⚠️ 全部来自服务端表，**不缺 2026-10-11**(客户端埋点缺的那一天)。

WITH b AS (
    SELECT  bd.id,
            COALESCE(NULLIF(bd.policy_version, ''), '(空)')  AS policy_version,
            bd.bound_at,
            bd.invitee_bonus_at,
            bd.inviter_bonus_at,
            bd.invitee_user_id,
            -- 🛑 沙盒只能从 subscription_event_log.environment 判（同 413）；
            --    soul_map.subscription 没有 environment 列。
            CASE WHEN sb.user_id IS NOT NULL THEN 1 ELSE 0 END AS invitee_is_sandbox,
            -- 被邀请人发过消息没有（用于显形「发了却没发放」，见卡头）
            CASE WHEN EXISTS (
                     SELECT 1 FROM soul_map.soulmap_chat_history ch
                     WHERE ch.user_id = bd.invitee_user_id COLLATE utf8mb4_unicode_ci
                       AND ch.role = 'user')
                 THEN 1 ELSE 0 END                          AS invitee_sent_msg
    FROM        soul_map.soulmap_invite_binding AS bd
    LEFT JOIN  (SELECT DISTINCT user_id
                FROM soul_map.subscription_event_log
                WHERE environment = 'SANDBOX') AS sb
            ON sb.user_id = bd.invitee_user_id COLLATE utf8mb4_0900_ai_ci
    WHERE       bd.bound_at >= '2026-10-08'
),
-- 一行一个 版本 × 侧，lag 只在「已发放」的行上算
lagged AS (
    SELECT  policy_version, side, lag_min,
            ROW_NUMBER() OVER (PARTITION BY policy_version, side ORDER BY lag_min) AS rn,
            COUNT(*)     OVER (PARTITION BY policy_version, side)                  AS cnt
    FROM (
        SELECT policy_version, 'invitee' AS side,
               TIMESTAMPDIFF(MINUTE, bound_at, invitee_bonus_at) AS lag_min
        FROM b WHERE invitee_bonus_at IS NOT NULL
        UNION ALL
        SELECT policy_version, 'inviter',
               TIMESTAMPDIFF(MINUTE, bound_at, inviter_bonus_at)
        FROM b WHERE inviter_bonus_at IS NOT NULL
    ) AS x
),
lag_stat AS (
    SELECT  policy_version, side,
            -- 中位数写法同 415，不用均值
            ROUND(AVG(CASE WHEN rn IN (FLOOR((cnt + 1) / 2), FLOOR((cnt + 2) / 2))
                           THEN lag_min END), 0)            AS lag_p50_min,
            MAX(lag_min)                                    AS lag_max_min
    FROM    lagged
    GROUP BY policy_version, side
),
agg AS (
    SELECT  policy_version, 1 AS seq_side, 'invitee' AS side,
            COUNT(*)                                        AS bindings,
            SUM(invitee_bonus_at IS NOT NULL)               AS granted,
            SUM(invitee_sent_msg)                           AS invitee_sent_msg,
            SUM(invitee_is_sandbox)                         AS sandbox_invitee
    FROM    b GROUP BY policy_version
    UNION ALL
    SELECT  policy_version, 2, 'inviter',
            COUNT(*),
            SUM(inviter_bonus_at IS NOT NULL),
            SUM(invitee_sent_msg),
            SUM(invitee_is_sandbox)
    FROM    b GROUP BY policy_version
)
SELECT  ROW_NUMBER() OVER (ORDER BY a.policy_version, a.seq_side)  AS seq,
        a.policy_version                                           AS policy_version,
        CASE a.side WHEN 'invitee' THEN '被邀请人侧'
                    ELSE                '邀请人侧'  END             AS side,
        a.side                                                     AS side_en,
        a.bindings                                                 AS bindings,
        a.granted                                                  AS granted,
        ROUND(100.0 * a.granted / NULLIF(a.bindings, 0), 1)        AS granted_pct,
        ls.lag_p50_min                                             AS lag_p50_min,
        ls.lag_max_min                                             AS lag_max_min,
        a.invitee_sent_msg                                         AS invitee_sent_msg,
        a.sandbox_invitee                                          AS sandbox_invitee,
        CASE
          WHEN a.side = 'invitee' AND a.granted = 0
            THEN '该版本没有被邀请人侧奖励，不是漏发'
          WHEN a.side = 'invitee'
            THEN CONCAT('绑定当时即发；分子 ', a.granted,
                        CASE WHEN a.granted < 10 THEN '<10，pct 读不出' ELSE '' END)
          WHEN a.granted < 10
            THEN CONCAT('分子 ', a.granted, '<10，pct 读不出；p50 与 max 要一起看')
          ELSE '发放条件未完全确定，见卡头'
        END                                                        AS note
FROM        agg      AS a
LEFT JOIN   lag_stat AS ls
         ON ls.policy_version = a.policy_version AND ls.side = a.side
ORDER BY    a.policy_version, a.seq_side

