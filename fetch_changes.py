#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Lark 变更登记表拉 SoulMap 的产品变更 → changes.json

2026-11-19 新建。此前 CUTOVERS 和 CHANGELOG 写死在 render_dashboard.py 里,
加一个切点要写四个地方(台账 + CUTOVERS + CHANGELOG + i18n 的英文表),漏一处就对不上。
现在一处维护:在 Lark 表加一行,管线自己拉。

表:「change log soulmap+invader+city」,三个项目共用,按「项目 = SoulMap」筛。
凭据读 ~/.lark_env,不要打印、不要写进文件。

用法:
    source ~/.lark_env
    python3 fetch_changes.py                 # → changes.json
    python3 fetch_changes.py --days 60

🛑 **拉不到时不要让整轮渲染失败。** 这是外部依赖,Lark 挂了、权限被改回只读、网络不通
   都可能发生。脚本在拉失败时保留上一次的 changes.json 并以退出码 0 结束 ——
   渲染照常用旧数据,总比整个看板发不出去强。
"""
from __future__ import annotations
import argparse, datetime, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "changes.json"
APP_TOKEN = "QBAJbm4OIaDL8asjmZqjXMRWpVm"
TABLE_ID = "tblCTnXxwQXeNztM"          # 「数据表」:三个项目的产品变更
HISTORY_TABLE_ID = "tbl9hlxK0yTwurec"  # 「soulmap详细记录」:2026-11-10 之前的读数切点
CN = datetime.timezone(datetime.timedelta(hours=8))


def cell(v):
    if isinstance(v, list) and v:
        return v[0].get("text", "") if isinstance(v[0], dict) else str(v[0])
    if isinstance(v, dict):
        return v.get("text", "")
    return v if isinstance(v, str) else ("" if v is None else str(v))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    out = Path(a.out)

    try:
        # 🔴 2026-11-25 修:原来只找 ~/.claude/skills/lark(我本机的 skill 目录),
        #    **主机上没有这个目录**,于是从 11-19 起每轮都 ModuleNotFoundError,
        #    被下面的兜底吞掉 ——「保留上一次的 changes.json,渲染照常」——
        #    页面照常出、不报错,但变更列表整整冻了六天没人发现。
        #    改成优先用仓库自带的 lib/lark.py(随 git pull 到主机),本机 skill 作为回退。
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        sys.path.append(str(Path.home() / ".claude/skills/lark"))
        import lark
        tok = lark.token()
        rows = lark.paged("POST",
                          f"/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/search",
                          tok, body={})
    except Exception as e:
        # 🛑 这里绝对不能抛出去 —— 看板的渲染不该因为 Lark 不可用而中断
        print(f"⚠️ 拉 Lark 失败({type(e).__name__}: {str(e)[:80]})")
        if out.exists():
            print(f"   保留上一次的 {out.name}(里面有 "
                  f"{len(json.loads(out.read_text()).get('items', []))} 条),渲染照常")
        else:
            out.write_text(json.dumps({"items": [], "stale": True}, ensure_ascii=False))
            print("   没有上一次的文件,写出空清单;页头的改动日志会是空的")
        return 0

    # 历史切点(11-10 之前)在另一张表里,拉不到就当空 —— 不影响主流程
    history = {}
    try:
        for r in lark.paged("POST",
                            f"/bitable/v1/apps/{APP_TOKEN}/tables/{HISTORY_TABLE_ID}/records/search",
                            tok, body={}):
            f = r.get("fields", {})
            raw = f.get("日期")
            if not isinstance(raw, (int, float)):
                continue
            zh = cell(f.get("切点说明"))
            if zh:
                history[datetime.datetime.fromtimestamp(raw / 1000, CN).strftime("%Y-%m-%d")] = {
                    "what": zh, "what_en": cell(f.get("切点说明(EN)"))}
    except Exception as e:
        print(f"⚠️ 历史切点表拉失败({type(e).__name__}),这一段按空处理")

    cutoff = datetime.datetime.now(CN) - datetime.timedelta(days=a.days)
    items = []
    for r in rows:
        f = r.get("fields", {})
        if cell(f.get("项目")) != "SoulMap":
            continue
        raw = f.get("生效时间")
        if isinstance(raw, (int, float)):
            at = datetime.datetime.fromtimestamp(raw / 1000, CN)
        else:
            try:
                at = datetime.datetime.strptime(cell(raw)[:16], "%Y-%m-%d %H:%M").replace(tzinfo=CN)
            except Exception:
                continue
        if at < cutoff:
            continue
        items.append({
            "at": at.strftime("%Y-%m-%d %H:%M"),
            "date": at.strftime("%Y-%m-%d"),
            "mmdd_hhmm": at.strftime("%m-%d %H:%M") if at.strftime("%H:%M") != "00:00"
                         else at.strftime("%m-%d"),
            "what": cell(f.get("事项")),
            "what_en": cell(f.get("事项(EN)")),
            "note": cell(f.get("备注")),
            "note_en": cell(f.get("备注(EN)")),
            "type": cell(f.get("类型")),
            "is_cutover": bool(f.get("读数切点")),
            "on_board": bool(f.get("上看板")),
        })
    items.sort(key=lambda x: x["at"], reverse=True)
    out.write_text(json.dumps({"items": items, "history": history, "stale": False,
                               "fetched_at": datetime.datetime.now(CN).strftime("%Y-%m-%d %H:%M")},
                              ensure_ascii=False, indent=1))
    cut = sum(1 for i in items if i["is_cutover"])
    print(f"✅ 拉到 SoulMap 变更 {len(items)} 条(近 {a.days} 天),其中读数切点 {cut} 条;"
          f"另有历史切点 {len(history)} 条 → {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
