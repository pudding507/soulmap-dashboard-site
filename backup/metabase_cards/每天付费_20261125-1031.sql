-- 🔴 2026-11-12:CityPLX 由「剔掉」改成「并列一栏」。
--    改了什么:`excluded_users` 不再剔 CityPLX(只剔 9 个测试 / 沙盒号),
--    改为多输出一列 `app_line`(CityPLX / SoulMap),并进 GROUP BY。
--    **两条线相加 = 改之前的「全部」**,但改前只有 SoulMap ⇒ 🛑 **改前改后不可直接比**。
--    🛑 实测 CityPLX 用户在本卡依赖的表里**目前 0 行**(能量五表与订阅表全是 0),
--       所以这一列现在只会出现 SoulMap;这是口径统一,不是漏数。
-- 变现_每天付费 · Daily Revenue by Type
-- 2026-11-04 新建(当天先按商品拆,同日改成按四类拆 —— 和实际在用的那张表对齐)。
--
-- ═══ 口径(已与现用表逐日逐格对上,8 天 × 5 行完全一致)═══
--   ① 一行 = 一天(新加坡时区),四类 + 合计。
--   ② 🛑 **`event_at` 是 UTC** —— 必须 `CONVERT_TZ(...,'+00:00','+08:00')` 再取日期。
--      不换算会把每天傍晚之后的单子算到前一天,合计逐日全错
--      (实测 11-01 换算前 $86.39 / 换算后 **$104.85**)。
--      🛑 同表的 `purchased_at` / `expiration_at` 也是 UTC;但 `subscription.expiry_time`
--      实测是 **SGT**(与本表 `expiration_at` 差整 8 小时),别一起换。
--   ③ **订阅首购 = `event_type='INITIAL_PURCHASE'`,其余订阅行都算续费。**
--      🛑 这和「收入_每天新首付」(430)**不是同一个口径** —— 那张按
--      「该账号时间序第 1 笔 price_usd>0」判,会把免费试用到期的首扣也算成首付。
--      两张卡的首购数对不上是正常的,**不要互相校验**。
--   ④ 只数 `price_usd > 0`、`environment='PRODUCTION'` 的行,沙盒不算收入。
--   ⑤ 分类:`com.soulmap.energy.*` → 能量包;`com.soulmap.pass.*` → 其他购买;
--      其余(含 `plus.monthly` 与 `plus.energy` 能量版 Plus)→ 订阅。
--   ⑥ 剔 CityPLX 与 9 个测试/沙盒号。
--   🛑 **收入是商店流水价,不是到手** —— 没扣商店抽成、没扣税
--      (`price_local` 一般含当地税,沙特 SAR4.29 ≈ $0.99 税前 +15% VAT)。
--   🛑 **当天那一行没结束**,不要拿它和昨天比。
--
-- 输出:日期 | 能量包 | 订阅首购 | 订阅续费 | 其他购买 | 合计 | 付费人数
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
paid AS (
  SELECT e.user_id,
         app_line_of_user.app_line,
         e.price_usd,
         e.event_type,
         CONVERT_TZ(e.event_at, '+00:00', '+08:00')                 AS at_sgt,   -- 见口径 ②
         CASE WHEN e.product_id LIKE 'com.soulmap.energy.%' THEN '能量包'
              WHEN e.product_id LIKE 'com.soulmap.pass.%'   THEN '其他购买'
              ELSE '订阅' END                                        AS kind
  FROM   soul_map.subscription_event_log AS e
  JOIN   app_line_of_user ON app_line_of_user.user_id = e.user_id
  WHERE  COALESCE(e.price_usd, 0) > 0
    AND  e.environment = 'PRODUCTION'
    AND  e.user_id NOT IN (SELECT id FROM excluded_users)
)
SELECT DATE(paid.at_sgt)                                             AS `date`,
       paid.app_line                                                 AS app_line,
       ROUND(COALESCE(SUM(CASE WHEN paid.kind = '能量包'
                               THEN paid.price_usd END), 0), 2)      AS energy_pack_usd,
       -- 见口径 ③:首购只认 INITIAL_PURCHASE,与「每天新首付」卡不是一个口径
       ROUND(COALESCE(SUM(CASE WHEN paid.kind = '订阅'
                                AND paid.event_type = 'INITIAL_PURCHASE'
                               THEN paid.price_usd END), 0), 2)      AS sub_first_usd,
       ROUND(COALESCE(SUM(CASE WHEN paid.kind = '订阅'
                                AND paid.event_type <> 'INITIAL_PURCHASE'
                               THEN paid.price_usd END), 0), 2)      AS sub_renew_usd,
       ROUND(COALESCE(SUM(CASE WHEN paid.kind = '其他购买'
                               THEN paid.price_usd END), 0), 2)      AS other_usd,
       ROUND(SUM(paid.price_usd), 2)                                 AS total_usd,
       COUNT(DISTINCT paid.user_id)                                  AS payers
FROM   paid
WHERE  paid.at_sgt >= CURDATE() - INTERVAL 30 DAY
GROUP BY `date`, paid.app_line
ORDER BY `date` DESC, paid.app_line;

