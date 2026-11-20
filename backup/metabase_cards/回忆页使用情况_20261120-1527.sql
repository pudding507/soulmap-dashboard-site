-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-11-20:`more_tap_devices` 换成 `load_failed_devices`              ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【为什么删 more_tap】查库:`memories_more_tap` **有埋点以来总共只有 1 条**
--   (2026-10-18,1 台设备),之后再没有过。同期 `memories_entry_tap` 有 1,472 条。
--   ⇒ 不是「没人点」,是这个 step 压根没在发。一列常年占着位置、永远是 0。
--   🛑 本卡保留 `filter_devices`(1,799 条,比 open 还多)—— 那才是真实在用的交互。
--
--   【为什么补 load_failed】`memories_load_failed` 实测 25 条(10-20 ~ 11-11),
--   是这条链路**唯一的异常信号**,而卡上原来没有任何一列能看见它。
--   🛑 这一列**全 0 是好事,不要因为它是 0 就删** —— 它是探针不是业务量。
--
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
       -- 2026-11-20:原 more_tap_devices 换成这一列,见卡头。加载失败是本链路唯一的异常信号。
       COUNT(DISTINCT CASE WHEN params ->> '$.step' = 'memories_load_failed'
                           THEN user_pseudo_id END)                             AS load_failed_devices
FROM host.firebase_event
WHERE event_name = 'sp_step'                 -- 🛑 必须留,否则用不上 idx_event_name_date
  AND event_date >= '20261015'
  AND params ->> '$.step' LIKE 'memories%'
GROUP BY STR_TO_DATE(event_date, '%Y%m%d')
ORDER BY date DESC;
