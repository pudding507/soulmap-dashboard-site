#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SoulMap 看板 · 从 Metabase 抓卡片结果 → raw_metrics.json

参考 kix daily-report/src/metabase_client.py 的三步:
  ① login          POST /api/session            拿 session token
  ② list cards     GET  /api/dashboard/{id}     取每张卡 card_id + name
  ③ run card       POST /api/card/{id}/query/json  让 Metabase 跑 SQL、返回 JSON 行

产物:{metric_id: [row, ...]},每张卡一个 key(metric_id = 卡名转 ASCII)。
用法:
  python3 fetch_metabase.py                 # 抓 dashboard 18+24 全部卡 → raw_metrics.json
  python3 fetch_metabase.py --limit 3       # 只抓前 3 张(冒烟测试)
  python3 fetch_metabase.py --dashboard-ids 18,24 --out raw_metrics.json

2026-10-19 改两处:
  ① 支持多看板。18 是 Report raw(基础监控),24 是 experiment(0.99/付费墙/额度墙/邀请/语音)。
     10-15 玩法改成 0.99 直购之后,新玩法的卡全在 24,只抓 18 的话看板上一张都看不到。
     两边有 15 张重叠卡(DAU/新用户/留存等),按 card_id 去重,只抓一次。
  ② 加 KEY_OVERRIDE。safe_metric_id 不转 ASCII(原 docstring 写了但没实现),
     24 的卡名带中文和 ·—,直接转出来是「现状_各国新用户与聊天深度_·_snapshot_—_...」,
     没法在 render 的 SECTIONS 里用。给这 22 张新卡显式指定英文 key。

⚠️ 凭据默认读环境变量,缺省回退到下面常量;上线时建议只用环境变量 / secrets,别把密码留在库里。
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error as E
import urllib.request as U
from datetime import date
from pathlib import Path

BASE_URL = os.environ.get("METABASE_URL", "https://metabase.stylepedia.co")
USERNAME = os.environ.get("METABASE_USER", "")      # 本地跑:export METABASE_USER=...
PASSWORD = os.environ.get("METABASE_PASSWORD", "")  # 线上:放 GitHub Actions secrets(勿写进代码)
# 18 = Report raw(基础监控) · 24 = experiment(0.99/付费墙/额度墙/邀请/语音,最新口径)
DASHBOARD_IDS = [int(x) for x in
                 os.environ.get("SOULMAP_DASHBOARD_IDS", "18,24").split(",") if x.strip()]

# 抓了也不渲染的卡 —— 2026-10-19 从 render 的 SECTIONS 里删掉了这三张,
# 但它们还挂在 Metabase 看板 18 上。不跳过的话每轮白抓三张(其中撞墙那张要扫 firebase_event)。
# 🛑 想重新显示,先在 render_dashboard.py 的 SECTIONS 里加回来,再从这里删掉 ——
#    只改一边的话会静默不显示。
SKIP_CARDS = {
    396: "Monetize_free quota wall daily —— 已被看板 24 的 424 替代(那张用真正的 chat_wall_blocked 事件)",
    398: "Monetize_trial cohort —— 10-15 起免费试用被 0.99 替代,分母持续萎缩",
    353: "Chat_voice text ratio —— 已被看板 24 的 418 替代(那张分国家分天)",
    341: "Activation_first msg latency —— 依赖的两个埋点从 3.1.1 起基本停发,近 30 天只剩 20 条和 6 条",
}

# 看板 24 的卡名是中文,safe_metric_id 转出来没法用。这里显式给 key。
# 🛑 改 key 要同步改 render_dashboard.py 的 SECTIONS,否则那张卡会静默不显示。
KEY_OVERRIDE = {
    417: "snapshot_country_depth",      418: "snapshot_voice_text_share",
    420: "intro_by_client_version",     421: "intro_by_country",
    422: "intro_rollout_coverage",
    406: "paywall_trial_outcome_by_arm", 409: "paywall_tpc_by_country",
    410: "paywall_tpc_by_creative",     404: "paywall_arm_funnel",
    407: "paywall_writeback_by_version", 403: "paywall_free_quota_line",
    402: "paywall_arm_split_hourly",    408: "paywall_retention_by_arm",
    424: "quota_wall_blocked_next",
    411: "invite_inviter_side",         412: "invite_invitee_side",
    413: "invite_reward_grants",        419: "invite_redeem_by_source",
    423: "invite_bonus_30msg",
    414: "voice_arm_comparison",        415: "voice_latency_miss",
    416: "voice_playback_reasons",
    425: "paywall_triggers_side_by_side",   # 2026-10-20 新建
    426: "risk_ref_photo_uploads",          # 2026-10-20 新建
    427: "attribution_adjust_recon",        # 2026-10-20 新建
    428: "sp_memories_usage",               # 2026-10-20 新建
}

HERE = Path(__file__).resolve().parent


def _req(path, method="GET", data=None, tok=None, timeout=180):
    hdr = {"Content-Type": "application/json"}
    if tok:
        hdr["X-Metabase-Session"] = tok
    req = U.Request(BASE_URL + path, method=method, headers=hdr,
                    data=json.dumps(data).encode() if data is not None else None)
    with U.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _req_retry(path, method="GET", data=None, tok=None,
               timeout=90, max_retries=3, backoff=2.0, label=""):
    """给启动阶段(登录/取看板)用的带重试请求。

    2026-09-16 新增。原来这两步是 timeout=30 且无重试,Metabase 一忙就整条挂掉 ——
    实测一次 `/api/session` 读超时就让整个 run 死在第一步,卡片那边的 4 次重试根本没机会跑。
    `/api/health` 不碰应用库所以秒回,但登录要查用户表 + bcrypt + 写 session,
    Metabase 被并发查询压住时这一步会明显变慢。放宽到 90 秒并退避重试 3 次。

    4xx 直接抛(凭据错/看板不存在,重试无意义),5xx 与超时才退避。
    """
    for attempt in range(max_retries + 1):
        try:
            return _req(path, method, data, tok, timeout=timeout)
        except E.HTTPError as ex:
            if 500 <= ex.code < 600 and attempt < max_retries:
                s = backoff ** attempt
                print(f"   ⏳ {label} retry {attempt+1}/{max_retries} (server {ex.code}) sleep={s:.1f}s")
                time.sleep(s); continue
            raise
        except Exception as ex:
            if attempt < max_retries:
                s = backoff ** attempt
                print(f"   ⏳ {label} retry {attempt+1}/{max_retries} ({type(ex).__name__}) sleep={s:.1f}s")
                time.sleep(s); continue
            raise


def login() -> str:
    if not USERNAME or not PASSWORD:
        raise SystemExit("缺少 Metabase 凭据:请设 METABASE_USER / METABASE_PASSWORD 环境变量(线上放 secrets)")
    tok = _req_retry("/api/session", "POST",
                     {"username": USERNAME, "password": PASSWORD},
                     timeout=90, label="login")["id"]
    print(f"✅ login OK ({tok[:8]}…)")
    return tok


def get_dashboard_cards(tok: str, dashboard_id: int):
    d = _req_retry(f"/api/dashboard/{dashboard_id}", tok=tok,
                   timeout=90, label="dashboard")
    name = str(d.get("name") or f"dashboard_{dashboard_id}")
    cards = []
    for dc in (d.get("dashcards") or []):
        cid = dc.get("card_id")
        cname = (dc.get("card") or {}).get("name")
        if cid and cname:
            cards.append({"card_id": cid, "card_name": cname})
    print(f"✅ dashboard {dashboard_id} ({name}) 含 {len(cards)} 卡")
    return name, cards


def safe_metric_id(name: str, card_id: int | None = None) -> str:
    """卡名 → metric_id。KEY_OVERRIDE 里有就用它(24 的中文卡名靠这个)。"""
    if card_id is not None and card_id in KEY_OVERRIDE:
        return KEY_OVERRIDE[card_id]
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
    ap.add_argument("--dashboard-ids", default=",".join(map(str, DASHBOARD_IDS)),
                    help="逗号分隔,如 18,24。重叠的卡按 card_id 去重")
    ap.add_argument("--out", default=str(HERE / "raw_metrics.json"))
    ap.add_argument("--run-date", default=date.today().isoformat())
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 张卡(冒烟测试)")
    ap.add_argument("--rounds", type=int, default=3, help="多轮重试,每轮把没抓到的再试一遍")
    ap.add_argument("--gap", type=int, default=15, help="轮间隔秒数")
    ap.add_argument("--workers", type=int, default=4, help="并发抓取的线程数(卡与卡互相独立)")
    args = ap.parse_args()

    tok = login()
    dash_ids = [int(x) for x in str(args.dashboard_ids).split(",") if x.strip()]
    cards, seen = [], set()
    for did in dash_ids:
        _, cs = get_dashboard_cards(tok, did)
        dup = 0
        for c in cs:
            if c["card_id"] in SKIP_CARDS:
                continue
            if c["card_id"] in seen:      # 两个看板共用的卡只抓一次
                dup += 1; continue
            seen.add(c["card_id"]); cards.append(c)
        if dup:
            print(f"   ↳ 其中 {dup} 张与前面的看板重复,已去重")
    print(f"📋 合计待抓 {len(cards)} 张卡(看板 {dash_ids},已跳过 {len(SKIP_CARDS)} 张不渲染的)")
    if args.limit:
        cards = cards[:args.limit]
        print(f"⚠️ --limit {args.limit}:只抓前 {len(cards)} 张")

    # 多轮制:每轮把还没抓到的卡再试一遍,轮间隔一会儿,去碰 RDS 空档(仿 kix"多试几次就成")
    # ⚡ 轮内并发:卡与卡互相独立,串行时墙上时间 = 所有卡耗时之和,其中几张必超时的卡
    #    每轮都要各自空等 60 秒(nginx 网关线)。改成线程池后 ≈ 最慢那张的耗时。
    metrics = {}
    lock = threading.Lock()
    todo = [(c["card_id"], c["card_name"], safe_metric_id(c["card_name"], c["card_id"]))
            for c in cards]

    def fetch_one(item):
        cid, cname, mid = item
        t0 = time.time()
        rows = run_card_with_retry(tok, cid, max_retries=0)   # 每轮 1 次,靠多轮磨
        if rows is None:
            print(f"  ✗ {cname}(留待下轮) {time.time()-t0:.0f}s", flush=True)
            return item
        with lock:
            metrics[mid] = rows
        print(f"  ✓ {cname} -> {mid}  {len(rows)}行 {time.time()-t0:.0f}s", flush=True)
        return None

    for rd in range(1, args.rounds + 1):
        # 并发递减:第1轮拼吞吐(4),后面几轮只剩硬骨头,降并发让每张卡拿到完整带宽。
        # 实测第3轮 7 张卡开 4 并发时互相拖累、6 张全超时;单跑 41–46 秒的卡本来能过。
        workers = max(1, min(args.workers // (2 ** (rd - 1)), len(todo)))
        print(f"\n===== 第 {rd}/{args.rounds} 轮 · 待抓 {len(todo)} 卡 · 并发 {workers} =====", flush=True)
        t_round = time.time()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            still = [x for x in pool.map(fetch_one, todo) if x is not None]
        print(f"  本轮用时 {time.time()-t_round:.0f}s", flush=True)
        todo = still
        if not todo:
            print("全部抓到 ✅"); break
        if rd < args.rounds:
            print(f"  本轮还差 {len(todo)} 卡,歇 {args.gap}s 再来…"); time.sleep(args.gap)
    failed = [cname for _, cname, _ in todo]

    out = {
        "_meta": {"run_date": args.run_date, "dashboard_ids": dash_ids,
                  "source": BASE_URL, "n_cards": len(metrics), "failed": failed},
        "metrics": metrics,
    }
    outp = Path(args.out)
    outp.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n✅ 写出 {outp}  ({len(metrics)} 卡" + (f", {len(failed)} 失败: {failed}" if failed else "") + ")")
    # 部分卡失败也算成功:有数据就渲染上线,别因为一两张 504 卡住整条流水线
    return 0 if metrics else 1


if __name__ == "__main__":
    raise SystemExit(main())
