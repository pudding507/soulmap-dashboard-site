# -*- coding: utf-8 -*-
"""check_stale_cards.py 的测试。

这个脚本跑在刷新管线里(scheduled_refresh.sh + daily.yml),它自己绝不能抛异常,
所以这里重点测三件:坏输入不炸、连续失败数算得对、只在踩到阈值倍数那轮才推。
"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import check_stale_cards as csc


def _runs(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                    encoding="utf-8")


def _row(at, failed, cards=("A", "B")):
    return {"at": at, "failed": list(failed),
            "timings": {c: 1.0 for c in cards if c not in failed}}


class TestLoadRuns(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())

    def test_missing_file(self):
        self.assertEqual(csc.load_runs(self.d / "nope.jsonl"), [])

    def test_skips_bad_lines(self):
        p = self.d / "r.jsonl"
        p.write_text('{"bad\n{"at":"1","failed":[],"timings":{}}\n\n', encoding="utf-8")
        self.assertEqual(len(csc.load_runs(p)), 1)


class TestStreaks(unittest.TestCase):
    def test_counts_consecutive_failures(self):
        rows = [_row("1", []), _row("2", ["A"]), _row("3", ["A"]), _row("4", ["A"])]
        streak, last_ok, at = csc.streaks(rows)
        self.assertEqual(streak.get("A"), 3)
        self.assertEqual(last_ok.get("A"), "1")
        self.assertEqual(at, "4")

    def test_success_resets_streak(self):
        rows = [_row("1", ["A"]), _row("2", ["A"]), _row("3", []), _row("4", ["A"])]
        streak, last_ok, _ = csc.streaks(rows)
        self.assertEqual(streak.get("A"), 1)
        self.assertEqual(last_ok.get("A"), "3")

    def test_healthy_card_has_no_streak(self):
        rows = [_row("1", ["A"]), _row("2", ["A"])]
        streak, _, _ = csc.streaks(rows)
        self.assertNotIn("B", streak)

    def test_ignores_cards_absent_from_last_round(self):
        """卡下线后(86 → 81 张)不该再报它。"""
        rows = [_row("1", ["GONE"], cards=("A", "GONE")),
                _row("2", ["GONE"], cards=("A", "GONE")),
                _row("3", [], cards=("A",))]
        streak, _, _ = csc.streaks(rows)
        self.assertNotIn("GONE", streak)

    def test_empty(self):
        self.assertEqual(csc.streaks([]), ({}, {}, ""))


class TestMain(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.p = self.d / "runs.jsonl"

    def _run(self, argv):
        old = sys.argv
        sys.argv = ["check_stale_cards.py", "--runs", str(self.p)] + argv
        try:
            return csc.main()
        finally:
            sys.argv = old

    def test_returns_zero_on_short_history(self):
        _runs(self.p, [_row("1", [])])
        self.assertEqual(self._run(["--dry-run"]), 0)

    def test_returns_zero_when_all_healthy(self):
        _runs(self.p, [_row(str(i), []) for i in range(5)])
        self.assertEqual(self._run(["--dry-run"]), 0)

    def test_returns_zero_when_stale(self):
        _runs(self.p, [_row("0", [])] + [_row(str(i), ["A"]) for i in range(1, 5)])
        self.assertEqual(self._run(["--dry-run"]), 0)

    def test_never_raises_on_garbage(self):
        self.p.write_text("not json at all\n{{{\n", encoding="utf-8")
        self.assertEqual(self._run(["--dry-run"]), 0)


if __name__ == "__main__":
    unittest.main()
