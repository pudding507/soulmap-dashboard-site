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
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEEK_ORDER = ["6/27-7/3", "7/4-10", "7/11-17", "7/18起"]

# ---------- 聚合 ----------
def _num(x):
    try: return float(x)
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
        s = str(r.get(by)) if by else "总计"
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
        s = str(r.get(by)) if by else "总计"
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
        s = str(r.get(by)) if by else "总计"
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

# ---------- 注册表 ----------
# line 卡: dims = [(key,label,by_col)]; by_col=None 即总体
# rate 卡: 加 rate=(num,den); rate_cols: cols+den; ret_multi: cards; funnel: 无参
SECTIONS = [
 ("① 增长", [
   ("growth_dau", "日活跃用户数 (DAU)", "line", dict(val="value",
       dims=[("overall","总体",None),("user_type","按新老","user_type"),("source","按来源","source")])),
   ("growth_dau_new_returning", "DAU 新老占比", "line", dict(val="value",
       dims=[("user_type","新/老","user_type")])),
   ("growth_new_user", "新用户数", "line", dict(val="value",
       dims=[("overall","总体",None),("source","按来源","source")])),
   ("growth_new_activated_user", "激活新用户数", "line", dict(val="value",
       dims=[("overall","总体",None),("source","按来源","source")])),
 ]),
 ("② 激活", [
   ("activation_funnel", "激活漏斗 · 4 版本周", "funnel", {}),
   ("activation_onboarding_dropoff", "Onboarding 流失", "line", dict(val="value",
       dims=[("overall","总体",None),("last_scene","按断点","last_scene")])),
   ("activation_user_first_latency", "用户首条消息时延(日均秒)", "line", dict(val="avg_secs", agg="avg",
       dims=[("overall","总体",None)])),
   ("activation_ai_first_latency", "AI 首条响应时延(日均秒)", "line", dict(val="avg_secs", agg="avg",
       dims=[("overall","总体",None)])),
 ]),
 ("③ 留存", [
   ("__ret__", "留存率 D1/D3/D7", "ret_multi", dict(cards=[
       ("retention_d1","D1","d1_retained","new_users"),
       ("retention_d3","D3","d3_retained","new_users"),
       ("retention_d7","D7","d7_retained","new_users")])),
   ("retention_by_path", "留存 · 按 path(D1)", "rate", dict(rate=("d1_retained","new_users"),
       dims=[("path","按 path","path")])),
   ("retention_by_activated", "留存 · 按激活(D1)", "rate", dict(rate=("d1_retained","new_users"),
       dims=[("is_activated","按激活","is_activated")])),
 ]),
 ("④ 模块", [
   ("module_tab_penetration", "四 Tab 渗透率", "rate_cols",
       dict(den="active_users", cols=[("Stars","stars_users"),("Chat","chat_users"),
            ("Discover","discover_users"),("Me","me_users")])),
   ("module_tab_opens_per_user", "人均 Tab 打开次数", "rate_cols",
       dict(den="active_users", pct=False, cols=[("Stars","stars_opens"),("Chat","chat_opens"),
            ("Discover","discover_opens"),("Me","me_opens")])),
   ("module_locked_tab_tap", "锁定 Tab 点击率", "rate", dict(rate=("users","active_users"),
       dims=[("tab_name","按 tab","tab_name")])),
 ]),
 ("⑤ Chat", [
   ("chat_msgs_per_user", "人均消息数(日均)", "line", dict(val="total_msgs", agg="avg",
       dims=[("overall","总体",None)])),
   ("chat_turns_distribution", "每场对话轮数(日均)", "line", dict(val="turn_count", agg="avg",
       dims=[("overall","总体",None)])),
   ("chat_session_duration", "对话时长(日均分钟)", "line", dict(val="duration_min", agg="avg",
       dims=[("overall","总体",None)])),
   ("chat_silent_rate", "Silent 会话率", "rate", dict(rate=("silent_sessions","sessions"),
       dims=[("overall","总体",None),("path","按 path","path")])),
   ("chat_voice_text_ratio", "语音消息占比", "share", dict(col="modality", value="voice",
       dims=[("overall","总体",None)])),
   ("chat_ai_latency", "AI 响应时延(日均秒)", "line", dict(val="latency_sec", agg="avg",
       dims=[("overall","总体",None)])),
   ("chat_msg_length", "用户消息长度(日均字符)", "line", dict(val="char_len", agg="avg",
       dims=[("overall","总体",None)])),
 ]),
 ("⑥ 星图", [
   ("starmap_seed_funnel", "种子星漏斗 · 4 版本周", "funnel", {}),
   ("starmap_new_user_stars", "新用户人均星数(按安装日)", "line", dict(val="star_count", agg="avg",
       dims=[("overall","总体",None)])),
   ("starmap_cluster_maturity", "星主题分布 (cluster)", "line", dict(val="stars", where=("dim","cluster"),
       dims=[("value","按主题","value")])),
   ("starmap_cluster_maturity", "星成熟度分布 (maturity)", "line", dict(val="stars", where=("dim","maturity"),
       dims=[("value","按成熟度","value")])),
   ("starmap_card_interaction", "星卡互动:展开动作", "line", dict(val="taps",
       dims=[("action","按动作","action")])),
 ]),
 ("⑦ Discover", [
   ("discover_visit_rate", "Discover 访问率", "rate", dict(rate=("discover_users","active_users"),
       dims=[("overall","总体",None),("user_stage","按阶段","user_stage")])),
   ("discover_scroll_depth", "滚动深度分布", "line", dict(val="users",
       dims=[("depth_pct","按深度","depth_pct")])),
   ("discover_card_ctr", "卡片 CTR(按位)", "rate", dict(rate=("taps","impressions"),
       dims=[("position","按位置","position")])),
   ("discover_empty_state", "空状态表现", "line", dict(val="empty_users",
       dims=[("reason","按原因","reason")])),
   ("discover_click_destination", "点击去向", "line", dict(val="taps",
       dims=[("destination","按去向","destination")])),
 ]),
]

def build_card(metrics, mid, title, kind, p):
    base = dict(id=mid, title=title, kind=kind)
    try:
        if kind == "funnel":
            rows = metrics.get(mid) or []
            if not rows or "step" not in rows[0]: return None   # 卡还是旧格式(非4版本周)→ 先跳过
            weeks = [w for w in WEEK_ORDER if w in rows[0]]
            base.update(steps=[r["step"] for r in rows], weeks=weeks,
                        matrix={r["step"]: {w: _num(r.get(w)) for w in weeks} for r in rows})
            return base
        if kind == "ret_multi":
            data = {}
            for cmid, lbl, num, den in p["cards"]:
                r = metrics.get(cmid)
                if r: data[lbl] = _rate(r, num, den, dc=_dc(r)).get("总计", [])
            if not data: return None
            base.update(kind="line", pct=True, dims=[{"key": "overall", "label": "D1/D3/D7", "data": data}])
            return base
        rows = metrics.get(mid)
        if not rows: return None
        if p.get("where"):
            wc, wv = p["where"]; rows = [r for r in rows if str(r.get(wc)) == wv]
            if not rows: return None
        dc = _dc(rows)
        pct = p.get("pct", kind in ("rate", "rate_cols", "share"))
        dims = []
        if kind == "rate_cols":
            data = {}
            den = p["den"]
            for lbl, nc in p["cols"]:
                data[lbl] = _rate(rows, nc, den, dc=dc).get("总计", [])
            dims = [{"key": "overall", "label": "", "data": data}]
        elif kind == "share":
            for key, label, by in p["dims"]:
                ser = _cap(_share(rows, p["col"], p["value"], by, dc=dc))
                dims.append({"key": key, "label": label, "data": {s: pts for s, pts in ser.items()}})
        else:
            for key, label, by in p["dims"]:
                ser = _rate(rows, p["rate"][0], p["rate"][1], by, dc=dc) if kind == "rate" \
                      else _agg(rows, p["val"], by, p.get("agg", "sum"), dc=dc)
                ser = _cap(ser)
                dims.append({"key": key, "label": label, "data": {s: pts for s, pts in ser.items()}})
        base.update(kind="line", pct=pct, dims=dims)
        return base
    except Exception as ex:
        base.update(kind="line", pct=False, dims=[], error=str(ex))
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
    hdr = (f'<header><h1>SoulMap 看板 · 趋势版</h1><div class="meta">'
           f'数据 {meta.get("run_date","?")} · Metabase dashboard {meta.get("dashboard_id","?")} · '
           f'{sum(len(s["cards"]) for s in sections)} 卡' + (f' · 缺 {len(failed)}' if failed else '') +
           '</div></header>')
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SoulMap 看板 · 趋势版</title>
<style>{CSS}</style></head><body>{hdr}<div id="root"></div>
<script>{chartjs}</script>
<script>const DATA={payload};</script>
<script>{APP_JS}</script></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    print(f"✅ 写出 {out_path} ({len(sections)} 板块, {sum(len(s['cards']) for s in sections)} 卡)")

APP_JS = r"""
const $=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;};
function fmtV(v,pct){if(v==null)return'';if(pct)return(v*100).toFixed(v<0.1?1:0)+'%';
  const a=Math.abs(v);return a>=1000?Math.round(v).toLocaleString():(a>=10||a===0?Math.round(v).toString():v.toFixed(1));}
const valueLabels={id:'vlab',afterDatasetsDraw(chart){const ctx=chart.ctx,pct=!!chart.$pct,bar=chart.config.type==='bar';
  const ic=ink();ctx.save();ctx.font='600 9px -apple-system,BlinkMacSystemFont,sans-serif';ctx.textAlign='center';
  chart.data.datasets.forEach((ds,di)=>{const m=chart.getDatasetMeta(di);if(m.hidden)return;
    m.data.forEach((pt,idx)=>{const v=ds.data[idx];if(v==null)return;
      ctx.fillStyle=bar?ic.ts:(ds.borderColor||ic.ts);ctx.fillText(fmtV(+v,pct),pt.x,pt.y-5);});});
  ctx.restore();}};
function isDark(){const r=document.documentElement.getAttribute('data-theme');
  return r?r==='dark':matchMedia('(prefers-color-scheme:dark)').matches;}
function ink(){const s=getComputedStyle(document.documentElement);
  return {ts:s.getPropertyValue('--ts').trim(),mut:s.getPropertyValue('--mut').trim(),grid:s.getPropertyValue('--grid').trim()};}
const charts=[];
function allDates(data){const s=new Set();for(const k in data)data[k].forEach(p=>s.add(p[0]));return[...s].sort();}
function lineCfg(dimData,pct){
  const labels=allDates(dimData);const names=Object.keys(dimData);const P=DATA.pal;
  const ds=names.map((nm,i)=>{const m=Object.fromEntries(dimData[nm]);
    return{label:nm,data:labels.map(d=>d in m?m[d]:null),borderColor:P[i%P.length],
      backgroundColor:P[i%P.length],borderWidth:2,tension:.3,cubicInterpolationMode:'monotone',
      pointRadius:0,pointHoverRadius:4,spanGaps:true};});
  const c=ink();
  return{type:'line',data:{labels,datasets:ds},plugins:[valueLabels],options:{responsive:true,maintainAspectRatio:false,
    layout:{padding:{top:14}},interaction:{mode:'index',intersect:false},
    plugins:{legend:{display:names.length>1,position:'top',align:'start',
      labels:{boxWidth:10,boxHeight:10,usePointStyle:true,pointStyle:'circle',color:c.ts,font:{size:11}}},
      tooltip:{callbacks:{label:x=>x.dataset.label+': '+(pct?(x.parsed.y*100).toFixed(1)+'%':(+x.parsed.y).toLocaleString())}}},
    scales:{x:{grid:{display:false},ticks:{color:c.mut,font:{size:10},maxRotation:0,autoSkipPadding:16,
        callback:function(v){return this.getLabelForValue(v).slice(5);}},border:{color:c.grid}},
      y:{grid:{color:c.grid},border:{display:false},ticks:{color:c.mut,font:{size:10},
        callback:v=>pct?(v*100).toFixed(0)+'%':(+v).toLocaleString()}}}}};
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
      const el=$('div','card');el.appendChild($('h3',null,card.title));
      if(card.error){el.appendChild($('div','empty','渲染失败: '+card.error));g.appendChild(el);return;}
      const cw=$('div','cw');const cv=document.createElement('canvas');cw.appendChild(cv);
      if(card.kind==='funnel'){el.appendChild(cw);g.appendChild(el);
        const fc=new Chart(cv,funnelCfg(card));fc.$pct=false;charts.push(fc);return;}
      const dims=card.dims||[];
      if(dims.length>1){const tb=$('div','toolbar');
        dims.forEach((dm,i)=>{const b=$('button','tbtn'+(i===0?' on':''),dm.label);
          b.onclick=()=>{const ch=cw._chart;const cfg=lineCfg(dm.data,card.pct);
            ch.data=cfg.data;ch.options=cfg.options;ch.update();
            tb.querySelectorAll('.tbtn').forEach(x=>x.classList.remove('on'));b.classList.add('on');};
          tb.appendChild(b);});el.appendChild(tb);}
      el.appendChild(cw);g.appendChild(el);
      const d0=(dims[0]&&dims[0].data)||{};
      const ch=new Chart(cv,lineCfg(d0,card.pct));ch.$pct=card.pct;cw._chart=ch;charts.push(ch);
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
