-- 🔴 2026-11-12:CityPLX 由「剔掉」改成「并列一栏」。
--    改了什么:`excluded_users` 不再剔 CityPLX(只剔 9 个测试 / 沙盒号),
--    改为多输出一列 `app_line`(CityPLX / SoulMap),并进 GROUP BY。
--    **两条线相加 = 改之前的「全部」**,但改前只有 SoulMap ⇒ 🛑 **改前改后不可直接比**。
--    🛑 实测 CityPLX 用户在本卡依赖的表里**目前 0 行**(能量五表与订阅表全是 0),
--       所以这一列现在只会出现 SoulMap;这是口径统一,不是漏数。
-- 能量_每天发放 · Energy — Daily Grants by Source
-- 2026-11-04 重做(原「能量_钱包三层」:日期 × 层 × 来源 × SKU,约 8 行/天、14 列,
--   既看不到「今天一共发了多少」,也分不清哪个数是流量、哪个是存量)。
--   现在拆成两张:**本卡只答「今天发了多少、从哪来」(流量,一行一天)**,
--   余额 / 已用 / 到期那套存量读数去「能量钱包现状」卡。
--
-- ═══ 口径 ═══
--   ① 一行 = 一天(`soulmap_energy_lot.created_at`,SGT),**来源做列**。
--   ② 🛑 **`改价补偿`(price_update_20261029)和 `换单位`(rescale_20261029)
--      不算发放、不算收入、不算购买**,两者整个排除在本卡之外。
--   ③ `其他赠送` = 邀请 `invite` + 每日签到 `checkin` + 创作者奖励 `creator_reward`
--      —— 三者量都是个位数到两位数,单列反而读不出。
--      🔴 `creator_reward` 是 **2026-11-04 才第一次出现**的新来源(当天 9 笔 / 9 能量),
--      还没有任何文档写过它,⬜ 要问 liwen 这是什么。
--   ④ 🛑 **三层过期规则不同**(买来的永不过期 · 订阅额度月底清零 · 赠送 14 天),
--      本卡只数「发出去多少」,**不要拿合计当成「用户手上还有多少」** —— 那看现状卡。
--   ⑤ 🛑 **不能从商品名推能量数**,商店商品已改成不带数字的 `Energy Pack S/M/L/XL/XXL`。
--   ⑥ 剔 CityPLX 与 9 个测试/沙盒号。
--
-- 输出:日期 | 新用户起始 | 第一次用完加送 | 定时回满 | 开推送 | 召回 | 其他赠送
--      | 购买 | 订阅额度 | 合计发放 | 拿到能量的人
WITH excluded_users AS (          -- 🔴 2026-11-12:只剔测试 / 沙盒号。
    -- CityPLX 不再剔除,改成并列一栏(见下面的 app_line_of_user)。
    SELECT id FROM soul_map.`user`
    WHERE id IN (62412, 72048, 72382, 72462, 74640,
                 74377, 74592, 71693, 71826)
),
app_line_of_user AS (        -- 🔴 2026-11-12:CityPLX 与 SoulMap 分开记,两者相加 = 原来的「全部」
    SELECT id                                                          AS user_id,
           CASE WHEN app_source = 'city' THEN 'CityPLX'
                WHEN app_source = 'web'  THEN 'SoulMap web'
                ELSE 'SoulMap' END AS app_line
    FROM   soul_map.`user`
),
lot AS (
  SELECT DATE(l.created_at)  AS date_lot,
         app_line_of_user.app_line,
         l.source,
         l.amount,
         l.user_id
  FROM   soul_map.soulmap_energy_lot AS l
  JOIN   app_line_of_user ON app_line_of_user.user_id = CAST(l.user_id AS UNSIGNED)
  WHERE  l.created_at >= GREATEST('2026-10-28 14:32:20',
                                  CURDATE() - INTERVAL 30 DAY)
    -- 见口径 ②:补偿与换单位整个不进本卡
    AND  l.source NOT IN ('price_update_20261029', 'rescale_20261029')
    AND  CAST(l.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
)
SELECT lot.date_lot                                                        AS `date`,
       lot.app_line                                                        AS app_line,
       SUM(CASE WHEN lot.source = 'free_start'   THEN lot.amount ELSE 0 END) AS g_free_start,
       SUM(CASE WHEN lot.source = 'first_out'    THEN lot.amount ELSE 0 END) AS g_first_out,
       SUM(CASE WHEN lot.source = 'refill'       THEN lot.amount ELSE 0 END) AS g_refill,
       SUM(CASE WHEN lot.source = 'push_enable'  THEN lot.amount ELSE 0 END) AS g_push_enable,
       SUM(CASE WHEN lot.source = 'recall'       THEN lot.amount ELSE 0 END) AS g_recall,
       -- 见口径 ③:三个零散来源合一列
       SUM(CASE WHEN lot.source IN ('invite','checkin','creator_reward')
                THEN lot.amount ELSE 0 END)                                AS g_other_bonus,
       SUM(CASE WHEN lot.source = 'purchase'     THEN lot.amount ELSE 0 END) AS g_purchase,
       SUM(CASE WHEN lot.source = 'subscription' THEN lot.amount ELSE 0 END) AS g_subscription,
       SUM(lot.amount)                                                     AS g_total,
       COUNT(DISTINCT lot.user_id)                                         AS granted_users
FROM   lot
GROUP BY lot.date_lot, lot.app_line
ORDER BY lot.date_lot DESC, lot.app_line;
