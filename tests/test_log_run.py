#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行记录的读写 —— 不连库。

2026-11-19 新建。这个脚本的唯一硬要求是:**它自己出错不能把流水线带下去**。
抓数已经跑完了,就因为记日志失败而不发布看板,是本末倒置。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import log_run    # noqa: E402


class _TempLog(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._saved = log_run.LOG
        log_run.LOG = Path(self._dir.name) / "logs" / "runs.jsonl"

    def tearDown(self):
        log_run.LOG = self._saved
        self._dir.cleanup()

    def write_raw(self, meta):
        p = Path(self._dir.name) / "raw.json"
        p.write_text(json.dumps({"_meta": meta, "metrics": {}}), encoding="utf-8")
        return p


class TestAppend(_TempLog):
    def test_writes_one_line_per_run(self):
        raw = self.write_raw({"run_date": "2026-11-19", "n_cards": 71, "n_asked": 88,
                              "failed": ["a", "b"], "seconds": 1475.0,
                              "round_seconds": [286.0, 731.0, 458.0],
                              "timings": {"a": 61.0, "b": 3.2},
                              "rounds_taken": {"b": 1}})
        log_run.append(raw)
        log_run.append(raw)
        runs = log_run.load_runs()
        self.assertEqual(len(runs), 2, "一天跑两轮就是两条记录,不按日期去重")
        self.assertEqual(runs[0]["n_cards"], 71)
        self.assertEqual(runs[0]["n_failed"], 2)
        self.assertEqual(runs[0]["round_seconds"], [286.0, 731.0, 458.0])

    def test_missing_file_does_not_raise(self):
        """🛑 记日志失败不能让整条流水线挂掉。"""
        self.assertEqual(log_run.append(Path("/nonexistent/raw.json")), 0)
        self.assertEqual(log_run.load_runs(), [])

    def test_broken_json_does_not_raise(self):
        p = Path(self._dir.name) / "broken.json"
        p.write_text("{不是 json", encoding="utf-8")
        self.assertEqual(log_run.append(p), 0)

    def test_meta_without_timings_still_logs(self):
        """2026-11-19 之前抓的 raw 没有 timings,那几行照样要能记。"""
        raw = self.write_raw({"run_date": "2026-11-18", "n_cards": 71, "failed": []})
        log_run.append(raw)
        row = log_run.load_runs()[0]
        self.assertEqual(row["timings"], {})
        self.assertIsNone(row["seconds"])


class TestLoad(_TempLog):
    def test_half_written_line_is_skipped(self):
        """断电 / 容器被杀会留下半行。那一行跳过,别让整个文件读不出来。"""
        log_run.LOG.parent.mkdir(parents=True, exist_ok=True)
        log_run.LOG.write_text(
            json.dumps({"at": "2026-11-18 03:00", "n_cards": 71, "n_failed": 0}) + "\n"
            + '{"at": "2026-11-19 03:0\n'
            + json.dumps({"at": "2026-11-19 04:00", "n_cards": 88, "n_failed": 0}) + "\n",
            encoding="utf-8")
        runs = log_run.load_runs()
        self.assertEqual([r["n_cards"] for r in runs], [71, 88])


class TestQueries(_TempLog):
    def test_show_and_slow_and_trend_run_on_an_empty_log(self):
        """还没有记录时,三个查询都要正常返回,不能抛异常。"""
        self.assertEqual(log_run.show(7), 0)
        self.assertEqual(log_run.slow(10), 0)
        self.assertEqual(log_run.trend("某张卡"), 1)

    def test_trend_finds_a_card_across_runs(self):
        log_run.LOG.parent.mkdir(parents=True, exist_ok=True)
        with log_run.LOG.open("w", encoding="utf-8") as f:
            for at, sec in [("2026-11-17 03:00", 12.0), ("2026-11-18 03:00", 48.0),
                            ("2026-11-19 03:00", 61.0)]:
                f.write(json.dumps({"at": at, "n_cards": 1, "n_failed": 0,
                                    "timings": {"某张慢卡": sec}}, ensure_ascii=False) + "\n")
        self.assertEqual(log_run.trend("某张慢卡"), 0)
        self.assertEqual(log_run.trend("不存在的卡"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
