-- 收入_每天续费 · Revenue — Renewals by Day
--
-- 2026-10-21 新建。对应 Michael 10-21 看板反馈 P0 第二条(D-371 / D-340),
-- 与 `收入_每天新首付` **成对使用,口径互斥不重叠**。
--
-- ═══ 🛑 本卡当前为空,这是结论不是故障 ═══
--   实测 2026-10-21:全库 **105 人付过钱,没有任何人扣过第二次**
--   (按人排序的 price_usd > 0 事件,第 1 次 105 人次、第 2 次 0)。
--   原因:① 0.99 买家最早 **2026-10-22** 才到期;
--        ② 那 29 个「免费试用到期扣全价」的人,下一个周期也还没到。
--   ⇒ 本卡从 10-22 起才会有行。**读到 0 行先看这一段,不要当成取数坏了。**
--
-- ═══ 🛑 「续费」的定义:同一个人**第 2 笔及以后**真的被扣到的钱 ═══
--   **不能按 event_type = 'RENEWAL' 判**。实测那 29 次 `RENEWAL` 全部是
--   **免费试用到期的第一次扣款**,对用户是「新首付」,已归到新首付那张卡。
--   按事件名判会让两张表重复计同一批人、总收入翻倍。
--   ⇒ 两张卡一律按 `pay_seq`(按人按时间排序的扣款序号)切:
--        pay_seq = 1  → 新首付卡
--        pay_seq >= 2 → 本卡
--   这样两张**互斥且穷尽**,相加 = 总收入。
--
-- ═══ 🛑 四个陷阱(同新首付卡)═══
-- ① `event_at` 是 **UTC**,分天前必须 CONVERT_TZ 到 SGT。
-- ② `environment = 'PRODUCTION'` 必须加(否则混进 sandbox)。
-- ③ 判「真的扣到钱」用 **price_usd > 0**,`INITIAL_PURCHASE + TRIAL` 是免费试用、一分没扣。
-- ④ 2026-11-12 起 CityPLX 不再剔除,改成 `app_line` 一列并列(D-563)。
--    实测 `subscription_event_log` 里没有任何 CityPLX 账号,所以这一列目前恒为 SoulMap。
--
-- 【展示形式】**表格**,一行 = 一天 × 国家 × 第几次续费。三个理由:
--   ① 「第几次续费」是个关键维度(第 2 次和第 5 次的留存含义完全不同),折线表达不了;
--   ② 和新首付卡成对读,两张保持同样的版式便于对照;
--   ③ 预期量级是个位数,画图没有意义。
WITH paid_event AS (
  SELECT e.user_id,
         e.event_at,
         e.period_type,
         e.price_usd,
         e.country_code,
         CASE WHEN u.app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line,
         ROW_NUMBER() OVER (PARTITION BY e.user_id ORDER BY e.event_at) AS pay_seq,
         LAG(e.event_at)  OVER (PARTITION BY e.user_id ORDER BY e.event_at) AS prev_pay_at
  FROM soul_map.subscription_event_log AS e
  JOIN soul_map.`user` AS u ON u.id = e.user_id
  WHERE e.environment = 'PRODUCTION'
    AND COALESCE(e.price_usd, 0) > 0
),
attr AS (
  SELECT c.user_id,
         SUBSTRING_INDEX(GROUP_CONCAT(NULLIF(l.network,'') ORDER BY l.add_on), ',', 1) AS network
  FROM (SELECT user_id FROM soul_map.soulmap_app_launch WHERE user_id <> '' GROUP BY user_id) c
  JOIN soul_map.soulmap_app_launch l ON l.user_id = c.user_id
  GROUP BY c.user_id
)
SELECT DATE(CONVERT_TZ(p.event_at, '+00:00', '+08:00'))                      AS date,
       p.app_line                                                            AS app_line,
       COALESCE(p.country_code, '?')                                         AS country,
       CASE WHEN a.network IS NULL OR a.network = ''   THEN '(无归因)'
            WHEN a.network = 'Organic'                 THEN '自然量'
            ELSE '广告' END                                                   AS acquisition,
       p.pay_seq                                                             AS pay_seq,
       COUNT(*)                                                              AS renewals,
       ROUND(SUM(p.price_usd), 2)                                            AS revenue_usd,
       -- 距上一笔多少天:0.99 周期实测 6.82 天、全价是一个月,差很多,放在一起看才分得开
       ROUND(AVG(TIMESTAMPDIFF(HOUR, p.prev_pay_at, p.event_at)) / 24, 1)    AS days_since_prev
FROM paid_event AS p
LEFT JOIN attr AS a ON a.user_id = CAST(p.user_id AS CHAR) COLLATE utf8mb4_0900_ai_ci
WHERE p.pay_seq >= 2                     -- 🛑 这一行是两张卡互斥的唯一开关
  -- 🛑 2026-11-20:只在最外层限展示窗口。pay_seq 必须拿全历史判,
  --    下推的话第二笔会被误判成第一笔。改之前这张卡返回全历史的每一天。
  -- 🛑 event_at 是 UTC,下界也换成 UTC 再比,两边窗口才对齐
  AND p.event_at >= CONVERT_TZ(CURDATE() - INTERVAL 30 DAY, '+08:00', '+00:00')
GROUP BY date, app_line, country, acquisition, p.pay_seq
ORDER BY date DESC, renewals DESC;
