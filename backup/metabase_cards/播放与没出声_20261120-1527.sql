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
  WHERE event_name = 'voice_playback_result' AND event_date >= '20261008'
  GROUP BY item
),
no_audio AS (
  SELECT JSON_UNQUOTE(JSON_EXTRACT(params, '$.reason')) AS item,
         COUNT(*) AS events, COUNT(DISTINCT uid) AS users
  FROM host.firebase_event
  WHERE event_name = 'voice_reply_no_audio' AND event_date >= '20261008'
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

