-- 结账档位对比 · Checkout by Tier
--
-- 2026-11-23 新建。和「结账链路(服务端)」同源(`soul_map.soulmap_energy_order`),
-- 那张按天看链路,这张按档位横向比。
--
-- 【为什么单独一张卡】档位之间的差距很大,而且**最便宜的档位最差**:
--   实测 11-19 起走完流程的单里,L1 到账率 26.6%、L2 50.5%,
--   而 L1 的失败几乎全是**用户主动取消**(118/184 = 64%),不是报错。
--   这个差异按天拆就读不出来了(每档每天只有几单),所以这张卡**整段合计、不拆天**。
--
-- 🛑 **不拆天的理由是「比较档位需要分母」,不是「量小」** ——
--    要看某个档位的逐日变化,用「结账链路(服务端)」那张按天的数据另算。
--
-- ═══ 🛑 口径(和「结账链路(服务端)」完全一致,改一张要同步改另一张)═══
-- ① 窗口下界 **2026-11-19**(安卓 3.9.7 上架,下单步骤从这天才上报),和滚动 30 天取晚的那个。
-- ② 🔴 **只统计走完流程的单**(`tapped_at` 非空)。`tapped_at` 为空的是服务端回调补记的成交,
--    实测 172 笔**全部是 credited**,混进分母会把到账率抬高(L1 混着算 43.5%,只看走流程 26.6%)。
-- ③ 成功状态叫 `credited`,表里没有 `success`。
-- ④ 排 CityPLX(`user.app_source`)和**内部测试号 15 个**(口径 24.4 的 9 个 + 变更记录的 6 个)。
--
-- 🛑 比率的分子不足 10 一律留空。实测 L5(到账 6)、plan(到账 1)就读不出,**那是对的,不是漏数**。
WITH window_start AS (
    SELECT GREATEST('2026-11-19 00:00:00', CURDATE() - INTERVAL 30 DAY) AS t0
),
test_account AS (
    -- 🛑 内部测试号。**两份名单合起来**:
    --   口径 24.4 的 9 个(2026-11-02 统一,台账 §184 + 康 247 自报的商店沙盒号)
    --   + Javier 在 11-20 变更记录第 5 节给的 6 个(84204 等,口径文档当时还没收录)
    -- 实测 11-19 起:前 9 个在订单表里 0 单,后 6 个有 5 单 / 2 人 ——
    --   其中 plan 档 12 单里占了 2 单(17%),对小分母的档位不能不剔。
    SELECT '62412' AS user_id UNION ALL SELECT '72048' UNION ALL SELECT '72382'
    UNION ALL SELECT '72462' UNION ALL SELECT '74640' UNION ALL SELECT '74377'
    UNION ALL SELECT '74592' UNION ALL SELECT '71693' UNION ALL SELECT '71826'
    UNION ALL SELECT '84204' UNION ALL SELECT '84214' UNION ALL SELECT '84209'
    UNION ALL SELECT '84216' UNION ALL SELECT '83130' UNION ALL SELECT '82459'
),
ord AS (
    SELECT  COALESCE(NULLIF(o.tier, ''), '(没记档位)')            AS tier,
            o.status                                             AS status,
            o.store_error_code                                   AS err,
            o.user_id                                            AS user_id
    -- 🛑 window_start 用显式 CROSS JOIN,逗号 join 的优先级低于 LEFT JOIN
    FROM        soul_map.soulmap_energy_order AS o
    CROSS JOIN  window_start
    LEFT JOIN   soul_map.`user` AS u ON u.id = CAST(o.user_id AS UNSIGNED)
    WHERE       o.created_at >= window_start.t0
      AND       o.tapped_at IS NOT NULL          -- 见口径 ②
      AND       (u.app_source IS NULL OR u.app_source = '')
      AND       o.user_id NOT IN (SELECT user_id FROM test_account)
)
SELECT  tier                                                     AS tier,
        COUNT(*)                                                 AS orders,
        COUNT(DISTINCT user_id)                                  AS users,
        SUM(status = 'credited')                                 AS credited,
        CASE WHEN SUM(status = 'credited') >= 10
             THEN ROUND(100.0 * SUM(status = 'credited') / COUNT(*), 1) END  AS credited_rate,
        SUM(status = 'user_cancel')                              AS user_cancel,
        CASE WHEN SUM(status = 'user_cancel') >= 10
             THEN ROUND(100.0 * SUM(status = 'user_cancel') / COUNT(*), 1) END AS cancel_rate,
        SUM(status = 'error')                                    AS errors,
        SUM(err = 'PURCHASE_NOT_ALLOWED_ERROR')                  AS err_not_allowed,
        -- 兜底:新错误码会落在这里,不会无声消失
        SUM(status = 'error'
            AND COALESCE(err, '') <> 'PURCHASE_NOT_ALLOWED_ERROR')           AS err_other
FROM    ord
GROUP BY tier
ORDER BY orders DESC;
