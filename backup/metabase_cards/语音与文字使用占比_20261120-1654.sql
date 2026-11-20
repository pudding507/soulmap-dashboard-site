-- 现状 · 语音与文字各用得多少 · Usage — Voice vs Text Share
-- 【展示形式】表格。一行一天 × 一个国家,按天读趋势。**不画饼图** —— 两个占比的分母不是同一个。
--
-- 2026-10-14 新建。起因:看板 24 三张语音卡测的都不是「谁用得多」——
--   `语音_分桶对照` 只覆盖阿拉伯实验人群;`语音_等待与漏回` 和
--   `语音_播放结果与没出声原因` 的分母本身就是语音。全站占比线上没有卡。
-- 2026-10-14 17:40 改两处:① 滚动窗口 → 钉死在 3.6.0 放量(与看板其余卡一致);
--   ② 空国家标签统一成 `(查不到)` 并处理空串。
--
-- 输出形状:date | country | users | voice_users | voice_user_pct | msgs | voice_msgs | voice_msg_pct
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑 窗口钉死在 `2026-10-08 02:11:00`(安卓 3.6.0 全量放量)                ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   **本看板所有卡都用钉死在切点的固定窗口,没有一张用滚动窗口。**
--   `语音_等待与漏回_服务端` 钉的也是 `2026-10-08`,**两张卡的起点对齐**,可以并排读。
--   🛑 **不要改成滚动窗口**(同 `邀请_被邀请人侧` 那条)——
--      近两周切点密集(10-08 3.6.0 · 10-09 阿语分桶 · 10-10 3.6.1 · 10-12 预算砍半 ·
--      10-13 分桶改又回滚 · 10-14 四件一起上),滚动窗口每天换人群组合且卡面看不出来。
--   ⚠️ 这是按天的卡,所以窗口变长只是**行数变多**,每一行的含义不变。
--
-- ═══ 口径 ═══
--   数据源:`soul_map.soulmap_chat_history`(服务端)。
--   🛑 **不用客户端埋点** —— `host.firebase_event` 缺 2026-10-11 一整天
--      (10-12 的入库作业没跑且不回补),按天读会在那天出现一个**假的坑**。
--      服务端这张表不缺(10-11 当天 1,083 轮语音)。
--      ⚠️ 这也是本卡和 `语音_播放结果与没出声原因_客户端` 的区别:**那张缺 10-11,这张不缺。**
--   只数 `role='user'` 的行 —— 要回答的是「**用户**用语音还是打字」,不是 host 怎么回。
--   `modality` 实测只有 `voice` / `text` 两个取值(另有 2 行为空,已排除)。
--
--   国家用 `geo_country`(真实 IP 归属),**不用 `country`** —— 同 409 第 90 行。
--   🛑 **`soulmap_app_launch` 每次启动写一行,`add_on` 只精确到秒**;同一用户在同一秒
--      可能有多行、`geo_country` 还可以不一样(409 第 85~87 行记过这个坑)。
--      ⇒ 本卡**不 JOIN 取国家**,用 `GROUP BY user_id` 内的 `SUBSTRING_INDEX(GROUP_CONCAT(...))`,
--        **天然一人一行**,不会把一个人算成多个。
--   🛑 取**全时段最早一次启动**的国家,不是窗口内最早的 —— `app_launch` 每次启动都写行,
--      窗口内的 MIN 是「窗口里第一次启动」,不是装机国家。
--
-- ═══ 两个占比不是一回事,分开读 ═══
--   `voice_user_pct`  = 当天发过语音的人 / 当天发过消息的人   ← **有多少人碰语音**
--   `voice_msg_pct`   = 当天的语音消息 / 当天的全部用户消息   ← **语音占了多少量**
--   ⚠️ 两者会差很远:少数重度语音用户能把 `voice_msg_pct` 拉高,而 `voice_user_pct` 不动。
--      **判断「推语音值不值」看前者,判断「语音成本有多大」看后者。**
--
-- ⚠️ 分子小于 10 的格子读不出,不要据它比较国家。
-- ⚠️ 当天未走完 ⇒ **最后一天永远偏低**,不要和前一天直接比。
-- ⚠️ 🛑 **这张卡不能用来谈因果** —— 用不用语音是用户自己选的(**自选择**)。
--    要谈「推用户去语音会怎样」,看 `语音_分桶对照`(随机分桶)那张。
-- ⚠️ `HAVING users >= 5` 与 409 一致;个位数国家的比例全是噪声。

WITH user_country AS (
    -- 🛑 一人一行：GROUP BY 内取首次启动国家，不 JOIN（见上方坑）
    SELECT  l.user_id,
            COALESCE(NULLIF(
                SUBSTRING_INDEX(GROUP_CONCAT(l.geo_country ORDER BY l.add_on), ',', 1),
                ''), '(查不到)')                                              AS country
    FROM    soul_map.soulmap_app_launch l
    WHERE   l.user_id IS NOT NULL AND l.user_id <> ''
    GROUP BY l.user_id
),
daily AS (
    SELECT  DATE(ch.add_on)                                                   AS stat_date,
            ch.user_id,
            COUNT(*)                                                          AS msgs,
            SUM(ch.modality = 'voice')                                        AS voice_msgs
    FROM    soul_map.soulmap_chat_history ch
    WHERE   ch.role = 'user'
      AND   ch.add_on >= '2026-10-08 02:11:00'
      AND   ch.modality IN ('voice', 'text')
    GROUP BY DATE(ch.add_on), ch.user_id
)
SELECT  d.stat_date                                                           AS `date`,
        COALESCE(uc.country, '(查不到)')                                      AS country,
        COUNT(*)                                                              AS users,
        COALESCE(SUM(d.voice_msgs > 0), 0)                                    AS voice_users,
        ROUND(100.0 * SUM(d.voice_msgs > 0) / COUNT(*), 1)                    AS voice_user_pct,
        COALESCE(SUM(d.msgs), 0)                                              AS msgs,
        COALESCE(SUM(d.voice_msgs), 0)                                        AS voice_msgs,
        ROUND(100.0 * SUM(d.voice_msgs) / NULLIF(SUM(d.msgs), 0), 1)          AS voice_msg_pct
FROM        daily d
LEFT JOIN   user_country uc
         ON uc.user_id = d.user_id COLLATE utf8mb4_unicode_ci
GROUP BY    d.stat_date, COALESCE(uc.country, '(查不到)')
HAVING      users >= 5          -- 🛑 与 409 一致；要看全量把这行注释掉
ORDER BY    d.stat_date DESC, users DESC
