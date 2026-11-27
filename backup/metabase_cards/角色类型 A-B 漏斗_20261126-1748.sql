-- ── 2026-11-20(同日第二处改动):加 date,改成一天一行一组 ──────────────────
--   和性能改写同一天做。实测加 date **不额外花时间**(35.0s vs 37.1s,在噪声内),
--   因为瓶颈在 entry 那一次索引扫描,分组多一维不改变扫描量。
--
--   🔴 **按天拆之后,三个比率列的读法变了,必须讲清楚**:
--     分母 = **当天**进过聊天页的设备;分子 = 这些人的**全历史**累计状态。
--     ⇒ 它回答的是「今天来的人里,有多少是已经聊到 N 句的」,
--       **不是**「今天来的人发了 N 句」。
--     ⇒ 按天拆之后比率会**比整段高**(实测 B 类 msg20:逐日 0.50 vs 整段 0.364),
--       那是因为每天来的多半是老用户,**不是指标变好了**。
--     🛑 **不要拿逐日比率和整段比率对比**,两者分母不是一回事。
--   ✅ 真正适合按天读的是 `entered_users` —— 当天各类角色的进入设备数。
--
--   🛑 跨天不要把 `entered_users` 相加当成人数:同一台设备每天来都会算一次。
--   🛑 `ios_devices` 按天拆之后更清楚:11-19 A 类 16 台里 7 台是 iOS,
--      B 类 370 台里只有 1 台 —— 和卡头 11-11 那段(552 开关后 iOS 不再出 B 类)吻合。
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-11-20 性能改写:54s(线上)/112s(本地) → 两个全表扫合并成一次查找  ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【动机】这张卡长期贴着 60 秒的抓数上限,随时会掉。
--
--   【EXPLAIN ANALYZE 实测,95 秒花在哪】
--     entry(firebase chat_entry_shown,走 idx_event_name_date)      29.3s
--     🔴 role_card_message —— **扫 soulmap_chat_history 全表 212 万行**  51.5s
--     🔴 total_message     —— **又扫一遍同一张表 212 万行**            14.3s
--     subscription_user                                              0.07s
--   两个 CTE 各扫一次全表,合计 65.8 秒,占七成。
--   (`role_card_message` 比 `total_message` 慢 3.6 倍,是多出来的 `host_id LIKE` 的代价。)
--
--   【改了什么】两件事一起做:
--   ① **合并成一次扫描 + 条件聚合** —— 本项目的老规矩(大表不要拆多个 CTE 各扫一遍)。
--      `total_messages` 和 `has_role_card_message` 在同一次 GROUP BY 里出来。
--   ② **先用 entry 的账号把范围收窄再聚合。** 原来两个 CTE 都是**全历史、无下界**,
--      把 212 万行全算一遍,而这张卡只需要 entry 里那 7,089 台设备对应的账号。
--      改成由 `entry_account` 驱动、走 `soulmap_chat_history` 的 `idx_uid` 逐个查找。
--      🛑 **这不改口径**:原来是「全算一遍,再 LEFT JOIN 取匹配的」,
--        现在是「先取匹配的,再算」,对命中的账号结果完全一样(见文末对照)。
--      🛑 `user_id` 是 varchar(50) utf8mb4_unicode_ci,**JOIN 时不要包 CAST**,
--        包了就用不上索引;CAST 放在 entry 那一侧。
--
--   ═══ 等价性验证见文末「2026-11-20 对照」═══
--
-- ═══ 🔴 2026-11-11:加 `ios_devices` 一列(不拆行);iOS 即将不再出 B 类 ═══
--   背景:服务端 552(2026-11-11)要做一个开关 `catalogue.ios_hide_type_b.enabled`,
--   打开后 **iOS 用户看不到、也开不了新的 B 类角色和社区角色**(安卓不受影响)。
--   🔴 这是**服务端开关,改完 1 分钟生效、不发版** ⇒ 切点时刻我们事先不知道,
--      要等 liwen 通知后回填到 `_已落地改动台账.md`。
--   ⇒ 开关打开之后,本卡的 **`B_仅幻想` 和 `AB_两类都进过` 两行只代表安卓**。
--
--   🛑 **为什么加列不拆行**:iOS 近 7 天只有约 32 个用户(552 §一-1 给的数)。
--      拆成「平台 × 四分组」八行的话每格都是个位数,按本项目口径
--      (分子 <10 标「读不出」、不排名)那八行读不出任何东西,反而会被当成真差异去比。
--      ⇒ 只加一列 `ios_devices` 做**分母提示**,让读的人知道这一行里有多少 iOS,
--        行数仍是四行、仍然可以相加。
--   🛑 平台取值用 `UPPER(platform)='IOS'` 判,不写死某一种大小写拼法。
--
-- ═══ 🛑 2026-10-19:「付费」口径修正(只改口径,不加列) ═══
--   实测:买过 0.99 的 43 人在 soul_map.subscription 里 **100% 是 in_trial=1**,一个 0 都没有;
--   对照免费试用 460 人里 439 人 in_trial=1、只有 21 人是 0。
--   ⇒ in_trial=0 的真实含义是「已走过首期、按原价续上了」,全库只有 21 人,
--     原写法把**全部 0.99 买家漏在外面** —— 他们明明付了钱。
--   改动:付费判定补 `OR 买过 INTRO`(period_type='INTRO',不能靠 product_id)。
--   🛑 **不新增列**:沿用本卡原有判断 —— 0.99 人数分到四个分组后每格都是个位数,读不出。
--      要看 0.99 请用看板 24 第二区的三张 `0.99首月_*`。
--   与看板 24 的 400 `has_paid` 完全同口径。
-- 【展示形式】**表格**。三个理由:
--   ① 🛑 四个分组(A 类 / B 类 / 混用 / 未知)**各自成行、可以相加**,
--      它们是**并列关系不是嵌套关系** —— 画成漏斗图会骗人;
--   ② 每台设备只进一组,四行的分母各自独立,表格才能把分母摆出来;
--   ③ 试用 / 付费两列是个位数,不配比率(见卡头),画成图会让人读出不存在的差异。
WITH entry AS (                        -- 每台设备窗口内进过哪些类型的聊天页 + 账号(客户端埋点)
--
-- ═══ 🛑 2026-10-16:`trial_effective_users` 的含义已复核 ═══
--   它统计的是 `subscription.in_trial = 1`,而**0.99 当场付清的人 in_trial 也是 1**,
--   所以这一列读作「**试用生效或买过 0.99**」。**数没错,是列名容易被读成只有免费试用。**
  -- 2026-09-15:账号直接取自 chat_entry_shown 自身的 uid 列(实测覆盖 3,691/3,697 = 99.8%),
  -- 不再另起一个跨全部事件的 device_account CTE —— 那个 CTE 用不上 event_name 索引,
  -- 实测把整卡从 148 秒拖成主要耗时;改后本 CTE 走索引、约 1.4 秒。
  SELECT STR_TO_DATE(event_date, '%Y%m%d')                               AS date,
         user_pseudo_id                                                  AS device_id,
         MAX(JSON_UNQUOTE(JSON_EXTRACT(params,'$.char_type')) = 'A')     AS entered_a,
         MAX(JSON_UNQUOTE(JSON_EXTRACT(params,'$.char_type')) = 'B')     AS entered_b,
         MAX(CASE WHEN uid <> '' AND uid IS NOT NULL THEN uid END)       AS account_id,
         -- 🔴 2026-11-11 新增:这台设备是不是 iOS(见卡头同日说明)。
         MAX(UPPER(platform) = 'IOS')                                    AS is_ios
  FROM host.firebase_event
  WHERE event_name = 'chat_entry_shown'                                  -- 走 event_name 索引
    AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
  GROUP BY date, user_pseudo_id
),
entry_account AS (                     -- 2026-11-20:entry 里出现过的账号,用来收窄下面的扫描
  SELECT DISTINCT CAST(account_id AS CHAR) COLLATE utf8mb4_unicode_ci    AS account_id
  FROM entry
  WHERE account_id IS NOT NULL AND account_id <> ''
),
message_stat AS (                      -- 2026-11-20:取代原来的 role_card_message + total_message
  -- 一次 GROUP BY 同时出两个指标,口径与原来逐字一致:
  --   total_messages        = 全历史累计全部用户消息(不限 host),与额度墙同口径
  --   has_role_card_message = 对**角色卡**(host_id 带 original: 前缀)发过消息
  -- 🛑 由 entry_account 驱动,走 soulmap_chat_history 的 idx_uid 逐账号查找。
  --    **JOIN 的这一侧不要包 CAST**,包了索引就用不上了(CAST 已经放在 entry_account 里)。
  SELECT ch.user_id                                                      AS user_id,
         COUNT(*)                                                        AS total_messages,
         MAX(ch.host_id LIKE 'original:%')                               AS has_role_card_message
  FROM entry_account AS ea
  JOIN soul_map.soulmap_chat_history AS ch ON ch.user_id = ea.account_id
  WHERE ch.role = 'user' AND ch.content IS NOT NULL AND ch.content <> ''
  GROUP BY ch.user_id
),
post_launch_user AS (                  -- 付费功能 2026-09-11 正式上线,此前的订阅行是上线前测试
  SELECT user_id
  FROM (SELECT user_id, trial_started_at AS related_at
          FROM soul_map.subscription_user_state WHERE trial_used = 1
        UNION ALL
        SELECT user_id, start_time       AS related_at
          FROM soul_map.subscription WHERE product_id NOT LIKE '%admin_test%') AS rel
  GROUP BY user_id
  HAVING MIN(related_at) >= '2026-09-11'
),
subscription_user AS (                 -- 每人是否试用生效 / 是否付费
  -- 🛑 2026-10-16 复核:`is_trial_effective = MAX(in_trial = 1)` **已经含 0.99 的人** ——
  --    实测 0.99 用户在 `soul_map.subscription` 里 `in_trial` 也是 1(13 人、每人一行)。
  --    ⇒ `trial_effective_users` 这一列读作「**试用生效或买过 0.99**」,不是只有免费试用。
  --    实测 459 个 in_trial=1 的人里 **13 人买过 0.99**(2.8%)。
  --    🛑 **不单独拆列** —— 13 人分到四个分组后每格都是个位数,读不出。
  --       要看 0.99 请用第二区的三张 `0.99首月_*`。
  SELECT CAST(s.user_id AS CHAR) COLLATE utf8mb4_unicode_ci              AS user_id,
         MAX(s.in_trial = 1)                                             AS is_trial_effective,
         -- 2026-10-19:补 0.99。原写法 `MAX(s.in_trial = 0)` 把买 0.99 的人整批漏掉
         MAX(s.in_trial = 0 OR intro.user_id IS NOT NULL)                AS is_paid
  FROM soul_map.subscription AS s
  JOIN post_launch_user AS p ON p.user_id = s.user_id
  LEFT JOIN (SELECT DISTINCT user_id FROM soul_map.subscription_event_log
             WHERE environment = 'PRODUCTION' AND period_type = 'INTRO') AS intro
         ON intro.user_id = s.user_id
  WHERE s.product_id NOT LIKE '%admin_test%'
  GROUP BY s.user_id
),
device_group AS (                      -- 每台设备归一组,每人只进一组 ⇒ 四行可相加
  SELECT entry.date,
         entry.device_id,
         CASE WHEN entry.entered_a = 1 AND entry.entered_b = 1 THEN 'AB_两类都进过'
              WHEN entry.entered_a = 1                         THEN 'A_仅真实'
              WHEN entry.entered_b = 1                         THEN 'B_仅幻想'
              ELSE '未知类型' END                                        AS group_name,
         CAST(entry.account_id AS CHAR) COLLATE utf8mb4_unicode_ci       AS account_id,
         entry.is_ios                                                    AS is_ios
  FROM entry
)
SELECT device_group.date                                                 AS date,
       device_group.group_name                                           AS group_name,
       COUNT(*)                                                          AS entered_users,
       SUM(COALESCE(message_stat.has_role_card_message, 0))              AS replied_users,
       ROUND(SUM(COALESCE(message_stat.has_role_card_message, 0))
             / COUNT(*), 4)                                              AS replied_rate,
       SUM(COALESCE(message_stat.total_messages, 0) >= 6)                AS msg6_users,
       ROUND(SUM(COALESCE(message_stat.total_messages, 0) >= 6)
             / COUNT(*), 4)                                              AS msg6_rate,
       SUM(COALESCE(message_stat.total_messages, 0) >= 20)               AS msg20_users,
       ROUND(SUM(COALESCE(message_stat.total_messages, 0) >= 20)
             / COUNT(*), 4)                                              AS msg20_rate,
       -- 个位数,不配比率,见头部
       SUM(COALESCE(subscription_user.is_trial_effective, 0))            AS trial_effective_users,
       SUM(COALESCE(subscription_user.is_paid, 0))                       AS paid_users,
       -- 🔴 2026-11-11 新增:本行里的 iOS 设备数,**只做分母提示,不是一个分组**。
       --    552 的开关打开后,iOS 不再出 B 类和社区角色 ⇒ 这一列 >0 的行,
       --    自切点起实际上只代表安卓。切点时刻见 `_已落地改动台账.md`。
       SUM(COALESCE(device_group.is_ios, 0))                             AS ios_devices
FROM device_group
LEFT JOIN message_stat      ON message_stat.user_id      = device_group.account_id
LEFT JOIN subscription_user ON subscription_user.user_id = device_group.account_id
GROUP BY device_group.date, device_group.group_name
ORDER BY date DESC, entered_users DESC;

-- ═══ 2026-11-20 对照(等价性验证)═══
--   同一台机器、同一时刻,新旧两版各跑一次,输出按行排序后 diff。
--     原版(两个 CTE 各扫一次 chat_history 全表)   112.3s   4 行
--     新版(合并成一次,由 entry 的账号驱动)      **37.1s**  4 行
--     **十一列数字逐行完全一致,diff 无输出。**
--   ⚠️ 本地比线上慢(线上 54.1s),机器和负载不同,降幅按比例读。
--   ⚠️ 剩下的大头是 `entry` 的约 29 秒 —— firebase_event 按索引取 49,883 行
--      再回表解析 params 里的 JSON。那是这张卡现在的时间下限。
