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
import argparse, json
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEEK_ORDER = ["6/27-7/3", "7/4-10", "7/11-17", "7/18起"]

# 顶部数据可靠性横幅(置空字符串即隐藏;以后有新事件改这里)
BANNER = ("提示:本周多项改动叠加、App 有过短暂不稳定(已陆续修复),"
          "干净可测窗口较短 —— 本周数据仅供参考,请谨慎下结论。")

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
        s = (str(by(r)) if callable(by) else str(r.get(by))) if by else "总计"
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
        s = (str(by(r)) if callable(by) else str(r.get(by))) if by else "总计"
        a = acc[(s, _nd(d))]; a[0] += _num(r.get(num)); a[1] += _num(r.get(den))
    out = defaultdict(list)
    for (s, d), (n, dd) in acc.items():
        out[s].append((d, round(n / dd, 4) if dd else 0.0))
    for s in out: out[s].sort()
    return out

def _share(rows, col, value, by=None, dc="date"):
    """某列取某值的占比(如 modality='voice' 的比例),按 date(×by)。"""
    acc = defaultdict(lambda: [0, 0])
    for r in rows:
        d = r.get(dc)
        if d is None: continue
        s = (str(by(r)) if callable(by) else str(r.get(by))) if by else "总计"
        a = acc[(s, _nd(d))]; a[1] += 1
        if str(r.get(col)) == value: a[0] += 1
    out = defaultdict(list)
    for (s, d), (n, t) in acc.items():
        out[s].append((d, round(n / t, 4) if t else 0.0))
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

# ---------- 注册表 ----------
# line 卡: dims = [(key,label,by_col)]; by_col=None 即总体
# rate 卡: 加 rate=(num,den); rate_cols: cols+den; ret_multi: cards; funnel: 无参
SECTIONS = [
 ("① 增长 · Growth", [
   ("growth_dau", "日活跃用户数 DAU", "line", dict(val="value", cap=12,
       dims=[("overall","Overall",None),("user_type","by user type","user_type"),("source","by source","source"),("adgroup","by source×adgroup",_ADG)])),
   ("growth_dau_new_returning", "DAU 新老占比 · New vs Returning", "pct_split", dict(val="value", by="user_type", fmt="pct0",
       note="新/老用户各占当天 DAU 的比例")),
   ("growth_new_user", "新用户数 · New Users", "line", dict(val="value", cap=12,
       dims=[("overall","Overall",None),("source","by source","source"),("adgroup","by source×adgroup",_ADG)])),
   ("growth_new_activated_user", "激活新用户数 · Activated New Users", "line", dict(val="value", cap=12,
       note="激活新用户 = 新用户中当天对话≥3轮的人(1问1答=1轮)",
       dims=[("overall","Overall",None),("source","by source","source"),("adgroup","by source×adgroup",_ADG)])),
 ]),
 ("② 激活 · Activation", [
   ("activation_funnel", "激活漏斗 Activation Funnel · 4 版本周", "funnel",
       dict(note="activated=对话≥3轮 · deep=对话≥5轮(1问1答=1轮)")),
   ("activation_funnel_by_adgroup", "激活漏斗 · 分 adgroup · by Ad Group", "funnel",
       dict(note="按 source×广告类型分组对比,右上/toolbar 切组;近4版本周·取前8组")),
   ("activation_guardrail_funnel", "护栏漏斗 · 分版本 · Guardrail by Version", "funnel",
       dict(gsort="version", note="onboarding 漏斗按 app_version 对比(看新 chip 有没有增流失);近30天·选topic=主动选")),
   ("activation_onboarding_dropoff", "Onboarding 流失 · Onboarding Dropoff", "line", dict(val="value",
       dims=[("overall","Overall",None),("last_scene","by scene","last_scene")])),
   ("activation_user_first_latency", "用户首条消息时延 · User First-Msg Latency (avg s)", "line", dict(val="avg_secs", agg="avg",
       note="用户看到 AI 首句后多久发出第一条消息",
       dims=[("overall","Overall",None)])),
   ("activation_ai_first_latency", "AI 首条响应时延 · AI First-Reply Latency (avg s)", "line", dict(val="avg_secs", agg="avg",
       dims=[("overall","Overall",None)])),
 ]),
 ("③ 留存 · Retention", [
   ("retention_d1", "留存 D1 · Retention D1", "retention_day",
       dict(day="d1", note="注册后第1天回访开App的比例;可切 Overall/来源/adgroup/path/激活")),
   ("retention_d3", "留存 D3 · Retention D3", "retention_day", dict(day="d3")),
   ("retention_d7", "留存 D7 · Retention D7", "retention_day",
       dict(day="d7", note="⚠️ 近7天 cohort 的 D7 未成熟(窗口未到),看趋势排除末尾几天")),
 ]),
 ("④ 模块 · Modules", [
   ("module_tab_penetration", "四 Tab 渗透率 · Tab Penetration", "rate_cols",
       dict(note="当天开 App 用户中访问过各 Tab 的比例", fmt="pct0",
            den="active_users", cols=[("Stars","stars_users"),("Chat","chat_users"),
            ("Discover","discover_users"),("Me","me_users")])),
   ("module_tab_opens_per_user", "人均 Tab 打开次数 · Tab Opens per User", "rate_cols",
       dict(den="active_users", pct=False, cols=[("Stars","stars_opens"),("Chat","chat_opens"),
            ("Discover","discover_opens"),("Me","me_opens")])),
   ("module_locked_tab_tap", "锁定 Tab 点击率 · Locked-Tab Tap Rate", "rate", dict(rate=("users","active_users"),
       note="点击未解锁 Tab 的人 ÷ 当天活跃",
       dims=[("tab_name","by tab","tab_name")])),
 ]),
 ("⑤ Chat", [
   ("chat_msgs_per_user", "人均消息数 · Msgs per User (avg)", "line", dict(val="total_msgs", agg="avg",
       note="统计期内每人总消息数(来回都算)取平均;分母=真聊过的用户,非DAU",
       dims=[("overall","Overall",None)])),
   ("chat_turns_distribution", "每场对话轮数 · Turns per Session (avg)", "line", dict(val="turn_count", agg="avg",
       note="1 问 1 答 = 1 轮", dims=[("overall","Overall",None)])),
   ("chat_session_duration", "对话时长 · Session Duration (avg min)", "line", dict(val="duration_min", agg="avg",
       note="单场会话首末消息时长,取平均(含中途挂机)",
       dims=[("overall","Overall",None)])),
   ("chat_silent_rate", "Silent 会话率 · Silent-Session Rate", "rate", dict(rate=("silent_sessions","sessions"),
       note="有进无出:开了会话但没发消息的比例",
       dims=[("overall","Overall",None),("path","by path","path")])),
   ("chat_voice_text_ratio", "语音消息占比 · Voice Msg Share", "share", dict(col="modality", value="voice",
       dims=[("overall","Overall",None)])),
   ("chat_ai_latency", "AI 响应时延 · AI Reply Latency (avg s)", "line", dict(val="latency_sec", agg="avg",
       dims=[("overall","Overall",None)])),
   ("chat_msg_length", "用户消息长度 · Msg Length (avg chars)", "line", dict(val="char_len", agg="avg",
       dims=[("overall","Overall",None)])),
 ]),
 ("⑥ Star", [
   ("starmap_seed_funnel", "种子星漏斗 Seed-Star Funnel · 4 版本周", "funnel",
       dict(note="冷启动展示 → 点种子星 → 转成实心星")),
   ("starmap_new_user_stars", "新用户人均星数 · Stars per New User", "line", dict(val="star_count", agg="avg",
       dims=[("overall","Overall",None)])),
   ("starmap_cluster_maturity", "星主题分布 · Star Cluster", "line", dict(val="stars", where=("dim","cluster"),
       dims=[("value","by cluster","value")], note="每天新增星按主题:core/heart/voice/mind/bond")),
   ("starmap_cluster_maturity", "星成熟度分布 · Star Maturity", "line", dict(val="stars", where=("dim","maturity"),
       dims=[("value","by maturity","value")], note="每天新增星按成熟度:emerging→confirmed→faded 等")),
   ("starmap_card_interaction", "星卡互动 · Star-Card Actions", "line", dict(val="taps",
       dims=[("action","by action","action")])),
 ]),
 ("⑦ Discover", [
   ("discover_visit_rate", "Discover 访问率 · Visit Rate", "rate", dict(rate=("discover_users","active_users"),
       note="进 Discover 的用户 ÷ 当天活跃",
       dims=[("overall","Overall",None),("user_stage","by stage","user_stage")])),
   ("discover_scroll_depth", "滚动深度分布 · Scroll Depth", "line", dict(val="users", slfmt=(lambda s: str(int(float(s)))+"%"),
       dims=[("depth_pct","by depth","depth_pct")])),
   ("discover_card_ctr", "卡片 CTR · Card CTR (top-10 pos)", "rate", dict(rate=("taps","impressions"),
       note="仅前 10 个排位;深位曝光少、CTR 噪声大已略去",
       only=[str(i) for i in range(10)], order=[str(i) for i in range(10)], slfmt=(lambda s:"位"+str(s)),
       dims=[("position","by position","position")])),
   ("discover_empty_state", "空状态表现 · Empty State", "line", dict(val="empty_users",
       slfmt=(lambda s: {"early_turn":"轮次太少","generating":"生成中"}.get(s,s)),
       note="Discover 冷启动填充失败:轮次太少/内容生成中",
       dims=[("reason","by reason","reason")])),
   ("discover_click_destination", "点击去向 · Click Destination", "line", dict(val="taps",
       dims=[("destination","by destination","destination")])),
 ]),
]

def _fmt_of(kind, pct, p):
    """每张图统一的小数格式:pct=百分比1位 / d1=1位小数 / int=整数。"""
    if p.get("fmt"): return p["fmt"]
    if pct: return "pct"
    if kind == "rate_cols" or p.get("agg") == "avg": return "d1"
    return "int"

def _finish(dims, p):
    """按 order 固定序列顺序 + 按 slfmt 改序列名(如 25→25%、position→位N、reason→中文)。"""
    order, slfmt, only = p.get("order"), p.get("slfmt"), p.get("only")
    for dm in dims:
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
        if kind == "ret_multi":
            data = {}
            for cmid, lbl, num, den in p["cards"]:
                r = metrics.get(cmid)
                if r: data[lbl] = _rate(r, num, den, dc=_dc(r)).get("总计", [])
            if not data: return None
            base.update(kind="line", pct=True, fmt="pct",
                        dims=[{"key": "overall", "label": "D1/D3/D7", "data": data}])
            return base
        if kind == "retention_day":   # 单张 Dx:overall/source/adgroup(来自 retention_dX)+ path/activation(来自另两卡)
            num = p["day"] + "_retained"; dims = []
            main = metrics.get(mid)
            if main:
                dc = _dc(main)
                dims.append({"key":"overall","label":"Overall","data":dict(_rate(main,num,"new_users",None,dc=dc))})
                dims.append({"key":"source","label":"by source","data":dict(_cap(_rate(main,num,"new_users","source",dc=dc)))})
                dims.append({"key":"adgroup","label":"by adgroup","data":dict(_cap(_rate(main,num,"new_users",_ADG,dc=dc),12))})
            pr = metrics.get("retention_by_path")
            if pr:
                dims.append({"key":"path","label":"by path","data":_ord(dict(_rate(pr,num,"new_users","path",dc=_dc(pr))),["text","voice","unknown"])})
            ar = metrics.get("retention_by_activated")
            if ar:
                dims.append({"key":"act","label":"by activation","data":_ord(dict(_rate(ar,num,"new_users","is_activated",dc=_dc(ar))),["activated","not_activated"])})
            if not any(d["data"] for d in dims): return None
            base.update(kind="line", pct=True, fmt="pct", dims=dims)
            return base
        rows = metrics.get(mid)
        if not rows: return None
        if p.get("where"):
            wc, wv = p["where"]; rows = [r for r in rows if str(r.get(wc)) == wv]
            if not rows: return None
        dc = _dc(rows)
        pct = p.get("pct", kind in ("rate", "rate_cols", "share", "rate_days", "pct_split"))
        dims = []
        if kind == "pct_split":            # 每类别占当天总量的比例(如 DAU 新老占比)
            tot = {d: v for d, v in _agg(rows, p["val"], None, "sum", dc=dc).get("总计", [])}
            ser = _agg(rows, p["val"], p["by"], "sum", dc=dc)
            data = {s: [[d, round(v / tot[d], 4) if tot.get(d) else 0] for d, v in pts] for s, pts in ser.items()}
            dims = [{"key": "overall", "label": "", "data": data}]
        elif kind == "rate_cols":
            data = {}
            den = p["den"]
            for lbl, nc in p["cols"]:
                data[lbl] = _rate(rows, nc, den, dc=dc).get("总计", [])
            dims = [{"key": "overall", "label": "", "data": data}]
        elif kind == "rate_days":              # 留存:D1/D3/D7 各一个切换,序列 = split 值
            den, split = p["den"], p["split"]
            for dlbl, num in p["days"]:
                ser = _rate(rows, num, den, split, dc=dc)
                dims.append({"key": dlbl, "label": dlbl, "data": {s: pts for s, pts in ser.items()}})
        elif kind == "share":
            for key, label, by in p["dims"]:
                ser = _cap(_share(rows, p["col"], p["value"], by, dc=dc))
                dims.append({"key": key, "label": label, "data": {s: pts for s, pts in ser.items()}})
        else:
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
    "activation_first_msg_latency": "activation_user_first_latency",
}

CSS = """
:root{--surface:#fcfcfb;--plane:#f7f7f5;--tp:#1f2430;--ts:#5b6270;--mut:#9aa0ac;
--grid:#edeef1;--bd:#e7e8ec;--acc:#6f9de0}
:root[data-theme=dark],@media (prefers-color-scheme:dark){}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--surface:#1b1c1f;--plane:#141517;--tp:#f2f3f5;
--ts:#b7bcc7;--mut:#7f8794;--grid:#2a2c30;--bd:#2f3237;--acc:#8fb4e6}}
:root[data-theme=dark]{--surface:#1b1c1f;--plane:#141517;--tp:#f2f3f5;--ts:#b7bcc7;--mut:#7f8794;--grid:#2a2c30;--bd:#2f3237;--acc:#8fb4e6}
*{box-sizing:border-box}body{margin:0;background:var(--plane);color:var(--tp);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;font-size:14px}
header{padding:22px 26px 8px}h1{margin:0;font-size:19px;font-weight:650}
.meta{color:var(--mut);font-size:12px;margin-top:4px}
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

def render(raw_path: Path, out_path: Path):
    D = json.loads(raw_path.read_text(encoding="utf-8"))
    meta = D.get("_meta", {}); metrics = D.get("metrics", D)
    for a, c in ALIAS.items():          # 现卡名 → 权威 metric_id,两种都能认
        if a in metrics and c not in metrics: metrics[c] = metrics[a]
    sections = []
    for sec, cards in SECTIONS:
        built = [c for c in (build_card(metrics, *spec) for spec in cards) if c]
        if built: sections.append({"title": sec, "cards": built})
    chartjs = (HERE / "lib" / "chart.umd.min.js").read_text(encoding="utf-8")
    payload = json.dumps({"sections": sections, "pal": PAL, "wkpal": WKPAL}, ensure_ascii=False)
    failed = meta.get("failed") or []
    hdr = (f'<header><h1>SoulMap 看板 · 趋势版 · SoulMap Dashboard</h1><div class="meta">'
           f'数据 {meta.get("run_date","?")} · Metabase dashboard {meta.get("dashboard_id","?")} · '
           f'{sum(len(s["cards"]) for s in sections)} 卡' + (f' · 缺 {len(failed)}' if failed else '') +
           '</div></header>' + (f'<div class="banner">{BANNER}</div>' if BANNER else ''))
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SoulMap 看板 · 趋势版 · SoulMap Dashboard</title>
<style>{CSS}</style></head><body>{hdr}<div id="root"></div>
<script>{chartjs}</script>
<script>const DATA={payload};</script>
<script>{APP_JS}</script></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    print(f"✅ 写出 {out_path} ({len(sections)} 板块, {sum(len(s['cards']) for s in sections)} 卡)")

APP_JS = r"""
const $=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;};
function fmtV(v,fmt){if(v==null)return'';
  if(fmt==='pct')return(v*100).toFixed(1)+'%';
  if(fmt==='pct0')return(v*100).toFixed(0)+'%';
  if(fmt==='d1')return(+v).toFixed(1);
  return Math.round(v).toLocaleString();}
const STEPMAP={'打开':'打开 Open','Welcome':'Welcome','进入onboarding':'进入 Onboarding',
 '完成onboarding':'完成 Onboarding','用户首条':'用户首条 First Msg','activated(3+)':'激活 Activated ≥3',
 'deep(5+)':'深度 Deep ≥5','冷启动展示':'冷启动展示 Cold Shown','种子星点击':'种子星点击 Seed Tap','转成实心星':'转成实心星 Owned'};
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
  let v;if(dd['总计']){const p=dd['总计'].find(x=>x[0]===d);v=p?p[1]:0;}
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
      y:{grid:{color:c.grid},border:{display:false},ticks:{color:c.mut,font:{size:10},
        callback:v=>fmtV(v,fmt)}}}}};
}
function funnelCfg(card){const c=ink();const W=DATA.wkpal;
  const ds=card.weeks.map((w,i)=>({label:w,data:card.steps.map(s=>card.matrix[s][w]||0),
    backgroundColor:W[i%W.length],borderRadius:4,borderSkipped:false}));
  return{type:'bar',data:{labels:card.steps.map(s=>s.replace(/^[0-9]+_/,'')),datasets:ds},plugins:[valueLabels],
    options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:14}},
      plugins:{legend:{position:'top',align:'start',labels:{boxWidth:10,boxHeight:10,usePointStyle:true,pointStyle:'rect',color:c.ts,font:{size:11}}}},
      scales:{x:{grid:{display:false},ticks:{color:c.mut,font:{size:10}},border:{color:c.grid}},
        y:{grid:{color:c.grid},border:{display:false},ticks:{color:c.mut,font:{size:10},callback:v=>(+v).toLocaleString()}}}}};
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
      if(card.note)el.appendChild($('div','cnote',card.note));
      if(card.error){el.appendChild($('div','empty','渲染失败: '+card.error));g.appendChild(el);return;}
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
        const all=$('button','chip'+(vis.size===names.length?' on':''),'全部');
        all.onclick=()=>{vis=new Set(names);chips();redraw();};chipbar.appendChild(all);
        names.forEach(n=>{const b=$('button','chip'+(vis.has(n)?' on':''),n);
          b.onclick=()=>{if(vis.size===names.length){vis=new Set([n]);}      // 全开时点一个=只看它(单选)
            else if(vis.has(n)){vis.delete(n);if(!vis.size)vis=new Set(names);}// 关到空则复位
            else{vis.add(n);}                                                 // 否则加选(多选)
            chips();redraw();};chipbar.appendChild(b);});}
      function applyDim(i){cur=i;vis=new Set(Object.keys((dims[i]||{data:{}}).data));chips();redraw();}
      applyDim(0);
    });
  });
  nav.appendChild($('div','sp'));
  const tg=$('button','nb','◐ 主题');tg.onclick=()=>{document.documentElement.setAttribute('data-theme',isDark()?'light':'dark');build();};
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
