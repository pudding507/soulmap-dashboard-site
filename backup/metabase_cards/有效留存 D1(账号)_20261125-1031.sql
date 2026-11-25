-- 🔴 2026-11-12 D-563:CityPLX 由「混在 SoulMap 里」改成「并列一栏」。
--    改了什么:队列 CTE 多出一列 `app_line`(`user.app_source='city'` ⇒ CityPLX,否则 SoulMap),
--    并在维度里多出一个 `app_line` 选项卡。**Overall 的口径没动**,仍是两条线合计,
--    所以历史趋势不断、`CityPLX + SoulMap = 原来的 Overall`。
--    为什么:本卡的队列来自 `soul_map.user`,而 CityPLX 用户**只在服务端表里、埋点里一行都没有**
--    (实测近 30 天 3,797 个 city 用户:`firebase_event` 命中 0、`soulmap_chat_history` 命中 3,777)
--    ⇒ 他们一直混在本卡的分母里。
--    影响有多大(近 30 天、次日窗口已走完):
--      SoulMap 10,355 人 / 次日 810 / D1 **7.8%**;CityPLX 3,678 人 / 次日 7 / D1 **0.2%**;
--      混算 14,033 人 / 817 / **5.8%** ⇒ **Overall 被压低 2.0 个百分点(相对 −26%)**。
--    🛑 CityPLX 占近 7 天注册的 **63%**,所以**越近的日子失真越大**;读 Overall 请切到
--       `by business line` 看 SoulMap 那条。
-- 有效留存 D1 · Effective Retention D1
-- 🛑 2026-09-08 决定:**本卡刻意保留账号口径,不跟随 Retention_d1 / d3 / d7 改成设备口径。**
--    原因:本卡的回访口径是「次日发过消息」,取自 soul_map.soulmap_chat_history ——
--    那是服务端表、**只有 user_id 没有 device 标识**,回访检测绕不开账号。
--    若改成设备口径,约 13% 映射不到账号的设备会被一律判为「没发消息」,
--    有效留存率被系统性低估(见 _口径与陷阱.md 一·六:那 13% 是启动最快的设备、
--    D1 反而更高,把它们判为未发消息会低估得更狠)。
--    ⚠️ 因此本卡与 Retention_d1 **分母不同源**:
--       Retention_d1        分母 = 有 first_open 的设备(近30天 19,530)
--       本卡                分母 = soul_map.user 注册账号(近30天 21,304)
--    **两张卡的留存率不可直接相减、也不可当成「同一批人的两个口径」。**
--    卡面需标注此点。
-- ⚠️ 2026-09-08 改动:第一个 CTE(user_daily_events)补 `event_name IN (...)` 过滤,一行。
--    原因:DBA 于 09-08 加了 `idx_event_name_date (event_name, event_date)`,但**原写法用不上** ——
--    该 CTE 只有 `uid REGEXP` 和 event_date 两个条件,没有 event_name 谓词,
--    EXPLAIN 是 `type=ALL / key=None / rows=6,160,464`,对全表逐行跑 REGEXP + 分组。
--    补上过滤后 `type=range / key=idx_event_name_date / rows=137,238`(行数降 45 倍)。
--    ⏱ 实测:改前**整卡 60 秒超时**(服务端 max_execution_time 截断) → 改后冷跑 11.6s / 热跑 1.8s。
--
--    📉 口径变化(只影响 country 一个维度):
--    `MIN(country)` 原本从该用户的**全部事件**取,现在只从这三个事件取。
--    实测对本卡 cohort(21,247 人)的 country 覆盖 = 17,962(84.5%),未覆盖的落入 'others'。
--    ⚠️ 现版的覆盖率**无法测量** —— 那条全表查询本身就 60 秒超时。
--    所以这不是「84.5% vs 更高」的取舍,是「84.5% vs 整张卡不出来」。
--    其余五个维度(overall / source / adgroup / input_path / activation)**完全不受影响**:
--    pf / type 本来就只从 attribution_received 取。
--    事件选择依据:first_open 覆盖新装(76.8%)· 加 session_start 覆盖回访 · attribution_received 顺带
--    (反正要读它拿 pf/type)⇒ 三者合并 84.5%。
-- 输出形状(长维度):date | dimension | dimension_value | new_users | messaged_users
--   dimension ∈ overall / source / adgroup(=source×adgroup 组合) / country / input_path / activation
--   与 Retention_d1 完全平行,只有「回访」的判定不同;率在 BI 里用 Sum(messaged_users)/Sum(new_users) 算
--
-- 口径:注册日 cohort(soul_map.user) · 近30天滚动
--   分母 new_users      = 当天注册的新用户
--   分子 messaged_users = 其中在**次日发出过至少 1 条消息**的人(soulmap_chat_history 的 role='user')
--
-- ⚠️ 与 Retention_d1 的唯一区别:
--     Retention_d1  的「回访」= 次日有 session_start(打开过 App)
--     本卡的「回访」= 次日**说过话**(发出过消息,不含只收到 AI 消息)
--
-- 为什么需要这张卡(2026-08-13):
--   标准 D1 衡量的是「打开了 App」,不是「用了 App」,两者差距很大且不稳定:
--     · 整体:标准 D1 14.0% vs 有效 D1 4.4% —— 每 10 个「留存用户」只有 3 个真的说了话
--     · 印度:标准 29.1% vs 有效 5.4%(转化 19%);非印度:标准 8.4% vs 有效 4.0%(转化 48%)
--       印度用户平均在前台待 8 分钟(engagement_time_msec 实测,非机刷、非秒退),但 81.5% 一条不发
--     · relationship 主题:标准 D1 最低(7.2%)但转化最高(50%),有效口径下与其他主题差距大幅缩小
--   更关键的是形状:7/24–8/10 标准 D1 从 8.4% 涨到 25.4% 再掉回 8.4%(翻三倍又跌回),
--   而**有效 D1 全月稳定在 2.6%–6.2%,没有趋势**。标准口径的波动主要反映买量投向了哪个国家,
--   不反映产品状况。两条线并排看,才能把「渠道波动」和「产品变化」分开。
--
-- 归因维度映射与 Retention_d1 完全一致(source 归平台 / adgroup 归主题,ELSE 透传原值),
--   详见 soulmap_dashboard_docs/看板归因维度改造_source归平台_adgroup归主题.md
-- 性能:约 45 秒(主要开销是 firebase_event 单次扫描取归因;chat_history 仅 40 万行,很轻)
-- ⚠️ 2026-08-17 adgroup 改为取末段,不再枚举关键词:
--    原写法逐个列举 burnout/career/relationship/children/stress/depression,每上一个新主题
--    都要手动补一条,漏补就显示成一长串广告组全名。实测全部 17 个 adgroup 都是「..._主题」结尾,
--    取末段与关键词法 16 个完全一致;第 17 个(TT_soulmap_android_adnd,2 人)末段法反而取对了。
--    改后新主题自动生效,无需维护映射表。
--    ⚠️ 依赖「主题在最后一段」的命名习惯 —— 若出现 SoulMap_relationship_MV1 这类主题在中间的
--       命名会取错(该模式目前只见于 creative 字段,adgroup 未出现过)。
WITH user_daily_events AS (            -- firebase_event 单次扫描:仅取归因属性(本卡不需要 session_start)
  SELECT CAST(uid AS UNSIGNED)                AS user_id,
         MIN(country)                         AS country,
         MIN(CASE WHEN event_name = 'attribution_received'
                  THEN params->>'$.pf'   END) AS attribution_platform,
         MIN(CASE WHEN event_name = 'attribution_received'
                  THEN params->>'$.type' END) AS attribution_ad_type
  FROM host.firebase_event
  WHERE event_name IN ('first_open','attribution_received','session_start')   -- 见头部 09-08:不加这行索引用不上
    AND uid REGEXP '^[0-9]+$'
    AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
  GROUP BY user_id
),
user_message_days AS (                 -- 每用户每个「说过话的日子」一行(只算用户自己发的消息)
  SELECT CAST(user_id AS UNSIGNED) AS user_id,
         DATE(add_on)              AS message_date
  FROM soul_map.soulmap_chat_history
  WHERE role = 'user'
    AND add_on >= CURDATE() - INTERVAL 30 DAY
    AND user_id REGEXP '^[0-9]+$'
  GROUP BY user_id, message_date
),
new_user_cohort AS (                   -- 近30天注册的新用户 + 偏好输入方式
  SELECT id                                        AS user_id,
         DATE(create_time)                         AS register_date,
         COALESCE(preferred_input_mode, 'unknown') AS input_path,
         -- 🔴 2026-11-12 D-563:CityPLX 不再混进 SoulMap,改成并列一栏
         CASE WHEN app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line
  FROM soul_map.user
  WHERE create_time >= CURDATE() - INTERVAL 30 DAY
),
user_max_turn_count AS (               -- 每用户近30天会话里的最高轮数(判定是否激活)
  SELECT CAST(session.user_id AS UNSIGNED) AS user_id,
         MAX(session_state.turn_count)     AS max_turn_count
  FROM soul_map.soulmap_session AS session
  JOIN soul_map.soulmap_session_state AS session_state
    ON session_state.session_id = session.session_id
  WHERE session.add_on >= CURDATE() - INTERVAL 30 DAY
  GROUP BY user_id
),
user_effective_retention_base AS (     -- 每个新用户一行:全部维度取值 + 次日是否说过话
  SELECT cohort.register_date AS date,
         cohort.user_id,
         CASE WHEN attribution.attribution_platform LIKE '%Organic%'   THEN 'Organic'
              WHEN attribution.attribution_platform LIKE '%Google%'    THEN 'Google'
              WHEN attribution.attribution_platform LIKE '%Facebook%' OR attribution.attribution_platform LIKE '%Instagram%'
                OR attribution.attribution_platform IN ('fb','meta')   THEN 'Facebook'
              WHEN attribution.attribution_platform LIKE '%TikTok%' OR attribution.attribution_platform IN ('tt','tiktok') THEN 'TikTok'
              WHEN attribution.attribution_platform IS NULL           THEN 'others'
              ELSE attribution.attribution_platform END  AS source,
         COALESCE(NULLIF(SUBSTRING_INDEX(SUBSTRING_INDEX(attribution.attribution_ad_type,' (',1),'_',-1),''),'others')  AS adgroup,
         COALESCE(attribution.country,  'others')              AS country,
         cohort.input_path,
         cohort.app_line,
         CASE WHEN COALESCE(turn_stats.max_turn_count, 0) >= 3
              THEN 'activated' ELSE 'not_activated' END        AS activation_status,
         MAX(next_day_message.user_id IS NOT NULL)             AS has_messaged_next_day
  FROM new_user_cohort AS cohort
  LEFT JOIN user_daily_events   AS attribution ON attribution.user_id = cohort.user_id
  LEFT JOIN user_max_turn_count AS turn_stats  ON turn_stats.user_id  = cohort.user_id
  LEFT JOIN user_message_days   AS next_day_message
         ON next_day_message.user_id      = cohort.user_id
        AND next_day_message.message_date = cohort.register_date + INTERVAL 1 DAY   -- ← D1:改这个数字即得 D3/D7
  GROUP BY cohort.register_date, cohort.user_id,
           source, adgroup, country, cohort.input_path, cohort.app_line, activation_status
)
SELECT date, 'overall' AS dimension, 'Overall' AS dimension_value,
       COUNT(*) AS new_users, SUM(has_messaged_next_day) AS messaged_users
FROM user_effective_retention_base GROUP BY date
UNION ALL SELECT date,'source',    source,            COUNT(*),SUM(has_messaged_next_day) FROM user_effective_retention_base GROUP BY date, source
UNION ALL SELECT date,'adgroup',  CONCAT(source,'_',adgroup), COUNT(*),SUM(has_messaged_next_day) FROM user_effective_retention_base GROUP BY date, source, adgroup
UNION ALL SELECT date,'country',   country,           COUNT(*),SUM(has_messaged_next_day) FROM user_effective_retention_base GROUP BY date, country
UNION ALL SELECT date,'app_line',  app_line,          COUNT(*),SUM(has_messaged_next_day) FROM user_effective_retention_base GROUP BY date, app_line
UNION ALL SELECT date,'input_path',input_path,        COUNT(*),SUM(has_messaged_next_day) FROM user_effective_retention_base GROUP BY date, input_path
UNION ALL SELECT date,'activation',activation_status, COUNT(*),SUM(has_messaged_next_day) FROM user_effective_retention_base GROUP BY date, activation_status
ORDER BY date DESC, dimension, dimension_value;

