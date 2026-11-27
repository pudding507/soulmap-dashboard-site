WITH u AS (
  SELECT user_pseudo_id AS device,   -- 按设备去重(下载量口径),不再按 uid
    MIN(CASE WHEN event_name='first_open' THEN event_date END)                     AS idt,
    MIN(CASE WHEN event_name='attribution_received' THEN params->>'$.pf'   END)    AS pf,
    MIN(CASE WHEN event_name='attribution_received' THEN params->>'$.type' END)    AS type,
    MIN(CASE WHEN event_name='first_open' THEN country END)                        AS country
  FROM host.firebase_event
  WHERE event_name IN ('first_open','attribution_received')   -- 见头部 09-08:不加这行索引用不上
    AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
  GROUP BY user_pseudo_id
  HAVING idt IS NOT NULL          -- 只保留近30天有 first_open 的新用户
)
SELECT
  STR_TO_DATE(idt,'%Y%m%d') AS date,
  CASE WHEN pf LIKE '%Organic%'   THEN 'Organic'
       WHEN pf LIKE '%Google%'    THEN 'Google'
       WHEN pf LIKE '%Facebook%' OR pf LIKE '%Instagram%'
         OR pf IN ('fb','meta')   THEN 'Facebook'
       WHEN pf LIKE '%TikTok%' OR pf IN ('tt','tiktok') THEN 'TikTok'
       WHEN pf IS NULL           THEN 'others'
       ELSE pf END  AS source,
  -- placement:保留 pf 原值,不做平台归并。见头部 2026-09-09。
  COALESCE(pf,'others')                                AS placement,
  COALESCE(NULLIF(SUBSTRING_INDEX(SUBSTRING_INDEX(type,' (',1),'_',-1),''),'others')  AS adgroup,
  COALESCE(country,'others')                           AS country,
  COUNT(*)                                             AS value
FROM u
GROUP BY date, source, placement, adgroup, country
ORDER BY date DESC, value Desc;

