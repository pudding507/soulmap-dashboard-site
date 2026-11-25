-- 🔴 2026-11-12:CityPLX 由「剔掉」改成「并列一栏」。
--    改了什么:`excluded_users` 不再剔 CityPLX(只剔 9 个测试 / 沙盒号),
--    改为多输出一列 `app_line`(CityPLX / SoulMap),并进 GROUP BY。
--    **两条线相加 = 改之前的「全部」**,但改前只有 SoulMap ⇒ 🛑 **改前改后不可直接比**。
--    🛑 实测 CityPLX 用户在本卡依赖的表里**目前 0 行**(能量五表与订阅表全是 0),
--       所以这一列现在只会出现 SoulMap;这是口径统一,不是漏数。
-- 能量_钱包现状 · Energy — Wallet Snapshot
-- 2026-11-04 新建。由原「能量_钱包三层」拆出来的**存量**那一半
--   (流量那一半见「能量_每天发放」)。一行一个层,**没有日期** —— 它答的是
--   「现在用户手上还有多少、用掉了多少」,不是「哪天发的」。
--
-- ═══ 口径 ═══
--   ① 一行 = 一个钱包层,全时段累计(自 2026-10-28 14:32:20)。
--   ② 🛑 **三层的过期规则完全不同,`剩余` 绝对不能跨层相加当成「用户还有多少能量」**:
--      `买来的` 永不过期 · `订阅额度` **月底清零** · `赠送` 14 天过期。
--   ③ 🛑 **`最早到期` 只是「部分可用」,不能拿来汇总「有多少赠送能量快到期」** ——
--      实测只有 `push_enable` / `invite` 两个新来源落了 14 天过期,
--      占九成以上行数的 `free_start` / `first_out` / `recall` **一条都没落**,
--      汇出来会小一个量级。`买来的` 为 NULL 是对的(永不过期)。
--   ④ 🛑 `其中首购` 只是近似:服务端分不清是从聊天内阶梯卡还是充值页买的
--      (两者用同一个商店商品)。
--   ⑤ 🛑 **`改价补偿` 和 `换单位` 不算发放**,本卡排除。
--   ⑥ 剔 CityPLX 与 9 个测试/沙盒号。
--
-- 输出:层 | 笔数 | 拿到的人 | 发放能量 | 剩余 | 已用 | 已用占比 | 其中首购 | 最早到期
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
lot AS (
  SELECT l.layer, l.amount, l.remaining, l.first_purchase, l.expires_at, l.user_id,
         app_line_of_user.app_line
  FROM   soul_map.soulmap_energy_lot AS l
  JOIN   app_line_of_user ON app_line_of_user.user_id = CAST(l.user_id AS UNSIGNED)
  WHERE  l.created_at >= '2026-10-28 14:32:20'
    AND  l.source NOT IN ('price_update_20261029', 'rescale_20261029')   -- 见口径 ⑤
    AND  CAST(l.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
)
SELECT lot.app_line                                                      AS app_line,
       CASE lot.layer
            WHEN 'purchased' THEN '① 买来的 Purchased(永不过期)'
            WHEN 'plan'      THEN '② 订阅额度 Plan(🛑 月底清零)'
            WHEN 'bonus'     THEN '③ 赠送 Bonus(14 天过期)'
            ELSE lot.layer END                                           AS layer,
       COUNT(*)                                                          AS lots,
       COUNT(DISTINCT lot.user_id)                                       AS users,
       SUM(lot.amount)                                                   AS granted_energy,
       SUM(lot.remaining)                                                AS remaining_energy,
       SUM(lot.amount - lot.remaining)                                   AS used_energy,
       ROUND(100.0 * SUM(lot.amount - lot.remaining)
                   / NULLIF(SUM(lot.amount), 0), 1)                      AS used_pct,
       SUM(lot.first_purchase = 1)                                       AS first_purchase_lots,
       MIN(lot.expires_at)                                               AS next_expiry
FROM   lot
GROUP BY lot.app_line, layer
ORDER BY lot.app_line, layer;

