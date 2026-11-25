-- 🔴 2026-11-03 口径分母:新增 `能量用户 Energy Users` 一列 ——
--    🛑 **本卡的人数要除这一列,不要除 DAU、不要除当天新注册,更不要除实验分组的 arm='energy'。**
--    实测 `experiment_assignment_v1` 里 arm='energy' 共 4,060 人,其中只有 2,607 人
--    (**64.2%**)真的进了能量系统;拿分组当分母会把所有占比系统性压低约三分之一。
--    (control 组 997 人里**一个都没进**,这是符合设计的,不是漏数。)
--    定义:在 `soulmap_energy_account` 里有行 —— 客户端 build 带能量 **且** 服务端对他下发,
--    两个条件都满足服务端才会建这一行,所以它就是「真的在能量系统里」的服务端口径。
--    剔 CityPLX 和 9 个测试/沙盒号后,截至 2026-11-03 共 **2,634 人**,
--    其中上线(10-28 14:32:20)前注册的老用户只有 **36 人**,其余全是上线后的新注册。
--    🛑 **这是「截至当天累计在册」的存量分母,不是当天活跃数** —— 占比天然随天数走低,
--       要看当天活跃请拿本卡同一天各行的人数自己比。
--    🛑 **分母本身每天在变**:新注册里真正进能量的比例 10-29 **51.8%** → 10-30 71.9%
--    → 10-31 75.1% → 11-01 68.6% → 11-02 74.8% → 11-03 **79.3%**,还在爬。
--    ⇒ 跨天比占比时分子分母**两头都在动**,不要只盯分子。
-- 🔴 2026-11-02:内部测试号名单统一为 9 个 —— 原名单基础上加 74377 / 74592 / 71693 / 71826,
--    都是康在正式包里用安卓许可测试号买的(康 247 自报)。`environment='SANDBOX'`,
--    其中 71693 / 71826 各 1 次首购 + 6 次 5 分钟沙盒续费($12.99×7),不按 environment 过滤会凭空多出约 $182。
--    🛑 本次改动**不改变任何现有数字**(实测加不加这两个号,能量包都是 43 笔 / 25 人 / $41.76)——
--    它们没有能量流水,订阅金额本来就按 environment 排掉了。这是预防性统一,防以后漏。
-- 🔴 2026-10-31:名单补 `74640` —— Javier 的 10-20~10-30 完整 changelog §4
--    把它列为测试账号,§3(10-30 11:37)又写明「先在测试号 74640 上试」。
--    实测它在能量表里有数(txn 5 / lot 1 / trial_use 1),不剔会混进读数。
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 能量_免费语音体验 · Energy — Free Voice Trial  2026-10-29 新建(玩法 §15.5)║
-- ╚══════════════════════════════════════════════════════════════════════════╝
-- 【展示形式】**表格**,一行 = 一天 × 种类(语音回复 / 语音消息)。两个理由:
--   ① 两种语音的**免费次数各 4 次、单价不同**(语音回复 $0.0127、语音消息 $0.0257),
--      合成一条线会把两件事平均掉;
--   ② 现在一天几十次、个位数人,折线全是贴地的点,要的是精确读数。
--
-- ═══ 🛑 口径(产品玩法 §15.5 末)═══
--   ① 🔴 **免费语音体验不用能量,是单独计数的** —— 4 次语音回复 + 4 次 🔊,
--      走 `soulmap_energy_trial_use`,**不进 `soulmap_energy_txn`**。
--      ⇒ **不要把这张卡的次数和「能量_每天进出」里的 `voice` / `tts` 扣费相加**,
--        那是免费额度用完**之后**才开始扣的,两者是前后两段,不是同一批。
--   ② `kind` 两种:`voice` = 语音回复(Host 用声音回)· `tts` = 语音消息 🔊(把文字读出来)。
--      🛑 **重听免费、生成失败不收费**,所以这里的「次数」是**计入免费额度的次数**,
--        不等于用户听到声音的次数。
--   ③ `refunded_at` 不为空 = 退回了这一次免费额度(生成失败等)。
--      📌 建卡时(2026-10-29)实测**一次退回都没有**;**2026-11-02 复测已经有了**,
--      而且不是偶发 —— **「语音回复」连续五天都在两到四成**,「语音消息 🔊」始终是 0:
--        | 日期  | 语音回复 次数 | 退回 | 退回率 |
--        | 10-29 |  16 |  2 | 12.5% |
--        | 10-30 |  88 | 36 | **40.9%** |
--        | 10-31 | 146 | 47 | 32.2% |
--        | 11-01 | 101 | 33 | 32.7% |
--        | 11-02 |  83 | 21 | 25.3% |
--      🛑 **退回率要用 `退回 ÷ 次数` 读,不要只看绝对数**。
--      🔴 **两到四成的免费语音回复生成失败,而且只发生在「语音回复」这一种上** ——
--        `tts`(把文字读出来)五天 1,543 次只退回 1 次。两条路的失败率差两个量级,
--        说明问题出在语音**生成**那一路,不是播放或额度。⬜ 要去语音侧的卡和服务端日志查。
--   ④ 起点 **2026-10-28 14:32:20**,同「能量_每天进出」卡头口径 ①。
--      🛑 实测首行在 **2026-10-29 01:29:50** —— 比能量系统本身晚约 11 小时,
--        不是漏数,是这个功能当天才有人用到。
--   ⑤ 只剔 9 个测试 / 沙盒号。2026-11-12 起 CityPLX 不再剔除,改成 `app_line` 一列并列(D-563);
--      实测能量各表里 CityPLX 0 行,这一列目前恒为 SoulMap。
--   🛑 **免费 4 次是按人按种类算的**,本卡给 `users` 和 `uses_per_user` 两列:
--      `uses_per_user` **接近 4 就说明这批人快用完了**,该看后面的付费转化。

WITH
energy_population AS (   -- 🔴 2026-11-03 新增:**真·能量用户**,本卡所有人数的分母
  -- 有 `soulmap_energy_account` 行 = 服务端真的给他开了能量账户
  -- (客户端 build 带能量 + 服务端对他下发,两个条件都满足才会有这一行)。
  SELECT ea.user_id,
         DATE(ea.started_at)                                       AS joined_date
  FROM   soul_map.soulmap_energy_account AS ea
  -- 剔除走数值侧比,不要 CAST(u.id AS CHAR),见「能量_每天进出」卡头那一段
  LEFT JOIN soul_map.`user` AS u ON u.id = CAST(ea.user_id AS UNSIGNED)
  WHERE  (u.id IS NULL OR u.id NOT IN (62412, 72048, 72382, 72462, 74640, 74377, 74592, 71693, 71826))
),
energy_base AS (         -- 逐日:当天新进能量系统的人 + 截至当天累计在册的人
  SELECT joined_date                                               AS base_date,
         COUNT(*)                                                  AS new_energy_users,
         SUM(COUNT(*)) OVER (ORDER BY joined_date)                 AS energy_users_cum
  FROM   energy_population
  GROUP  BY joined_date
),
trial AS (
  SELECT DATE(tu.created_at)   AS date_use,
         CASE WHEN u.app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line,
         tu.kind,
         tu.user_id,
         tu.refunded_at
  FROM   soul_map.soulmap_energy_trial_use AS tu
  -- 🛑 剔除走数值侧比,不要 CAST(u.id AS CHAR),见「能量_每天进出」卡头。
  LEFT JOIN soul_map.`user` AS u ON u.id = CAST(tu.user_id AS UNSIGNED)
  WHERE  tu.created_at >= GREATEST('2026-10-28 14:32:20',
                                   CURDATE() - INTERVAL 14 DAY)
    AND  (u.id IS NULL OR u.id NOT IN (62412, 72048, 72382, 72462, 74640, 74377, 74592, 71693, 71826))
)
SELECT trial.date_use                                                    AS `date`,
       trial.app_line                                                    AS app_line,
       CASE trial.kind
            WHEN 'voice' THEN '语音回复 Voice Reply(免费 4 次)'
            WHEN 'tts'   THEN '语音消息 🔊 TTS(免费 4 次)'
            ELSE trial.kind END                                          AS kind,
       COUNT(*)                                                          AS uses,
       COUNT(DISTINCT trial.user_id)                                     AS users,
       -- 🔴 2026-11-03:分母 = 截至当天在册的真·能量用户,见卡头
       MAX(eb.energy_users_cum)                                          AS energy_users,
       ROUND(100.0 * COUNT(DISTINCT trial.user_id)
                   / NULLIF(MAX(eb.energy_users_cum), 0), 1)             AS users_pct,
       ROUND(COUNT(*) / NULLIF(COUNT(DISTINCT trial.user_id), 0), 2)     AS uses_per_user,
       SUM(trial.refunded_at IS NOT NULL)                                AS refunded_uses
FROM   trial
LEFT JOIN energy_base AS eb ON eb.base_date = trial.date_use   -- 🔴 2026-11-03
GROUP BY `date`, trial.app_line, trial.kind
ORDER BY `date` DESC, trial.app_line, uses DESC;

