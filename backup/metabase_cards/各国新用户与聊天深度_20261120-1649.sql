-- 现状 · 各国的新用户与聊天深度 · Snapshot — New Users & Depth by Country
-- 【展示形式】表格。一行一个国家,按新用户数倒序。
--
-- 2026-10-14 新建。起因:看板 24 是「experiment」主题,大盘现状线上没有卡 ——
--   409 的 `new_users` 是唯一的大盘口,但它只接到试用/付费/取消,没有聊天深度。
-- 2026-10-14 17:40 改四处(与看板既有卡对齐,详见下方「与其它卡的一致性」):
--   ① 滚动窗口 → 钉死在 3.6.0 放量;② HAVING 20 → 5;
--   ③ 空国家标签统一成 `(查不到)` 并处理空串;④ 补上 409 那条样本同质性警告。
--
-- 输出形状:country | new_users | engaged_gt3 | engaged_gt3_pct | engaged_ge10 | engaged_ge10_pct
--           | deep_ge20 | deep_ge20_pct | returned_denom | returned | returned_pct
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑 窗口钉死在 `2026-10-08 02:11:00`(安卓 3.6.0 全量放量)                ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   **本看板所有卡都用钉死在切点的固定窗口,没有一张用滚动窗口** ——
--   402 钉 09-23;403/404/406/407/408/409/410 钉 `2026-09-25 01:54`(付费墙实验开始);
--   `语音_等待与漏回_服务端` 钉 `2026-10-08`;邀请三张钉 `20261008`(开关当天)。
--   ⇒ 本卡取 **3.6.0 全量放量**那一刻:在它之后装机的人**都在同一个客户端上**。
--
--   🛑 **不要改成滚动窗口**(同 `邀请_被邀请人侧` 里那条)。理由:
--   近两周切点密集 —— 10-08 3.6.0 · 10-09 17:02 阿语分桶 · 10-10 00:36 3.6.1 ·
--   10-12 预算 S$270→S$100 · 10-13 分桶改又回滚 · 10-14 四件一起上。
--   滚动窗口**每天都在换人群组合,而且卡面上看不出来** ——
--   上周的截图和这周的截图不是同一件事。
--
--   ⚠️ **代价:这是「自 3.6.0 起累计」,不是「最近 N 天」。** 窗口每天变长,
--      首日指标会越来越像长期均值。要看「最近几天」请用每日例行 R1。
--
-- ═══ 口径(定义与 R1 一致,**窗口不同**)═══
--   新用户   = **首次启动后 24 小时内发过至少 1 条消息**的人
--   入戏 >3  = 首日消息数 > 3   ｜ 入戏 ≥10 = ≥ 10   ｜ 聊深 ≥20 = ≥ 20
--   回来     = 首开后第 24~48 小时之间又发了消息
--   🛑 **定义和 `战情室/每日例行_R1R3/run.py` 逐条一致,但 R1 用的是滚动近 10 天。**
--      ⇒ **本卡的数不会等于当天 R1 的数**,两边都没错,是窗口不同。改定义要两边一起改。
--
-- 🛑 **「聊深」的原定义(聊满免费条数)已失效** —— 免费条数按国家和实验不同
--    (非印度 10 条、印度 20 条,10-06 17:16:35 之前非印度是 5 条),
--    同一张表里对不同的人不是同一件事。**这里出固定门槛 ≥20 条**,可跨国家跨实验比较。
--
-- 🛑 **`returned` 的分母是 `returned_denom`,不是 `new_users`** ——
--    它只含**装机 +2 天已满**的队列,所以一定比 `new_users` 小。**这是刻意的,不是漏数。**
--    分母单独出一列,就是为了避免有人拿 `new_users` 去除(同 409 把分母写进表头的做法)。
--
-- ═══ 与其它卡的一致性(改之前踩过的)═══
--   国家用 `geo_country`(真实 IP 归属),**不用 `country`** —— 同 409 第 90 行。
--   🛑 **`soulmap_app_launch` 每次启动写一行,`add_on` 只精确到秒**;同一用户在同一秒
--      可能有多行,且这些行的 `geo_country` 可以不一样。409 第 85~87 行记过这个坑:
--      直接 `JOIN ... ON add_on = MIN(add_on)` 会让一个用户匹配到多行、按国家分组被算成多个人。
--      ⇒ 本卡**不用 JOIN 取国家**,改用 `GROUP BY user_id` 内的
--        `SUBSTRING_INDEX(GROUP_CONCAT(... ORDER BY add_on), ',', 1)`,**天然一人一行**。
--   空国家标签统一写 `(查不到)`(同 409),并且 `NULLIF(...,'')` 把空串也接住。
--   `HAVING new_users >= 5` 与 409 一致。
--
-- ⚠️ **`HAVING new_users >= 5` 会随窗口变长滤掉越来越少的行**,而 409 那条警告反过来也成立:
--    **跨 10-12(预算 S$270→S$100)的前后不是同质样本** —— 国别构成已经变了,
--    这张卡是累计值,**不要拿它做前后对比**,要比请按国家分层并自己切段。
-- ⚠️ 分子小于 10 的格子读不出,**不要据它排名国家**。
-- ⚠️ 「入戏 >3」各国通常都在 70~85%,**没有区分度** —— 比国家看 `engaged_ge10` 和 `deep_ge20`。

WITH first_launch AS (
    -- 🛑 一人一行：用 GROUP BY 内的 SUBSTRING_INDEX 取首次启动国家，不 JOIN（见上方坑）
    SELECT  l.user_id,
            MIN(l.add_on)                                                         AS first_at,
            COALESCE(NULLIF(
                SUBSTRING_INDEX(GROUP_CONCAT(l.geo_country ORDER BY l.add_on), ',', 1),
                ''), '(查不到)')                                                  AS country
    FROM    soul_map.soulmap_app_launch l
    WHERE   l.user_id IS NOT NULL AND l.user_id <> ''
    GROUP BY l.user_id
    HAVING  MIN(l.add_on) >= '2026-10-08 02:11:00'
),
msg AS (
    SELECT  f.user_id, f.country, f.first_at,
            SUM(ch.add_on <  f.first_at + INTERVAL 24 HOUR)                       AS day0_msgs,
            SUM(ch.add_on >= f.first_at + INTERVAL 24 HOUR
            AND ch.add_on <  f.first_at + INTERVAL 48 HOUR)                       AS day1_msgs
    FROM        first_launch f
    JOIN        soul_map.soulmap_chat_history ch
             ON ch.user_id = f.user_id COLLATE utf8mb4_unicode_ci
            AND ch.role    = 'user'
            AND ch.add_on >= f.first_at
            AND ch.add_on <  f.first_at + INTERVAL 48 HOUR
    GROUP BY    f.user_id, f.country, f.first_at
)
SELECT  country,
        COUNT(*)                                                                  AS new_users,
        COALESCE(SUM(day0_msgs >  3), 0)                                          AS engaged_gt3,
        ROUND(100.0 * SUM(day0_msgs >  3) / COUNT(*), 1)                          AS engaged_gt3_pct,
        COALESCE(SUM(day0_msgs >= 10), 0)                                         AS engaged_ge10,
        ROUND(100.0 * SUM(day0_msgs >= 10) / COUNT(*), 1)                         AS engaged_ge10_pct,
        COALESCE(SUM(day0_msgs >= 20), 0)                                         AS deep_ge20,
        ROUND(100.0 * SUM(day0_msgs >= 20) / COUNT(*), 1)                         AS deep_ge20_pct,
        -- 🛑 分母换成「装机 +2 天已满」的队列，单独出一列，避免有人拿 new_users 去除
        COALESCE(SUM(first_at < DATE_SUB(NOW(), INTERVAL 48 HOUR)), 0)            AS returned_denom,
        COALESCE(SUM(first_at < DATE_SUB(NOW(), INTERVAL 48 HOUR)
                 AND day1_msgs > 0), 0)                                           AS returned,
        ROUND(100.0 * SUM(first_at < DATE_SUB(NOW(), INTERVAL 48 HOUR) AND day1_msgs > 0)
                    / NULLIF(SUM(first_at < DATE_SUB(NOW(), INTERVAL 48 HOUR)), 0), 1)
                                                                                  AS returned_pct
FROM        msg
WHERE       day0_msgs >= 1
GROUP BY    country
HAVING      new_users >= 5      -- 🛑 与 409 一致；要看全量把这行注释掉
ORDER BY    new_users DESC
