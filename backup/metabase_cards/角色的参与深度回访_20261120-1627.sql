-- 🔴 2026-11-12:**本卡是 D-563「CityPLX 并列一栏」的例外,仍然剔除 CityPLX。**
--    为什么例外:本卡读 `soulmap_chat_history`,CityPLX 在这张表里有 3,792 人、
--    近 14 天 24,816 条消息(占全部的 **6.9%**)。把他们加回来之后本卡**跑不进 60 秒**,
--    卡会从看板上消失 —— 少一张卡比口径不统一更糟,所以这里按「仍剔除」处理。
--    🛑 读本卡时请记住:**分母里没有 CityPLX**,不要和已经并列成两栏的那些卡相加。
--    ⬜ 等本卡本身提速之后再按 D-563 统一。
--    ✅ 这次顺带留下的两处提速(与剔不剔无关,都保留):
--       ① 原来「排除集」和「CityPLX 标记集」是两个 CTE、join 两次,现在合成一个 `user_line` 只 join 一次。
--       ② 原 CityPLX 排除集里「扫正文含 CITY situation / from the game system」那一半
--          实测**多抓到 0 个人**(`app_source='city'` 已全覆盖),却要对 21 天聊天表做两次 LIKE 全扫,已删。
WITH cityplx AS (                -- 🛑 CityPLX 排除集
  -- 🛑 **只按 `app_source` 判,不再扫正文** —— 原来还 UNION 了「近 21 天正文含
  --    `CITY situation` / `from the game system`」那一半。实测它**多抓到 0 个人**
  --    (`app_source='city'` 已经全覆盖),却要对 21 天的 `soulmap_chat_history`
  --    做两次 LIKE 全扫。去掉是净省时间。
  SELECT id AS user_id FROM soul_map.`user` WHERE app_source = 'city'
),
first_touch AS (                 -- 每个(人, 角色)的首次聊天时刻 —— 这是分母的锚(见口径 ①)
  SELECT c.user_id                                                   AS user_id,
         REPLACE(COALESCE(NULLIF(c.host_id,''), s.host_id),
                 'original:', '')                                    AS host_key,
         MIN(c.add_on)                                               AS first_at
  FROM soul_map.soulmap_chat_history AS c
  LEFT JOIN soul_map.soulmap_session AS s ON s.session_id = c.session_id
  WHERE c.role = 'user'
    AND CAST(c.user_id AS UNSIGNED) NOT IN (SELECT user_id FROM cityplx)   -- 🔴 2026-11-12:仍然剔,见卡头
    AND c.add_on >= CURDATE() - INTERVAL 21 DAY
    AND COALESCE(NULLIF(c.host_id,''), s.host_id) IS NOT NULL
    -- 🛑 2026-10-26 加:剔 CityPLX,见口径 ⑥

  GROUP BY c.user_id, host_key
),
day0 AS (                        -- 首日对该角色发了多少条
  SELECT f.user_id, f.host_key, f.first_at,
         (SELECT COUNT(*) FROM soul_map.soulmap_chat_history AS c2
          LEFT JOIN soul_map.soulmap_session AS s2 ON s2.session_id = c2.session_id
          WHERE c2.user_id = f.user_id AND c2.role = 'user'
            AND REPLACE(COALESCE(NULLIF(c2.host_id,''), s2.host_id),'original:','') = f.host_key
            AND DATE(c2.add_on) = DATE(f.first_at))                  AS day0_msgs,
         -- 🛑 回来用小时窗口(见口径 ④)
         EXISTS(SELECT 1 FROM soul_map.soulmap_chat_history AS c3
                LEFT JOIN soul_map.soulmap_session AS s3 ON s3.session_id = c3.session_id
                WHERE c3.user_id = f.user_id AND c3.role = 'user'
                  AND REPLACE(COALESCE(NULLIF(c3.host_id,''), s3.host_id),'original:','') = f.host_key
                  AND c3.add_on >= f.first_at + INTERVAL 24 HOUR
                  AND c3.add_on <  f.first_at + INTERVAL 48 HOUR)    AS returned_24_48h
  FROM first_touch AS f
)
SELECT d.host_key                                                            AS host_key,
       COALESCE(h.display_name, h.name, d.host_key)                          AS host_name,
      CASE WHEN h.roster_batch  = 'user-created' THEN '用户自建'
           WHEN h.review_status <> 'approved'    THEN '(未上线)'
           WHEN h.character_type = 'realistic'   THEN 'A 类 (realistic)'
           WHEN h.character_type = 'fictional'   THEN 'B 类 (fictional)'
           ELSE '(未分类)' END                                              AS char_class,
       COUNT(*)                                                              AS new_chatters,
       SUM(d.day0_msgs > 3)                                                  AS engaged_gt3,
       ROUND(SUM(d.day0_msgs > 3)  / COUNT(*), 4)                            AS engage_rate,
       SUM(d.day0_msgs >= 10)                                                AS deep_ge10,
       ROUND(SUM(d.day0_msgs >= 10) / COUNT(*), 4)                           AS deep_rate,
       SUM(d.day0_msgs >= 100)                                               AS heavy_ge100,
       ROUND(SUM(d.day0_msgs >= 100) / COUNT(*), 4)                          AS heavy_rate,
       SUM(d.returned_24_48h)                                                AS returned,
       ROUND(SUM(d.returned_24_48h) / COUNT(*), 4)                           AS return_rate
FROM day0 AS d
LEFT JOIN soul_map.soulmap_host_info AS h
       ON h.host_key = d.host_key COLLATE utf8mb4_0900_ai_ci
GROUP BY d.host_key, host_name, char_class
HAVING new_chatters >= 10        -- 🛑 不足 10 人不出,避免长尾噪声(见展示形式 ④)
ORDER BY new_chatters DESC;

