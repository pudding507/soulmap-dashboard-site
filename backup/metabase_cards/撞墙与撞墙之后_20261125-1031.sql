-- ── 2026-11-20:取数窗口改成滚动 30 天(原来是写死 2026-09-30,已 51 天)──────────────
--   全看板统一规则:**取数窗口最多 30 天**。写死的起点会随时间越拖越长,
--   抓数越来越慢 —— 「等待与漏回」就是这么从 26s 涨到 60s 抓数超时的。
--   🛑 这条规则**只管取数窗口**。实验起点、版本放量切点、人群定义
--      (如 `HAVING MIN(related_at) >= '2026-09-11'`)和留给回访判定的成熟期
--      **都不在此列**,它们改了会动口径。
--
-- 🔴 2026-11-12:CityPLX 由「剔掉」改成「并列一栏」。
--    改了什么:`excluded_users` 不再剔 CityPLX(只剔 9 个测试 / 沙盒号),
--    改为多输出一列 `app_line`(CityPLX / SoulMap),并进 GROUP BY。
--    **两条线相加 = 改之前的「全部」**,但改前只有 SoulMap ⇒ 🛑 **改前改后不可直接比**。
--    🛑 实测 CityPLX 用户在本卡依赖的表里**目前 0 行**(能量五表与订阅表全是 0),
--       所以这一列现在只会出现 SoulMap;这是口径统一,不是漏数。
-- 🔴 2026-11-03:加「能量用完卡」这一路 —— 本卡原来只数 `chat_wall_blocked`,
--    那是**旧免费额度制**的事件;能量系统 2026-10-28 14:32:20 上线后,
--    走能量的用户用完能量时弹的是「用完卡」,**不会**再发 `chat_wall_blocked`。
--    实测近十天 `chat_wall_blocked` 的人数已经从 125/天 腰斩到 50/天,
--    同期 `soulmap_energy_offer_event` 的 `shown` 从 0 涨到 2,626 次 / 366 人。
--    ⇒ **不加这一路,这张卡会随着用户迁移慢慢归零,而看不出是机制换了还是真的没人撞墙。**
--
--    【怎么加的】加一列 `wall_kind`,一行 = 一天 × 墙的种类:
--      `① 免费额度墙` = `soulmap_interaction_event.chat_wall_blocked`(旧制)
--      `② 能量用完卡` = `soulmap_energy_offer_event` 里 `action='shown'`(新制)
--    🛑 **两行绝不能相加** —— 同一个人在迁移前后可能两边都出现过,而且分母不是同一批人。
--    🛑 下游三列(看到付费墙 / 点订阅 / 扣款成功)**两路用同一套事件**,所以可比;
--       另加一列 `买了能量`(`action='accepted'`,24 小时内),这一列**只有能量那一路有值**。
--    🔴 剔除补齐:原卡只剔了 CityPLX,现按全项目统一名单再剔 9 个测试 / 沙盒号。
--    🛑 `soulmap_interaction_event.user_id` 是 `utf8mb4_0900_ai_ci`、两张能量表是
--       `utf8mb4_unicode_ci`,UNION 两侧不显式 COLLATE 会直接报 1271。全部统一到 unicode_ci。
--
-- 额度墙 · 撞墙与撞墙之后(服务端) · Quota Wall — Blocked & What Happens Next (Server)
-- 【展示形式】**表格**。三个理由:
--   ① 要同时读「撞墙人数」和它下游三级的比率,折线叠不下;
--   ② 看板 24 其余各卡全是表格,保持一致;
--   ③ 比率画成折线会把**分母的变化藏起来** —— 撞墙人数本身每天在动。
--
-- 2026-10-16 新建。起因:`403 付费墙实验_免费额度线` 卡头写着
--   「目前**没有一个能直接数「撞墙人数」的字段**,只能看 total 的上界。已挂给客户端。」
--   —— 这句现在已经过时:服务端 `soulmap_interaction_event` 的 `chat_wall_blocked`
--   就是这个字段,且**一天不缺**。
--
-- 输出形状:d | blocked_users | blocked_events | events_per_user
--           | saw_paywall_24h | saw_paywall_pct | tapped_sub_24h | tapped_sub_pct
--           | billing_done_24h | note
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑 为什么走服务端,不走客户端埋点                                          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   `403` / `396` 认撞墙用的是客户端 `host.firebase_event` 的
--   `paywall_viewed` + `source='plus_sheet'` + `trigger='message_quota'`。
--   **那张表本周缺天** —— 实测 `paywall_viewed` 在 **2026-10-11 与 10-16 没有任何行**,
--   而同期服务端 `chat_wall_blocked` 两天都有(10-11 238 人 · 10-16 137 人)。
--   ⇒ 本卡全部走服务端,**9-30 至今 17 天一天不缺**。
--   ⇒ 🛑 **本卡与 403 / 396 的数不会相等**,两边都没错,是数据源不同。要对比请先对齐源。
--
-- ═══ 🛑 下游三级是「撞墙后 24 小时内」,不是「当天内」═══
--   撞墙发生在 23:50、订阅点在次日 00:10 是常见情形,按自然日切会把它算丢。
--   ⇒ 统一用 **撞墙时刻起 24 小时**,跨日也接得住。
--   ⚠️ **代价:当天最后几小时撞墙的人窗口还没走完**,最后一行的下游三列**会偏低**,
--      `note` 已标。**不要拿最后一行做趋势判断。**
--
-- ═══ 🛑 「看到付费墙」不等于「撞墙触发的那次」═══
--   付费墙有三个入口(`message_quota` 额度墙 / `launch_prompt` 启动墙 / `me_upgrade` Me 页)。
--   本卡的 `saw_paywall_24h` 统计的是**撞墙之后 24 小时内看到过任意一次付费墙**,
--   里面可能混着启动墙。实测撞墙后看到付费墙的比例在 98% 上下,
--   **这一列是用来确认「撞墙 → 墙」这段衔接没断,不是用来做归因的。**
--
-- ═══ 口径 ═══
--   窗口钉死 **2026-09-30**(`chat_wall_blocked` 最早有数据那天),**不要改成滚动窗口**
--   —— 同本看板其余各卡的做法(`417` 卡头列了每张卡的切点)。
--   `created_at` 是 SGT。本卡不读 `subscription_event_log`,所以不涉及 UTC 换算。
--   去重口径:`blocked_users` 是当日**去重用户**,`blocked_events` 是条数,两者分列。
--   🛑 **比率一律以当日 `blocked_users` 为分母**,不以上一级为分母 —— 三级是并列的观察,
--      不是嵌套漏斗(同 `411` 卡头那条)。
--
-- ⚠️ **分子 < 10 的格子读不出**,不要据它下结论或比较日期。
-- ⚠️ 已排除另一个产品的账号(`user.app_source = 'city'`)。

WITH excluded_users AS (     -- 🔴 2026-11-12:只剔测试 / 沙盒号;CityPLX 改成并列一栏
    SELECT id FROM soul_map.`user`
    WHERE id IN (62412, 72048, 72382, 72462, 74640,   -- 测试号
                 74377, 74592, 71693, 71826)          -- 商店沙盒号
),
app_line_of_user AS (        -- 🔴 2026-11-12:CityPLX 与 SoulMap 分开记
    SELECT CAST(id AS CHAR) COLLATE utf8mb4_unicode_ci                 AS user_id,
           CASE WHEN app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line
    FROM   soul_map.`user`
),
blocked AS (
    -- ① 旧制:免费额度墙
    SELECT  ie.user_id COLLATE utf8mb4_unicode_ci       AS user_id,
            '① 免费额度墙 Free-quota wall'               AS wall_kind,
            ie.created_at                               AS blocked_at,
            DATE(ie.created_at)                         AS d,
            ROW_NUMBER() OVER (PARTITION BY ie.user_id, DATE(ie.created_at)
                               ORDER BY ie.created_at)  AS rn_in_day
    FROM        soul_map.soulmap_interaction_event AS ie
    WHERE       ie.event_name = 'chat_wall_blocked'
            AND ie.created_at >= CURDATE() - INTERVAL 30 DAY
            AND CAST(ie.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
    UNION ALL
    -- ② 新制:能量用完卡(能量系统 2026-10-28 14:32:20 上线)
    SELECT  oe.user_id COLLATE utf8mb4_unicode_ci       AS user_id,
            '② 能量用完卡 Energy out-of-credit'          AS wall_kind,
            oe.created_at                               AS blocked_at,
            DATE(oe.created_at)                         AS d,
            ROW_NUMBER() OVER (PARTITION BY oe.user_id, DATE(oe.created_at)
                               ORDER BY oe.created_at)  AS rn_in_day
    FROM        soul_map.soulmap_energy_offer_event AS oe
    WHERE       oe.action = 'shown'
            AND oe.created_at >= '2026-10-28 14:32:20'
            AND CAST(oe.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
),
first_block AS (
    SELECT user_id, wall_kind, d, blocked_at FROM blocked WHERE rn_in_day = 1
),
nxt AS (
    SELECT  fb.user_id, fb.wall_kind, fb.d,
            MAX(ie.event_name = 'paywall_shown')             AS saw_paywall,
            MAX(ie.event_name = 'paywall_subscribe_tapped')  AS tapped_sub,
            MAX(ie.event_name = 'paywall_billing_succeeded') AS billing_done
    FROM        first_block AS fb
    LEFT JOIN   soul_map.soulmap_interaction_event AS ie
             ON ie.user_id COLLATE utf8mb4_unicode_ci = fb.user_id
            AND ie.created_at >= fb.blocked_at
            AND ie.created_at <  fb.blocked_at + INTERVAL 24 HOUR
            AND ie.event_name IN ('paywall_shown','paywall_subscribe_tapped',
                                  'paywall_billing_succeeded')
    GROUP BY    fb.user_id, fb.wall_kind, fb.d
),
bought AS (                       -- 24 小时内真的买了能量(只有能量那一路会有)
    SELECT  fb.user_id, fb.wall_kind, fb.d,
            MAX(oe.action = 'accepted') AS bought_energy
    FROM        first_block AS fb
    LEFT JOIN   soul_map.soulmap_energy_offer_event AS oe
             ON oe.user_id    = fb.user_id
            AND oe.action     = 'accepted'
            AND oe.created_at >= fb.blocked_at
            AND oe.created_at <  fb.blocked_at + INTERVAL 24 HOUR
    GROUP BY    fb.user_id, fb.wall_kind, fb.d
),
ev AS (
    SELECT wall_kind, d, COUNT(*) AS blocked_events FROM blocked GROUP BY wall_kind, d
)
SELECT  fb.d                                                            AS d,
        app_line_of_user.app_line                                       AS app_line,
        fb.wall_kind                                                    AS wall_kind,
        COUNT(DISTINCT fb.user_id)                                      AS blocked_users,
        MAX(ev.blocked_events)                                          AS blocked_events,
        ROUND(MAX(ev.blocked_events) / NULLIF(COUNT(DISTINCT fb.user_id), 0), 2)
                                                                        AS events_per_user,
        COUNT(DISTINCT CASE WHEN n.saw_paywall   THEN fb.user_id END)   AS saw_paywall_24h,
        ROUND(100.0 * COUNT(DISTINCT CASE WHEN n.saw_paywall THEN fb.user_id END)
                    / NULLIF(COUNT(DISTINCT fb.user_id), 0), 1)         AS saw_paywall_pct,
        COUNT(DISTINCT CASE WHEN n.tapped_sub    THEN fb.user_id END)   AS tapped_sub_24h,
        ROUND(100.0 * COUNT(DISTINCT CASE WHEN n.tapped_sub THEN fb.user_id END)
                    / NULLIF(COUNT(DISTINCT fb.user_id), 0), 1)         AS tapped_sub_pct,
        COUNT(DISTINCT CASE WHEN n.billing_done  THEN fb.user_id END)   AS billing_done_24h,
        COUNT(DISTINCT CASE WHEN b.bought_energy THEN fb.user_id END)   AS bought_energy_24h,
        CASE WHEN fb.d >= DATE(NOW() - INTERVAL 24 HOUR)
                  THEN '🛑 24 小时窗口未走完，下游各列偏低，不要做趋势判断'
             WHEN COUNT(DISTINCT CASE WHEN n.tapped_sub THEN fb.user_id END) < 10
                  THEN '点订阅分子<10，该格读不出'
             ELSE '' END                                                AS note
FROM        first_block AS fb
JOIN        app_line_of_user ON app_line_of_user.user_id = fb.user_id
LEFT JOIN   nxt    AS n ON n.user_id = fb.user_id AND n.d = fb.d AND n.wall_kind = fb.wall_kind
LEFT JOIN   bought AS b ON b.user_id = fb.user_id AND b.d = fb.d AND b.wall_kind = fb.wall_kind
LEFT JOIN   ev          ON ev.d      = fb.d       AND ev.wall_kind = fb.wall_kind
GROUP BY    fb.d, app_line_of_user.app_line, fb.wall_kind
ORDER BY    fb.d DESC, fb.wall_kind
