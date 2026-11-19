#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地 SQL 推到 Metabase 卡片,或把线上 SQL 拉下来。

2026-11-19 新建。此前改完卡 SQL 只能人工复制粘贴到 Metabase,
本地 `soulmap_dashboard/Metabase/*.sql` 和线上会悄悄分叉 —— 没人知道线上跑的是哪一版。

用法(先 `source ~/.soulmap_env`):
    python3 push_card.py --pull                     # 把全部卡的线上 SQL 拉到本地目录
    python3 push_card.py --pull "有效 D1 分来源"      # 只拉一张
    python3 push_card.py --diff "有效 D1 分来源"      # 比线上和本地差在哪,不改任何东西
    python3 push_card.py --push "有效 D1 分来源"      # 本地 → 线上(会先存一份线上原样)

🛑 **推之前一定会先 --diff 给你看,并要求 --yes 才真的写。**
   这是对生产看板的写操作,线上那版一旦被覆盖就只能从备份找回来。
🛑 每次 push 都把线上原样存进 `backup/metabase_cards/<卡名>_<时刻>.sql`,
   随仓库提交。回滚就是把备份内容再 push 回去。
🛑 只动 `dataset_query.native.query` 这一个字段,卡片的名字、可视化设置、
   所在看板位置一概不碰 —— 那些在 Metabase 上改,不走这里。
"""
from __future__ import annotations
import argparse
import difflib
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fetch_metabase as fm    # noqa: E402  复用它的登录和请求封装

SQL_DIR = Path.home() / "DataGripProjects/soulmap_dashboard/Metabase"
BACKUP_DIR = HERE / "backup" / "metabase_cards"
SGT = timezone(timedelta(hours=8))


def all_cards(tok):
    """看板上的全部卡:卡名 → card_id。同名卡取第一张并提示。"""
    out, dup = {}, []
    for did in fm.DASHBOARD_IDS:
        _board, cards = fm.get_dashboard_cards(tok, did)   # 返回 (看板名, 卡列表)
        for c in cards:
            name = c["card_name"]
            if name in out:
                dup.append(name)
                continue
            out[name] = c["card_id"]
    if dup:
        print(f"⚠️ 看板上有同名卡,只取第一张:{sorted(set(dup))}")
    return out


def fetch_card(tok, card_id) -> dict:
    return fm._req_retry(f"/api/card/{card_id}", tok=tok, label="get card")


def sql_of(card: dict) -> str:
    q = (card.get("dataset_query") or {}).get("native") or {}
    if "query" not in q:
        raise SystemExit(f"卡「{card.get('name')}」不是原生 SQL 卡,这个脚本不处理")
    return q["query"]


def local_path(name: str) -> Path:
    # 卡名里的 / 不能做文件名,归档时一律换成 -
    return SQL_DIR / f"{name.replace('/', '-')}.sql"


def show_diff(name: str, online: str, local: str) -> bool:
    """返回 True 表示有差异。注释行也算差异 —— 本地的改动记录就在注释里。"""
    a, b = online.splitlines(), local.splitlines()
    if a == b:
        print(f"✅ 「{name}」线上和本地完全一致")
        return False
    diff = list(difflib.unified_diff(a, b, fromfile="线上", tofile="本地", lineterm="", n=2))
    print(f"📋 「{name}」有差异({len(a)} 行 → {len(b)} 行):")
    for ln in diff[:80]:
        print("   " + ln)
    if len(diff) > 80:
        print(f"   …… 还有 {len(diff) - 80} 行差异没显示")
    return True


def do_pull(tok, names):
    cards = all_cards(tok)
    targets = names or sorted(cards)
    for name in targets:
        if name not in cards:
            print(f"✗ 看板上没有「{name}」")
            continue
        sql = sql_of(fetch_card(tok, cards[name]))
        p = local_path(name)
        p.write_text(sql if sql.endswith("\n") else sql + "\n", encoding="utf-8")
        print(f"✅ 拉下「{name}」→ {p.name}({len(sql.splitlines())} 行)")
    return 0


def do_diff(tok, names):
    cards = all_cards(tok)
    changed = 0
    for name in (names or sorted(cards)):
        if name not in cards:
            print(f"✗ 看板上没有「{name}」")
            continue
        p = local_path(name)
        if not p.exists():
            print(f"✗ 本地没有 {p.name}")
            continue
        if show_diff(name, sql_of(fetch_card(tok, cards[name])), p.read_text(encoding="utf-8").rstrip("\n")):
            changed += 1
    print(f"\n{changed} 张有差异")
    return 0


def do_push(tok, names, yes: bool):
    cards = all_cards(tok)
    stamp = datetime.now(SGT).strftime("%Y%m%d-%H%M")
    for name in names:
        if name not in cards:
            print(f"✗ 看板上没有「{name}」")
            return 1
        card_id = cards[name]
        p = local_path(name)
        if not p.exists():
            print(f"✗ 本地没有 {p.name}")
            return 1
        card = fetch_card(tok, card_id)
        online, local = sql_of(card), p.read_text(encoding="utf-8").rstrip("\n")
        if not show_diff(name, online, local):
            continue
        if not yes:
            print(f"\n🛑 以上是将要写进 Metabase 卡 {card_id} 的改动。确认无误后加 --yes 再跑一次。")
            return 2
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        bak = BACKUP_DIR / f"{name.replace('/', '-')}_{stamp}.sql"
        bak.write_text(online + "\n", encoding="utf-8")
        print(f"   线上原样已备份 → {bak.relative_to(HERE)}")
        dq = card["dataset_query"]
        dq["native"]["query"] = local
        fm._req_retry(f"/api/card/{card_id}", "PUT", {"dataset_query": dq},
                      tok=tok, label="update card")
        back = sql_of(fetch_card(tok, card_id))
        if back.rstrip("\n") != local:
            print(f"❌ 写回后读出来的和本地对不上,请人工检查卡 {card_id}")
            return 1
        print(f"✅ 「{name}」已推到 Metabase 卡 {card_id},读回校验一致")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pull", action="store_true", help="线上 → 本地")
    g.add_argument("--diff", action="store_true", help="只比对,不改")
    g.add_argument("--push", action="store_true", help="本地 → 线上")
    ap.add_argument("names", nargs="*", help="卡名(和 Metabase 上一字不差);不给就是全部")
    ap.add_argument("--yes", action="store_true", help="push 时确认真的写入")
    a = ap.parse_args()
    if a.push and not a.names:
        print("🛑 push 必须点名要推哪张卡,不接受一次全推")
        return 1
    tok = fm.login()
    if a.pull:
        return do_pull(tok, a.names)
    if a.diff:
        return do_diff(tok, a.names)
    return do_push(tok, a.names, a.yes)


if __name__ == "__main__":
    sys.exit(main())
