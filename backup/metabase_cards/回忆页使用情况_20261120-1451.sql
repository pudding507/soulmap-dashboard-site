-- SuperPower_我们的回忆页使用 · Super Power — Memories Page Usage
--
-- 2026-10-20 新建。这是 Super Power 里**唯一一个对所有角色都开**的入口,实测已经有量。
--
-- 【展示形式】**表格**,一行一天。量在百位数以内、而且要并排读漏斗三级 + 「有内容的占比」,
--   折线叠不下,也会把每天在动的分母藏起来。
--
-- ═══ 🛑 口径 ═══
-- ① **这几步不是独立事件名**,是 `sp_step` 的 `params.step` 取值。
--    按 event_name 去查 memories_* 会一条都查不到(字典里也容易被误读)。
-- ② 🛑 **入口对所有角色显示,大部分人的回忆是空的** ⇒ `count=0` 占比高是**正常的,不是 bug**。
--    实测 10 月:`memories_loaded` 207 次里 **203 次 kind='p0_l0_e0'(全空)**,
--    92 台设备里只有 **1 台**真的有内容。
-- ③ `kind` 字段的编码是 `p{照片数}_l{其中锁住的}_e{片段数}` ——
--    「有内容」= 这三个数**不全为 0**,用 kind <> 'p0_l0_e0' 判。
-- ④ 三级**不是严格嵌套**:entry_tap 是点入口、open 是页面打开、loaded 是数据加载完。
--    正常情况下 open ≈ entry_tap,loaded 可能多于 open(重复加载/筛选触发)。
--    ⇒ **不要把它们相除当转化率**,只看三个数的量级是否匹配。
-- ⑤ firebase 是 T+1 入库,**最后一天通常偏低或为 0**,不是没人用。
SELECT STR_TO_DATE(event_date, '%Y%m%d')                                        AS date,
       COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_entry_tap'
                           THEN user_pseudo_id END)                             AS entry_tap_devices,
       COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_open'
                           THEN user_pseudo_id END)                             AS open_devices,
       COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_loaded'
                           THEN user_pseudo_id END)                             AS loaded_devices,
       -- 有内容 = kind 不是全 0(见口径 ③)
       COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_loaded'
                            AND params ->> '$.kind' <> 'p0_l0_e0'
                           THEN user_pseudo_id END)                             AS loaded_nonempty_devices,
       ROUND(COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_loaded'
                                  AND params ->> '$.kind' <> 'p0_l0_e0'
                                 THEN user_pseudo_id END)
             / NULLIF(COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_loaded'
                                          THEN user_pseudo_id END), 0), 4)      AS nonempty_rate,
       COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_filter'
                           THEN user_pseudo_id END)                             AS filter_devices,
       COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_more_tap'
                           THEN user_pseudo_id END)                             AS more_tap_devices
FROM host.firebase_event
WHERE event_name = 'sp_step'                 -- 🛑 必须留,否则用不上 idx_event_name_date
  AND event_date >= '20261015'
  AND params ->> '$.step' LIKE 'memories%'
GROUP BY STR_TO_DATE(event_date, '%Y%m%d')
ORDER BY date DESC;

