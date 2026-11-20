-- 风险_合照参考照上传量 · Risk — Reference Photo Uploads
--
-- ═══ 🛑 这张卡的作用是看风险,不是看增长 ═══
--   **功能不存在,但用户已经在上传自己的真人照片。**
--   合照算法还没做,客户端 172 把这个开关标成「3.7.1 包里开没开不确定,待确认」——
--   数据里已经确认是**开着的**。
--   产品要定的是:先关掉入口,还是加文案说明照片会用来做什么。
--   ⇒ 所以这张卡盯的是「现在有多少真人照片躺在库里」,不是转化率。
--
-- 【展示形式】**表格**,一行一天。量很小(每天个位数到几十),画折线没有意义,
--   而且要同时读「当天新增」和「累计仍在库」两个口径,表格更直接。
--
-- 🛑 口径
-- ① 权威数以服务端 `soulmap_user_media` 为准(kind='ref_photo'),客户端 sp_step 只做补充。
-- ② `status` 两个值:active(仍在库) / deleted(用户删了)。**deleted 的行不会消失**,
--    所以「当天上传」要按 created_at 数全部行,「仍在库」要按 status='active' 数。
-- ③ **累计在库是按天滚动算的**,不是当天新增 —— 看风险要看存量。
-- ④ 客户端那几步在 `host.firebase_event` 的 **`sp_step` 里**,是 `params.step` 的取值,
--    **不是独立事件名**(查不到 ref_photo_* 这个 event_name 是正常的)。
-- ⑤ firebase 是 T+1 入库,所以客户端三列**最后一天通常是 0**,不是没人用。
WITH media_day AS (              -- 服务端:每天上传与删除
  SELECT DATE(created_at)                                        AS d,
         COUNT(*)                                                AS uploaded,
         COUNT(DISTINCT user_id)                                 AS uploaded_users,
         SUM(status = 'deleted')                                 AS later_deleted
  FROM soul_map.soulmap_user_media
  WHERE kind = 'ref_photo'
  GROUP BY DATE(created_at)
),
cum AS (                         -- 累计仍在库(按天滚动)
  SELECT d, uploaded, uploaded_users, later_deleted,
         SUM(uploaded - later_deleted) OVER (ORDER BY d)         AS active_cumulative
  FROM media_day
),
client_day AS (                  -- 客户端:卡片展示 / 点添加 / 设置成功(都在 sp_step 里)
  SELECT STR_TO_DATE(event_date, '%Y%m%d')                                          AS d,
         COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'ref_photo_card_shown'
                             THEN user_pseudo_id END)                               AS card_shown_devices,
         COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'ref_photo_add_tap'
                             THEN user_pseudo_id END)                               AS add_tap_devices,
         COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'ref_photo_set_result'
                              AND params ->> '$.result' = 'ok'
                             THEN user_pseudo_id END)                               AS set_ok_devices
  FROM host.firebase_event
  WHERE event_name = 'sp_step'                 -- 🛑 必须留,否则用不上索引
    AND event_date >= '20261015'
  GROUP BY STR_TO_DATE(event_date, '%Y%m%d')
)
SELECT c.d                                     AS date,
       c.uploaded                              AS uploaded,
       c.uploaded_users                        AS uploaded_users,
       c.later_deleted                         AS later_deleted,
       c.active_cumulative                     AS active_cumulative,
       COALESCE(cl.card_shown_devices, 0)      AS card_shown_devices,
       COALESCE(cl.add_tap_devices, 0)         AS add_tap_devices,
       COALESCE(cl.set_ok_devices, 0)          AS set_ok_devices
FROM cum AS c
LEFT JOIN client_day AS cl ON cl.d = c.d
ORDER BY c.d DESC;

