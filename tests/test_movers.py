#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页头「今天变化最大的 5 个数」的五条口径 —— 喂假数据验,不连库。

2026-11-19 新建。口径写在 render_dashboard._movers() 的卡头注释里,这里逐条钉住:
  ① 只比已过完的整天(服务端表实时、埋点表 T+1,当天那条都不完整)
  ② 分子两天都要 ≥ 门槛(防小分母按百分比霸榜)
  ③ 均值卡 / 中位数卡不进榜(没有分子,门槛 ② 落不到实处)
  ④ 表格卡 / 漏斗卡不进榜(一行一个实体 / 一行一级,没有「今天这一个数」)
  ⑤ 一张卡只出一行

外加一条踩过的坑:有分母 ≠ 是百分比。「人均消息数」是 rate 卡但 fmt=d1,
按百分比显示会把 1.82 次/人 印成 181.7%。
"""
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import render_dashboard as rd      # noqa: E402

RUN_DATE = "2026-11-19"


@contextmanager
def sections(cards):
    """_movers 读的是模块级 SECTIONS,测试期间整个换掉。"""
    saved = rd.SECTIONS
    rd.SECTIONS = [("测试区 · Test", cards)]
    try:
        yield
    finally:
        rd.SECTIONS = saved


def days(*pairs, col="users"):
    return [{"date": d, col: v} for d, v in pairs]


class TestCompleteDaysOnly(unittest.TestCase):
    def test_today_is_excluded(self):
        """口径 ①:run_date 当天那条不参与,否则榜上天天是假跌。"""
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = days(("2026-11-17", 100), ("2026-11-18", 200), ("2026-11-19", 3))
        with sections([card]):
            got = rd._movers({"c": rows}, RUN_DATE)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["d0"], got[0]["d1"]), ("2026-11-17", "2026-11-18"))
        self.assertEqual((got[0]["v0"], got[0]["v1"]), (100, 200))

    def test_needs_two_complete_days(self):
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = days(("2026-11-18", 200), ("2026-11-19", 300))
        with sections([card]):
            self.assertEqual(rd._movers({"c": rows}, RUN_DATE), [])


class TestNumeratorThreshold(unittest.TestCase):
    def test_small_numerator_is_dropped(self):
        """口径 ②:分子没到门槛的不进榜 —— 2 → 4 的相对变化是 100%,但读不出。"""
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = days(("2026-11-17", 2), ("2026-11-18", 4))
        with sections([card]):
            self.assertEqual(rd._movers({"c": rows}, RUN_DATE), [])

    def test_both_days_must_pass(self):
        """一天够、另一天不够,也不进榜。"""
        below = rd.MOVERS_MIN_N - 1
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = days(("2026-11-17", below), ("2026-11-18", 500))
        with sections([card]):
            self.assertEqual(rd._movers({"c": rows}, RUN_DATE), [])

    def test_rate_card_checks_numerator_not_rate(self):
        """比率卡卡的是分子,不是比率本身。"""
        card = ("c", "卡 · Card", "rate", {"rate": ("paid", "total")})
        rows = [{"date": "2026-11-17", "paid": 5, "total": 1000},
                {"date": "2026-11-18", "paid": 9, "total": 1000}]
        with sections([card]):
            self.assertEqual(rd._movers({"c": rows}, RUN_DATE), [])


class TestExcludedKinds(unittest.TestCase):
    def test_table_and_funnel_never_rank(self):
        """口径 ④。"""
        rows = days(("2026-11-17", 100), ("2026-11-18", 200))
        for kind in ("table", "funnel"):
            with self.subTest(kind=kind), sections([("c", "卡 · Card", kind, {"val": "users"})]):
                self.assertEqual(rd._movers({"c": rows}, RUN_DATE), [])

    def test_avg_and_median_never_rank(self):
        """口径 ③。"""
        rows = days(("2026-11-17", 100), ("2026-11-18", 200))
        for agg in ("avg", "median"):
            with self.subTest(agg=agg), \
                 sections([("c", "卡 · Card", "line", {"val": "users", "agg": agg})]):
                self.assertEqual(rd._movers({"c": rows}, RUN_DATE), [])


class TestOneRowPerCard(unittest.TestCase):
    def test_multi_series_card_yields_one_row(self):
        """口径 ⑤:一张多序列的卡按天汇总成一行,否则它能占满五行。"""
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = [{"date": "2026-11-17", "arm": "a", "users": 60},
                {"date": "2026-11-17", "arm": "b", "users": 40},
                {"date": "2026-11-18", "arm": "a", "users": 120},
                {"date": "2026-11-18", "arm": "b", "users": 80}]
        with sections([card]):
            got = rd._movers({"c": rows}, RUN_DATE)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["v0"], got[0]["v1"]), (100, 200))


class TestUnit(unittest.TestCase):
    def test_rate_with_fmt_d1_is_not_a_percentage(self):
        """🛑 踩过的坑:「人均消息数」有分母但不是百分比,按 pct 显示会印成 181.7%。"""
        card = ("c", "人均消息数 · Messages per User", "rate",
                {"rate": ("msgs", "users"), "fmt": "d1"})
        rows = [{"date": "2026-11-17", "msgs": 1000, "users": 550},
                {"date": "2026-11-18", "msgs": 2000, "users": 550}]
        with sections([card]):
            got = rd._movers({"c": rows}, RUN_DATE)
        self.assertEqual(got[0]["unit"], "d1")
        self.assertEqual(rd._mvval(got[0]["v1"], got[0]["unit"]), "3.6")

    def test_rate_without_fmt_is_a_percentage(self):
        card = ("c", "付费率 · Paid Rate", "rate", {"rate": ("paid", "total")})
        rows = [{"date": "2026-11-17", "paid": 100, "total": 1000},
                {"date": "2026-11-18", "paid": 200, "total": 1000}]
        with sections([card]):
            got = rd._movers({"c": rows}, RUN_DATE)
        self.assertEqual(got[0]["unit"], "pct")
        self.assertEqual(rd._mvval(got[0]["v1"], got[0]["unit"]), "20.0%")


class TestRanking(unittest.TestCase):
    def test_sorted_by_relative_change_and_capped(self):
        cards, metrics = [], {}
        for i, (a, b) in enumerate([(100, 110), (100, 300), (100, 150),
                                    (100, 900), (100, 120), (100, 400)]):
            mid = f"c{i}"
            cards.append((mid, f"卡{i} · Card {i}", "line", {"val": "users"}))
            metrics[mid] = days(("2026-11-17", a), ("2026-11-18", b))
        with sections(cards):
            got = rd._movers(metrics, RUN_DATE, top=5)
        self.assertEqual(len(got), 5)
        self.assertEqual([m["v1"] for m in got], [900, 400, 300, 150, 120])


if __name__ == "__main__":
    unittest.main(verbosity=2)
