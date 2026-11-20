-- ╔══════════════════════════════════════════════════════════════════════════╗
--
-- 🔴 2026-11-20:新增 `prepaid_monthly` 列(预付能量月包,period_type='PREPAID')。
--   为什么:卡头写着「三类相加 = first_payers」,但 PREPAID 的 event_type 是
--   INITIAL_PURCHASE、period_type 不是 NORMAL,三类一个都不占,承诺被打破。
--   实测近 30 天 160 行里 6 行对不上(全是印度,各差 1 人)。
--   🛑 收入列 `revenue_full_usd` 用的是 `period_type <> 'INTRO'`,PREPAID 的钱一直算在里面,
--      这次**没动它** —— 改收入口径会让历史数不可比,要改另提。
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
--   【本卡原来错在哪 —— 2026-10-29 实测】
--     本卡只过滤 `environment='PRODUCTION' AND price_usd > 0`,没有 event_type/product_id 条件,
--     所以消耗型购买进了 `paid_event`,产生两处坏法:
--       ① **`pay_seq = 1` 被抢位** —— 10-24、10-27 各 1 笔 0.42 USD 的 3 天通行证、
--          10-29 1 笔 0.51 USD 的能量包,各自把那个人记成了当天的「新首付」;
--          **等这个人之后真买月订阅,就不再是第 1 笔,永远不会进这张卡。**
--       ② **三类之和对不上总数** —— `intro_099 / trial_to_full / direct_full` 判的是
--          INTRO / RENEWAL / INITIAL_PURCHASE+NORMAL,消耗型是 `NON_RENEWING_PURCHASE`,
--          一类都不属于 ⇒ 那几行 `first_payers=1` 但三列全是 0;
--          而 `revenue_full_usd` 用 `period_type <> 'INTRO'`,**又把钱算进去了**。
--   【本卡改动】`paid_event` 加 `event_type <> 'NON_RENEWING_PURCHASE'`,消耗型不进订阅排序;
--     另起 `consumable` CTE,新增 `pass3day_buys` / `energy_pack_buys` / `consumable_usd` 三列。
--     🛑 新三列的单位是「**笔**」(一个人可以买很多次),左边几列是「**人**」,**不要相加**。
--     🛑 `first_payers` 和 `revenue_usd` 现在都只算订阅,和 10-29 以前的历史数相比会**略微变小**。
--
-- 收入_每天新首付 · Revenue — First-Time Payers by Day
--
-- 2026-10-21 新建。对应 Michael 10-21 看板反馈 P0 第二条(D-371 / D-340)。
--
-- ═══ 🛑 「新首付」的定义:这个人**第一次**真的被扣到钱 ═══
--   **不能按事件名判**。实测(2026-10-21 全库):
--     INITIAL_PURCHASE + INTRO   75 人 ·  53.21 USD   ← 0.99 首购
--     RENEWAL          + NORMAL  29 人 · 296.39 USD   ← **免费试用到期扣全价**
--     INITIAL_PURCHASE + NORMAL   1 人 ·   7.54 USD   ← 直接全价首购
--   那 29 次 `RENEWAL` **在订阅系统里叫「续费」,但对用户是第一次付钱** ——
--   按事件名归类会把他们错算进续费表,新首付就少了 29 人、少了 83% 的钱。
--   ⇒ 本卡一律按「该用户**按时间排序的第 1 笔** price_usd > 0 的事件」判,不看事件名。
--
-- ═══ 🛑 五个陷阱 ═══
-- ① `event_at` 是 **UTC**(同表 purchased_at / expiration_at 也是),分天前必须 CONVERT_TZ 到 SGT。
-- ② `environment = 'PRODUCTION'` 必须加 —— 不限环境会混进 sandbox 测试号(实测多 2 人)。
-- ③ 判「真的扣到钱」用 **price_usd > 0**,不是看 event_type ——
--    `INITIAL_PURCHASE + TRIAL`(415 次)是开免费试用,**一分钱没扣**。
-- ④ 2026-11-12 起 CityPLX 不再剔除,改成 `app_line` 一列并列(D-563)。
--    实测 `subscription_event_log` 里没有任何 CityPLX 账号,所以这一列目前恒为 SoulMap。
-- ⑤ 判 0.99 只能用 `period_type='INTRO'`,**不能靠 product_id**(它写的是 monthly,
--    但 0.99 实际周期只有 6.82 天)。
--
-- 【展示形式】**表格**,一行 = 一天 × 国家。三个理由:
--   ① 要并排读「0.99 / 试用转全价 / 直接全价」三类人数和各自金额,折线叠不下;
--   ② 三类的单价差 14 倍(0.71 vs 10.22 USD),画在一张图上小的那类会看不见;
--   ③ 量是个位数到两位数,而且要按国家、渠道筛,表格直接。
WITH paid_event AS (             -- 所有「真的扣到钱」的事件,按人排序
  SELECT e.user_id,
         e.event_at,
         e.period_type,
         e.event_type,
         e.price_usd,
         e.country_code,
         CASE WHEN u.app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line,
         ROW_NUMBER() OVER (PARTITION BY e.user_id ORDER BY e.event_at) AS pay_seq
  FROM soul_map.subscription_event_log AS e
  JOIN soul_map.`user` AS u ON u.id = e.user_id
  WHERE e.environment = 'PRODUCTION'
    AND COALESCE(e.price_usd, 0) > 0                  -- 见陷阱 ③
    -- 🔴 2026-10-29 新增:消耗型商品(3 天通行证 / 能量包)**不进订阅排序**。见卡头断点说明。
    AND e.event_type <> 'NON_RENEWING_PURCHASE'
),
first_pay AS (                   -- 只取每人第 1 笔订阅 = 新首付
  SELECT * FROM paid_event WHERE pay_seq = 1
),
consumable AS (                  -- 🔴 2026-10-29 新增:消耗型购买,单独数,不做 pay_seq
  -- 🛑 一个人可以买很多次,**这里数的是「笔」不是「人」**,和 first_payers 不是一个量纲。
  SELECT e.user_id, e.event_at, e.price_usd, e.country_code,
         CASE WHEN u.app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line,
         CASE WHEN e.product_id LIKE 'com.soulmap.energy.%' THEN 'energy' ELSE 'pass' END AS pay_kind
  FROM soul_map.subscription_event_log AS e
  JOIN soul_map.`user` AS u ON u.id = e.user_id
  WHERE e.environment = 'PRODUCTION'
    AND COALESCE(e.price_usd, 0) > 0
    AND e.event_type = 'NON_RENEWING_PURCHASE'
),
counted AS (                     -- 订阅首付 + 消耗型购买合成一张,只为能按同一组维度聚合
  SELECT user_id, event_at, period_type, event_type, price_usd, country_code, app_line, 'sub' AS pay_kind
  FROM first_pay
  UNION ALL
  SELECT user_id, event_at, NULL, 'NON_RENEWING_PURCHASE', price_usd, country_code, app_line, pay_kind
  FROM consumable
),
attr AS (                        -- 广告 / 自然:取首次启动那一行(同 385/386 归因口径)
  SELECT c.user_id,
         SUBSTRING_INDEX(GROUP_CONCAT(NULLIF(l.network,'') ORDER BY l.add_on), ',', 1) AS network
  FROM (SELECT user_id FROM soul_map.soulmap_app_launch WHERE user_id <> '' GROUP BY user_id) c
  JOIN soul_map.soulmap_app_launch l ON l.user_id = c.user_id
  GROUP BY c.user_id
)
SELECT DATE(CONVERT_TZ(f.event_at, '+00:00', '+08:00'))                      AS date,
       f.app_line                                                            AS app_line,
       COALESCE(f.country_code, '?')                                         AS country,
       CASE WHEN a.network IS NULL OR a.network = ''   THEN '(无归因)'
            WHEN a.network = 'Organic'                 THEN '自然量'
            ELSE '广告' END                                                   AS acquisition,
       SUM(f.pay_kind = 'sub')                                               AS first_payers,
       -- 四类分开(见上面的口径说明)。🛑 只在订阅里拆,**相加 = first_payers**。
       SUM(f.pay_kind = 'sub' AND f.period_type = 'INTRO')                   AS intro_099,
       SUM(f.pay_kind = 'sub' AND f.event_type = 'RENEWAL')                  AS trial_to_full,
       SUM(f.pay_kind = 'sub' AND f.event_type = 'INITIAL_PURCHASE'
                              AND f.period_type = 'NORMAL')                  AS direct_full,
       -- 🔴 2026-11-20 新增:预付能量月包(com.soulmap.plus.energy:prepaid-1m)。
       --    它的 event_type 是 INITIAL_PURCHASE,但 period_type 是 PREPAID 不是 NORMAL,
       --    上面三类一个都不占 ⇒ 卡头承诺的「三类相加 = first_payers」被它打破。
       --    实测 160 行里 6 行对不上(全是印度,各差 1 人)。补上这一列后四类相加重新等于总数。
       SUM(f.pay_kind = 'sub' AND f.period_type = 'PREPAID')                 AS prepaid_monthly,
       ROUND(SUM(CASE WHEN f.pay_kind = 'sub' THEN f.price_usd END), 2)      AS revenue_usd,
       ROUND(SUM(CASE WHEN f.pay_kind = 'sub'
                       AND f.period_type = 'INTRO' THEN f.price_usd END), 2) AS revenue_099_usd,
       ROUND(SUM(CASE WHEN f.pay_kind = 'sub'
                       AND f.period_type <> 'INTRO' THEN f.price_usd END),2) AS revenue_full_usd,
       -- 🔴 2026-10-29 新增:消耗型购买。**单位是「笔」,不是「人」**,不要和左边几列相加。
       SUM(f.pay_kind = 'pass')                                              AS pass3day_buys,
       SUM(f.pay_kind = 'energy')                                            AS energy_pack_buys,
       ROUND(SUM(CASE WHEN f.pay_kind <> 'sub' THEN f.price_usd END), 2)     AS consumable_usd
FROM counted AS f
LEFT JOIN attr AS a ON a.user_id = CAST(f.user_id AS CHAR) COLLATE utf8mb4_0900_ai_ci
GROUP BY date, app_line, country, acquisition
ORDER BY date DESC, first_payers DESC;
