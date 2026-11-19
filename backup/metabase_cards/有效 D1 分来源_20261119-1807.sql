-- 留存_有效D1与投入率下滑定位 · Retention — Effective D1 & Engagement Drop Diagnosis
--
-- 2026-11-19 改写:**只改执行方式,口径、输出列、行数一字未改**。
--   为什么:这张卡在 Metabase 上稳定超 60 秒网关线(实测 65.1 秒),每天都抓不到、
--   页面上一直沿用旧值。
--   改了三处:① behaviour 的两个相关子查询 → 一次 LEFT JOIN + 条件聚合;
--            ② 末尾六段 `FROM base` 的 UNION ALL → base CROSS JOIN 六行维度表(CTE 只算一次);
--            ③ attr 去掉多余的自连接。
--   效果:65.1 秒 → 38.6 秒(-41%),**423 行逐行比对完全一致**。
--   🛑 改写时踩到的坑:LEFT JOIN 之后,一条消息都没有的人聚合出 NULL 而不是 0,
--      整组人都没发过消息的格子(HK、PS、「(查不到版本)」)会从 0 变成空白。
--      已用 COALESCE 补回 —— 本项目「0 就是 0」。
--
-- 2026-10-22 新建。对应 Michael 10-21 看板反馈 P0 第三项、第六节第 2 条。
--
-- ═══ 🛑 这张卡要回答的问题 ═══
--   有效 D1 从 10-13/14 的 13~14% 掉到 10-18~20 的 5.5~7.6%,是哪一段掉的?
--   **实测结论(2026-10-22,已固化进本卡)**:
--     · **不是分母被异常装机撑大** —— 分子(次日发消息)从 32~34 到 22~33 基本不动,
--       是分母从 240 涨到 436。10-13/14 那个 13~14% 的高点是**那两天注册只有 240 人**造成的。
--     · **不是流量质量** —— 三个付费来源各自腰斩(Facebook 8.8→4.9、AudienceNet 8.9→4.3、
--       Instagram 14.0→10.4),而**自然量只从 6.3 掉到 5.4**。如果是买来的量变差,自然量不该跟着掉。
--   ⇒ 本卡把四个维度固化下来逐日盯:来源 / 国家 / 客户端版本 / 能否看到 0.99。
--
-- ═══ 🛑 六个口径要点 ═══
-- ① **分母是「当天注册的账号」(D-151),不是装机设备**。和 `374 有效留存D1` 同源,
--    两张卡的 overall 行应该对得上。**不要用 first_open 设备数当分母** ——
--    10-17 起有大批设备拿不到 uid、根本进不了 `soul_map.user`(见 OPPO/Realme 那条)。
-- ② 2026-11-12 起 CityPLX 不再剔除,改成 `按业务线 / app_line` 一个维度并列(D-563)。
--    近 21 天注册里 CityPLX 占 3,610 / 11,014,**它的 D1 常年不到 1%**,
--    混在 overall 里会把整体压低 ⇒ 读趋势切到 `app_line` 看 SoulMap 那一行。
-- ③ 「有效 D1」= 次日**自己发过消息**(chat_history.role='user'),不是打开 App。
-- ④ 「投入率」= 首日发 ≥5 条。🛑 门槛是 **≥5**,和北极星的「>3 条」**不是一回事**,
--    Michael 反馈第二节第 2 条点过;沿用 `373 新用户投入率` 的门槛以便对照。
-- ⑤ **客户端版本取自服务端 `soulmap_interaction_event.build`**,不是 firebase ——
--    实测覆盖率 **93.4%**(5,695/6,097),而且比 join firebase(1,077 万行)快一个量级。
--    🛑 覆盖不到的那 6.6% 归入 `(查不到版本)`,**不要当成老版本**。
-- ⑥ 🛑 **最后一天的 D1 必然偏低甚至为 0** —— 次日还没过完。读最后一行先看这条。
-- ⑦ 🔴 **实测发现:`(查不到版本)` 那一组每天 18~35 人,D1 和投入率全是 0.0%** ——
--    他们在 `soul_map.user` 里有账号,但在 `soulmap_interaction_event` 里一条记录都没有,
--    也一条消息都没发过。**这批人会把 overall 的两个比率一起拉低**,
--    读 overall 之前先看这一组有多大。原因未查明(2026-10-22)。
--
-- 【展示形式】**表格**,一行 = 一天 × 一个维度值(长表,同 `374 有效留存D1` 的形态)。四个理由:
--   ① 四个维度要能独立切换,宽表放不下;
--   ② 每个维度值的分母各自独立且每天在动,比率画成折线会把分母藏起来;
--   ③ 要同时读「有效 D1」和「投入率」两个指标,折线叠不下;
--   ④ 分子经常是个位数,画成图会让人读出不存在的差异。
WITH new_user AS (               -- 分母:当天注册的账号(见口径 ①②)
  SELECT u.id                                        AS account_id,
         DATE(u.create_time)                         AS reg_date,
         CASE WHEN u.app_source = 'city'
              THEN 'CityPLX' ELSE 'SoulMap' END      AS app_line
  FROM soul_map.`user` AS u
  WHERE u.create_time >= CURDATE() - INTERVAL 21 DAY
),
behaviour AS (                   -- 两个指标:次日发过消息 / 首日发 ≥5 条
  -- 🔴 2026-11-19 改写(只改执行方式,口径不变):原本是两个相关子查询,
  --    每个新用户各扫一次 chat_history,11,014 人 × 2 = 22,028 次;而 base 又被引用 6 次
  --    ⇒ 实际 13 万次。改成一次 LEFT JOIN + 条件聚合(项目规矩:大表单次扫描)。
  --    🛑 时间条件用范围不用 DATE(c.add_on)=X —— 对列套函数要逐行求值。
  --       chat_history 上没有 add_on 的复合索引,走的是 idx_uid,范围条件至少省掉函数调用。
  SELECT n.account_id,
         n.reg_date,
         n.app_line,
         -- 🛑 外面要套 COALESCE:一个人一条消息都没有时 LEFT JOIN 补的是 NULL,
         --    MAX/SUM 出来也是 NULL。整组人都没发过消息的那些格子(HK、PS、
         --    「(查不到版本)」那组)原本是 0,不补就变成空白 —— 本项目「0 就是 0」。
         COALESCE(MAX(c.add_on >= n.reg_date + INTERVAL 1 DAY
                      AND c.add_on <  n.reg_date + INTERVAL 2 DAY), 0)       AS retained_d1,
         COALESCE(SUM(c.add_on >= n.reg_date
                      AND c.add_on <  n.reg_date + INTERVAL 1 DAY), 0)       AS day0_msgs
  FROM new_user AS n
  LEFT JOIN soul_map.soulmap_chat_history AS c
         ON c.user_id = CAST(n.account_id AS CHAR) COLLATE utf8mb4_unicode_ci
        AND c.role    = 'user'
        AND c.add_on >= n.reg_date
        AND c.add_on <  n.reg_date + INTERVAL 2 DAY
  GROUP BY n.account_id, n.reg_date, n.app_line
),
ver AS (                         -- 客户端版本:服务端 build,取最早一条(见口径 ⑤)
  SELECT user_id,
         SUBSTRING_INDEX(GROUP_CONCAT(NULLIF(build,'') ORDER BY occurred_at), ',', 1) AS build
  FROM soul_map.soulmap_interaction_event
  WHERE occurred_at >= CURDATE() - INTERVAL 22 DAY AND build IS NOT NULL AND build <> ''
  GROUP BY user_id
),
attr AS (                        -- 来源与国家:首次启动那一行(同 385/386 归因口径)
  -- 🔴 2026-11-19:去掉自连接 —— 原本先 GROUP BY 取一遍 user_id,再 join 回全表,
  --    两次扫描做的是一次 GROUP BY 的事。结果完全一样。
  --    🛑 不加时间下界:app_launch 每次启动写一行,窗口内 MIN(add_on) 不是安装时间,
  --       加下界会把「装得早、注册晚」的人归到错误的首次启动行上。
  SELECT user_id,
         SUBSTRING_INDEX(GROUP_CONCAT(NULLIF(network,'')     ORDER BY add_on), ',', 1) AS network,
         SUBSTRING_INDEX(GROUP_CONCAT(NULLIF(geo_country,'') ORDER BY add_on), ',', 1) AS country
  FROM soul_map.soulmap_app_launch
  WHERE user_id <> ''
  GROUP BY user_id
),
base AS (
  SELECT b.reg_date                                                          AS date,
         b.app_line                                                          AS app_line,
         b.retained_d1                                                       AS retained_d1,
         (b.day0_msgs >= 5)                                                  AS engaged_5plus,
         CASE WHEN a.network IS NULL OR a.network = ''        THEN '(无归因)'
              WHEN a.network = 'Instagram Installs'           THEN 'Instagram'
              WHEN a.network = 'Facebook Installs'            THEN 'Facebook'
              WHEN a.network = 'Off-Facebook Installs'        THEN 'AudienceNet'
              WHEN a.network = 'Organic'                      THEN '自然量'
              ELSE a.network END                                             AS source,
         COALESCE(NULLIF(a.country, ''), '?')                                AS country,
         COALESCE(v.build, '(查不到版本)')                                    AS app_version,
         -- 🛑 能看到 0.99 的门槛是 3.7.0,同 `422 放量覆盖按装机日`
         CASE WHEN v.build IS NULL THEN '(查不到版本)'
              WHEN CAST(SUBSTRING_INDEX(v.build,'.',1) AS UNSIGNED) * 10000
                 + CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(v.build,'.',2),'.',-1) AS UNSIGNED) * 100
                 + CAST(SUBSTRING_INDEX(v.build,'.',-1) AS UNSIGNED) >= 30700
                   THEN '能看到 0.99 (>=3.7.0)'
              ELSE '看不到 0.99 (<3.7.0)' END                                AS can_see_intro
  FROM behaviour AS b
  LEFT JOIN attr AS a ON a.user_id = CAST(b.account_id AS CHAR) COLLATE utf8mb4_0900_ai_ci
  LEFT JOIN ver  AS v ON v.user_id = CAST(b.account_id AS CHAR) COLLATE utf8mb4_0900_ai_ci
)
SELECT date, dim, dim_value,
       COUNT(*)                                                      AS new_users,
       SUM(retained_d1)                                              AS retained_d1,
       ROUND(SUM(retained_d1) / COUNT(*), 4)                         AS d1_rate,
       SUM(engaged_5plus)                                            AS engaged_5plus,
       ROUND(SUM(engaged_5plus) / COUNT(*), 4)                       AS engaged_rate
-- 🔴 2026-11-19 改写:原本是六段 `FROM base` 的 UNION ALL。MySQL 8 不物化 CTE,
--    引用几次就把整个 base(连带 behaviour 扫 chat_history)重算几次 —— 六遍。
--    改成 base 和一张六行的维度表做 CROSS JOIN,base 只出现一次,输出一行不差。
FROM (
  SELECT b.date,
         d.dim,
         CASE d.dim WHEN 'overall'   THEN 'overall'
                    WHEN 'app_line'  THEN b.app_line
                    WHEN 'source'    THEN b.source
                    WHEN 'country'   THEN b.country
                    WHEN 'version'   THEN b.app_version
                    WHEN 'see_intro' THEN b.can_see_intro END AS dim_value,
         b.retained_d1,
         b.engaged_5plus
  FROM base AS b
  CROSS JOIN (            SELECT 'overall'   AS dim
              UNION ALL SELECT 'app_line'  UNION ALL SELECT 'source'
              UNION ALL SELECT 'country'   UNION ALL SELECT 'version'
              UNION ALL SELECT 'see_intro') AS d
) AS u
GROUP BY date, dim, dim_value
HAVING new_users >= 5            -- 🛑 分母 <5 读不出,滤掉;要看全量把这行注释掉
ORDER BY date DESC, dim, new_users DESC;
