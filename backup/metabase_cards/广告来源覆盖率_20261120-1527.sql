-- 归因_广告来源覆盖率 · Attribution — Ad Source Coverage
-- 2026-11-13 新建。出处:需求文档 `01_看板/卡片需求_2026-11-12.md` §4.3(团队包看板 8)。
-- ═══ 这张卡回答什么 ═══
--   每天新注册的用户里,有多少能查到是从哪条广告来的(系列 / 广告组 / 素材三项分开)。
--   一行一天 × 一个业务线,近 30 天。
--
-- ═══ 🔴 文档的「现值 1~4%」是分母没拆业务线算出来的 ═══
--   实测 SoulMap 业务线稳定在 **74~82%**(11-12 为 214/270 = 79.3%)。
--   **CityPLX 用户在 `soulmap_app_launch` 里一行都没有**(逐日全是 0,它走自己的客户端)。
--   11-06 那天 CityPLX 注册 2,169 人 ⇒ 不拆业务线就是 97 / 2,299 = **4.2%**,正是文档那个数。
--   ⇒ **分母必须按 `app_line` 拆**,不拆的话这张卡量的是「当天有多少 CityPLX 注册」。
--   🛑 CityPLX 那一行的 0% 不是「归因失败」,是它根本不写这张表 —— 不要当缺口报。
--
-- ═══ 🔴 跨 2026-11-02 不可比:归因机制变了 ═══
--   `attr_backfilled_at`(事后回填)占「有系列标记」的比例:
--     10-31  31 / 636 = 5%  →  11-02  135 / 578 = 23%  →  11-12  207 / 214 = 97%
--   11-02 前后归因基本换了一套来源。**跨这天的覆盖率变化不能读成投放质量变化。**
--   本卡输出 `backfilled_share` 一列,就是给这件事留的证据。
--
-- ═══ 🔴 D-565「广告来源记到账号」已经做了,2026-11-10 11:57 起 ═══
--   服务端**另建了一张 `soul_map.soulmap_user_attribution`**(不是往 `user` 表加列,
--   `user` 上确实一个归因字段都没有),一个账号一行,带 `campaign` / `adgroup` / `creative`
--   **以及对应的 `campaign_id` / `adgroup_id` / `creative_id`** —— ID 列比名字稳,
--   投放改 Ad Set 名字也不会断(见口径文件:Ad Set 会改名)。
--   另有 `invite_link_id`(邀请归因,现在全空,和 564 §二「邀请卡开关一直关着」一致)。
--
--   ⇒ **本卡出两个口径,对着看**:
--     `account_coverage_rate` = 记到账号上的比例 —— **D-565 的正式验收口径**
--     `launch_coverage_rate`  = 通过设备(`soulmap_app_launch`)接到账号的比例 ——
--        有完整历史,用来立基线和看趋势。
--   实测 11-10~11-13:账号口径 **83~86%**,反而比设备口径(74~82%)略高。
--
--   🔴 **`account_coverage_rate` 只有 2026-11-08 以后的注册用户能读。**
--      表 11-10 11:57 建,往回只回填到 11-08。逐日实测:
--        11-08 **83.1%** · 11-09 76.9% · 11-10 83.5% · 11-11 82.8% · 11-12 83.0% · 11-13 85.5%
--        ← 以上可读;以下不可读 →
--        11-07 **38.2%**(回填了一半)· 11-06 4.6% · 11-05 3.2% · 11-01~11-04 1.3~2.5% · 10 月 0.3~1.6%
--      🛑 **11-07 及之前的低值不是「归因崩了」,是这些人根本没进这张表。**
--      那段要看覆盖率只能用 `launch_coverage_rate`。画图时把 11-08 之前的账号口径当缺失,别当 0。
--
-- ═══ 🛑 口径 ═══
--   ① 分母 = `user.create_time` 当天新注册的账号,按 `app_line` 拆(D-563)。
--   ② 分子 = 该账号在 `soulmap_app_launch` 里有记录、且对应列非空。
--      取的是**该用户所有启动记录里任意一个非空值**,不是 `MIN(add_on)` 那一行。
--      归因是回填上去的,首次启动那行可能还是空的 ⇒ 按非空取更稳。
--      (2026-11-13 实测近 21 天两种取法结果完全相同,这里按非空取是为了防回填时序变化。)
--   ③ `soulmap_app_launch.user_id` 是 varchar 且排序规则是 `utf8mb4_0900_ai_ci`
--      (全库只有这张表是 0900),join `user.id`(bigint)必须 CAST + COLLATE,否则报
--      `Illegal mix of collations`。
--   ④ 启动记录窗口比注册窗口往前放 7 天 —— 先启动后注册,放宽才不会漏掉注册前就装好的人。
--   ⑤ 三项(系列 / 广告组 / 素材)实测几乎完全一致,近 21 天只有两天差 1 个。
--      定稿要求三项分开读,所以仍分三列,不要合并。
--
-- ═══ 2026-11-13 实测基线(近 7 天,SoulMap 业务线)═══
--   11-12 79.3%(214/270) · 11-11 81.6%(204/250) · 11-10 81.3%(187/230)
--   11-09 76.0%(168/221) · 11-08 82.6%(161/195) · 11-07 72.0%(113/157) · 11-06 74.6%(97/130)
--   ⇒ 目标 ≥90% 距离约 10 个百分点,不是文档以为的 86 个百分点。

WITH new_user AS (
    SELECT
        u.id                                                                   AS user_id,
        DATE(u.create_time)                                                    AS register_date,
        CASE WHEN COALESCE(u.app_source, '') = 'city' THEN 'CityPLX'
             ELSE 'SoulMap' END                                                AS app_line
    FROM soul_map.user u
    WHERE u.create_time >= CURRENT_DATE - INTERVAL 30 DAY
      AND u.create_time <  CURRENT_DATE
),
launch_attribution AS (
    -- 一个账号一行。取任意非空值:归因是回填的,首次启动那行常常还是空的
    SELECT
        launch.user_id                                                         AS launch_user_id,
        MAX(NULLIF(launch.campaign, ''))                                       AS campaign,
        MAX(NULLIF(launch.adgroup,  ''))                                       AS ad_group,
        MAX(NULLIF(launch.creative, ''))                                       AS creative,
        MAX(launch.attr_backfilled_at)                                         AS attr_backfilled_at
    FROM soul_map.soulmap_app_launch launch
    WHERE launch.add_on >= CURRENT_DATE - INTERVAL 37 DAY
    GROUP BY launch.user_id
),
account_attribution AS (
    -- D-565:记到账号上的归因,一个账号一行(表本身就是一人一行,不用聚合)
    SELECT
        attribution.user_id                                                    AS account_user_id,
        NULLIF(attribution.campaign, '')                                       AS campaign,
        NULLIF(attribution.campaign_id, '')                                    AS campaign_id,
        NULLIF(attribution.creative_id, '')                                    AS creative_id
    FROM soul_map.soulmap_user_attribution attribution
)
SELECT
    new_user.register_date                                                     AS date,
    new_user.app_line                                                          AS app_line,
    COUNT(*)                                                                   AS new_users,
    SUM(launch_attribution.launch_user_id IS NOT NULL)                         AS users_with_launch_record,
    SUM(launch_attribution.campaign IS NOT NULL)                               AS users_with_campaign,
    SUM(launch_attribution.ad_group IS NOT NULL)                               AS users_with_adgroup,
    SUM(launch_attribution.creative IS NOT NULL)                               AS users_with_creative,
    ROUND(100.0 * SUM(launch_attribution.campaign IS NOT NULL) / COUNT(*), 1)  AS launch_coverage_rate,
    ROUND(100.0 * SUM(launch_attribution.attr_backfilled_at IS NOT NULL)
          / NULLIF(SUM(launch_attribution.campaign IS NOT NULL), 0), 1)        AS backfilled_share,
    -- D-565 正式验收口径(本表 2026-11-10 11:57 起才有数据,之前恒为 0)
    SUM(account_attribution.account_user_id IS NOT NULL)                       AS users_in_attribution_table,
    SUM(account_attribution.campaign IS NOT NULL)                              AS users_with_campaign_on_account,
    SUM(account_attribution.campaign_id IS NOT NULL)                           AS users_with_campaign_id,
    SUM(account_attribution.creative_id IS NOT NULL)                           AS users_with_creative_id,
    ROUND(100.0 * SUM(account_attribution.campaign IS NOT NULL) / COUNT(*), 1) AS account_coverage_rate
FROM new_user
LEFT JOIN launch_attribution
       ON launch_attribution.launch_user_id
        = CAST(new_user.user_id AS CHAR) COLLATE utf8mb4_0900_ai_ci
LEFT JOIN account_attribution
       ON account_attribution.account_user_id COLLATE utf8mb4_unicode_ci
        = CAST(new_user.user_id AS CHAR) COLLATE utf8mb4_unicode_ci
GROUP BY new_user.register_date, new_user.app_line
ORDER BY new_user.register_date DESC, new_user.app_line

