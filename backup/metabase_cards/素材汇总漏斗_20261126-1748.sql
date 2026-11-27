-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-11-20:付费级补能量包 —— 这张卡的变现三级 11-11 起全瞎了          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   同「装机日素材漏斗」那张,两张卡口径一致,改动同步做。
--   【改之前是什么情况】订阅线 2026-11-10 彻底停售(最后一笔 TRIAL 和 INTRO 都在 11-10),
--   11-11 起全部成交都是能量包。而 `paid_users` 查的是 `soul_map.subscription`,
--   **一次性能量包不进这张表** ⇒ 变现三列从 11-06 起全 0(本卡窗口更长,更早见底)。
--   【改了什么】① 新增 `energy_buyer` CTE + `energy_buyers` / `energy_revenue_usd` 两列;
--   ② `paid_user` UNION 能量买家;③ 删 `intro_users` 列,`trial_effective_users` 留到窗口滑过。
--   🛑 **跨 11-10 不要把 `paid_users` 当同一口径比** —— 之前数订阅,之后数能量包。
--
-- 🔴 2026-11-05 加 / 11-06 更正:本卡跨 **2026-11-02 ~ 11-05** 不可比(投放侧切点)
--   投放把 Meta 优化目标从 install 改成 purchase,**11-02 起分批切,11-05 才全部切完**
--   (按 Meta 导出的 Result indicator:11-02 两个 B 类先切 → 11-04 Sander/Yui → 11-05 五个齐)。
--   🛑 原注释写「11-03 一次性切」是错的,切点要按区间处理。
--   后果:
--     · 日装机 630~894 → 75~172(−89%);CPI 0.15~0.20 → 0.605 → 1.051(×7)
--     · 四个 campaign 11-03 当天同时归零 —— Meta 按新目标重新分配了流量,
--       所以本卡**分组的构成本身变了**,不只是量变少了
--   🛑 **这是改优化目标的定义性后果,不是这些素材 / 广告组变差了。**
--      同期当日成交充值 9/6/9/8 → 8/8 一笔没掉,每笔充值成本 25.99/39.43
--      仍落在切换前的波动区间(18.23~38.78)内。
--   ⇒ 读法:**11-02 之前 / 11-05 之后当成两段,中间四天是过渡不单独读**。
--      判断素材 / 广告组好坏只在同一段内横比,
--      跨段比的是两套不同的流量分配。
--   出处:`_已落地改动台账.md` 切点总表「11-03(投放侧)」· 飞书「Meta 广告核对」`Sq7CFh`
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
-- 【展示形式】**表格**。三个理由:
--   ① 列太多:装机 → 发消息 → QCD(6句) → 累计20句 四级漏斗,外加发起购买 / 开过订阅 /
--      其中0.99 / 付费 四个变现列,再加 D1 / D7 两个留存率 —— 漏斗图放不下;
--   ② **每条素材的分母不同**(各自的装机数),跨素材比较必须把分母摆在同一行里看;
--   ③ 变现那几列是个位数,画成图会让人误读成有统计意义的差异。
--   🛑 读比率前先看 `installs` 列 —— 实测有素材 installs=14、D1=7 就显示 50%。
WITH user_first_launch AS (                       -- 每个用户最早一次启动的时间
  SELECT user_id, MIN(add_on) AS user_first_launch_at
  FROM soul_map.soulmap_app_launch
  WHERE user_id IS NOT NULL AND user_id <> ''
  GROUP BY user_id
),
cohort AS (                                  -- Meta 装机 cohort + 用户级归因
  SELECT launch.user_id COLLATE utf8mb4_unicode_ci        AS user_id,   -- app_launch 是 0900_ai_ci,统一到 unicode_ci
         DATE(launch.add_on)                              AS install_date,
         launch.creative                                  AS creative
  FROM soul_map.soulmap_app_launch AS launch
  JOIN user_first_launch ON user_first_launch.user_id      = launch.user_id
                   AND user_first_launch.user_first_launch_at = launch.add_on
  WHERE launch.add_on >= CURDATE() - INTERVAL 14 DAY   -- 右端不设界,放到当天,见头部 2026-09-07
    AND launch.network IN ('Facebook Installs', 'Off-Facebook Installs', 'Instagram Installs')
),
host_day AS (                                -- 一次扫描出 (用户, 角色, 日) 的消息数,
  SELECT chat.user_id                                                        AS user_id,   --    下面四项全从它派生
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
  -- 不限日期窗口:「累计 20 句」是全历史口径。对本卡无影响 —— cohort 取的是全历史最早一次
  -- 启动落在窗口内的用户,他们的消息本就都在窗口内。
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
  WHERE s.product_id NOT LIKE '%admin_test%'
    AND s.in_trial = 1
  GROUP BY s.user_id
  -- 上线后 7 个点过试用的用户里只有 4 个产生了试用订阅行,另 3 个一行都没有。
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
user_launch_day AS (                              -- 每个(用户, 启动日)一行,供回访判定
  SELECT user_id COLLATE utf8mb4_unicode_ci AS user_id, DATE(add_on) AS launch_date
  FROM soul_map.soulmap_app_launch
  WHERE add_on >= CURDATE() - INTERVAL 14 DAY
    AND user_id IS NOT NULL AND user_id <> ''
  GROUP BY user_id, launch_date
),
user_retention AS (                                -- 必须用一次性聚合,不要写 correlated EXISTS:
  SELECT cohort.user_id,                     --    那样每个用户都要重扫一遍 app_launch(14万行),实测跑不完
         MAX(user_launch_day.launch_date = cohort.install_date + INTERVAL 1 DAY)      AS retained_d1,
         MAX(user_launch_day.launch_date BETWEEN cohort.install_date + INTERVAL 5 DAY
                                       AND cohort.install_date + INTERVAL 9 DAY) AS retained_d7_window
  FROM cohort
  JOIN user_launch_day ON user_launch_day.user_id = cohort.user_id
  GROUP BY cohort.user_id
)
SELECT per_user.creative                                                      AS creative,
       MIN(per_user.install_date)                                             AS first_install_date,
       MAX(per_user.install_date)                                             AS last_install_date,
       -- ── 漏斗四级:严格嵌套(installs ⊇ first_message ⊇ qcd ⊇ 20msg),可直接读转化率
       COUNT(*)                                                               AS installs,
       SUM(depth_user.user_id IS NOT NULL)                                    AS reached_first_message,
       ROUND(SUM(depth_user.user_id IS NOT NULL) / COUNT(*), 4)                AS first_message_rate,
       -- 必须 COALESCE:LEFT JOIN 后若该 creative 无人发过消息,depth_user.* 全为 NULL,
       -- SUM(NULL >= 6) 得到的是 NULL 不是 0,会渲染成空白。
       SUM(COALESCE(depth_user.max_messages_in_one_day, 0) >= 6)              AS reached_qcd,
       ROUND(SUM(COALESCE(depth_user.max_messages_in_one_day, 0) >= 6)
             / COUNT(*), 4)                                                    AS qcd_rate,
       SUM(COALESCE(all_message_user.total_messages_all_time, 0) >= 20)       AS reached_20msg,
       ROUND(SUM(COALESCE(all_message_user.total_messages_all_time, 0) >= 20)
             / COUNT(*), 4)                                                    AS msg20_rate,
       -- ── 结果列:与漏斗并列,不是下一级(不聊天也能试用 / 付费 / 回访),分母同为 installs
       SUM(purchase_started_user.user_id IS NOT NULL)                            AS purchase_started_users,
       SUM(trial_effective_user.user_id IS NOT NULL)                          AS trial_effective_users,
       -- 2026-11-20 新增。能量包从 11-11 起是唯一还在成交的商品,见卡头。
       SUM(energy_buyer.user_id IS NOT NULL)                                  AS energy_buyers,
       ROUND(SUM(COALESCE(energy_buyer.energy_revenue_usd, 0)), 2)            AS energy_revenue_usd,
       SUM(paid_user.user_id IS NOT NULL)                                     AS paid_users,
       ROUND(SUM(COALESCE(user_retention.retained_d1, 0))
             / COUNT(*), 4)                                                    AS retained_d1_rate,
       ROUND(SUM(COALESCE(user_retention.retained_d7_window, 0))
             / COUNT(*), 4)                                                    AS retained_d7_window_rate
FROM per_user
LEFT JOIN depth_user       ON depth_user.user_id       = per_user.user_id
LEFT JOIN all_message_user ON all_message_user.user_id = per_user.user_id
LEFT JOIN purchase_started_user ON purchase_started_user.user_id = per_user.user_id
LEFT JOIN trial_effective_user ON trial_effective_user.user_id = per_user.user_id
LEFT JOIN energy_buyer   ON energy_buyer.user_id   = per_user.user_id
LEFT JOIN paid_user      ON paid_user.user_id      = per_user.user_id
LEFT JOIN user_retention ON user_retention.user_id = per_user.user_id
GROUP BY per_user.creative
ORDER BY installs DESC;
