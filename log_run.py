#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一轮抓数的结果追加到 logs/runs.jsonl —— 一行一轮,随仓库提交。

2026-11-19 新建。此前只有 GitHub Actions 的日志,过期就没了,翻不到更早的。
11-19 那次连跑三轮把 Metabase 压垮(286 秒 4 张失败 → 731 秒 12 张 → 1,475 秒 18 张),
这个趋势是人工从三次输出里拼出来的,没有留档 —— 有了它才能回答
「这张卡是从哪天开始变慢的」「失败的是不是固定那几张」。

用法:
    python3 log_run.py                      # 读 raw_metrics.json → 追加一行
    python3 log_run.py --show 7             # 看最近 7 轮
    python3 log_run.py --slow 10            # 看最慢的 10 张卡(按最近一轮)
    python3 log_run.py --trend "卡名"        # 看某张卡的耗时变化

🛑 一天可能跑好几轮(重跑、手动补)。**不按日期去重** —— 每一轮都是一条独立记录,
   重跑本身就是要观察的现象(第二轮往往比第一轮慢,那是 Metabase 被压住了)。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw_metrics.json"
LOG = HERE / "logs" / "runs.jsonl"
SGT = timezone(timedelta(hours=8))


def load_runs():
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # 半行写坏了不该让整个命令崩掉
    return out


def append(raw_path: Path) -> int:
    try:
        meta = json.loads(raw_path.read_text(encoding="utf-8")).get("_meta", {})
    except Exception as e:
        print(f"⚠️ 读不了 {raw_path.name}({type(e).__name__}),这一轮不记录")
        return 0              # 🛑 记日志失败不该让整条流水线挂掉
    if not meta:
        print("⚠️ 没有 _meta,这一轮不记录")
        return 0
    failed = meta.get("failed") or []
    # 🔴 2026-11-20 新增 runner。主机(launchd,一天四次)和 GitHub Actions(22:20 补位)
    #    都会往这个文件追加,不标来源的话排查时只能靠提交时间倒推,很别扭。
    #    判据:Actions 的 runner 上 GITHUB_ACTIONS=true,这是官方保证一直有的环境变量。
    runner = "actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "host"
    row = {
        "at": datetime.now(SGT).strftime("%Y-%m-%d %H:%M"),
        "runner": runner,
        "run_date": meta.get("run_date"),
        "n_asked": meta.get("n_asked"),
        "n_cards": meta.get("n_cards"),
        "n_failed": len(failed),
        "seconds": meta.get("seconds"),
        "round_seconds": meta.get("round_seconds") or [],
        "failed": failed,
        "timings": meta.get("timings") or {},
        "rounds_taken": meta.get("rounds_taken") or {},
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    where = LOG.relative_to(HERE) if LOG.is_relative_to(HERE) else LOG
    print(f"✅ 记了一轮:{row['at']} [{runner}] · 抓到 {row['n_cards']}/{row['n_asked'] or '?'} 卡"
          f" · 缺 {row['n_failed']} · {row['seconds'] or '?'}s → {where}")
    return 0


def show(n: int) -> int:
    runs = load_runs()[-n:]
    if not runs:
        print("还没有记录")
        return 0
    print(f"{'时刻':<17}{'抓到':>8}{'缺':>5}{'总耗时':>9}  各轮耗时")
    for r in runs:
        got = f"{r['n_cards']}/{r['n_asked']}" if r.get("n_asked") else str(r["n_cards"])
        rs = " · ".join(f"{x:.0f}s" for x in r.get("round_seconds") or [])
        secs = f"{r['seconds']:.0f}s" if r.get("seconds") else "?"
        print(f"{r['at']:<17}{got:>8}{r['n_failed']:>5}{secs:>9}  {rs}")
    return 0


def slow(n: int) -> int:
    runs = load_runs()
    if not runs:
        print("还没有记录")
        return 0
    last = runs[-1]
    timings = last.get("timings") or {}
    if not timings:
        print("最近一轮没有耗时数据(抓数脚本是 2026-11-19 之后的版本才记)")
        return 0
    print(f"最近一轮({last['at']})最慢的 {n} 张:")
    for name, sec in sorted(timings.items(), key=lambda x: -x[1])[:n]:
        mark = "✗ 没抓到" if name in (last.get("failed") or []) else \
               f"第 {last.get('rounds_taken', {}).get(name, '?')} 轮抓到"
        print(f"  {sec:>7.1f}s  {name}  —— {mark}")
    return 0


def trend(name: str) -> int:
    runs = load_runs()
    hits = [(r["at"], (r.get("timings") or {}).get(name)) for r in runs]
    hits = [(at, sec) for at, sec in hits if sec is not None]
    if not hits:
        print(f"没有「{name}」的记录。卡名要和 Metabase 上的一字不差,"
              f"用 --slow 看看最近一轮都有哪些卡。")
        return 1
    print(f"「{name}」的耗时:")
    for at, sec in hits:
        bar = "█" * min(40, int(sec / 2))
        print(f"  {at}  {sec:>7.1f}s  {bar}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--show", type=int, metavar="N", help="看最近 N 轮")
    ap.add_argument("--slow", type=int, metavar="N", help="看最近一轮最慢的 N 张卡")
    ap.add_argument("--trend", metavar="卡名", help="看某张卡的耗时变化")
    a = ap.parse_args()
    if a.show:
        return show(a.show)
    if a.slow:
        return slow(a.slow)
    if a.trend:
        return trend(a.trend)
    return append(Path(a.raw))


if __name__ == "__main__":
    sys.exit(main())
