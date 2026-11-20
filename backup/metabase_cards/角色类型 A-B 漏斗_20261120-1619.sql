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
  SELECT user_pseudo_id                                                  AS device_id,
         MAX(JSON_UNQUOTE(JSON_EXTRACT(params,'$.char_type')) = 'A')     AS entered_a,
         MAX(JSON_UNQUOTE(JSON_EXTRACT(params,'$.char_type')) = 'B')     AS entered_b,
         MAX(CASE WHEN uid <> '' AND uid IS NOT NULL THEN uid END)       AS account_id
  FROM host.firebase_event
  WHERE event_name = 'chat_entry_shown'                                  -- 走 event_name 索引
    AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
  GROUP BY user_pseudo_id
),
role_card_message AS (                 -- 对**角色卡**发过消息的账号(用于 replied_users)
  SELECT user_id                                                         AS user_id
  FROM soul_map.soulmap_chat_history
  WHERE role = 'user' AND content IS NOT NULL AND content <> ''
    AND host_id LIKE 'original:%'
  GROUP BY user_id
),
total_message AS (                     -- 全历史累计全部用户消息(不限 host),与额度墙同口径
  SELECT user_id                                                         AS user_id,
         COUNT(*)                                                        AS total_messages
  FROM soul_map.soulmap_chat_history
  WHERE role = 'user' AND content IS NOT NULL AND content <> ''
  GROUP BY user_id
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
  SELECT entry.device_id,
         CASE WHEN entry.entered_a = 1 AND entry.entered_b = 1 THEN 'AB_两类都进过'
              WHEN entry.entered_a = 1                         THEN 'A_仅真实'
              WHEN entry.entered_b = 1                         THEN 'B_仅幻想'
              ELSE '未知类型' END                                        AS group_name,
         CAST(entry.account_id AS CHAR) COLLATE utf8mb4_unicode_ci       AS account_id
  FROM entry
)
SELECT device_group.group_name                                           AS group_name,
       COUNT(*)                                                          AS entered_users,
       SUM(role_card_message.user_id IS NOT NULL)                        AS replied_users,
       ROUND(SUM(role_card_message.user_id IS NOT NULL) / COUNT(*), 4)   AS replied_rate,
       SUM(COALESCE(total_message.total_messages, 0) >= 6)               AS msg6_users,
       ROUND(SUM(COALESCE(total_message.total_messages, 0) >= 6)
             / COUNT(*), 4)                                              AS msg6_rate,
       SUM(COALESCE(total_message.total_messages, 0) >= 20)              AS msg20_users,
       ROUND(SUM(COALESCE(total_message.total_messages, 0) >= 20)
             / COUNT(*), 4)                                              AS msg20_rate,
       -- 个位数,不配比率,见头部
       SUM(COALESCE(subscription_user.is_trial_effective, 0))            AS trial_effective_users,
       SUM(COALESCE(subscription_user.is_paid, 0))                       AS paid_users
FROM device_group
LEFT JOIN role_card_message ON role_card_message.user_id = device_group.account_id
LEFT JOIN total_message     ON total_message.user_id     = device_group.account_id
LEFT JOIN subscription_user ON subscription_user.user_id = device_group.account_id
GROUP BY device_group.group_name
ORDER BY entered_users DESC;

