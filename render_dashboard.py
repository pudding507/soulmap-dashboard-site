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

# ---------- 聚合 ----------
def _num(x):
    # ⚠️ Metabase query/json 把大数返回成带千分位逗号的字符串("3,065"),必须先去逗号再转
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

def _agg(rows, val, by=None, how="sum", dc="date"):
    acc = defaultdict(lambda: [0.0, 0])
    for r in rows:
        d = r.get(dc)
        if d is None: continue
        s = (str(by(r)) if callable(by) else str(r.get(by))) if by else "Overall"
        a = acc[(s, _nd(d))]; a[0] += _num(r.get(val)); a[1] += 1
    out = defaultdict(list)
    for (s, d), (t, c) in acc.items():
        out[s].append((d, round(t / c, 3) if (how == "avg" and c) else round(t, 3)))
    for s in out: out[s].sort()
    return out

def _rate(rows, num, den, by=None, dc="date"):
    acc = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        d = r.get(dc)
        if d is None: continue
        s = (str(by(r)) if callable(by) else str(r.get(by))) if by else "Overall"
        a = acc[(s, _nd(d))]; a[0] += _num(r.get(num)); a[1] += _num(r.get(den))
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
_ADGROUP_METRICS = ["first_message", "turns_5plus", "turns_10plus", "retention_d1"]
_ADGROUP_ORDER   = ["relationship", "burnout", "career", "others"]   # 固定线序,新广告组自动接在后面
ADGROUP_DIMS = dict(
    dimorder=_ADGROUP_METRICS,
    dimlabels={"first_message": "First message", "turns_5plus": "5+ turns (day 0)",
               "turns_10plus": "10+ turns (day 0)", "retention_d1": "D1 retention"},
    slorder={k: _ADGROUP_ORDER for k in _ADGROUP_METRICS},
    min_vol=30,   # 累计新用户不足 30 的广告组不画(刚上线的小广告组率值波动极大)
)

# 每日角色 CTR 的维度配置(SQL 的 dimension 列 → 选项卡;dimension_value = 各角色线)
CHAR_DAILY_CTR_DIMS = dict(
    dimorder=["overall", "character"],
    dimlabels={"overall": "Overall", "character": "by character"},
    # 按**点击数**排线,不按曝光:目录按字母序展示,曝光被顶得人人相近
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

# ---------- 注册表 ----------
# line 卡: dims = [(key,label,by_col)]; by_col=None 即总体
# rate 卡: 加 rate=(num,den); long_dim: SQL 自带 dimension/dimension_value 列; funnel: 无参
SECTIONS = [
 ("① 增长 · Growth", [
   ("growth_dau", "日活跃用户数 · DAU", "line", dict(
            note="当天打开过 App 的用户(session_start) ｜ Users who opened the app that day (session_start)",val="value", cap=12,
       dims=[("overall","Overall",None),("user_type","by user type","user_type"),("source","by source","source"),("adgroup","by source×adgroup",_ADG)])),
   ("growth_dau_new_returning", "DAU 新老占比 · New vs Returning", "rate",
       dict(rate=("users","daily_active_users"), fmt="pct0", order=["new","returning"],
            note="新/老用户 ÷ 当天DAU;新=当天安装 ｜ New vs returning share of daily DAU; “new” = installed that day",
            dims=[("user_type","","user_type")])),
   ("growth_new_user", "新用户数 · New Users", "line", dict(
            note="当天首次安装 App 的用户(first_open) ｜ Users whose first_open happened that day",val="value", cap=12,
       dims=[("overall","Overall",None),("source","by source","source"),("adgroup","by source×adgroup",_ADG)])),
   ("growth_version_adoption", "版本覆盖率 · Version Adoption", "rate",
         dict(rate=("devices","daily_active_devices"), fmt="pct0", cap=9,
              note="当天活跃设备按 App 版本拆分;设备一天内跨版本时归入较高版本 ｜ Daily active devices by app version; a device spanning versions in one day counts to the higher one",
              dims=[("app_version","","app_version")])),
     ("growth_adgroup_d0_comparison", "广告组首日对照 · Ad-Group D0 Comparison", "long_dim",
         dict(rate=("numerator","denominator"), fmt="pct0", **ADGROUP_DIMS,
              note="各广告组的新用户首日行为与次日留存,分母为该广告组当天新用户数(按账号) ｜ Day-0 behaviour and D1 retention by ad group; denominator = that group\u2019s new users that day (accounts)")),
     ("growth_new_activated_user", "深度新用户数 · Deep New Users", "line", dict(val="value", cap=12,
       note="新用户中对话≥5轮的人(1问1答=1轮) ｜ New users reaching ≥5 conversation turns (1 exchange = 1 turn)",
       dims=[("overall","Overall",None),("source","by source","source"),("adgroup","by source×adgroup",_ADG)])),
   ("growth_meta_qcd_trend_by_creative", "Meta 素材 QCD 趋势 · Meta QCD by Creative", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct1", cap=8, min_vol=50,
            dimlabels={"creative":"by creative"},
            note="按**装机日**看每条素材带来的用户里有多少达成 QCD(同日同角色≥6条用户消息);排除 reception ｜ QCD rate by install date for each Meta creative (≥6 user messages with the same host in a day); reception excluded")),
   ("growth_meta_funnel_by_creative", "Meta 素材全链路 · Meta Full Funnel by Creative", "table",
       dict(top=15, sort="installs",
            cols=[("creative","素材 Creative","text"),
                  ("installs","装机 Installs","int"),
                  ("reached_card_shown","看过角色卡 Saw Card","int"),
                  ("reached_card_tap","点击 Tapped","int"),
                  ("reached_chat","点后开聊 Tap→Chat","int"),
                  ("reached_first_message","发过消息 Any Msg","int"),
                  ("reached_qcd","达成 QCD","int"),
                  ("retained_d1","D1 回访","int"),
                  ("retained_d7_window","D7窗 回访 (5–9d)","int"),
                  ("card_shown_rate","装机→看卡","pct0"),
                  ("tap_rate","看卡→点击","pct0"),
                  ("qcd_rate","装机→QCD","pct1"),
                  ("first_install_date","首个装机日 First Install","text")],
            bar=["installs","qcd_rate"],
            note="⚠️「看过角色卡」「点击」两列**只对 2026-08-15(2.7.0 放量)之后的装机有意义** —— 之前装机的用户没有角色目录界面,那些行接近 0 不是素材差,看「首个装机日」列判断 ｜ ⚠️ The Saw-Card and Tapped columns only apply to installs on/after Aug 15 (2.7.0 rollout); earlier installs had no catalogue UI, so near-zero values there are not a creative problem — check the First-Install column")),
 ]),
 ("② 激活 · Activation", [
   ("activation_funnel", "激活漏斗 · Activation Funnel", "funnel",
       dict(note="各步骤人数,按安装日归入版本周;activated=≥3轮 · deep=≥5轮 ｜ Users at each step, grouped by install week; activated = ≥3 turns, deep = ≥5 turns")),
   ("activation_funnel_by_adgroup", "激活漏斗分广告组 · Activation Funnel by Ad Group", "funnel",
       dict(note="同激活漏斗,按 source×广告类型分组;近4版本周·取前8组 ｜ Same funnel split by source × ad type; last 4 release weeks, top 8 groups")),
   ("activation_guardrail_funnel", "护栏漏斗分版本 · Guardrail Funnel by Version", "funnel",
       dict(gsort="version", note="onboarding 六步按 app_version 分组,看新 chip 有没有增流失;近30天,activated=≥3轮 deep=≥5轮 ｜ Onboarding steps split by app version — did the new chip add drop-off? Last 30 days")),
   ("activation_onboarding_dropoff", "Onboarding 流失 · Onboarding Dropoff", "line", dict(
            note="放弃 onboarding 的人数,每人计在最后停留的那一屏 ｜ Users abandoning onboarding, counted at the last screen they reached",val="value",
       dims=[("overall","Overall",None),("last_scene","by scene","last_scene")])),
   ("activation_onboarding_from_2.5.0", "新版 Onboarding Anchor 分布 · New-Onboarding Anchor Distribution", "line",
       dict(val="users",
            note="投放口径 user.topic_anchor,含默认落到 just_talk 的 ≈62%(主动选择仅 ≈11%) ｜ Delivery definition; ~62% default to just_talk (explicit choice: ~11%)",
            dims=[("overall","Overall",None),("anchor","by anchor","anchor"),
                  ("source","by source","source"),("adgroup","by source×adgroup",_ADG)])),
   ("activation_user_first_latency", "用户首条消息时延 · User First-Msg Latency (avg s)", "line", dict(val="avg_secs", agg="avg",
       note="用户看到 AI 首句后发出第一条消息的秒数,取平均 ｜ Avg seconds from the AI's opening line to the user's first message",
       dims=[("overall","Overall",None)])),
   ("activation_ai_first_latency", "AI 首条响应时延 · AI First-Reply Latency (avg s)", "line", dict(
            note="每会话首次 composer 回复的耗时,每用户取最早一次再平均;不含前置组件,是真实等待的下限 ｜ Avg time for composer to generate the first reply; excludes upstream components, so a lower bound",val="avg_secs", agg="avg",
       dims=[("overall","Overall",None)])),
 ]),
 ("③ 留存 · Retention", [
   ("retention_d1", "留存 D1 · Retention D1", "long_dim",
       dict(rate=("retained_users","new_users"), **RETENTION_DIMS,
            note="次日开App的人 ÷ 当天注册的新用户;回访=session_start ｜ Users reopening the app on day 1 ÷ new users registered that day")),
   ("retention_d1_effective", "有效留存 D1 · Effective Retention D1", "long_dim",
       dict(rate=("messaged_users","new_users"), **RETENTION_DIMS,
            note="次日发过消息的人 ÷ 当天注册的新用户;只算用户自己发言,打开App不算 ｜ Users who sent a message on day 1 ÷ new users that day; opening the app alone doesn't count")),
   ("retention_d3", "留存 D3 · Retention D3", "long_dim",
       dict(
            note="第3天开App的人 ÷ 当天注册的新用户 ｜ Users reopening on day 3 ÷ new users registered that day",rate=("retained_users","new_users"), **RETENTION_DIMS)),
   ("retention_d7", "留存 D7 · Retention D7", "long_dim",
       dict(rate=("retained_users","new_users"), **RETENTION_DIMS,
            note="第7天开App的人 ÷ 当天注册的新用户;末尾几天观察窗未满 ｜ Users reopening on day 7 ÷ new users that day; the trailing days' window hasn't closed")),
   ("retention_push_funnel", "推送链路漏斗 · Push Setup Funnel", "funnel",
       dict(note="弹出权限窗的设备:授权 → 拿到 token → 服务端注册,按系统分组;数据自 2.7.0(8/15)起 ｜ Devices shown the permission prompt: granted → token obtained → registered on server, grouped by OS; data starts with 2.7.0 (Aug 15)")),
   ("retention_push_delivery", "推送触达漏斗 · Push Delivery Funnel", "funnel",
       dict(note="收到通知的设备:有反应(点开或划掉) → 点开 → 点开后 30 分钟内发消息;数据自 2.7.0(8/15)起 ｜ Devices that received a notification: reacted (opened or dismissed) → opened → sent a message within 30 min of opening; data starts with 2.7.0 (Aug 15)")),
 ]),
 ("④ 模块 · Modules", [
   ("module_tab_penetration", "四 Tab 渗透率 · Four-Tab Penetration", "rate",
       dict(rate=("tab_users","active_users"), fmt="pct0",
            note="访问过该 Tab 的人 ÷ 当天DAU ｜ Users who opened each tab ÷ that day's DAU",
            order=["Stars","Chat","Discover","Me"],
            dims=[("tab","","tab")])),
   ("module_tab_opens_per_user", "人均 Tab 打开次数 · Tab Opens per User", "rate",
       dict(
            note="该 Tab 打开次数 ÷ 当天DAU ｜ Tab opens ÷ that day's DAU",rate=("tab_opens","active_users"), pct=False, fmt="d1",
            order=["Stars","Chat","Discover","Me"],
            dims=[("tab","","tab")])),
   ("module_locked_tab_tap", "锁定 Tab 点击率 · Locked-Tab Tap Rate", "rate", dict(rate=("users","active_users"),
       note="点击未解锁 Tab 的用户 ÷ 当天DAU ｜ Users tapping a locked tab ÷ that day's DAU",
       dims=[("overall","Overall",None),("tab_name","by tab","tab_name")])),
 ]),
 ("⑤ 对话 · Chat", [
   # —— 参与广度 · Engagement breadth ——
   ("chat_engaged_new_user_rate", "新用户投入率 · Engaged New-User Rate", "rate",
       dict(rate=("engaged_new_users","new_users"),
            note="首日发≥5条的新用户 ÷ 当天注册的新用户 ｜ New users sending ≥5 messages on day 0 ÷ new users registered that day",
            dims=[("overall","Overall",None)])),
   ("chat_engaged_user_focus", "投入用户数 · Engaged Users", "line",
       dict(val="users",
            note="当天发≥5条消息的用户(含老用户);purpose 来自旧版 onboarding 表单,新版用 anchor ｜ Users sending ≥5 messages that day; purpose comes from the old onboarding form, the new one uses anchors",
            dims=[("overall","Overall",None),
                  ("user_type","by user type","user_type"),
                  ("source","by source","source"),("adgroup","by source×adgroup",_ADG),
                  ("purpose","by purpose (old form)","purpose")])),
   ("chat_silent_rate", "Silent 会话率 · Silent-Session Rate", "rate", dict(rate=("silent_sessions","sessions"),
       note="开了会话但一条没发的会话 ÷ 全部会话 ｜ Sessions opened with no message sent ÷ all sessions",
       dims=[("overall","Overall",None),("path","by path","path")])),
   # —— 参与深度 · Engagement depth ——
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
   ("chat_voice_text_ratio", "语音消息占比 · Voice Msg Share", "rate",
       dict(rate=("voice_msgs","total_msgs"),
            note="语音消息 ÷ 全部用户消息,按消息实际模态统计 ｜ Voice messages ÷ all user messages, by the message's actual mode",
            dims=[("overall","Overall",None)])),
   # —— 系统质量 · System quality ——
   ("chat_module_call_success", "模块成功响应率 · Module-Call Success by Content", "rate",
       dict(rate=("success","turns"),
            note="成功调用模块的轮次 ÷ 有 director 判断的轮次;闲聊本就不需模块,低值非失败 ｜ Turns where a module fired ÷ turns with a director decision; casual chat needs none, so a low rate isn't a failure",
            dims=[("overall","Overall",None),("purpose","by content","purpose")])),
   ("chat_ai_latency", "AI 响应时延 · AI Reply Latency (avg s)", "rate",
       dict(rate=("latency_sec_total","turns"), pct=False, fmt="d1",
            note="每一轮 AI 生成回复的耗时,取平均(llm_response 组件) ｜ Avg time for the AI to generate a reply, per turn (llm_response)",
            dims=[("overall","Overall",None)])),
   ("chat_qcd_v1_daily", "QCD 日度 · Quality Conversations per Day", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct1", min_vol=0,
            dimorder=["overall","host_type"],
            dimlabels={"overall":"Overall","host_type":"by host type"},
            # slorder 固定线序:角色卡在前(它才是 North Star),系统行垫底
            slorder={"host_type":["角色卡","reception","SoulMap系统行"]},
            note="QCD = 同一天里对同一个 Host 发了 ≥6 条非空消息的用户,占当天 DAU 的比例。三档分开看:角色卡才是 North Star,reception 是打开就在的默认接待(用户没做过选择)。⚠️ 口径暂定,A/B 闭环定义正在重新对齐 ｜ QCD = users who sent ≥6 non-empty messages to the same host in one day, over DAU. Split by host type: only character cards count toward the North Star; reception is the default greeter (no user choice involved). ⚠️ Definition provisional")),
 ]),
 ("⑥ 星图 · Star Map", [
   ("starmap_seed_funnel", "种子星漏斗 · Seed-Star Funnel", "funnel",
       dict(note="冷启动展示 → 点种子星 → 转成实心星,按首次展示归入版本周 ｜ Cold-start display → tap seed star → converts to a solid star, grouped by release week")),
   ("starmap_new_user_stars", "新用户人均星数 · Stars per New User", "line", dict(
            note="每个新用户账上的累计星数,取平均 ｜ Avg cumulative stars per new user",val="star_count", agg="avg",
       dims=[("overall","Overall",None)])),
   ("starmap_cluster_maturity", "星主题分布 · Star Cluster Distribution", "line", dict(val="stars", where=("dim","cluster"),
       dims=[("overall","Overall",None),("value","by cluster","value")], note="当天新建的星按主题:core / heart / voice / mind / bond ｜ Stars created that day, by theme")),
   ("starmap_cluster_maturity", "星成熟度分布 · Star Maturity Distribution", "line", dict(val="stars", where=("dim","maturity"),
       dims=[("overall","Overall",None),("value","by maturity","value")], note="当天新建的星按成熟度:emerging → confirmed → faded ｜ Stars created that day, by maturity")),
   ("starmap_card_interaction", "星卡互动 · Star-Card Actions", "line", dict(
            note="展开星卡后的动作次数:explore_deeper / dismiss / vote / mute ｜ Actions taken after expanding a star card",val="taps",
       dims=[("overall","Overall",None),("action","by action","action")])),
 ]),
 ("⑦ 发现 · Discover", [
   ("discover_character_position_ctr", "角色卡 CTR · Character Card CTR (top-10 pos)", "rate",
       dict(rate=("taps","impressions"),
            note="角色目录里点击 ÷ 曝光,仅前 10 个排位;数据自 2.7.0(8/15 放量)起 ｜ Taps ÷ impressions in the character catalogue, top 10 positions; data starts with 2.7.0 (rolled out Aug 15)",
            only=[str(i) for i in range(10)], order=[str(i) for i in range(10)], slfmt=(lambda s:"位"+str(s)),
            dims=[("overall","Overall",None),("position","by position","position")])),
   ("discover_character_daily_ctr", "每日角色 CTR · Daily CTR by Character", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct1", **CHAR_DAILY_CTR_DIMS,
            note="每天各角色在目录里的点击 ÷ 曝光,按累计点击取 top 10(<20 不画)。"
                 "⚠️ 曝光少的角色开头几天 CTR 会偏高再回落,那是小样本收敛不是变差 ｜ "
                 "Daily taps ÷ impressions per character, top 10 by cumulative taps (<20 dropped)")),
   ("discover_character_by_tile", "角色卡漏斗分场景 · Character Funnel by Tile", "long_dim",
       dict(rate=("numerator","denominator"), fmt="pct1", **TILE_DIMS,
            note="角色卡按场景类别的三级转化:曝光→点击→开聊→深聊(≥5轮);曝光按(用户×角色×日)去重 ｜ Three-step conversion by scene category: impression → tap → chat → deep (≥5 turns); impressions deduped per user × character × day")),
   ("discover_character_coverage", "角色覆盖 · Character Coverage", "line",
       dict(val="characters", cap=4,
            note="每天被曝光 / 被点击过的**角色个数**(不是用户数);目录共 445 个角色 ｜ Number of distinct characters impressed / tapped each day (not users); the catalogue holds 445",
            dims=[("metric","","metric")])),
   ("discover_character_leaderboard", "角色表现榜 · Character Leaderboard", "table",
       dict(top=20, sort="ctr",
            # host_id 排最后:它最长、也最不常看,放前面会把关键列挤出可视区
            cols=[("character","角色 Character","text"),      ("tile","场景 Tile","text"),
                  ("first_seen","首次曝光 First Seen","text"), ("impressions","曝光 Impressions","int"),
                  ("taps","点击 Taps","int"),                 ("ctr","CTR","pct1"),
                  ("chatted","开聊 Chatted","int"),           ("chat_rate","点击→开聊 Tap→Chat","pct0"),
                  ("deep_rate","曝光→深聊 Impr→Deep","pct1"), ("host_key","host_id","text")],
            bar=["ctr","chat_rate","deep_rate"],
            note="近30天累计,每个角色一行,仅列曝光≥50 的角色;曝光按(用户×角色×日)去重 ｜ Last 30 days, one row per character, characters with ≥50 impressions only; impressions deduped per user × character × day")),
   ("discover_click_destination", "点击去向 · Click Destination", "line", dict(
            note="点击后跳去哪:站内详情 / 外链 / 付费墙 ｜ Where a tap goes: in-app detail / external link / paywall",val="taps",
       dims=[("overall","Overall",None),("destination","by destination","destination")])),
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
            note="和「角色表现榜」互补:那张看曝光→点击,这张看开聊→QCD→回访。仅列被 ≥20 人聊过的角色。⚠️「D7窗 回同一角色」现在必然是 0 —— 角色卡 8/14 才上线,大部分 cohort 的第 5 天还在未来,约 8/24 才能读第一批,**不是没有留存** ｜ Complements the Character Leaderboard: that one covers impression→tap, this one covers chat→QCD→return. Characters chatted by ≥20 users only. ⚠️ The D7-window column is necessarily 0 right now — character cards only launched Aug 14, so day 5 is still in the future for most cohorts; readable around Aug 24. Not a retention finding")),
 ]),
 ("⑧ 商业化 · Monetization", [
   ("monetize_usage_distribution_30d", "用量分位 · Usage Percentiles (30d)", "table",
       dict(top=6, sort="observations",
            cols=[("cohort","人群 Cohort","text"),
                  ("metric","计量口径 Metric","text"),
                  ("observations","样本 Observations","int"),
                  ("avg_messages","人均 Avg","d1"),
                  ("p50","P50","int"), ("p70","P70","int"),
                  ("p80","P80","int"), ("p90","P90","int"),
                  ("p95","P95","int"), ("p99","P99","int"),
                  ("max_value","最大 Max","int")],
            bar=["p80","p90"],
            note="定免费额度用的输入表。额度设在 P80 = 八成用户碰不到墙,设在 P90 = 只有一成碰到。⚠️ 三个人群的 P80 差 10 倍(全体 12 / 活跃≥3天 116 / 达成过QCD 27),**必须先选参照系再读数**,不要跨行比较 ｜ Input table for setting the free quota. A cap at P80 means 80% of users never hit the wall; at P90, only 10% do. ⚠️ P80 differs 10× across the three cohorts — pick a reference cohort before reading, never compare rows")),
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
                steps = sorted({r["step"] for r in rows}); s1 = steps[0] if steps else None
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
            # 表格卡:SQL 出什么就铺什么,渲染器不做聚合。用于**排行榜**这类
            # 折线/漏斗表达不了的形态(行数多、每行是一个实体、多列指标并列)。
            rows = metrics.get(mid)
            if not rows: return None
            cols = p["cols"]                      # [(列名, 表头, 格式)] 顺序即显示顺序
            miss = [c for c, _l, _f in cols if c not in rows[0]]
            if miss:
                raise ValueError(f"table 卡缺列 {miss},SQL 实际列: {list(rows[0])}")
            srt = p.get("sort") or cols[0][0]     # 默认按第一列降序
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
        for key, label, by in p["dims"]:
            ser = _rate(rows, p["rate"][0], p["rate"][1], by, dc=dc) if kind == "rate" \
                  else _agg(rows, p["val"], by, p.get("agg", "sum"), dc=dc)
            ser = ser if (p.get("only") or p.get("order")) else _cap(ser, p.get("cap", 6))
            dims.append({"key": key, "label": label, "data": {s: pts for s, pts in ser.items()}})
        dims = _finish(dims, p)
        base.update(kind="line", pct=pct, fmt=_fmt_of(kind, pct, p), dims=dims)
        return base
    except Exception as ex:
        base.update(kind="line", pct=False, fmt="int", dims=[], error=str(ex))
        return base

# ---------- 柔和统一配色 ----------
PAL = ["#6f9de0", "#5cbfa6", "#e0b366", "#9a8cd9", "#e0899f", "#7cc490", "#8b98ac", "#d69a72"]
WKPAL = ["#bcd3f2", "#8fb4e6", "#6f9de0", "#4a79c9"]   # 4 版本周,由浅到深(旧→新)

# 卡名别名:现 Metabase 卡名 → 权威清单 metric_id(两种名字都能认)
ALIAS = {
    "growth_new_users": "growth_new_user",
    "growth_activated_new_users": "growth_new_activated_user",
    "growth_deep_new_users": "growth_new_activated_user",   # 2026-08-14 卡名 Activated → Deep(阈值≥3→≥5);旧名保留以便回滚
    "activation_first_msg_latency": "activation_user_first_latency",
    # 2026-08-18 卡名 card ctr → position ctr;Metabase 若未同步改名,旧名兜底
    "discover_character_card_ctr": "discover_character_position_ctr",
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

STALE_MAX_DAYS = 3    # 抓失败时沿用上一次的值,但最多 3 天 —— 再久就让卡消失。
                     # 不设上限的话,长期超时的卡(AI 响应时延等)会永久显示冻结数据,
                     # 比"图不见了"更危险:看的人不会怀疑一张画得好好的图。


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
    """这次没抓到 → 沿用上一次的卡。stale 记的是**数据真正的日期**,沿用链上不刷新,
    否则一张永久超时的卡会天天显示"昨天",永远不过期。"""
    card = prev_cards.get(mid)
    if not card: return None
    stale = card.get("stale") or prev_date
    if not stale: return None
    try:
        age = (datetime.now().date() - datetime.strptime(stale, "%Y-%m-%d").date()).days
    except ValueError:
        return None
    if age > STALE_MAX_DAYS: return None
    out = dict(card); out["stale"] = stale
    return out


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
    # 副标题第二行:说明埋点类图表的固有延迟。实测 ETL 每天 SGT 13:00-13:03 入库前一天的数据
    # (连续 5 天一分不差),所以 13:00 前最新只到前天。服务端库(留存/对话)不走这条链路,实时。
    lag_note = ('每天 13:00(SGT) 入库前一天的埋点数据,数据有延迟'
                ' ｜ Event data for the previous day lands at 13:00 SGT — charts lag accordingly')
    hdr = (f'<header><h1>SoulMap 看板 · SoulMap Dashboard</h1><div class="meta">'
           f'数据 {meta.get("run_date","?")} · Metabase dashboard {meta.get("dashboard_id","?")} · '
           f'{sum(len(s["cards"]) for s in sections)} 卡'
           + (f' · 缺 {len(failed)}' if failed else '')
           + (f' · 沿用旧值 {len(carried)}' if carried else '') +
           f'</div><div class="meta lag">{lag_note}</div></header>'
           + (f'<div class="banner">{BANNER}</div>' if BANNER else ''))
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
    print(f"✅ 写出 {out_path} ({len(sections)} 板块, {sum(len(s['cards']) for s in sections)} 卡"
          + (f", 沿用旧值 {len(carried)}: {carried}" if carried else "") + ")")

APP_JS = r"""
const $=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;};
function fmtV(v,fmt){if(v==null)return'';
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
  '冷启动展示':'冷启动展示 Cold Shown','种子星点击':'种子星点击 Seed Tap','转成实心星':'转成实心星 Owned'};
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
      const txt=isNum?fmtV(+v,c.fmt):(v==null?'':String(v));
      const safe=String(txt).replace(/"/g,'&quot;');
      if(c.max){const w=c.max>0?Math.max(0,Math.min(100,(+v)/c.max*100)):0;
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
modal.addEventListener('click',e=>{if(e.target===modal||e.target.className==='mclose')modal.style.display='none';});
let modalChart=null;
function openLineDetail(card,data){modal.querySelector('.mtitle').textContent=card.title;
  const mb=modal.querySelector('.mbody');mb.style.height='64vh';mb.innerHTML='';
  const cv=document.createElement('canvas');mb.appendChild(cv);
  if(modalChart)modalChart.destroy();modalChart=new Chart(cv,lineCfg(data,card.fmt));modalChart.$fmt=card.fmt;
  modal.style.display='flex';}
function openFunnelDetail(card,wk){modal.querySelector('.mtitle').textContent=card.title+(wk?'  ·  '+wk:'');
  const mb=modal.querySelector('.mbody');mb.style.height='auto';mb.innerHTML='';
  const box=$('div');mb.appendChild(box);drawFunnel(box,card,wk);modal.style.display='flex';}
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
