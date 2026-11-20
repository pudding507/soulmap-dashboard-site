-- 验收_广告用户落地角色 · Acceptance — Ad User Lands on Ad Host
-- 2026-11-13 新建。出处:WW48 定稿 〇.8 待办 1(D-559 / D-560)—— 验收「落地率 49% → 80%」。
--
-- 【2026-11-13 改】取「第一条消息」的写法换掉,耗时 22.3s(冷)/ 5.6~7.6s(热) → 4.1~4.8s。
--   改了什么:`first_user_message` 原来是 `ROW_NUMBER() OVER (PARTITION BY chat.user_id)`,
--     且在 `chat.user_id` 上套了 `COLLATE utf8mb4_unicode_ci`;现在拆成
--     `first_message_id`(JOIN 队列 + `MIN(chat.id)`,不套 COLLATE)+ 按 id 回表取 host_id。
--   为什么:那个 COLLATE 是空操作(本表就是 unicode_ci),但它让 `idx_uid` 失效,
--     200 万行的 `soulmap_chat_history` 整表走窗口排序。网关超时线是 60 秒,冷跑 22 秒
--     经 `/api/card/:id/query` 很可能撞上,会变成每天要重抓的硬骨头卡。
--   影响:**结果零变化** —— 85 行逐行 diff 完全一致。
--
-- ═══ 这张卡回答什么 ═══
--   从**角色广告**进来的新用户,第一条消息是不是发给了广告里那个角色。
--   一行 = 一天 × 一个广告角色,近 21 天。
--
-- ═══ 🔴 分母必须只算「角色系列」,否则落地率被压到 6~13% ═══
--   投放的 campaign 有两类:带角色的(`SoulMap_TypeA_M_Divya_…`)和不带的
--   (下划线第 4 段解析出来是 `india` / `board` / `android` / `arabic` / `st` 这些)。
--   **不带角色的系列没有「广告角色」可落,算进分母就是永远匹配不上。**
--   🛑 **角色命名是 2026-10-26 才开始用的** —— 10-22~10-25 的角色系列用户数是 **0**,
--      那几天把全部广告用户当分母会算出 6~13%,**那是解析失准,不是真实落地率**。
--   本卡用 `soulmap_host_info` 的 `host_key` 首段做白名单,只保留能对上角色的系列。
--   实测近 7 天约 **85~88%** 的广告用户来自角色系列。
--
-- ═══ 🔴 真实形态:放量期暴跌,之后没回到原位 ═══
--   整体(分母 = 角色系列里说过话的人):
--     10-26 ~ 10-29(量小,每天 84~127 人) **65~81%**
--     10-30 ~ 11-03(大放量,每天 519~736 人) **24~33%**  ← 暴跌
--     11-04 起(每天 77~211 人) 41% → 55% → **57~65%**
--   🛑 **不要把这个形态读成某次改动的效果。** 它和当天投放的系列构成高度相关
--      (见下),同期还叠着 11-02~11-05 的投放目标切换(install → purchase)和
--      11-05 01:58 的 3.9.3 放量。**要定因果必须按版本或按系列分组,本卡只给相关性。**
--
-- ═══ 🔴 按角色系列差很多 —— 整体低主要是 Sander 和 Divya ═══
--   | 广告角色 | 10-30~11-03 | 11-04 起 |
--   |---|---|---|
--   | Lucien | 62.3% | **75.2%**(最接近 80% 目标) |
--   | Yui    | 50.8% | 61.0% |
--   | Divya  | **21.3%**(放量期 1,568 人,量最大) | 51.1% |
--   | Kabir  | 35.6% | 42.9% |
--   | Sander | **19.1%** | **29.5%**(一直最低) |
--   ⇒ 「落地率 80%」这个目标**不要只看整体数**:Lucien 已经快到了,Sander 还差 50 个点。
--
-- ═══ 🛑 两个分母,差约 10 个点,引用必须说清用的哪个 ═══
--   `landing_rate_of_spoke` 分母 = **发过第一条消息的**人 —— 近 7 天 57~65%
--   `landing_rate_of_all`   分母 = **全部**角色系列广告用户(含一句话没说的)—— 近 7 天 44~54%
--   🛑 定稿的「49% → 80%」没写分母。`landing_rate_of_all` 近三天是 49.0 / 50.2 / 51.1,
--      和 49% 很接近 ⇒ **定稿那个数大概率用的是「全部」口径**,但这是推断,没有出处佐证。
--
-- ═══ 🛑 其余口径 ═══
--   ① 广告用户 = 账号在 `soulmap_app_launch` 里有非空 `campaign`(设备级;广告来源还没
--      记到账号上,D-565 未做,见 `归因_广告来源覆盖率` 那张卡)。
--   ② 广告角色靠 campaign 下划线第 4 段解析。**这是启发式,靠投放的命名规范。**
--      命名一变就会静默失准 ⇒ 本卡输出 `ad_users`,某个系列的量突然掉就要回来核命名。
--   ③ 落地判据 `LOWER(host_id) LIKE '%<角色名>%'`。`host_id` 形如
--      `original:lucien_possessive_boyfriend_f4647f`,角色名就在里面。
--      用户自建角色是 `user:<uuid>`,永远匹配不上 —— 这是对的,它不是广告角色。
--   ④ 第一条消息 = `soulmap_chat_history` 里该用户 `role='user'` 的最小 `id`。
--      🛑 **必须限定 `role='user'`** —— 否则会取到 `reception-default` 群发的开场白。
--   ⑤ 排序规则:`soulmap_app_launch` 是 `utf8mb4_0900_ai_ci`(全库只有它),
--      `soulmap_chat_history` / `soulmap_host_info` 是 `utf8mb4_unicode_ci`
--      ⇒ 在 CTE 边界统一成 unicode_ci,否则报 `Illegal mix of collations`。
--   ⑥ 剔 CityPLX(`app_source='city'`):它不投广告,也不写 `soulmap_app_launch`。
--   ⑦ 单日 × 单系列分子常 <10,**不要单格下结论**,按系列或按周汇总了看。
--
-- ═══ 不在这张卡里的 ═══
--   待办 1 的另一半验收(所有 A 类 host 免费额度 = 20 + 送 10)是付费墙配置,不在这里。

WITH character_token AS (
    -- 角色名白名单:host_key 首段,如 lucien_possessive_boyfriend_f4647f → lucien
    SELECT DISTINCT
        LOWER(SUBSTRING_INDEX(host_info.host_key, '_', 1))
             COLLATE utf8mb4_unicode_ci                                        AS character_token
    FROM soul_map.soulmap_host_info host_info
    WHERE host_info.host_type = 'ai_companion'
      AND host_info.enabled = 1
      AND CHAR_LENGTH(SUBSTRING_INDEX(host_info.host_key, '_', 1)) >= 3
),
advertising_user AS (
    SELECT
        CAST(u.id AS CHAR) COLLATE utf8mb4_unicode_ci                          AS user_id_text,
        DATE(u.create_time)                                                    AS register_date,
        character_token.character_token                                        AS advertised_host
    FROM soul_map.user u
    JOIN (
        SELECT user_id, MAX(NULLIF(campaign, '')) AS campaign
        FROM soul_map.soulmap_app_launch
        WHERE add_on >= CURRENT_DATE - INTERVAL 31 DAY
        GROUP BY user_id
    ) launch
      ON launch.user_id = CAST(u.id AS CHAR) COLLATE utf8mb4_0900_ai_ci
    JOIN character_token
      ON character_token.character_token
       = LOWER(SUBSTRING_INDEX(SUBSTRING_INDEX(launch.campaign, '_', 4), '_', -1))
             COLLATE utf8mb4_unicode_ci
    WHERE u.create_time >= CURRENT_DATE - INTERVAL 21 DAY
      AND u.create_time <  CURRENT_DATE
      AND COALESCE(u.app_source, '') <> 'city'
),
first_message_id AS (
    -- 先只取「每人第一条 user 消息的 id」,再按 id 回表取 host_id。
    -- 🛑 **不要在 `chat.user_id` 上套 COLLATE** —— `soulmap_chat_history` 本来就是
    --   `utf8mb4_unicode_ci`,套了是空操作,但会让 `idx_uid` 用不上、整表走窗口排序。
    SELECT
        chat.user_id                                                           AS user_id_text,
        MIN(chat.id)                                                           AS first_message_id
    FROM soul_map.soulmap_chat_history chat
    JOIN advertising_user
      ON advertising_user.user_id_text = chat.user_id
    WHERE chat.role = 'user'
    GROUP BY chat.user_id
),
first_user_message AS (
    SELECT
        first_message_id.user_id_text                                          AS user_id_text,
        chat.host_id                                                           AS host_id
    FROM first_message_id
    JOIN soul_map.soulmap_chat_history chat
      ON chat.id = first_message_id.first_message_id
)
SELECT
    advertising_user.register_date                                             AS date,
    advertising_user.advertised_host                                           AS advertised_host,
    COUNT(*)                                                                   AS ad_users,
    SUM(first_user_message.host_id IS NOT NULL)                                AS users_who_spoke,
    SUM(LOWER(first_user_message.host_id)
        LIKE CONCAT('%', advertising_user.advertised_host, '%'))               AS landed_on_ad_host,
    ROUND(100.0 * SUM(LOWER(first_user_message.host_id)
          LIKE CONCAT('%', advertising_user.advertised_host, '%'))
          / NULLIF(SUM(first_user_message.host_id IS NOT NULL), 0), 1)         AS landing_rate_of_spoke,
    ROUND(100.0 * SUM(LOWER(first_user_message.host_id)
          LIKE CONCAT('%', advertising_user.advertised_host, '%'))
          / COUNT(*), 1)                                                       AS landing_rate_of_all
FROM advertising_user
LEFT JOIN first_user_message
       ON first_user_message.user_id_text = advertising_user.user_id_text
GROUP BY advertising_user.register_date, advertising_user.advertised_host
ORDER BY advertising_user.register_date DESC, ad_users DESC

