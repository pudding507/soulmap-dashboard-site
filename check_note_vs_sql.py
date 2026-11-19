#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看板体检:note 说的口径,SQL 真的是那么算的吗

2026-11-19 新建。起因:「发现页搜索使用与质量」的 note 写着「设备级,埋点次日入库,
最后一两天必然偏低」,而 SQL 查的是服务端表的 user_id —— 账号级、实时,两处都说反了。
这种错比没写更糟:有人会因为「最后一两天必然偏低」而忽略真实的下跌。

它只查**能机器验证的断言**,查不出口径对不对,只查 note 和 SQL 一不一致。

用法:
    python3 check_note_vs_sql.py
    python3 check_note_vs_sql.py --verbose     # 连通过的也列出来

🛑 误报比漏报更费时间。下面每条规则都写了为什么要加那个限定 ——
   改规则前先看一眼,2026-11-19 第一版因为规则太粗,6 条里 5 条是误报。
"""
from __future__ import annotations
import argparse, importlib.util, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQLDIR = Path.home() / "DataGripProjects/soulmap_dashboard/Metabase"


def load_sections():
    spec = importlib.util.spec_from_file_location("rd", HERE / "render_dashboard.py")
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HERE))
    spec.loader.exec_module(m)
    return m.SECTIONS


def sql_body(zh: str) -> str:
    """读 SQL,去掉注释行 —— 注释里常写「以前是怎样」,拿它比对会误判。"""
    p = SQLDIR / f"{zh.replace(' / ', ' - ').replace('/', '-')}.sql"
    if not p.exists():
        return ""
    return "\n".join(l for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()
                     if not l.strip().startswith("--"))


def check(zh: str, note: str, sql: str) -> list[str]:
    out = []
    # ① 说不含 CityPLX,SQL 就该有 app_source 过滤
    if re.search(r"不含 ?CityPLX|排.{0,3}CityPLX|只统计 ?SoulMap", note) and "app_source" not in sql:
        out.append("说不含 CityPLX,但 SQL 没有 app_source 过滤")
    # ② 说剔沙盒,就该有 environment='PRODUCTION'
    if re.search(r"沙盒", note) and not re.search(r"environment\s*=\s*'PRODUCTION'", sql, re.I):
        out.append("说剔了沙盒,但 SQL 没有 environment='PRODUCTION'")
    # ③ 说只算用户发的,就该有 role='user'
    if re.search(r"只算用户|用户自己发|不含 ?AI ?回复", note) and not re.search(r"role\s*=\s*'user'", sql, re.I):
        out.append("说只算用户发的,但 SQL 没有 role='user'")
    # ④ 设备级 / 账号级
    #    🛑 只认「X级」这种断言句式。note 里常有「不要和设备级的卡比」这类**提醒**,
    #       那是在说别的卡,不是说自己 —— 第一版没区分,4 条全是误报。
    claim_dev = re.search(r"(?<!和)(?<!与)设备级", note) and not re.search(r"[和与、]设备级|设备级的", note)
    claim_acc = re.search(r"(?<!和)(?<!与)账号级", note) and not re.search(r"[和与、]账号级|账号级的", note)
    has_dev = re.search(r"user_pseudo_id|device_id", sql, re.I)
    has_acc = re.search(r"\buser_id\b|account_id", sql, re.I)
    if claim_dev and not has_dev:
        out.append("说设备级,但 SQL 里没有设备标识(user_pseudo_id / device_id)")
    if claim_acc and not has_acc:
        out.append("说账号级,但 SQL 里没有账号标识(user_id / account_id)")
    # ⑤ 说走埋点 T+1 / 说走服务端实时
    if re.search(r"埋点(次日|T\+1)|次日入库", note) and "firebase_event" not in sql:
        out.append("说走埋点次日入库,但 SQL 没查 firebase_event(服务端表是实时的)")
    if re.search(r"服务端表.{0,6}实时|实时,不走埋点", note) and "firebase_event" in sql:
        out.append("说走服务端实时,但 SQL 查了 firebase_event")
    # ⑥ 窗口天数
    #    🛑 只在「本卡窗口」的语境下比。note 里「占近 7 天注册的六成」这种是实测观察,
    #       不是窗口 —— 第一版没限定,2 条误报。
    said = {int(x) for x in re.findall(r"(?:窗口|近)\s*(\d+)\s*天(?!注册|的)", note)}
    real = {int(x) for x in re.findall(r"INTERVAL\s+(\d+)\s+DAY", sql, re.I)}
    if said and real and not (said & real):
        out.append(f"note 的窗口写近 {sorted(said)} 天,SQL 用的是 {sorted(real)} 天")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    total, nosql, bad = 0, [], []
    for _sec, cards in load_sections():
        for _key, title, _kind, p in cards:
            zh = title.split(" · ")[0]
            total += 1
            note = (p.get("note") or "").split(" ｜ ")[0] if isinstance(p, dict) else ""
            sql = sql_body(zh)
            if not sql:
                nosql.append(zh); continue
            for issue in check(zh, note, sql):
                bad.append((zh, issue))
            if a.verbose:
                print(f"   ok  {zh}")
    print(f"核了 {total} 张卡;找不到 SQL 归档的 {len(nosql)} 张"
          + (f":{nosql}" if nosql else ""))
    print(f"\n=== note 与 SQL 对不上:{len(bad)} 处 ===")
    for zh, why in bad:
        print(f"  {zh}\n      {why}")
    if not bad:
        print("  ✅ 没有发现不一致")
    print("\n🛑 它只查一致性,查不出口径本身对不对 —— note 和 SQL 一起错的,这个脚本发现不了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
