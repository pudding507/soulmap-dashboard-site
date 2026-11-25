-- 🛑 本卡**不拆天**(没有 date 列):构成表,一行 = 一个口径下的一档。它回答「现在的买家长什么样」,不是日度指标。(2026-11-20 补记)
-- 能量_复购与月卡 · Energy — Repeat Purchase & Monthly Card
-- 2026-11-12 新建。出处:需求文档 `01_看板/卡片需求_2026-11-12.md` §4.5(团队包看板 4)。
--
-- ═══ 这张卡回答四件事,分三块 ═══
--   ① 第 2 / 3 次购买率         —— 块「购买次序」
--   ② 月卡占比 + 买的是什么      —— 块「买了什么」
--   ③ 月卡到手后的逐日消耗曲线   —— 块「月卡到手后逐日消耗」
--   ④ 到期再买                  —— 块「月卡到期之后」
--
-- ═══ 🔴 建卡当天的实情:月卡几乎还没有量,这张卡现在立的是基线 ═══
--   实测全库只有 `com.soulmap.plus.energy:prepaid-1m` 这一种月卡有成交:
--   **8 笔 / 6 人 / $84.50**(10-29 ~ 11-09)。
--   🛑 **两种自动续费拼法 `:monthly` 和 `.monthly` 至今 0 行** —— 商品类型还没切。
--      口径文档 §1.2 ① 说有三种拼法,本卡按前缀 `com.soulmap.plus.energy%` 一次收全,
--      切了配置不用改 SQL。
--   ⇒ **月卡那两块现在是个位数,只读绝对人数,不要算比率、不要排名。**
--
-- ═══ 🛑 口径 ═══
--   ① **「买过」= 能量包 + 月卡 + 自动续费月订阅**,不只是预付。
--      能量包走 `soulmap_energy_lot`(layer='purchased' AND source='purchase'),
--      月卡走 `subscription_event_log` 的 `com.soulmap.plus.energy%` 前缀。
--      🛑 **不要用 `LIKE 'com.soulmap.energy.%'`** —— 月卡的前缀是 `plus.energy`,
--         那个写法收不到月卡,这正是 11-11 之前月卡在付费漏斗里一列都没进的原因。
--   ② **`price_update_20261029` 不是购买**,是改价补偿,已排除。
--   ③ 月卡到账看 `soulmap_energy_lot` 的 `layer='plan'`;
--      🛑 `source='test_grant'` 和 `plan_transfer` **不是买来的**,排除在「到手」之外。
--   ④ **$9.99 = 950 一次性到账,不是每天 80。** 所以逐日那一块是
--      **到手之后每天花掉多少**,不是「每天领了多少」⇒ **不要做每日领取率**。
--      🔴 实测到账额不全是 950:有一笔是 **750**(用户 74449,10-29),早于现行配置。
--   ⑤ 剔 9 个测试 / 沙盒号。2026-11-12 起 CityPLX 不再剔除,改成 `app_line` 一列并列(D-563);
--      实测能量各表与订阅表里 CityPLX 都是 0 人,这一列目前恒为 SoulMap。
--   ⑥ `event_at` 是 **UTC**,分天前 CONVERT_TZ 到 SGT;`soulmap_energy_lot.created_at` 是 SGT。
--
-- 【展示形式】**表格**,一行 = 块 × 项。三个理由:
--   ① 三块的量纲不同(人数 / 能量 / 美元),画在一张图上会互相盖掉;
--   ② 月卡那两块是个位数,画图会让人读出不存在的曲线;
--   ③ 要并排读「人数 + 占比 + 金额」,折线表达不了。
WITH
excluded_users AS (             -- 只剔测试 / 沙盒号,见口径 ⑤
  SELECT id FROM soul_map.`user`
  WHERE id IN (62412, 72048, 72382, 72462, 74640, 74377, 74592, 71693, 71826)
),
app_line_of_user AS (
  SELECT id AS user_id,
         CASE WHEN app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line
  FROM   soul_map.`user`
),
pack_buy AS (                   -- 能量包购买,一行一笔,见口径 ①②
  SELECT CAST(lot.user_id AS UNSIGNED)                              AS user_id,
         lot.created_at                                             AS bought_at,
         lot.amount                                                 AS energy
  FROM   soul_map.soulmap_energy_lot AS lot
  WHERE  lot.layer = 'purchased' AND lot.source = 'purchase'
    AND  CAST(lot.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
),
card_buy AS (                   -- 月卡购买,见口径 ①
  SELECT e.user_id                                                  AS user_id,
         CONVERT_TZ(e.event_at, '+00:00', '+08:00')                 AS bought_at,
         e.price_usd                                                AS price_usd
  FROM   soul_map.subscription_event_log AS e
  WHERE  e.environment = 'PRODUCTION'
    AND  e.product_id LIKE 'com.soulmap.plus.energy%'
    AND  e.event_type IN ('INITIAL_PURCHASE', 'RENEWAL')
    AND  COALESCE(e.price_usd, 0) > 0
    AND  e.user_id NOT IN (SELECT id FROM excluded_users)
),
any_buy AS (                    -- 两种合一,排购买次序
  SELECT user_id, bought_at, '能量包' AS kind FROM pack_buy
  UNION ALL
  SELECT user_id, bought_at, '月卡'   AS kind FROM card_buy
),
buy_seq AS (
  SELECT user_id, bought_at, kind,
         ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY bought_at) AS seq
  FROM   any_buy
),
first_buyers AS (SELECT COUNT(DISTINCT user_id) AS n FROM buy_seq),
plan_grant AS (                 -- 月卡到账,一行一笔,见口径 ③④
  SELECT lot.id                                                     AS lot_id,
         CAST(lot.user_id AS UNSIGNED)                              AS user_id,
         DATE(lot.created_at)                                       AS granted_date,
         lot.amount                                                 AS energy_granted
  FROM   soul_map.soulmap_energy_lot AS lot
  WHERE  lot.layer = 'plan' AND lot.source = 'subscription'
    AND  CAST(lot.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
),
plan_spend AS (
  -- 🛑 **精确到「这一笔消耗是从哪个 lot 扣的」**,不是「到手之后总共花了多少」。
  --    `soulmap_energy_txn.detail` 是 `[{"lotId":7029,"amount":1}]` 这样的数组,
  --    拆开之后只认 lotId 落在月卡那一笔上的部分。
  --    不这么做会把同期从赠送层 / 购买层扣的能量也算进月卡的消耗曲线
  --    (实测会把第 0 天虚高到到账额本身,看上去像「当天就花光」)。
  SELECT pg.user_id                                                 AS user_id,
         DATEDIFF(DATE(txn.created_at), pg.granted_date)            AS day_since,
         lot_detail.amount                                          AS energy
  FROM   soul_map.soulmap_energy_txn AS txn
  JOIN   JSON_TABLE(txn.detail, '$[*]'
           COLUMNS (lot_id BIGINT PATH '$.lotId',
                    amount INT    PATH '$.amount')) AS lot_detail ON TRUE
  JOIN   plan_grant AS pg ON pg.lot_id = lot_detail.lot_id
  WHERE  txn.op = 'consume'
)
SELECT '① 购买次序'                                                 AS section,
       CASE WHEN buy_seq.seq >= 5 THEN '第 5 次及以后'
            ELSE CONCAT('第 ', buy_seq.seq, ' 次') END               AS item,
       LEAST(buy_seq.seq, 5)                                         AS ord,
       app_line_of_user.app_line                                     AS app_line,
       COUNT(DISTINCT buy_seq.user_id)                               AS users,
       ROUND(100.0 * COUNT(DISTINCT buy_seq.user_id)
                   / (SELECT n FROM first_buyers), 1)                AS pct_of_buyers,
       NULL                                                          AS energy
FROM   buy_seq
JOIN   app_line_of_user ON app_line_of_user.user_id = buy_seq.user_id
GROUP  BY LEAST(buy_seq.seq, 5), app_line_of_user.app_line

UNION ALL
SELECT '② 买了什么',
       buy_seq.kind,
       CASE buy_seq.kind WHEN '能量包' THEN 1 ELSE 2 END,
       app_line_of_user.app_line,
       COUNT(DISTINCT buy_seq.user_id),
       ROUND(100.0 * COUNT(DISTINCT buy_seq.user_id)
                   / (SELECT n FROM first_buyers), 1),
       NULL
FROM   buy_seq
JOIN   app_line_of_user ON app_line_of_user.user_id = buy_seq.user_id
GROUP  BY buy_seq.kind, app_line_of_user.app_line

UNION ALL
-- 🛑 到手是一次性 950,这里是「到手之后每天花掉多少」,不是每天领了多少
SELECT '③ 月卡到手后逐日消耗',
       CONCAT('第 ', LPAD(plan_spend.day_since, 2, '0'), ' 天'),
       plan_spend.day_since,
       app_line_of_user.app_line,
       COUNT(DISTINCT plan_spend.user_id),
       NULL,
       SUM(plan_spend.energy)
FROM   plan_spend
JOIN   app_line_of_user ON app_line_of_user.user_id = plan_spend.user_id
GROUP  BY plan_spend.day_since, app_line_of_user.app_line

UNION ALL
SELECT '④ 月卡到手合计',
       CONCAT('到账 ', plan_grant.energy_granted, ' 能量'),
       plan_grant.energy_granted,
       app_line_of_user.app_line,
       COUNT(DISTINCT plan_grant.user_id),
       NULL,
       SUM(plan_grant.energy_granted)
FROM   plan_grant
JOIN   app_line_of_user ON app_line_of_user.user_id = plan_grant.user_id
GROUP  BY plan_grant.energy_granted, app_line_of_user.app_line

UNION ALL
-- ④「到期再买」:月卡买家各自买过几次月卡。🛑 现在全库只有 6 个人,只读绝对人数。
SELECT CASE WHEN card_count.times >= 2 THEN '⑤ 月卡到期再买' ELSE '⑤ 月卡到期再买' END,
       CASE WHEN card_count.times >= 2 THEN '买过 2 次及以上' ELSE '只买过 1 次' END,
       CASE WHEN card_count.times >= 2 THEN 2 ELSE 1 END,
       app_line_of_user.app_line,
       COUNT(*),
       NULL,
       NULL
FROM   (SELECT user_id, COUNT(*) AS times FROM card_buy GROUP BY user_id) AS card_count
JOIN   app_line_of_user ON app_line_of_user.user_id = card_count.user_id
GROUP  BY CASE WHEN card_count.times >= 2 THEN 2 ELSE 1 END, app_line_of_user.app_line

ORDER  BY section, ord, item;
