#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一个卡片 SQL 文件在生产库上跑一遍,看行数和头几行。

    source ~/.soulmap_env
    python3 tools/run_sql.py "../soulmap_dashboard/Metabase/每天新首付.sql"
    python3 tools/run_sql.py "….sql" --rows 10        # 多看几行
    python3 tools/run_sql.py "….sql" --explain        # 跑 EXPLAIN ANALYZE 而不是取数

用途:改完卡**推 Metabase 之前**自己验一次,别等下一轮刷新才发现错了。

🛑 **只读。** 不要用它跑任何写操作。
🛑 **连接排序规则对齐 Metabase**(utf8mb4_unicode_ci)—— 本地 pymysql 默认是
   0900_ai_ci,而 `CAST(x AS CHAR)` 跟连接走。不对齐的话本地验通了、
   线上照样报 Illegal mix of collations(2026-11-20 踩过)。
🛑 自动跳过文件开头的注释,从第一个 WITH / SELECT 开始取。
"""
from __future__ import annotations
import argparse
import os
import sys


def body_of(path: str) -> str:
    """跳过头部注释,取 SQL 主体。"""
    lines = open(path, encoding="utf-8").read().splitlines(True)
    for i, l in enumerate(lines):
        if l.startswith("WITH ") or l.startswith("SELECT "):
            return "".join(lines[i:])
    raise SystemExit(f"{path} 里找不到以 WITH / SELECT 开头的行")


def main() -> int:
    ap = argparse.ArgumentParser(description="在生产库上跑一个卡片 SQL(只读)")
    ap.add_argument("sql_file")
    ap.add_argument("--rows", type=int, default=3, help="打印前几行,默认 3")
    ap.add_argument("--explain", action="store_true", help="跑 EXPLAIN ANALYZE")
    ap.add_argument("--timeout", type=int, default=300, help="客户端读超时秒数")
    a = ap.parse_args()

    try:
        import pymysql
    except ImportError:
        raise SystemExit("没装 pymysql:pip3 install pymysql")
    for v in ("SOULMAP_DB_HOST", "SOULMAP_DB_USER", "SOULMAP_DB_PASS"):
        if not os.environ.get(v):
            raise SystemExit(f"缺 {v} —— 先 source ~/.soulmap_env")

    sql = body_of(a.sql_file)
    if a.explain:
        sql = "EXPLAIN ANALYZE\n" + sql

    conn = pymysql.connect(
        host=os.environ["SOULMAP_DB_HOST"], user=os.environ["SOULMAP_DB_USER"],
        password=os.environ["SOULMAP_DB_PASS"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=20, read_timeout=a.timeout)
    import time
    t0 = time.time()
    with conn.cursor() as cur:
        # 🛑 见模块注释:必须对齐 Metabase 的排序规则
        cur.execute("SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute("SET SESSION max_execution_time=%s", (a.timeout * 1000,))
        cur.execute(sql)
        rows = cur.fetchall()
    secs = time.time() - t0
    if a.explain:
        for r in rows:
            print(list(r.values())[0])
        return 0
    print(f"--- {len(rows)} 行 · {secs:.1f}s ---")
    for r in rows[: a.rows]:
        print(" | ".join(f"{k}={v}" for k, v in r.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
