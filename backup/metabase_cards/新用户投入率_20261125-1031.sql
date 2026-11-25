-- 🔴 2026-11-12 D-563:CityPLX 由「混在 SoulMap 里」改成「并列一栏」。
--    改了什么:队列 CTE 多出一列 `app_line`(`user.app_source='city'` ⇒ CityPLX,否则 SoulMap),
--    并在维度里多出一个 `app_line` 选项卡。**Overall 的口径没动**,仍是两条线合计,
--    所以历史趋势不断、`CityPLX + SoulMap = 原来的 Overall`。
--    为什么:本卡的队列来自 `soul_map.user`,而 CityPLX 用户**只在服务端表里、埋点里一行都没有**
--    (实测近 30 天 3,797 个 city 用户:`firebase_event` 命中 0、`soulmap_chat_history` 命中 3,777)
--    ⇒ 他们一直混在本卡的分母里。
--    影响有多大(近 30 天、次日窗口已走完):
--      首日发 ≥5 条的比例:SoulMap **39.2%**、CityPLX **27.9%**、混算 **36.3%**
--      ⇒ Overall 被压低约 3 个百分点。
--    🛑 CityPLX 占近 7 天注册的 **63%**,所以**越近的日子失真越大**;读 Overall 请切到
--       `by business line` 看 SoulMap 那条。
-- 新用户投入率 · Engaged New-User Rate · 近30天按天
-- 口径:当天注册的新用户里,当天发出 ≥5 条 user 消息的占比
--   分子 engaged_new_users = 注册当天就发了 ≥5 条的人
--   分母 new_users         = 当天注册的全部新用户(soul_map.user.create_time)
--   率在 BI 里用 Sum(engaged_new_users)/Sum(new_users) 算,别对率求平均
-- 与「投入用户数」那张卡的区别:那张是绝对人数(含老用户),这张只看新用户且是占比
-- 输出形状:date | country | new_users | engaged_new_users
-- 校验(2026-07-30):30天合计 4793/19717 = 24.3%;7/28 125/399 = 31.3%,与「投入用户数」卡 user_type=new 逐日一致
--
-- ⚠️ 2026-08-31 加 country 维度。
--    改了什么:新增 install_country CTE,把 user_id 映射到装机国家;输出多一列 country。
--    为什么:看板要按国家筛选。
--      🔴 **这张卡原本不碰 firebase**,而服务端侧没有可用的国家字段:
--         `soulmap_app_launch.country` 列存在但 100% 为空(近14天 47,332 行全空);
--         `soul_map.user.country_code` 是账号/商店地区,与埋点 country 仅 43% 一致(US 24.7% vs 1.8%)。
--      ⇒ 只能 join `host.firebase_event` 取埋点 country,**与其余国家筛选卡口径统一** ——
--         否则同一个看板上「美国」会指两批不同的人,比不做筛选更危险。
--    国家取「最早一条 `first_open` 的 country」= 装机国家。
--      🔴 `firebase_event` 没有 event_name 索引,**加什么条件都要付全表扫的固定成本**,
--         所以换锚点不影响耗时,只影响覆盖率。
--    ⚠️ 映射不到的记 `unknown`,**不并进任何真实国家** —— 埋点 uid 覆盖率约 85%,
--       这部分是真的不知道,不是零。
--    影响(实测 2026-08-31):
--      🔴 **耗时 0.3 秒 → 44 秒**,已贴近网关 60 秒超时线。这是加国家维度不可避免的代价:
--         `firebase_event` 没有 event_name 索引,任何 join 都要付全表扫的固定成本。
--      行数 30 → 2,318(date × 188 个国家)。
--      总量校验:分国家汇总 new=20,056 / engaged=4,145,与改前完全一致,join 未造成扇出或丢行。
--      ⚠️ **unknown 占 23.1%** —— 埋点里找不到该 user_id 的用户,单列为 unknown,
--         **不并进任何真实国家**。其中 12.8pp 是真实缺口(该用户在任何埋点事件里都没有 uid),
--         其中 12.8pp 是真实缺口(该用户在任何埋点事件里都没有 uid),
--         与 Page 1 的「埋点 uid 覆盖率 85%」是同一件事,不是本卡的问题;
--         另外约 10pp 是 first_open 锚点本身的局限,是为性能主动接受的代价。
WITH new_user_daily AS (               -- 当天注册的新用户(分母)
  SELECT id AS user_id, DATE(create_time) AS register_date,
         -- 🔴 2026-11-12 D-563:CityPLX 不再混进 SoulMap,改成并列一栏
         CASE WHEN app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line
  FROM soul_map.user
  WHERE create_time >= CURDATE() - INTERVAL 30 DAY
),
engaged_user_daily AS (                -- 当天发 ≥5 条 user 消息的人
  SELECT CAST(user_id AS UNSIGNED) AS user_id, DATE(add_on) AS engaged_date
  FROM soul_map.soulmap_chat_history
  WHERE role = 'user' AND add_on >= CURDATE() - INTERVAL 30 DAY
  GROUP BY user_id, DATE(add_on)
  HAVING COUNT(*) >= 5
),
install_country AS (                   -- uid → 装机国家(取最早一条 first_open)
  -- ⚠️ 锚点是 `first_open`。**不要"优化"成 `app_open`** —— 那样覆盖率更好但会超时:
  --    实测对照(2026-08-31,30 天窗口):
  --      first_open  · GROUP_CONCAT+ORDER BY    unknown 23.1%   44s   ✅ 采用
  --      app_open    · GROUP_CONCAT+ORDER BY    unknown 15.0%   75s   ❌ 超网关 60s
  --      app_open    · MAX(country) 不排序       unknown 15.0%   48s   ⚠️ 边缘,且语义错
  --                    (变成"出现过的国家里字典序最大的",用户跨国家时取错)
  --      任意埋点事件(理论下限)                   unknown 12.8%
  --    差距来源:first_open 的 uid 覆盖率 80.6%,app_open 是 98.5%;
  --             且 first_open 事件数(19,183)本身就少于注册数(20,056) —— 有人更早装机、本窗口才注册。
  --    ⇒ **2026-08-31 决定:宁可 23% unknown,也要这张卡稳定抓得到。**
  -- ⚠️ `uid REGEXP '^[0-9]+$'` 是必须的:uid 有 1.1% 不是纯数字,
  --    CAST(uid AS UNSIGNED) 会静默变成 0 然后错配到 user_id=0。
  -- GROUP_CONCAT + ORDER BY 取首元素:只关心第一个值,默认 1024 长度上限截断不影响结果。
  SELECT CAST(uid AS UNSIGNED) AS user_id,
         SUBSTRING_INDEX(
           GROUP_CONCAT(COALESCE(NULLIF(country,''),'others')
                        ORDER BY event_timestamp), ',', 1) AS country
  FROM host.firebase_event
  WHERE event_name = 'first_open'
    AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
    AND uid IS NOT NULL AND uid <> '' AND uid REGEXP '^[0-9]+$'
  GROUP BY user_id
)
SELECT new_user_daily.register_date                    AS date,
       COALESCE(install_country.country, 'unknown')     AS country,
       new_user_daily.app_line                          AS app_line,
       COUNT(DISTINCT new_user_daily.user_id)           AS new_users,
       COUNT(DISTINCT engaged_user_daily.user_id)       AS engaged_new_users
FROM new_user_daily
LEFT JOIN engaged_user_daily
       ON engaged_user_daily.user_id      = new_user_daily.user_id
      AND engaged_user_daily.engaged_date = new_user_daily.register_date
LEFT JOIN install_country
       ON install_country.user_id = new_user_daily.user_id
GROUP BY date, country, app_line
ORDER BY date DESC;

