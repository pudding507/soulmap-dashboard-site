-- 能量_两臂对照 · Energy — energy_v1 Arm Comparison
-- 2026-11-04 新建。出处:《产品玩法》§15.6 / §十一「正在跑的实验」。
--
-- ═══ 为什么要这张卡 ═══
--   `energy_v1` 2026-10-26 12:08 起分组(control 20% / energy 80%),
--   但**至今没有任何一张卡在比两臂** —— 能量系统到底让用户聊得更多还是更少,
--   现在没人答得上来。这张卡就干这一件事。
--
-- ═══ 🛑 只能比结果,不能比过程 ═══
--   control 臂的人**根本不进能量系统**(实测 997 人里 0 人有能量账户,这是符合设计的),
--   所以能量内部的指标(钱包、档位、撞卡)在 control 臂恒为空。
--   ⇒ **只能比两臂都有的结果指标**:开口、聊天深度、次日回来、付费。
--
-- ═══ 口径 ═══
--   ① 队列 = `experiment_assignment_v1` 里 `energy_v1` 且 `is_test=0` 的账号,
--      且 `user.create_time >= '2026-10-26'`(分组起点),
--      且 **注册满 2 天**(`<= CURDATE() - INTERVAL 2 DAY`)—— 不这么切,
--      最后两天的人 D1 窗口还没走完,会把 D1 一路拉低。
--   ② 🛑 **分到 `energy` 臂 ≠ 进了能量系统**(《产品玩法》§15.6):实测 arm='energy'
--      4,060 人里只有 64.2% 真有能量账户。本卡**按分臂读,不按「是不是能量用户」读** ——
--      这是对的,意向处理(ITT)才是随机分组能支持的结论;
--      但也因此 **energy 臂的效应被稀释了约三分之一**,看到的差要当成下界。
--   ③ `开口 / ≥5 条 / ≥20 条` 是**全历史累计**用户自己发的消息(`role='user'`),不限 host,
--      与护栏卡、adgroup 卡同口径。`次日回来` = 注册日 +1 自然日发过消息。
--   ④ `付费` 只数 `price_usd > 0` 且 `environment='PRODUCTION'` 的扣款。
--   ⑤ 只剔 9 个测试/沙盒号。2026-11-12 起 CityPLX 不再剔除,改成 `app_line` 一列并列(D-563)。
--      🛑 CityPLX 也被分进了 energy_v1(10-26 起 3,084 / 9,117),原来整批剔掉;
--         现在两条线各自算一套比率,**不要跨线比分臂** —— 两边的人群完全不同。
--   ⑥ 🛑 **先看 SRM**:control 占比应当在 20% 附近,偏了后面所有对比都不成立。
--
-- 输出:业务线 | 分臂 | 人数 | 占比 | 开口 | 开口率 | ≥5条 | ≥5率 | ≥20条 | ≥20率 | 次日回来 | D1率 | 付费人数 | 收入
WITH excluded_users AS (          -- 只剔测试 / 沙盒号
    SELECT id FROM soul_map.`user`
    WHERE id IN (62412, 72048, 72382, 72462, 74640,
                 74377, 74592, 71693, 71826)
),
cohort AS (
  SELECT u.id                                                      AS user_id,
         CAST(u.id AS CHAR) COLLATE utf8mb4_0900_ai_ci             AS user_key,
         DATE(u.create_time)                                       AS reg_date,
         CASE WHEN u.app_source = 'city'
              THEN 'CityPLX' ELSE 'SoulMap' END                    AS app_line,
         MAX(a.arm)                                                AS arm
  FROM   soul_map.experiment_assignment_v1 AS a
  JOIN   soul_map.`user` AS u ON u.id = CAST(a.analytics_user_key AS UNSIGNED)
  WHERE  a.experiment_id = 'energy_v1'
    AND  a.is_test = 0
    AND  u.create_time >= '2026-10-26'
    AND  u.create_time <= CURDATE() - INTERVAL 2 DAY       -- 见口径 ①:D1 窗口要走完
    AND  u.id NOT IN (SELECT id FROM excluded_users)
  GROUP  BY u.id, u.create_time, u.app_source
),
msgs AS (                      -- 只扫队列这批人,吃得上 idx_uid(user_id)
  SELECT ch.user_id                                                AS user_key,
         COUNT(*)                                                  AS total_messages
  FROM   soul_map.soulmap_chat_history AS ch
  JOIN   cohort ON cohort.user_key = ch.user_id
  WHERE  ch.role = 'user' AND ch.content IS NOT NULL AND ch.content <> ''
  GROUP  BY ch.user_id
),
d1 AS (                        -- 注册日 +1 自然日发过消息
  SELECT ch.user_id                                                AS user_key
  FROM   soul_map.soulmap_chat_history AS ch
  JOIN   cohort ON cohort.user_key = ch.user_id
  WHERE  ch.role = 'user' AND ch.content IS NOT NULL AND ch.content <> ''
    AND  DATE(ch.add_on) = cohort.reg_date + INTERVAL 1 DAY
  GROUP  BY ch.user_id
),
pay AS (
  SELECT e.user_id,
         SUM(e.price_usd)                                          AS revenue_usd
  FROM   soul_map.subscription_event_log AS e
  WHERE  COALESCE(e.price_usd, 0) > 0
    AND  e.environment = 'PRODUCTION'
  GROUP  BY e.user_id
)
SELECT cohort.app_line                                             AS app_line,
       cohort.arm                                                  AS arm,
       COUNT(*)                                                    AS users,
       -- 占比在**各自业务线内部**算,两条线的人群不同,合起来算没有意义
       ROUND(100.0 * COUNT(*)
             / SUM(COUNT(*)) OVER (PARTITION BY cohort.app_line), 1) AS share_pct,
       SUM(msgs.total_messages >= 1)                               AS spoke,
       ROUND(100.0 * SUM(msgs.total_messages >= 1) / COUNT(*), 1)  AS spoke_pct,
       SUM(msgs.total_messages >= 5)                               AS msg_ge5,
       ROUND(100.0 * SUM(msgs.total_messages >= 5) / COUNT(*), 1)  AS msg_ge5_pct,
       SUM(msgs.total_messages >= 20)                              AS msg_ge20,
       ROUND(100.0 * SUM(msgs.total_messages >= 20) / COUNT(*), 1) AS msg_ge20_pct,
       SUM(d1.user_key IS NOT NULL)                                AS returned_d1,
       ROUND(100.0 * SUM(d1.user_key IS NOT NULL) / COUNT(*), 1)   AS d1_pct,
       SUM(pay.user_id IS NOT NULL)                                AS payers,
       ROUND(SUM(COALESCE(pay.revenue_usd, 0)), 2)                 AS revenue_usd
FROM       cohort
LEFT JOIN  msgs ON msgs.user_key = cohort.user_key
LEFT JOIN  d1   ON d1.user_key   = cohort.user_key
LEFT JOIN  pay  ON pay.user_id   = cohort.user_id
GROUP BY   cohort.app_line, cohort.arm
ORDER BY   cohort.app_line, cohort.arm;

