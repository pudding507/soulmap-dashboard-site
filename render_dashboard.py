#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SoulMap 线上看板 · 趋势优先渲染器 v2(内嵌 Chart.js + 维度切换)

读 raw_metrics.json → 单文件 self-contained HTML:
  · 折线趋势为主,卡片可切维度(如 DAU:总体 / 按新老 / 按来源)
  · 激活漏斗 / 种子星漏斗 → 4 版本周分组柱
  · 内嵌 Chart.js(lib/chart.umd.min.js,离线)· 柔和统一配色 · 明暗双主题
聚合在 Python 做好(每卡每维度预算成 {series:[[date,y]]}),JS 只负责画 + 切换。

用法: python3 render_dashboard.py [--raw raw_metrics.json] [--out soulmap-online.html]
加卡只需在 SECTIONS 里加一行。
"""
from __future__ import annotations
import argparse, json, re
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEEK_ORDER = ["6/27-7/3", "7/4-10", "7/11-17", "7/18起"]

# 顶部数据可靠性横幅(置空字符串即隐藏;以后有新事件改这里)
BANNER = ""

# ---------- 切点总表(机器可读)----------
# 2026-10-28 新建。对应 186 §四 我答应维护的那张表 —— 台账 §2.0 现在是人读的 markdown,
# 这里是给代码读的那一份。**两边都要加,别只加一处。**
#   用途:页头「今天变化最大的 5 个数」判断某一行的比较窗口是不是跨了切点。
#   🛑 跨切点的行**打 ⚠ 标,不剔除** —— 剔掉就看不见切点当天的真实跳变,
#      而那一跳往往正是当天最该看的数。
CUTOVERS = {
    "2026-10-11": "埋点侧缺这一天(服务端不缺);画趋势留空,不补零不插值",
    "2026-10-16": "印度启动墙上线(18:37)",
    "2026-10-20": "全球免费额度 10 → 20(印度 A 类 30)",
    "2026-10-22": "印度以外的 A 类额度也放到 30;first_message_gate 上线(16:16);「买 3 天」通行证开始有真实购买——它和月订阅共用 purchase_* 事件,付费口径从这天起必须按 product_id 限定",
    "2026-10-26": "AN 渠道关停(18:30)—— 装机分母清理,整体数会跳,不是产品变好",
    "2026-10-28": "能量系统上线(14:32:20)—— 能量包 L1~L6 + 能量版 Plus 订阅,同样共用 purchase_* 事件;3.9.0 发版同日",
}

# ---------- 页头「今天变化最大的 5 个数」的门槛 ----------
# 出处:埋点需求 §10 最后一行「Chris 每天在看板顶部给一张『今天变化最大的 5 个数』」。
MOVERS_MIN_N = 30     # 两天的值都要到这个数才进榜,见 _movers() 的口径 ③
MOVERS_TOP   = 5      # Michael 要的是「5 个数」

# ---------- 聚合 ----------
def _num(x):
    # Metabase query/json 把大数返回成带千分位逗号的字符串("3,065"),必须先去逗号再转
    try: return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError): return 0.0

def _nd(d):
    """把各种日期格式统一成 ISO(YYYY-MM-DD),保证按时间正确排序 + 干净标签。
    Metabase JSON 可能返回 'Jun 30, 2026' / '2026-06-30' / '2026-06-30T…' 等。"""
    s = str(d).strip()
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        return s[:10]
    s2 = s.split("T")[0].strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y/%m/%d", "%d %b %Y"):
        try: return datetime.strptime(s2, fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    return s2

def _dc(rows):
    """识别日期列:优先 date,否则第一个以 date 开头的列(date_msg/date_session/date_turn/date_first_chat…)。"""
    if not rows: return "date"
    r0 = rows[0]
    if "date" in r0: return "date"
    for k in r0:
        if str(k).startswith("date"): return k
    return "date"

def _rollup(acc, cap, other="其他"):
    """把尾部序列并进「其他」,而不是丢掉。

    必须在聚合层(acc)做,不能在算完之后做:
       rate 卡的正确归并是「分子和 ÷ 分母和」,把各自的率相加是错的。
       acc 的值是 [分子/总量, 分母/条数] 这种可加的对,所以直接相加即可。
    排名沿用 _cap 的口径(按末值),保持既有卡的命名序列不变;
    唯一的行为变化是:原先被静默丢掉的序列,现在汇总成一条「其他」。
    """
    if not cap: return acc
    last = {}
    for (s, d), v in acc.items():
        if s not in last or d > last[s][0]: last[s] = (d, v[0])
    keep = {s for s, _ in sorted(last.items(), key=lambda kv: kv[1][1], reverse=True)[:cap]}
    if len(last) <= cap: return acc
    merged = defaultdict(lambda: [0.0, 0.0])
    for (s, d), v in acc.items():
        key = (s if s in keep else other, d)
        m = merged[key]; m[0] += v[0]; m[1] += v[1]
    return merged

def _agg(rows, val, by=None, how="sum", dc="date", cap=None):
    acc = defaultdict(lambda: [0.0, 0])
    for r in rows:
        d = r.get(dc)
        if d is None: continue
        s = (str(by(r)) if callable(by) else str(r.get(by))) if by else "Overall"
        a = acc[(s, _nd(d))]; a[0] += _num(r.get(val)); a[1] += 1
    acc = _rollup(acc, cap)
    out = defaultdict(list)
    for (s, d), (t, c) in acc.items():
        out[s].append((d, round(t / c, 3) if (how == "avg" and c) else round(t, 3)))
    for s in out: out[s].sort()
    return out

def _rate(rows, num, den, by=None, dc="date", cap=None):
    acc = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        d = r.get(dc)
        if d is None: continue
        s = (str(by(r)) if callable(by) else str(r.get(by))) if by else "Overall"
        a = acc[(s, _nd(d))]; a[0] += _num(r.get(num)); a[1] += _num(r.get(den))
    acc = _rollup(acc, cap)
    out = defaultdict(list)
    for (s, d), (n, dd) in acc.items():
        out[s].append((d, round(n / dd, 4) if dd else 0.0))
    for s in out: out[s].sort()
    return out

def _cap(ser, n=6):
    """序列过多只留末值最大的 n 个。"""
    items = sorted(ser.items(), key=lambda kv: kv[1][-1][1] if kv[1] else 0, reverse=True)
    return OrderedDict(items[:n])

def _ord(ser, order):
    """按 order 固定序列顺序,其余接后面。"""
    od = OrderedDict((k, ser[k]) for k in order if k in ser)
    for k in ser:
        if k not in od: od[k] = ser[k]
    return od

_ADG = lambda r: f"{r.get('source')}_{r.get('adgroup')}"   # source×adgroup 组合序列
# 2026-09-29:素材名本身已含来源信息(SoulMap_CH01_… / SoulMap_MV1_… / SoulMap_SM_TA_…),
#   不再叠 source,否则图例会长到放不下。取不到素材的落 others,与自然量混在一起 —— 见 SQL 头部。
_CRE = lambda r: r.get('creative')

# 三张留存卡共用的维度配置(SQL 输出 dimension 列的取值 → 选项卡标签/顺序)
RETENTION_DIMS = dict(
    dimorder=["overall", "source", "adgroup", "country", "input_path", "first_day_depth"],
    dimlabels={"overall": "Overall", "source": "by source", "adgroup": "by source×adgroup",
               "country": "by country", "input_path": "by input path",
               "first_day_depth": "by day-0 turns"},
    slorder={"input_path": ["text", "voice", "unknown"],
             "first_day_depth": ["0-4", "5-9", "10+"]},
    min_vol=30,   # 累计新用户不足 30 的维度取值不画(小样本率没有参考价值)
)

# 广告组首日对照卡的维度配置(SQL 的 dimension 列 → 指标选项卡;dimension_value = 各广告组线)
# 每日角色 CTR 的维度配置(SQL 的 dimension 列 → 选项卡;dimension_value = 各角色线)
CHAR_DAILY_CTR_DIMS = dict(
    dimorder=["overall", "character"],
    dimlabels={"overall": "Overall", "character": "by character"},
    # 按点击数排线,不按曝光:目录按字母序展示,曝光被顶得人人相近
    # (实测累计曝光 top5 全是 A 开头、都是 ~1960),按曝光取 top10 等于按首字母取。
    volcol={"character": "numerator"},
    min_vol={"character": 20},   # 累计点击不足 20 的角色不画(个位数点击的 CTR 是噪音)
    cap=10,
)

# 角色卡漏斗分场景的维度配置(SQL 的 dimension 列 → 指标选项卡;dimension_value = 各 tile 线)
_TILE_METRICS = ["tap_rate", "chat_rate", "deep_rate"]
TILE_DIMS = dict(
    dimorder=_TILE_METRICS,
    dimlabels={"tap_rate": "Tap rate", "chat_rate": "Tap → chat", "deep_rate": "Impression → deep"},
    # 按选项卡分设:tap/deep 的分母是曝光(累计 470~17379),chat 的分母是点击(19~682),量级差 25 倍
    min_vol={"tap_rate": 200, "deep_rate": 200, "chat_rate": 50},
    cap=13,        # tile 共 13 类,全画
)

# 点击位次分布的维度配置(SQL 的 dimension 列 = 子 tab → 选项卡;dimension_value = 位次档 = 线)
# 本卡只用 card_tap,分子分母同盘,与曝光无关 —— 不要给它加回 CTR 语义,原因见 SQL 头部。
_POSITION_BUCKETS = ["位0-4", "位5-9", "位10-29", "位30-59", "位60+"]
_POSITION_TABS = ["foryou", "all", "new_this_week", "try_different", "(pre-2.8.0)"]
POSITION_DIMS = dict(
    dimorder=_POSITION_TABS,
    dimlabels={"foryou": "For you", "all": "All", "new_this_week": "New this week",
               "try_different": "Try something", "(pre-2.8.0)": "2.8.0 之前"},
    slorder={k: _POSITION_BUCKETS for k in _POSITION_TABS},   # 固定档位顺序,别按量排
    min_vol=30,    # 当天该 tab 总点击不足 30 不画(占比在小分母上跳得没有意义)
    cap=5,         # 五档全画
)

# 用户偏好分布的维度配置(SQL 的 dimension 列 → 选项卡;dimension_value = 各取值线)
# theme 选项卡是多选(每人 1~4 个),各线之和约 219% —— 不是构成比,不可堆叠。
#    gender_preference / theme_count 是单选,各线之和 = 100%,可读构成。
_PREF_THEMES = ["romance","friendship","relationship_issues","drama","adventure",
                "fantasy","life_advice","venting","cheer_up","career_school"]
PREFERENCE_DIMS = dict(
    dimorder=["theme", "gender_preference", "theme_count"],
    dimlabels={"theme": "by theme (multi-select)", "gender_preference": "by who to meet",
               "theme_count": "by how many themes"},
    slorder={"theme": _PREF_THEMES,
             "gender_preference": ["female", "male", "mixed", "none", "unknown"],
             "theme_count": ["1个", "2个", "3个", "4个", "0个"]},
    cap=10,        # theme 共 10 项,全画
)

# ---------- 注册表 ----------
# line 卡: dims = [(key,label,by_col)]; by_col=None 即总体
# rate 卡: 加 rate=(num,den); long_dim: SQL 自带 dimension/dimension_value 列; funnel: 无参
SECTIONS = [



 # ╔══════════════════════════════════════════════════════════════════════════╗
 # ║ 2026-10-19 新增六章,全部来自 Metabase 看板 24(experiment)                ║
 # ╚══════════════════════════════════════════════════════════════════════════╝
 # 起因:Pages 看板原来只抓看板 18(Report raw),而 10-15 玩法改成 0.99 直购之后,
 #   新玩法的卡(0.99/付费墙实验/额度墙/邀请/语音)全部建在看板 24,线上一张都看不到。
 #   fetch_metabase.py 已改成同时抓 18+24,重叠的 15 张按 card_id 去重。
 #
 # 🛑 这六章的卡全部用 table —— 不是偷懒,是跟着看板 24 的设计走:
 #    那边每张卡的卡头都写了「展示形式:表格」,理由是比率画成折线会把分母的变化藏起来
 #    (撞墙人数、分臂人数每天都在动)。这里画成折线等于把那层保护拆掉。
 #
 # 🛑 看板 24 的百分比列一律是 `ROUND(100.0 * ... , 1)`,也就是 0~100 的数;
 #    而本文件的 pct0/pct1 格式化器吃的是 0~1(见 APP_JS 的 fmtV)。
 #    所以这些列一律用 `d1`、把 % 写进列名 —— 同 capability 卡的 delivery_rate_before_0819。
 #    ⚠️ 写成 pct1 的话会显示成 7540%,而且不会报错。

 # 2026-10-19 第二次调整:区从 15 压到 10,顺序改成「用户旅程」。
 #   · 额度墙(1 张)并进付费墙实验 —— 「撞墙才弹墙」和「什么时机弹墙」是一件事的两面
 #   · 模型(1 张)+ 能力链路(2 张)合成「后端」—— 原来各自单卡成区
 #   · 原「现状」区的 2 张拆散:各国新用户与深度 → 增长,语音文字占比 → 语音
 #   · 0.99 首月(3 张)并进变现 —— 0.99 是价格、付费漏斗是结果,本来就是一条链
 #   · 三 Tab(3 张)并进发现 —— Tab 是进发现页的入口,渗透率和点击连着看

 # 2026-10-21 第三次调整:按 Michael 10-21 看板反馈第七条「瘦身」,
 #   把 23 张卡移进新建的「⑬ 附录」—— **不是删卡,只是挪到后面**。
 #   他的判据是「不服务『聊深、回来、不退订』这三件事」,具体四类:
 #     · 日活 / DAU新老占比 / 新用户数 —— Bible 写明注册数、日活不作成功指标(被买量主导)
 #     · 装机口径的 D1/D3/D7 —— 和「有效留存 D1」并存会有两个 D1,后者才是北极星口径
 #     · 导航与发现页 —— 做界面时有用,不服务上面三件事
 #     · 均值类(轮数/时长/消息长度/人均消息/AI首条时延)—— 均值被长尾带偏,和「人·天≥10条」对不上
 #   另外两张按他的意见也挪了:投入用户数(purpose 来自旧版 onboarding 表单)、
 #   深度新用户数(还在用「≥5 轮」,其余卡已改成按句数)。
 # 🛑 发现页只留两张在前面:角色表现榜 + 角色 QCD与回访 —— 他把后者列进「最有用」前三。
 #   原「⑥ 发现与导航」因此改名为「⑥ 角色」。

 # 2026-10-21 第四次调整:把 5 张从附录拿回前面。
 #   原因:Michael 反馈第七条点名的四类里,有两类的理由只对部分卡成立 ——
 #   · **日活 / DAU新老占比 / 新用户数**:Bible 说它们不作**成功指标**是对的,
 #     但它们是**分母**。10-21 查有效 D1 下滑,正是靠「注册账号从 240 涨到 436」
 #     才定位到是分母在动;他自己也用新用户数做过分析。**不当 KPI ≠ 不用看。**
 #   · **留存 D3 / D7**:「和有效留存 D1 并存会有两个 D1」只对 **D1** 成立 ——
 #     有效留存卡**没有 D3、D7**,移走就没有任何三日/七日留存了。
 #   ⇒ 附录只留 18 张,全部是「实在没用」的:渲染失败 1 张(角色卡漏斗分场景 error:'0')、
 #     字段已废 1 张(投入用户数的 purpose 来自旧版 onboarding 表单)、
 #     口径不一致 1 张(深度新用户仍用「≥5 轮」)、均值类 5 张、导航 3 张、发现页 7 张。
 ("① 增长 · Growth", [
   ("channel_start_success", "渠道启动成功率 · Channel Start Success", "table",
       # 2026-10-27 新建(Metabase 卡 443)。本周最大的问题,此前看板上一张卡都看不到,
       #   10-19 起全靠人工取数(跨团队 174/175/188/206)。
       # 🛑 渠道取 firebase_campaign.source(SDK 原生事件);**不能取 attribution_received** ——
       #   那是 JS 发的,而要查的恰恰是 JS 没跑起来的设备,用它取渠道等于先把要查的人删掉。
       dict(top=60,
            cols=[("install_date","装机日 Install Date","text"),
                  ("channel","渠道 Channel","text"),
                  ("installs","装机设备 Installs","int"),
                  ("opened","正常启动 Opened","int"),
                  ("open_pct","正常启动率 %","d1"),
                  ("has_account","建了号 Account","int"),
                  ("account_pct","建号率 %","d1"),
                  ("attributed","有归因 Attributed","int"),
                  ("attributed_pct","有归因率 %","d1")],
            bar=["installs","open_pct"],
            note="🛑 **「正常启动」= 有 `app_open`**(JS 根组件挂载时发)。不要用 `screen_view`(系统自动记,JS 没跑也有,AN 上实测 99.6%,完全看不出问题),也不要用 `launch_splash_decided`(在 welcome.tsx,不在根组件)。🔴 **实测 AN 渠道 10-17 起只有 2.1~19.6% 能正常启动,其余渠道 77~100%** —— 这批设备不建号不付费但全算进分母,整体付费率 3.49%→1.73% 里约 1.06 个点是被它稀释的。AN 在往上走(10-18 的 2.1% → 10-26 的 19.2%),**修复到位的标志是回到 90% 以上**。🛑 **「无来源记录」是最大的一格**(每天 160~330 台,多数日子比 AN 还多),它不是某个渠道,启动率 83~94%,**不要并进「其它渠道」读**。🛑 `(not set)` 和「无来源记录」是两回事:前者 SDK 发了事件但归因为空,后者连事件都没有。｜ Devices that installed but never booted the JS layer — AN at 2~20% vs 77~100% elsewhere.")),
   ("snapshot_country_depth", "各国新用户与聊天深度 · New Users & Depth by Country", "table",
       dict(top=25,
            cols=[("country","国家 Country","text"),
                  ("new_users","新用户 New Users","int"),
                  ("engaged_gt3",">3句 >3 msgs","int"),
                  ("engaged_gt3_pct",">3句 % ","d1"),
                  ("engaged_ge10","≥10句 ≥10 msgs","int"),
                  ("engaged_ge10_pct","≥10句 %","d1"),
                  ("deep_ge20","≥20句 ≥20 msgs","int"),
                  ("deep_ge20_pct","≥20句 %","d1"),
                  ("returned_denom","回访分母 Denom","int"),
                  ("returned","回访 Returned","int"),
                  ("returned_pct","回访率 %","d1")],
            bar=["new_users","engaged_ge10_pct"],
            note="首日句数口径(day0_msgs),一行一个国家。三个深度档的分母都是该国新用户;回访那组分母另算(returned_denom),不要拿 returned 去除 new_users。｜ Day-0 message depth by country; the return columns have their own denominator.")),
   ("growth_dau", "日活跃用户数 · DAU", "line", dict(
            note="当天打开过 App 的用户(session_start) ｜ Users who opened the app that day (session_start)",val="value", cap=12,
       rollup={"country": 20},
       dims=[("overall","Overall",None),("user_type","by user type","user_type"),("source","by source","source"),("adgroup","by source×adgroup",_ADG),("country","by country","country")])),
   ("growth_dau_new_returning", "DAU 新老占比 · New vs Returning", "rate",
       dict(rate=("users","daily_active_users"), fmt="pct0", order=["new","returning"],
            note="新/老用户 ÷ 当天DAU;新=当天安装 ｜ New vs returning share of daily DAU; “new” = installed that day",
            dims=[("user_type","","user_type")])),
   ("growth_new_user", "新用户数 · New Users", "line", dict(
            note="当天首次安装 App 的用户(first_open) ｜ Users whose first_open happened that day",val="value", cap=12,
       rollup={"country": 20},
       # 2026-09-09 加 by placement:source 是平台归并(Meta 三版位合成 Facebook),placement 是
       #   pf 原值。实测三个版位的地区结构差别大(Facebook Installs 英语一线 9.0% vs
       #   Off-Facebook 3.5%),合并会抹掉。两个切页都留:汇报看 source,投放看 placement。
       # 2026-09-29 加 by creative:埋点侧没有素材字段(attribution_received 只有 pf/pm/type,
       #   且 pm 装的是 campaign 名 —— TypeB 测试下三条素材的 pm 完全相同),
       #   素材来自服务端 app_launch,在 SQL 里 join 进来。
       #   ⚠️ 2026-09-01 之前的设备 app_instance_id 恒为 0、join 不上,那几天落 others;
       #      约 2026-10-01 后 09-01 滚出 30 天窗口即自愈。详见 SQL 头部。
       dims=[("overall","Overall",None),("source","by source","source"),
             ("placement","by placement","placement"),
             ("adgroup","by source×adgroup",_ADG),("creative","by creative",_CRE),
             ("country","by country","country")])),
   ("growth_version_adoption", "版本覆盖率 · Version Adoption", "rate",
         dict(rate=("devices","daily_active_devices"), fmt="pct0", cap=9,
              note="当天活跃设备按 App 版本拆分;设备一天内跨版本时归入较高版本 ｜ Daily active devices by app version; a device spanning versions in one day counts to the higher one",
              dims=[("app_version","","app_version")])),
     ("growth_adgroup_d0_comparison", "广告组首日对照 · Ad-Group D0 Comparison", "table",
         dict(top=40,          # 不填 sort = 保持 SQL 的 ORDER BY date DESC, new_users DESC
              cols=[("date","日期 Date","text"),
                    ("adgroup","广告组 Ad Group","text"),
                    ("new_users","新用户 New Users","int"),
                    ("first_message","首条消息 First Msg","int"),
                    ("first_message_rate","首条率 Rate","pct0"),
                    ("turns_5plus","5+轮 5+ Turns","int"),
                    ("turns_5plus_rate","5+轮率 Rate","pct0"),
                    ("turns_10plus","10+轮 10+ Turns","int"),
                    ("turns_10plus_rate","10+轮率 Rate","pct0"),
                    ("retained_d1","D1 回访 D1","int"),
                    ("retention_d1_rate","D1 留存率 Rate","pct0")],
              bar=["new_users","first_message_rate"],
              note="各广告组新增设备的首日行为与次日留存,按日倒序;分母 = 该广告组当天新设备数 \uff5c Day-0 behaviour and D1 retention by ad group, newest first; denominator = that group\u2019s new devices that day")),
   ("growth_meta_daily_qcd_by_creative", "按装机日明细 · Meta 素材全链路 · Meta Funnel by Install Date", "table",
       # 2026-09-14 随 SQL 改版:列结构与 growth_meta_funnel_by_creative 对齐,只是多一个 date 维度。
       #   两张卡变成「明细 / 汇总」的关系:本卡按装机日拆,那张按素材汇总,口径完全一致。
       #   唯一例外是本卡有 HAVING installs >= 10,所以按 date 求和会略小于汇总表。
       dict(top=30,          # 不填 sort = 保持 SQL 的 ORDER BY date DESC, installs DESC
            cols=[("date","装机日 Install Date","text"),
                  ("creative","素材 Creative","text"),
                  ("installs","装机 Installs","int"),
                  ("reached_first_message","发过消息 Any Msg","int"),
                  ("first_message_rate","装机→发消息","pct0"),
                  ("reached_qcd","达成 QCD (6句)","int"),
                  ("qcd_rate","装机→QCD","pct1"),
                  ("reached_20msg","累计 20 句","int"),
                  ("msg20_rate","装机→20句","pct1"),
                  ("purchase_started_users","发起购买 Started","int"),
                  ("trial_effective_users","开过订阅(试用或0.99) Sub Started","int"),
                  ("intro_users","其中 0.99 Intro","int"),
                  ("paid_users","付费 Paid","int"),
                  ("retained_d1_rate","D1 回访率","pct1"),
                  ("retained_d7_window_rate","D7窗 回访率 (5\u20139d)","pct1")],
            bar=["installs","qcd_rate"],
            note="上一张卡的按装机日明细，列与口径相同，滤掉装机<10 的素材-日。按天拆分母更小，读比率前先看装机列。「发起购买」走埋点、滞后 1–2 天。｜ Per-install-date detail of the card above; same definitions. Started is telemetry, lagged 1–2 days.")),
   ("growth_meta_funnel_by_creative", "按素材汇总 · Meta 素材全链路 · Meta Funnel by Creative", "table",
       # 2026-09-07 随 SQL 重构:删掉「看过角色卡」与两个相关率列 —— 曝光埋点只覆盖部分 tab
       #   (foryou/new_this_week/try_different 曝光恒为 0,而这三个占点击 79.5%),拿它当漏斗
       #   第一级会出现「点击比看卡多 2.7 倍」。漏斗只留严格嵌套三级,目录那条路降为并列列。
       # 2026-09-14 随 SQL 改版,三件事:
       #   ① 漏斗加到四级:装机 → 发消息 → QCD(6句) → 累计20句。「20 句」用全历史累计口径
       #      (同 Monetize_free quota wall daily 的额度上限那条线);实测 950 个达标用户里
       #      只有 1 个不是 QCD,故仍可当严格漏斗读。
       #   ② 变现做成三级「点击试用 → 试用生效 → 最终付费」。产品是点 7 天试用、到期才扣费、
       #      期间可随时取消,所以必须分开:点击试用取 subscription_user_state、
       #      试用生效取 subscription 里 in_trial=1 的行、付费取 in_trial=0(到期扣费后才转 0)。
       #      只统计付费功能 2026-09-11 正式上线后才建立订阅关系的用户 —— 上线前那批是测试数据,
       #      product_id NOT LIKE '%admin_test%' 过滤不掉(按分钟级续订周期才识别得出)。
       #      三列量级都是个位数,只标人数不配率,不用于素材间比较。
       #   ③ D1 / D7 由人数改为比率,分母同为装机(与本卡其余比率一致);人数不再单列,
       #      装机就在同一行、乘回去即可。装机量小的素材比率噪声很大(实测有素材
       #      installs=14、D1=7 → 50%),读比率前先看装机列。
       #   ④ 瘦身:删掉目录那条路的四列(点击角色卡 / 装机→点卡 / 点后开聊 / 点卡→开聊)。
       #      它们不是漏斗的级,而「曝光→点击→开聊」已有 9 张 Discover 专卡;留着只会把表撑宽
       #      并持续制造误读。连带本卡不再读 host.firebase_event,跑时从 40~46s 降到 5 秒级。
       dict(top=15, sort="installs",
            cols=[("creative","素材 Creative","text"),
                  ("installs","装机 Installs","int"),
                  ("reached_first_message","发过消息 Any Msg","int"),
                  ("first_message_rate","装机→发消息","pct0"),
                  ("reached_qcd","达成 QCD (6句)","int"),
                  ("qcd_rate","装机→QCD","pct1"),
                  ("reached_20msg","累计 20 句","int"),
                  ("msg20_rate","装机→20句","pct1"),
                  ("purchase_started_users","发起购买 Started","int"),
                  ("trial_effective_users","开过订阅(试用或0.99) Sub Started","int"),
                  ("intro_users","其中 0.99 Intro","int"),
                  ("paid_users","付费 Paid","int"),
                  ("retained_d1_rate","D1 回访率","pct1"),
                  ("retained_d7_window_rate","D7窗 回访率 (5\u20139d)","pct1"),
                  ("first_install_date","首个装机日 First Install","text"),
                  ("last_install_date","末个装机日 Last Install","text")],
            bar=["installs","qcd_rate"],
            note="四级漏斗：装机 → 发消息 → QCD → 累计20句，严格嵌套可直读转化率。变现三级跨源，不可相减。「发起购买」走埋点、滞后 1–2 天，最近两天偏低是数据未到。｜ Four-level funnel by creative. Monetisation columns mix sources; Started is telemetry, lagged 1–2 days.")),
 ]),
 ("② 激活 · Activation", [
   ("activation_funnel_by_adgroup", "激活漏斗分广告组 · Activation Funnel by Ad Group", "funnel",
       # 2026-09-14 随 SQL 改:只统计最新 1 个装机版本(原为最新 2 个)。
       #   note 改为自述式 —— 原文「同激活漏斗」引用的那张卡已下线。
       # 2026-09-15 随 SQL 改:轮数两级+埋点首条 → 累计句数五级,7 级改 9 级(与护栏卡同步)。
       dict(note="九步按 source×广告类型分组，只统计最新一个装机版本，近4版本周、取前8组。前四步是埋点（设备级），后五步是服务端全历史累计句数（账号级），与护栏卡、撞墙卡、Meta 素材卡同口径，可跨卡对照。2026-09-15 由轮数改为累计句数，绝对数跳过一次（同口径实测 ≥3 +17.6%、≥5 +29.5%、≥10 +50.7%），翻历史截图对不上数时先看这条。第2步 Welcome 取自 first_screen_visible，该事件触发位置不稳定，1→2 的落差不全是真流失，连带 4→5 会往上翘。前四步与后五步不同源不同窗，只在各自区段内比较。 ｜ Nine steps by source x ad type. Steps 1-4 telemetry, 5-9 server-side cumulative messages; do not compare across that boundary.")),
   ("activation_guardrail_funnel", "护栏漏斗分版本 · Guardrail Funnel by Version", "funnel",
       # 2026-09-07 随 SQL 改:9 级→8 级(删掉「看到角色目录」),版本来源改用顶层 version,
        #   选版本规则改为「人数前 6 + 强制含最新版」——原按版本号取最新 7 个,把人数最多的
        #   2.6.1(5,147 人)排除在外了。
        # 2026-09-15 随 SQL 改:轮数三级 → 累计句数五级,8 级改 9 级。
       #   绝对数会跳一次(≥3 +17.6% / ≥5 +29.5% / ≥10 +50.7%),是口径变化不是数据错。
       dict(gsort="version", note="八步按版本分组。前两步是埋点（设备级、近30天），后六步是服务端全历史累计句数（账号级），与 adgroup 卡、撞墙卡、Meta 素材卡同口径。1→2 跨源跨窗可能往上翘，2~8 步严格嵌套。小样本版本波动大，先看第一行人数。2026-09-20 删掉 onboarding 三步（3.1.1 起已从产品移除）。｜ Eight steps by app version. Steps 1-2 telemetry, 3-8 server-side cumulative messages. Onboarding steps dropped 2026-09-20.")),
   ("activation_first_day_crosstab", "新用户第一天交叉表 · First Day — Crosstab", "table",
       # 2026-10-26 新建(Metabase 卡 442)。WW46 D-456「新用户第一天」整段重做的第一环,
       #   Javier 牵头、Kang 配合;Kang 要据此查 3.7.0 起首屏到选角色多出的那一步(D-454)。
       # 🛑 原稿带 Metabase 模板变量 {{date_from}}/{{date_to}},管线不传参跑不了,
       #   上线时改成固定近 14 天滚动窗口。卡头记了这件事,别再加回模板变量。
       dict(top=40,
            cols=[("version","版本 Version","text"),
                  ("source","来源 Source","text"),
                  # 2026-10-28 新增一列。加在 source 后面是因为它**限定 source** ——
                  # 同一个渠道的设备,JS 起没起来后面每一级的表现完全不同。
                  ("js_ok","JS 起没起来 JS Boot","text"),
                  ("saw_launch_wall","启动墙 Launch Wall","text"),
                  ("saw_first_msg_gate","首条消息墙 First-Msg Gate","text"),
                  ("first_host_type","首个角色 First Host","text"),
                  ("devices","设备数 Devices","int"),
                  ("pick_rate","打开→选角色 %","d1"),
                  ("d1_msg5_rate","首日≥5条 %","d1"),
                  ("d1_return_rate","有效D1 %","d1")],
            bar=["devices","pick_rate"],
            note="一行 = 版本 × 来源 × 是否见过启动墙 × 是否撞过首条消息墙 × 首个角色类型,近 14 天、每格 ≥20 台才列出。🛑 **这张卡是把三件事拆开看,不是给出归因** —— 3.7.x 放量、启动墙上线、10-17 起无归因流量三件同期叠在一起(D-454)。🛑 版本取 **first_open** 那条,不取 onboarding_started(该事件近两周只剩 61 行,拿它归版本会把绝大多数设备归成「查不到」)。🛑 前两级是**埋点设备级**,后两级是**服务端账号级**,接不上账号的设备记「未达」不从分母剔除,**跨这条线不要相除**。🔴 **2026-10-28 换了来源判法** —— 由 `attribution_received`(JS 发的)改为 `firebase_campaign.source`(SDK 原生事件,Play Install Referrer 下发,JS 没跑也有),判据与「渠道启动成功率 · Channel Start Success」**逐字一致**。起因:AN 渠道近一周有 **985 台装了却从没进过 App**,旧判法把它们全归进 `others` 一格,把那一格的比率整体稀释;剔掉之后广告设备次日回来 **4.6% → 8.9%**。⇒ **跨 10-28 不要把本卡的来源分布前后对比**(`others` 已更名为「无来源记录」,新增 AN / (not set),Google 改称「自然量 Organic」,取值集合整个变了)。🛑 **「无来源记录」= 连 firebase_campaign 事件都没有的设备,不是 CityPLX**(那些用户不发 SoulMap 埋点,实测 325 个账号 0 条);它和 `(not set)` 也不是一回事 —— 后者是 SDK 发了事件但归因为空。🛑 首条消息墙(first_message_gate,10-22 16:16 起)截至 10-26 只有 6 次/2 人,量小读不出,单列是因为它弹在「选了角色、还没发第一条」那个位置,放量后会搅乱这一段归因。｜ Crosstab of day-one behaviour by version x source x walls x first host type.")),
   # 🛑 2026-10-22 摘牌(用户决定):这里原有两张卡 ——
   #     「Onboarding 流失 · Onboarding Dropoff」(Metabase 卡 335,原在 ② 激活)
   #     「Silent 会话率 · Silent-Session Rate」(Metabase 卡 352,原在 ④ 对话)
   #   处理方式:**只把 dashcard 从 Metabase 看板上摘掉,卡没有归档** ——
   #     卡 352 原在看板 18;卡 335 在看板 18 和 24 **两个**上都有,都摘了。
   #     两张卡仍在 collection 里,能单独打开查,只是不在任何看板上。
   #   ⇒ 所以抓数侧**不用加 SKIP_CARDS**:fetch 是遍历看板的 dashcard,
   #     卡不在看板上就自然不会被抓到,写进 SKIP_CARDS 反而是条死配置。
   #   🛑 恢复的时候:先把 dashcard 加回 Metabase 看板,再把卡定义写回这里。
   #     看板摘牌前的完整配置备份在
   #     scratchpad/dashboard_18.bak_20261022.json 和 dashboard_24.bak_20261022.json
   # 2026-09-08 下线「新版 Onboarding Anchor 分布」(activation_onboarding_from_2.5.0)。
   #   SQL 备份在 soulmap_dashboard/Metabase/old/old_Activation_onboarding from 2.5.0.sql
 ]),
 ("③ 留存 · Retention", [
   ("retention_d1_drop_diagnosis", "有效D1与投入率下滑定位 · D1 & Engagement Drop", "table",
       # 2026-10-22 新建(Metabase 卡 432)。对应 Michael 10-21 反馈 P0 第三项。
       # 🛑 分母是「当天注册的账号」(D-151),**不是装机设备** —— 10-17 起有大批设备
       #   拿不到 uid、根本进不了 soul_map.user(见 OPPO/Realme 那条)。
       dict(top=80,
            cols=[("date","日期 Date","text"),("dim","维度 Dim","text"),
                  ("dim_value","维度值 Value","text"),
                  ("new_users","注册账号 New","int"),
                  ("retained_d1","次日发消息 D1","int"),("d1_rate","有效D1 %","pct1"),
                  ("engaged_5plus","首日≥5条 Engaged","int"),("engaged_rate","投入率 %","pct1")],
            bar=["new_users","d1_rate"],
            note="🛑 **实测结论:不是分母被异常装机撑大,也不是流量质量** —— 分子(次日发消息)从 32~34 到 22~33 基本不动,是分母从 240 涨到 436;三个付费来源各自腰斩(Facebook 8.8→4.9、AudienceNet 8.9→4.3、Instagram 14.0→10.4),而自然量只从 6.3 掉到 5.4。🛑 10-13/14 那个 13~14% 的高点是**那两天注册只有 240 人**造成的,不是真的变好。🛑 投入率门槛是 **≥5 条**,和北极星的 >3 条不是一回事。🛑 最后一天 D1 必然偏低(次日没过完)。🔴 `(查不到版本)` 那组每天 18~35 人、D1 和投入率全是 0,会把 overall 拉低。｜ Not a denominator artifact: all three paid sources halved while organic barely moved.")),
   ("retention_d1_effective", "有效留存 D1 · 账号级 · Effective Retention D1 (account)", "long_dim",
       # 🛑 2026-10-27 卡头补口径(口径清单 ② / ⑥)。SQL 没动,只写清楚这是哪一套。
       dict(rate=("messaged_users","new_users"), **RETENTION_DIMS,
            note="🛑 **账号级**:次日发过消息的账号 ÷ 当天注册的账号,只算用户自己发言,打开 App 不算。🛑 **不要和「留存 D1(设备级)」相比** —— 那张的分母是装机设备、分子是开 App,两者差 1.4 倍。🛑 **也不要和 D3 / D7 连成一条曲线**,那两张是设备级的。⚠️ 实测「发了消息但没记启动」有 43 人、「启动了没发消息」有 129 人,**两张表不同源**,所以取交集那套会系统性低估。🛑 北极星用哪一套待 Javier 拍板(口径清单第 ② 条)。｜ Account-level D1; not comparable with the device-level card or with D3/D7.")),
   ("retention_d3", "留存 D3 · Retention D3", "long_dim",
       dict(
            note="第3天开App的设备 ÷ 装机当天的新设备 \uff5c Devices reopening on day 3 \u00f7 new devices that installed that day",rate=("retained_users","new_users"), **RETENTION_DIMS)),
   ("retention_d7", "留存 D7 · Retention D7", "long_dim",
       dict(rate=("retained_users","new_users"), **RETENTION_DIMS,
            note="第7天开App的设备 ÷ 装机当天的新设备;末尾几天观察窗未满 \uff5c Devices reopening on day 7 \u00f7 new devices that installed that day; the trailing days\u2019 window hasn\u2019t closed")),
   ("retention_push_funnel", "推送权限与注册 · Push Permission & Registration", "table",
       # 2026-10-19 由漏斗图改表格。原四级「弹窗→授权→token→注册」**不是嵌套关系**:
       #   实测 4,848 台(占有 token 总数的 64%)没授权通知权限却照样拿到了 FCM token ——
       #   Android 上 token 不依赖通知权限,app 启动就能拿。画成漏斗必然"掉下去又涨回来"。
       #   现拆成两条各自嵌套的线并排:左=权限(弹窗→授权) 右=推送能力(token→注册)。
       # 🛑 **两条线之间不要相除**。
       dict(top=10,
            cols=[("app_version","版本 Version","text"),
                  ("prompt_devices","弹过权限窗 Prompted","int"),
                  ("granted_devices","授权通过 Granted","int"),
                  ("granted_rate","授权率 Grant %","pct1"),
                  ("token_devices","拿到 token Token","int"),
                  ("registered_devices","服务端注册 Registered","int"),
                  ("registered_rate","注册率(÷token) Reg %","pct1"),
                  ("token_without_grant","没授权但有token No-Grant Token","int"),
                  ("token_without_grant_rate","占有token的 %","pct1")],
            bar=["prompt_devices","granted_rate"],
            note="🛑 左右两组是**两条互不嵌套的线**,不要跨组相除 —— FCM token 不依赖通知权限,实测 69~70% 拿到 token 的设备并没有授权。左组分母=弹过窗的设备;右组「注册率」分母=拿到 token 的设备。｜ Two independent tracks, not one funnel: FCM tokens do not require notification permission.")),
   ("retention_push_delivery", "推送发送与送达 · Push Send & Delivery", "table",
       # 2026-10-19 换数据源 + 漏斗改表格,**改前改后不可比**。
       #   原卡用客户端埋点做四级漏斗,但实测队列只剩 31~42 台、分子全是个位数。
       #   根因不是埋点漏了,是**推送本身几乎没在发**:服务端近 14 天 2,051 次尝试里
       #   NO_DEVICE_TOKEN 占 64%,根本没发出去。改成服务端口径把这个瓶颈摆出来。
       # 🛑 不给「收到÷发出」:服务端发出与客户端收到会跨日,逐日相除会得出 160% 这种数。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("attempts","尝试 Attempts","int"),
                  ("no_token","没 token No Token","int"),
                  ("no_token_rate","没 token %","pct0"),
                  ("fcm_attempted","实际发出 Sent","int"),
                  ("dedup_skipped","去重跳过 Dedup","int"),
                  ("tokens_accepted","FCM 接受 Accepted","int"),
                  ("tokens_invalid","无效 token Invalid","int"),
                  ("tokens_invalid_rate","无效 %","pct0"),
                  ("client_received","客户端收到 Received","int"),
                  ("client_opened","点开 Opened","int")],
            bar=["attempts","no_token_rate"],
            note="🛑 左边七列是**服务端**口径(次数),右边两列是**客户端**口径(设备去重),两边不同源、而且发出与收到会跨日 —— **不要相除**,只做量级对照。🛑 最大的瓶颈是「没 token」常年 64~88%,和「无效 token」(10-19 达 49%)是同一问题的两面。🛑 20261011 客户端埋点整天空白,那天的 0 是 ETL 缺口不是业务为 0。｜ Left = server-side counts, right = client-side devices; different sources and they cross days. Do not divide across."))
 ]),
 ("④ 对话 · Chat", [
   ("chat_character_type_ab_funnel", "角色类型 A/B 漏斗 · Character Type A/B Funnel", "table", dict(top=4, cols=[("group_name","分组 Group","text"), ("entered_users","进过聊天页 Entered","int"), ("replied_users","回复 Replied","int"), ("replied_rate","回复率","pct1"), ("msg6_users","累计≥6句","int"), ("msg6_rate","6句率","pct1"), ("msg20_users","累计≥20句","int"), ("msg20_rate","20句率","pct1"), ("trial_effective_users","开过订阅(试用或0.99) Sub Started","int"),
                  ("paid_users","付费 Paid","int")], bar=["entered_users","msg20_rate"], note="A = 真实 realistic，B = 幻想 fictional。按「进过哪类角色的聊天页」分组，每台设备只进一组、四行可相加；全库 16.2% 的用户两类都用过，故混用组单列。分母用客户端埋点（chat_entry_shown，2026-09-04 上线，本卡实际起点为该日）——服务端只在用户开口后才落库，拿不到「进了但没开口」的人。6句/20句 = 全历史累计全部用户消息、不限 host，与撞墙卡、护栏卡、Meta 素材卡同口径。试用/付费靠「进过哪类聊天页」反推（订阅表无角色维度），个位数、不配比率；没进过聊天页的订阅用户不在任何一行，故两列合计小于付费漏斗卡，是预期不是漏数。「未知类型」多来自会话列表入口（老用户回访），深度天然偏高，不要与前三行并列比较。｜ A = realistic, B = fictional. Grouped by which type's chat page was entered; rows are additive. Trial/paid are inferred and single-digit.")),
   # —— 参与广度 · Engagement breadth ——
   ("chat_engaged_new_user_rate", "新用户投入率 · Engaged New-User Rate", "rate",
       dict(rate=("engaged_new_users","new_users"),
            note="首日发≥5条的新用户 ÷ 当天注册的账号数 ｜ New users sending 5+ messages on day 0 ÷ accounts registered that day"
                 "比「新用户数」卡的装机数多约 15%，两张卡的「新用户」不是同一批人。"
                 "by country 里的 unknown 是账号接不回埋点设备(约 23%)，不是不知道国家 ｜ "
                 "New users sending \u22655 messages on day 0 \u00f7 accounts created that day. "
                 "Note: the denominator counts server-side account creations (94.5% auto-created guests), "
                 "~15% above the install count used by the New Users card \u2014 the two cards do not "
                 "count the same people. In the by-country view, unknown means the account cannot be "
                 "linked back to an instrumented device (~23%), not that the country is unknown.",
            rollup={"country": 20},
            dims=[("overall","Overall",None),("country","by country","country")])),
   # 2026-10-22 摘牌:「Silent 会话率 · Silent-Session Rate」(卡 352),见 ② 激活区那条注释。
   # —— 参与深度 · Engagement depth ——
   ("chat_qcd_v1_daily", "QCD 日度 · Quality Conversations per Day", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct1", min_vol=0,
            dimorder=["overall","host_type"],
            dimlabels={"overall":"Overall","host_type":"by host type"},
            # slorder 固定线序:角色卡在前(它才是 North Star),系统行垫底
            slorder={"host_type":["角色卡","reception","SoulMap系统行"]},
            note="QCD = 同一天对同一个 Host 发≥6条非空消息的账号,占当天启动过 App 的账号数;按 host 类型分三档 ｜ QCD = accounts sending 6+ non-empty messages to the same host in a day, over accounts that launched the app that day; split by host type")),
 ]),
 ("⑤ 语音 · Voice", [
   ("snapshot_voice_text_share", "语音与文字使用占比 · Voice vs Text Share", "table",
       dict(top=40,
            cols=[("date","日期 Date","text"),
                  ("country","国家 Country","text"),
                  ("users","用户 Users","int"),
                  ("voice_users","语音用户 Voice Users","int"),
                  ("voice_user_pct","语音用户占比 %","d1"),
                  ("msgs","消息 Msgs","int"),
                  ("voice_msgs","语音消息 Voice Msgs","int"),
                  ("voice_msg_pct","语音消息占比 %","d1")],
            bar=["users","voice_user_pct"],
            note="一行一天×一个国家。🛑 两个占比的分母不是同一个(一个是人、一个是消息),不要互相换算,也不要画成饼图。本卡替代原「Chat_voice text ratio」,那张没有国家维度。｜ One row per day x country. The two shares have different denominators.")),
   ("voice_arm_comparison", "分桶对照 · Randomized Arm Comparison", "table",
       dict(cols=[("seq","#","int"),
                  ("metric","指标 Metric","text"),
                  ("metric_en","Metric (EN)","text"),
                  ("holdout_k","对照 分子 k","int"),
                  ("holdout_n","对照 分母 n","int"),
                  ("holdout_pct","对照 %","d1"),
                  ("holdout_lo","对照 区间下 lo","d1"),
                  ("holdout_hi","对照 区间上 hi","d1"),
                  ("treat_k","实验 分子 k","int"),
                  ("treat_n","实验 分母 n","int"),
                  ("treat_pct","实验 %","d1"),
                  ("treat_lo","实验 区间下 lo","d1"),
                  ("treat_hi","实验 区间上 hi","d1"),
                  ("readable","读得出? Readable","text")],
            note="🛑 先看最后一列 readable —— 两边区间重叠时这一行读不出差异,别把百分比的高低当结论。分子分母都列出来了,比率要连着分母一起看。｜ Check the `readable` column first; overlapping intervals mean no readable difference.")),
   ("voice_latency_miss", "等待与漏回 · Latency & Miss Rate (Server)", "table",
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("voice_user_msgs","语音消息 Voice Msgs","int"),
                  ("miss_n","漏回 Missed","int"),
                  ("miss_pct","漏回率 %","d1"),
                  ("pending_n","待回 Pending","int"),
                  ("asr_p50_s","ASR 中位(秒)","d1"),
                  ("first_audio_p50_s","首个音频 中位(秒)","d1"),
                  ("wait_after_asr_p50_s","ASR后等待 中位(秒)","d1"),
                  ("over_10s_n",">10 秒 Over 10s","int"),
                  ("over_10s_pct",">10 秒 %","d1")],
            bar=["voice_user_msgs","miss_pct"],
            note="时延一律给中位数(p50),不给均值 —— 这类分布尾巴很长,均值会被少数极慢的拖走。｜ Latency is reported as median; the distribution has a long tail.")),
   ("voice_playback_reasons", "播放结果与没出声的原因 · Playback & No-Audio Reasons (Client)", "table",
       dict(top=25,
            cols=[("grp","分组 Group","text"),
                  ("grp_en","Group (EN)","text"),
                  ("item","项 Item","text"),
                  ("item_cn","项(中) Item CN","text"),
                  ("events","次数 Events","int"),
                  ("users","人数 Users","int"),
                  ("pct_within_grp","组内占比 %","d1")],
            bar=["events"],
            note="🛑 两组各自成一块,组内占比的分母是本组 —— 不要跨组相加或相除,也不要画成饼图。｜ The two groups have different denominators; do not combine them.")),
 ]),
 ("⑥ 角色 · Characters", [
   ("foryou_community_share", "For You 里社区角色占比 · Community Share in For You", "table",
       # 2026-10-27 新建(Metabase 卡 448)。起因:2026-10-26 起服务端把社区角色混进 For You,
       #   而算法的 /ai/catalogue/slate 只从自有角色里选、以后也不会加(Javier 回 483/208)。
       #   不拆出来会把服务端的编排算到算法头上。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("impressions","For You 曝光 Impressions","int"),
                  ("community_impressions","其中社区角色 Community","int"),
                  ("community_pct","社区占比 %","d1"),
                  ("own_taps","自有点击 Own Taps","int"),
                  ("own_ctr_pct","自有 CTR %","d1"),
                  ("community_taps","社区点击 Community Taps","int"),
                  ("community_ctr_pct","社区 CTR %","d1")],
            bar=["impressions","community_pct"],
            note="🛑 判据是 `card_id` 以 `user:` 开头。⚠️ **建卡时(10-27)曝光埋点里一条 `user:` 都没有** —— 近 10 天 For You 每天 1.1~2.3 万次曝光,社区角色 0 条(10-26 当天也是 0)。两种可能:① 服务端的混入 10-27 才真正生效(埋点 **T+1**,建卡时 10-27 的数还没到);② 客户端曝光埋点里社区角色的 `card_id` 不带 `user:` 前缀,那判据得改。🛑 **这一列持续为 0 不等于「没混入」**,要先排除第 ② 种 —— 对照办法:同一天 `soulmap_chat_history` 里 `user:` 开头的 host 近 7 天有 1,847 条消息 / 104 人,**人确实在聊**,聊得到却曝光不到就是埋点问题。🛑 10-26 之后 `discover_*` 那组卡(角色表现榜 / 每日 CTR / 点击去向 / 点击位次)**全都混了两个来源**,趋势跨这一天不可比。｜ Splitting server-side community characters out of the algorithm's For You slate.")),
   ("host_three_metrics", "每个角色三个数 · Per-Host Engage/Depth/Return", "table",
       # 2026-10-22 新建(Metabase 卡 437)。对应 Michael 10-21 反馈 P1 第 7 项(D-181/D-182)。
       dict(top=60,
            cols=[("host_name","角色 Host","text"),("char_class","类型 Class","text"),
                  ("new_chatters","首次聊 New","int"),
                  ("engaged_gt3",">3条 Engaged","int"),("engage_rate","入戏率 %","pct1"),
                  ("deep_ge10","≥10条 Deep","int"),("deep_rate","聊深率 %","pct1"),
                  ("heavy_ge100","≥100句 Heavy","int"),("heavy_rate","≥100句 %","pct1"),
                  ("returned","24~48h回来 Returned","int"),("return_rate","回来率 %","pct1")],
            bar=["new_chatters","deep_rate"],
            note="🛑 **三个门槛都和现有卡不同,不可直接对**:入戏用 **>3 条**(北极星 D-181),而 `373 新用户投入率` 用 ≥5 条;聊深用 **≥10 条**,而 `387 角色QCD与回访` 用 QCD 6 句;回来用 **24~48 小时**窗口,而 387 按自然日。🛑 A/B 类判据是 `character_type`(realistic / fictional),**`host_type='ai_expert'` 不是 A 类**。🛑 分母是「当天**第一次**和该角色聊的人」,同一人对同一角色只进一次。🛑 不足 10 人的角色不出,避免长尾噪声。｜ All three thresholds differ from existing cards — do not cross-compare.")),
   ("discover_character_leaderboard", "角色表现榜 · Character Leaderboard", "table",
       dict(top=20, sort="ctr",
            # host_id 排最后:它最长、也最不常看,放前面会把关键列挤出可视区
            cols=[("character","角色 Character","text"),      ("tile","场景 Tile","text"),
                  ("first_seen","首次曝光 First Seen","text"), ("impressions","曝光 Impressions","int"),
                  ("taps","点击 Taps","int"),                 ("ctr","CTR","pct1"),
                  ("chatted","开聊 Chatted","int"),           ("chat_rate","点击→开聊 Tap→Chat","pct0"),
                  ("deep_rate","曝光→深聊 Impr→Deep","pct1"), ("host_key","host_id","text")],
            bar=["ctr","chat_rate","deep_rate"],
            note="🔴 **2026-10-29 口径变更:`foryou` 加进了曝光白名单** —— 此前白名单是 `all/everyday/fantasy`,而 **`all` 早已恒为 0**(近 21 天只有 11 次),等于只算了 `everyday`+`fantasy`,**占全部角色卡曝光的 16.4%**(10-27)。改后分母 2,236 → 12,533(5.6 倍),CTR 3.49% → 4.37%,波动由 2.26~5.07% 收窄到 4.12~4.58%,与服务端独立算出的 foryou CTR 4.58% 相互印证。🛑 **跨 10-29 不要前后对比**。🛑 `search` 有意不加(搜索带意图,与浏览不同质)。🛑 **2026-10-29 窗口由近 30 天缩到近 14 天**(与另外三张 Discover 卡一起),原因是四张卡压着 60 秒网关超时、推上去全部 504;`coverage` 实测缩窗口后 63.6s → 16.5s。🛑 **埋点侧和服务端侧一起缩** —— 本卡两个窗口都动了,只缩一个会让分子分母不同盘。⚠️ **曝光门槛仍是 ≥50 没动,实测也不需要动** —— 加 `foryou` 的 5.6 倍曝光盖过了窗口减半,过门槛的角色由 **529 增到 705**。但「窗口内出现过的角色」由 924 降到 773,那是窗口短了长尾角色没露面,**不是角色下架**,两个数方向相反别混着读。近14天累计,每个角色一行,仅列曝光≥50 的角色;曝光按(用户×角色×日)去重 ｜ Last 14 days (was 30), one row per character, characters with ≥50 impressions only; impressions deduped per user × character × day")),
   ("discover_character_qcd_and_retention", "角色 QCD 与回访 · Character QCD & Return", "table",
       dict(top=20, sort="chatted_users",
            cols=[("character","角色 Character","text"),
                  ("chatted_users","聊过的人 Chatted Users","int"),
                  ("reached_qcd","达成 QCD","int"),
                  ("qcd_rate","开聊→QCD","pct1"),
                  ("retained_d1_app","D1 回 App","int"),
                  ("retained_d1_same_host","D1 回同一角色","int"),
                  ("retained_d7_window_same_host","D7窗 回同一角色","int"),
                  ("first_chat_date","首次对话日 First Chat","text"),
                  ("host_key","host_id","text")],
            bar=["chatted_users","qcd_rate"],
            note="🛑 **2026-10-29 聊天窗口由近 30 天缩到近 14 天**,与另外四张 Discover 卡对齐(本卡不是性能问题,缩它是为了窗口一致,否则两边的角色没法比)。**代价是上榜角色由 82 个降到 41 个** —— 门槛仍是 ≥20 人聊过,窗口短了过门槛的角色就少一半,**不是角色变差,也不是角色下架**。🔴 **D7 那一列受影响更大**:它看的是首次对话后第 5~9 天是否又回来找同一角色,首次对话落在最近 9 天内的队列这个窗口还没走完、天然判为「没回来」—— 这批人占比由 9/30(**30%**)升到 9/14(**64%**)。⇒ **D7 只能用来比角色之间的相对高低(所有角色受同样影响),不能当绝对回访率读,也不能和 10-29 之前的数比。**🛑 跨 10-29 不要把本卡前后对比。各角色的开聊 → QCD → 回访;仅列被 ≥20 人聊过的角色 ｜ Chat → QCD → return per character; only characters chatted by 20+ people. Window shortened 30d → 14d on 2026-10-29.")),
 ]),
 ("⑦ 变现 · Monetization", [
   ("energy_waterfall", "能量系统瀑布表 · Energy Waterfall", "table",
       # 2026-10-27 新建(Metabase 卡 444)。建卡时 soulmap_energy_offer_event 为 0 行。
       # 🔴 2026-10-29:**不再是壳** —— 能量系统 10-28 14:32:20 已上线,本卡出数了。
       #   empty_ok 仍然留着,但理由变了:现在一天只有个位数档位行,
       #   某一天一条都没有是完全可能的,仍不该让卡从看板上消失、也不该算进「缺 N」。
       dict(top=60,
            cols=[("date","日期 Date","text"),
                  ("tier","档位 Tier","text"),
                  ("arm","分组 Arm","text"),
                  ("reached_users","到达人数 Reached","int"),
                  ("accepted_users","接受 Accepted","int"),
                  ("declined_users","看了没点 Declined","int"),
                  ("cancelled_users","付款单取消 Cancelled","int"),
                  ("cancelled_within_3s_users","其中3秒内 <3s","int"),
                  ("accept_pct","接受率 %","d1")],
            bar=["reached_users","accept_pct"],
            empty_ok=True,          # 见 table 分支:能量系统还没上线,零行是预期不是故障
            note="🔴 **2026-10-29:本卡不再是壳** —— 能量系统 **2026-10-28 14:32:20** 上线(`soulmap_energy_lot` 第一行),卡头原来写的「现在为空是预期」已过时。实测 10-29:L1 曝光 41 次 / 11 人、L1 接受 1、L2 接受 1。🔴 **同日补了剔除** —— 建卡时表是空的,一条剔除都没写;现在加上 CityPLX、四个测试号和**两个沙盒号 `74377` / `74592`**,**行数由 4 降到 3**(被剔掉的正是「L2 接受 1」那条,它是沙盒号 74377)。另把下界加到 `2026-10-28 14:32:20` —— 30 天窗在系统只活了两天时没有意义。🛑 **影子计费 `soulmap_energy_shadow_charge`(28.5 万行)不扣用户的钱、不是上线**,本卡不读它。✅ **建卡时 SRM 正常**:`energy_v1` 分组 2026-10-26 12:08 起,control 90 / energy 365 = **19.8%**(设计 20%)。**上线后每天先看这个再看别的,分组偏了后面所有对比都不成立**。🛑 **「看了没点」(declined)才是拒绝;「付款单取消」(cancelled)是点了订阅、进了商店页又自己取消,不算拒绝** —— 混在一起会把「不想要」和「想要但没付成」算成一回事。🛑 **分组表里的 arm='energy' ≠ 真的进了能量系统**,还要满足注册时间 / 客户端 build / 国家三个条件,两组必须按同样条件筛完再比。🔴 **印度和其它国家现在拆不开** —— 服务端判国家用的是首登 IP 的 GeoIP、不是 `user.country_code`,那一列库里没有,要请服务端补。🛑 **付款方式拿不到**,Play Billing 只告诉客户端「用户取消了」,按付款方式拆只能看 Play Console。🛑 **「其中3秒内」单列**:3 秒内关掉的人根本没看商店页,更像误触或立刻反悔,和「进去看了价格再退出来」是两回事。⚠️ **两处还没做,等上线后补**:① 分母还没限定「新注册 × 新客户端」(客户端 build 白名单还没定);② 需求里的时间轴(L1 看当天 / L2 第 2 天 / L3·L4·订阅 第 3~5 天)**没写死进 SQL** —— 本卡是逐日 × 档位的原始形态,那条时间轴先当读法用。｜ Shell card; empty until the energy system ships.")),
   ("energy_ledger", "能量流水 · Energy Ledger", "table",
       # 2026-10-29 新建(Metabase 卡 451)。出处:埋点需求 §3「能量从哪来、花到哪」。
       # 🛑 一行 = 一天 × 方向 × 来源/用途。入账 6 种、扣费 4 种,折线画十条贴地的线没法读;
       #   而且入账和扣费量纲一样方向相反,叠一张图上会互相抵消。
       dict(top=60,
            cols=[("date","日期 Date","text"),
                  ("direction","方向 In/Out","text"),
                  ("source","来源·用途 Source","text"),
                  ("txn_count","笔数 Txns","int"),
                  ("users","人数 Users","int"),
                  ("energy","能量 Energy","int"),
                  ("energy_per_user","人均能量 per User","d1"),
                  ("chat_msgs_equiv","折合聊天条数 Msgs","d1")],
            bar=["energy","users"],
            note="🔴 **聊天单价一天内改过两次**:① 2 能量/条(10-28 14:32:20 起)② **4(10-29 12:21:47 起,现在线上)** ③ 1(**待定**,切点是配置项 `energy.unit_v2_at`,由 Javier 定)。⇒ 「折合聊天条数」按**当时**的单价折算,跨段可比;**第三段一旦配上,SQL 里的 CASE 必须回去加一段**,否则第三段条数会被按 4 低估到四分之一。🛑 **这一列只对「聊天」算** —— 语音 / 🔊 / 创建角色的单价三段各不相同(30·50 → 20·25 → 5·5,创建 5/20 → 1/5),折了反而更容易误读,所以只给原始能量数。🛑 **`改价补偿` 和 `换单位` 两行不算收入也不算购买**,单独成行,不要并进「购买」。🛑 **已剔两个沙盒号**:`74377`(沙盒购买)、`74592`(沙盒订阅 —— 台账 §九十七 记的「首个能量订阅发 15,000」实为沙盒,生产一笔都没有);另剔 CityPLX 和四个测试号。🛑 **起点是 2026-10-28 14:32:20**,不是任何一个 3.9.0 提交日;影子计费 `soulmap_energy_shadow_charge`(28.5 万行)**不扣用户的钱、不是上线**,本卡不读。🔴 **真实成本**:聊天 **$0.0108/条**(含记忆、理解等后台调用,不是 $0.0076),重度用户 $0.0125;语音回复 $0.0127、语音消息 $0.0257、创建角色约 $0.08。｜ Energy in/out by day and source. Chat unit price changed twice on 10-28/10-29; the msgs column normalizes for it.")),
   ("energy_wallet_layers", "能量钱包三层 · Energy Wallet Layers", "table",
       # 2026-10-29 新建(Metabase 卡 452)。出处:产品玩法 §15.2。
       # 🛑 三层**不是上下级,是三种过期规则**,所以必须按层出行、不能合计成一个余额。
       dict(top=60,
            cols=[("date","日期 Date","text"),
                  ("layer","层 Layer","text"),
                  ("source","来源 Source","text"),
                  ("sku","商品 SKU","text"),
                  ("lots","笔数 Lots","int"),
                  ("users","人数 Users","int"),
                  ("granted_energy","发放能量 Granted","int"),
                  ("remaining_energy","剩余 Remaining","int"),
                  ("used_energy","已用 Used","int"),
                  ("used_pct","已用占比 Used %","d1"),
                  ("first_purchase_lots","其中首购 First Buy","int"),
                  ("next_expiry","最早到期 Next Expiry","text")],
            bar=["granted_energy","used_pct"],
            note="🛑 **三层的过期规则完全不同,`剩余` 不能跨层相加当成「用户还有多少能量」**:`买来的` 永不过期 · `订阅额度` **月底清零** · `赠送` 14 天过期。🔴 **实测 2026-10-29:`最早到期` 这一列读不出东西** —— 126 条 `赠送` 行的 `expires_at` **全部为 NULL**(规则说 14 天过期,库里没落下时间);`买来的` 4 行也是 NULL(**这是对的**,永不过期);唯一有值的那条 `订阅额度` 是沙盒行(03:07:49 → 03:12:45,5 分钟)。**这不代表赠送能量不会过期**,过期可能是读取时按 `created_at` 现算的 —— **要和 liwen 确认,确认前不要拿这列回答「有多少赠送能量快到期」**。🛑 **以后不能从商品名推能量数** —— 商店商品已改成不带数字的 `Energy Pack S/M/L/XL/XXL`,只能查配置或读 `发放能量`。🛑 **`其中首购` 只能当近似** —— 服务端分不清是从聊天内阶梯卡还是充值页买的(两者用同一个商店商品)。🛑 剔除同「能量流水」卡。｜ Three wallet layers have different expiry rules; do not sum `remaining` across them.")),
   ("energy_winback_list", "付费流失召回 · Energy Win-back List", "table",
       # 2026-10-29 新建(Metabase 卡 453)。出处:倡议书 §四「因付款失败走掉的入戏用户」。
       # 🛑 名单是**一次性批次**(404 行全写在 2026-10-27 10:07:28),不是日流水,
       #   所以本卡不设滚动窗口、也不按天画线。
       dict(top=30,
            cols=[("date","名单日 Listed","text"),
                  ("grp","分组 Group","text"),
                  ("listed_users","名单人数 Listed","int"),
                  ("granted_users","真发了 Granted","int"),
                  ("granted_pct","发放率 Granted %","d1"),
                  ("returned_to_chat_users","回来聊了 Returned","int"),
                  ("returned_pct","回来率 Returned %","d1"),
                  ("paid_subscription_users","回来买订阅 Sub","int"),
                  ("paid_consumable_users","回来买消耗型 Consumable","int"),
                  ("distinct_last_hosts","涉及角色数 Hosts","int")],
            bar=["listed_users","returned_pct"],
            note="🔴 **名单建好了,触达还没跑起来** —— 404 人里**只有 1 人真的发了能量**(A 组 392 人一个都没发)。几乎全零**是结论不是故障**。🛑 **名单生成于 2026-10-27 10:07:28,早于能量系统上线(10-28 14:32:20)** —— 它是预先算好的名单,不是每天滚动产生的。🛑 **`分组` 是名单自带的,不是随机分桶** —— 拿它谈因果前必须先确认分组规则和依从率,两者现在都没有文档;而且 B 组只有 12 人,任何比率都读不出,**必须连绝对人数一起看**。🔴 **召回赠送额度是 1,000 不是文档写的 10**(服务端按旧版 App 上的数发,新版普及后才改回,而「普及」的标准还没定)—— 但**实测那唯一 1 笔发的是 20**,三个数都对不上,**要和 liwen 对**。⇒ 🛑 **算召回成本不要按规则推算,直接读 `soulmap_energy_lot.amount`。**🛑 「回来聊了」只数用户**自己**发的消息(`role='user'`)—— 用 host 侧会把「被默认助手群发了开场白」读成「回来聊天了」,虚高约 2.5 倍。｜ The win-back list exists but outreach has not run: 1 of 404 actually received energy.")),
   ("energy_free_voice_trial", "免费语音体验 · Energy Free Voice Trial", "table",
       # 2026-10-29 新建(Metabase 卡 454)。出处:产品玩法 §15.5 末「免费语音体验单独计数,不用能量」。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("kind","种类 Kind","text"),
                  ("uses","次数 Uses","int"),
                  ("users","人数 Users","int"),
                  ("uses_per_user","人均次数 per User","d1"),
                  ("refunded_uses","退回 Refunded","int")],
            bar=["uses","users"],
            note="🔴 **免费语音体验不用能量,是单独计数的**(4 次语音回复 + 4 次 🔊,走 `soulmap_energy_trial_use`,不进 `soulmap_energy_txn`)⇒ 🛑 **不要把这张卡的次数和「能量流水」里的语音 / 🔊 扣费相加** —— 那是免费额度用完**之后**才开始扣的,两者是前后两段,不是同一批人同一件事。🛑 **免费 4 次是按人按种类算的**,所以 `人均次数` 接近 4 就说明这批人快用完了,该去看后面的付费转化 —— 实测 10-29「语音回复」人均正好 **4.00**(3 人全部用满),「语音消息」人均 2.00(32 人)。🛑 **重听免费、生成失败不收费**,所以这里的「次数」是计入免费额度的次数,**不等于用户听到声音的次数**。🛑 首行在 **10-29 01:29:50**,比能量系统本身晚约 11 小时 —— 不是漏数,是当天才有人用到。`退回` 实测全是 0,0 是结论不是故障。｜ Free voice trial is counted separately and does NOT consume energy; do not add it to the voice/TTS rows in the ledger card.")),
   ("attribution_adjust_recon", "Adjust 发送对账 · Attribution Reconciliation", "table",
       # 2026-10-20 新建(Metabase 卡 427)。3.7.2 起同一笔 0.99 最多有三条路到 Meta,
       #   其中两路没有共享 event_id、Meta 去重不了。本卡盯服务端这一路。
       # 🛑 两张表的 event_at 都是 UTC,SQL 里都已 CONVERT_TZ 到 SGT。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("intro_should_send","应发(真实0.99) Should","int"),
                  ("intro_sent","实发 Sent","int"),
                  ("intro_gap","差 Gap","int"),
                  ("trial_start_sent","试用开始 TrialStart","int"),
                  ("trial_conversion_sent","试用转化 TrialConv","int"),
                  ("skipped_no_device_id","跳过·无设备ID Skipped","int"),
                  ("failed","发送失败 Failed","int")],
            bar=["intro_should_send"],
            note="🛑「差」不是 0 就是漏发或双算,要查。实测 18 天全部对平。🛑「实发」只数 status='SENT';跳过和失败单独成列——它们是真的没发出去,算进实发会让对账永远是平的。🛑 **第三路(RevenueCat 后台的 Meta 集成)要去 Events Manager 对,看板里放不进来**,所以本卡对平不等于 Meta 侧没有双算。｜ Gap≠0 means missing or double-sent. The third path (RC's own Meta integration) is not visible here.")),
   ("revenue_first_time_payers", "每天新首付 · First-Time Payers", "table",
       # 2026-10-21 新建(Metabase 卡 430)。与「每天续费」成对,按 pay_seq 互斥切分。
       # 🛑 **不能按事件名判新首付**:实测 29 次 RENEWAL 其实是免费试用到期的**首次**扣款,
       #   对用户是新首付。按名字归类会少算 29 人、少算 83% 的钱。
       # 🛑 判「真的扣到钱」用 price_usd > 0 —— INITIAL_PURCHASE+TRIAL(415 次)是开免费试用,一分没扣。
       dict(top=60,
            cols=[("date","日期 Date","text"),
                  ("country","国家 Country","text"),
                  ("acquisition","来源 Source","text"),
                  ("first_payers","新首付人数 First Payers","int"),
                  ("intro_099","其中 0.99 Intro","int"),
                  ("trial_to_full","其中 试用转全价 Trial→Full","int"),
                  ("direct_full","其中 直接全价 Direct","int"),
                  ("revenue_usd","收入 USD","d1"),
                  ("revenue_099_usd","其中 0.99 收入","d1"),
                  ("revenue_full_usd","其中 全价收入","d1"),
                  # 2026-10-29 新增:消耗型购买(3 天通行证 / 能量包)。
                  # 🛑 单位是「笔」不是「人」——一个人可以买很多次,**不要和左边几列相加**。
                  ("pass3day_buys","3天通行证 Pass(笔)","int"),
                  ("energy_pack_buys","能量包 Energy(笔)","int"),
                  ("consumable_usd","消耗型收入 USD","d1")],
            bar=["first_payers","revenue_usd"],
            note="🛑「新首付」= 该用户**按时间排序的第 1 笔** price_usd>0 的扣款,**不看事件名**。实测 29 次 RENEWAL 是免费试用到期的首次扣款,对用户就是新首付。🛑 三类的单价差 14 倍(0.99 均价 0.71 USD vs 全价 10.22),**读人数必须连着收入一起看** —— 印度 13 个 0.99 只有 6.76 USD,美国 1 个全价就 12.99。🛑 和「每天续费」卡按 pay_seq 互斥,相加=总收入。🛑 **2026-10-29 改口径**:3 天通行证(10-22 起)和能量包(10-28 起)也进 subscription_event_log,此前被当成订阅首付**抢了 pay_seq 的第 1 位**(10-24/10-27/10-29 各 1 笔),现已剔出订阅排序、单列成右边三列;`first_payers` 和 `revenue_usd` 因此比 10-29 以前的历史数略小。｜ First payment per user by time order, not by event type. Consumables split out 2026-10-29.")),
   ("revenue_renewals", "每天续费 · Renewals", "table",
       # 2026-10-21 新建(Metabase 卡 431)。pay_seq >= 2,与新首付卡互斥。
       # 🛑 当前为空是结论不是故障:全库 105 人付过钱,**没有任何人扣过第二次**。
       #   0.99 最早 10-22 到期,试用转全价那 29 人下个周期也没到。
       dict(top=60,
            cols=[("date","日期 Date","text"),
                  ("country","国家 Country","text"),
                  ("acquisition","来源 Source","text"),
                  ("pay_seq","第几次扣款 Pay #","int"),
                  ("renewals","续费笔数 Renewals","int"),
                  ("revenue_usd","收入 USD","d1"),
                  ("days_since_prev","距上一笔(天) Days","d1")],
            bar=["renewals","revenue_usd"],
            empty_ok=True,          # 见 table 分支:零行要照常出卡,这张卡空着本身就是结论
            note="🛑 **当前为空是结论,不是取数坏了** —— 实测全库 105 人付过钱、没有一个人扣过第二次(0.99 最早 10-22 才到期)。从 10-22 起才会有行。🛑「续费」= 同一人**第 2 笔及以后**的扣款,**不能按 event_type='RENEWAL' 判** —— 那 29 次 RENEWAL 全是试用到期的首次扣款,已归新首付卡。🛑「距上一笔」能分开两种周期:0.99 实测 6.82 天、全价是一个月。｜ Empty by fact, not by bug: nobody has been charged a second time yet.")),
   ("india_soft_wall", "软墙转化 · India Soft Wall", "table",
       # 2026-10-22 新建(Metabase 卡 440)。软墙已是第三大付费入口(近 3 天 378 次/225 人),
       #   但 10-20 刚开那天 10 次曝光全被关掉。soft_wall_index 只挂在客户端 paywall_viewed 上,
       #   所以这张卡只能走 host.firebase_event(T+1)。
       # 🔴 2026-10-28:这张卡 10-28 抓数 **504 超时**(实测 102.6s)。last-touch 归因原本用
       #   相关子查询,每条下游事件回头扫一遍曝光表 ⇒ 改成窗口函数 **102.6s → 1.3s**
       #   (Metabase 侧 0.5s)。顺带修好「关掉率 101.3%」—— 同微秒两条曝光会把同一条
       #   下游事件重复归因。两版 128 个格子只差那 2 格。同卡 437 的那类问题。
       # 🛑 **本卡保留不摘牌**(2026-10-28 定):倡议书 §二 要把印度软墙换成能量系统的
       #   内联首充卡,换完软墙曝光会归零 —— 留着这张才有「换之前是什么样」的基线。
       #   替换时点未定;定了之后 CUTOVERS、卡头、台账 §2.0 **三处都要记日期**。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("soft_wall_index","第几次弹 Which","text"),
                  ("shown_events","曝光次数 Shown","int"),
                  ("shown_devices","曝光设备 Devices","int"),
                  ("dismissed","关掉 Dismissed","int"),
                  ("dismiss_rate_pct","关掉率 %","d1"),
                  ("sub_tapped","点订阅 Tapped","int"),
                  ("sheet_opened","开收银台 Sheet","int"),
                  ("completed","成交 Completed","int"),
                  ("failed","失败 Failed","int")],
            bar=["shown_events","dismiss_rate_pct"],
            note="印度非会员聊到**第 10、20 条**时弹的**可关掉**的 Plus 弹窗(安卓 build≥211)。🛑 **实测近 3 天:244 次曝光 → 244 次全被关掉 → 3 人点订阅 → 3 人开收银台 → 3 人付款失败 → 成交 0**,曝光数和关掉数精确相等。🛑 **两行的曝光设备数不能相加** —— 同一天同设备可能先后撞到第 10 和第 20 条,合计要另算。🛑 下游事件**都不带 index**(3.8.0 说加了,实测仍全是 NULL),全部按「同设备、之前最近一条软墙曝光」归因。🛑 firebase **T+1**,最后一天天然缺。🔴 **本卡保留做前后对比** —— 倡议书 §二 要用能量系统的内联首充卡(₹49 = 1,000 能量)替换印度软墙,换完这张卡的曝光会归零。旧机制的基线就是上面这组数(3 天 244 次曝光、成交 0),新机制至少要比它好。**替换时点一旦确定,会在页头的切点表里标出来**,跨那一天不要把两段并着读。｜ Soft wall: 100% dismissed, zero conversions so far. Kept as the baseline for the energy-system replacement.")),
   ("price_by_market", "分市场实收价 · Price by Market", "table",
       # 2026-10-22 新建(Metabase 卡 438)。起因:当天 ABC 三档取消,全球统一
       #   「试用 $0.99 / 月订阅 $9.99」,之前手动改过的地区价格全部清掉。
       dict(top=60,
            cols=[("date","日期 Date","text"),
                  ("country_code","国家 Country","text"),
                  ("period_type","档位 Period","text"),
                  ("currency","币种 Currency","text"),
                  ("price_local","本币价 Local","d1"),
                  ("price_usd","折美元 USD","d1"),
                  ("purchases","笔数 Purchases","int")],
            bar=["purchases"],
            note="看**实际成交价**什么时候真的统一 —— 商店价格改动有生效延迟,配置改了不等于用户看到的价变了。实测 10-22 印度仍是 ₹49≈$0.52,没变成 $0.99。🛑 **同一天同一国家可能有两个价**(改价当天新旧并存),本卡每个价单独一行,**不取均值** —— 取均值会算出一个谁都没付过的数。🛑 判 0.99 只能看 period_type='INTRO',**不能按 product_id**(它写 monthly 但周期不到 7 天)。🛑 price_local 一般含当地税(沙特 SAR4.29 ≈ $0.99 税前 +15% VAT),所以折美元回来不会正好 0.99;**用户在商店看到的是 price_local**。｜ Actual transacted price by market; store price changes take effect with a lag.")),
   ("paywall_free_quota_line", "免费额度线 · Free Quota Line", "table",
       # 2026-10-22 复活(Metabase 卡 403)。原来窗口是「2026-09-25 起固定」,每天都在长,
       #   必定超 nginx 60 秒代理超时,长期抓不到数;改成近 3 天滚动后 25.8 秒。
       #   🛑 代价:看不到 10-15 / 10-20 这些历史切点,历史切点看 _已落地改动台账.md。
       dict(top=40,
            cols=[("date","日期 Date","text"),
                  ("reason","原因 Reason","text"),
                  ("free_total","免费额度 Free Total","int"),
                  ("rows_n","行数 Rows","int"),
                  ("sessions","会话 Sessions","int"),
                  ("total_min","最小 Min","int"),
                  ("total_avg","均值 Avg","d1"),
                  ("total_max","最大 Max","int")],
            note="当前免费额度线是多少、这两三天有没有变。🛑 **只回答「当前」** —— 窗口是近 3 天滚动(再长就超 60 秒网关超时),历史切点看台账。🛑 freeTotal **非空行**正常只有 20(全球)和 30(印度 A 类)两个值,**出现第三个值 = 有人改了配置**;但**空值是正常的、不算第三个值**,实测它全部且仅来自 reason='client_missing' 和 'voice_skipped' 这两条不算额度的代码路径。🛑 **配置改了和数据里旧值消失差约一天** —— freeTotal 按额度周期打戳,已发出的周期仍带旧值。🛑 这张卡数的是 total 的上下界,**不是撞墙人数**,撞墙人数看 424。｜ Current free-quota line only; 3-day rolling window.")),
   ("billing_sheet_success", "付款页成功率与真实失败 · Billing Sheet Success", "table",
       # 2026-10-22 新建(Metabase 卡 433)。合并了 Michael P1「付款页成功率」与文档 A-7
       #   「购买失败真实率」—— 同一条链路的两头,分两张会让人跨卡相减、把分母弄错。
       dict(top=60,
            cols=[("date","日期 Date","text"),("country","国家 Country","text"),
                  ("opened_users","打开付款页 Opened","int"),
                  ("succeeded_users","成功 Done","int"),("success_rate","成功率 %","pct1"),
                  ("failed_users","失败 Failed","int"),
                  ("user_cancel_users","其中 用户取消","int"),
                  ("other_error_users","其中 其他错误","int"),
                  ("cancel_share_of_fail","取消占失败 %","pct1"),
                  ("recovered_events","自动找回 Recovered","int"),
                  ("true_fail_events","真实失败 True Fail","int")],
            bar=["opened_users","success_rate"],
            note="🔴 **直接用 failed 算失败率会高估** —— 失败后自动找回(3.7.2 的 purchase_recovered)那条 purchase_failed **照发、不撤销**,所以「真实失败 = failed − recovered」。🛑 分母是**打开过付款页的人**,从付费墙到付款页之间还有一层流失,那层看「四道墙并排」。🛑 实测整体成功率 19.4%,**印度 23~39%、沙特只有 7~20%**,失败几乎全是「用户取消」。｜ Recovered purchases do NOT cancel the earlier failed event.")),
   # 🛑 2026-10-27 摘牌:「印度·0.99首购率与次日回来 · India Intro & Return」(Metabase 卡 434)。
   #   原因:和下面这张只差一个 WHERE,**剔除版才是对的**(A 类实验广告的落地链路是断的,会污染分母),
   #   两个数并存只会在会上被问「到底看哪个」。
   #   处理方式:**只把 dashcard 从看板 24 摘掉,卡没有归档** —— 434 仍在 collection 里能单独打开。
   #   ⇒ 抓数侧不用加 SKIP_CARDS(fetch 遍历的是 dashcard,卡不在看板上就不会被抓)。
   #   恢复:先把 dashcard 加回看板 24,再把卡定义写回这里。
   #   🛑 2026-10-28:摘牌之后 435 成了印度这一块唯一的卡,**已把它的标题改回**
   #     「印度·0.99首购率与次日回来」(Metabase 卡名同步改了)。要恢复 434 的话,
   #     **记得把 435 的标题改回带「剔除A类实验广告」**,否则两张卡会同名。
   #   摘牌前的看板配置备份在 scratchpad/dashboard_24.bak_20261027.json
   ("india_intro_and_return_excl", "印度·0.99首购率与次日回来 · India Intro & Return", "table",
       # 2026-10-22 新建(Metabase 卡 435)。
       # 🛑 2026-10-28 改标题:原来叫「印度·同上·剔除A类实验广告」—— 那个「同上」指的是
       #   不剔的那张(卡 434),10-27 已摘牌,本张成了印度这一块唯一的卡,
       #   再叫「同上·剔除」读的人不知道剔的是什么。**剔除规则改写进 note。**
       # 🛑 key 和 Metabase 卡 id 都没动(还是 india_intro_and_return_excl / 435),
       #   只改了显示标题和卡头 —— 改 key 要同时动 fetch 的 KEY_OVERRIDE,没必要。
       dict(top=60,
            cols=[("date","注册日 Date","text"),("creative","素材 Creative","text"),
                  ("new_users","印度广告新用户 New","int"),
                  ("intro_buyers","买 0.99 Buyers","int"),("intro_rate","首购率 %","pct1"),
                  ("returned_d1","次日回来 Returned","int"),("d1_rate","次日回来率 %","pct1")],
            bar=["new_users","intro_rate"],
            note="印度广告来的新用户,按**注册日切队列**:分子是这批人**后来**买的 0.99,不是「当天买家 ÷ 当天新用户」(分子分母不是同一批人,Michael 反馈第五节第 4 条指出过)。🛑 **本卡剔掉了两个 TypeA 实验 campaign**(`SoulMap_TypeA_Android_Board/india_20261016`)—— 它们的**落地链路是断的**,广告里的角色没出现在首页,实测开口率 45.6%/25.0% vs 印度其余 73.9%,聊≥5条 25.9%/17.5% vs 52.1%,混进来会把首购率和留存一起拉低。🛑 **实测当前体量下剔不剔只差 0.01 个点**(那两个 campaign 在印度广告口径里只有 80 人),**等 A 类放量后这个差别才会起来**。🛑 「每个 0.99 首购成本」这张卡给不了 —— 广告花费不在生产库。｜ India ad-sourced cohorts by signup date; two broken-funnel TypeA campaigns are excluded.")),
   ("intro_expiry_per_user", "0.99 到期逐人结果 · Intro Expiry Per-User", "table",
       # 2026-10-21 新建(Metabase 卡 429)。对应 Michael 10-21 反馈 P0 第一条(W43 ③ / D-335)。
       # 🛑 到期取 MAX(expiration_at),**不能算「首购 + 7 天」** —— 实测周期均值 6.82 天、最长 6.96,
       #   而且扣款失败时商店会发 SUBSCRIPTION_EXTENDED 把到期往后推,每次推一天。
       # 🛑「关了自动续费」看最新状态:实测有人 CANCELLATION 之后又 UNCANCELLATION 恢复了。
       dict(top=100,
            cols=[("expire_date","到期日 Expire Date","text"),
                  ("expire_at_sgt","到期时刻(SGT)","text"),
                  ("purchased_at_sgt","首购时刻(SGT)","text"),
                  ("user_id","用户 User","text"),
                  ("country","国家 Country","text"),
                  ("creative","素材 Creative","text"),
                  ("network","渠道 Network","text"),
                  ("price_local","本地价 Price","text"),
                  ("outcome","结果 Outcome","text"),
                  ("canceled_at_sgt","关续费时刻 Canceled At","text"),
                  ("cancel_reason","原因 Reason","text"),
                  ("was_extended","被推迟过 Extended","int")],
            note="🛑 结果按**终态优先级**判:扣全价成功 > 扣款失败已失效 > 退订后到期失效 > 扣款失败重试中 > 已关自动续费待到期 > 首期内。🛑 到期取 MAX(expiration_at),不是「首购+7天」—— 周期实测 6.82 天均值,且扣款失败时商店会把到期往后推(was_extended 那列)。🛑 「关了自动续费」看最新状态,有人取消后又恢复过。🛑 判 0.99 只能用 period_type='INTRO',product_id 写的是 monthly 但实际周期不到 7 天。｜ Outcome is resolved by terminal state. Expiry uses MAX(expiration_at), never purchase+7d.")),
   # 🛑 2026-10-28 摘牌(用户决定):这里原有三张 0.99 放量期的监控卡 ——
   #     「0.99首月_首购按客户端版本 · Intro Purchase by Client Version」(Metabase 卡 420)
   #     「0.99首月_首购按国家 · Intro Purchase by Country」(卡 421)
   #     「0.99首月_放量覆盖按装机日 · Rollout Coverage by Install Date」(卡 422)
   #   原因:它们量的是**放量进度**,而 0.99 在 2026-10-15 就已全量 ——
   #     422 的「覆盖率」从那天起恒等于 100%,420 的客户端版本维度也是放量期用来看覆盖的;
   #     421 的国家维度和「分市场实收价 · Price by Market」(438)、
   #     「付费_付款页成功率与真实失败」(433)重合。
   #   🛑 **「0.99首月_到期逐人结果 · Intro Expiry — Per-User Outcome」(429)留着** ——
   #     它量的是续费结局,不是放量,数还在长(121 行)。
   #   处理方式:**只摘 dashcard,卡没有归档** —— 三张卡都从看板 18 和 24 上摘掉,
   #     仍在 collection 里能单独打开。⇒ 抓数侧不用加 SKIP_CARDS(fetch 遍历的是 dashcard)。
   #   恢复:先把 dashcard 加回看板,再把卡定义写回这里。
   #   摘牌前的看板配置备份在 scratchpad/dashboard_18.bak_20261028b.json 和 dashboard_24.bak_20261028b.json
   ("monetize_payment_funnel_daily", "付费漏斗 · Payment Funnel Daily", "table",
       # 2026-09-09 新建。付费链路 09-08~09 刚打通。
       #   选表格不选折线:① 量级个位数到几十,折线全是贴地的点;② 左右两半是两个源、时效不同,
       #   叠在一张图上会诱导跨源比较;③ 日报要精确读数,表格直读。
       #   与 Discover_search usage / Model_provider daily 一致,按 date 倒序。
       # 2026-09-11 随 SQL 改:付费墙曝光拆出专家墙 / 额度墙两列。
       #   客户端给额度墙补了曝光埋点(复用 paywall_viewed、带 source='plus_sheet'),上线后
       #   总数会从「只有专家墙」变成两墙混合,拆开才看得见那个口径断点、两墙也能各读各的。
       dict(top=14,
            cols=[("date","日期 Date","text"),
                  ("paywall_users","付费墙曝光 Paywall","int"),
                  ("expert_paywall_users","其中·专家墙 Expert","int"),
                  ("plus_paywall_users","其中·额度墙 Plus","int"),
                  ("purchase_started_users","发起购买 Started","int"),
                  ("purchase_started_rate","曝光→发起","pct1"),
                  ("purchase_completed_users","购买成功 Completed","int"),
                  # 2026-10-29 新增:非订阅购买单列。🛑 和订阅那几列是**并列的三类**,不要相加。
                  ("energy_pack_users","能量包 Energy","int"),
                  ("pass3day_users","3天通行证 Pass","int"),
                  ("purchase_canceled_users","用户取消 Canceled","int"),
                  ("trial_effective_users","开过订阅(试用或0.99) Sub Started","int"),
                  ("intro_users","其中 0.99 Intro","int"),
                  ("paid_users","付费 Paid","int"),
                  ("new_subscription_apple","Apple","int"),
                  ("new_subscription_google","Google","int"),
                  ("restore_success_users","恢复成功 Restored","int")],
            bar=["paywall_users","new_subscription_users"],
            note="左半走埋点（滞后 1–2 天）、右半走服务端（实时），两半不可相加或互验；最新一天左半为 0 是 ETL 未到。付费墙曝光拆专家墙与额度墙，转化率不要混读。样本是个位数，引用请报绝对人数。🛑 **2026-10-29 改口径**:商店里多了三类非订阅商品(3 天通行证 10-22 起、能量包与能量版 Plus 10-28 起),它们和月订阅**共用 purchase_started / purchase_completed 两个事件**,左半四列已按 `product_id` 限定到月订阅;非订阅购买在「能量包 / 3天通行证」两列单列。跨 10-22 / 10-28 比旧数时,旧数里这三类是混着的。｜ Left half is telemetry (1–2 day lag), right half is server-side (realtime). Do not cross-compare. Single-digit samples. Non-subscription SKUs split out 2026-10-29.")),
   ("monetize_usage_distribution_30d", "免费额度撞墙测算 · Free-Quota Impact (30d)", "table",
       # 不写 sort = 保持 SQL 的 ORDER BY(人群 → 额度由低到高的自然阅读序)
       # 2026-09-07 随 SQL 改版:原为分位数表(6 行),现为「额度 → 撞墙影响」表(3 人群 × 10 档 = 30 行)。
       #   原表把问题问反了:要定的是「额度 30 行不行」,给的是「P80 是 41 条」,而分位刻度里没有 30。
       dict(top=30,
            cols=[("cohort","人群 Cohort","text"),
                  ("daily_cap","每日额度 Cap","int"),
                  ("users_total","总人数 Users","int"),
                  ("users_hitting_cap","撞墙人数 Hit","int"),
                  ("users_hitting_cap_rate","撞墙人占比 Hit %","pct1"),
                  ("person_days_total","总人日 P-Days","int"),
                  ("person_days_hitting_cap","撞墙人日 Hit","int"),
                  ("person_days_hitting_cap_rate","撞墙人日占比 Hit %","pct1"),
                  ("messages_blocked","被挡消息 Blocked","int"),
                  ("messages_blocked_rate","被挡占比 Blocked %","pct1"),
                  ("current_tier","","text")],
            bar=["users_hitting_cap_rate","messages_blocked_rate"],
            note="免费额度决策表:一行一个候选额度,读「多少人会撞墙」;现行 30/天 已标出 ｜ Free-quota decision table: one row per candidate cap showing how many users would hit it; the current 30/day is marked")),
   ("monetize_payment_funnel_by_country", "付费漏斗分国家 · Payment Funnel by Country", "funnel",
       # 2026-09-21 新建。起因:09-18 晚把 Meta 地域定向改到英美加澳,需要一条能持续看
       #   「发达国家 vs 南亚在付费链路上差在哪一环」的线,而不是每次手工取数。
       # 🛑 队列起点写死 2026-09-12(额度付费墙上线日),不是滚动 30 天 ——
       #   09-11 之前装机的用户不可能撞墙,算进分母会凭空压低撞墙率。
       #   实测这个坑有多深:按整月算英美加澳撞墙率 1.5%、南亚 8.9%;按 09-12 起算是 6.4% / 14.5%。
       # 🛑 与 monetize_full_funnel_by_version 共有五个环节,数值必须一致,改口径要同步改两张。
       dict(note="七步按国家分组，队列是 2026-09-12 起新装的设备（额度付费墙那天上线，此前装机的人碰不到它）。前五步是埋点（设备级），后两步是服务端订阅表（账号级），需经埋点里的数字 uid 桥接、覆盖约 85%，所以试用与付费两级系统性偏低约一成半。英美加澳样本只有三位数，撞墙以下每级都是个位数，只能看「差距出现在哪一段」，不能比较两地付费率。｜ Seven steps by country. Cohort installs from 2026-09-12 (paywall launch). Steps 1-5 telemetry, 6-7 server-side subscriptions bridged via numeric uid (~85% coverage, so trial/paid are understated). The UK/US/CA/AU arm is small; read where the gap appears, not the paid rates.")),
   ("churn_before_after_speaking", "退订·讲话前还是讲话后 · Churn Before/After Speaking", "table",
       # 2026-10-22 新建(Metabase 卡 436)。对应 Michael 10-21 反馈 P1 第 8 项(D-210)。
       dict(top=60,
            cols=[("unsub_date","退订日 Date","text"),("country","国家 Country","text"),
                  ("sub_type","订阅类型 Type","text"),
                  ("unsub_users","主动退订 Unsub","int"),
                  ("spoke_then_churned","讲过话才退 Spoke","int"),
                  ("churned_before_speaking","一句没说就退 Silent","int"),
                  ("before_speaking_rate","没说话就退 %","pct1")],
            bar=["unsub_users","before_speaking_rate"],
            note="🛑 **分母只算主动退订**(cancel_reason='UNSUBSCRIBE',210 人),**不含扣款失败**(BILLING_ERROR,199 人)—— 两者合起来算「退订率」会把支付问题当成产品问题。扣款失败那批看 409/410。🛑 判据是消息落在 [订阅开始, 退订时刻] 之间,不是「有没有聊过天」——后者会把订阅前聊过、订阅后没碰的人误判。🛑 实测 **215 人里 37 人(17.2%)一句话没说就退了**。｜ Denominator is voluntary churn only; billing failures are a different thing.")),
   ("monetize_full_funnel_by_version", "全链路付费漏斗分版本 · Full Payment Funnel by Version", "funnel",
       # 2026-09-21 新建。补 `2_点击角色卡` 这一环 —— Discover 页到聊天页之间唯一的观测点。
       #   点击取 card_tap 且 card_type='character',**不限 sub_tab**:
       #   discover_character_daily_ctr 限了三个 tab 是为了让 CTR 分子分母同盘(曝光只在那三个发),
       #   本卡只数点击不算率,限了反而漏掉 foryou(每天 631~779 次点击但曝光恒为 0)。
       # 🛑 队列起点同上写死 09-12,代价是装机窗口最长 9 天,只有 3.1.0 / 3.1.1 够样本,
       #   其余版本并入「zz_其它版本合计」不丢行,否则各版本之和对不上总数。
       # 🛑 4_撞墙 在版本之间**不完全可比**:免费额度自 09-15 起是 20/40/60 三档随机实验
       #   (soulmap_message_quota_usage.quota_arm),不同版本用户被随机分到不同额度档。
       #   且 60 档墙曝光覆盖率仅 10.8%(20/40 档 65.6%/75.5%),疑似未正常触发,已报客户端。
       dict(gsort="version", note="七步按 App 版本分组，队列是 2026-09-12 起新装的设备。第 2 步「点击角色卡」取 card_tap（不限 sub_tab，foryou 有点击无曝光）。装机量不足 200 的版本并入「其它版本合计」，不丢行。⚠️ 第 4 步「撞墙」跨版本不可直接比较：免费额度自 2026-09-15 起是 20/40/60 三档随机实验，不同版本用户被随机分到不同档位；且 60 档疑似未正常弹窗（曝光覆盖率 10.8% vs 65~76%），已报客户端排查。要看额度本身的影响应按 quota_arm 拆，不是按版本。｜ Seven steps by app version, installs from 2026-09-12. Step 4 is NOT comparable across versions: free quota is a randomised 20/40/60 experiment since 2026-09-15, and the 60 arm looks like it is not firing (10.8% wall-exposure coverage vs 65-76%).")),
 ]),
 ("⑧ 付费墙实验 · Paywall Experiment", [
   ("paywall_triggers_side_by_side", "五道墙并排 · Paywall Triggers Side by Side", "table",
       # 🛑 2026-10-27 改名「四道墙」→「五道墙」。SQL 一行没动 —— 本卡从建卡起就是按 trigger
       #   动态分组、没有白名单,第五道墙 first_message_gate 一出现就自动有行。
       # 🛑 first_message_gate 不是 10-22 才有的:实测全量 344 次 / 126 人,
       #   最早 2026-10-01 01:49、最后 10-25 00:45,10-01~10-09 有过真实量级(单日最高 127 次/44 人),
       #   之后每天只剩 1~5 次。「只有 2 人 6 次」是「10-22 起」的切片,不是全部。
       # 2026-10-20 新建(Metabase 卡 425)。3.7.2 起 wall='chat' 里混了额度硬墙(message_quota)
       #   和软墙(quota_soft_wall),「wall='chat' = 撞上额度被挡住」这个老等式不成立了。
       #   本卡按 trigger 并排拆开,并把成交按 period_type 分成「免费试用 / 0.99」两列。
       # 🛑 occurred_at 是 UTC(实测差 8 小时),SQL 里已 CONVERT_TZ 到 SGT。
       dict(top=40,
            cols=[("date","日期 Date","text"),
                  ("trigger_cn","哪道墙 Trigger","text"),
                  ("shown_users","曝光 Shown","int"),
                  ("tapped_users","点订阅 Tapped","int"),
                  ("tapped_rate","点击率 Tap %","pct1"),
                  ("opened_users","开收银台 Billing","int"),
                  ("succeeded_users","成交 Done","int"),
                  ("succeeded_intro","其中 0.99 Intro","int"),
                  ("succeeded_trial","其中 免费试用 Trial","int"),
                  ("succeeded_rate","成交率 Done %","pct1")],
            bar=["shown_users","tapped_rate"],
            note="🛑 一个用户一天可能撞多道墙,各行人数**不能跨 trigger 相加**,合计会重复计人。🛑 成交必须分开读:10-14 之前全是免费试用、10-19 之后全是 0.99,合成一个「付款」的任何跨期比较都不成立。🛑 **分母缺两类**:trigger=sp_locked(点锁住的照片)和 sp_vision_quota(看图额度)不进服务端这四个事件,所以本卡不是全部付费入口。🛑 软墙(印度可关弹窗)起点 2026-10-20 17:20,现在只有个位数人,三天内不要读它的比率。｜ One row per day x trigger. Users can hit multiple walls a day — do NOT sum across rows.")),
   ("paywall_writeback_by_version", "回写率分客户端版本 · Writeback Rate by Client Version", "table",
       dict(top=40,
            cols=[("date","日期 Date","text"),
                  ("app_version","版本 Version","text"),
                  ("should_show","应展示 Should Show","int"),
                  ("devices","设备 Devices","int"),
                  ("written_back","已回写 Written Back","int"),
                  ("pct_written_back","回写率 %","d1")],
            bar=["devices","pct_written_back"],
            note="这是实验数据本身的质量卡:回写率低的版本,它的分臂结果就不可信。读上面几张分臂卡之前先看这张。｜ Data-quality guard for the experiment: low writeback = unreliable arm data for that version.")),
   # 🛑 2026-10-22 摘牌:「免费额度线」(Metabase 卡 403)已进 fetch_metabase.py 的停抓名单,
   #   处理方式与 404 分臂漏斗一致 —— **等条件,不是作废**,所以 Metabase 那边没归档。
   #   原因:必定超 60 秒网关超时(三种写法都在 240 秒上下),根因是 soulmap_turn_log
   #   36.8GB 数据 + 13.5GB 索引、而 buffer pool 只有 1.5GB,几乎每次回表都落盘,SQL 改不动。
   #   🛑 恢复的时候:**这段注释换回原来的卡定义**,列名是
   #     date / reason / free_total / rows_n / sessions / total_min / total_avg / total_max,
   #     top=40,表格,卡头写明「数的是 total 的上下界,不是撞墙人数,撞墙人数看 424」。
   #   详见 02_跨团队沟通/服务端/173_TO-Liwen-db-index-and-buffer-pool-20261022.md
   ("quota_wall_blocked_next", "撞墙与撞墙之后 · Quota Wall — Blocked & Next", "table",
       dict(top=30,
            cols=[("d","日期 Date","text"),
                  ("blocked_users","撞墙人数 Blocked Users","int"),
                  ("blocked_events","撞墙次数 Events","int"),
                  ("events_per_user","人均次数 per User","d1"),
                  ("saw_paywall_24h","24h内看到付费墙 Saw Paywall","int"),
                  ("saw_paywall_pct","看到墙 %","d1"),
                  ("tapped_sub_24h","24h内点订阅 Tapped","int"),
                  ("tapped_sub_pct","点订阅 %","d1"),
                  ("billing_done_24h","24h内完成扣款 Billing Done","int"),
                  ("note","备注 Note","text")],
            bar=["blocked_users","saw_paywall_pct"],
            note="撞墙用服务端 chat_wall_blocked 事件数,下游三级都是撞墙后 24 小时内。🛑 本卡替代原「Monetize_free quota wall daily」—— 那张没有真正的撞墙字段,只能看 total 的上界。🛑 比率的分母是当天撞墙人数,这个分母每天都在动,读比率时要同时看第一列。｜ Replaces the old quota-wall card, which had no real blocked-event field.")),
 ]),
 ("⑨ 邀请 · Invite", [
   ("invite_inviter_side", "邀请人侧 · Invite — Inviter Side", "table",
       dict(cols=[("seq","#","int"),
                  ("step","环节 Step","text"),
                  ("step_en","Step (EN)","text"),
                  ("users","人数 Users","int"),
                  ("events","次数 Events","int"),
                  ("pct_of_code_holders","占持码人 %","d1")],
            bar=["users"],
            note="🛑 这六行不是嵌套漏斗,是六个各自独立的动作,把相邻两行相除当转化率会得到没有意义的数。｜ These six rows are independent actions, NOT a nested funnel.")),
   ("invite_invitee_side", "被邀请人侧 · Invite — Invitee Side", "table",
       dict(cols=[("seq","#","int"),
                  ("step","环节 Step","text"),
                  ("step_en","Step (EN)","text"),
                  ("source","数据源 Source","text"),
                  ("users","人数 Users","int"),
                  ("note","备注 Note","text")],
            bar=["users"],
            note="🛑 最后一行换了数据源(见 source 列),所以五行仍要逐行读、不画漏斗图。多数行分子是个位数,读不出比例。｜ The last row comes from a different source; read row by row.")),
   ("invite_bonus_30msg", "30 条奖励发放 · 30-Message Bonus Grants", "table",
       dict(cols=[("seq","#","int"),
                  ("policy_version","策略版本 Policy","text"),
                  ("side","侧 Side","text"),
                  ("side_en","Side (EN)","text"),
                  ("bindings","绑定数 Bindings","int"),
                  ("granted","已发放 Granted","int"),
                  ("granted_pct","发放率 %","d1"),
                  ("lag_p50_min","延迟中位(分) p50","d1"),
                  ("lag_max_min","延迟最大(分) max","int"),
                  ("invitee_sent_msg","被邀请人发过消息 Sent","int"),
                  ("sandbox_invitee","沙盒 Sandbox","int"),
                  ("note","备注 Note","text")],
            bar=["bindings","granted_pct"],
            note="🛑 发放与否看 invite_binding 的 bonus_at 字段,不看 reward_state。🛑 延迟同时给中位和最大值 —— 实测逐条是 0/0/1/1/2/3/20/2933 分钟,只看均值会被那个极值带偏。｜ Grant is determined by bonus_at, not reward_state; median and max are both shown because the tail is extreme.")),
   ("invite_redeem_by_source", "兑换结果按来源 · Redeem by Source & Reason", "table",
       dict(top=25,
            cols=[("via_cn","来源 Source","text"),
                  ("via","Source (raw)","text"),
                  ("reason_cn","原因 Reason","text"),
                  ("reason","Reason (raw)","text"),
                  ("ok","成功? OK","text"),
                  ("attempts","尝试 Attempts","int"),
                  ("users","人数 Users","int")],
            bar=["attempts"],
            note="兑换失败的原因分布,按来源(链接 / 手动输码)拆。｜ Redemption outcomes split by entry path and failure reason.")),
   ("invite_reward_grants", "奖励发放明细 · Reward Grants", "table",
       dict(top=40,
            cols=[("granted_date","发放日 Date","text"),
                  ("kind","类型 Kind","text"),
                  ("inviter_user_id","邀请人 Inviter","text"),
                  ("invitee_user_id","被邀请人 Invitee","text"),
                  ("invitee_env","环境 Env","text"),
                  ("is_real","真实? Real","int"),
                  ("month_index","月序 Month","int")],
            note="🛑 逐条明细,看 is_real 和 invitee_env 两列筛掉沙盒数据再数。｜ Row-level grants; filter sandbox rows via is_real / invitee_env before counting.")),
 ]),
 ("⑩ 后端 · Backend", [
   ("capability_funnel_by_capability", "各能力可读性 · Capability Readability", "table",
       dict(top=40,          # 不填 sort = 保持 SQL 的 ORDER BY surfaced_7d DESC
            cols=[("capability","能力 Capability","text"),
                  ("readability","可读性 Readability","text"),
                  ("surfaced_7d","近7天出现 Surfaced 7d","int"),
                  ("delivered_7d","近7天送达 Delivered 7d","int"),
                  ("unknown_7d","近7天未知 Unknown 7d","int"),
                  ("delivery_rate_before_0819","08-19前送达率 % Pre-0819 Delivery","d1"),
                  ("reply_rate_before_0819","08-19前回复率 % Pre-0819 Reply","d1"),
                  ("surfaced_before_0819","08-19前出现 Pre-0819 Surfaced","int"),
                  ("delivered_before_0819","08-19前送达 Pre-0819 Delivered","int"),
                  ("unknown_top_reason","最大未知原因 Top Unknown Reason","text")],
            bar=["surfaced_7d"],
            note="每个能力一行,用于在日度健康卡报警后定位是哪些能力;送达率分近7天与 08-19 前两段,后者是历史基线 ｜ One row per capability, used to pinpoint which ones after the daily-health card flags a problem; delivery is split into last 7 days and pre-08-19, the latter being the historical baseline")),
   ("capability_funnel_daily_health", "能力链路日度健康 · Capability Chain Daily Health", "table",
       dict(top=30,          # 不填 sort = 保持 SQL 的 ORDER BY log_date DESC
            cols=[("log_date","日期 Date","text"),
                  ("status","状态 Status","text"),
                  ("caps_reporting_delivered","报 delivered 的能力数 Caps Reporting","int"),
                  ("caps_active","活跃能力数 Caps Active","int"),
                  ("surfaced","出现 Surfaced","int"),
                  ("delivered","送达 Delivered","int"),
                  ("unknown_events","未知 Unknown","int"),
                  ("replied","回复 Replied","int"),
                  ("delivery_rate_pct","送达率 % Delivery","d1"),
                  ("unknown_share_pct","未知占比 % Unknown","d1"),
                  ("top_unknown_reason","最大未知原因 Top Unknown Reason","text")],
            bar=["surfaced"],
            note="一天一行,看能力链路当天是否正常;status 由「报 delivered 的能力数」判定,该列正常时送达率才有意义 ｜ One row per day showing whether the capability chain is healthy; status comes from the count of capabilities reporting delivered — the delivery rate is only meaningful when that count is normal")),
 ]),
 ("⑪ 风险 · Risk", [
   ("churn_winback", "退订与挽回链路 · Churn & Win-back", "table",
       # 2026-10-22 新建(Metabase 卡 441)。整条链都在跑但看板上一张卡都没有;
       #   0.99 首批 10-22 到期,这条链马上从边缘变主战场。
       #   🛑 近 30 天整段合计、**不拆天** —— 分子全是个位数,拆天每格都是 0~3 读不出。
       # 🔴 2026-10-29:两条链各补一个 ⓪ 级,用服务端 `subscription_event_log.cancel_reason`
       #   给出分母。⓪ 和 ① 是**两个数据源**,不是嵌套漏斗 —— 见 note。
       dict(top=20,
            cols=[("chain","链路 Chain","text"),
                  ("step_no","级 Step","int"),
                  ("step","步骤 Name","text"),
                  ("events","次数 Events","int"),
                  ("users","人数 Users","int")],
            bar=["users"],
            note="🔴 **2026-10-29 两条链各加了一个 ⓪ 级**,用服务端 `cancel_reason` 给出分母 —— 改之前卡里只有客户端漏斗的绝对量,读的人不知道「保留期弹窗曝光 28 人」是 28 分之几。实测近 30 天(已剔 CityPLX / 四个测试号 / 两个沙盒号):**扣款失败 `BILLING_ERROR` 265 人**、**主动退订 `UNSUBSCRIBE` 241 人**、客服与后台取消 4 人。🔴 **「退订」里扣款失败比主动退订还多**(265 vs 241),而且 **221/265 = 83% 发生在免费试用期**、0.99 一次都没有 —— 这就是下面「扣款失败≠流失」那条的量化版本。⚠️ **本卡原来的预测被实测推翻**:卡头原写「0.99 首批 10-22 到期后大部分会走到扣款失败,这条链马上变主战场」,实测到 10-29 为止 **0.99 的 35 次取消全是主动退订、扣款失败 0 次** —— 🛑 **但不要据此下结论**,宽限期已改 0 天,到期可能直接走 `EXPIRATION` 而不记 `CANCELLATION`,要判断得查 0.99 到期那批人的终态(卡 429)。🛑 **⓪ 和 ① 是两个数据源**(服务端账本 vs 客户端埋点)、**不是嵌套关系,`①÷⓪` 不是「弹窗覆盖率」** —— ⓪ 的唯一作用是给量级参照。🛑 **和客户端那个取消理由不是一回事**:`payload->>'$.reason'`(太贵 15 / 其它 5 / …,共 28 条)是**用户自己选的理由**,这里的 `cancel_reason` 是**服务端判定的类型**(510 人),两者互补,不要混用也不要相加。两条链:**A 扣款失败挽回**(保留期弹窗→点更新→恢复扣款)、**B 主动取消挽回**(取消弹窗→问原因→填/跳过→重新订阅/稍后→撤销取消)。🛑 **不是严格嵌套漏斗**,相邻两级不要相除 —— 实测「问原因」60 人反而多于「取消弹窗曝光」58 人(两个入口不完全重合),**只读各级绝对量,看哪级掉得最狠**。🛑 **分子<10 的级别读不出**,不排名不算比率。🛑 banner 三步是**旁路不是主链**,45 次只来自 9 个人(每次进 App 都弹),**只读 users**。🛑 「扣款失败」≠「流失」:宽限期是 0 天但账户保留期有 60 天,期间仍可能恢复。🛑 和「0.99 到期逐人结果」(429)**分母不同,不要互相相除** —— 那张看到期终态,这张看挽回动作有没有人响应。｜ Two win-back chains; counts are single digits, read absolute levels only.")),
   ("silence_nudge_by_tier", "沉默提醒按档位与角色类型 · Silence Nudge by Ladder & Class", "table",
       # 2026-10-22 新建(Metabase 卡 439)。起因:10-21 18:19 服务端上线、10-22 算法侧打开,
       #   B 类沉默提醒现在能走到 3h 档。原来 B 类在 3m 被算法拒 ⇒ 计数还是 0 ⇒ 永远到不了 3h。
       dict(top=40,
            cols=[("date","日期 Date","text"),
                  ("tier","档位 Tier","text"),
                  ("char_class","角色类型 Class","text"),
                  ("attempts","尝试 Attempts","int"),
                  ("sent_n","实发 Sent","int"),
                  ("sent_pct","实发率 %","d1"),
                  ("declined_empty","拒:算法空回 Empty","int"),
                  ("declined_quiet_hours","拒:夜间静默 Quiet","int"),
                  ("declined_no_timezone","拒:无时区 No TZ","int"),
                  ("declined_non200","拒:接口非200 Non-200","int")],
            bar=["attempts","sent_pct"],
            note="🛑 **「尝试」和「实发」必须分开看** —— 算法侧打开前 B 类的 3h 行全是 declined_empty,**不是没触发,是触发了被拒**,只看实发会以为功能没上。实测 B 类 3h 尝试数 10-20 只有 1 → **10-21 跳到 116 → 10-22 到 218**,梯子确实通了;**但 B 类 sent 近 6 天每一档都是 0,一条都没真发出去**,所以推送量并没有跟着涨。🛑 实发率天然到不了 100%(夜间静默、10% 对照组、每日上限照旧生效),它是**结构占比不是健康度**,低不等于坏。｜ Attempts vs actually-sent must be read separately.")),
   ("chat_quality_daily_alerts", "对话质量每日告警 · Chat Quality — Daily Alerts", "table",
       # 2026-10-28 新建(Metabase 卡 449)。出处:埋点需求 §7「对话质量(每天自动算,
       #   不靠人看)」。该节四条标「System A」的判据**库里直接能算**,没等回传。
       # 【展示形式】表格,一天一行 —— 告警要的是「今天有没有、有几条」,
       #   且四类量级差几十倍(兜底 12 条 vs 回复 15 万条),画折线小的那条永远贴 0 轴。
       # 🛑 放在 ⑪ 风险 不放 ④ 对话:它不是对话指标,是「>0 即报」的告警。
       #   与下面的语言错配卡**剔除规则完全一致,两张必须同步改**。
       dict(top=20,
            cols=[("date_msg","日期 Date","text"),
                  ("host_msgs","模型回复数 Replies","int"),
                  ("blank_msgs","空回复 Blank","int"),
                  ("blank_pct","空回复率 %","d1"),
                  ("fallback_msgs","兜底话术 Fallback","int"),
                  ("fallback_pct","兜底率 %","d1"),
                  ("phone_like_msgs","疑似手机号 Phone?","int"),
                  ("email_msgs","邮箱 Email","int"),
                  ("arabic_slash_msgs","阿语模板残留 AR /ة","int"),
                  ("excluded_alert_msgs","被剔人群中的告警 Excluded","int")],
            bar=["host_msgs"],
            note="🛑 **分母是「模型生成的 host 回复」**,已剔掉开场白模板(`authoredOpener`/`presetOpener`,近 14 天 10,823 条 = 6.4%)、主动问候、CityPLX(`app_source='city'`,765 个账号)和四个内部测试号。实测开场白里四类告警**全是 0**,剔掉不丢任何一条。🔴 **末列是防「剔完变 0」的** —— 近 14 天**全部 12 条兜底都来自 CityPLX**(集中在 10-26),剔完 `兜底话术` 整列是 0;末列把它们单独计出来,不进前面任何分子分母。⚠️ 连带结论:兜底白名单**至今没在 SoulMap 自己的流量上命中过**,别把「兜底 0」当结论。🛑 **「疑似手机号」是宽判据(连续 9 位以上数字 / `+` 开头国际号形态),会误报** —— 用途是「>0 去看一眼」,**不要算比率、不要写进对外材料**;10-28 抽查两条是 `0706029414` / `0113932791`,形态就是手机号,对应倡议书 §六「Type C++ 把手机号写回」。🛑 **兜底是白名单不是通用判据**,目前只认 `could not verify` / `couldn't verify` / `unable to verify` 三个串,出现新文案必须往 SQL 里加,否则静默漏掉。🛑 **空回复与 `launch_gate.py` 的归零条件 Z1 同判据**,两处必须一致。｜ Daily quality alerts on model-generated replies: blanks, fallbacks, leaked phone/email, Arabic gender-slash template residue.")),
   ("chat_quality_lang_mismatch", "语言错配 · Chat Quality — Language Mismatch", "table",
       # 2026-10-28 新建(Metabase 卡 450)。出处:埋点需求 §7「语言对不上」。
       # 🛑 **不和 449 合卡**:449 的分母是 host 回复条数,本卡是「用户问—host 答」的
       #   配对数,两者不是一回事。口径清单 ⑥:分母不同必须拆成两张。
       # 【展示形式】表格,一行 = 一天 × 用户用的书写系统 —— 要回答的是
       #   「**哪种语言的用户**被用别的语言回」,是二维问题,折线画不下;
       #   且各语言配对量差两个量级(拉丁 8 千/天、天城文个位数)。
       dict(top=40,
            cols=[("date_msg","日期 Date","text"),
                  ("user_script","用户书写系统 User Script","text"),
                  ("pairs","配对数 Pairs","int"),
                  ("mismatch_pairs","错配 Mismatch","int"),
                  ("mismatch_pct","错配率 %","d1")],
            bar=["pairs","mismatch_pct"],
            note="🛑 **本卡判的是「书写系统」不是「语言」** —— 判据是 Unicode 码点区间(阿拉伯/天城文/西里尔/中日韩/谚文/假名/泰文/拉丁)。⇒ **拉丁字母内部的错配判不出来**(用户用西班牙语、host 用英语回,两边都是拉丁,本卡算「对上了」)。所以 `错配` 是**下界不是真实量**,语言级判定要等 System A 回传(埋点需求 §7 原本就派给他们)。**不要拿它当「语言错配率」对外报。** 🛑 配对取法:同一 `session_id` 内按 `add_on, id` 排序,只取**紧挨着**的 (user → host);中间隔了别的消息的不算,宁可少算不错算。`add_on` 只到秒,必须拿自增 `id` 当第二排序键,否则同秒两条的先后在两次跑之间会变(卡 437 踩过)。🛑 **只看 `modality='text'`** —— 语音那侧 content 是转写文本,转写本身可能换语言,会把 ASR 的问题算到回复头上。🛑 分母不足 30 的格子整行不出。🛑 剔除规则与「对话质量每日告警」**完全一致,两张必须同步改**。🔴 10-28 实测:天城文用户 10-20 当天 44 配对 **错配 15 = 34.1%**;拉丁 10-26/10-27 由常态 0.6% 升到 **2.8%/2.6%**。｜ Lower-bound language mismatch by writing system; Latin-internal mismatches are not detectable here.")),
   ("risk_ref_photo_uploads", "合照参考照上传量 · Reference Photo Uploads", "table",
       # 2026-10-20 新建(Metabase 卡 426)。🔴 合照功能还不存在,但用户已经在上传真人照片。
       #   10-17 起累计 36 张在库,10-20 单日 20 张(15 人),在加速。
       #   这张卡盯的是存量风险,不是增长 —— 产品要定先关入口还是加文案。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("uploaded","当天上传 Uploaded","int"),
                  ("uploaded_users","上传人数 Users","int"),
                  ("later_deleted","其中后被删 Deleted","int"),
                  ("active_cumulative","累计仍在库 Active","int"),
                  ("card_shown_devices","客户端·卡片展示 Shown","int"),
                  ("add_tap_devices","客户端·点添加 Add","int"),
                  ("set_ok_devices","客户端·设置成功 Set OK","int")],
            bar=["active_cumulative","uploaded"],
            note="🔴 **这张卡看的是风险不是增长**:合照算法还没做,但真人照片已经在进库。「累计仍在库」是按天滚动的存量,产品决定前应该盯着它。🛑 服务端 soulmap_user_media 是权威数,客户端三列只做补充 —— 它们在 sp_step 的 params.step 里(不是独立事件名)。🛑 firebase 是 T+1 入库,客户端三列**最后一天通常是 0**,不是没人用。｜ Risk monitor, not a growth metric: users are uploading real photos for a feature that does not exist yet.")),
 ]),
 ("⑫ Super Power", [
   ("power_modes_entry_funnel", "四种模式入口三层 · Power Modes — Entry Funnel", "table",
       # 2026-10-27 新建(Metabase 卡 447)。SQL 来自本地 soulmap_dashboard/Metabase/
       #   「模式_四种模式入口三层 · Power Modes — Entry Funnel.sql」,口径依据客户端 214。
       # 🛑 日度一个比率都不给:日度分子只有 2~3 台,按天算会得到「5.0%→8.1% 涨了六成」,
       #   实际是 2 台变 3 台。唯一的比率是七天滚动,且滚动分子不足 10 台输出空。
       dict(top=40,
            cols=[("date","日期 Date","text"),
                  # 2026-10-29 新增。3.9.0 换成胶囊入口,和 3.8.1 的「+」不是同一个交互,
                  # 并成一行会把两套入口的点开率平均掉 —— 所以按版本拆行,不是按版本筛。
                  ("app_version","版本 Version","text"),
                  ("a_class_chat_opener_devices","开过A类 A-class","int"),
                  ("layer_1_plus_shown_devices","①看到「+」Shown","int"),
                  ("layer_2_plus_tapped_devices","②点「+」Tapped","int"),
                  ("layer_3_menu_picked_devices","③选了模式 Picked","int"),
                  ("layer_3_menu_dismissed_devices","③关掉菜单 Dismissed","int"),
                  ("layer_4_start_tapped_devices","④点开始 Start","int"),
                  ("layer_5_started_ok_devices","⑤跑起来 OK","int"),
                  ("layer_5_blocked_by_paywall_devices","⑤被付费墙挡 Blocked","int"),
                  ("plus_tap_rate_trailing_7d_pct","点开率(7天滚动)%","d1")],
            bar=["layer_1_plus_shown_devices","layer_2_plus_tapped_devices"],
            note="🔴 **「+」不是没显示出来,是显示了没人点**:10-23~10-26 实测 100 台看到、**只有 5 台点**,漏损全在这一跳;后面选模式 2 台、点开始 2 台、**真的跑起来 0 台**(两台真实用户 100% 被 `purchase_required` 挡掉,唯二成功的是测试机)。🛑 **曝光机制没问题** —— 打开过 A 类角色的 105 台里 104 台看到了「+」(99.0%)。**天花板是 A 类进入量**:609 台进过聊天的设备里只有 105 台开过 A 类(17.2%),「+」压根不在另外 586 台屏上出现过。🛑 **已硬编码剔掉 4 台内部测试机**(SG Google / SG Apple / CN Xiaomi ×2)—— 不剔会把结论读反。🛑 **日度不给比率**,分子只有 2~3 台;七天滚动分子不足 10 台时那列为空(现在是 5,所以空的)。🛑 **版本白名单要手工维护**,MySQL 里 `'3.8.10' < '3.8.9'`,漏加新版的表现是分母骤降、点开率虚高。🔴 **2026-10-29 已加 3.9.0**(10-28 发版,埋点侧当天 8 台 / 119 条 `sp_step`,此前一条都没被本卡数到),并**新增版本列**:3.9.0 换成胶囊入口,和 3.8.1 的「+」不是同一个交互,合在一行会把两套入口平均掉;七天滚动窗同步按版本分区。3.9.0 现在只有个位数设备,比率列按 ≥10 台的门槛留空 —— **那是对的,不是漏数**。｜ The「+」is shown but not tapped: 100 devices saw it, 5 tapped, 0 completed. 3.9.0 added 2026-10-29, split by version.")),
   ("sp_memories_usage", "我们的回忆页使用 · Memories Page Usage", "table",
       # 2026-10-20 新建(Metabase 卡 428)。Super Power 里唯一对所有角色都开的入口。
       # 🛑 这几步不是独立事件名,是 sp_step 的 params.step 取值 —— 按事件名查会一条都查不到。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("entry_tap_devices","点入口 Entry","int"),
                  ("open_devices","打开 Open","int"),
                  ("loaded_devices","加载完 Loaded","int"),
                  ("loaded_nonempty_devices","其中有内容 Non-empty","int"),
                  ("nonempty_rate","有内容率 Non-empty %","pct1"),
                  ("filter_devices","用了筛选 Filter","int"),
                  ("more_tap_devices","点更多 More","int")],
            bar=["entry_tap_devices","nonempty_rate"],
            note="🛑 **有内容率低是正常的,不是 bug** —— 入口对所有角色显示,大部分人的回忆本来就是空的。实测 98 台用过、只有 1 台真有内容。🛑 三级**不是严格嵌套**(点入口/页面打开/数据加载完),loaded 可能多于 open(重复加载或筛选触发),**不要相除当转化率**,只看量级是否匹配。🛑 firebase 是 T+1 入库,最后一天通常偏低。｜ A low non-empty rate is expected: the entry shows for every character. The three steps are NOT a nested funnel.")),
 ]),
 ("⑬ 附录 · Appendix", [
   ("search_zero_result_by_length", "搜索零结果 × 词长 · Zero-Result by Query Length", "table",
       # 2026-10-27 新建(Metabase 卡 445)。新语义搜索 2026-10-26 15:14 上线,
       #   现有 discover_search_usage 只给整体率、不给分布,而新旧对比必须按词长分档。
       dict(top=60,
            cols=[("date","日期 Date","text"),
                  ("query_len_bucket","词长 Query Length","text"),
                  ("searches","搜索次数 Searches","int"),
                  ("zero_results","零结果次数 Zero","int"),
                  ("zero_result_pct","零结果率 %","d1"),
                  ("avg_result_count","平均结果数 Avg Results","int")],
            bar=["searches","zero_result_pct"],
            note="🔴 **旧搜索:用户打得越完整越找不到** —— 近 14 天 4,951 次实测,1 字 2.0%、3 字 19.9%、5 字 45.8%、6 字 64.4%、7-10 字 57.0%、**11+ 字 82.3%**。这正是换语义搜索的理由。🛑 **比整体率会低估改善幅度**,因为改善集中在长词那一段。🛑 `query_len` / `has_result` / `result_count` 在埋点里是**浮点**(`3.0`/`1.0`),写 `='0'` 一行都匹配不到且不报错,必须数值比较。🛑 **服务端 `catalogue_search` 的 payload 里没有词长**,拆不了档,所以只能走埋点(**T+1**,最后一天天然缺)。🛑 **这张卡只说明「有没有返回」,说明不了「返回得对不对」** —— 向量匹配几乎总能返回些东西,零结果率会趋近 0,后者看配套那张「搜索结果相关性」。｜ Zero-result rate by query length; the old search failed hardest on long queries.")),
   ("search_result_relevance", "搜索结果相关性 · Search Result Relevance", "table",
       # 2026-10-27 新建(Metabase 卡 446)。和上面那张成对,**必须一起读** ——
       #   语义搜索上线后零结果率趋近 0,那张卡就只剩「有没有返回」一个信息,
       #   换搜索这件事用它验收不了。这张回答另一半:返回得对不对。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  ("searches","搜索次数 Searches","int"),
                  ("searches_with_result","有结果 With Result","int"),
                  ("result_taps","点了结果 Taps","int"),
                  ("tap_rate_pct","点击率 %","d1"),
                  ("suggestion_taps","点了建议 Suggestion Taps","int"),
                  ("avg_tap_position","点击位次(均值)Avg Pos","d1"),
                  ("top3_tap_pct","点在前三 %","d1")],
            bar=["searches","tap_rate_pct"],
            note="🛑 **分母是「有结果的搜索次数」,不是全部搜索** —— 零结果的本来就没得点,混进分母会让点击率随零结果率一起动,两个指标就纠缠了。🛑 **判相关性看 `top3_tap_pct`,不要看位次均值** —— 均值会被个别深翻的人拉得很偏(10-24 实测 97.8,是少数人翻到几十位之后点的)。🛑 `search_suggestion_tap` 是**搜索建议**不是结果,单列、不并进点击率。⚠️ **切换日 2026-10-26 15:14**,当天是新旧混合,跨这一天要当成两段读。设备级,埋点 **T+1**。｜ Did people click what the search returned — the other half of the zero-result card.")),
   ("retention_d1", "留存 D1 · 设备级 · Retention D1 (device)", "long_dim",
       # 🛑 2026-10-27 卡头补口径(口径清单 ② / ⑥)。SQL 没动,只写清楚这是哪一套。
       dict(rate=("retained_users","new_users"), **RETENTION_DIMS,
            note="🛑 **设备级**:次日开 App 的设备 ÷ 装机当天的新设备,回访 = `session_start`。🛑 **这一套和 D3 / D7 同源同层级,留存曲线要连着读就用这张** —— 另一张「有效留存 D1」是**账号级、分子是发消息**,两者差 1.4 倍(实测同一批人:次日有启动 11.5% / 次日有发消息 9.4% / 既启动又发消息 8.3%),**不要互相比、不要相除**。🛑 北极星到底用哪一套待 Javier 拍板(口径清单第 ② 条),定之前这个数只当参考。｜ Device-level D1, same basis as D3/D7. Do not compare against the account-level card.")),
     ("growth_new_activated_user", "深度新用户数 · Deep New Users", "line", dict(val="value", cap=12,
       note="新用户中对话≥5轮的人(1问1答=1轮) ｜ New users reaching ≥5 conversation turns (1 exchange = 1 turn)",
       rollup={"country": 20},
       dims=[("overall","Overall",None),("source","by source","source"),("adgroup","by source×adgroup",_ADG),("country","by country","country")])),
   ("module_tab_penetration", "三 Tab 渗透率 · Three-Tab Penetration", "rate",
       dict(rate=("tab_users","active_users"), fmt="pct0",
                        note="访问过该 Tab 的人 ÷ 当天DAU ｜ Users who opened each tab ÷ that day's DAU", order=["Chat","Discover","Me"], dims=[("tab","","tab")])),
   ("module_tab_opens_per_user", "人均 Tab 打开次数 · Tab Opens per User", "rate", dict( note="该 Tab 打开次数 ÷ 当天DAU ｜ Tab opens ÷ that day's DAU",rate=("tab_opens","active_users"), pct=False, fmt="d1", order=["Chat","Discover","Me"], dims=[("tab","","tab")])),
   ("discover_search_usage", "搜索使用与结果质量 · Search Usage & Result Quality", "table",
       # 2026-09-09 新建。选表格不选折线:13 个指标折线放不下,而零结果率需要精确读数
       #   (40.0% 与 52.0% 的差别要看得出);且日均仅 33–467 次搜索、6–70 用户,折线噪声大。
       #   表格按 date 倒序 —— 纵向扫一列看趋势,横向扫一行看当天横截面,两种读法都在。
       # 不写 sort = 保持 SQL 的 ORDER BY date DESC(行序有含义)。
       dict(top=30,
            cols=[("date","日期 Date","text"),
                  # 2026-10-29 新增。30 天窗里有三代搜索,zero_result_rate 不是同一个指标。
                  ("search_era","搜索世代 Era","text"),
                  ("discover_users","发现页用户 Discover","int"),
                  ("search_users","搜索用户 Searchers","int"),
                  ("search_penetration_rate","搜索渗透率 Penetration","pct1"),
                  ("search_count","搜索次数 Searches","int"),
                  ("searches_per_user","人均次数 per User","d1"),
                  ("distinct_query_count","不同 query Distinct","int"),
                  ("repeat_search_rate","重复搜索率 Repeat","pct1"),
                  ("zero_result_count","零结果 Zero","int"),
                  ("zero_result_rate","零结果率 Zero %","pct1"),
                  ("narrow_result_count","1-20 结果","int"),
                  ("broad_result_count","21-399 结果","int"),
                  ("near_full_result_count","400+ 结果","int")],
            bar=["search_penetration_rate","zero_result_rate"],
            note="🔴 **2026-10-29 新增「搜索世代」列**:本卡 30 天窗里有**三代搜索** —— 10-26 15:14 换语义搜索(向量匹配)、10-28 18:22 按角色打分全量重排。🛑 **`零结果` 不是同一个指标**:向量匹配几乎总能返回些东西,实测零结果数 10-23~10-25 的 113 / 85 / 39 → 切换当天 32 → **之后每天都是 0**。那不是「搜不到的少了」,是「搜不到」不再以零结果的形式出现;`窄/宽/接近全量` 三档的分界在两代之间同样不可比。10-26 和 10-28 两天是切换当天,新旧混合,单独标出。｜ Three search generations in this 30-day window; zero-result rate is not comparable across them. 搜索框只在发现页里，所以渗透率的分母是当天打开过发现页的人，不是 DAU。零结果率四成以上：分子是 resultCount=0 的搜索次数，分母是当天全部搜索次数。「400+ 结果」不等于全量（角色库 865），只是筛得很宽。本卡不提供搜索→点击转化：catalogue_search 没有 slate_id，点击事件也区分不出是搜来的还是逛来的。这条通道批量上传，最后 1–2 天必然偏低，不要拿来做对比；数据下限 2026-09-02。 ｜ Penetration denominator is users who opened Discover that day, not DAU. Zero-result rate is above 40%. No search-to-tap conversion available. The last 1-2 days are always low (batched upload).")),
   ("discover_click_position_distribution", "点击位次分布 · Click Position Distribution", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct0", **POSITION_DIMS,
            note="每个子 tab 里,点击落在哪些位次档(占该 tab 当天点击的比例);只用点击侧数据,不含曝光。🛑 **2026-10-29 补断点**:**10-28 18:22 搜索结果按角色打分全量重排、不留对照组**,**只影响 `search` 这一档**(all / everyday / fantasy / foryou 的排序没动,跨 10-28 照常比)。台账存的基线:搜索后第 1 位点击率 31.5% / 第 2 位起 3.3~5.3%。更早还有 **10-26 15:14 换语义搜索**,换的是召回集合,`search` 档的位次分布在 10-26 前后同样不可比。本卡按天 × sub_tab 出行,不跨天汇总,切点不会被 SQL 抹平 —— 要当心的是把 30 天平着看。｜ Tap-side only. The `search` sub-tab was re-ranked 10-28 18:22 (full rollout, no control); other tabs unaffected.")),
   ("discover_character_daily_ctr", "每日角色 CTR · Daily CTR by Character", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct1", **CHAR_DAILY_CTR_DIMS,
            note="🔴 **2026-10-29 口径变更:`foryou` 加进了曝光白名单** —— 此前白名单是 `all/everyday/fantasy`,而 **`all` 早已恒为 0**(近 21 天只有 11 次),等于只算了 `everyday`+`fantasy`,**占全部角色卡曝光的 16.4%**(10-27)。改后分母 2,236 → 12,533(5.6 倍),CTR 3.49% → 4.37%,波动由 2.26~5.07% 收窄到 4.12~4.58%,与服务端独立算出的 foryou CTR 4.58% 相互印证。🛑 **跨 10-29 不要前后对比**。🛑 `search` 有意不加(搜索带意图,与浏览不同质)。每天各角色在目录里的点击 ÷ 曝光,按累计点击取 top 10 ｜ Daily taps ÷ impressions per character in the catalogue, top 10 by cumulative taps"
                 "曝光少的角色开头几天 CTR 会偏高再回落,那是小样本收敛不是变差 ｜ "
                 "Daily taps ÷ impressions per character, top 10 by cumulative taps (<20 dropped)")),
   ("discover_character_by_tile", "角色卡漏斗分场景 · Character Funnel by Tile", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct1", **TILE_DIMS,
            note="🔴 **2026-10-29 口径变更:`foryou` 加进了曝光白名单** —— 此前白名单是 `all/everyday/fantasy`,而 **`all` 早已恒为 0**(近 21 天只有 11 次),等于只算了 `everyday`+`fantasy`,**占全部角色卡曝光的 16.4%**(10-27)。改后分母 2,236 → 12,533(5.6 倍),CTR 3.49% → 4.37%,波动由 2.26~5.07% 收窄到 4.12~4.58%,与服务端独立算出的 foryou CTR 4.58% 相互印证。🛑 **跨 10-29 不要前后对比**。🛑 `search` 有意不加(搜索带意图,与浏览不同质)。角色卡按场景类别的三级转化:曝光→点击→开聊→深聊(≥5轮);曝光按(用户×角色×日)去重 ｜ Three-step conversion by scene category: impression → tap → chat → deep (≥5 turns); impressions deduped per user × character × day")),
   ("discover_character_coverage", "角色覆盖 · Character Coverage", "line",
       dict(val="characters", cap=4,
            note="🔴 **2026-10-29 口径变更:`foryou` 加进了曝光白名单** —— 此前白名单是 `all/everyday/fantasy`,而 **`all` 早已恒为 0**(近 21 天只有 11 次),等于只算了 `everyday`+`fantasy`,**占全部角色卡曝光的 16.4%**(10-27)。改后分母 2,236 → 12,533(5.6 倍),CTR 3.49% → 4.37%,波动由 2.26~5.07% 收窄到 4.12~4.58%,与服务端独立算出的 foryou CTR 4.58% 相互印证。🛑 **跨 10-29 不要前后对比**。🛑 `search` 有意不加(搜索带意图,与浏览不同质)。🛑 **2026-10-29 窗口由近 30 天缩到近 14 天**(四张 Discover 卡一起,原因见「角色表现榜」卡头)。每天被曝光 / 被点击过的角色个数(不是用户数)⚠️ 卡头写的「目录共 445 个角色」是旧数,**口径清单 ⑬ 已把「上线可见角色数」定为 764**(`enabled=1 AND discoverable=1 AND review_status='approved'`),这里待同步 ｜ Number of distinct characters impressed / tapped each day (not users); the catalogue holds 445",
            dims=[("metric","","metric")])),
   ("discover_click_destination", "点击去向 · Click Destination", "line", dict(
            note="点击后跳去哪:站内详情 / 外链 / 付费墙 ｜ Where a tap goes: in-app detail / external link / paywall",val="taps",
       dims=[("overall","Overall",None),("destination","by destination","destination")])),
   ("discover_preference_distribution", "用户偏好分布 · Preference Distribution", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct0", **PREFERENCE_DIMS,
            note="用户在 Preferences 面板设置的偏好占比,分母 = 当天成功写入 profile 的用户数;主题为多选,各线之和大于 100% ｜ Preferences set in the Preferences panel, over users whose profile was written that day; themes are multi-select so the lines sum to over 100%")),
   ("chat_turns_distribution", "每场对话轮数 · Turns per Session (avg)", "line", dict(val="turn_count", agg="avg",
       note="当天开始的每场会话的轮数,取平均(1问1答=1轮) ｜ Avg turns per session started that day (1 exchange = 1 turn)", dims=[("overall","Overall",None)])),
   ("chat_daily_msgs_per_user", "当天人均消息数 · Daily Msgs per User", "rate",
       dict(rate=("messages","users"), pct=False, fmt="d1",
            note="当天用户发出的消息数 ÷ 当天发过消息的用户数(不含AI回复) ｜ User messages that day ÷ users who sent at least one (AI replies excluded)",
            dims=[("overall","Overall",None)])),
   ("chat_session_duration", "对话时长 · Session Duration (avg min)", "line", dict(val="duration_min", agg="avg",
       note="当天开始的每场会话首末消息间隔,取平均(仅含 2 条以上消息的会话) ｜ Avg minutes from a session's first to last message, for sessions with 2+ messages",
       dims=[("overall","Overall",None)])),
   # —— 交互形态 · Interaction form ——
   ("chat_msg_length", "用户消息长度 · Msg Length (avg chars)", "line", dict(
            note="用户每条文字消息的字符数取平均 ｜ Avg characters per user text message",val="char_len", agg="avg",
       dims=[("overall","Overall",None)])),
   ("activation_ai_first_latency", "AI 首条响应时延 · AI First-Reply Latency (avg s)", "line", dict(
            note="每会话首次 composer 回复的耗时,每用户取最早一次再平均;不含前置组件,是真实等待的下限 ｜ Avg time for composer to generate the first reply; excludes upstream components, so a lower bound",val="avg_secs", agg="avg",
       dims=[("overall","Overall",None)])),
 ]),
 ("⑭ 历史队列 · Legacy Cohorts", [
   # 🛑 2026-10-27 新建分区。这里的卡**没有坏,也没有归档** —— 是它们描述的那个世界过去了,
   #   分母已经塌了,放在主位会让人以为还在看当下。
   #
   #   ① 分臂卡(A/B/C):**近一周新入组 A 臂 6 人、B 臂 3 人、C 臂 2,319 人** ——
   #      10-03 之后新用户几乎全进 C,那几张「分臂」实际只剩一列有数。
   #   ② 试用卡:**每天只有 0~4 人开试用**(10-21 开 1 / 买 0.99 15;10-27 开 0 / 买 2)。
   #      0.99 直购上线之后,试用这条路基本没人走了。
   #
   # 🛑 **一张都不要归档、不要删** —— 召回名单(ADDENDUM 第 4 条,A 组约 392 人)
   #   要用到试用结局的历史数据。移到这里只是让它们不占主位。
   # 🛑 `paywall_writeback_by_version` **没有跟着搬** —— 它的维度是客户端版本、没有 arm 列,
   #   测的是「服务端说该弹、客户端有没有回写」,和分臂塌不塌无关,留在 ⑧。
   ("paywall_trial_outcome_by_arm", "试用结局分臂 · Trial Outcome by Arm", "table",
       dict(top=30,
            cols=[("country_group","国家组 Country Group","text"),
                  ("arm","臂 Arm","text"),
                  ("trials","开过订阅 Trials","int"),
                  ("trials_intro","其中 0.99 Intro","int"),
                  ("trials_free7","其中 免费7天 Free7","int"),
                  ("in_trial","仍在试用 In Trial","int"),
                  ("canceled","试用期内取消 Canceled","int"),
                  ("canceled_after_expiry","到期后失效 Expired-Unsub","int"),
                  ("converted","转付费 Converted","int"),
                  ("billing_failed","扣款失败 Billing Failed","int"),
                  ("grace_period","宽限期 Grace","int"),
                  ("expired","已过期 Expired","int"),
                  ("pending_recheck","待复查 Pending","int")],
            bar=["trials"],
            note="🛑「开过订阅」含两种人:买 0.99(trials_intro)和开免费 7 天试用(trials_free7),已拆成两列。退订也有两种:试用期内取消(canceled)、退订后走到期末失效(canceled_after_expiry),两者不要相加当「退订」读。｜ Trials mix intro-paid and free-7-day; cancellation has two distinct shapes.")),
   ("paywall_tpc_by_country", "试用付费取消 · 按国家 · Trial-Paid-Cancel by Country", "table",
       dict(top=25,
            cols=[("country","国家 Country","text"),
                  ("new_users","新用户 New Users","int"),
                  ("trials","开订阅 Trials","int"),
                  ("trial_pct","开订阅率 %","d1"),
                  ("canceled","取消 Canceled","int"),
                  ("cancel_pct","取消率 %","d1"),
                  ("lost","流失 Lost","int"),
                  ("lost_pct","流失率 %","d1"),
                  ("user_unsubscribed","主动退订 Unsub","int"),
                  ("billing_failed","扣款失败 Billing Failed","int"),
                  ("billing_failed_share_of_lost","扣款失败占流失 %","d1"),
                  ("expired","过期 Expired","int"),
                  ("paid","付费 Paid","int"),
                  ("paid_pct","付费率 %","d1"),
                  ("arm_a_share","A 臂占比 %","d1"),
                  ("arm_b_share","B 臂占比 %","d1"),
                  ("arm_c_share","C 臂占比 %","d1")],
            bar=["new_users","paid_pct"],
            note="🛑 三个臂占比列是说这个国家的人怎么分到各臂的,不同国家的臂结构不同 —— 跨国比付费率之前先看这三列,差异可能来自分臂而不是国家。分子小于 10 的比率读不出来,不要排名。｜ Arm mix differs by country; check it before comparing paid rates across countries.")),
   ("paywall_tpc_by_creative", "试用付费取消 · 按素材 · Trial-Paid-Cancel by Creative", "table",
       dict(top=30,
            cols=[("creative_name","素材 Creative","text"),
                  ("creative_id","素材 ID","text"),
                  ("networks","渠道 Networks","text"),
                  ("campaign_name","Campaign","text"),
                  ("new_users","新用户 New Users","int"),
                  ("trials","开订阅 Trials","int"),
                  ("trial_pct","开订阅率 %","d1"),
                  ("canceled","取消 Canceled","int"),
                  ("cancel_pct","取消率 %","d1"),
                  ("user_unsubscribed","主动退订 Unsub","int"),
                  ("billing_failed","扣款失败 Billing","int"),
                  ("expired","过期 Expired","int"),
                  ("paid","付费 Paid","int"),
                  ("paid_pct","付费率 %","d1")],
            bar=["new_users","paid_pct"],
            note="🛑 素材名会重复,必须看 creative_id —— 实测同名素材有三个不同 ID,每装机收入差一倍以上。广告组也会改名,按名字归组会把同一组拆开。｜ Creative names repeat; always read creative_id.")),
   ("paywall_retention_by_arm", "分臂留存 · Retention by Arm", "table",
       dict(top=40,
            cols=[("install_date","装机日 Install Date","text"),
                  ("arm","臂 Arm","text"),
                  ("cohort_users","队列人数 Cohort","int"),
                  ("d1_users","D1","int"), ("d1_pct","D1 %","d1"),
                  ("d3_users","D3","int"), ("d3_pct","D3 %","d1"),
                  ("d7_users","D7","int"), ("d7_pct","D7 %","d1"),
                  ("maturity","成熟度 Maturity","text")],
            bar=["cohort_users","d1_pct"],
            note="🛑 先看 maturity 那列 —— 没满窗的队列 D3/D7 天然偏低,那不是留存变差。｜ Check the maturity column first; immature cohorts under-report D3/D7.")),
   ("paywall_arm_split_hourly", "分流比例逐小时 · Arm Split Hourly", "table",
       dict(top=48,
            cols=[("hour_sgt","小时(SGT) Hour","text"),
                  ("assigned","入组 Assigned","int"),
                  ("arm_a","A","int"), ("arm_c","C","int"),
                  ("pct_a","A %","d1"), ("pct_c","C %","d1"),
                  ("new_install_share","新装占比 %","d1"),
                  ("developed_four_assigned","发达四国入组 Dev4","int"),
                  ("developed_four_pct_a","Dev4 A %","d1"),
                  ("developed_four_pct_c","Dev4 C %","d1")],
            bar=["assigned"],
            note="用途是盯分流比例的变更点,逐行读。🛑 B 臂不在这张表里(写入条件不同,覆盖率太低,列出来会误导)。｜ For spotting when the split changed. Arm B is omitted — its assignment rows are too sparse to read.")),
 ]),
]

def _fmt_of(kind, pct, p):
    """每张图统一的小数格式:pct=百分比1位 / d1=1位小数 / int=整数。"""
    if p.get("fmt"): return p["fmt"]
    if pct: return "pct"
    if p.get("agg") == "avg": return "d1"
    return "int"

def _finish(dims, p):
    """按 order 固定序列顺序 + 按 slfmt 改序列名(如 25→25%、position→位N、reason→中文)。"""
    order, slfmt, only = p.get("order"), p.get("slfmt"), p.get("only")
    for dm in dims:
        if dm.get("key") == "overall":   # overall(总计)不参与 only/order/slfmt,避免被过滤或改名
            continue
        data = dm["data"]
        if only:
            data = {k: v for k, v in data.items() if k in only}
        if order:
            od = OrderedDict((k, data[k]) for k in order if k in data)
            for k in data:
                if k not in od: od[k] = data[k]
            data = od
        if slfmt:
            data = OrderedDict((slfmt(k), v) for k, v in data.items())
        dm["data"] = data
    return dims

def build_card(metrics, mid, title, kind, p):
    base = dict(id=mid, title=title, kind=kind, note=p.get("note"))
    try:
        if kind == "funnel":
            rows = metrics.get(mid) or []
            if not rows or "step" not in rows[0]: return None
            if "grp" in rows[0]:   # 分组对比漏斗(如 adgroup):每组一条,可切换;取 step1 最大的前 8 组
                groups = {}
                for r in rows:
                    g = str(r["grp"]); st = r["step"]
                    groups.setdefault(g, {}); groups[g][st] = groups[g].get(st, 0) + _num(r.get("users"))
                # 2026-09-20:改自然序。原按字符串排,步骤 ≥10 级时 '10_'/'11_' 会排到
                #   '1_' 前面,漏斗第一级变成最后一步、成了 100% 基准(护栏卡实测 624%/761%)。
                def _sk(st):
                    h = str(st).split("_", 1)[0]
                    return (int(h), str(st)) if h.isdigit() else (1 << 30, str(st))
                steps = sorted({r["step"] for r in rows}, key=_sk); s1 = steps[0] if steps else None
                if p.get("gsort") == "version":   # 按版本号从大到小(如 2.5.1 > 2.5.0 > 2.4.2)
                    def _vk(g):
                        try: return tuple(int(x) for x in str(g).split("."))
                        except ValueError: return (0,)
                    order = sorted(groups, key=_vk, reverse=True)[:8]
                else:                              # 默认按 step1 量最大排
                    order = sorted(groups, key=lambda g: groups[g].get(s1, 0), reverse=True)[:8]
                base.update(steps=steps, weeks=order, defwk="first",
                            matrix={st: {g: groups[g].get(st, 0) for g in order} for st in steps})
                return base
            wcol = "wk_start" if "wk_start" in rows[0] else ("wk" if "wk" in rows[0] else None)
            if wcol:  # 长表(自动滚动近四周):step, wk_start, users
                def _wl(iso):   # 周六起始 → "M/D–M/D"(整周区间,别被当成单日)
                    d0 = datetime.strptime(iso, "%Y-%m-%d"); d1 = d0 + timedelta(days=6)
                    return f"{d0.month}/{d0.day}–{d1.month}/{d1.day}"
                wks = sorted({_nd(r[wcol]) for r in rows})[-4:]           # 最近 4 个版本周
                wmap = {w: _wl(w) for w in wks}
                matrix = {}
                for r in rows:
                    w = _nd(r[wcol])
                    if w not in wmap: continue
                    st = r["step"]; matrix.setdefault(st, {})
                    matrix[st][wmap[w]] = matrix[st].get(wmap[w], 0) + _num(r.get("users") or r.get("value"))
                base.update(steps=sorted(matrix.keys()), weeks=[wmap[w] for w in wks], matrix=matrix, defwk="last")
            else:     # 旧宽表:step + 各周列(动态读,不依赖 WEEK_ORDER)
                weeks = [k for k in rows[0].keys() if k != "step"]
                base.update(steps=[r["step"] for r in rows], weeks=weeks,
                            matrix={r["step"]: {w: _num(r.get(w)) for w in weeks} for r in rows})
            return base
        if kind == "table":
            # 表格卡:SQL 出什么就铺什么,渲染器不做聚合。用于排行榜这类
            # 折线/漏斗表达不了的形态(行数多、每行是一个实体、多列指标并列)。
            rows = metrics.get(mid)
            # 🛑 2026-10-22:`empty_ok=True` 的卡,**零行是结论不是故障**,要照常出卡
            #   (只有表头 + 卡头注释,前端显示「0 行」)。
            #   起因:431 每天续费 —— 全库没有一个人扣过第二次钱,这正是要让人看到的事;
            #   按老逻辑 return None,卡直接从看板上消失,那个结论也跟着没了,
            #   而且页头的「缺 N」会把它算成一张抓失败的卡。
            #   不加这个开关的卡保持原样:空 = 当缺卡处理,免得真的取数坏了被静默吞掉。
            if not rows:
                if not p.get("empty_ok"): return None
                base.update(kind="table", fmt=None,
                            cols=[{"k": c, "label": l, "fmt": f, "max": None}
                                  for c, l, f in p["cols"]],
                            rows=[], top=p.get("top", 20))
                return base
            # 🛑 2026-10-21:抓到的东西可能不是行数组 —— Metabase 出错时返回 HTTP 200 +
            #    错误对象(dict)。原来直接 rows[0] 会抛 KeyError: 0,卡上只显示「渲染失败: 0」,
            #    看不出到底怎么了。fetch 侧已加同样的检查,这里是第二道防线。
            if not isinstance(rows, list) or not isinstance(rows[0], dict):
                raise ValueError(
                    f"抓到的不是行数组({type(rows).__name__}),很可能是 Metabase 的错误响应:"
                    f"{str(rows)[:160]}")
            cols = p["cols"]                      # [(列名, 表头, 格式)] 顺序即显示顺序
            miss = [c for c, _l, _f in cols if c not in rows[0]]
            if miss:
                raise ValueError(f"table 卡缺列 {miss},SQL 实际列: {list(rows[0])}")
            # sort 不填 = 保持 SQL 的 ORDER BY(2026-08-20 改)。
            # 改前是「不填就按 cols 第一列降序」,结果「行序本身有含义」的表(如用量分位的
            # 人群×计量口径)在 DataGrip 里对、上了看板就乱 —— 渲染器不该替 SQL 决定行序。
            # 代价:SQL 忘写 ORDER BY 的话行序就是数据库返回的顺序。写表格卡记得加 ORDER BY。
            srt = p.get("sort")
            if srt:
                rows = sorted(rows, key=lambda r: _num(r.get(srt)), reverse=True)
            # bar=需要画格内条形的列;每列各自按本列最大值归一化
            bars = {c: max([_num(r.get(c)) for r in rows] + [0]) for c in (p.get("bar") or [])}
            base.update(kind="table", fmt=None,
                        cols=[{"k": c, "label": l, "fmt": f, "max": bars.get(c)} for c, l, f in cols],
                        rows=[{c: r.get(c) for c, _l, _f in cols} for r in rows],
                        top=p.get("top", 20))
            return base
        if kind == "long_dim":
            # 长维度形状:一张卡自带全部维度,SQL 输出 date | dimension | dimension_value | 值列…
            # 每个 dimension 取值 = 一个维度选项卡,dimension_value = 该选项卡里的各条线。
            rows = metrics.get(mid)
            if not rows: return None
            r0 = rows[0]
            dim_col = "dimension" if "dimension" in r0 else ("dim_name" if "dim_name" in r0 else None)
            val_col = "dimension_value" if "dimension_value" in r0 else ("dim_value" if "dim_value" in r0 else None)
            if not dim_col or not val_col:
                raise ValueError(f"long_dim 需要 dimension/dimension_value 列,实际列: {list(r0)}")
            dc = _dc(rows)
            labels = p.get("dimlabels") or {}
            order  = p.get("dimorder") or []
            slorder = p.get("slorder") or {}          # 某个维度内部的固定线序
            buckets = defaultdict(list)
            for r in rows:
                buckets[str(r.get(dim_col))].append(r)
            keys = [k for k in order if k in buckets] + [k for k in buckets if k not in order]
            dims = []
            # 率类卡按"量"筛线,不按率:否则只有 1 个用户、恰好回访的小国会以 100% 排在最前
            # 排线/过滤用哪一列的"量":默认率卡用分母、量卡用值列。
            # volcol 可整卡指定,也可 {维度: 列} 分维度指定 —— 角色卡 CTR 必须按分子(点击)排,
            # 因为目录按字母序展示,曝光被顶得人人相近(实测 top5 全是 A 开头、都是 ~1960),
            # 按曝光取 top10 等于按首字母取,真正高 CTR 的角色永远进不来。
            volcol_cfg = p.get("volcol")
            # min_vol 可以是数,也可以是 {维度: 数} —— 同一张卡的各选项卡分母量级可能差几十倍
            # (实测角色卡漏斗:tap_rate 分母=曝光 最大 17379,chat_rate 分母=点击 最大 682,差 25 倍),
            # 用单一阈值会把小分母那个选项卡的线几乎全滤光。
            min_vol_cfg = p.get("min_vol", 0)
            for k in keys:
                min_vol = min_vol_cfg.get(k, 0) if isinstance(min_vol_cfg, dict) else min_vol_cfg
                vc = volcol_cfg.get(k) if isinstance(volcol_cfg, dict) else volcol_cfg
                vol_col = vc or (p["rate"][1] if p.get("rate") else p.get("val"))
                sub = buckets[k]
                volume = defaultdict(float)
                for r in sub:
                    volume[str(r.get(val_col))] += _num(r.get(vol_col))
                ser = _rate(sub, p["rate"][0], p["rate"][1], val_col, dc=dc) if p.get("rate") \
                      else _agg(sub, p["val"], val_col, p.get("agg", "sum"), dc=dc)
                if k in slorder:
                    # 固定线序;但同样按量过滤 —— 否则刚上线的小主题(如 1 人 100%)会以噪音线混进来
                    ser = OrderedDict((s2, v) for s2, v in ser.items() if volume.get(s2, 0) >= min_vol)
                    ser = _ord(ser, slorder[k])
                else:
                    keep = [s for s in sorted(ser, key=lambda s: volume.get(s, 0), reverse=True)
                            if volume.get(s, 0) >= min_vol][: p.get("cap", 8)]
                    ser = OrderedDict((s, ser[s]) for s in keep)
                dims.append({"key": k, "label": labels.get(k, "by " + k), "data": dict(ser)})
            if not any(d["data"] for d in dims): return None
            base.update(kind="line", pct=bool(p.get("rate")),
                        fmt=p.get("fmt", "pct" if p.get("rate") else "int"), dims=dims)
            return base
        rows = metrics.get(mid)
        if not rows: return None
        if p.get("where"):
            wc, wv = p["where"]; rows = [r for r in rows if str(r.get(wc)) == wv]
            if not rows: return None
        dc = _dc(rows)
        pct = p.get("pct", kind == "rate")
        dims = []
        rollup = p.get("rollup") or {}
        for key, label, by in p["dims"]:
            # 该维度配了 rollup:把 cap 交给聚合函数,尾部并成「其他」而不是丢掉
            rcap = rollup.get(key)
            ser = _rate(rows, p["rate"][0], p["rate"][1], by, dc=dc, cap=rcap) if kind == "rate" \
                  else _agg(rows, p["val"], by, p.get("agg", "sum"), dc=dc, cap=rcap)
            if rcap:
                pass                                   # 已在聚合层截断+归并,不再走 _cap
            elif not (p.get("only") or p.get("order")):
                ser = _cap(ser, p.get("cap", 6))
            dims.append({"key": key, "label": label, "data": {s: pts for s, pts in ser.items()}})
        dims = _finish(dims, p)
        base.update(kind="line", pct=pct, fmt=_fmt_of(kind, pct, p), dims=dims)
        return base
    except Exception as ex:
        base.update(kind="line", pct=False, fmt="int", dims=[], error=str(ex))
        return base

# ---------- 柔和统一配色 ----------
# 2026-09-10 由 8 色扩到 20 色。
#   改了什么:前 8 个保持原值不变(既有卡的配色不动),后面补 12 个。
#   为什么:by country 的 rollup 从 12 调到 20(见下),而前端取色是 P[i%P.length] ——
#          8 色下 20 条序列每色要重复 2~3 次,图例无法辨认。
#   后 12 个的构成:4 个原调色板没占用的色相(黄绿/青/品红/珊瑚)+ 原 8 色的深色版。
#   影响:第 9 条及以后的序列换色;前 8 条不变。深浅两档在明暗两种主题下都测过可读。
PAL = ["#6f9de0", "#5cbfa6", "#e0b366", "#9a8cd9", "#e0899f", "#7cc490", "#8b98ac", "#d69a72",
       "#8fb84a", "#4aa8c4", "#c46fb8", "#d4665c",
       "#3f6fb0", "#2f8f78", "#b0873a", "#6f5fa8", "#b05f78", "#4f9460", "#5b6878", "#a86f48"]
WKPAL = ["#bcd3f2", "#8fb4e6", "#6f9de0", "#4a79c9"]   # 4 版本周,由浅到深(旧→新)

# 卡名别名:现 Metabase 卡名 → 权威清单 metric_id(两种名字都能认)
ALIAS = {
    "growth_new_users": "growth_new_user",
    "growth_activated_new_users": "growth_new_activated_user",
    "growth_deep_new_users": "growth_new_activated_user",   # 2026-08-14 卡名 Activated → Deep(阈值≥3→≥5);旧名保留以便回滚
    "activation_first_msg_latency": "activation_user_first_latency",
    # 2026-08-18 卡名 card ctr → position ctr;Metabase 若未同步改名,旧名兜底
    "discover_character_card_ctr": "discover_click_position_distribution",
    "growth_meta_qcd_trend_by_creative": "growth_meta_daily_qcd_by_creative",
    "growth_meta_qcd_by_creative":       "growth_meta_daily_qcd_by_creative",
    "discover_character_position_ctr": "discover_click_position_distribution",
}

CSS = """
/* 不用 table-layout:fixed —— 固定布局会按列数均分宽度,长角色名和 host_id 必被截断。
   改成按内容撑开(min-width:100% 保证不足一屏时仍铺满),放不下由 .tblwrap 横向滚动。 */
.tbl{width:max-content;min-width:100%;border-collapse:collapse;font-size:12px}
.tbl th{position:sticky;top:0;background:var(--plane);color:var(--ts);font-weight:600;
  text-align:left;padding:7px 8px;border-bottom:1px solid var(--bd);white-space:nowrap;z-index:1}
.tbl td{padding:6px 8px;border-bottom:1px solid var(--grid);color:var(--tp);white-space:nowrap}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover td{background:var(--plane)}
.tbl .num{text-align:right;font-variant-numeric:tabular-nums}
.tbl .bar{position:relative}
.tbl .bar>i{position:absolute;left:0;top:3px;bottom:3px;border-radius:2px;
  background:var(--acc);opacity:.16;pointer-events:none}
.tblwrap{max-height:380px;overflow:auto;border:1px solid var(--bd);border-radius:8px}
.tblmore{margin-top:8px;font-size:12px;color:var(--acc);cursor:pointer;user-select:none}
.tblmore:hover{text-decoration:underline}

:root{--surface:#fcfcfb;--plane:#f7f7f5;--tp:#1f2430;--ts:#5b6270;--mut:#9aa0ac;
--grid:#edeef1;--bd:#e7e8ec;--acc:#6f9de0;--stalefg:#9a6b2f;--stalebg:#f7efe1;--stalebd:#e3cfa8}
:root[data-theme=dark],@media (prefers-color-scheme:dark){}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--surface:#1b1c1f;--plane:#141517;--tp:#f2f3f5;
--ts:#b7bcc7;--mut:#7f8794;--grid:#2a2c30;--bd:#2f3237;--acc:#8fb4e6;--stalefg:#d9b076;--stalebg:#2b2519;--stalebd:#4a3f28}}
:root[data-theme=dark]{--surface:#1b1c1f;--plane:#141517;--tp:#f2f3f5;--ts:#b7bcc7;--mut:#7f8794;--grid:#2a2c30;--bd:#2f3237;--acc:#8fb4e6;--stalefg:#d9b076;--stalebg:#2b2519;--stalebd:#4a3f28}
*{box-sizing:border-box}body{margin:0;background:var(--plane);color:var(--tp);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;font-size:14px}
header{padding:22px 26px 8px}h1{margin:0;font-size:19px;font-weight:650}
.meta{color:var(--mut);font-size:12px;margin-top:4px}
.meta.lag{margin-top:6px;font-size:11.5px;line-height:1.5;max-width:1000px;opacity:.9}
h2{font-size:14px;color:var(--ts);font-weight:600;margin:24px 26px 10px;letter-spacing:.02em}
.grid-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;padding:0 26px}
@media (max-width:920px){.grid-cards{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--bd);border-radius:12px;padding:16px 18px 12px}
.card h3{margin:0 0 2px;font-size:14px;font-weight:600}
.toolbar{display:flex;gap:6px;margin:8px 0 4px;flex-wrap:wrap}
.tbtn{font-size:12px;color:var(--ts);background:transparent;border:1px solid var(--bd);
border-radius:999px;padding:3px 11px;cursor:pointer}
.tbtn.on{background:var(--acc);border-color:var(--acc);color:#fff}
.cw{position:relative;height:320px}
.empty{color:var(--mut);font-size:12px;padding:26px 0;text-align:center}
.banner{margin:8px 26px 2px;padding:10px 14px;border-radius:9px;font-size:12.5px;line-height:1.55;
background:rgba(240,180,60,.14);border:1px solid rgba(240,180,60,.55);color:var(--tp)}
/* 「今天变化最大的 5 个数」。五列网格:指标 | 比较的两天 | 前→后 | 变化量 | 切点提示。
   数字列一律 tabular-nums,否则五行的位数对不齐,一眼看不出谁大。
   窄屏(手机)退化成两列:指标占满一行,数字那组换行跟在下面。 */
.movers{margin:10px 26px 2px;padding:11px 14px 9px;border-radius:9px;
  background:var(--surface);border:1px solid var(--bd)}
.mv-h{font-size:13.5px;font-weight:700;color:var(--tp);margin-bottom:3px}
.mv-sub{font-size:11px;color:var(--mut);line-height:1.5;margin-bottom:8px}
.mv-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto minmax(0,1.1fr);
  gap:4px 14px;align-items:baseline;padding:5px 0;border-top:1px solid var(--grid)}
.mv-t{font-size:12.5px;color:var(--tp);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mv-s{color:var(--ts);font-weight:400}
.mv-dt{font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums;white-space:nowrap}
.mv-n{font-size:12.5px;color:var(--ts);font-variant-numeric:tabular-nums;white-space:nowrap}
.mv-n b{color:var(--tp)}
.mv-ar{color:var(--mut);padding:0 1px}
/* 🛑 涨跌不上色。这张榜什么卡都可能上(新用户数、零结果数、扣款失败数……),
   涨不等于好、跌不等于坏 —— 用红绿会替读者下一个这张卡给不出的判断。
   方向交给 ▲/▼,颜色只负责让数字跳出来。 */
.mv-d{font-size:12.5px;font-weight:700;font-variant-numeric:tabular-nums;
  white-space:nowrap;color:var(--tp)}
.mv-c{font-size:11px;color:var(--stalefg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mv-all-cut{font-size:11.5px;color:var(--stalefg);background:var(--stalebg);border:1px solid var(--stalebd);
  border-radius:6px;padding:5px 9px;margin:0 0 7px;line-height:1.45}
.mv-empty{font-size:12px;color:var(--mut);padding:6px 0}
@media (max-width:720px){
  .movers{margin:10px 14px 2px}
  .mv-row{grid-template-columns:auto auto 1fr}
  .mv-t{grid-column:1/-1}
  .mv-c{grid-column:1/-1;white-space:normal}
}
.cnote{color:var(--mut);font-size:11.5px;margin:1px 0 4px;line-height:1.4}
.chead{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.chead h3{margin:0 0 2px}
.latest{font-size:12px;color:var(--acc);font-weight:600;white-space:nowrap}
/* 沿用上一次数据的卡:虚线边 + 斜纹底 + 角标。只加文字容易被忽略,所以整卡降级 —— */
/* 一张画得好好的图在展示旧数据,是这套看板最容易骗到人的状态。 */
.stalefoot{margin-top:6px;font-size:10.5px;font-weight:600;color:var(--stalefg);text-align:left}
.stalefoot::before{content:'⟳ ';opacity:.8}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin:2px 0 5px}
.chip{font-size:11px;color:var(--ts);background:transparent;border:1px solid var(--bd);border-radius:999px;padding:2px 9px;cursor:pointer}
.chip.on{background:var(--acc);border-color:var(--acc);color:#fff}
.vlink{text-align:right;margin-top:4px;font-size:11.5px;color:var(--acc);cursor:pointer}
.vlink:hover{text-decoration:underline}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:20;align-items:center;justify-content:center}
.modalbox{background:var(--surface);border:1px solid var(--bd);border-radius:12px;width:min(1000px,92vw);max-height:88vh;overflow:auto;padding:18px 20px;position:relative}
/* 2026-09-09 表格详情用更宽的弹窗。卡片本身是两列网格里的半屏格子,13 列的表在那里必须
   横向滚才能读全;点 View details 后用这个尺寸,常见屏幕一屏放得下。
   只给表格加,折线/漏斗仍用 1000px —— 那两种图放大到 1800px 反而稀疏。 */
.modalbox.wide{width:min(1800px,96vw)}
/* 详情里的表格给到 70vh,而不是卡片里的 380px */
.tbldetail .tblwrap{max-height:70vh}
.mtitle{font-size:15px;font-weight:600;margin-bottom:10px;color:var(--tp);padding-right:24px}
.mbody{min-height:320px;height:64vh}
.mclose{position:absolute;top:10px;right:14px;border:none;background:transparent;font-size:17px;cursor:pointer;color:var(--ts)}
.frow{display:grid;grid-template-columns:128px 1fr 52px;align-items:center;gap:8px;margin:2px 0}
.fconn{display:grid;grid-template-columns:128px 1fr 52px;gap:8px}
.fconn>span{grid-column:2;text-align:center;font-size:10px;color:var(--mut)}
.flab{font-size:11.5px;color:var(--ts);text-align:right;line-height:1.2}
.fbarwrap{display:flex;justify-content:center}
.fbar{background:var(--acc);color:#fff;text-align:center;border-radius:5px;padding:5px 6px;font-size:11px;font-weight:600;white-space:nowrap;min-width:24px}
.fpc{font-size:11px;color:var(--ts);text-align:right;font-weight:600}
.meta.src{margin-top:6px;line-height:1.55;max-width:1100px}
.meta.src b{color:var(--ts);font-weight:600}
.nav{position:sticky;top:0;z-index:8;display:flex;gap:6px;flex-wrap:wrap;align-items:center;
padding:8px 24px;margin-bottom:4px;background:var(--plane);border-bottom:1px solid var(--bd)}
.nav .nb{font-size:12.5px;color:var(--ts);background:transparent;border:none;border-radius:7px;padding:5px 12px;cursor:pointer}
.nav .nb:hover{background:var(--surface)}
.nav .nb.on{background:var(--acc);color:#fff}
.nav .sp{flex:1}
section{scroll-margin-top:56px}
.theme{position:fixed;top:14px;right:18px;background:var(--surface);border:1px solid var(--bd);
border-radius:8px;padding:5px 11px;font-size:12px;cursor:pointer;color:var(--ts)}
"""

STALE_MAX_DAYS = 14   # 抓失败时沿用上一次的值,超过这个天数就让卡消失。
                     # 不设上限的话,长期超时的卡(AI 响应时延等)会永久显示冻结数据,
                     # 比"图不见了"更危险:看的人不会怀疑一张画得好好的图。
                     #
                     # 2026-09-07 临时 3 → 14:Metabase 主机 502(nginx 活着、后面的
                     # Java 进程连不上,/api/health 也 502),抓数在 login() 就失败,
                     # 流水线每次都死在第一步 —— 好处是 index.html 没被覆盖,页面冻在
                     # 最后一版;风险在恢复那一刻:沿用来源是上一版 index.html 本身,
                     # 只要有一次跑够 25 张卡过了 guard 就会渲染+push,此时超过上限的卡
                     # 被删掉,而卡一旦从 index.html 消失,下次连沿用的来源都没有了。
                     # 当时已有 1 张卡沿用到 2026-09-03(4 天,已过原来的 3 天线)。
                     # Metabase 稳定后调回 3 —— 14 天的冻结数据本身也是误导。


def _load_prev(out_path: Path) -> tuple[dict, str | None]:
    """从上一次写出的 index.html 里取回 DATA —— 这个文件是入库的,所以 checkout 就有。
    不用 actions/cache、也不必把几十 MB 的 raw_metrics.json 提交进仓库。
    返回 ({metric_id: 卡对象}, 上一版的数据日期)。任何解析失败都退化成"没有上一版"。"""
    try:
        html = out_path.read_text(encoding="utf-8")
        i = html.index("{", html.index("const DATA"))
        data, _ = json.JSONDecoder().raw_decode(html[i:])
        cards = {c["id"]: c for sec in data.get("sections", []) for c in sec.get("cards", [])
                 if c.get("id")}
        run_date = data.get("run_date")
        if not run_date:              # 老版本页面没往 DATA 里写 run_date,退回解析页头
            m = re.search(r"数据 (\d{4}-\d{2}-\d{2})", html)
            run_date = m.group(1) if m else None
        return cards, run_date
    except Exception:
        return {}, None


def _carry(prev_cards: dict, mid: str, prev_date: str | None):
    """这次没抓到 → 沿用上一次的卡。stale 记的是数据真正的日期,沿用链上不刷新,
    否则一张永久超时的卡会天天显示"昨天",永远不过期。"""
    card = prev_cards.get(mid)
    if not card: return None
    # 🛑 2026-10-22:不沿用「上一次就渲染失败」的卡。
    #   原来不检查 error,于是一张失败的卡会被每天捞出来重显示一遍,
    #   错误信息一路传下去 —— 实测 425 四道墙并排的 `渲染失败: 0` 就是这么挂了两天的,
    #   而且页头的「缺 N」数不到它(它被当成"沿用旧值"而不是"缺")。
    #   改后:上次失败 + 这次没抓到 → 这张卡**不显示**,并计入「缺 N」。
    #   宁可少一张,也不要显示一张带错误的僵尸卡。
    if card.get("error") is not None: return None
    stale = card.get("stale") or prev_date
    if not stale: return None
    try:
        age = (datetime.now().date() - datetime.strptime(stale, "%Y-%m-%d").date()).days
    except ValueError:
        return None
    if age > STALE_MAX_DAYS: return None
    out = dict(card); out["stale"] = stale
    return out


# ---------- 页头:今天变化最大的 5 个数 ----------
# 2026-10-28 新建。出处:埋点需求 §10 最后一行(Michael 10-28 要的每日例行)。
#
# 【为什么不从已渲染好的卡里取数】第一版是扫 build_card 的产物,结果只有 5 张卡够格 ——
# 渲染层拿到的比率卡只剩比率本身,**分子已经被除掉了**,没法做「分子 ≥ 30」这道门槛,
# 只能把比率卡整类排除,候选池就只剩 5 张,「前 5」等于「全部 5」,不成榜。
# ⇒ 改成直接读 raw 里的原始行,自己按天汇总 —— 这样比率卡的分子分母都在手上。
#
# ═══ 🛑 五条口径,已写在卡头上,不要在看板之外另解释 ═══
# ① **只比已过完的整天**:任何 `date >= run_date` 的点一律不参与。
#    服务端表是实时的,当天那条是半天数据;埋点表 T+1,当天那条根本还没入库。
#    拿它们去比,榜上天天是假跌 —— 这是这张卡最容易出的错,所以放在第一条。
# ② **分子 ≥ MOVERS_MIN_N(30),两天都要**。比率卡卡分子、绝对数卡卡值本身。
#    ⚠️ 这是 185 里请 Javier 拍板的那条(「按百分比排小分母霸榜」)的从严版,
#    他定了别的口径就改 MOVERS_MIN_N 一处。
# ③ **均值卡(`agg="avg"`)不进榜** —— 它没有分子,门槛 ② 落不到实处。
# ④ **表格卡和漏斗卡不进榜** —— 一行一个实体 / 一行一级,没有「今天这一个数」。
# ⑤ **一张卡只出一行**,取整卡总体(不拆维度),否则一张多序列的卡能占满五行。
#
# 排序按**相对变化**,但两天的绝对值、变化量、比率卡的分子**同时给** ——
# 只给百分比会把「40 → 80」和「4,000 → 8,000」混为一谈。
# 各卡的「最后两个完整日」可能不同(埋点 T+1、服务端实时),所以**日期逐行给**,
# 表头不写统一区间。
def _movers(metrics, run_date, top=MOVERS_TOP):
    """直接从 raw 行里算,不走 build_card。返回已排好序的前 top 条。"""
    cand = []
    for _sec, cards in SECTIONS:
        for mid, title, kind, p in cards:
            if kind in ("table", "funnel"): continue          # 口径 ④
            if not isinstance(p, dict): continue
            rows = metrics.get(mid)
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                continue
            if p.get("where"):
                wc, wv = p["where"]
                rows = [r for r in rows if str(r.get(wc)) == wv]
                if not rows: continue
            if kind == "long_dim":
                # 🛑 long_dim 的同一天在**每个维度里各出现一行**,直接按天汇总会重复 N 倍。
                #   ⇒ 只取第一个维度那一桶(即卡上默认打开的那个选项卡)。
                r0 = rows[0]
                dim_col = ("dimension" if "dimension" in r0 else
                           ("dim_name" if "dim_name" in r0 else None))
                if not dim_col: continue
                have = []
                for r in rows:
                    k = str(r.get(dim_col))
                    if k not in have: have.append(k)
                if not have: continue
                first = next((k for k in (p.get("dimorder") or []) if k in have), have[0])
                rows = [r for r in rows if str(r.get(dim_col)) == first]
            if p.get("agg") == "avg": continue                 # 口径 ③
            num, den = p["rate"] if p.get("rate") else (None, None)
            col = num or p.get("val")
            if not col: continue
            dc = _dc(rows)
            acc = defaultdict(lambda: [0.0, 0.0])              # 日 → [分子, 分母]
            for r in rows:
                d = r.get(dc)
                if d is None: continue
                a = acc[_nd(d)]
                a[0] += _num(r.get(col))
                if den: a[1] += _num(r.get(den))
            days = sorted(d for d in acc if not run_date or d < run_date)   # 口径 ①
            if len(days) < 2: continue
            d0, d1 = days[-2], days[-1]
            n0, n1 = acc[d0][0], acc[d1][0]
            if n0 < MOVERS_MIN_N or n1 < MOVERS_MIN_N: continue             # 口径 ②
            if den:
                q0, q1 = acc[d0][1], acc[d1][1]
                if q0 <= 0 or q1 <= 0: continue
                # 🛑 「有分母」≠「是百分比」。`人均 Tab 打开次数`、`当天人均消息数`
                #   都是 rate 卡,但它们是**每人多少次**,fmt 写的是 d1。
                #   不看 fmt 一律按百分比显示,会把 1.82 次/人 印成 181.7%(第一版就是这样)。
                v0, v1 = n0 / q0, n1 / q1
                unit = "d1" if p.get("fmt") == "d1" else "pct"
            else:
                v0, v1, unit = n0, n1, p.get("fmt") or "int"
            if v0 == 0: continue
            cand.append(dict(title=title, d0=d0, d1=d1, v0=v0, v1=v1, unit=unit,
                             n1=n1, delta=v1 - v0, rel=abs(v1 - v0) / v0,
                             cut=CUTOVERS.get(d1) or CUTOVERS.get(d0)))
    cand.sort(key=lambda m: m["rel"], reverse=True)
    return cand[:top]


def _mvnum(v):
    return f"{int(round(v)):,}"


def _mvval(v, unit):
    if unit == "pct": return f"{v * 100:.1f}%"
    if unit == "d1":  return f"{v:.1f}"          # 每人多少次 / 多少条,不是百分比
    return _mvnum(v)


def _mvdelta(m):
    """百分比给 pp(百分点),每人多少次给 1 位小数,绝对数给整数差;括号里统一是相对变化。"""
    d = abs(m["delta"]); u = m["unit"]
    core = f"{d * 100:.1f}pp" if u == "pct" else (f"{d:.1f}" if u == "d1" else _mvnum(d))
    return f'{"▲" if m["delta"] > 0 else "▼"} {core} ({m["rel"] * 100:.0f}%)'


def _movers_html(movers):
    head = ('<div class="mv-h">今天变化最大的 '
            f'{len(movers) or MOVERS_TOP} 个数 · Biggest Movers</div>'
            '<div class="mv-sub">口径:只比<b>已过完的整天</b>'
            '(当天那条服务端只有半天、埋点还没入库)'
            f' ｜ 分子两天都要 ≥ {MOVERS_MIN_N} ｜ 均值卡 / 表格卡 / 漏斗卡不进榜'
            ' ｜ 一张卡只出一行,取整卡总体'
            ' ｜ ⚠ = 比较窗口跨了切点,这一跳可能不是业务变化</div>')
    if not movers:
        return ('<div class="movers">' + head +
                f'<div class="mv-empty">今天没有分子两天都 ≥ {MOVERS_MIN_N} '
                '的指标 —— 是门槛拦住了,不是没有变化。</div></div>')
    # 切点落在窗口里的时候,**五行往往全中同一个切点**(比如 AN 关停那天)。
    # 逐行重复五遍只会把真正的差异盖掉 ⇒ 全员相同就提到表头说一次。
    cuts = {m["cut"] for m in movers}
    shared = cuts.pop() if len(cuts) == 1 and all(m["cut"] for m in movers) else None
    if shared:
        head += f'<div class="mv-all-cut">⚠ 本榜全部 {len(movers)} 行都跨了同一个切点:{shared}</div>'
    rows = []
    for m in movers:
        rows.append(
            '<div class="mv-row">'
            f'<div class="mv-t">{m["title"]}</div>'
            f'<div class="mv-dt">{m["d0"][5:]} → {m["d1"][5:]}</div>'
            f'<div class="mv-n">{_mvval(m["v0"], m["unit"])} <span class="mv-ar">→</span> '
            f'<b>{_mvval(m["v1"], m["unit"])}</b>'
            + (f'<span class="mv-s"> 分子 {_mvnum(m["n1"])}</span>' if m["unit"] != "int" else "")
            + '</div>'
            f'<div class="mv-d">{_mvdelta(m)}</div>'
            f'<div class="mv-c">{("⚠ " + m["cut"]) if (m["cut"] and not shared) else ""}</div>'
            '</div>')
    return '<div class="movers">' + head + "".join(rows) + '</div>'


def render(raw_path: Path, out_path: Path):
    D = json.loads(raw_path.read_text(encoding="utf-8"))
    meta = D.get("_meta", {}); metrics = D.get("metrics", D)
    for a, c in ALIAS.items():          # 现卡名 → 权威 metric_id,两种都能认
        if a in metrics and c not in metrics: metrics[c] = metrics[a]
    prev_cards, prev_date = _load_prev(out_path)   # 必须在覆盖 out_path 之前读
    sections, carried = [], []
    for sec, cards in SECTIONS:
        built = []
        for spec in cards:
            card = build_card(metrics, *spec)
            if card is None:                       # 抓失败 / 无数据 → 沿用上一次
                card = _carry(prev_cards, spec[0], prev_date)
                if card: carried.append(card["title"])
            if card: built.append(card)
        if built: sections.append({"title": sec, "cards": built})
    chartjs = (HERE / "lib" / "chart.umd.min.js").read_text(encoding="utf-8")
    payload = json.dumps({"sections": sections, "pal": PAL, "wkpal": WKPAL,
                          "run_date": meta.get("run_date")}, ensure_ascii=False)
    failed = meta.get("failed") or []
    # 副标题第二行:说明埋点类图表的固有延迟。服务端库(留存/对话)不走这条链路,实时。
    #
    # 2026-09-07 重测(host.firebase_event.created_date,近 8 天):ETL 已提前到 SGT
    # 10:02 前后,不再是原先连续 5 天一分不差的 13:00。实测每个 event_date 的落库时点:
    #   20260906→09-07 09:02   20260905→09-06 10:02   20260904→09-05 10:01
    #   20260903→09-04 10:03   20260902→09-03 11:03   20260901→09-02 10:01
    #   20260831→09-01 10:02   20260830→08-31 10:03
    # 灌数本身只花 ~20 秒,但时点在 09:02~11:03 之间浮动 ⇒ 对外只能说"11:00 之后",
    # 说 10:00 会在 ETL 迟到那天(如 09-03 的 11:03)变成谎话。
    # 2026-10-20 扩写。原来只说了客户端埋点的延迟,但本页从 10-20 起同时抓看板 18 和 24,
    # 服务端表的卡(额度墙/付费墙/邀请/回传对账/参考照)是**实时**的,和客户端埋点表差一天。
    # 🛑 看板上没有任何手动导入的数据 —— 全是 Metabase 跑 SQL 查生产库。
    #   385/386 虽然叫「Meta 素材全链路」,数据源也是 soulmap_app_launch 的归因字段,
    #   不是 Meta 导出的表格(那个在「战情室/素材级对账」本地管线里,不进看板)。
    # 不说清楚的话,同一页上把「服务端今天的数」和「客户端昨天的数」并排读会误判。
    lag_note = (
        '每天自动刷新 5 次(SGT 11:20 / 14:20 / 17:20 / 21:20 / 04:20)'
        ' ｜ Auto-refreshed 5×/day')
    source_note = (
        '🛑 本页全部来自生产库,但两类表的新鲜度差一天:'
        '<b>服务端表</b>(额度墙 / 付费墙 / 邀请 / 回传对账 / 参考照 / 推送发送)= <b>实时</b>;'
        '<b>客户端埋点表</b> host.firebase_event(版本覆盖 / 语音 / 回忆页 / 各国首日深度)= <b>T+1</b>,'
        '每天 11:00(SGT) 前入库前一天的数据 ⇒ <b>这些卡最后一天偏低或为 0,是没入库不是业务为 0</b>。'
        ' ｜ All cards query the production DB. Server tables are live; client telemetry lands one day late.')
    hdr = (f'<header><h1>SoulMap 看板 · SoulMap Dashboard</h1><div class="meta">'
           f'数据 {meta.get("run_date","?")} · Metabase 看板 '
           f'{",".join(str(x) for x in (meta.get("dashboard_ids") or [meta.get("dashboard_id","?")]))} · '
           f'{sum(len(s["cards"]) for s in sections)} 卡'
           + (f' · 缺 {len(failed)}' if failed else '')
           + (f' · 沿用旧值 {len(carried)}' if carried else '') +
           f'</div><div class="meta lag">{lag_note}</div>'
           f'<div class="meta src">{source_note}</div></header>'
           + (f'<div class="banner">{BANNER}</div>' if BANNER else '')
           # 2026-10-28:「今天变化最大的 5 个数」放在横幅之后、卡片之前 ——
           # Michael 要的是「看板顶部」,但它不能盖住上面那条新鲜度说明,
           # 因为这张榜的第一条口径(只比完整的天)正是从那条说明来的。
           + _movers_html(_movers(metrics, meta.get("run_date"))))
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SoulMap 看板 · SoulMap Dashboard</title>
<style>{CSS}</style></head><body>{hdr}<div id="root"></div>
<script>{chartjs}</script>
<script>const DATA={payload};</script>
<script>{APP_JS}</script></body></html>"""
    # 一张卡都没有就不要写 —— 写出去等于把上一版好页面覆盖成空白,而且下次连沿用的来源都没了。
    # workflow 的 guard 正常会先拦住(抓不满 25 张就不 render),这里是第二道,防手工误跑。
    if not sections:
        raise SystemExit("✗ 一张卡都没建出来,拒绝写出 —— 保留上一版页面。"
                         "检查 raw_metrics.json 是否为空,或上一版数据是否已超过 "
                         f"STALE_MAX_DAYS={STALE_MAX_DAYS} 天。")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    print(f"写出 {out_path} ({len(sections)} 板块, {sum(len(s['cards']) for s in sections)} 卡"
          + (f", 沿用旧值 {len(carried)}: {carried}" if carried else "") + ")")

APP_JS = r"""
const $=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;};
// Metabase query/json 把 >=1000 的数返回成带千分位逗号的字符串("1,184"),
// 直接 +v 会得到 NaN。Python 侧 _num() 早就处理了,JS 侧 2026-08-20 之前一直没处理 ——
// 后果是所有 table 卡里 >=1000 的整数列全显示 NaN(<1000 的正常,所以很容易漏掉)。
function toNum(v){return typeof v==='string'?+v.replace(/,/g,''):+v;}
function fmtV(v,fmt){if(v==null)return'';v=toNum(v);if(!isFinite(v))return'';
  // 按模式匹配,不再逐个列举 —— 2026-08-18 踩过:注册表用了 pct1,这里没实现,
  // 于是掉到末尾的 Math.round,0.2027 显示成 0、0.5137 显示成 1,三张卡静默显示错值。
  // pct/pct0/pct1/pct2… 与 d1/d2… 现在一律走通用分支,加新格式不必改这里。
  const mp=/^pct(\d*)$/.exec(fmt); if(mp)return(v*100).toFixed(mp[1]===''?1:+mp[1])+'%';
  const md=/^d(\d+)$/.exec(fmt);   if(md)return(+v).toFixed(+md[1]);
  return Math.round(v).toLocaleString();}
const STEPMAP={'打开':'打开 Open','Welcome':'Welcome','进入onboarding':'进入 Onboarding',
 '完成onboarding':'完成 Onboarding','用户首条':'用户首条 First Msg','activated(3+)':'激活 Activated ≥3',
 'deep(5+)':'深度 Deep ≥5','deep(10+)':'深度 Deep ≥10',
  '开始onboarding':'开始 Onboarding','选topic':'选 Topic',
  '看到角色目录':'看到角色目录 Catalog Shown','选择角色':'选择角色 Character Picked',
  '收到通知':'收到通知 Received','有反应':'有反应 Reacted',
  '点开通知':'点开通知 Opened','点开后聊天':'点开后聊天 Chatted (30min)',
  '弹出权限窗':'弹出权限窗 Prompt Shown','授权通过':'授权通过 Granted',
  '拿到token':'拿到 Token','服务端注册':'服务端注册 Registered',
  '看到目录':'看到目录 Catalog Shown','看到角色卡':'看到角色卡 Cards Seen',
  '点击角色':'点击角色 Character Tapped','发出首条':'发出首条 First Msg',
  '冷启动展示':'冷启动展示 Cold Shown','种子星点击':'种子星点击 Seed Tap','转成实心星':'转成实心星 Owned',
  // 2026-09-21 补:激活两张漏斗卡 2026-09-15 由轮数改为累计句数后,这六级一直没进 STEPMAP,
  //   图上显示的是中文裸名。句数口径为服务端全历史累计,见对应 SQL 头部。
  '累计1句':'累计1句 ≥1 msg','累计3句':'累计3句 ≥3 msgs','累计5句':'累计5句 ≥5 msgs',
  '累计10句':'累计10句 ≥10 msgs','累计20句':'累计20句 ≥20 msgs',
  '单host累计20句':'单host 20句 ≥20 w/ one host',
  // 2026-09-21 新增:两张付费漏斗卡(by country / by version)的环节
  '装机':'装机 Install','开口':'开口 First Msg','点击角色卡':'点击角色卡 Card Tap',
  '撞墙':'撞墙 Quota Wall','点订阅':'点订阅 Subscribe Tap',
  '试用生效':'试用生效 Trial','真实付费':'真实付费 Paid',
  // 分组值(不是步骤):付费漏斗分国家的三组 / 分版本的长尾合计。
  //   check_cards.py 按 `数字_中文` 的格式识别,分组值与步骤同格式,所以一并登记;
  //   登记后图例也会显示英文,与其余卡一致。
  '英美加澳':'英美加澳 US/UK/CA/AU','南亚':'南亚 South Asia','其它':'其它 Other',
  'zz_其它版本合计':'其它版本合计 Other versions'};
function drawTable(el,card){
  el.innerHTML='';
  const cols=card.cols||[],all=card.rows||[];let expanded=false;
  const wrap=$('div','tblwrap'),t=document.createElement('table');t.className='tbl';
  wrap.appendChild(t);el.appendChild(wrap);
  const more=$('div','tblmore');el.appendChild(more);
  function paint(){
    const rows=expanded?all:all.slice(0,card.top||20);
    let h='<thead><tr>'+cols.map(c=>'<th class="'+(c.fmt&&c.fmt!=='text'?'num':'')+'">'+c.label+'</th>').join('')+'</tr></thead><tbody>';
    rows.forEach(r=>{h+='<tr>'+cols.map(c=>{
      const v=r[c.k],isNum=c.fmt&&c.fmt!=='text';
      const nv=isNum?toNum(v):null;
      const txt=isNum?fmtV(nv,c.fmt):(v==null?'':String(v));
      const safe=String(txt).replace(/"/g,'&quot;');
      if(c.max){const w=(c.max>0&&isFinite(nv))?Math.max(0,Math.min(100,nv/c.max*100)):0;
        return '<td class="num bar" title="'+safe+'"><i style="width:'+w.toFixed(1)+'%"></i>'+txt+'</td>';}
      return '<td class="'+(isNum?'num':'')+'" title="'+safe+'">'+txt+'</td>';
    }).join('')+'</tr>';});
    t.innerHTML=h+'</tbody>';
    if(all.length>(card.top||20)){
      more.textContent=expanded?('收起 · 只看前 '+(card.top||20)+' 行'):('展开全部 '+all.length+' 行 ↓');
      more.style.display='block';
    } else more.style.display='none';
  }
  more.onclick=()=>{expanded=!expanded;paint();wrap.scrollTop=0;};
  paint();
}
function drawFunnel(el,card,wk){
  el.innerHTML='';const steps=card.steps||[],mx=card.matrix||{};
  const vals=steps.map(s=>+((mx[s]||{})[wk])||0);const top=vals[0]||1;
  steps.forEach((s,i)=>{
    if(i>0){const conv=vals[i-1]?vals[i]/vals[i-1]*100:0;   // 环比:写在两条之间的连接处,只写数字
      const c=$('div','fconn');c.innerHTML='<span>↓ '+conv.toFixed(0)+'%</span>';el.appendChild(c);}
    const v=vals[i],w=Math.max(2,v/top*100),tot=top?v/top*100:0;   // 整体:写右侧
    const raw=s.replace(/^[0-9]+_/,''),lab=STEPMAP[raw]||raw;
    const row=$('div','frow');
    row.innerHTML='<span class="flab">'+lab+'</span>'+
      '<div class="fbarwrap"><div class="fbar" style="width:'+w.toFixed(1)+'%">'+v.toLocaleString()+'</div></div>'+
      '<span class="fpc">'+tot.toFixed(0)+'%</span>';
    el.appendChild(row);});}
function latestOf(dd,fmt){const ds=allDates(dd);if(!ds.length)return'';const d=ds[ds.length-1];
  let v;if(dd['Overall']){const p=dd['Overall'].find(x=>x[0]===d);v=p?p[1]:0;}
  else{v=0;for(const k in dd){const p=dd[k].find(x=>x[0]===d);if(p)v+=p[1];}}
  return fmtV(v,fmt);}   // 右上角只显示最新值,不带日期
const modal=$('div','modal');
modal.innerHTML='<div class="modalbox"><button class="mclose">✕</button><div class="mtitle"></div><div class="mbody"></div></div>';
document.body.appendChild(modal);
modal.addEventListener('click',e=>{if(e.target===modal||e.target.className==='mclose'){
  modal.style.display='none';modal.querySelector('.modalbox').classList.remove('wide');}});
let modalChart=null;
function openLineDetail(card,data){modal.querySelector('.mtitle').textContent=card.title;
  const mb=modal.querySelector('.mbody');mb.style.height='64vh';mb.innerHTML='';
  const cv=document.createElement('canvas');mb.appendChild(cv);
  if(modalChart)modalChart.destroy();modalChart=new Chart(cv,lineCfg(data,card.fmt));modalChart.$fmt=card.fmt;
  modal.style.display='flex';}
function openFunnelDetail(card,wk){modal.querySelector('.mtitle').textContent=card.title+(wk?'  ·  '+wk:'');
  const mb=modal.querySelector('.mbody');mb.style.height='auto';mb.innerHTML='';
  const box=$('div');mb.appendChild(box);drawFunnel(box,card,wk);modal.style.display='flex';}
function openTableDetail(card){modal.querySelector('.mtitle').textContent=card.title;
  modal.querySelector('.modalbox').classList.add('wide');
  const mb=modal.querySelector('.mbody');mb.style.height='auto';mb.innerHTML='';
  const box=$('div','tbldetail');mb.appendChild(box);
  // 详情里默认铺开全部行:把 top 抬到行数,drawTable 的「展开全部」链接自然不出现
  drawTable(box,Object.assign({},card,{top:(card.rows||[]).length}));
  modal.style.display='flex';}
const valueLabels={id:'vlab',afterDatasetsDraw(chart){const ctx=chart.ctx,fmt=chart.$fmt||'int',bar=chart.config.type==='bar';
  const ic=ink();ctx.save();ctx.font='600 9px -apple-system,BlinkMacSystemFont,sans-serif';ctx.textAlign='center';
  chart.data.datasets.forEach((ds,di)=>{const m=chart.getDatasetMeta(di);if(m.hidden)return;
    m.data.forEach((pt,idx)=>{const v=ds.data[idx];if(v==null)return;
      ctx.fillStyle=bar?ic.ts:(ds.borderColor||ic.ts);ctx.fillText(fmtV(+v,fmt),pt.x,pt.y-5);});});
  ctx.restore();}};
function isDark(){const r=document.documentElement.getAttribute('data-theme');
  return r?r==='dark':matchMedia('(prefers-color-scheme:dark)').matches;}
function ink(){const s=getComputedStyle(document.documentElement);
  return {ts:s.getPropertyValue('--ts').trim(),mut:s.getPropertyValue('--mut').trim(),grid:s.getPropertyValue('--grid').trim()};}
const charts=[];
function allDates(data){const s=new Set();for(const k in data)data[k].forEach(p=>s.add(p[0]));return[...s].sort();}
function lineCfg(dimData,fmt){
  const labels=allDates(dimData);const names=Object.keys(dimData);const P=DATA.pal;
  const ds=names.map((nm,i)=>{const m=Object.fromEntries(dimData[nm]);
    return{label:nm,data:labels.map(d=>d in m?m[d]:null),borderColor:P[i%P.length],
      backgroundColor:P[i%P.length],borderWidth:2,tension:.3,cubicInterpolationMode:'monotone',
      pointRadius:0,pointHoverRadius:4,spanGaps:true};});
  const c=ink();
  return{type:'line',data:{labels,datasets:ds},plugins:[valueLabels],options:{responsive:true,maintainAspectRatio:false,
    layout:{padding:{top:16,right:52,left:4}},interaction:{mode:'index',intersect:false},
    plugins:{legend:{display:names.length>1,position:'top',align:'start',
      labels:{boxWidth:10,boxHeight:10,usePointStyle:true,pointStyle:'circle',color:c.ts,font:{size:11}}},
      tooltip:{callbacks:{label:x=>x.dataset.label+': '+fmtV(x.parsed.y,fmt)}}},
    scales:{x:{grid:{display:false},ticks:{color:c.mut,font:{size:9},maxRotation:55,autoSkip:true,autoSkipPadding:4,
        callback:function(v){return this.getLabelForValue(v).slice(5);}},border:{color:c.grid}},
      y:{beginAtZero:true,grid:{color:c.grid},border:{display:false},ticks:{color:c.mut,font:{size:10},
        callback:v=>fmtV(v,fmt)}}}}};
}
function funnelCfg(card){const c=ink();const W=DATA.wkpal;
  const ds=card.weeks.map((w,i)=>({label:w,data:card.steps.map(s=>card.matrix[s][w]||0),
    backgroundColor:W[i%W.length],borderRadius:4,borderSkipped:false}));
  return{type:'bar',data:{labels:card.steps.map(s=>s.replace(/^[0-9]+_/,'')),datasets:ds},plugins:[valueLabels],
    options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:14}},
      plugins:{legend:{position:'top',align:'start',labels:{boxWidth:10,boxHeight:10,usePointStyle:true,pointStyle:'rect',color:c.ts,font:{size:11}}}},
      scales:{x:{grid:{display:false},ticks:{color:c.mut,font:{size:10}},border:{color:c.grid}},
        y:{beginAtZero:true,grid:{color:c.grid},border:{display:false},ticks:{color:c.mut,font:{size:10},callback:v=>(+v).toLocaleString()}}}}};
}
function build(){
  charts.forEach(c=>c.destroy());charts.length=0;
  const root=document.getElementById('root');root.innerHTML='';
  const nav=$('div','nav');root.appendChild(nav);const navbtns=[],secEls=[];
  DATA.sections.forEach((sec,si)=>{
    const wrap=document.createElement('section');wrap.id='sec-'+si;
    wrap.appendChild($('h2',null,sec.title));
    const g=$('div','grid-cards');wrap.appendChild(g);root.appendChild(wrap);secEls.push(wrap);
    const nb=$('button','nb',sec.title.replace(/^[①-⑳\s]+/,''));
    nb.onclick=()=>wrap.scrollIntoView({behavior:'smooth',block:'start'});nav.appendChild(nb);navbtns.push(nb);
    sec.cards.forEach(card=>{
      const el=$('div','card');
      const hd=$('div','chead');hd.appendChild($('h3',null,card.title));
      const lv=$('span','latest');hd.appendChild(lv);el.appendChild(hd);
      // 这次没抓到 → 沿用旧值,标在卡片左下角(挂在 el 末尾,三种卡型都落在图下方)
      const staleFoot=card.stale
        ? $('div','stalefoot','沿用 '+card.stale.slice(5).replace('-','/')+' 数据 ｜ stale')
        : null;
      const markStale=()=>{if(staleFoot)el.appendChild(staleFoot);};
      if(card.note)el.appendChild($('div','cnote',card.note));
      if(card.error){el.appendChild($('div','empty','渲染失败: '+card.error));g.appendChild(el);return;}

      if(card.kind==='table'){
        const body=$('div');el.appendChild(body);g.appendChild(el);
        drawTable(body,card);lv.textContent=(card.rows||[]).length+' 行';
        // 卡片是半屏宽,列多的表在这里要横向滚;点这里用宽弹窗一屏读全
        const vd=$('div','vlink','View details ↗');vd.onclick=()=>openTableDetail(card);el.appendChild(vd);
        markStale();
        return;}
      if(card.kind==='funnel'){
        const wks=card.weeks||[];const defi=(card.defwk==='first')?0:wks.length-1;let curw=wks.length?wks[defi]:null;
        const tb=$('div','toolbar');const body=$('div');
        wks.forEach((w,i)=>{const b=$('button','tbtn'+(i===defi?' on':''),w);
          b.onclick=()=>{curw=w;drawFunnel(body,card,w);lv.textContent='最新 '+w;tb.querySelectorAll('.tbtn').forEach(x=>x.classList.remove('on'));b.classList.add('on');};
          tb.appendChild(b);});
        if(wks.length>1)el.appendChild(tb);el.appendChild(body);
        const vd=$('div','vlink','View details ↗');vd.onclick=()=>openFunnelDetail(card,curw);el.appendChild(vd);
        g.appendChild(el);
        if(curw){drawFunnel(body,card,curw);lv.textContent='最新 '+curw;}
        markStale();
        return;}
      const dims=card.dims||[];let cur=0,vis=new Set();
      const cw=$('div','cw');const cv=document.createElement('canvas');cw.appendChild(cv);
      const chipbar=$('div','chips');
      if(dims.length>1){const tb=$('div','toolbar');
        dims.forEach((dm,i)=>{const b=$('button','tbtn'+(i===0?' on':''),dm.label);
          b.onclick=()=>{tb.querySelectorAll('.tbtn').forEach(x=>x.classList.remove('on'));b.classList.add('on');applyDim(i);};
          tb.appendChild(b);});el.appendChild(tb);}
      el.appendChild(chipbar);el.appendChild(cw);
      const vd=$('div','vlink','View details ↗');vd.onclick=()=>openLineDetail(card,curData());el.appendChild(vd);
      g.appendChild(el);
      const ch=new Chart(cv,lineCfg({},card.fmt));ch.$fmt=card.fmt;cw._chart=ch;charts.push(ch);
      function curData(){const dd=(dims[cur]||{data:{}}).data,o={};for(const k in dd)if(vis.has(k))o[k]=dd[k];return o;}
      function redraw(){const fd=curData(),cfg=lineCfg(fd,card.fmt),c2=cw._chart;c2.data=cfg.data;c2.options=cfg.options;c2.update();lv.textContent=latestOf(fd,card.fmt);}
      function chips(){chipbar.innerHTML='';const names=Object.keys((dims[cur]||{data:{}}).data);
        if(names.length<=1){chipbar.style.display='none';return;}chipbar.style.display='flex';
        const all=$('button','chip'+(vis.size===names.length?' on':''),'All');
        all.onclick=()=>{vis=new Set(names);chips();redraw();};chipbar.appendChild(all);
        names.forEach(n=>{const b=$('button','chip'+(vis.has(n)?' on':''),n);
          b.onclick=()=>{if(vis.size===names.length){vis=new Set([n]);}      // 全开时点一个=只看它(单选)
            else if(vis.has(n)){vis.delete(n);if(!vis.size)vis=new Set(names);}// 关到空则复位
            else{vis.add(n);}                                                 // 否则加选(多选)
            chips();redraw();};chipbar.appendChild(b);});}
      function applyDim(i){cur=i;vis=new Set(Object.keys((dims[i]||{data:{}}).data));chips();redraw();}
      applyDim(0);
      markStale();
    });
  });
  nav.appendChild($('div','sp'));
  const tg=$('button','nb','◐ 主题 Theme');tg.onclick=()=>{document.documentElement.setAttribute('data-theme',isDark()?'light':'dark');build();};
  nav.appendChild(tg);
  if(window.__io)window.__io.disconnect();
  window.__io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){
    const i=secEls.indexOf(e.target);navbtns.forEach((b,j)=>b.classList.toggle('on',j===i));}});},
    {rootMargin:'-45% 0px -50% 0px'});
  secEls.forEach(s=>window.__io.observe(s));
  if(navbtns[0])navbtns[0].classList.add('on');
}
build();
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(HERE / "raw_metrics.json"))
    ap.add_argument("--out", default=str(HERE / "soulmap-online.html"))
    a = ap.parse_args()
    render(Path(a.raw), Path(a.out))

if __name__ == "__main__":
    main()
