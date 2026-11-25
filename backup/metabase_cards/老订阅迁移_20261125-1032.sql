-- 🔴 2026-11-12:CityPLX 由「剔掉」改成「并列一栏」。
--    改了什么:`excluded_users` 不再剔 CityPLX(只剔 9 个测试 / 沙盒号),
--    改为多输出一列 `app_line`(CityPLX / SoulMap),并进 GROUP BY。
--    **两条线相加 = 改之前的「全部」**,但改前只有 SoulMap ⇒ 🛑 **改前改后不可直接比**。
--    🛑 实测 CityPLX 用户在本卡依赖的表里**目前 0 行**(能量五表与订阅表全是 0),
--       所以这一列现在只会出现 SoulMap;这是口径统一,不是漏数。
-- 能量_老订阅迁移 · Energy — Legacy Subscriber Migration
-- 2026-11-04 新建。出处:《产品玩法》§15.7「老用户怎么迁」。
--
-- ═══ 为什么要这张卡 ═══
--   老订阅用户切换前是**无限**,切换后变成**每月 950 能量**(迁移那次一次性 +950,
--   所以第一个月 1,900)。切换条件:**3.9.0 上架满 7 天后的第一个续费日,且已经在用 3.9.0**
--   ⇒ 3.9.0 是 2026-10-29 13:13 上线,**满 7 天就是 2026-11-05**,从那天起陆续切。
--   🔴 切换当天没有任何卡在看这件事,所以建这张。
--
-- ═══ 🛑 最该盯的一行 ═══
--   《产品玩法》§15.7 明写 **`INTRO`(0.99 首月)/ `TRIAL`(免费七天)/ `PROMOTIONAL`(赠送月)
--   三种形态没有换算规则**。2026-11-04 实测:会被切的 76 人里这三类占 **20 人(26%)**,
--   其中 **15 人 11-05 当天就到期**。按 Plus 发 950 的话,$0.99 的人拿 950
--   相当于 L5 档($9.99 / 920)的 **10 倍**划算。
--
-- ═══ 口径 ═══
--   ① 队列 = `subscription` 里 `superseded=0`、状态 ACTIVE 或 IN_GRACE_PERIOD、
--      `auto_renewing=1`、`expiry_time >= CURDATE()` 的订阅,一人一行。
--      退订的(CANCELED)不会续费,不进队列。
--   ② `付费形态` 取该账号 `subscription_event_log` 里**最后一条**非空 `period_type`,
--      🛑 **不能用取消行上的 period_type**(0.99 首期结束后转入全价周期,写的是 NORMAL)。
--   ③ `已切` 判据是能量钱包里有 `layer='plan'` 的行(订阅月额度层)。
--      🛑 **`plan` 层月底清零**,所以这一列只说明「切过」,不说明「现在还有」。
--   ④ 🛑 **「已经在用 3.9.0」这个条件服务端查不出来** —— `soulmap_app_launch` 没有版本列,
--      版本只在 firebase 埋点里、且是设备级。所以本卡用 `进了能量系统`
--      (有 `soulmap_energy_account` 行)当最接近的服务端替代:它要求客户端 build
--      带能量**且**服务端对他下发。**这不等于「装了 3.9.0」,读的时候别当成版本。**
--   ⑤ 剔 CityPLX 与 9 个测试/沙盒号。
--
-- 输出:续费日 | 还有几天 | 付费形态 | 订阅状态 | 商品 | user_id
--      | 进了能量系统 | 已切 | 已发订阅额度 | 钱包余额
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
due AS (                       -- 会被切的在册订阅
  SELECT s.user_id,
         app_line_of_user.app_line,
         DATE(s.expiry_time)                                      AS renew_date,
         s.status,
         s.product_id
  FROM   soul_map.subscription AS s
  JOIN   app_line_of_user ON app_line_of_user.user_id = s.user_id
  WHERE  s.superseded = 0
    AND  s.status IN ('ACTIVE', 'IN_GRACE_PERIOD')
    AND  s.auto_renewing = 1
    AND  s.expiry_time >= CURDATE()
    AND  s.user_id NOT IN (SELECT id FROM excluded_users)
),
last_period_type AS (          -- 见口径 ②:取最后一条非空 period_type
  SELECT e.user_id,
         SUBSTRING_INDEX(GROUP_CONCAT(e.period_type ORDER BY e.event_at DESC), ',', 1) AS period_type
  FROM   soul_map.subscription_event_log AS e
  WHERE  e.period_type IS NOT NULL AND e.period_type <> ''
  GROUP  BY e.user_id
),
plan_lot AS (                  -- 见口径 ③:订阅月额度层
  SELECT CAST(l.user_id AS UNSIGNED)  AS user_id,
         SUM(l.amount)                AS plan_energy_granted
  FROM   soul_map.soulmap_energy_lot AS l
  WHERE  l.layer = 'plan'
  GROUP  BY CAST(l.user_id AS UNSIGNED)
),
wallet AS (                    -- 现在钱包里还剩多少(三层合计,仅作量级参照)
  SELECT CAST(l.user_id AS UNSIGNED)  AS user_id,
         SUM(l.remaining)             AS wallet_remaining
  FROM   soul_map.soulmap_energy_lot AS l
  GROUP  BY CAST(l.user_id AS UNSIGNED)
)
SELECT due.renew_date                                             AS `date`,
       due.app_line                                               AS app_line,
       DATEDIFF(due.renew_date, CURDATE())                        AS days_to_renew,
       CASE COALESCE(last_period_type.period_type, '(查不到)')
            WHEN 'NORMAL'       THEN '全价 Normal'
            WHEN 'INTRO'        THEN '🛑 0.99 首月 Intro(无换算规则)'
            WHEN 'TRIAL'        THEN '🛑 免费七天 Trial(无换算规则)'
            WHEN 'PROMOTIONAL'  THEN '🛑 赠送月 Promotional(无换算规则)'
            WHEN 'PREPAID'      THEN '预付 Prepaid'
            ELSE COALESCE(last_period_type.period_type, '(查不到)') END AS period_type,
       due.status                                                 AS sub_status,
       due.product_id                                             AS product_id,
       due.user_id                                                AS user_id,
       (energy_account.user_id IS NOT NULL)                       AS in_energy_system,
       (plan_lot.user_id IS NOT NULL)                             AS switched,
       COALESCE(plan_lot.plan_energy_granted, 0)                  AS plan_energy_granted,
       COALESCE(wallet.wallet_remaining, 0)                       AS wallet_remaining
FROM        due
LEFT  JOIN  last_period_type ON last_period_type.user_id = due.user_id
LEFT  JOIN  plan_lot         ON plan_lot.user_id         = due.user_id
LEFT  JOIN  wallet           ON wallet.user_id           = due.user_id
LEFT  JOIN  soul_map.soulmap_energy_account AS energy_account
            ON CAST(energy_account.user_id AS UNSIGNED)  = due.user_id
ORDER BY due.renew_date, period_type, due.user_id;

