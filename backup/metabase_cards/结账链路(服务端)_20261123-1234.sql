-- 结账链路(服务端) · Checkout Chain (Server)
--
-- 2026-11-23 新建。数据源 `soul_map.soulmap_energy_order`(服务端 11-16 16:28 上线),
-- 此前看板上**没有任何一张卡用这张表**。
--
-- 【为什么要这张卡】看板已有的「付款页成功率与真实失败」走**客户端埋点**,
--   会漏报,也没有完整的时间戳。这张表是服务端记的,补上了:
--     tapped_at → sheet_opened_at → pending_at → result_at → credited_at 完整链路
--     store_error_code 直接给(不用从客户端三层错误码下钻)
--     paywall_arm(半屏/全屏实验臂)、tier(档位)、client_build
--   🛑 **两张卡并存,不要互相替代**:客户端那张有 `ms_in_sheet` 和 `trigger`,这张没有。
--
-- ═══ 🛑 两个必须知道的口径 ═══
--
-- ① **11-19 04:05 之前没有客户端上报的链路字段。**
--    `tapped_at` / `sheet_opened_at` / `price_micros` / `paywall_arm` 这些要 3.9.7+ 才上报
--    (changelog:「下单步骤上报从这里开始,只有 3.9.7+」)。实测填充率:
--      11-16~11-18 几乎全空 → 11-19 45% → 11-20 66% → 11-21 89% → 11-22 92% → 11-23 100%
--    ⇒ 窗口下界取 **2026-11-19**,和滚动 30 天取晚的那个。往前取会把没有链路的单算进分母。
--
-- ② 🔴 **`tapped_at` 为空的单是「服务端回调补记的成交」,不是「走完流程的单」。**
--    实测这类单 **172 笔状态全部是 `credited`** —— 它们没经过客户端上报,
--    直接从商店回调补记。混进分母会把到账率抬高:
--      L1 档混着算 43.5%,只看走完流程的单是 **26.6%**。
--    ⇒ 本卡把两者**分开列**:链路各级和到账率只对 `reported`(走完流程的)算,
--      `credited_backfill` 单独一列放补记的成交,两者相加才是当天全部到账。
--
-- 🛑 成功状态叫 **`credited`**,表里**没有 `success` 这个值**(写 success 会得到 0)。
-- 🛑 `surface`(入口)近 7 天有 32.6% 是空 —— 老版本不上报,所以本卡不做入口维度,
--    等 3.9.7+ 覆盖率上来再说。
--
-- 【展示形式】表格,一行 = 一天 × 弹窗实验臂。带 arm 是因为半屏/全屏实验正在跑,
--   而看板上还没有卡能看它的**结账转化** —— 这张卡顺带回答了。
--   🛑 到账率的分子不足 10 时留空(读不出就别给数)。
WITH window_start AS (
    -- 下界:3.9.7 上架日和滚动 30 天取晚的那个,见卡头 ①
    SELECT GREATEST('2026-11-19 00:00:00', CURDATE() - INTERVAL 30 DAY) AS t0
),
ord AS (
    SELECT  DATE(o.created_at)                                   AS date,
            CASE o.paywall_arm WHEN 'half' THEN 'half 半屏'
                               WHEN 'full' THEN 'full 全屏'
                               ELSE '未进组' END                  AS arm,
            o.status                                             AS status,
            o.store_error_code                                   AS err,
            o.tapped_at IS NOT NULL                              AS reported,
            o.user_id                                            AS user_id,
            o.tapped_at, o.sheet_opened_at, o.result_at, o.credited_at
    -- 🛑 window_start 要用显式 CROSS JOIN,不能写成逗号 ——
    --    逗号 join 的优先级**低于** LEFT JOIN,会导致下面 ON 子句里看不见 o
    --    (报 Unknown column 'o.user_id' in 'on clause')。
    FROM        soul_map.soulmap_energy_order AS o
    CROSS JOIN  window_start
    -- 🛑 排 CityPLX,口径同其它能量卡
    LEFT JOIN   soul_map.`user` AS u ON u.id = CAST(o.user_id AS UNSIGNED)
    WHERE       o.created_at >= window_start.t0
      AND       (u.app_source IS NULL OR u.app_source = '')
)
SELECT  date                                                     AS date,
        arm                                                      AS arm,
        COUNT(*)                                                 AS orders,
        COUNT(DISTINCT user_id)                                  AS users,
        -- ↓ 链路各级:只对走完流程的单算(见卡头 ②)
        SUM(reported)                                            AS reported,
        SUM(reported AND sheet_opened_at IS NOT NULL)            AS sheet_opened,
        SUM(reported AND result_at IS NOT NULL)                  AS got_result,
        SUM(reported AND status = 'credited')                    AS credited,
        -- 分子 < 10 不给比率
        CASE WHEN SUM(reported AND status = 'credited') >= 10
             THEN ROUND(100.0 * SUM(reported AND status = 'credited')
                        / NULLIF(SUM(reported), 0), 1) END       AS credited_rate,
        SUM(reported AND status = 'user_cancel')                 AS user_cancel,
        SUM(reported AND err = 'PURCHASE_NOT_ALLOWED_ERROR')     AS err_not_allowed,
        SUM(reported AND err = 'PRODUCT_ALREADY_PURCHASED_ERROR') AS err_already_owned,
        -- 🛑 兜底:服务端加新错误码时这一列会立刻有数,而不是无声消失
        SUM(reported AND status = 'error'
            AND COALESCE(err, '') NOT IN ('PURCHASE_NOT_ALLOWED_ERROR',
                                          'PRODUCT_ALREADY_PURCHASED_ERROR'))
                                                                 AS err_other,
        SUM(reported AND status IN ('pending', 'sheet_opened'))  AS still_open,
        -- ↓ 补记的成交:没经过客户端上报,直接从商店回调记的(见卡头 ②)
        SUM(NOT reported AND status = 'credited')                AS credited_backfill
FROM    ord
GROUP BY date, arm
ORDER BY date DESC, orders DESC;

