-- 邀请 · 兑换尝试按来源与结果 · Invite — Redeem Attempts by Source & Reason
-- 【展示形式】表格。一行一个 来源 × 结果,按次数倒序。
--
-- 2026-10-14 新建。起因:服务端今天(`liwen` 383 §三)开始把**每一次兑换尝试**
--   (成功和失败都落)写进 `soulmap_interaction_event`。在此之前,
--   「链接带不回码」和「带回了码但绑不上」在数据里分不开。
--
-- 输出形状:via | via_cn | reason | reason_cn | ok | attempts | users
--
-- ═══ 这张卡要回答的那个问题 ═══
--   **自动绑定上线后,绑定数如果掉了,是链接坏了还是没人邀请?**
--     · 「链接带不回码」⇒ **`redeem` 根本不会被调用**,这张卡上**连失败行都没有**;
--     · 「带回了码但绑不上」⇒ 出现 `via='referrer_auto'` 的失败行。
--   ⇒ **两者分得开。** 这是 120 §4.1 提的那个诉求的落地。
--
-- ═══ 🛑 日期一律用 `created_at`,不要用 `occurred_at` ═══
--   `occurred_at` 是**客户端上报的时刻**,有时钟偏差。
--   实测 10-01 起 363,884 行里有 **44 行的 `occurred_at` 在未来**(最远到 10-17)。
--   按它过滤窗口会把这些行漏掉或错算。`created_at` 是落库时刻,单调。
--
-- ═══ 取值词表(服务端 388 §3.1 核过)═══
--   `via`     = `referrer_auto`(深链接自动) · `manual`(用户手输) · `unknown`(老客户端不传)
--   `reason`  = bound · already_bound · bound_already_paid · bad_code · unknown_code
--               self_invite · already_invited_by_other · same_device · write_failed · no_user
--   ⚠️ **`rate_limited` 在 `redeem` 上永远不会出现** —— 它只在 `preview` 接口上有。
--      `redeem` **没有限流**,所以自动绑定不会被限流挡住。
--
-- ⚠️ **`same_device` 不是故障** —— 它是反自邀判据(同一台机器先登 A 再登 B)。
--    用一台手机做自动绑定验证时一定会撞上它,**那不是链路坏了**。
-- ⚠️ 这个事件 **2026-10-14 14:46 才开始有行**,在那之前的兑换**不在这张卡里**。
--    ⇒ 上线前后对比**只能从 10-14 14:46 之后算起**。
-- ⚠️ 分子小于 10 的行读不出。
--
-- ═══ 🔴 2026-10-14 17:15 实跑:3 行,**全部是 `via='unknown'`** ═══
--   今天这 3 次兑换全部 `via` 为空(老客户端不传)、`reason='bound'`。
--   ⇒ **带 `via` 的客户端版本还没放量**,在它放量之前,
--      这张卡**分不出「深链接自动」和「用户手输」** —— 全落在「老客户端不传」一行。
--   ⇒ **这张卡现在先挂上去占位**,等新客户端放量后才真正可读。
--   ⚠️ 在那之前,「走链接 vs 手输」只能从客户端埋点 `invite_step · redeem` 的
--      `params.via` 读(实测 10-08 起:`manual` 9 人 / `referrer` 5 人),
--      但那一侧**缺 2026-10-11 一整天**。

SELECT  COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.via')), '(未传)')      AS via,
        CASE JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.via'))
             WHEN 'referrer_auto' THEN '深链接自动'
             WHEN 'manual'        THEN '用户手输'
             WHEN 'unknown'       THEN '老客户端不传'
             ELSE '(未传)' END                                                 AS via_cn,
        COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.reason')), '(空)')    AS reason,
        CASE JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.reason'))
             WHEN 'bound'                    THEN '绑定成功'
             WHEN 'already_bound'            THEN '已经绑过'
             WHEN 'bound_already_paid'       THEN '绑了但已是付费用户'
             WHEN 'bad_code'                 THEN '码格式不对'
             WHEN 'unknown_code'             THEN '查无此码'
             WHEN 'self_invite'              THEN '自己邀请自己'
             WHEN 'already_invited_by_other' THEN '已被别人邀请过'
             WHEN 'same_device'              THEN '同一台设备(反自邀)'
             WHEN 'write_failed'             THEN '写库失败(可重试)'
             WHEN 'no_user'                  THEN '用户不存在(可重试)'
             ELSE '(其它)' END                                                 AS reason_cn,
        JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.ok'))                          AS ok,
        COUNT(*)                                                               AS attempts,
        COUNT(DISTINCT e.user_id)                                              AS users
FROM        soul_map.soulmap_interaction_event e
WHERE       e.event_name = 'referral_redeem'
  AND       e.created_at >= '2026-10-14'          -- 事件本身 10-14 14:46 才上线
GROUP BY    via, via_cn, reason, reason_cn, ok
ORDER BY    attempts DESC, via, reason
