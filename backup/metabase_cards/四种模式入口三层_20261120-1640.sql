-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-11-20:版本白名单作废,改成「版本数值下界 + 入口代次」              ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【改之前是什么情况】白名单停在 `'3.8.1'` / `'3.9.0'`(10-29 加的那次),
--   之后 **3.9.1 ~ 3.9.7 七个版本全部掉在白名单外面**。
--   实测近 7 天发 `sp_step` 的 **2,048 台设备**里,只有 **14 台(0.7%)** 在白名单内
--   (3.8.1 十三台 + 3.9.0 一台)。
--   ⇒ `layer_3/4/5` 从 11-07 起全 0 **不是没人用,是这张卡看不见他们**。
--   🛑 和「各能力数据可读性」那个 bug 是同一种病:**清单写死、时间往前走、不报错。**
--
--   【为什么不是再加七行白名单】加完下一次发版还会再漏一次。
--   手工清单在这张卡上已经栽了两回(10-29 漏 3.9.0 · 11-20 漏 3.9.1~3.9.7)。
--   ⇒ 改成**版本数值下界**,3.8.1 以上全进,发版不用再动这张卡。
--     🛑 仍然不能写 `version >= '3.8.1'` —— MySQL 按字符串比,`'3.8.10' < '3.8.9'`。
--       拆三段算成整数:3.8.1 → 30801,3.9.10 → 30910 > 3.9.9 的 30909,顺序才对。
--
--   【版本维度怎么保留】放开之后版本有十来个,一天一版会变成 280 行上下,读不了。
--   ⇒ 按**入口代次**归并 —— 这正是 10-29 当初要分版本的理由(别把两套入口平均掉):
--       `3.8.x「＋」` = 聊天框里的加号 · `3.9+ 胶囊` = 胶囊入口。
--     3.9.1~3.9.7 之间入口设计没变,并成一组不丢信息。
--   🛑 **跨这两组不要相加** —— 同一台设备换版本后会在两组各算一次。
--
--   【影响】分母从 14 台回到 2,048 台;`plus_tap_rate_trailing_7d_pct` 此前是
--   在十几台的分母上算的,**11-20 之前的比率值不要和之后比**。
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-10-30 11:57:「研究」模式从入口移除 —— 现在只剩三种模式            ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   出处:服务端 changelog(liwen 508,W44)——
--   `power.capabilities.enabled` 去掉 `research`,**已配生产**。
--
--   ⇒ 🛑 **本卡名字里的「四种模式」从这一刻起不再准确**,但**卡名和列名不改** ——
--     改了就和 10-30 之前的历史数对不上,也和台账 / 待办里的引用对不上。
--     以 10-30 11:57 为切点:之前菜单里 4 个选项,之后 3 个。
--   ⇒ 🛑 **`power_menu_pick` 和 `power_menu_dismiss` 跨这一刻不可直接比** ——
--     菜单少了一个选项,选中率和关掉率都会动,**那是选项数变了不是用户变了**。
--   🛑 本卡**不按 capability 拆**,所以「研究」那部分量会直接从总数里消失,
--     看上去像掉量。要看是不是只掉了 research,得去 `sp_step` 按 `capability` 拆。
--
-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║ 🔴 2026-10-29:白名单加 3.9.0,并新增版本维度                              ║
-- ╚══════════════════════════════════════════════════════════════════════════╝
--   【改之前是什么情况】白名单里只有 `'3.8.1'`,而 **3.9.0 已于 2026-10-28 发版**
--   (安卓 versionCode 215 / iOS build 202610281230)。实测 10-28 埋点侧
--   3.9.0 有 **8 台设备 / 119 条 `sp_step`**,**一条都没被这张卡数到**。
--   本卡头部原来就写着「漏加新版的表现是分母骤降、点开率虚高」—— 正好撞上。
--
--   【为什么不是只加一行白名单】3.9.0 把入口换成了**胶囊**,和 3.8.1 的「+」
--   不是同一个交互。并成同一行 = 把两套入口的点开率平均掉。
--   ⇒ 新增 `app_version` 列,一行 = 一天 × 版本;七天滚动窗同步 `PARTITION BY app_version`
--     (不加这个,窗会横跨两个版本,把 3.9.0 的分子算进 3.8.1 的窗)。
--
--   🛑 **3.9.0 现在只有 8 台**,日度和滚动比率都读不出来,
--      本卡的 `>= 10 台` 门槛会让它的比率列为空 —— **那是对的,不是漏数。**
--   🛑 下界 `event_date >= '20261023'` 不动:那是 3.8.1 发版日,也是这些事件最早出现的日子。
--
-- 四种模式「＋」入口 · 一天一行
-- 输出形状:一个 event_date 一行,回答「昨天有多少人看到「＋」、多少人点了、多少人真的跑起来」
-- 源:host.firebase_event(埋点,T+1)。事件全部落在 event_name='sp_step',用 params.step 区分。
--
-- ⚠️ 2026-10-27 新建。配合给客户端的
--    `02_跨团队沟通/客户端/184_回Kang-214-四种模式入口三层已拉-看到了不点是主要漏损-20261027.md`。
--    建卡前这套数只存在于临时脚本里,看板上没有任何一张卡覆盖四种模式。
--
-- ══════════════════════════════════════════════════════════════════════════
-- 🛑 一、为什么必须剔掉四台设备
-- ══════════════════════════════════════════════════════════════════════════
-- 下面硬编码的 4 个 user_pseudo_id 是我们自己的测试机,证据:
--    1af333746b5d3be244e6e5bcfb76e7e6  新加坡 · Google · Android · 10-23 首现 ·   312 条事件/4 天
--    D54E0529FA3E4D259559671F91355BB2  新加坡 · Apple  · iOS     · 10-22 首现 · 1,075 条事件/4 天
--    6a468fc9b33122fe82fa19d551c60f1b  中国   · Xiaomi · Android · 10-23 首现 ·   303 条事件/4 天
--    6af5d04f2428ab06546728cba0fa49ec  中国   · Xiaomi · Android · 10-23 首现 · 1,157 条事件/4 天
-- 全部在发版前后首次出现,国家是新加坡和中国,四天内事件密度是普通设备的几十倍。
--
-- **不剔会把结论读反**:10-23~10-26 实测,菜单里选了模式的 6 台设备中有 4 台是这些测试机;
-- 唯一两台 `power_start_result='ok'`(真的把活动跑起来)的也全是测试机 ——
-- 剔掉之后真实用户的 ok 是 **0**,走到最后的 2 台全部撞付费墙。
--
-- ══════════════════════════════════════════════════════════════════════════
-- 🛑 二、为什么只有一列给百分比
-- ══════════════════════════════════════════════════════════════════════════
-- 实测四天合计(已剔测试机):① 100 台 → ② 5 台 → ③ 2 台 → ④ 2 台 → ⑤ 0 台。
--
-- 日度的分子有多小:10-25 点了「＋」的是 2 台,10-26 是 3 台。
-- 按天算比率会得到 5.0% → 8.1%,看起来涨了六成,**实际是 2 台变 3 台,纯噪声**。
-- ⇒ 本卡的日度列**只给台数,一个比率都不给**。
--    唯一的比率是 `plus_tap_rate_trailing_7d_pct` —— 七天滚动的 ② ÷ ①,
--    而且**滚动分子不足 10 台时输出 NULL**,让「读不出来」显式可见,而不是给一个假精度的百分比。
--    别在看板上给 ③④⑤ 加任何比率,那几层的量级永远是个位数。
--
-- 注:滚动列只是用来读趋势的,日度台数列保持一天一行不做平滑 ——
--     断点要能自己跳出来,不能被窗口抹平。
--
-- ══════════════════════════════════════════════════════════════════════════
-- 🛑 三、分母那一列是天花板,不是漏损
-- ══════════════════════════════════════════════════════════════════════════
-- `a_class_chat_opener_devices` = 当天打开过 A 类角色聊天页的设备数。
-- 「＋」只长在 A 类角色上,所以这是曝光面的物理上限。
-- 实测 609 台进过聊天的设备里只有 105 台开过 A 类(17.2%),而这 105 台里 104 台看到了「＋」——
-- **曝光机制没有漏,天花板来自 A 类角色本身进入量就小。** 这一列掉下去是产品问题,不是埋点问题。
--
-- ══════════════════════════════════════════════════════════════════════════
-- 🛑 四、版本下界怎么算(2026-11-20 起不再手工维护白名单)
-- ══════════════════════════════════════════════════════════════════════════
-- 分母必须限定在「带四种模式埋点的版本」上,否则会把看不到入口的老版本设备算进分母。
-- 但 MySQL 里 '3.8.10' < '3.8.9'(按字符串比),`version >= '3.8.1'` 会把 3.8.10 排掉。
-- ⇒ 拆三段算成整数再比:`major*10000 + minor*100 + patch`。
--    3.8.1 → 30801 · 3.9.0 → 30900 · 3.9.10 → 30910,顺序正确。
-- 🛑 这个表达式在 WHERE 和 CASE 里各出现一次,**改一处必须改另一处**,
--    否则会出现「进了分母却归不进任何一代」的行。
-- 🛑 只认 `x.y.z` 三段数字的版本号(实测 10-23 起全部是这个形状);
--    将来出现 `3.9.6-beta` 这类会被 REGEXP 挡掉,**宁可少算也不要算错代次**。

WITH internal_test_device AS (
    SELECT '1af333746b5d3be244e6e5bcfb76e7e6' AS user_pseudo_id
    UNION ALL SELECT 'D54E0529FA3E4D259559671F91355BB2'
    UNION ALL SELECT '6a468fc9b33122fe82fa19d551c60f1b'
    UNION ALL SELECT '6af5d04f2428ab06546728cba0fa49ec'
),
daily_entry_funnel AS (
    -- firebase_event 很贵,这里只扫一遍,全部用条件聚合拆层,不要为每一层各写一个 CTE。
    SELECT
        STR_TO_DATE(firebase_event.event_date, '%Y%m%d') AS date,
        -- 🔴 2026-10-29 新增版本维度,2026-11-20 改为「入口代次」。
        --    3.9.0 换了入口设计(胶囊),和 3.8.x 的「＋」不是同一个东西,
        --    并成一行会把两套入口平均掉 —— 正是本卡最该避免的读法。
        --    但 3.9.1~3.9.7 之间入口没再变,按小版本拆只会把行数撑到读不了。
        CASE WHEN CAST(SUBSTRING_INDEX(firebase_event.version, '.', 1) AS UNSIGNED) * 10000
                + CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(firebase_event.version, '.', 2), '.', -1) AS UNSIGNED) * 100
                + CAST(SUBSTRING_INDEX(firebase_event.version, '.', -1) AS UNSIGNED) >= 30900
             THEN '3.9+ 胶囊'
             ELSE '3.8.x 「＋」'
        END                                              AS app_version,

        COUNT(DISTINCT CASE WHEN firebase_event.event_name = 'chat_entry_shown'
                             AND firebase_event.params ->> '$.char_type' = 'A'
                            THEN firebase_event.user_pseudo_id END)
            AS a_class_chat_opener_devices,

        COUNT(DISTINCT CASE WHEN firebase_event.params ->> '$.step' = 'power_plus_shown'
                            THEN firebase_event.user_pseudo_id END)
            AS layer_1_plus_shown_devices,

        COUNT(DISTINCT CASE WHEN firebase_event.params ->> '$.step'       = 'capability_entry_tap'
                             AND firebase_event.params ->> '$.capability' = 'power_modes'
                             AND firebase_event.params ->> '$.src'        = 'chat_plus'
                            THEN firebase_event.user_pseudo_id END)
            AS layer_2_plus_tapped_devices,

        COUNT(DISTINCT CASE WHEN firebase_event.params ->> '$.step' = 'power_menu_pick'
                            THEN firebase_event.user_pseudo_id END)
            AS layer_3_menu_picked_devices,

        COUNT(DISTINCT CASE WHEN firebase_event.params ->> '$.step' = 'power_menu_dismiss'
                            THEN firebase_event.user_pseudo_id END)
            AS layer_3_menu_dismissed_devices,

        COUNT(DISTINCT CASE WHEN firebase_event.params ->> '$.step' = 'power_start_tap'
                            THEN firebase_event.user_pseudo_id END)
            AS layer_4_start_tapped_devices,

        COUNT(DISTINCT CASE WHEN firebase_event.params ->> '$.step'   = 'power_start_result'
                             AND firebase_event.params ->> '$.result' = 'ok'
                            THEN firebase_event.user_pseudo_id END)
            AS layer_5_started_ok_devices,

        COUNT(DISTINCT CASE WHEN firebase_event.params ->> '$.step'   = 'power_start_result'
                             AND firebase_event.params ->> '$.result' = 'purchase_required'
                            THEN firebase_event.user_pseudo_id END)
            AS layer_5_blocked_by_paywall_devices

    FROM host.firebase_event
    LEFT JOIN internal_test_device
      ON internal_test_device.user_pseudo_id = firebase_event.user_pseudo_id
    WHERE firebase_event.event_date >= '20261023'          -- 3.8.1 发版日,此前没有这些事件
      AND firebase_event.event_name IN ('sp_step', 'chat_entry_shown')
      AND internal_test_device.user_pseudo_id IS NULL      -- 剔内部测试机,见头部注释 一
      -- 版本下界(见头部注释 四)。2026-11-20 起取代原来的 supported_app_version 白名单。
      AND firebase_event.version REGEXP '^[0-9]+\\.[0-9]+\\.[0-9]+$'
      AND CAST(SUBSTRING_INDEX(firebase_event.version, '.', 1) AS UNSIGNED) * 10000
        + CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(firebase_event.version, '.', 2), '.', -1) AS UNSIGNED) * 100
        + CAST(SUBSTRING_INDEX(firebase_event.version, '.', -1) AS UNSIGNED) >= 30801
    GROUP BY 1, 2
)
,
trailing_seven_day AS (
    -- 七天滚动。注意:这里滚动的是**每天的去重设备数之和**,不是跨天再去重的设备数,
    -- 所以同一台设备连续几天都看到「＋」会被计多次。比率的分子分母用的是同一套口径,
    -- 作为趋势读没问题,但别把 `plus_shown_device_days_trailing_7d` 当成「这七天有多少台设备」。
    SELECT
        daily_entry_funnel.*,
        -- 🛑 加了版本维度之后,滚动窗必须 PARTITION BY app_version,
        --    否则 7 天窗会横跨两个版本的行,把 3.9.0 的分子算进 3.8.1 的窗里。
        SUM(layer_1_plus_shown_devices)  OVER (PARTITION BY app_version ORDER BY date
                                               ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
            AS plus_shown_device_days_trailing_7d,
        SUM(layer_2_plus_tapped_devices) OVER (PARTITION BY app_version ORDER BY date
                                               ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
            AS plus_tapped_device_days_trailing_7d
    FROM daily_entry_funnel
)
SELECT
    date,
    app_version,
    a_class_chat_opener_devices,
    layer_1_plus_shown_devices,
    layer_2_plus_tapped_devices,
    layer_3_menu_picked_devices,
    layer_3_menu_dismissed_devices,
    layer_4_start_tapped_devices,
    layer_5_started_ok_devices,
    layer_5_blocked_by_paywall_devices,
    plus_shown_device_days_trailing_7d,
    plus_tapped_device_days_trailing_7d,
    -- 唯一一列比率。分子(七天累计点击台日)不足 10 时输出 NULL —— 读不出来就别给数。
    CASE WHEN plus_tapped_device_days_trailing_7d >= 10
         THEN ROUND(100.0 * plus_tapped_device_days_trailing_7d
                          / NULLIF(plus_shown_device_days_trailing_7d, 0), 1)
    END AS plus_tap_rate_trailing_7d_pct
FROM trailing_seven_day
ORDER BY date DESC, app_version DESC
