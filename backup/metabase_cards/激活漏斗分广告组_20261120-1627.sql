-- 🔴 2026-11-05 加 / 11-06 更正:本卡跨 **2026-11-02 ~ 11-05** 不可比(投放侧切点)
--   投放把 Meta 优化目标从 install 改成 purchase,**11-02 起分批切,11-05 才全部切完**
--   (按 Meta 导出的 Result indicator:11-02 两个 B 类先切 → 11-04 Sander/Yui → 11-05 五个齐)。
--   🛑 原注释写「11-03 一次性切」是错的,切点要按区间处理。
--   后果:
--     · 日装机 630~894 → 75~172(−89%);CPI 0.15~0.20 → 0.605 → 1.051(×7)
--     · 四个 campaign 11-03 当天同时归零 —— Meta 按新目标重新分配了流量,
--       所以本卡**分组的构成本身变了**,不只是量变少了
--   🛑 **这是改优化目标的定义性后果,不是这些素材 / 广告组变差了。**
--      同期当日成交充值 9/6/9/8 → 8/8 一笔没掉,每笔充值成本 25.99/39.43
--      仍落在切换前的波动区间(18.23~38.78)内。
--   ⇒ 读法:**11-02 之前 / 11-05 之后当成两段,中间四天是过渡不单独读**。
--      判断素材 / 广告组好坏只在同一段内横比,
--      跨段比的是两套不同的流量分配。
--   出处:`_已落地改动台账.md` 切点总表「11-03(投放侧)」· 飞书「Meta 广告核对」`Sq7CFh`
--
-- 🔴 2026-11-03 性能:本卡此前**每次都 60 秒网关超时(504),一行都出不来**。
--    瓶颈不是 firebase_event,是下面两个 CTE 对 `soulmap_chat_history` 做
--    **全表、全历史**的 GROUP BY —— 为了「全历史累计句数」这个口径,它们没有任何
--    日期限制,等于每跑一次卡就把整张聊天表数一遍。
--    【改法】口径一个字不改,只是**先把本次队列的账号列出来,再拿它去 join 聊天表**:
--      仍然不限日期(所以还是「全历史累计」),但只数队列里这批人的,
--      能吃上 `idx_uid(user_id)` / `idx_user_host_id(user_id,host_id,id)` 两个索引,
--      不再全表扫。🛑 **数值应当与改前完全一致** —— 队列外的用户本来也进不了漏斗,
--      他们的统计算出来只是被 LEFT JOIN 丢掉。
-- 🔴 2026-11-03:加一级「买过能量」—— 能量系统 2026-10-28 14:32:20 上线,
--    10-31 起订阅首购基本归零、能量包接管(实测首购 10-24~10-28 每天 5~11 笔 →
--    10-30 起 1 / 0 / 2 / 0 / 0;同期能量包从 0 涨到每天 9~13 笔),
--    这个漏斗不加这一级就看不到变现的新出口。
--    口径:`soulmap_energy_lot` 里 `layer='purchased' AND source='purchase'` 的账号
--    (全库至今 52 笔 / 30 人)。🛑 **不要用 `source='price_update_20261029'`** ——
--    那是改价补偿,不是购买。
--    🛑 **这一级每组只有个位数,只读绝对人数,不要算转化率**(口径清单:分子 <10 不给比率)。
--    🛑 本卡窗口只覆盖最近几周的装机,而能量上线才几天 ⇒ **这一级天然偏小**,
--       不能和上面几级的漏斗收窄放在一起解释。
--
-- 🛑 2026-11-03:本文件以**线上版为基线**重写(原本地版与线上不一致,差异见台账)。
--    这么做是为了不把线上已有、本地没有的改动静默回滚掉。

WITH
energy_buyers AS (                     -- 2026-11-03 新增:买过能量包的账号
  SELECT DISTINCT user_id
  FROM   soul_map.soulmap_energy_lot
  WHERE  layer = 'purchased' AND source = 'purchase'
),
fe AS (
  SELECT user_pseudo_id AS device_id,
    MAX(CASE WHEN uid <> '' AND uid IS NOT NULL THEN CAST(uid AS UNSIGNED) END) AS account_id,
    STR_TO_DATE(MIN(CASE WHEN event_name='first_open' THEN event_date END),'%Y%m%d') AS idt,
    MIN(CASE WHEN event_name='first_open' THEN NULLIF(version,'') END) AS app_version,
    MIN(CASE WHEN event_name='attribution_received' THEN params->>'$.pf'   END) AS pf,
    MIN(CASE WHEN event_name='attribution_received' THEN params->>'$.type' END) AS type,
    -- 2026-09-18:onboarding 自 3.1.1 起对广告用户已移除,原先的 s_welcome /
    --   s_onb_start / s_onb_done 三个标记连同下游三个 step 一并删除。见头部同日说明。
    MAX(event_name='first_open')                              s_open
  FROM host.firebase_event
  WHERE event_name IN ('first_open','attribution_received')   -- 见头部 09-08:不加这行索引用不上;first_text/audio_sent 见 2026-09-15;onboarding 三个事件见 2026-09-18
    AND event_date >= DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL ((WEEKDAY(CURDATE())+2)%7 + 21) DAY),'%Y%m%d')
  GROUP BY user_pseudo_id
),
cohort_accounts AS (        -- 🔴 2026-11-03:本次队列的账号,用来把聊天表的扫描限在这批人上
  SELECT DISTINCT CAST(fe.account_id AS CHAR) COLLATE utf8mb4_unicode_ci AS user_id
  FROM   fe
  WHERE  fe.account_id IS NOT NULL
),
user_max_messages_single_host AS (   -- 2026-09-18 新增:每用户与**单个 host** 的最大累计消息数
  -- ⚠️ 排除 reception-default(系统接待,不是角色),与 QCD 口径一致
  SELECT user_id, MAX(messages_with_host) AS max_messages_single_host
  FROM (
      SELECT ch.user_id, ch.host_id, COUNT(*) AS messages_with_host
      FROM soul_map.soulmap_chat_history AS ch
      JOIN cohort_accounts AS ca ON ca.user_id = ch.user_id    -- 🔴 2026-11-03:只数本次队列,见卡头
      WHERE ch.role = 'user' AND ch.content IS NOT NULL AND ch.content <> ''
        AND ch.host_id <> 'reception-default'
      GROUP BY ch.user_id, ch.host_id
  ) per_user_host
  GROUP BY user_id
),
user_total_messages AS (          -- 每用户**全历史**累计非空用户消息数(不限 host)
  -- ⚠️ 2026-09-18:曾尝试与下方 single_host 合并为一次扫描,**但无法判断快慢** ——
  --    同一份 SQL 连跑三轮实测 6.9s / 25.4s / 48.4s(差 7 倍),库负载波动完全淹没了结构差异。
  --    ⇒ **不要用单次计时做优化判断。** 当前保持两个 CTE 是因为语义清晰,不是因为它更快。
  --    若日后要认真优化,需在低峰期多轮取中位数,或直接看 EXPLAIN。
  SELECT ch.user_id, COUNT(*) AS total_messages
  FROM soul_map.soulmap_chat_history AS ch
  JOIN cohort_accounts AS ca ON ca.user_id = ch.user_id        -- 🔴 2026-11-03:只数本次队列,见卡头
  WHERE ch.role = 'user' AND ch.content IS NOT NULL AND ch.content <> ''
  GROUP BY ch.user_id
),
u AS (
  SELECT
    CONCAT(
      CASE WHEN fe.pf LIKE '%Organic%'   THEN 'Organic'
           WHEN fe.pf LIKE '%Google%'    THEN 'Google'
           WHEN fe.pf LIKE '%Facebook%' OR fe.pf LIKE '%Instagram%'
             OR fe.pf IN ('fb','meta')   THEN 'Facebook'
           WHEN fe.pf LIKE '%TikTok%' OR fe.pf IN ('tt','tiktok') THEN 'TikTok'
           WHEN fe.pf IS NULL           THEN 'others'
           ELSE fe.pf END,
      '_',
      COALESCE(NULLIF(SUBSTRING_INDEX(SUBSTRING_INDEX(fe.type,' (',1),'_',-1),''),'others')
    ) AS grp,   -- source + 广告类型最后一段(如 Facebook_career / Facebook_burnout)
    fe.app_version,
    fe.s_open,
    (m.total_messages >= 1)  AS s_msg1,
    (m.total_messages >= 3)  AS s_msg3,
    (m.total_messages >= 5)  AS s_msg5,
    (m.total_messages >= 10) AS s_msg10,
    (m.total_messages >= 20) AS s_msg20,
    (h.max_messages_single_host >= 20) AS s_single_host_msg20,
    (eb.user_id IS NOT NULL)           AS s_bought_energy
  -- account_id 是 UNSIGNED、chat_history.user_id 是 varchar/unicode_ci ⇒ 必须显式 CAST + COLLATE,否则 1267
  FROM fe
  LEFT JOIN user_max_messages_single_host h
         ON h.user_id = CAST(fe.account_id AS CHAR) COLLATE utf8mb4_unicode_ci
  LEFT JOIN user_total_messages m
         ON m.user_id = CAST(fe.account_id AS CHAR) COLLATE utf8mb4_unicode_ci   -- 取不到账号 ⇒ NULL ⇒ 记「未达」不剔除
  LEFT JOIN energy_buyers eb
         ON eb.user_id = CAST(fe.account_id AS CHAR) COLLATE utf8mb4_unicode_ci
  WHERE fe.idt IS NOT NULL
)
,
latest_version AS (                    -- 动态取最新的 1 个装机版本(按版本号数值降序),不写死
  -- ⚠️ HAVING install_devices >= 1000 是 2026-09-18 新增的下限,原因见头部同日说明。
  --    没有这道下限时,任何一台装了预发布包的设备都会被选成「最新版本」,整张卡归零。
  SELECT app_version FROM (
      SELECT app_version, COUNT(*) AS install_devices
      FROM u
      WHERE app_version IS NOT NULL AND app_version <> ''
      GROUP BY app_version
      HAVING install_devices >= 1000        -- 排除灰度/内测/预发布版本
  ) v
  ORDER BY CAST(SUBSTRING_INDEX(app_version,'.',1) AS UNSIGNED) * 1000000
         + CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(app_version,'.',2),'.',-1) AS UNSIGNED) * 1000
         + CAST(SUBSTRING_INDEX(app_version,'.',-1) AS UNSIGNED) DESC
  LIMIT 1
),
u_latest AS (
  SELECT * FROM u WHERE app_version IN (SELECT app_version FROM latest_version)
)
SELECT step, grp, COUNT(*) AS users
FROM (
  SELECT grp, '1_打开'              AS step FROM u_latest WHERE s_open
  UNION ALL SELECT grp, '2_累计1句'          FROM u_latest WHERE s_msg1
  UNION ALL SELECT grp, '3_累计3句'          FROM u_latest WHERE s_msg3
  UNION ALL SELECT grp, '4_累计5句'          FROM u_latest WHERE s_msg5
  UNION ALL SELECT grp, '5_累计10句'         FROM u_latest WHERE s_msg10
  UNION ALL SELECT grp, '6_累计20句'         FROM u_latest WHERE s_msg20
  UNION ALL SELECT grp, '7_单host累计20句'   FROM u_latest WHERE s_single_host_msg20
  UNION ALL SELECT grp, '8_买过能量'         FROM u_latest WHERE s_bought_energy
) t
GROUP BY step, grp
ORDER BY step, grp;

