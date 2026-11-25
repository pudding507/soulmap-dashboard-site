-- 🔴 2026-11-12:CityPLX 由「剔掉」改成「并列一栏」。
--    改了什么:`excluded_users` 不再剔 CityPLX(只剔 9 个测试 / 沙盒号),
--    改为多输出一列 `app_line`(CityPLX / SoulMap),并进 GROUP BY。
--    **两条线相加 = 改之前的「全部」**,但改前只有 SoulMap ⇒ 🛑 **改前改后不可直接比**。
--    🛑 实测 CityPLX 用户在本卡依赖的表里**目前 0 行**(能量五表与订阅表全是 0),
--       所以这一列现在只会出现 SoulMap;这是口径统一,不是漏数。
-- 能量_阶梯推进 · Energy — Offer Ladder Progression
-- 2026-11-04 新建。出处:《产品玩法》§15.4 ②「聊天内阶梯优惠」。
--
-- ═══ 为什么要这张卡 ═══
--   能量用完时在**聊天里**弹的卡是分档的:L1 $0.49 → L2 $0.99 → L3 $1.99 → L4 $4.99 → L5 $9.99,
--   每档的加送比例递减(100% → 50% → 25% → 10% → 10%)。
--   推进规则:**买了这一档,或从它第一次出现起满 24 小时,并且是新的一次用完** ⇒ 换下一档。
--   「能量系统瀑布表」是按**天 × 档位**出的,看得到每天各档多少人,
--   **看不到「同一个人从 L1 推到了第几档」** —— 而这正是现在的核心变现阶梯。
--   2026-11-04 实测曝光次数:L1 4,013 · L2 213 · L3 39 · L4 13 · L5 5。
--
-- ═══ 口径 ═══
--   ① 全时段累计(自 2026-10-28 14:32:20 能量上线),**不按天拆** —— 按天拆就看不出推进。
--   ② `到达人数` = 这一档**有任何一条记录**的人(去重),不是只算 `shown` ——
--      实测有人只有 `accepted` 没有 `shown`(L3 到达 6 人却接受 8 人),
--      只按 `shown` 做分母会算出大于 100% 的接受率。`接受` = `action='accepted'`(真的买了)。
--   ③ `推进到下一档` = 这个人后来**见过比本档更高的档**。
--      🛑 **它不等于「因为买了才推进」** —— 规则里「满 24 小时 + 新的一次用完」也会推进,
--      两条路服务端分不开,所以 `推进率` 读成「这一档之后还会不会再被要钱」,不是转化率。
--   ④ 🛑 **分子 <10 的档不要算比率**(L3 以上现在全是个位数),只读绝对人数。
--   ⑤ 🔴 **`accepted` 这一行不带 `surface`** —— 2026-11-04 实测:`shown` / `declined` /
--      `cancelled` 三种 action 的 `surface` 都有值(inline 2,881 / full 6),
--      而 **63 条 `accepted` 全是 NULL** ⇒ **买成的那一笔归不到「聊天卡」还是「充值页」**。
--      所以本卡把曝光按来源拆成两列,接受只给一个合计数,**不要把接受数往某一个来源上算**。
--      ⬜ 要请服务端在 `accepted` 上补 `surface`。
--      (另外《产品玩法》§15.4 也写了:优惠档和充值页用的是同一个商店商品,服务端本来就分不清。)
--   ⑥ 剔 CityPLX 与 9 个测试/沙盒号。
--
-- 输出:档位 | 聊天内曝光 | 充值页曝光 | 到达人数 | 看了没点 | 接受人数 | 接受率 | 推进到下一档 | 推进率
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
offer AS (
  SELECT oe.user_id,
         app_line_of_user.app_line,
         oe.tier,
         COALESCE(oe.surface, '(未标来源)')                       AS surface,
         oe.action,
         CAST(SUBSTRING(oe.tier, 2) AS UNSIGNED)                  AS tier_rank
  FROM   soul_map.soulmap_energy_offer_event AS oe
  JOIN   app_line_of_user ON app_line_of_user.user_id = CAST(oe.user_id AS UNSIGNED)
  WHERE  oe.created_at >= '2026-10-28 14:32:20'
    AND  oe.tier REGEXP '^L[1-9]$'
    AND  CAST(oe.user_id AS UNSIGNED) NOT IN (SELECT id FROM excluded_users)
),
max_rank AS (                  -- 每个人最终推到了第几档
  SELECT user_id, MAX(tier_rank) AS max_tier_rank
  FROM   offer
  GROUP  BY user_id
)
SELECT offer.app_line                                             AS app_line,
       offer.tier                                                 AS tier,
       SUM(offer.action = 'shown' AND offer.surface = 'inline')   AS shows_inline,
       SUM(offer.action = 'shown' AND offer.surface = 'full')     AS shows_full,
       -- 🛑 分母 = 这一档**有任何一条记录**的人,不是只算 `shown` ——
       --    实测有人只有 `accepted` 没有 `shown`(L3 到达 6 人却接受 8 人),
       --    只按 shown 做分母会算出 >100% 的接受率。
       COUNT(DISTINCT offer.user_id)                              AS reached_users,
       COUNT(DISTINCT CASE WHEN offer.action = 'declined'
                           THEN offer.user_id END)                AS declined_users,
       -- 见口径 ⑤:accepted 不带 surface,只能给合计
       COUNT(DISTINCT CASE WHEN offer.action = 'accepted'
                           THEN offer.user_id END)                AS accepted_users,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN offer.action = 'accepted'
                                         THEN offer.user_id END)
                   / NULLIF(COUNT(DISTINCT offer.user_id), 0), 1) AS accept_pct,
       -- 见口径 ③:后来见过更高的档,不代表是「买了才推进」
       COUNT(DISTINCT CASE WHEN max_rank.max_tier_rank > offer.tier_rank
                           THEN offer.user_id END)                AS advanced_users,
       ROUND(100.0 * COUNT(DISTINCT CASE WHEN max_rank.max_tier_rank > offer.tier_rank
                                         THEN offer.user_id END)
                   / NULLIF(COUNT(DISTINCT offer.user_id), 0), 1) AS advance_pct
FROM       offer
JOIN       max_rank ON max_rank.user_id = offer.user_id
GROUP BY   offer.app_line, offer.tier
ORDER BY   offer.app_line, offer.tier;

