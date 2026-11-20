-- 🔴 2026-11-03 删掉 onboarding 三步(2_开始onboarding / 3_选topic / 4_完成onboarding):
--    这三步对应 `onboarding_started` / `onboarding_card_selected` / `onboarding_completed`,
--    产品 3.1.1 起已从客户端移除。本地 2026-09-20 就删过,但那版从没推到线上,
--    线上一直还在出这三步。实测近 30 天这三个事件仍有少量行
--    (started 112 / card_selected 192 / completed 34),但**全部来自 2.x 与 3.0.x 的老装机**,
--    3.1.1 及以上一行都没有 ⇒ 对本卡「近 30 天装机」这个队列来说恒为 0,
--    留着只会让 1→2 看起来断崖。删完步骤重新编号,其余各步口径一个字没动。
-- 🔴 2026-11-03 性能:本卡此前**每次都 60 秒网关超时(504),一行都出不来**。
--    瓶颈不是 firebase_event,是下面两个 CTE 对 `soulmap_chat_history` 做
--    **全表、全历史**的 GROUP BY —— 为了「全历史累计句数」这个口径,它们没有任何
--    日期限制,等于每跑一次卡就把整张聊天表数一遍。
--    【改法】口径一个字不改,只是**先把本次队列的账号列出来,再拿它去 join 聊天表**:
--      仍然不限日期(所以还是「全历史累计」),但只数队列里这批人的,
--      能吃上 `idx_uid(user_id)` / `idx_user_host_id(user_id,host_id,id)` 两个索引,
--      不再全表扫。🛑 **数值应当与改前完全一致** —— 队列外的用户本来也进不了漏斗,
--      他们的统计算出来只是被 LEFT JOIN 丢掉。
-- 🔴 2026-11-03:加一级「买过能量」—— 能量系统 2026-10-28 14:32:20 上线,
--    10-31 起订阅首购基本归零、能量包接管(实测首购 10-24~10-28 每天 5~11 笔 →
--    10-30 起 1 / 0 / 2 / 0 / 0;同期能量包从 0 涨到每天 9~13 笔),
--    这个漏斗不加这一级就看不到变现的新出口。
--    口径:`soulmap_energy_lot` 里 `layer='purchased' AND source='purchase'` 的账号
--    (全库至今 52 笔 / 30 人)。🛑 **不要用 `source='price_update_20261029'`** ——
--    那是改价补偿,不是购买。
--    🛑 **这一级每组只有个位数,只读绝对人数,不要算转化率**(口径清单:分子 <10 不给比率)。
--    🛑 本卡窗口只覆盖最近几周的装机,而能量上线才几天 ⇒ **这一级天然偏小**,
--       不能和上面几级的漏斗收窄放在一起解释。
--
-- 🛑 2026-11-03:本文件以**线上版为基线**重写(原本地版与线上不一致,差异见台账)。
--    这么做是为了不把线上已有、本地没有的改动静默回滚掉。

WITH
energy_buyers AS (                     -- 2026-11-03 新增:买过能量包的账号
  SELECT DISTINCT user_id
  FROM   soul_map.soulmap_energy_lot
  WHERE  layer = 'purchased' AND source = 'purchase'
),
onboarding_events AS (            -- 每个用户的 onboarding 各步是否到达 + 所在版本
  SELECT user_pseudo_id AS device_id,
    MAX(CASE WHEN uid <> '' AND uid IS NOT NULL THEN CAST(uid AS UNSIGNED) END) AS account_id,
    -- ⚠️ 2026-09-18:版本与 cohort 入口由 onboarding_started 改为 first_open。见头部同日说明。
    MIN(CASE WHEN event_name='first_open' THEN version END)     AS app_version,   -- 用顶层 version,不用 params,见头部 2026-09-07 ④
    MAX(event_name='first_open')                                AS reached_open,
    MAX(event_name = 'card_tap'
        AND params->>'$.card_type' = 'character')               AS reached_pick_character
  FROM host.firebase_event
  WHERE event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
    AND event_name IN ('first_open','card_tap')   -- catalog_shown 见头部 2026-09-07 ⑥;first_text/audio_sent 见 2026-09-15(改走服务端句数);first_open 见 2026-09-18;onboarding 三件见 2026-11-03
  GROUP BY device_id
),
cohort_accounts AS (        -- 🔴 2026-11-03:本次队列的账号,用来把聊天表的扫描限在这批人上
  SELECT DISTINCT CAST(onboarding_events.account_id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_id
  FROM   onboarding_events
  WHERE  onboarding_events.account_id IS NOT NULL
),
user_max_messages_single_host AS (     -- 2026-09-18 新增:每用户与**单个 host** 的最大累计消息数
  -- ⚠️ 排除 reception-default(系统接待,不是角色),与 QCD 口径一致;同为全历史累计
  SELECT user_id, MAX(messages_with_host) AS max_messages_single_host
  FROM (
      SELECT ch.user_id, ch.host_id, COUNT(*) AS messages_with_host
      FROM soul_map.soulmap_chat_history AS ch
      JOIN cohort_accounts AS ca ON ca.user_id = ch.user_id    -- 🔴 2026-11-03:只数本次队列,见卡头
      WHERE ch.role = 'user' AND ch.content IS NOT NULL AND ch.content <> ''
        AND ch.host_id <> 'reception-default'
      GROUP BY ch.user_id, ch.host_id
  ) per_user_host
  GROUP BY user_id
),
user_total_messages AS (               -- 每用户**全历史**累计非空用户消息数(不限 host)
  -- 2026-09-15 取代原 user_max_turn_count。免费额度算的是全部用户消息、且是全历史累计,
  -- 所以这里不加窗口 —— 与额度墙、Growth 两张卡同口径。
  -- 实测 3.8s(走 idx_uid),比原来 join session + session_state 更快。
  -- ⚠️ 2026-09-18:曾尝试与下方 single_host 合并为一次扫描,**但无法判断快慢** ——
  --    同一份 SQL 连跑三轮实测 6.9s / 25.4s / 48.4s(差 7 倍),库负载波动完全淹没了结构差异。
  --    ⇒ **不要用单次计时做优化判断。** 当前保持两个 CTE 是因为语义清晰,不是因为它更快。
  --    若日后要认真优化,需在低峰期多轮取中位数,或直接看 EXPLAIN。
  SELECT ch.user_id, COUNT(*) AS total_messages
  FROM soul_map.soulmap_chat_history AS ch
  JOIN cohort_accounts AS ca ON ca.user_id = ch.user_id        -- 🔴 2026-11-03:只数本次队列,见卡头
  WHERE ch.role = 'user' AND ch.content IS NOT NULL AND ch.content <> ''
  GROUP BY ch.user_id
),
funnel_user AS (                       -- 2026-09-18 起:保留所有装机用户(入口 first_open),不再要求开始过 onboarding
  SELECT onboarding_events.app_version AS grp,
         reached_pick_character,
         (message_stats.total_messages >= 1)  AS reached_1_message,
         (message_stats.total_messages >= 3)  AS reached_3_messages,
         (message_stats.total_messages >= 5)  AS reached_5_messages,
         (message_stats.total_messages >= 10) AS reached_10_messages,
         (message_stats.total_messages >= 20) AS reached_20_messages,
         (single_host_stats.max_messages_single_host >= 20) AS reached_20_messages_single_host,
         (energy_buyer.user_id IS NOT NULL)                 AS reached_bought_energy
  FROM onboarding_events
  -- account_id 是 UNSIGNED、chat_history.user_id 是 varchar/unicode_ci ⇒ 必须显式 CAST + COLLATE,否则 1267
  LEFT JOIN user_total_messages AS message_stats
         ON message_stats.user_id
          = CAST(onboarding_events.account_id AS CHAR) COLLATE utf8mb4_unicode_ci   -- 取不到账号 ⇒ NULL ⇒ 记「未达」不剔除
  LEFT JOIN user_max_messages_single_host AS single_host_stats
         ON single_host_stats.user_id
          = CAST(onboarding_events.account_id AS CHAR) COLLATE utf8mb4_unicode_ci
  LEFT JOIN energy_buyers AS energy_buyer
         ON energy_buyer.user_id
          = CAST(onboarding_events.account_id AS CHAR) COLLATE utf8mb4_unicode_ci
  -- ⚠️ 2026-09-18:原为 `reached_start = 1`(要求开始过 onboarding),这正是 3.1.1 进不来的闸门。
  --    改为 reached_open,app_version 也已改取 first_open —— 两者一致,窗口内装机即入 cohort。
  WHERE reached_open = 1 AND app_version IS NOT NULL AND app_version <> ''
),
version_user_count AS (                -- 每个版本有多少人装机(2026-09-18 前为「开始过 onboarding」)
  SELECT grp, COUNT(*) AS users,
         CAST(SUBSTRING_INDEX(grp,'.',1) AS UNSIGNED) * 1000000
       + CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(grp,'.',2),'.',-1) AS UNSIGNED) * 1000
       + CAST(SUBSTRING_INDEX(grp,'.',-1) AS UNSIGNED)            AS version_numeric
  FROM funnel_user GROUP BY grp
),
latest_versions AS (                   -- 人数前 6 的版本 + 强制含最新版,见头部 2026-09-07 ⑤
  -- ⚠️ 2026-09-18:「最新版」加装机量下限 200。原写法无下限,2026-09-17 一台预发布包(3.2.0)
  --    就占掉了这个名额,把真正的新版本 3.1.1(549 台)挤出榜外,且该列全是 1 台设备的噪音。
  SELECT grp FROM (SELECT grp FROM version_user_count ORDER BY users DESC LIMIT 6) top_by_users
  UNION
  SELECT grp FROM (SELECT grp FROM version_user_count
                   WHERE users >= 200            -- 排除灰度/内测/预发布版本
                   ORDER BY version_numeric DESC LIMIT 1) newest
),
funnel_top AS (
  SELECT * FROM funnel_user WHERE grp IN (SELECT grp FROM latest_versions)
)
SELECT step, grp, COUNT(*) AS users FROM (
  SELECT grp, '1_打开'             AS step FROM funnel_top
  -- ⚠️ 2–4 步自 3.1.1 起对广告用户恒为 0(onboarding 已移除),不是回退。见头部 2026-09-18。
  UNION ALL SELECT grp, '2_选择角色'       FROM funnel_top WHERE reached_pick_character
  UNION ALL SELECT grp, '3_累计1句'        FROM funnel_top WHERE reached_1_message
  UNION ALL SELECT grp, '4_累计3句'        FROM funnel_top WHERE reached_3_messages
  UNION ALL SELECT grp, '5_累计5句'        FROM funnel_top WHERE reached_5_messages
  UNION ALL SELECT grp, '6_累计10句'       FROM funnel_top WHERE reached_10_messages
  UNION ALL SELECT grp, '7_累计20句'       FROM funnel_top WHERE reached_20_messages
  UNION ALL SELECT grp, '8_单host累计20句' FROM funnel_top WHERE reached_20_messages_single_host
  UNION ALL SELECT grp, '9_买过能量'       FROM funnel_top WHERE reached_bought_energy
) t
GROUP BY step, grp
ORDER BY step, grp;

