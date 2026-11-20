-- 语音 · 等待与漏回(服务端) · Voice — Latency & Miss Rate (Server)
-- 【展示形式】表格。一行一天,要逐天读上线前后的变化,数值比趋势重要。
--
-- 2026-10-14 新建。起因:语音界面改动(收到 final 就显示用户的话 + 播「思考中」动画)
--   即将上线,**基线必须在上线前落成卡**,否则上线后没有干净的对照。
--
-- 输出形状:date | voice_user_msgs | miss_n | miss_pct | pending_n
--          | asr_p50_s | first_audio_p50_s | wait_after_asr_p50_s | over_10s_n | over_10s_pct
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑🛑 `wait_after_asr_p50_s` 才是团队说的那个「4.9 秒」                   ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   两个数落在**不同的行**上:`asrMs` 在 user 行,`firstAudioMs` / `totalMs` 在 host 行,
--   而同一轮的两行 `add_on` **完全相同**(都在整轮结束时才落库)
--   ⇒ **行间时间戳推不出等待**,只能用这两个字段相减。
--   实测 4,828 轮里只有 34 轮(0.7%)出现 `firstAudioMs < asrMs` ⇒ **两者起点一致**,
--   所以差值与起点是什么无关。`firstAudioMs − asrMs` 中位数 **4.90 秒**,正是那个数。
--   ⇒ 它测的是**转写完成之后**的等待(模型生成 + 合成语音),**不是从用户说完算起**。
--   ⚠️ **用户实际感知的空白比它长** —— 还要加上转写那一段。加多少现在算不出来:
--      `voice_duration_ms` **整列是空的**,拆不开 asrMs 里「用户说话」和「转写耗时」。
--      **所以这一列是用户等待的下界,不是全部。**
--
-- ═══ 🛑 `pending_n` 不算漏回 —— 它是会话里**最后一条**,还没判定 ═══
--   会话的最后一条用户消息后面本来就没有下一行,**那不等于「没回复」**,
--   尤其当天还没走完的会话全部长这样。
--   2026-10-14 踩过:把 `next_role IS NULL` 并进 miss,当天的漏回率被抬到 27.1%,
--   而前几天都在 8~16% —— 那个跳变是口径造成的,不是真的。
--   ⇒ **`miss_n` 只数「下一行还是用户」** (= 确实没等到回复就又说了一句);
--     `pending_n` 单列,**不进分子也不进分母的判定**。
--   ⇒ 最近一天的 `pending_n` 天然偏大,**那天的 miss_pct 要等第二天再读**。
--
-- ═══ 🛑 `miss_pct` 是服务端口径的漏回,和客户端 `voice_reply_no_audio` 不是一个数 ═══
--   本卡数的是「**根本没有回复**」;客户端那个数的是「有回复但没出声」。
--   两个都要看,但**不能相加、也不能互相替代**。客户端那半见另一张卡。
--
-- ⚠️ 全部来自服务端 `soul_map.soulmap_chat_history`,**不缺 2026-10-11**。
--   客户端埋点缺那天,所以**本卡和客户端那张卡在 10-11 对不上是正常的**。
-- ⚠️ `add_on` 是 SGT。
-- ⚠️ 中位数用行号法取,偶数条时取中间两条的均值。分母 < 10 的那天读不出。
-- ⚠️ 窗口从 2026-10-08(安卓 3.6.0 放量 02:11)起,再往前不是同一个客户端。
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🛑 2026-10-22 性能改写:66s → 26s。改了什么、为什么、动没动口径              ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   **动机**:本卡从 10-10 起一直超 Nginx 的 60 秒网关超时,线上看板抓不到,
--   一直在沿用旧值。口径**一个字没改**,逐日比对与原版完全一致(见文末对照)。
--
--   ① **先圈出「有语音的会话」,再做窗口函数**(新增 voice_session CTE)。
--      原版对 10-08 以来**全部 32.5 万行**做 `LEAD(...) PARTITION BY session_id`,
--      但其中只有 **1,769 / 28,674 个会话(6%)**出现过用户语音,其余 94% 白算。
--      圈定之后参与窗口的行数砍掉九成多。
--      🛑 这**不改口径**:voice_session 只筛会话、不筛行,命中的会话**全部行**照旧进窗口,
--        所以 next_role 的判定和原来一模一样。
--
--   ② **`FORCE INDEX (PRIMARY)` 不能去掉**。不写的话优化器给 voice_session 选 idx_session,
--      为了省掉按 session_id 的排序,它会把**全表 140 万行的索引项扫一遍再逐行回表** ——
--      比老老实实全表扫还慢。实测 44.6s(走 idx_session) vs 25.9s(强制走主键)。
--      ⚠️ soulmap_chat_history **没有 add_on 单列索引**,所以「找出语音会话」这一趟
--        必然是一次全表扫(实测约 12 秒),那是本卡的时间下限。
--
--   ③ **相关子查询换成窗口函数取下一条 host 行的 id**:
--        MIN(CASE WHEN role<>'user' THEN id END)
--          OVER (PARTITION BY session_id ORDER BY id ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)
--      等价于原来的 `h.id = (SELECT MIN(h2.id) ... WHERE h2.session_id=u.session_id
--      AND h2.id>u.id AND h2.role<>'user')`,但不用每行跑一次子查询;
--      拿到 id 之后按**主键**单行取那条 host 行,是全查询最便宜的一步。
--
--   ④ **删掉 host_voice 这个 CTE** —— 它从建卡起就没被任何地方引用(死代码),
--      而它会对每条 host 行解析一次 metadata JSON。
--
--   ⑤ **user_voice 的 GROUP BY 去掉 asr_ms**。原版按 (d, asr_ms) 分组、day_count 再求和,
--      结果和直接按 d 分组完全相同,但白白对每条用户语音行解析一次 JSON。
--      两个 CTE 因此合并成一个 day_count。
--
--   ═══ 实测计时(2026-10-22,逐条单独跑)═══
--     原版,窗口缩到 10-19(**只有 4 天**)            225.7s
--     原版,正常窗口 10-08(15 天)                   跑满 12 分钟没出来,手动中止
--     新版,只做 ①③④⑤(不加 FORCE INDEX),15 天      44.6s
--     新版,①~⑤ 全上,15 天                        **25.9s**  ← 现行
--     参照:单跑一次 10-08 以来的全表扫                12.4s(本卡的时间下限)
--   ⚠️ 台账里 10-20 记的「415 已优化到 65.9s」指的是**中途那一版**(只换掉相关子查询),
--      不是原版。原版从来没在 60 秒内跑完过。
--
--   ═══ 等价性验证(2026-10-22)═══
--     两版都把窗口缩到 10-19 各跑一次,逐日逐列对比:
--     **10-19 / 10-20 / 10-21 三个完整日,十列数字全部相同。**
--     10-22 当天两版不同(539 vs 531),是因为两次跑的时点不同、当天还在进数,不是口径差异。


WITH voice_session AS (
  SELECT DISTINCT session_id
  FROM soul_map.soulmap_chat_history FORCE INDEX (PRIMARY)
  WHERE add_on >= '2026-10-08' AND role = 'user' AND modality = 'voice'
),
turn AS (
  SELECT c.id, c.session_id, c.role, c.modality, c.metadata,
         DATE(c.add_on) AS d,
         LEAD(c.role) OVER (PARTITION BY c.session_id ORDER BY c.add_on, c.id) AS next_role,
         MIN(CASE WHEN c.role <> 'user' THEN c.id END)
           OVER (PARTITION BY c.session_id ORDER BY c.id
                 ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)             AS next_host_id
  FROM soul_map.soulmap_chat_history AS c
  JOIN voice_session AS vs ON vs.session_id = c.session_id
  WHERE c.add_on >= '2026-10-08'
),
day_count AS (
  SELECT d                                                     AS d,
         COUNT(*)                                              AS voice_user_msgs,
         SUM(next_role = 'user')                               AS miss_n,
         SUM(next_role IS NULL)                                AS pending_n
  FROM turn
  WHERE role = 'user' AND modality = 'voice'
  GROUP BY d
),
paired AS (
  SELECT u.d AS d,
         CAST(JSON_UNQUOTE(JSON_EXTRACT(u.metadata, '$.asrMs'))        AS DECIMAL(12,2)) AS asr_ms,
         CAST(JSON_UNQUOTE(JSON_EXTRACT(h.metadata, '$.firstAudioMs')) AS DECIMAL(12,2)) AS first_audio_ms
  FROM turn AS u
  JOIN soul_map.soulmap_chat_history AS h ON h.id = u.next_host_id
  WHERE u.role = 'user' AND u.modality = 'voice'
    AND JSON_EXTRACT(u.metadata, '$.asrMs')        IS NOT NULL
    AND JSON_EXTRACT(h.metadata, '$.firstAudioMs') IS NOT NULL
),
ranked AS (
  SELECT d, asr_ms, first_audio_ms, (first_audio_ms - asr_ms) AS wait_ms,
         ROW_NUMBER() OVER (PARTITION BY d ORDER BY asr_ms)                   AS rn_asr,
         ROW_NUMBER() OVER (PARTITION BY d ORDER BY first_audio_ms)           AS rn_fa,
         ROW_NUMBER() OVER (PARTITION BY d ORDER BY (first_audio_ms-asr_ms))  AS rn_wait,
         COUNT(*)    OVER (PARTITION BY d)                                    AS cnt
  FROM paired
),
medians AS (
  SELECT d, cnt,
         AVG(CASE WHEN rn_asr  IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2)) THEN asr_ms END)         AS asr_p50,
         AVG(CASE WHEN rn_fa   IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2)) THEN first_audio_ms END) AS fa_p50,
         AVG(CASE WHEN rn_wait IN (FLOOR((cnt+1)/2), CEIL((cnt+1)/2)) THEN wait_ms END)        AS wait_p50,
         SUM(first_audio_ms > 10000)                                                           AS over_10s_n
  FROM ranked GROUP BY d, cnt
)
SELECT dc.d                                               AS date,
       dc.voice_user_msgs                                 AS voice_user_msgs,
       dc.miss_n                                          AS miss_n,
       ROUND(100.0 * dc.miss_n / NULLIF(dc.voice_user_msgs - dc.pending_n, 0), 1) AS miss_pct,
       dc.pending_n                                       AS pending_n,
       ROUND(m.asr_p50  / 1000, 2)                        AS asr_p50_s,
       ROUND(m.fa_p50   / 1000, 2)                        AS first_audio_p50_s,
       ROUND(m.wait_p50 / 1000, 2)                        AS wait_after_asr_p50_s,
       m.over_10s_n                                       AS over_10s_n,
       ROUND(100.0 * m.over_10s_n / NULLIF(m.cnt, 0), 1)  AS over_10s_pct
FROM day_count AS dc
LEFT JOIN medians AS m ON m.d = dc.d
ORDER BY dc.d DESC;

