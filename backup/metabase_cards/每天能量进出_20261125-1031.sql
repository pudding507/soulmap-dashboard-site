-- 🔴 2026-11-12:CityPLX 由「剔掉」改成「并列一栏」。
--    改了什么:`excluded_users` 不再剔 CityPLX(只剔 9 个测试 / 沙盒号),
--    改为多输出一列 `app_line`(CityPLX / SoulMap),并进 GROUP BY。
--    **两条线相加 = 改之前的「全部」**,但改前只有 SoulMap ⇒ 🛑 **改前改后不可直接比**。
--    🛑 实测 CityPLX 用户在本卡依赖的表里**目前 0 行**(能量五表与订阅表全是 0),
--       所以这一列现在只会出现 SoulMap;这是口径统一,不是漏数。
-- 能量_每天进出 · Energy — Daily In & Out
-- 2026-11-04 重做(原「能量_流水 · Energy — Ledger」:日期 × 方向 × 来源,约 10 行/天、10 列,
--   一眼看不到「今天一共进出多少」,得自己在脑子里加)。
--   现在改成**一行一天**:扣费的四个用途做成列,入账只给合计。
--   🛑 **「能量从哪来」这个问题整个挪到「每天发放能量」卡**(按来源拆,也是一行一天),
--      两张卡不再重复。
--
-- ═══ 口径 ═══
--   ① 一行 = 一天(`soulmap_energy_txn.created_at`,本表是 SGT,不用换算)。
--   ② `入账` / `扣费` 都取绝对值合计,**不相减成净额** —— 赠送与购买混在一起,
--      净额读不出意义;要看余额去「能量钱包现状」卡。
--   ③ 🛑 **`改价补偿` 和 `换单位` 不算收入也不算购买**,单列一列,不并进 `入账`。
--   ④ 🛑 **`折合聊天条数` 只对聊天算**,且按**当时**的单价折:
--      2 能量/条(10-28 14:32:20 起)→ 4(10-29 12:14)→ **1(10-30 18:43,现行)**。
--      语音 / 🔊 / 创建角色三段单价各不相同,折了更容易误读,所以只给原始能量数。
--   ⑤ `花过能量的人` = 当天有任何一笔扣费的账号;`能量用户` = 截至当天在册的
--      真·能量用户(`soulmap_energy_account` 有行),见那张卡的口径。
--   ⑥ 剔 CityPLX 与 9 个测试/沙盒号。起点 2026-10-28 14:32:20;
--      影子计费 `soulmap_energy_shadow_charge` 不扣用户的钱,本卡不读。
--
-- 输出:日期 | 入账 | 扣费 | 聊天 | 语音回复 | 语音消息 | 创建角色
--      | 折合聊天条数 | 补偿换算 | 花过能量的人 | 能量用户
WITH excluded_users AS (          -- 🔴 2026-11-12:只剔测试 / 沙盒号。
    -- CityPLX 不再剔除,改成并列一栏(见下面的 app_line_of_user)。
    SELECT id FROM soul_map.`user`
    WHERE id IN (62412, 72048, 72382, 72462, 74640,
                 74377, 74592, 71693, 71826)
),
app_line_of_user AS (        -- 🔴 2026-11-12:CityPLX 与 SoulMap 分开记,两者相加 = 原来的「全部」
    SELECT id                                                          AS user_id,
           CASE WHEN app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line
    FROM   soul_map.`user`
),
energy_population AS (   -- 真·能量用户,见「能量系统瀑布表」卡头
  SELECT DATE(ea.started_at) AS joined_date
  FROM   soul_map.soulmap_energy_account AS ea
  WHERE  CAST(ea.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
),
energy_base AS (
  SELECT joined_date                                      AS base_date,
         SUM(COUNT(*)) OVER (ORDER BY joined_date)        AS energy_users_cum
  FROM   energy_population GROUP BY joined_date
),
txn AS (
  SELECT DATE(t.created_at)                               AS date_txn,
         app_line_of_user.app_line,
         t.op, t.source, t.amount, t.user_id,
         CASE WHEN t.created_at < '2026-10-29 12:14:00' THEN 2
              WHEN t.created_at < '2026-10-30 18:43:00' THEN 4
              ELSE 1 END                                  AS chat_unit   -- 见口径 ④
  FROM   soul_map.soulmap_energy_txn AS t
  JOIN   app_line_of_user ON app_line_of_user.user_id = CAST(t.user_id AS UNSIGNED)
  WHERE  t.created_at >= GREATEST('2026-10-28 14:32:20',
                                  CURDATE() - INTERVAL 30 DAY)
    AND  CAST(t.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
)
SELECT txn.date_txn                                                       AS `date`,
       txn.app_line                                                       AS app_line,
       SUM(CASE WHEN txn.op = 'grant'
                 AND txn.source NOT IN ('price_update_20261029','rescale_20261029')
                THEN txn.amount ELSE 0 END)                               AS energy_in,
       -- 🛑 `换单位` 的回收也走扣费,必须一并排掉,否则 10-30 那天 `扣费` 会被
       --    21,666 的换算冲掉(实测 16,802 → 38,468),看上去像当天花了两倍多
       SUM(CASE WHEN txn.op <> 'grant'
                 AND txn.source NOT IN ('price_update_20261029','rescale_20261029')
                THEN txn.amount ELSE 0 END)                               AS energy_out,
       SUM(CASE WHEN txn.source = 'chat'      THEN txn.amount ELSE 0 END) AS out_chat,
       SUM(CASE WHEN txn.source = 'voice'     THEN txn.amount ELSE 0 END) AS out_voice,
       SUM(CASE WHEN txn.source = 'tts'       THEN txn.amount ELSE 0 END) AS out_tts,
       SUM(CASE WHEN txn.source = 'character' THEN txn.amount ELSE 0 END) AS out_character,
       ROUND(SUM(CASE WHEN txn.source = 'chat'
                      THEN txn.amount / txn.chat_unit ELSE 0 END))        AS chat_msgs_equiv,
       -- 见口径 ③:不算收入也不算购买,单列
       SUM(CASE WHEN txn.source IN ('price_update_20261029','rescale_20261029')
                THEN txn.amount ELSE 0 END)                               AS adjust_energy,
       COUNT(DISTINCT CASE WHEN txn.op <> 'grant' THEN txn.user_id END)   AS spenders,
       MAX(energy_base.energy_users_cum)                                  AS energy_users
FROM       txn
LEFT JOIN  energy_base ON energy_base.base_date = txn.date_txn
GROUP BY   txn.date_txn, txn.app_line
ORDER BY   txn.date_txn DESC, txn.app_line;

