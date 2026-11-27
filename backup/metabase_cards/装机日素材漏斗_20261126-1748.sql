-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-11-20:付费级补能量包 —— 这张卡的变现三级 11-11 起全瞎了          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【改之前是什么情况】查库实测:**订阅线 2026-11-10 彻底停了** ——
--   最后一笔免费试用(TRIAL)和最后一笔 0.99(INTRO)都在 11-10,
--   11-11 起全部成交都是能量包(每天约 20 人、近 14 天 400 笔)。
--   而本卡 `paid_users` 的口径是查 `soul_map.subscription` 表,
--   **一次性能量包根本不进这张表** ⇒ `trial_effective_users` / `intro_users` /
--   `paid_users` 三列从 11-10 起全 0,而同期 `purchase_started_users` 还有 12~15/天。
--   ⇒ **人在买,卡记不上。** 投放侧看素材 ROI 就靠这张卡,付费级断在「发起购买」。
--
--   【改了什么】
--   ① 新增 `energy_buyer` CTE + 两列 `energy_buyers` / `energy_revenue_usd`。
--   ② `paid_user` 改成 UNION 能量买家 —— 原来只从 subscription 出发,补不进来。
--   ③ 删掉 `intro_users` 列(0.99 已停售,窗口只有 14 天,很快永远是 0);
--      `trial_effective_users` **保留但已停售**,窗口滑过 11-10 之后它会恒为 0,
--      到时再删 —— 现在删会让 11-10 之前那几天的订阅数凭空消失。
--
--   🛑 **跨 11-10 不要把 `paid_users` 当成同一个口径比** ——
--      之前它数的是订阅(试用转全价 + 0.99),之后数的是能量包买家。两边不是一回事。
--
-- ═══ 🛑 2026-10-19:「付费」口径修正 + 新增 intro_users 列 ═══
--   实测:买过 0.99 的 43 人在 soul_map.subscription 里 **100% 是 in_trial=1**,一个 0 都没有;
--   对照免费试用 460 人里 439 人 in_trial=1、只有 21 人是 0。
--   ⇒ in_trial 的真实含义是「**这一行还在首期**」(免费试用期 或 0.99 首期),
--     in_trial=0 是「**已走过首期、按原价续上了**」。
--   原写法 `paid_user = in_trial 0` 因此**把全部 0.99 买家漏在外面** —— 他们明明付了钱。
--   改动:① paid_user 补 `OR 买过 INTRO`;② 新增 intro_users 列单独留痕。
--   影响:paid_users 会变大(补回 0.99 那批);trial_effective_users **不变**
--        (它数的是 in_trial=1,本来就同时含免费试用和 0.99,拿它减 intro_users 得纯免费试用数)。
--   与看板 24 的 400 `has_paid` / `has_intro` 完全同口径。
--   🛑 本卡是 385 的按装机日明细版,两张卡口径必须一起改,否则汇总对不上。
-- 【展示形式】**表格**。理由同上一张卡(385 按素材汇总版),本卡是它的按装机日明细版,
--   列结构与口径完全一致,只多一个 date 维度。
--   🛑 本卡有 `HAVING installs >= 10`,所以按 date 求和会略小于汇总表,不是漏数。
WITH user_first_launch AS (
  SELECT user_id, MIN(add_on) AS user_first_launch_at
  FROM soul_map.soulmap_app_launch
  WHERE user_id IS NOT NULL AND user_id <> ''
  GROUP BY user_id
),
cohort AS (
  SELECT launch.user_id COLLATE utf8mb4_unicode_ci   AS user_id,
         DATE(launch.add_on)                         AS install_date,
         launch.creative                             AS creative
  FROM soul_map.soulmap_app_launch AS launch
  JOIN user_first_launch ON user_first_launch.user_id      = launch.user_id
                   AND user_first_launch.user_first_launch_at = launch.add_on
  WHERE launch.add_on >= GREATEST(CURDATE() - INTERVAL 14 DAY, DATE('2026-08-15'))
    AND launch.network IN ('Facebook Installs', 'Off-Facebook Installs', 'Instagram Installs')
),
host_day AS (                                -- 一次扫描出 (用户, 角色, 日) 的消息数,下面三项全从它派生
  SELECT chat.user_id                                                        AS user_id,
         REPLACE(COALESCE(NULLIF(chat.host_id, ''), session.host_id),
                 'original:', '')                                            AS host_key,
         DATE(chat.add_on)                                                   AS chat_date,
         COUNT(*)                                                            AS user_messages
  FROM soul_map.soulmap_chat_history AS chat
  LEFT JOIN soul_map.soulmap_session AS session ON session.session_id = chat.session_id
  WHERE chat.role = 'user'
    AND chat.content IS NOT NULL AND chat.content <> ''
    AND COALESCE(NULLIF(chat.host_id,''), session.host_id) LIKE 'original:%'
  GROUP BY user_id, host_key, chat_date
  -- 不限日期窗口:「累计 20 句」是全历史口径。对本卡无影响,cohort 是窗口内的新用户。
),
depth_user AS (                              -- 用户级:发过角色卡消息 / QCD
  SELECT user_id,
         MAX(user_messages) AS max_messages_in_one_day    -- >=6 即 QCD_v1
  FROM host_day GROUP BY user_id
),
all_message_user AS (                        -- 全部用户消息的累计,不限 host
  SELECT user_id, COUNT(*) AS total_messages_all_time
  FROM soul_map.soulmap_chat_history
  WHERE role = 'user' AND content IS NOT NULL AND content <> ''
  GROUP BY user_id
),
post_launch_user AS (                        -- 付费上线后才建立订阅关系的用户,见头部
  SELECT user_id
  FROM (SELECT user_id, trial_started_at AS related_at
          FROM soul_map.subscription_user_state WHERE trial_used = 1
        UNION ALL
        SELECT user_id, start_time       AS related_at
          FROM soul_map.subscription WHERE product_id NOT LIKE '%admin_test%') AS rel
  GROUP BY user_id
  HAVING MIN(related_at) >= '2026-09-11'
),
purchase_started_user AS (                   -- ① 发起购买:埋点,用户在订阅墙上点了订阅按钮
  -- 2026-09-17 取代原 trial_clicked_user。原列取 subscription_user_state.trial_used,
  -- 实测它与 subscription.start_time **时间戳秒级完全相同**(7/7 对),
  -- 说明两者是同一事件写出的两条记录,不是「点击」与「商店确认」两个先后动作;
  -- 且该表会被账号 ID 漂移放大(实测一台设备 3 天换 5 个账号 ⇒ 一次试用产生 6 条 trial_used=1)。
  -- ⇒ 两列之差会被误读成「转化损失 71%」,实际为 0。改用埋点的真实点击事件。
  -- 成本:走 idx_event_name_date,EXPLAIN type=range/rows=256,实测 0.02~0.41s,可忽略。
  SELECT uid COLLATE utf8mb4_unicode_ci AS user_id
  FROM host.firebase_event
  WHERE event_name = 'purchase_started'
    AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 14 DAY, '%Y%m%d')
    AND uid <> '' AND uid IS NOT NULL
  GROUP BY uid
),
trial_effective_user AS (                    -- ② 试用生效:商店确认并建了试用订阅行
  SELECT CAST(s.user_id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_id
  FROM soul_map.subscription AS s
  JOIN post_launch_user ON post_launch_user.user_id = s.user_id
  WHERE s.product_id NOT LIKE '%admin_test%' AND s.in_trial = 1
  GROUP BY s.user_id
),
intro_user AS (                              -- ②.5 买过 0.99 首期的用户
  -- 🛑 判「0.99」只能看 subscription_event_log.period_type = 'INTRO',不能靠 product_id
  --    (product_id 写的是 monthly,但 0.99 的实际周期是 7 天)。与看板 24 的 400/406/420 同口径。
  SELECT DISTINCT CAST(user_id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_id
  FROM soul_map.subscription_event_log
  WHERE environment = 'PRODUCTION' AND period_type = 'INTRO'
),
energy_buyer AS (                            -- 2026-11-20 新增:买过能量的人 + 实收
  -- 🛑 判据只能用 `%energy%`,**不能写 `com.soulmap.energy.%`** —— 能量有三种商品形态,
  --    后一种写法会把订阅制那两个漏掉:
  --      com.soulmap.energy.lN              一次性能量包  NON_RENEWING_PURCHASE
  --      com.soulmap.plus.energy:prepaid-1m 预付月包      INITIAL_PURCHASE / PREPAID
  --      com.soulmap.plus.energy:monthly    订阅制能量    INITIAL_PURCHASE / NORMAL
  -- 🛑 也**不能拿 `event_type='NON_RENEWING_PURCHASE'` 当能量判据** ——
  --    通行证 `com.soulmap.pass.*` 也是这个 event_type,不是能量。
  -- 🛑 `price_usd` 在 TRIAL 行是 0,这里不含 TRIAL,所以可以直接求和。
  SELECT CAST(user_id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_id,
         SUM(COALESCE(price_usd, 0))                      AS energy_revenue_usd
  FROM soul_map.subscription_event_log
  WHERE environment = 'PRODUCTION'
    AND product_id LIKE '%energy%'
    AND event_type IN ('INITIAL_PURCHASE', 'NON_RENEWING_PURCHASE')
  GROUP BY user_id
),
paid_user AS (                               -- ③ 真正付过钱:订阅 **或** 能量,任一算数
  -- 2026-11-20:加 UNION 能量买家。原来只从 soul_map.subscription 出发,
  -- 而买一次性能量包的人**根本不在那张表里**,靠加 WHERE 条件补不进来,只能 UNION。
  SELECT CAST(s.user_id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_id
  FROM soul_map.subscription AS s
  JOIN post_launch_user ON post_launch_user.user_id = s.user_id
  WHERE s.product_id NOT LIKE '%admin_test%'
    AND (s.in_trial = 0                      -- 走完首期、按原价续上的
         OR CAST(s.user_id AS CHAR) COLLATE utf8mb4_unicode_ci
            IN (SELECT user_id FROM intro_user))   -- 2026-10-19 补:买 0.99 的人
  GROUP BY s.user_id
  UNION                                      -- UNION 去重,同时买过订阅和能量的只算一次
  SELECT user_id FROM energy_buyer
),
per_user AS (                                -- 收敛到用户级,避免 cohort 里同一用户的重复行放大计数
  SELECT cohort.user_id, cohort.creative, cohort.install_date
  FROM cohort
  GROUP BY cohort.user_id, cohort.creative, cohort.install_date
),
user_launch_day AS (                         -- 每个(用户, 启动日)一行,供回访判定
  SELECT user_id COLLATE utf8mb4_unicode_ci AS user_id, DATE(add_on) AS launch_date
  FROM soul_map.soulmap_app_launch
  WHERE add_on >= CURDATE() - INTERVAL 25 DAY   -- 比 cohort 窗口宽,够覆盖最早装机日 +9 天
    AND user_id IS NOT NULL AND user_id <> ''
  GROUP BY user_id, launch_date
),
user_retention AS (                          -- 必须一次性聚合,不要写 correlated EXISTS
  SELECT cohort.user_id,
         MAX(user_launch_day.launch_date = cohort.install_date + INTERVAL 1 DAY)  AS retained_d1,
         MAX(user_launch_day.launch_date BETWEEN cohort.install_date + INTERVAL 5 DAY
                                       AND cohort.install_date + INTERVAL 9 DAY)  AS retained_d7_window
  FROM cohort
  JOIN user_launch_day ON user_launch_day.user_id = cohort.user_id
  GROUP BY cohort.user_id
)
SELECT per_user.install_date                                                  AS `date`,
       per_user.creative                                                      AS creative,
       -- ── 漏斗四级:严格嵌套(installs ⊇ first_message ⊇ qcd ⊇ 20msg)
       COUNT(*)                                                               AS installs,
       SUM(depth_user.user_id IS NOT NULL)                                    AS reached_first_message,
       ROUND(SUM(depth_user.user_id IS NOT NULL) / COUNT(*), 4)                AS first_message_rate,
       SUM(COALESCE(depth_user.max_messages_in_one_day, 0) >= 6)              AS reached_qcd,
       ROUND(SUM(COALESCE(depth_user.max_messages_in_one_day, 0) >= 6)
             / COUNT(*), 4)                                                    AS qcd_rate,
       SUM(COALESCE(all_message_user.total_messages_all_time, 0) >= 20)       AS reached_20msg,
       ROUND(SUM(COALESCE(all_message_user.total_messages_all_time, 0) >= 20)
             / COUNT(*), 4)                                                    AS msg20_rate,
       -- ── 变现三级:①⊇②,量级极小故不配率
       SUM(purchase_started_user.user_id IS NOT NULL)                            AS purchase_started_users,
       SUM(trial_effective_user.user_id IS NOT NULL)                          AS trial_effective_users,
       -- 2026-11-20 新增。能量包从 11-11 起是唯一还在成交的商品,见卡头。
       SUM(energy_buyer.user_id IS NOT NULL)                                  AS energy_buyers,
       ROUND(SUM(COALESCE(energy_buyer.energy_revenue_usd, 0)), 2)            AS energy_revenue_usd,
       SUM(paid_user.user_id IS NOT NULL)                                     AS paid_users,
       -- ── 留存:分母同为该素材-日的装机数
       ROUND(SUM(COALESCE(user_retention.retained_d1, 0))
             / COUNT(*), 4)                                                    AS retained_d1_rate,
       ROUND(SUM(COALESCE(user_retention.retained_d7_window, 0))
             / COUNT(*), 4)                                                    AS retained_d7_window_rate
FROM per_user
LEFT JOIN depth_user           ON depth_user.user_id           = per_user.user_id
LEFT JOIN all_message_user     ON all_message_user.user_id     = per_user.user_id
LEFT JOIN purchase_started_user ON purchase_started_user.user_id = per_user.user_id
LEFT JOIN trial_effective_user ON trial_effective_user.user_id = per_user.user_id
LEFT JOIN energy_buyer         ON energy_buyer.user_id         = per_user.user_id
LEFT JOIN paid_user            ON paid_user.user_id            = per_user.user_id
LEFT JOIN user_retention       ON user_retention.user_id       = per_user.user_id
GROUP BY per_user.install_date, per_user.creative
HAVING installs >= 10                        -- 分母低于 10 的素材-日没有参考价值
-- 行序有含义(按天倒序),看板注册表里不要写 sort。
ORDER BY `date` DESC, installs DESC;
