-- ── 2026-11-20:取数窗口改成滚动 30 天(原来是写死 20261008,已 43 天)──────────────
--   全看板统一规则:**取数窗口最多 30 天**。写死的起点会随时间越拖越长,
--   抓数越来越慢 —— 「等待与漏回」就是这么从 26s 涨到 60s 抓数超时的。
--   🛑 这条规则**只管取数窗口**。实验起点、版本放量切点、人群定义
--      (如 `HAVING MIN(related_at) >= '2026-09-11'`)和留给回访判定的成熟期
--      **都不在此列**,它们改了会动口径。
--
-- 语音_播放结果与没出声原因_客户端 · Voice — Playback & No-Audio Reasons (Client)
--
-- 2026-11-19 补归档。这张卡此前只存在于 Metabase,本地没有副本 ——
--   本地 .sql 是这些卡唯一的变更历史(Metabase 自己不留),没有副本就查不到谁改过什么。
--   本文件是从 Metabase 卡 416 原样导出的当前版本,**没有改动过 SQL**。
-- 🛑 以后每次改这张卡,在这里加一行「日期 + 改了什么 + 为什么 + 影响」。

-- 语音 · 播放结果与没出声的原因(客户端) · Voice — Playback Outcome & No-Audio Reasons (Client)
-- 【展示形式】表格。两组各自成一块,组内按次数倒序,逐行读。不画饼图 —— 两组的分母不是同一个。
--
-- 2026-10-14 新建。起因:语音界面改动即将上线,**基线必须在上线前落成卡**。
--
-- 输出形状:grp | grp_en | item | item_cn | events | users | pct_within_grp
--
-- ═══ 🛑 两组的分母不同,**不要跨组相加或相除** ═══
--   `播放结果`  分母 = `voice_playback_result` 的全部次数(一次播放一行)
--   `没出声原因` 分母 = `voice_reply_no_audio` 的全部次数(只有没出声时才发)
--   ⇒ `pct_within_grp` 只在**组内**成立。
--
-- ═══ 🛑 「加思考中动画」能影响的只有 `interrupted` 这一行 ═══
--   `interrupted` = 用户在**出声之前**自己放弃了,这正是空白期造成的。
--   `no_audio` / `empty_reply` 是**服务端和模型**那一侧的事,动画动不了它们。
--   ⇒ 上线后若 `empty_reply` 占比也动了,**那不是动画的功劳**,先查这版还改了什么。
--
-- ═══ 🛑 没出声里八成是模型回了空,不是播放或网络的问题 ═══
--   实测 `empty_reply` 占 82.4%;各类 `error:*`(ws_error / upstream_closed /
--   asr_failed / upstream_error)加起来只有 9 次、1.1% ⇒ **链路故障不是主因**。
--
-- ⚠️ 本卡来自客户端埋点 `host.firebase_event`,**缺 2026-10-11 一整天**
--   (10-12 的入库作业没跑且后续不回补)。服务端那张卡不缺,
--   **两张卡在 10-11 对不上是正常的。**
-- ⚠️ 不按版本拆:3.6.0 和 3.6.1 的在线时长与人数都不同,**两版的次数不可直接比**。
--   要按版本看请用本地管线,并且只看占比不看绝对数。
-- ⚠️ 窗口从 2026-10-08(安卓 3.6.0 放量 02:11)起。
WITH playback AS (
  SELECT JSON_UNQUOTE(JSON_EXTRACT(params, '$.result')) AS item,
         COUNT(*) AS events, COUNT(DISTINCT uid) AS users
  FROM host.firebase_event
  WHERE event_name = 'voice_playback_result' AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
  GROUP BY item
),
no_audio AS (
  SELECT JSON_UNQUOTE(JSON_EXTRACT(params, '$.reason')) AS item,
         COUNT(*) AS events, COUNT(DISTINCT uid) AS users
  FROM host.firebase_event
  WHERE event_name = 'voice_reply_no_audio' AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
  GROUP BY item
)
SELECT '1 播放结果' AS grp, 'playback result' AS grp_en,
       p.item AS item,
       CASE p.item WHEN 'completed'     THEN '正常播完'
                   WHEN 'no_audio'      THEN '没有音频可播'
                   WHEN 'interrupted'   THEN '出声前被用户放弃'
                   WHEN 'quota_blocked' THEN '被额度拦住'
                   ELSE p.item END                               AS item_cn,
       p.events, p.users,
       ROUND(100.0 * p.events / SUM(p.events) OVER (), 1)        AS pct_within_grp
FROM playback AS p
UNION ALL
SELECT '2 没出声的原因', 'no-audio reason',
       n.item,
       CASE n.item WHEN 'empty_reply'         THEN '模型回的是空'
                   WHEN 'ready_without_audio' THEN '就绪但没有音频'
                   WHEN 'done_no_audio'       THEN '结束时没有音频'
                   WHEN 'done_no_stream'      THEN '结束时没有音频流'
                   ELSE n.item END,
       n.events, n.users,
       ROUND(100.0 * n.events / SUM(n.events) OVER (), 1)
FROM no_audio AS n
ORDER BY grp, events DESC;
