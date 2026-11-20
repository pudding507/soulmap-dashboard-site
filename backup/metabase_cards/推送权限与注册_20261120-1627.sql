-- ═══ 🛑 2026-10-19:漏斗图 → 表格,因为这四级**不是嵌套关系** ═══
--   实测(近 30 天、弹过权限窗的设备):
--     授权=1 且 有token  2,673 台
--     授权=1 但 无token    111 台
--     **授权=0 但 有token 4,848 台**  ← 占「有 token」总数的 64%
--     授权=0 且 无token  2,019 台
--   原因:**FCM token 不依赖通知权限** —— Android 上 app 启动就能拿到 token,
--   用户拒绝通知权限照样有,只是推送发出去不显示。
--   ⇒ 原来画成「弹窗 → 授权 → token → 注册」的四级漏斗,第 3 级必然比第 2 级大,
--     在图上表现为「掉下去又涨回来」。**数没错,是展示形式错了。**
--   改动:拆成两条各自嵌套的线,用表格并排给出:
--     左:弹窗 → 授权(权限线)  ·  右:拿到 token → 服务端注册(推送能力线)
--     另出 token_without_grant 一列,把那 64% 显式标出来。
--   🛑 **两条线之间不要相除**。
--   版本筛选逻辑(最近 3 个 + 5% 相对下限)原样保留,未改。
-- 【展示形式】**表格**(2026-10-20 由漏斗图改来)。三个理由:
--   ① 左右两组**互不嵌套**(见下面的实测),漏斗图天然表达「上一级包含下一级」,用在这里必然骗人;
--   ② 要同时读两组各自的人数和各自的率,漏斗图一次只能表达一条链;
--   ③ 另出「没授权但有 token」一列把那 64% 显式标出来 —— 这个数在漏斗图里无处安放。
WITH device_version AS (          -- 设备进入漏斗那一刻所在的版本(锚点事件的最早一条)
  -- 为什么取锚点事件而不是 first_open:本卡队列由推送事件定义,设备可能装机于窗口之前,
  --   取不到 first_open。且 30 天内设备可能升级过,用「进入漏斗时」的版本归组语义最清楚。
  -- ⚠️ 用顶层 `version` 列,不用 params->>'$.app_version' —— 后者会把不同版本合并成一个,
  --    同 `Activation_guardrail funnel` 头部 2026-09-07 ④。
  SELECT user_pseudo_id AS device_id, version AS app_version
  FROM (
    SELECT user_pseudo_id, version,
           ROW_NUMBER() OVER (PARTITION BY user_pseudo_id ORDER BY event_timestamp) AS rn
    FROM host.firebase_event
    WHERE event_name = 'push_permission_result'
      AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
      AND version IS NOT NULL AND version <> ''
  ) AS ranked
  WHERE rn = 1
),
version_pick AS (                -- 最近 3 个版本,带 5% 相对下限
  -- 🛑 下限用**占本队列的 5%**,不是固定台数 —— 两张推送卡的队列规模差 6 倍
  --    (setup 约 1.6 万台 / delivery 约 2,700 台),固定阈值必然一边太松一边太严。
  -- 🛑 为什么要下限:严格按版本号取最近 3 个会选中灰度/预发布包。实测 2026-09-21:
  --    setup 卡里 3.0.3 只有 91 台、3.0.1 只有 237 台,会把真正在跑的 3.0.0(2,228 台)挤掉。
  --    同一个坑 `Activation_guardrail funnel` 2026-09-18 踩过。
  SELECT app_version FROM (
    SELECT app_version, COUNT(*) AS devices,
           CAST(SUBSTRING_INDEX(app_version,'.',1) AS UNSIGNED) * 1000000
         + CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(app_version,'.',2),'.',-1) AS UNSIGNED) * 1000
         + CAST(SUBSTRING_INDEX(app_version,'.',-1) AS UNSIGNED)          AS version_numeric,
           SUM(COUNT(*)) OVER ()                                          AS cohort_devices
    FROM device_version GROUP BY app_version
  ) AS sized
  WHERE devices >= 0.05 * cohort_devices
  ORDER BY version_numeric DESC
  LIMIT 3
),
push_device AS (                  -- 每台设备:各步是否到达
  SELECT user_pseudo_id                                        AS device_id,
         COALESCE(MAX(params ->> '$.os'), 'unknown')            AS os,
         MAX(event_name = 'push_permission_result')             AS reached_prompt,
         MAX(event_name = 'push_permission_result'
             AND params ->> '$.granted' = 'true')               AS reached_granted,
         MAX(event_name = 'push_token_obtained'
             AND params ->> '$.ok' = 'true')                     AS reached_token,
         MAX(event_name = 'push_register_result'
             AND params ->> '$.ok' = 'true')                     AS reached_registered
  FROM host.firebase_event
  WHERE event_name IN ('push_permission_result','push_token_obtained','push_register_result')
    AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
  GROUP BY device_id
  HAVING reached_prompt = 1            -- 只看弹过权限窗的设备
),
cohort_with_version AS (         -- 只保留落在最近 3 个版本里的设备
  SELECT d.*, dv.app_version
  FROM push_device AS d
  JOIN device_version AS dv ON dv.device_id = d.device_id
  JOIN version_pick   AS vp ON vp.app_version = dv.app_version
)
SELECT app_version                                                        AS app_version,
       COUNT(*)                                                           AS prompt_devices,
       -- ── 左边一条线:权限。弹窗 → 授权,这两级是真嵌套 ──
       SUM(reached_granted)                                               AS granted_devices,
       ROUND(SUM(reached_granted) / COUNT(*), 4)                          AS granted_rate,
       -- ── 右边一条线:推送能力。拿到 token → 服务端注册,这两级也是真嵌套 ──
       -- 🛑 但它**和左边不嵌套** —— token 不依赖通知权限(见卡头),不要拿它除授权数
       SUM(reached_token)                                                 AS token_devices,
       SUM(reached_registered)                                            AS registered_devices,
       ROUND(SUM(reached_registered) / NULLIF(SUM(reached_token), 0), 4)  AS registered_rate,
       -- ── 两条线的交叉:有多少人是「没授权但有 token」 ──
       SUM(reached_token AND NOT reached_granted)                         AS token_without_grant,
       ROUND(SUM(reached_token AND NOT reached_granted)
             / NULLIF(SUM(reached_token), 0), 4)                          AS token_without_grant_rate
FROM cohort_with_version
GROUP BY app_version
ORDER BY app_version DESC;

