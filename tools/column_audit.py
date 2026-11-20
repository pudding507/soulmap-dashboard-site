#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看板列核对 · 三种自动扫描(只读,不改任何东西)

方法说明见 soulmap_dashboard_docs/08_方法论与Skills/04_看板列核对方法_2026-11-20.md。
2026-11-20 新建。读本地 raw_metrics.json(抓数产物),一次几秒。

    python3 tools/column_audit.py --all               # 三种全跑
    python3 tools/column_audit.py --stale             # 只跑列级停更
    python3 tools/column_audit.py --all --section 增长 # 只看某个板块

🛑 **扫描报出来的是「可疑的」,不是「错的」**。每一条都要回去读卡头注释和查库才能定性。
   反过来也成立:**没报出来的是「这几道筛子看不出问题」,不是「这一列不存在」**
   (2026-11-20 踩过:看扫描结果里没有某列,就以为卡上没有这一列)。
"""
import argparse, datetime, importlib.util, itertools, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def load_sections():
    spec = importlib.util.spec_from_file_location("rd", os.path.join(REPO, "render_dashboard.py"))
    rd = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(rd)
    except SystemExit:
        pass
    return rd.SECTIONS


def num(v):
    """Metabase 把 ≥1000 的数返回成带千分位的字符串,先去逗号再转。"""
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def pdate(v):
    if not isinstance(v, str):
        return None
    for f in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(v.strip(), f).date()
        except Exception:
            pass
    return None


def iter_cards(sections, metrics, section_filter):
    for sec, cards in sections:
        if section_filter and section_filter not in sec:
            continue
        for c in cards:
            rows = metrics.get(c[0]) or []
            if not rows:
                continue
            cfg = c[3] if len(c) > 3 else {}
            cols = [x[0] for x in cfg.get("cols", [])] or list(rows[0])
            yield sec, c[0], c[1].split(" · ")[0], cols, rows


# ── ① 死列:全为 0 / 全为空 ────────────────────────────────────────────
def scan_dead(sections, metrics, sf):
    print("\n══ ① 死列扫描(全 0 / 全空)══")
    print("🛑 全 0 不等于该删。先问:这一列是在量业务,还是在守异常?守异常的留着。\n")
    for sec, key, title, cols, rows in iter_cards(sections, metrics, sf):
        hits = []
        for col in cols:
            if col not in rows[0]:
                continue
            vals = [num(r.get(col)) for r in rows]
            got = [v for v in vals if v is not None]
            if not got:
                hits.append((col, "全为空"))
            elif all(v == 0 for v in got):
                hits.append((col, "全为 0"))
        if hits:
            print(f"  {title} [{key}]  {len(rows)} 行")
            for col, why in hits:
                print(f"      {col:<36} {why}")


# ── ②′ 列级停更:卡还在更新,某列从某天起恒为 0 ──────────────────────────
def scan_stale(sections, metrics, sf, today):
    print("\n══ ②′ 列级停更扫描 ══")
    print("🛑 这一道产出最大,卡级停更看不见它。")
    print("🔴 未成熟数据会混进来(留存 D7 近 7 天 0 是队列没满,不是停更),先看口径要几天成熟。\n")
    for sec, key, title, cols, rows in iter_cards(sections, metrics, sf):
        dcol = next((k for k in rows[0] if k == "date" or k.endswith("_date") or k == "d"), None)
        if not dcol:
            continue
        dates = [pdate(r.get(dcol)) for r in rows]
        live_dates = [d for d in dates if d]
        if not live_dates:
            continue
        span = max(live_dates)
        if (today - span).days > 4:      # 整卡就停了,卡级筛子已经报过
            continue
        hits = []
        for col in cols:
            if col == dcol or col not in rows[0]:
                continue
            per = {}
            for r, d in zip(rows, dates):
                if d is None:
                    continue
                v = num(r.get(col))
                if v is not None:
                    per[d] = per.get(d, 0) + abs(v)
            if len(per) < 8:
                continue
            live = [d for d, v in per.items() if v > 0]
            if not live:
                continue                 # 全 0 列,第 ① 道已经报过
            last = max(live)
            after = [d for d in per if d > last]
            if (today - last).days >= 6 and (span - last).days >= 6 and len(after) >= 5:
                hits.append((col, last, len(after)))
        if hits:
            print(f"  {title} [{key}]  数据到 {span}")
            for col, last, n in hits:
                print(f"      {col:<36} 最后非零 {last}  之后 {n} 天全 0")


# ── ④ 不变式:T = a+b(+c+d) 与 P = 100*a/b,多数行成立、少数行不成立 ──────
def scan_invariant(sections, metrics, sf):
    print("\n══ ④ 不变式自动探测 ══")
    print("🛑 信噪比不高:小数字之间「三个数互为和」的巧合会大量报出来。")
    print("   它的用处是把人工要看的范围从几百列缩到十几处,不是直接给答案。\n")
    for sec, key, title, cols, rows in iter_cards(sections, metrics, sf):
        data = {}
        for n_ in cols:
            if n_ not in rows[0]:
                continue
            col = [num(r.get(n_)) for r in rows]
            if sum(1 for v in col if v is not None) >= max(3, len(rows) * 0.3):
                data[n_] = col
        if len(data) < 3:
            continue
        cnt = [n_ for n_ in data
               if all(v is None or (v == int(v) and v >= 0) for v in data[n_])]
        out = []
        for t in cnt:
            others = [n_ for n_ in cnt if n_ != t][:12]
            found = []
            for k in (2, 3, 4):
                for combo in itertools.combinations(others, k):
                    ok = bad = 0
                    for i in range(len(rows)):
                        tv, parts = data[t][i], [data[c][i] for c in combo]
                        if tv is None or any(p is None for p in parts):
                            continue
                        if abs(sum(parts) - tv) < 0.5:
                            ok += 1
                        else:
                            bad += 1
                    if ok + bad >= 5 and ok >= (ok + bad) * 0.8 and bad > 0 and ok >= 5:
                        found.append((bad, ok + bad, t, combo))
                if found:
                    break                # 优先最短的组合
            for bad, tot, t_, combo in sorted(found)[:2]:
                out.append((bad, f"[SUM] {t_} ≠ {' + '.join(combo)} 在 {bad}/{tot} 行"))
        for p in [n_ for n_ in data if n_ not in cnt]:
            for a, b in itertools.permutations(cnt, 2):
                ok = bad = 0
                for i in range(len(rows)):
                    pv, av, bv = data[p][i], data[a][i], data[b][i]
                    if pv is None or av is None or not bv:
                        continue
                    if abs(100.0 * av / bv - pv) < 0.15:
                        ok += 1
                    else:
                        bad += 1
                if ok + bad >= 5 and ok >= (ok + bad) * 0.8 and bad > 0 and ok >= 5:
                    out.append((bad, f"[PCT] {p} ≠ 100*{a}/{b} 在 {bad}/{ok + bad} 行"))
                    break
        if out:
            print(f"  {title} [{key}]  {len(rows)} 行")
            seen = set()
            for bad, msg in sorted(out, key=lambda x: -x[0])[:6]:
                if msg not in seen:
                    seen.add(msg)
                    print(f"      {msg}")


def main():
    ap = argparse.ArgumentParser(description="看板列核对的三种自动扫描(只读)")
    ap.add_argument("--raw", default=os.path.join(REPO, "raw_metrics.json"))
    ap.add_argument("--dead", action="store_true", help="① 死列")
    ap.add_argument("--stale", action="store_true", help="②′ 列级停更")
    ap.add_argument("--invariant", action="store_true", help="④ 不变式")
    ap.add_argument("--all", action="store_true", help="三种全跑")
    ap.add_argument("--section", help="只看板块名里含这几个字的,如 增长")
    a = ap.parse_args()
    if not (a.dead or a.stale or a.invariant):
        a.all = True

    with open(a.raw, encoding="utf-8") as f:
        raw = json.load(f)
    metrics = raw.get("metrics", {})
    run_date = (raw.get("_meta") or {}).get("run_date")
    today = pdate(run_date) or datetime.date.today()
    print(f"数据:{a.raw}  抓数日 {run_date}  {len(metrics)} 张卡")

    sections = load_sections()
    if a.all or a.dead:
        scan_dead(sections, metrics, a.section)
    if a.all or a.stale:
        scan_stale(sections, metrics, a.section, today)
    if a.all or a.invariant:
        scan_invariant(sections, metrics, a.section)


if __name__ == "__main__":
    main()
