#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SoulMap 看板 · 从 Metabase 抓卡片结果 → raw_metrics.json

参考 kix daily-report/src/metabase_client.py 的三步:
  ① login          POST /api/session            拿 session token
  ② list cards     GET  /api/dashboard/{id}     取每张卡 card_id + name
  ③ run card       POST /api/card/{id}/query/json  让 Metabase 跑 SQL、返回 JSON 行

产物:{metric_id: [row, ...]},每张卡一个 key(metric_id = 卡名转 ASCII)。
用法:
  python3 fetch_metabase.py                 # 抓 dashboard 18 全部卡 → raw_metrics.json
  python3 fetch_metabase.py --limit 3       # 只抓前 3 张(冒烟测试)
  python3 fetch_metabase.py --dashboard-id 18 --out raw_metrics.json

⚠️ 凭据默认读环境变量,缺省回退到下面常量;上线时建议只用环境变量 / secrets,别把密码留在库里。
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error as E
import urllib.request as U
from datetime import date
from pathlib import Path

BASE_URL = os.environ.get("METABASE_URL", "https://metabase.stylepedia.co")
USERNAME = os.environ.get("METABASE_USER", "")      # 本地跑:export METABASE_USER=...
PASSWORD = os.environ.get("METABASE_PASSWORD", "")  # 线上:放 GitHub Actions secrets(勿写进代码)
DASHBOARD_ID = int(os.environ.get("SOULMAP_DASHBOARD_ID", "18"))

HERE = Path(__file__).resolve().parent


def _req(path, method="GET", data=None, tok=None, timeout=180):
    hdr = {"Content-Type": "application/json"}
    if tok:
        hdr["X-Metabase-Session"] = tok
    req = U.Request(BASE_URL + path, method=method, headers=hdr,
                    data=json.dumps(data).encode() if data is not None else None)
    with U.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def login() -> str:
    if not USERNAME or not PASSWORD:
        raise SystemExit("缺少 Metabase 凭据:请设 METABASE_USER / METABASE_PASSWORD 环境变量(线上放 secrets)")
    tok = _req("/api/session", "POST",
               {"username": USERNAME, "password": PASSWORD}, timeout=30)["id"]
    print(f"✅ login OK ({tok[:8]}…)")
    return tok


def get_dashboard_cards(tok: str, dashboard_id: int):
    d = _req(f"/api/dashboard/{dashboard_id}", tok=tok, timeout=30)
    name = str(d.get("name") or f"dashboard_{dashboard_id}")
    cards = []
    for dc in (d.get("dashcards") or []):
        cid = dc.get("card_id")
        cname = (dc.get("card") or {}).get("name")
        if cid and cname:
            cards.append({"card_id": cid, "card_name": cname})
    print(f"✅ dashboard {dashboard_id} ({name}) 含 {len(cards)} 卡")
    return name, cards


def safe_metric_id(name: str) -> str:
    return (str(name).strip().lower()
            .replace(" ", "_").replace("-", "_").replace("/", "_"))


def run_card_with_retry(tok: str, card_id: int, timeout=180, max_retries=4, backoff=1.6):
    """POST /api/card/{id}/query/json,带指数退避重试(治连接抖动/5xx)。"""
    path = f"/api/card/{card_id}/query/json"
    for attempt in range(max_retries + 1):
        try:
            return _req(path, "POST", {}, tok=tok, timeout=timeout)
        except E.HTTPError as ex:
            if 500 <= ex.code < 600 and attempt < max_retries:
                s = backoff ** attempt
                print(f"   ⏳ retry {attempt+1}/{max_retries} (server {ex.code}) sleep={s:.1f}s")
                time.sleep(s); continue
            print(f"   ❌ HTTP {ex.code} card={card_id}: {ex.read().decode('utf-8','replace')[:200]}")
            return None
        except Exception as ex:
            if attempt < max_retries:
                s = backoff ** attempt
                print(f"   ⏳ retry {attempt+1}/{max_retries} ({type(ex).__name__}) sleep={s:.1f}s")
                time.sleep(s); continue
            print(f"   ❌ {type(ex).__name__} card={card_id}: {ex}")
            return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard-id", type=int, default=DASHBOARD_ID)
    ap.add_argument("--out", default=str(HERE / "raw_metrics.json"))
    ap.add_argument("--run-date", default=date.today().isoformat())
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 张卡(冒烟测试)")
    args = ap.parse_args()

    tok = login()
    _, cards = get_dashboard_cards(tok, args.dashboard_id)
    if args.limit:
        cards = cards[:args.limit]
        print(f"⚠️ --limit {args.limit}:只抓前 {len(cards)} 张")

    metrics, failed = {}, []
    for i, c in enumerate(cards, 1):
        cid, cname = c["card_id"], c["card_name"]
        mid = safe_metric_id(cname)
        t0 = time.time()
        rows = run_card_with_retry(tok, cid)
        if rows is None:
            failed.append(cname); continue
        metrics[mid] = rows
        keys = list(rows[0].keys()) if rows else []
        print(f"  [{i}/{len(cards)}] {cname} -> {mid}  {len(rows)}行 {time.time()-t0:.1f}s  {keys}")

    out = {
        "_meta": {"run_date": args.run_date, "dashboard_id": args.dashboard_id,
                  "source": BASE_URL, "n_cards": len(metrics), "failed": failed},
        "metrics": metrics,
    }
    outp = Path(args.out)
    outp.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n✅ 写出 {outp}  ({len(metrics)} 卡" + (f", {len(failed)} 失败: {failed}" if failed else "") + ")")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
