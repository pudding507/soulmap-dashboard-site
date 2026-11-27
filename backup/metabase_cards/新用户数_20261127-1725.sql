-- New Users（新用户）· 近30天
-- ⚠️ 2026-09-08 提速:补 `event_name IN (...)` 过滤,一行。
--    原因:DBA 于 09-08 加了 `idx_event_name_date (event_name, event_date)`,但原写法 WHERE 里
--    没有 event_name 谓词,EXPLAIN 是 `type=ALL / key=None / rows=6,160,464`(全表扫)。
--    ✅ **口径中性**:country 是 MIN(CASE WHEN first_open THEN country END),条件聚合;first_open 的 country 填充率 100%。
--    实测这几个事件的 country 填充率均为 100%(first_open / attribution_received /
--    session_start / app_open 都是),所以加过滤不损失 country 覆盖。

-- 口径：新用户(first_open) 近30天滚动；按 source(平台) × placement(版位原值) × adgroup(type) × country
--   ⚠️ 单次扫描 host.firebase_event(条件聚合),不拆多 CTE 各扫一遍 —— 减少全表扫描(仿 Activation_funnel 的 fe)
--   adgroup=广告类型(career/burnout…),原值含广告组ID后缀,SUBSTRING_INDEX 去掉；NULL 兜底 others
-- ⚠️ 2026-08-10 归因维度改造(起因:8/07 上线 relationship 主题广告,占之后新装约75%):
--    source  归平台 —— Meta 三个版位(Facebook/Off-Facebook/Instagram)合并为 Facebook,
--            并兜住 deeplink 可能传来的 fb/meta;%Organic% 排在 %Google% 之前,
--            否则 Google Organic Search(自然搜索)会被算成 Google 投放。
--    adgroup 归主题 —— 原按广告组全名分组,因投放侧命名不统一且有拼写错误(SouMap_/intsall/beign),
--            career 被劈成 4 桶、burnout 3 桶,新主题 relationship 只有 1 桶,三者无法对比。
--            改为关键词匹配(不用取末段,抗 SoulMap_MV1_relationship 这类主题在中间的命名)。
--    两段映射均用 ELSE 透传原值,不用 ELSE 'others' —— 新平台/新主题会以原名显形,不会静默消失。
--    影响:Facebook 线不变(8,311);career 5,221、burnout 5,107 各由多桶合并而来,会看起来「翻倍」,
--         属口径变化;others(无归因埋点的用户)前后一人不差。详见
--         soulmap_dashboard_docs/看板归因维度改造_source归平台_adgroup归主题.md
-- ⚠️ 2026-08-13 新用户改为按设备去重(起因:与「新版 Onboarding Anchor 分布」对不上数):
--    原写法 WHERE uid<>'' + GROUP BY uid 按**账号**去重。但 first_open 在 App 启动那一刻触发,
--    此时用户尚未注册、还没有 uid —— 这批行被 uid<>'' 直接过滤掉了。
--    实测 8/11:first_open 共 858 台设备,其中带 uid 的只有 705,漏掉 153(18%);
--    因此出现「first_open(706) 比当天注册数(851) 还少」这种不可能的现象。
--    改为按 user_pseudo_id(设备)去重,符合「新用户数=下载量」的口径。
--    影响:新用户数上升,近7天 +12%~+51%(量小的日子漏得更狠,所以修正的不只是绝对值,还有趋势);
--         归因维度覆盖率由约 90% 降到 78% —— 多出来的是「没注册就走了」的设备,
--         其 attribution_received 也常缺失,会落入 others,others 桶约由 10% 涨到 22%。
--    ⚠️ 留存/激活等**率类**卡片仍按账号(uid),因为轮数与回访挂在账号上;
--       故「新用户数」与「留存的分母」不再是同一个数,勿跨卡对数。
--    未决:埋点 first_open 去重设备(858) vs 服务端 soulmap_app_launch 新 device_id(2,122)差 2.5 倍,
--         谁更接近真实下载量需用 App Store Connect / Play Console 的下载量校准。
-- ⚠️ 2026-08-17 adgroup 改为取末段,不再枚举关键词:
--    原写法逐个列举 burnout/career/relationship/children/stress/depression,每上一个新主题
--    都要手动补一条,漏补就显示成一长串广告组全名。实测全部 17 个 adgroup 都是「..._主题」结尾,
--    取末段与关键词法 16 个完全一致;第 17 个(TT_soulmap_android_adnd,2 人)末段法反而取对了。
--    改后新主题自动生效,无需维护映射表。
--    ⚠️ 依赖「主题在最后一段」的命名习惯 —— 若出现 SoulMap_relationship_MV1 这类主题在中间的
--       命名会取错(该模式目前只见于 creative 字段,adgroup 未出现过)。
-- ⚠️ 2026-09-09 新增一列 `placement`,**`source` 保持不变**:
--    改了什么:多输出一列 placement = `pf` 原值(NULL → others),不做任何归并。
--    为什么:2026-08-10 起 source 把 Meta 三个版位合并成 'Facebook',平台级汇报够用,
--          但**三个版位买到的是结构不同的人**,合并会把差异抹掉。近14天新设备实测:
--            Facebook Installs      1,946 (27.6%)  英语一线 9.0%   南亚 39.7%
--            Off-Facebook Installs  2,046 (29.0%)  英语一线 3.5%   南亚 51.5%
--            Instagram Installs     1,274 (18.1%)  英语一线 6.6%   南亚 48.7%
--          Facebook Installs 的英语一线占比是 Off-Facebook 的 **2.6 倍**,南亚反过来。
--    为什么不直接改 source:那会让 2026-08-10 之后所有按 source 的历史对比断掉
--          (一条 Facebook 线裂成三条),而且同样的合并还在另外 8 张卡里。
--          新增列则两种读法都在:汇报看 source(平台),投放看 placement(版位)。
--    影响:多一列、多一个 GROUP BY 维度,行数变多但数值不变;渲染器新增「by placement」切页。
--    ⚠️ 另外 8 张卡(Growth_DAU / Growth_Deep New Users / Retention_d1·d3·d7·d1 effective /
--       Activation_funnel by adgroup / Chat_engaged user focus)仍是合并口径,**尚未加此列**。
-- ⚠️ 2026-09-07 country 改为只取 first_open 那条事件,不再对窗口内全部事件取 MIN:
--    改了什么:MIN(country) → MIN(CASE WHEN event_name='first_open' THEN country END)
--    为什么:MIN() 对字符串取的是**字母序最小值**,不是「第一个」也不是「最常见的」。
--          firebase 的 country 是逐事件按 IP 定位的,同一设备换网络/VPN/出差都会出现多个取值,
--          于是一条漂移的事件就能翻掉整台设备的国家归属。实测极端例子:
--            某设备 347 条事件里 346 条在 Ghana、1 条在 Canada  → MIN() 判给 Canada
--            某设备 497 条事件里 494 条在 United States、3 条在 Nigeria → 判给 Nigeria
--          且偏差是**单向**的:字母序靠前的国家只会多算,靠后的只会少算。
--          受影响的还恰好是重度用户(这批设备总事件数 300~2,000 条),用得多才更容易碰到第二个国家。
--          新写法取装 App 那一刻的国家,与「新用户来自哪」的语义一致,且 first_open 每设备仅一条,
--          天然没有多值问题。同为条件聚合,不增加扫描次数。
--    影响:近30天 19,786 台新设备中 **153 台(0.77%)** 国家归属发生变化;
--         **新口径 country 为空 0 台**,others 桶不会因此变大(改前也是 0)。
--         净变化最大的:United States 262→289(+27,+10.3%)、Germany 147→124(-23,-15.6%)、
--         France 70→58(-12)、Pakistan 2944→2954(+10)、Canada 93→85(-8)。
--         方向符合预期 —— US / Russia / Syria / Türkiye / Ukraine 回流,
--         Canada / France / Germany / Iran 吐出原本不属于它们的设备。
--         ⚠️ US 基数小(262),+10.3% 是相对大的变动,评估美国市场时前后不可直接对比。
-- ⚠️ 2026-09-29 新增一列 `creative`(素材名),**本卡由此从单表变成跨源**:
--    改了什么:join 服务端 `soul_map.soulmap_app_launch`,取该设备最早一条启动行的 creative。
--    为什么不能用埋点:`attribution_received` 的参数只有 `pf` / `pm` / `type` 三个,
--      **没有素材字段**。曾考虑用 `pm`,但实测 99.6% 的设备上 `pm` 装的是 **campaign 名**
--      (如 `SoulMap_TypeB_W2A_FemaleChar_MaleAudience_Test_20260923 (120248568903110025)`),
--      只有 35 台设备(0.4%,手工配的链接)里 `pm` 才是素材名。
--      实证:TypeB 测试下三条素材 `SoulMap_CH10_Yui` / `CH18_Cathy` / `CH06_Olivia`,
--      三者的 `pm` 完全相同 —— 按 `pm` 取会把三条素材并成一条。
--    也没有从 `type` 里解析:这次的广告组名恰好带角色名(`R10_Yui`),但上一个 campaign 的
--      `F18-44_US-UK-CA-AU_Broad_relationship-friction` 就不带。依赖命名习惯会在改名时静默失效,
--      与本文件 2026-08-17 那条「依赖主题在最后一段」是同一类坑。
--    join 键:`app_launch.app_instance_id` = `firebase_event.user_pseudo_id`。
--    🛑 **2026-09-01 之前的设备一律对不上** —— 该列当时恒为 0(见 _口径与陷阱.md)。
--       实测近 30 天 12,428 台里 creative 落 `others` 的 4,169 台(33.5%),其中:
--         2,957 台是自然量/无归因(本来就没有素材,不算缺失)
--         1,212 台有归因却取不到素材(9.8%),而这里面 **1,126 台(93%)集中在 08-30~09-01**;
--         09-02 起每天只有 4~21 台对不上。
--       ⇒ 等 09-01 滚出 30 天窗口(约 2026-10-01)后,这块缺口会自行消失。
--    ⚠️ 对不上的落成 `others`,与「自然量/无归因」混在同一个值里 —— 要区分二者请按 source 拆。
--    影响:多一列、多一个 GROUP BY 维度,行数 3,903 → 4,457(+14%),
--      **各维度的 value 合计不变**(新旧均为 12,428,已实测对账);
--      渲染器 render_dashboard.py 的 cols 要一起改。

WITH u AS (
  SELECT user_pseudo_id AS device,   -- 按设备去重(下载量口径),不再按 uid
    MIN(CASE WHEN event_name='first_open' THEN event_date END)                     AS idt,
    MIN(CASE WHEN event_name='attribution_received' THEN params->>'$.pf'   END)    AS pf,
    MIN(CASE WHEN event_name='attribution_received' THEN params->>'$.type' END)    AS type,
    MIN(CASE WHEN event_name='first_open' THEN country END)                        AS country
  FROM host.firebase_event
  WHERE event_name IN ('first_open','attribution_received')   -- 见头部 09-08:不加这行索引用不上
    AND event_date >= DATE_FORMAT(CURDATE() - INTERVAL 30 DAY, '%Y%m%d')
  GROUP BY user_pseudo_id
  HAVING idt IS NOT NULL          -- 只保留近30天有 first_open 的新用户
),
device_creative AS (              -- 服务端素材名,取该设备最早一条启动行。见头部 2026-09-29
  SELECT app_instance_id AS device, MIN(NULLIF(creative, '')) AS creative
  FROM soul_map.soulmap_app_launch
  WHERE app_instance_id IS NOT NULL AND app_instance_id NOT IN ('', '0')
    AND add_on >= CURDATE() - INTERVAL 40 DAY   -- 比埋点窗口宽 10 天,兜住装机早于首个埋点日的设备
  GROUP BY app_instance_id
)
SELECT
  STR_TO_DATE(idt,'%Y%m%d') AS date,
  CASE WHEN pf LIKE '%Organic%'   THEN 'Organic'
       WHEN pf LIKE '%Google%'    THEN 'Google'
       WHEN pf LIKE '%Facebook%' OR pf LIKE '%Instagram%'
         OR pf IN ('fb','meta')   THEN 'Facebook'
       WHEN pf LIKE '%TikTok%' OR pf IN ('tt','tiktok') THEN 'TikTok'
       WHEN pf IS NULL           THEN 'others'
       ELSE pf END  AS source,
  -- placement:保留 pf 原值,不做平台归并。见头部 2026-09-09。
  COALESCE(pf,'others')                                AS placement,
  COALESCE(NULLIF(SUBSTRING_INDEX(SUBSTRING_INDEX(type,' (',1),'_',-1),''),'others')  AS adgroup,
  -- 素材名去掉 ` (数字ID)` 后缀,与 adgroup 同处理;取不到的落 others。见头部 2026-09-29
  COALESCE(NULLIF(SUBSTRING_INDEX(device_creative.creative,' (',1),''),'others')       AS creative,
  COALESCE(country,'others')                           AS country,
  COUNT(*)                                             AS value
FROM u
-- ⚠️ 显式 COLLATE:firebase_event.user_pseudo_id 是 utf8mb4_general_ci,
--    soulmap_app_launch.app_instance_id 是 utf8mb4_0900_ai_ci,直接 = 会报 1267。
LEFT JOIN device_creative
       ON device_creative.device COLLATE utf8mb4_general_ci = u.device
GROUP BY date, source, placement, adgroup, creative, country
ORDER BY date DESC, value Desc;
