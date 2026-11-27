-- 🔴 2026-11-04 新增「找回成交」一列:此前付费笔数系统性少算。
--    埋点字典 11-04 版收的客户端 253:`purchase_recovered`(10-16 起,3.7.x 之后的包都有)
--    —— **这一笔不会再发 `purchase_completed`**,所以只数 `purchase_completed` 会漏掉它。
--    实测近 21 天 `purchase_recovered` 20 笔 vs `purchase_completed` 约 108 笔,
--    **漏掉约 15%**;事件带 `product_id`(全部 plus.monthly)和 `trigger`
--    (message_quota 14 / launch_prompt 4 / create_character 2)。
--    🛑 **单列一列,不折进 `purchase_completed_users`** —— 找回事件**不带 `is_trial`**,
--       折进去会破坏 `completed_paid_now + completed_trial_only = purchase_completed_users`
--       这个恒等式。**真实成交 = `purchase_completed_users` + `purchase_recovered_users`。**
--    🛑 这一列不进左半四列的 `product_id` 限定(找回事件实测全是 plus.monthly)。
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-10-29:`soul_map.subscription` 里混着**沙盒订阅**,本卡此前全算进去了 ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   这张表**没有 `environment` 列**(和 `subscription_event_log` 不一样),
--   但 `raw_payload` 里有 `subscriptions.<product_id>.is_sandbox`。
--   实测(按本卡原来的过滤 `product_id NOT LIKE '%admin_test%'`):
--     算进来、不是沙盒 786 行 / 613 人 · **算进来、是沙盒 97 行 / 15 人** · 被 admin_test 排掉 28 行 / 4 人
--   近 14 天命中:10-29 `plus.energy` 1 人 · 10-22 / 10-21 / 10-18 各 1 人(`plus.monthly`)。
--   🛑 **全库只占 2.4%,但落在命中那几天就是当天 6~17 人里的 1 个**,
--      右半边的订阅列(试用生效 / 0.99 / 付费 / Apple / Google)都会多算。
--   ⇒ 本卡读 `soul_map.subscription` 的**两处**都加 `raw_payload NOT LIKE '%"is_sandbox":true%'`。
--   🛑 改后 10-18 / 10-21 / 10-22 / 10-29 的订阅数各少 1 人,**是修正不是掉量**。
--   🛑 沙盒行的特征是「同一人同一商品、每行只活约 5 分钟」(加速续订),
--      认它**不要靠这个特征去猜**,直接读 `is_sandbox`。
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑 2026-10-29:商店里多了三类非订阅商品,付费口径必须按 product_id 限定      ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【两个断点】
--     · **2026-10-22** 「买 3 天」通行证开始有真实购买(服务端 10-19 就绪)
--     · **2026-10-28 14:32:20** 能量系统上线(能量包 L1~L6 + 能量版 Plus 订阅)
--   三类商品**和月订阅共用 `purchase_started` / `purchase_completed` 两个事件**,
--   也**一起进 `soul_map.subscription_event_log`** —— 不加限定就会被算成订阅。
--
--   【2026-10-29 实测,全时段】
--     purchase_started    : plus.monthly 4,299 · (无 product_id) 99(04-15~09-28,老客户端)
--                           pass.3day 15 · one.monthly 10(已停用) · energy.l2 3
--                           · plus.energy:monthly 1 · energy.l1 1 · energy.l6 1
--     purchase_completed  : plus.monthly 485 · pass.3day 7 · energy.l2 1
--     purchase_recovered  : 只有 plus.monthly 12 笔,**不受影响**
--     subscription_event_log(全时段,按 event_type):
--       🛑 **按 `environment` 拆开看**(2026-10-29 复核补):
--       pass.3day        NON_RENEWING_PURCHASE  PRODUCTION 6 笔 $6.53(10-24~10-28)· SANDBOX 2 笔(10-23)
--       energy.l1        NON_RENEWING_PURCHASE  PRODUCTION 1 笔 $0.51(10-28)
--       energy.l2        NON_RENEWING_PURCHASE  **SANDBOX** 1 笔 $0.99(10-28)
--       plus.energy:monthly  **9 笔全部 SANDBOX**(10-28 19:07~19:43)—— 生产一笔都没有
--       ⇒ `price_usd > 0` 的行只有三种 event_type:INITIAL_PURCHASE / RENEWAL / NON_RENEWING_PURCHASE。
--         所以「排掉 NON_RENEWING_PURCHASE」和「只留前两种」在当前数据上**等价**;
--         本卡用前者(黑名单),将来多一种付费 event_type 时不会被静默漏掉。
--
--   🛑 **不能靠 `is_trial` 或 `period_type` 区分** —— 非订阅商品是
--      `is_trial=false` / `period_type=NORMAL`,但月订阅的「当场付清」(0.99 和全价)
--      也是 `is_trial=false`。**只能靠 `product_id`(埋点)或 `event_type`(服务端)。**
--
--   🛑 **两张表的 product_id 写法不一样**:`subscription_event_log` 写
--      `com.soulmap.plus.energy:monthly`,`soul_map.subscription` 写
--      `com.soulmap.plus.energy`(无 `:monthly`)。**按 product_id join 两张表会静默漏行。**
--
--   🛑 跨 10-22 / 10-28 和更早的数据比时,**旧数里这三类是混着的**,不是本卡改坏了。
--   【本卡改动】`purchase_started` / `purchase_completed` / `completed_paid_now`
--     / `completed_trial_only` 四处都限定到 `plus.monthly`(并放行老客户端的 NULL);
--     非订阅购买**不丢**,新开 `energy_pack_users` / `pass3day_users` 两列单列。
--     🛑 这两列和订阅那几列是**并列的三类**,不是上下级,不要相加。
--     能量包的第一个读数就在这里(B3 的专卡还没建)。
--
-- ═══ 🛑 2026-10-19:「付费」口径修正 + 新增 intro_users 列 ═══
--   实测:买过 0.99 的 43 人在 soul_map.subscription 里 **100% 是 in_trial=1**,一个 0 都没有;
--   对照免费试用 460 人里 439 人 in_trial=1、只有 21 人是 0。
--   ⇒ in_trial 的真实含义是「**这一行还在首期**」(免费试用期 或 0.99 首期),
--     in_trial=0 是「**已走过首期、按原价续上了**」,全库只有 21 人。
--   原写法 paid_date 只认 in_trial=0,**把全部 0.99 买家漏在外面**。
--   改动:① paid_date 取「续上日」与「买 0.99 日」的**较早者**(不是两者都算,避免一个人计两天);
--        ② 新增 intro_users 列;③ CROSS JOIN 的日期集合补上 intro_date,否则只在 0.99 那天有购买
--           的用户会因为日期不在集合里而整行消失。
--   影响:paid_users 变大;trial_effective_users **不变**(它数 in_trial=1,本就含 0.99)。
--   与看板 24 的 400 `has_paid` / `has_intro` 同口径。
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-10-16：加四列，把 0.99 和免费试用拆开                              ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   **本卡原来读不出 0.99，但不是因为漏数** —— `purchase_completed` 一直都含
--   0.99 当场付清的人，只是和「开了免费试用」混在同一个数里。
--
--   客户端 params 里本来就有区分字段，这次把它们用起来：
--     · `paywall_viewed.offer_kind`  —— **2026-10-14 起**有。`paid` = 墙上展示 0.99 ·
--       `free` = 展示免费试用 · `none`。实测 10-14~10-15：paid 255 条 · free 41 · none 40 ·
--       **无此字段 646 条（老客户端）**。
--       ⇒ 🛑 **`paywall_users_paid + paywall_users_free` 会小于 `paywall_users`**，
--         差的是老客户端那批，**不是漏数**。
--       ⇒ 🔴 **所以必须用 `paywall_users_with_kind` 当分母，不要用 `paywall_users`。**
--         前者 = 有 `offer_kind` 这个字段的人数。实测 10-14~10-15 共 982 条曝光里
--         **646 条(66%)来自老客户端、没有这个字段** —— 拿 `paywall_users` 当分母
--         会把「有字段的人里有多少看到 0.99」读成「全部人里只有这么多看到 0.99」，差一倍以上。
--       ⇒ 覆盖率会随客户端版本上来而好转，**在那之前这三列只能内部看，不要对外引用比率**。
--     · `purchase_completed.is_trial` —— 一直都有。`false` = 当场付清（0.99 或全价）·
--       `true` = 只开了免费试用。
--       ⇒ `completed_paid_now + completed_trial_only = purchase_completed_users`。
--
--   🛑 **0.99 放量后客户端还新增了 `period_type` / `offer_kind` 两个字段**，
--      但只在部分上报里出现（实测 10-15 的 12 条里带 `period_type` 的只有 6 条），
--      **覆盖还不全，所以本卡用 `is_trial` 而不用 `period_type`** —— 前者一直都有。
--
-- 【展示形式】**表格**,一行一天。三个理由:
--   ① 一天里要并排读付费墙曝光 → 发起购买 → 购买成功 → 开过订阅 → 其中0.99 → 付费
--      六七个环节的人数和比率,折线叠不下;
--   ② **分母每天在动**(当天付费墙曝光人数),比率画成折线会把分母的变化藏起来;
--   ③ 渠道(Apple / Google)是横切、阶段是纵切,同一批人的两种拆法 —— 表格里并列更清楚,
--      画在一张图上会让人误以为能相加。
WITH ev AS (
  SELECT STR_TO_DATE(event_date, '%Y%m%d')                                   AS d,
         COUNT(DISTINCT CASE WHEN event_name='paywall_viewed'     THEN uid END) AS paywall_users,
         COUNT(DISTINCT CASE WHEN event_name='paywall_viewed'
                              AND params ->> '$.source' = 'expert_activation' THEN uid END) AS expert_paywall_users,
         COUNT(DISTINCT CASE WHEN event_name='paywall_viewed'
                              AND params ->> '$.source' = 'plus_sheet'        THEN uid END) AS plus_paywall_users,
         -- 🔴 2026-10-29 新增 product_id 限定(见卡头断点说明)。
         COUNT(DISTINCT CASE WHEN event_name='purchase_started'
                              AND (params ->> '$.product_id' = 'com.soulmap.plus.monthly'
                                   OR params ->> '$.product_id' IS NULL) THEN uid END) AS purchase_started_users,
         -- 🔴 2026-10-16 新增：按墙上展示的档位拆曝光。客户端 `paywall_viewed` 的 params
         --    从 2026-10-14 起带 `offer_kind`（paid = 展示 0.99 · free = 展示免费试用 · none）。
         --    🛑 老客户端没有这个字段，落在 (NULL)，**三列相加会小于 paywall_users**。
         -- 🔴 2026-10-16 复核后补：**这两列的分母**。老客户端没有 offer_kind，
         --    不出这一列的话，读的人（尤其 AI）会拿 paid 去除 paywall_users，
         --    把「有档位字段的人里有多少看到 0.99」读成「全部人里只有这么多看到 0.99」。
         COUNT(DISTINCT CASE WHEN event_name='paywall_viewed'
                              AND params ->> '$.offer_kind' IS NOT NULL THEN uid END) AS paywall_users_with_kind,
         COUNT(DISTINCT CASE WHEN event_name='paywall_viewed'
                              AND params ->> '$.offer_kind' = 'paid' THEN uid END) AS paywall_users_paid,
         COUNT(DISTINCT CASE WHEN event_name='paywall_viewed'
                              AND params ->> '$.offer_kind' = 'free' THEN uid END) AS paywall_users_free,
         COUNT(DISTINCT CASE WHEN event_name='purchase_completed'
                              AND (params ->> '$.product_id' = 'com.soulmap.plus.monthly'
                                   OR params ->> '$.product_id' IS NULL) THEN uid END) AS purchase_completed_users,
         -- 🔴 2026-10-16 新增：把「完成付款」按 `is_trial` 拆开。
         --    🛑 `purchase_completed` **一直都含 0.99**，不是漏数 —— 但
         --    「当场付清 0.99」和「开了免费试用」混在一个数里，口径上是两回事。
         COUNT(DISTINCT CASE WHEN event_name='purchase_completed'
                              AND (params ->> '$.product_id' = 'com.soulmap.plus.monthly'
                                   OR params ->> '$.product_id' IS NULL)
                              AND params ->> '$.is_trial' = 'false' THEN uid END) AS completed_paid_now,
         COUNT(DISTINCT CASE WHEN event_name='purchase_completed'
                              AND (params ->> '$.product_id' = 'com.soulmap.plus.monthly'
                                   OR params ->> '$.product_id' IS NULL)
                              AND params ->> '$.is_trial' = 'true'  THEN uid END) AS completed_trial_only,
         -- 🔴 2026-10-29 新增：非订阅购买单独成列，不丢数（见卡头断点说明）。
         --    这两列和上面的订阅列是**并列的三类**，不是上下级，不要相加。
         COUNT(DISTINCT CASE WHEN event_name='purchase_completed'
                              AND params ->> '$.product_id' LIKE 'com.soulmap.energy.%' THEN uid END) AS energy_pack_users,
         COUNT(DISTINCT CASE WHEN event_name='purchase_completed'
                              AND params ->> '$.product_id' = 'com.soulmap.pass.3day'   THEN uid END) AS pass3day_users,
         COUNT(DISTINCT CASE WHEN event_name='purchase_failed'
                              AND params ->> '$.is_user_cancel' = 'true'      THEN uid END) AS purchase_canceled_users,
         -- 🔴 2026-11-04 新增。见卡头同日说明:找回的那一笔**不会再发 purchase_completed**,
         --    单列一列,不折进上面的 completed —— 折进去会破坏
         --    `completed_paid_now + completed_trial_only = purchase_completed_users`
         --    这个恒等式(找回事件不带 `is_trial`,拆不开)。
         COUNT(DISTINCT CASE WHEN event_name='purchase_recovered'
                             THEN uid END)                       AS purchase_recovered_users,
         COUNT(DISTINCT CASE WHEN event_name='restore_completed'
                              AND JSON_EXTRACT(params,'$.restored') = 1 THEN uid END) AS restore_success_users
  FROM host.firebase_event
  WHERE event_date >= DATE_FORMAT(CURDATE() - INTERVAL 14 DAY, '%Y%m%d')
    AND event_name IN ('paywall_viewed','purchase_started','purchase_completed',
                       'purchase_failed','restore_completed',
                       'purchase_recovered')   -- 🔴 2026-11-04 新增,见卡头
  GROUP BY d
),
post_launch_user AS (                             -- 付费功能 2026-09-11 正式上线,此前的订阅行是上线前测试
  SELECT user_id
  FROM (SELECT user_id, trial_started_at AS related_at
          FROM soul_map.subscription_user_state WHERE trial_used = 1
        UNION ALL
        SELECT user_id, start_time       AS related_at
          FROM soul_map.subscription
          WHERE product_id NOT LIKE '%admin_test%'
            AND raw_payload NOT LIKE '%"is_sandbox":true%') AS rel
  GROUP BY user_id
  HAVING MIN(related_at) >= '2026-09-11'
),
sub_first AS (                                    -- 每人**首次**达成各阶段的日期,与额度墙卡 MIN(DATE(start_time)) 同口径
  -- 2026-09-14:原写法按 DATE(created_at) 逐日 COUNT(DISTINCT),同一用户跨天开多行会被重复计
  -- (实测用户 53889 近 14 天 7 行、跨 6 天 ⇒ 会显示成 6 个人)。改为取首次达成日。
  -- 窗口不在此裁:要先看**全历史**才能判断"首次",裁窗口放到下面 sub。
  -- 2026-10-19:paid_date 补上 0.99。原来只认 in_trial=0,那是「走完首期按原价续上」,
  --   买 0.99 的人 in_trial 恒为 1 ⇒ 他们一个都不算付费。见本卡头部说明。
  -- 🛑 intro 那张子表的 event_at 是 **UTC**,而 subscription.start_time 是 SGT,
  --   必须 CONVERT_TZ 之后再 DATE(),否则两边差 8 小时、跨日的会归错天。
  SELECT s.user_id                                                            AS user_id,
         MIN(CASE WHEN s.in_trial=1        THEN DATE(s.start_time) END)       AS trial_effective_date,
         MIN(intro.intro_date)                                                AS intro_date,
         NULLIF(LEAST(
           COALESCE(MIN(CASE WHEN s.in_trial=0 THEN DATE(s.start_time) END), '9999-12-31'),
           COALESCE(MIN(intro.intro_date),                                    '9999-12-31')
         ), '9999-12-31')                                                     AS paid_date,
         MIN(CASE WHEN s.channel='APPLE'   THEN DATE(s.start_time) END)       AS apple_date,
         MIN(CASE WHEN s.channel='GOOGLE'  THEN DATE(s.start_time) END)       AS google_date
  FROM soul_map.subscription AS s
  JOIN post_launch_user AS p ON p.user_id = s.user_id
  LEFT JOIN (SELECT user_id,
                    MIN(DATE(CONVERT_TZ(event_at, '+00:00', '+08:00')))       AS intro_date
             FROM soul_map.subscription_event_log
             WHERE environment = 'PRODUCTION' AND period_type = 'INTRO'
             GROUP BY user_id) AS intro ON intro.user_id = s.user_id
  WHERE s.product_id NOT LIKE '%admin_test%'        -- 后台手动授予(adminGrant),不是购买
    AND s.raw_payload NOT LIKE '%"is_sandbox":true%'   -- 🔴 2026-10-29 新增:沙盒订阅,见卡头
  GROUP BY s.user_id
),
sub AS (                                          -- 按首次达成日归属,一个用户在每列只计一次
  SELECT d,
         COUNT(DISTINCT CASE WHEN trial_effective_date = d THEN user_id END)  AS trial_effective_users,
         COUNT(DISTINCT CASE WHEN intro_date           = d THEN user_id END)  AS intro_users,
         COUNT(DISTINCT CASE WHEN paid_date            = d THEN user_id END)  AS paid_users,
         -- 渠道是横切、阶段是纵切,同一批人的两种拆法,不要相加
         COUNT(DISTINCT CASE WHEN apple_date           = d THEN user_id END)  AS new_subscription_apple,
         COUNT(DISTINCT CASE WHEN google_date          = d THEN user_id END)  AS new_subscription_google
  FROM sub_first
  CROSS JOIN (SELECT DISTINCT d FROM
               (SELECT trial_effective_date d FROM sub_first UNION
                SELECT intro_date           FROM sub_first UNION
                SELECT paid_date            FROM sub_first UNION
                SELECT apple_date           FROM sub_first UNION
                SELECT google_date          FROM sub_first) x
              WHERE d IS NOT NULL AND d >= CURDATE() - INTERVAL 14 DAY) AS cal_sub
  GROUP BY d
),
cal AS (SELECT d FROM ev UNION SELECT d FROM sub)
SELECT cal.d                                                    AS `date`,
       COALESCE(ev.paywall_users, 0)                            AS paywall_users,
       COALESCE(ev.expert_paywall_users, 0)                     AS expert_paywall_users,
       COALESCE(ev.plus_paywall_users, 0)                       AS plus_paywall_users,
       COALESCE(ev.paywall_users_with_kind, 0)                  AS paywall_users_with_kind,
       COALESCE(ev.paywall_users_paid, 0)                       AS paywall_users_paid,
       COALESCE(ev.paywall_users_free, 0)                        AS paywall_users_free,
       COALESCE(ev.purchase_started_users, 0)                   AS purchase_started_users,
       ROUND(ev.purchase_started_users
             / NULLIF(ev.paywall_users, 0), 4)                  AS purchase_started_rate,
       COALESCE(ev.purchase_completed_users, 0)                 AS purchase_completed_users,
       COALESCE(ev.purchase_recovered_users, 0)                 AS purchase_recovered_users,
       COALESCE(ev.completed_paid_now, 0)                       AS completed_paid_now,
       COALESCE(ev.completed_trial_only, 0)                     AS completed_trial_only,
       COALESCE(ev.energy_pack_users, 0)                        AS energy_pack_users,
       COALESCE(ev.pass3day_users, 0)                           AS pass3day_users,
       COALESCE(ev.purchase_canceled_users, 0)                  AS purchase_canceled_users,
       COALESCE(sub.trial_effective_users, 0)                   AS trial_effective_users,
       COALESCE(sub.intro_users, 0)                             AS intro_users,
       COALESCE(sub.paid_users, 0)                              AS paid_users,
       COALESCE(sub.new_subscription_apple, 0)                  AS new_subscription_apple,
       COALESCE(sub.new_subscription_google, 0)                 AS new_subscription_google,
       COALESCE(ev.restore_success_users, 0)                    AS restore_success_users
FROM cal
LEFT JOIN ev          ON ev.d          = cal.d
LEFT JOIN sub         ON sub.d         = cal.d
-- ⚠️ 行序有含义(按天倒序),看板注册表里**不要写 sort**。
ORDER BY `date` DESC;

