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
def sections(cards, cutovers=None):
    """_movers 读的是模块级 SECTIONS 和 CUTOVERS,测试期间整个换掉 ——
    CUTOVERS 是从 Lark 拉下来的真实数据,不隔离的话用例的结果会随当天的切点变。"""
    saved_s, saved_c = rd.SECTIONS, rd.CUTOVERS
    rd.SECTIONS = [("测试区 · Test", cards)]
    rd.CUTOVERS = cutovers or {}
    try:
        yield
    finally:
        rd.SECTIONS, rd.CUTOVERS = saved_s, saved_c


def days(*pairs, col="users"):
    return [{"date": d, col: v} for d, v in pairs]


class TestCompleteDaysOnly(unittest.TestCase):
    def test_today_is_excluded(self):
        """口径 ①:run_date 当天那条不参与,否则榜上天天是假跌。"""
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = days(("2026-11-17", 100), ("2026-11-18", 200), ("2026-11-19", 3))
        with sections([card]):
            got, _ = rd._movers({"c": rows}, RUN_DATE)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["d0"], got[0]["d1"]), ("2026-11-17", "2026-11-18"))
        self.assertEqual((got[0]["v0"], got[0]["v1"]), (100, 200))

    def test_needs_two_complete_days(self):
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = days(("2026-11-18", 200), ("2026-11-19", 300))
        with sections([card]):
            self.assertEqual(rd._movers({"c": rows}, RUN_DATE)[0], [])


class TestNumeratorThreshold(unittest.TestCase):
    def test_small_numerator_is_dropped(self):
        """口径 ②:分子没到门槛的不进榜 —— 2 → 4 的相对变化是 100%,但读不出。"""
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = days(("2026-11-17", 2), ("2026-11-18", 4))
        with sections([card]):
            self.assertEqual(rd._movers({"c": rows}, RUN_DATE)[0], [])

    def test_both_days_must_pass(self):
        """一天够、另一天不够,也不进榜。"""
        below = rd.MOVERS_MIN_N - 1
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = days(("2026-11-17", below), ("2026-11-18", 500))
        with sections([card]):
            self.assertEqual(rd._movers({"c": rows}, RUN_DATE)[0], [])

    def test_rate_card_checks_numerator_not_rate(self):
        """比率卡卡的是分子,不是比率本身。"""
        card = ("c", "卡 · Card", "rate", {"rate": ("paid", "total")})
        rows = [{"date": "2026-11-17", "paid": 5, "total": 1000},
                {"date": "2026-11-18", "paid": 9, "total": 1000}]
        with sections([card]):
            self.assertEqual(rd._movers({"c": rows}, RUN_DATE)[0], [])


class TestExcludedKinds(unittest.TestCase):
    def test_table_and_funnel_never_rank(self):
        """口径 ④。"""
        rows = days(("2026-11-17", 100), ("2026-11-18", 200))
        for kind in ("table", "funnel"):
            with self.subTest(kind=kind), sections([("c", "卡 · Card", kind, {"val": "users"})]):
                self.assertEqual(rd._movers({"c": rows}, RUN_DATE)[0], [])

    def test_avg_and_median_never_rank(self):
        """口径 ③。"""
        rows = days(("2026-11-17", 100), ("2026-11-18", 200))
        for agg in ("avg", "median"):
            with self.subTest(agg=agg), \
                 sections([("c", "卡 · Card", "line", {"val": "users", "agg": agg})]):
                self.assertEqual(rd._movers({"c": rows}, RUN_DATE)[0], [])


class TestOneRowPerCard(unittest.TestCase):
    def test_multi_series_card_yields_one_row(self):
        """口径 ⑤:一张多序列的卡按天汇总成一行,否则它能占满五行。"""
        card = ("c", "卡 · Card", "line", {"val": "users"})
        rows = [{"date": "2026-11-17", "arm": "a", "users": 60},
                {"date": "2026-11-17", "arm": "b", "users": 40},
                {"date": "2026-11-18", "arm": "a", "users": 120},
                {"date": "2026-11-18", "arm": "b", "users": 80}]
        with sections([card]):
            got, _ = rd._movers({"c": rows}, RUN_DATE)
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
            got, _ = rd._movers({"c": rows}, RUN_DATE)
        self.assertEqual(got[0]["unit"], "d1")
        self.assertEqual(rd._mvval(got[0]["v1"], got[0]["unit"]), "3.6")

    def test_rate_without_fmt_is_a_percentage(self):
        card = ("c", "付费率 · Paid Rate", "rate", {"rate": ("paid", "total")})
        rows = [{"date": "2026-11-17", "paid": 100, "total": 1000},
                {"date": "2026-11-18", "paid": 200, "total": 1000}]
        with sections([card]):
            got, _ = rd._movers({"c": rows}, RUN_DATE)
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
            got, _ = rd._movers(metrics, RUN_DATE, top=5)
        self.assertEqual(len(got), 5)
        self.assertEqual([m["v1"] for m in got], [900, 400, 300, 150, 120])


if __name__ == "__main__":
    unittest.main(verbosity=2)


def many(n, cut_date=None):
    """n 张卡,相对变化依次递减;cut_date 那天所有卡都跨切点。"""
    cards, metrics = [], {}
    for i in range(n):
        mid = f"m{i}"
        cards.append((mid, f"指标{i} · Metric {i}", "line", {"val": "users"}))
        metrics[mid] = days(("2026-11-17", 100), ("2026-11-18", 1000 - i * 10))
    return cards, metrics


class TestConfig(unittest.TestCase):
    def test_defaults_survive_a_missing_file(self):
        """配置文件没了不该让整个看板发不出去。"""
        saved = rd.CONFIG_JSON
        try:
            rd.CONFIG_JSON = Path("/nonexistent/movers.json")
            cfg = rd._load_movers_config()
        finally:
            rd.CONFIG_JSON = saved
        self.assertEqual(cfg["top"], rd.MOVERS_TOP)
        self.assertEqual(cfg["min_numerator"], rd.MOVERS_MIN_N)

    def test_threshold_comes_from_config(self):
        cards, metrics = many(3)
        cfg = dict(rd.MOVERS_CFG, min_numerator=100000)
        with sections(cards):
            got, _ = rd._movers(metrics, RUN_DATE, cfg=cfg, history={})
        self.assertEqual(got, [], "门槛抬到十万,不该有指标进榜")

    def test_top_comes_from_config(self):
        cards, metrics = many(8)
        cfg = dict(rd.MOVERS_CFG, top=3)
        with sections(cards):
            got, _ = rd._movers(metrics, RUN_DATE, cfg=cfg, history={})
        self.assertEqual(len(got), 3)


class TestSuppressSameCutover(unittest.TestCase):
    """🛑 2026-11-19 的实况:五行全是同一个切点,这张卡当天等于没提供信息。"""

    CUT = {"2026-11-18": "能量账本改为一位小数"}

    def _with_cutover(self, n_cards, n_with_cut):
        cards, metrics = many(n_cards)
        # 只让前 n_with_cut 张卡落在切点那天,其余往前挪一天
        for i in range(n_with_cut, n_cards):
            metrics[f"m{i}"] = days(("2026-11-16", 100), ("2026-11-17", 900 - i * 10))
        return cards, metrics

    def test_at_most_two_rows_share_a_cutover_when_substitutes_exist(self):
        cards, metrics = self._with_cutover(8, 5)
        with sections(cards, self.CUT):
            got, dropped = rd._movers(metrics, RUN_DATE, history={})
        with_cut = [m for m in got if m["cut"]]
        self.assertEqual(len(with_cut), 2, "同一个切点最多占 2 行")
        self.assertEqual(len(got), 5, "被挤下去的要让位给下一名,榜上仍是 5 行")
        self.assertTrue(all(m["why"] == "same_cutover" for m in dropped))

    def test_refills_when_there_is_no_substitute(self):
        """🛑 所有候选都跨同一个切点时,压制会把榜压成 2 行 ——
        「变化最大的 5 个数」给 2 个数更难读,所以补回来并在榜底说明。"""
        cards, metrics = self._with_cutover(6, 6)
        with sections(cards, self.CUT):
            got, dropped = rd._movers(metrics, RUN_DATE, history={})
        self.assertEqual(len(got), 5)
        self.assertEqual(len([m for m in got if m.get("refilled")]), 3)
        self.assertEqual(len(dropped), 1, "补满 5 行之后剩下的仍在 dropped 里")

    def test_can_be_turned_off(self):
        cards, metrics = self._with_cutover(6, 6)
        cfg = dict(rd.MOVERS_CFG, suppress={"max_per_cutover": 0, "repeat_days": 0})
        with sections(cards, self.CUT):
            got, dropped = rd._movers(metrics, RUN_DATE, cfg=cfg, history={})
        self.assertEqual(len(got), 5)
        self.assertEqual(dropped, [])
        self.assertFalse(any(m.get("refilled") for m in got))


class TestSuppressRepeat(unittest.TestCase):
    def test_card_on_the_list_three_days_running_gives_up_its_slot(self):
        cards, metrics = many(8)
        history = {d: ["m0"] for d in ("2026-11-16", "2026-11-17", "2026-11-18")}
        with sections(cards):
            got, dropped = rd._movers(metrics, RUN_DATE, history=history)
        self.assertNotIn("m0", [m["key"] for m in got], "连上三天的该让位")
        self.assertEqual(len(got), 5)
        self.assertEqual([m["key"] for m in dropped], ["m0"])
        self.assertEqual(dropped[0]["streak"], 3)

    def test_a_gap_resets_the_streak(self):
        """哪天没跑(周末、Actions 挂了)不该把连续计数打断 —— 按有记录的日期往回数。"""
        cards, metrics = many(8)
        history = {"2026-11-16": ["m0"], "2026-11-17": [], "2026-11-18": ["m0"]}
        with sections(cards):
            got, _ = rd._movers(metrics, RUN_DATE, history=history)
        self.assertIn("m0", [m["key"] for m in got], "中间断过一天,连续计数重新算")


class TestHistoryFile(unittest.TestCase):
    def test_keeps_only_30_days(self):
        import tempfile
        saved = rd.HISTORY_JSON
        with tempfile.TemporaryDirectory() as d:
            rd.HISTORY_JSON = Path(d) / "h.json"
            try:
                runs = {f"2026-{m:02d}-{day:02d}": ["x"]
                        for m in (9, 10) for day in range(1, 29)}
                rd._save_history(runs, "2026-11-19", ["y"])
                kept = rd._load_history()
            finally:
                rd.HISTORY_JSON = saved
        self.assertEqual(len(kept), 30)
        self.assertIn("2026-11-19", kept)
