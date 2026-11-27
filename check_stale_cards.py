#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看 logs/runs.jsonl,找出连续抓不到的卡,到阈值就推 Lark。

2026-11-27 新建。起因:实测发现 Metabase 前面的 **nginx 代理超时是 60 秒**,
超过就返回 504 —— `fetch_metabase.py` 里的 `timeout=90` 和三轮重试对它**完全无效**
(被掐断,不是慢)。卡一旦越过 60 秒就每轮都抓不到,而页面上只是「沿用旧值」,
**没有任何地方会报出来**。实测 11-25~11-27 十轮里:付费漏斗分国家 9 次没抓到、
新用户首日行为交叉 8 次、四种模式入口三层 8 次、装机日素材漏斗 6 次 —— 没人知道。

🛑 **无状态**:不写状态文件。主机(12:20/14:20/17:20/21:20)和 GitHub Actions(22:20)
   两边都会跑,靠文件同步状态必然打架。改成只在「连续失败数正好踩到 N、2N、3N…」
   那一轮推送,所以既不会每轮刷屏,也不需要记上次推过什么。

🛑 **这个脚本自己绝不能让流水线失败** —— 任何异常都只打印、返回 0。
   notify.py 同样保证(webhook 没配只打印)。

用法:
    python3 check_stale_cards.py            # 正常检查并在到阈值时推送
    python3 check_stale_cards.py --dry-run  # 只打印,不推送
    python3 check_stale_cards.py --every 3  # 改阈值(默认 3 轮)
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
RUNS = HERE / "logs" / "runs.jsonl"
DEFAULT_EVERY = 3          # 连续失败多少轮算一次「该说一声了」


def load_runs(path: pathlib.Path) -> list[dict]:
    """读 runs.jsonl。坏行跳过,不让整个脚本倒在一行上。"""
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def streaks(runs: list[dict]) -> tuple[dict[str, int], dict[str, str], str]:
    """倒着数每张卡连续失败了多少轮,以及它上一次成功是什么时候。

    只看最近一轮 timings 里出现过的卡 —— 卡会下线(86 → 81 张),
    早就不抓的卡不该再报。
    """
    if not runs:
        return {}, {}, ""
    last = runs[-1]
    known = set(last.get("timings") or {}) | set(last.get("failed") or [])
    streak: dict[str, int] = {}
    last_ok: dict[str, str] = {}
    done: set[str] = set()
    for run in reversed(runs):
        failed = set(run.get("failed") or [])
        asked = set(run.get("timings") or {}) | failed
        for card in known:
            if card in done or card not in asked:
                continue
            if card in failed:
                streak[card] = streak.get(card, 0) + 1
            else:
                last_ok[card] = run.get("at", "?")
                done.add(card)          # 往前再数就没意义了
    return streak, last_ok, last.get("at", "?")


def main() -> int:
    ap = argparse.ArgumentParser(description="连续抓不到的卡,到阈值推 Lark")
    ap.add_argument("--dry-run", action="store_true", help="只打印不推送")
    ap.add_argument("--every", type=int, default=DEFAULT_EVERY,
                    help=f"连续失败多少轮报一次(默认 {DEFAULT_EVERY})")
    ap.add_argument("--runs", default=str(RUNS))
    args = ap.parse_args()

    every = max(1, args.every)
    runs = load_runs(pathlib.Path(args.runs))
    if len(runs) < 2:
        print("[stale] 运行记录不足两轮,跳过")
        return 0

    streak, last_ok, at = streaks(runs)
    bad = {c: n for c, n in streak.items() if n >= every}
    if not bad:
        print(f"[stale] {at}:没有连续 {every} 轮抓不到的卡")
        return 0

    # 只在踩到 every 的整数倍那一轮说话,别每轮刷屏
    due = {c: n for c, n in bad.items() if n % every == 0}
    lines = []
    for card, n in sorted(bad.items(), key=lambda x: -x[1]):
        ok = last_ok.get(card)
        when = f"上次抓到 {ok}" if ok else "这段记录里一次都没抓到"
        lines.append(f"· {card} —— 连续 {n} 轮没抓到,{when}")
    body = "\n".join(lines)
    print(f"[stale] {at}:{len(bad)} 张卡连续 ≥{every} 轮抓不到\n{body}")

    if not due:
        print(f"[stale] 本轮不推送(等踩到 {every} 的整数倍那一轮再说)")
        return 0
    if args.dry_run:
        print("[stale] --dry-run,不推送")
        return 0

    try:
        sys.path.insert(0, str(HERE))
        import notify
        notify.send(
            f"看板有 {len(bad)} 张卡抓不到了",
            body + "\n\n页面上这些卡显示的是旧值,不会报错。"
                   "常见原因是查询超过 60 秒被网关掐断(504),重试无效。",
            project="SoulMap")
    except Exception as e:                      # 绝不让流水线倒在这里
        print(f"[stale] 推送失败(不影响发布): {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[stale] 自身出错(不影响发布): {type(e).__name__}: {e}")
        sys.exit(0)
