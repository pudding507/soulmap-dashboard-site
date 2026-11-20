-- 🔴 2026-11-02:内部测试号名单统一为 9 个 —— 原名单基础上加 74377 / 74592 / 71693 / 71826,
--    都是康在正式包里用安卓许可测试号买的(康 247 自报)。`environment='SANDBOX'`,
--    其中 71693 / 71826 各 1 次首购 + 6 次 5 分钟沙盒续费($12.99×7),不按 environment 过滤会凭空多出约 $182。
--    🛑 本次改动**不改变任何现有数字**(实测加不加这两个号,能量包都是 43 笔 / 25 人 / $41.76)——
--    它们没有能量流水,订阅金额本来就按 environment 排掉了。这是预防性统一,防以后漏。
-- 🔴 2026-10-31:名单补 `74640` —— Javier 的 10-20~10-30 完整 changelog §4
--    把它列为测试账号,§3(10-30 11:37)又写明「先在测试号 74640 上试」。
--    实测它在能量表里有数(txn 5 / lot 1 / trial_use 1),不剔会混进读数。
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-10-29:两条链各补一个 ⓪ 级 —— 用服务端 `cancel_reason` 给出分母     ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【改之前缺什么】卡里只有客户端漏斗的各级绝对量,**没有分母** ——
--   读的人看到「保留期弹窗曝光 28 人」,不知道这 28 是 28 分之几。
--
--   `soul_map.subscription_event_log.cancel_reason`(varchar(32))**只在
--   `event_type='CANCELLATION'` 上有值**,取值正好和本卡两条链一一对上:
--     `BILLING_ERROR`        扣款失败   → 链 A 的分母
--     `UNSUBSCRIBE`          主动退订   → 链 B 的分母
--     `CUSTOMER_SUPPORT` / `DEVELOPER_INITIATED`  客服 / 后台取消 → 两条链都不管,单列成 C
--
--   ═══ 🛑🛑 先读这一条:**不能用取消行上的 `period_type` 判断买家类型** ═══
--   0.99 首期结束后订阅转入**全价周期**,续费失败发生在那个周期
--   ⇒ **0.99 买家的 `BILLING_ERROR` 取消行,`period_type` 写的是 `NORMAL` 不是 `INTRO`**。
--   实测(0.99 买家全时段):`BILLING_ERROR` 42 人 **period_type 全是 NORMAL**;
--   `UNSUBSCRIBE` 31 次是 INTRO、2 次是 NORMAL。
--   ⇒ **判买家类型必须回到 `INITIAL_PURCHASE` 那一行认人。**
--
--   【2026-10-29 实测,近 30 天,已剔 CityPLX / 四个测试号 / 两个沙盒号】
--   **按买家类型拆(回 INITIAL_PURCHASE 认的,不是取消行的 period_type):**
--     | 原因                | 人  | 0.99 买家 | 免费试用起 | 全价直购 | 认不出 |
--     | BILLING_ERROR       | 266 | **42**    | **211**    | 0        | 13     |
--     | UNSUBSCRIBE         | 241 | 32        | 194        | 0        | 15     |
--     | CUSTOMER_SUPPORT    |   3 |  1        |   2        | 0        |  0     |
--     | DEVELOPER_INITIATED |   1 |  0        |   0        | 0        |  1     |
--   🛑 `全价直购` 一栏全是 0 —— **取消全部来自免费试用和 0.99 两种入口**,
--      直接按全价开订阅的人全库只有 4 个,一个都没取消。
--
--   🔴 **「退订」里扣款失败比主动退订还多**(266 vs 241)。
--      这正是口径陷阱 ② 那句「扣款失败不等于流失」的量化版本。
--
--   ✅ **本卡原来的预测被实测证实了**(2026-10-29 查卡 429 的口径核的):
--      卡头下面写着「**0.99 首批 10-22 到期**,按服务端历史数据大部分会走到扣款失败 ——
--      这条链马上会从边缘变成主战场」。
--      **0.99 买家里已到期的 85 人,终态是:**
--        扣款失败 `BILLING_ERROR` **42 人(49%)**
--        主动退订 `UNSUBSCRIBE`   **25 人(29%)**
--        没有任何取消事件         **18 人(21%)** —— 其中 **8 人续上了全价**
--      ⇒ **扣款失败确实是 0.99 到期后的第一大去向。**
--
--   ═══ 🔴🔴 ⓪ 级是**安卓口径**,不是全量(2026-10-30 补)═══
--   埋点文档 `07_埋点/README.md` 坑 #12:**Google RTDN 2026-10-06 19:10 SGT 才接通,
--   iOS 的 App Store 服务器通知至今未接通**(RevenueCat 后台显示 No notifications received)。
--   实测(全时段,按 `subscription.channel` 拆):
--     GOOGLE  `BILLING_ERROR` **274** · `UNSUBSCRIBE` 237
--     APPLE   `BILLING_ERROR` **1**   · `UNSUBSCRIBE` 5
--   ⇒ 🛑 **`BILLING_ERROR` 几乎是纯安卓的数** —— iOS 的扣款失败**根本没进这张表**,
--     不是 iOS 不失败。
--   ⇒ 🛑 **「扣款失败比主动退订还多」这个结论只在安卓成立**,不要当成全量结论对外讲。
--   ⇒ 🛑 **跨 2026-10-06 的退订率对比不成立**(RTDN 接通前安卓也是偏低的);
--     **iOS 侧暂不要出任何退订 / 扣款失败结论。**
--
--   ═══ 🛑 ⓪ 级怎么读(最重要的一条)═══
--   **⓪ 和 ① 是两个数据源**:⓪ 来自服务端账本(RevenueCat webhook),
--   ① 起各级来自客户端埋点。**两者不是嵌套关系,`① ÷ ⓪` 不是「弹窗覆盖率」。**
--   和本卡原有的「相邻两级不要直接相除」是同一条规矩。
--   ⓪ 的唯一作用:**给出量级参照**,让人知道 ① 的那个数大概是几分之几的量级。
--
--   🛑 服务端侧三个必须加的条件,少一个数就不对:
--     ① `environment='PRODUCTION'` —— 沙盒有 7 条 `BILLING_ERROR`;
--     ② `event_at` **是 UTC**(和 `occurred_at` 一样),下界用同一种 `CONVERT_TZ` 写法;
--     ③ 2026-11-12 起 CityPLX 不再剔,改成 `app_line` 一列并列(D-563);实测订阅事件和
--        `subscription_*` 埋点里 CityPLX 都是 0 行,这一列目前恒为 SoulMap。
--        只剔四个测试号 / 两个沙盒号 —— 同时**也补到了客户端侧 `evt`**,
--        不然两边口径不同没法并排放。实测客户端侧只有「取消弹窗」三级各少 1 人。
--
--   🛑 **和客户端那个 `reason` 不是一回事**:本卡下面记的
--     `payload ->> '$.reason'`(too_expensive 15 / other 5 / …)是**用户自己选的理由**,
--     只有 28 条;这里的 `cancel_reason` 是**服务端判定的取消类型**,510 人。
--     **两者互补,不要混用也不要相加。**
--
-- 退订与挽回链路 · Churn & Win-back
-- 【展示形式】**表格**。一行 = 链路里的一级。**近 30 天整段合计,不拆天。**
--   🛑 为什么不拆天:**分子全是个位数**(整段 30 天里 billing_recovered 才 3 人、
--     uncanceled 4 人、tap_resubscribe 6 人)。拆天之后每格都是 0~3,读不出任何东西,
--     而且看的人很容易拿当天的 1 去除当天的 3。**拆天要等 0.99 到期后量起来再说。**
--
-- 2026-10-22 新建。起因:**整条链都在跑,但看板上一张卡都没有**。
--   🔴 而且 **0.99 首批 10-22 到期**,按服务端的历史数据大部分会走到扣款失败 ——
--   **这条链马上会从边缘变成主战场。**
--
-- 输出形状:chain | step_no | step | events | users
--
-- ═══ 两条链 ═══
--   **链 A · 扣款失败挽回**:billing_hold_modal_shown → _tap_update → billing_recovered
--     (旁路:billing_banner_shown → _tap / _dismiss)
--   **链 B · 主动取消挽回**:canceled_modal_shown → cancel_reason_shown
--     → _submitted / _skipped → canceled_modal_tap_resubscribe / _later → uncanceled
--
-- ═══ 🛑 口径陷阱 ═══
--   ① **`occurred_at` 是 UTC**,同表其它列和别的表是 SGT。窗口下界要把 SGT 零点换成 UTC。
--   ② **「扣款失败」不等于「流失」** —— 宽限期已从 7 天改成 **0 天**,但**账户保留期有 60 天**,
--      期间仍可能恢复(`subscription_billing_recovered` 就是这个)。
--   ③ **和「0.99 到期逐人结果」(卡 429)是两件事**:那张看**到期后的终态**,
--      这张看**挽回动作有没有人响应**。**两张的分母不同,不要互相相除。**
--   ④ **买 3 天通行证不记 `subscription_billing_recovered`**,且保留「见过扣款失败」的标记
--      ⇒ 通行证用户不算挽回。(目前 `subscription_pass` 为 0 行,暂时不影响。)
--   ⑤ **链 A 的 banner 三步是旁路不是主链** —— `billing_banner_shown` 45 次只来自 9 个人
--      (人均 5 次,它每次进 App 都弹),**次数和人数差一个量级,只读 users 那一列。**
--
-- ═══ 🛑 取消原因的字段名(实测,与需求文档不符)═══
--   需求文档写的是 `cancel_reason`,**实测那个键恒为 NULL**。
--   真实字段是 **`payload ->> '$.reason'`**。照文档写会得到一张全空的分布表,**而且不报错**。
--   实测取值(全历史 28 条):
--     too_expensive 15 · other 5 · didnt_like_conversations 4
--     · technical_problems 2 · not_using_enough 2
--   ⇒ **太贵占 54%**,是第一位的取消原因。
--
-- ⚠️ 每一级都给**次数**和**去重人数**两列。
--   🛑 **这不是严格嵌套漏斗**,相邻两级不要直接相除当转化率 ——
--     比如 cancel_reason_shown 60 人 > canceled_modal_shown 58 人(两个入口不完全重合)。
--     **只读各级的绝对量,看哪一级掉得最狠。**
-- 🛑 **分子 < 10 的级别读不出**,卡上保留原始数字但不要排名、不要算比率。
--
-- ═══ 验收 ═══
--   两条链各级的量都能看到,`reason` 的取值分布能看到。
--   **0.99 首批到期后,链 A 的量应该明显上升** —— 那是这张卡真正要抓的时刻。

WITH step_def AS (
  SELECT 'A · 扣款失败挽回' AS chain, 1 AS step_no, '① 保留期弹窗曝光 Hold modal shown'  AS step, 'subscription_billing_hold_modal_shown'      AS event_name
  UNION ALL SELECT 'A · 扣款失败挽回', 2, '② 点了去更新 Tap update',              'subscription_billing_hold_modal_tap_update'
  UNION ALL SELECT 'A · 扣款失败挽回', 3, '③ 恢复扣款成功 Recovered',             'subscription_billing_recovered'
  UNION ALL SELECT 'A · 扣款失败挽回', 4, '(旁路)横幅曝光 Banner shown',         'subscription_billing_banner_shown'
  UNION ALL SELECT 'A · 扣款失败挽回', 5, '(旁路)横幅点击 Banner tap',           'subscription_billing_banner_tap'
  UNION ALL SELECT 'A · 扣款失败挽回', 6, '(旁路)横幅关掉 Banner dismiss',       'subscription_billing_banner_dismiss'
  UNION ALL SELECT 'B · 主动取消挽回', 1, '① 取消弹窗曝光 Cancel modal shown',    'subscription_canceled_modal_shown'
  UNION ALL SELECT 'B · 主动取消挽回', 2, '② 问原因 Reason shown',                'subscription_cancel_reason_shown'
  UNION ALL SELECT 'B · 主动取消挽回', 3, '③ 填了原因 Reason submitted',          'subscription_cancel_reason_submitted'
  UNION ALL SELECT 'B · 主动取消挽回', 4, '③ 跳过原因 Reason skipped',            'subscription_cancel_reason_skipped'
  UNION ALL SELECT 'B · 主动取消挽回', 5, '④ 点重新订阅 Tap resubscribe',         'subscription_canceled_modal_tap_resubscribe'
  UNION ALL SELECT 'B · 主动取消挽回', 6, '④ 选稍后再说 Later',                   'subscription_canceled_modal_later'
  UNION ALL SELECT 'B · 主动取消挽回', 7, '⑤ 撤销取消 Uncanceled',                'subscription_uncanceled'
),
evt AS (
  SELECT e.event_name                                            AS event_name,
         e.user_id                                               AS user_id,
         CASE WHEN u.app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line
  FROM soul_map.soulmap_interaction_event AS e
  -- 🔴 2026-10-29 新增剔除。建卡时没写,现在要和 ⓪ 级的服务端口径对齐才可比。
  --    🛑 走数值侧比,不要 CAST(u.id AS CHAR) —— 会报 Illegal mix of collations。
  --    实测影响极小:只有「取消弹窗」那三级各少 1 人,其余各级一个都不变。
  LEFT JOIN soul_map.`user` AS u ON u.id = CAST(e.user_id AS UNSIGNED)
  WHERE e.event_name LIKE 'subscription\_%'
    -- 🛑 occurred_at 是 UTC,下界先把 SGT 零点换成 UTC(见口径陷阱 ①)
    AND e.occurred_at >= CONVERT_TZ(CURDATE() - INTERVAL 30 DAY, '+08:00', '+00:00')
    AND (u.id IS NULL OR u.id NOT IN (62412, 72048, 72382, 72462, 74640, 74377, 74592, 71693, 71826))
),
server_cancel AS (            -- 🔴 2026-10-29 新增:服务端账本里真实发生的取消,见卡头「⓪ 级」
  SELECT l.cancel_reason                                         AS cancel_reason,
         CASE WHEN u.app_source = 'city' THEN 'CityPLX' ELSE 'SoulMap' END AS app_line,
         COUNT(*)                                                AS events,
         COUNT(DISTINCT l.user_id)                               AS users
  FROM soul_map.subscription_event_log AS l
  LEFT JOIN soul_map.`user` AS u ON u.id = l.user_id
  WHERE l.event_type  = 'CANCELLATION'
    -- 🛑 必须加 PRODUCTION:沙盒有 7 条 BILLING_ERROR,不排会虚高。
    AND l.environment = 'PRODUCTION'
    -- 🛑 event_at 也是 UTC(同 occurred_at),下界用同一种写法,两边窗口才对齐。
    AND l.event_at   >= CONVERT_TZ(CURDATE() - INTERVAL 30 DAY, '+08:00', '+00:00')
    AND (u.id IS NULL OR u.id NOT IN (62412, 72048, 72382, 72462, 74640, 74377, 74592, 71693, 71826))
  GROUP BY l.cancel_reason, app_line
)
SELECT chain, app_line, step_no, step, events, users FROM (
  SELECT d.chain                                                 AS chain,
         -- 没有任何事件的那一级也要留一行,所以 NULL 归到 SoulMap(见卡头 D-563 一段)
         COALESCE(e.app_line, 'SoulMap')                         AS app_line,
         d.step_no                                               AS step_no,
         d.step                                                  AS step,
         COUNT(e.user_id)                                        AS events,
         COUNT(DISTINCT e.user_id)                               AS users
  FROM step_def AS d
  LEFT JOIN evt AS e ON e.event_name = d.event_name
  GROUP BY d.chain, app_line, d.step_no, d.step

  -- 🔴 2026-10-29 新增 ⓪ 级:服务端账本里真实发生的取消 = 这条链的**分母**。
  --    🛑 ⓪ 和 ① 是**两个数据源**(服务端账本 vs 客户端埋点),**不是嵌套漏斗**,
  --       **不要拿 ①÷⓪ 当「弹窗覆盖率」** —— 同卡里「相邻两级不要相除」那条规矩一样适用。
  --       ⓪ 的作用只有一个:给出量级参照,让人知道 ① 的那个数是几分之几量级。
  UNION ALL
  SELECT 'A · 扣款失败挽回', sc.app_line, 0, '⓪ 服务端记到的扣款失败 Billing cancels (server)',
         sc.events, sc.users
  FROM server_cancel AS sc WHERE sc.cancel_reason = 'BILLING_ERROR'
  UNION ALL
  SELECT 'B · 主动取消挽回', sc.app_line, 0, '⓪ 服务端记到的主动退订 User cancels (server)',
         sc.events, sc.users
  FROM server_cancel AS sc WHERE sc.cancel_reason = 'UNSUBSCRIBE'
  -- 🛑 第三行是为了让两条链的 ⓪ 加起来能对上**全部**取消数 —— 不列的话,
  --    读的人会以为 BILLING_ERROR + UNSUBSCRIBE 就是取消总量。
  UNION ALL
  SELECT 'C · 两条链都不管', sc.app_line, 0, '⓪ 其它原因(客服 / 后台)Other (server)',
         SUM(sc.events), SUM(sc.users)
  FROM server_cancel AS sc
  WHERE sc.cancel_reason NOT IN ('BILLING_ERROR', 'UNSUBSCRIBE')
     OR sc.cancel_reason IS NULL
  GROUP BY sc.app_line
) AS all_steps
ORDER BY chain, app_line, step_no, step;

