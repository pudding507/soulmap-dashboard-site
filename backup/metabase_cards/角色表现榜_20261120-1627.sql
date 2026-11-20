-- 角色表现榜 · Character Leaderboard · 近14天累计 · 表格
--
-- ═══ 🔴 2026-10-29 窗口 30 天 → 14 天(用户决定)═══
--   为什么:这四张卡压着 60 秒网关超时跑,推 Metabase 后全部 504。
--   🛑 **不是同日加 `foryou` 造成的** —— 直连实测 `coverage` 旧版 69.5s / 新版 63.6s、
--      `daily ctr` 旧版 53.1s / 新版 54.5s,**旧版反而更慢或持平**。
--      这四张在加 foryou 之前就已经超了(10-28 抓数日志里 377/380/381/382 都曾 504)。
--   实测 `coverage` 缩到 14 天后 **63.6s → 16.5s**。
--   🛑 **埋点侧和服务端侧必须一起缩** —— 本卡若同时有
--      `firebase_event.event_date` 和 `soulmap_session.add_on` 两个窗口,
--      只缩一个会让分子分母不同盘,是会静默出错的那种。
--   🛑 **跨 2026-10-29 不要把本卡前后对比**(窗口和曝光白名单同日都变了)。
--   根因仍是索引 / buffer pool,见 `173_TO-Liwen-db-index-and-buffer-pool-20261022`
--   (已发)。那边解决后可以考虑把窗口放回 30 天。
-- ⚠️ 2026-09-08 曝光口径修正:数据起点定为 **2026-09-04**,并把两侧都限制到
--    `sub_tab IN ('all','everyday','fantasy')`。
--    背景:card_impression 与 card_tap 的覆盖面自 2.8.0 起多次变化,分子分母长期不同盘 ——
--      ≤08-21      Discover 单列表,无 sub_tab 字段                    ⇒ 两侧同盘,可用
--      08-22~08-25 拆四子 tab 但 sub_tab 尚未落地(覆盖 0%→8%→70%)      ⇒ 点击无法归回 tab,不可修
--      08-26~09-03 sub_tab 可用,但曝光只在 all 一个 tab 发             ⇒ CTR 虚高到真实值的 6~8 倍
--      09-04 起     曝光改在 all / everyday / fantasy 三个 tab 发       ⇒ 本次口径的起点
--    实测虚高幅度(修正前 vs 只算 All):09-04 55.8% vs 5.8% · 08-30 48.2% vs 5.0%。
--    ⚠️ 客户端若再改 sub_tab 取值,本过滤需同步更新,否则该 tab 的曝光会静默丢失。
--
-- ═══ 🔴 2026-10-29 把 `foryou` 加进白名单。上面 09-08 那段的后半截已经过时 ═══
--   **原文说**:「`foryou` 每天 631~779 次点击但**曝光恒为 0**(服务端 catalogue 曝光
--   接收端 status=server_disabled)⇒ 本卡 CTR 只代表这三个 tab,要算全站得等服务端
--   把 catalogue 曝光打开。」**这两句现在都不成立。**
--
--   ① **`foryou` 客户端曝光早就有了**,而且是最大的一格 —— 实测 10-27 共 10,297 次、
--      10-21 共 17,447 次、10-07 共 16,762 次,**至少三周一直有**。
--   ② 🛑 **更要紧的是 `all` 已经恒为 0** —— 近 21 天只有 10-16 的 7 次、10-09 的 4 次。
--      ⇒ 白名单写死在一个**已经不存在的 tab** 上,本卡实际只算 `everyday` + `fantasy`,
--        10-27 是 2,236 次曝光,**占当天全部角色卡曝光(13,648)的 16.4%**。
--   ③ **不要改成用服务端 `catalogue_host_impression` 算「全站」** ——
--      实测服务端近 7 天只有 `foryou`(98,361)和 `search`(6,789),
--      **没有 `everyday` 和 `fantasy`**。换过去是换一批漏掉的东西,不是变全站。
--      服务端的用处在别处:它带 `slate_id` / `policy_version` / `experiment_arm`,
--      客户端只有 `position` 没有 slate ⇒ **位次配额类分析必须走服务端**。
--
--   **改动影响(实测)**:分母 2,236 → 12,533(10-27,**5.6 倍**);
--   CTR 3.49% → 4.37%,而且**波动由 2.26~5.07% 收窄到 4.12~4.58%**(近 7 天),
--   与服务端独立算出的 foryou CTR **4.58%** 相互印证。
--   🛑 **跨 2026-10-29 不要把本卡的 CTR 前后对比** —— 分母换了盘子。
--
--   **`search` 没有加进来**,有意为之:搜索是带意图的,CTR 与浏览不同质,
--   混进来会把目录浏览的 CTR 顶高。要看搜索另开卡(`搜索使用与结果质量`)。
--   `(无)` 的那少量曝光(10-24 共 26 次)归不到 tab,也不进。
-- 输出形状:每个角色一行(不带 date)—— 这是**排行榜**不是趋势,渲染器按 table 类型直接铺表
--   列:character / host_key / tile / first_seen / impressions / taps / ctr / chatted / chat_rate / deep_rate
-- Metabase 卡名:Discover_character leaderboard → metric_id = discover_character_leaderboard
--
-- 口径与「角色卡漏斗分场景」(Discover_character funnel by tile)**完全一致**,只是分组不同:
--   那张按 tile(场景类别,13 类)、看趋势;本张按**单个角色**、看排行。两张互补,勿重复解读。
--   曝光 impressions = (用户 × 角色 × 曝光日) 去重后的组合数,不是曝光次数
--                      —— 同一个人同一天反复滚到同一张卡只算一次,否则来回滚动会重复计数
--   ctr        点击 ÷ 曝光
--   chat_rate  开聊 ÷ 点击        点击后该用户与该角色确实产生过会话
--   deep_rate  深聊 ÷ 曝光        深聊 = 该(用户,角色)会话最高轮数 ≥5
--   host_key   两侧都去掉 'original:' 前缀后关联(埋点 card_id ↔ 服务端 host_id ↔ host_info.host_key)
--
-- ⚠️ 2026-08-18 新建。为什么要按角色而不只按 tile:
--    2.7.0 上线 445 个角色,实测埋点里 393 个被曝光过、仅 126 个被点开过(8/16)——
--    **三分之二的角色从没被点开**。tile 维度看不出是"整类不行"还是"类里只有几个能打",
--    必须落到单个角色才能回答「哪些角色该留、哪些该换」。
-- ⚠️ 只保留曝光 ≥50 的角色:曝光个位数的角色 CTR 会出现 0% 或 100% 这种无意义极值。
--    渲染器再按曝光量取 top N,故本表已按 impressions 降序。
-- ⚠️ 数据自 2.7.0 起(8/14 灰度、8/15 放量),之前无角色卡曝光。
-- ⚠️ host_key 是去掉 'original:' 前缀后的角色 ID,三边通用:
--    埋点 card_id = 'original:'+host_key · 服务端 session.host_id = 'original:'+host_key · host_info.host_key
--    列出来是为了能直接拿去查库/对接内容侧,name 可能重名或为空。
-- ⚠️ first_seen = 该角色在埋点里**首次被曝光**的日期,不是角色创建日 ——
--    soulmap_host_info 表**没有任何时间列**,拿不到真正的上架时间。
--    用途:区分「新角色还没跑够」和「老角色确实没人点」。
--    实测首次曝光日分布:8/14 共 128 个、8/15 共 261 个、8/16 共 13 个、8/17 共 8 个,
--    说明放量后仍在陆续加新角色,这一列会越来越有用。
WITH card_event AS (                   -- 埋点:每个(用户,角色,曝光日)一行
  SELECT uid                                                     AS user_id,
         STR_TO_DATE(event_date,'%Y%m%d')                         AS impression_date,
         REPLACE(params ->> '$.card_id','original:','')           AS host_key,
         MAX(event_name = 'card_tap')                             AS was_tapped
  FROM host.firebase_event
  WHERE event_name IN ('card_impression','card_tap')
    AND params ->> '$.sub_tab' IN ('all','everyday','fantasy','foryou')  -- 🔴 见头部 10-29
    AND event_date >= GREATEST(DATE_FORMAT(CURDATE() - INTERVAL 14 DAY, '%Y%m%d'), '20260904')
    AND params ->> '$.card_type' = 'character'
    AND uid <> '' AND uid IS NOT NULL
  GROUP BY user_id, impression_date, host_key
),
chat_with_host AS (                    -- 服务端:该用户与该角色是否聊过 + 最高轮数
  SELECT session.user_id COLLATE utf8mb4_unicode_ci                         AS user_id,
         REPLACE(session.host_id,'original:','') COLLATE utf8mb4_unicode_ci AS host_key,
         MAX(session_state.turn_count)                                      AS max_turn_count
  FROM soul_map.soulmap_session AS session
  LEFT JOIN soul_map.soulmap_session_state AS session_state
         ON session_state.session_id = session.session_id
  WHERE session.add_on >= CURDATE() - INTERVAL 14 DAY
    AND session.host_id LIKE 'original:%'
  GROUP BY user_id, host_key
),
per_character AS (
  SELECT card_event.host_key,
         MIN(card_event.impression_date)                         AS first_seen,
         COUNT(*)                                                AS impressions,
         SUM(card_event.was_tapped)                              AS taps,
         SUM(card_event.was_tapped
             AND chat_with_host.user_id IS NOT NULL)             AS chatted,
         SUM(card_event.was_tapped
             AND chat_with_host.max_turn_count >= 5)             AS deep_chatted
  FROM card_event
  LEFT JOIN chat_with_host
         ON chat_with_host.user_id  = card_event.user_id  COLLATE utf8mb4_unicode_ci
        AND chat_with_host.host_key = card_event.host_key COLLATE utf8mb4_unicode_ci
  GROUP BY card_event.host_key
  HAVING impressions >= 50
)
SELECT
  COALESCE(NULLIF(host_info.name,''), per_character.host_key)     AS `character`,
  per_character.host_key                                          AS host_key,
  COALESCE(NULLIF(host_info.tile,''), '(未登记)')                  AS tile,
  per_character.first_seen                                        AS first_seen,
  per_character.impressions                                       AS impressions,
  per_character.taps                                              AS taps,
  ROUND(per_character.taps / per_character.impressions, 4)        AS ctr,
  per_character.chatted                                           AS chatted,
  ROUND(per_character.chatted / NULLIF(per_character.taps,0), 4)  AS chat_rate,
  per_character.deep_chatted                                      AS deep_chatted,
  ROUND(per_character.deep_chatted / per_character.impressions,4) AS deep_rate
FROM per_character
LEFT JOIN soul_map.soulmap_host_info AS host_info
       ON host_info.host_key COLLATE utf8mb4_unicode_ci
        = per_character.host_key COLLATE utf8mb4_unicode_ci
ORDER BY ctr DESC;

