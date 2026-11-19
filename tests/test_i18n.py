#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中英切换的拆分规则 —— 不连库。

2026-11-19 新建。这里每一条都对应一个**已经犯过**的错:
  · 三段式卡名按第一个 ' · ' 拆 → 中文留在英文侧
  · 全角括号后漏一个空格 → ' · ' 失效,整条拆不开
  · 「装机→QCD」被拆成「装机」+「→QCD」→ 英文侧以箭头开头
  · changelog / 切点的英文改从 Lark 来之后,常量表必须保持空的
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import i18n    # noqa: E402


class TestSplitTitle(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(i18n.split_title("渠道启动成功率 · Channel Start Success"),
                         ("渠道启动成功率", "Channel Start Success"))

    def test_three_parts_keeps_chinese_on_the_left(self):
        """🛑 用 rsplit 取最后一个 ' · ' —— 卡名里本来就带一个中文的 ' · '。"""
        zh, en = i18n.split_title("按装机日明细 · Meta 素材全链路 · Meta Funnel by Install Date")
        self.assertEqual(zh, "按装机日明细 · Meta 素材全链路")
        self.assertEqual(en, "Meta Funnel by Install Date")

    def test_no_separator(self):
        self.assertEqual(i18n.split_title("Super Power"), ("Super Power", None))

    def test_missing_space_after_fullwidth_paren_is_not_split(self):
        """踩过的坑:「有效留存 D1(账号)· Effective…」—— 全角括号后漏了空格,
        分隔符失效。这里钉住「拆不开」这个事实,好让 test_config 的卡名检查能抓到它。"""
        self.assertIsNone(i18n.split_title("有效留存 D1(账号)· Effective Retention D1")[1])


class TestSplitColumn(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(i18n.split_column("装机日 Install Date"), ("装机日", "Install Date"))

    def test_pure_chinese_column_comes_from_the_manual_table(self):
        """纯中文列名(连 % 都不算英文)自动拆不出东西,只能靠 COLUMN_EN。"""
        self.assertEqual(i18n.split_column("正常启动率 %"), ("正常启动率 %", "Normal Launch %"))
        self.assertIsNone(i18n.split_column("没登记过的中文列名")[1])

    def test_arrow_does_not_start_the_english_side(self):
        """「曝光→深聊 Impr→Deep」:中间那个箭头不能成为英文侧的开头。"""
        zh, en = i18n.split_column("曝光→深聊 Impr→Deep")
        self.assertEqual(zh, "曝光→深聊")
        self.assertEqual(en, "Impr→Deep")

    def test_abbreviation_after_arrow_needs_the_manual_table(self):
        """🛑 「装机→QCD」自动拆会切成「装机→」+「QCD」—— 中文侧和页面原文对不上,
        I18N 查不到表,英文模式下这列仍显示中文。2026-11-19 补进 COLUMN_FIX。"""
        self.assertEqual(i18n.split_column("装机→QCD"), ("装机→QCD", "Install → QCD"))

    def test_pure_english_unchanged(self):
        self.assertEqual(i18n.split_column("Install Date"), ("Install Date", None))

    def test_manual_tables_win(self):
        """COLUMN_FIX / COLUMN_EN 优先于自动拆 —— 中文里夹着 query / 0.99 这类会切坏。"""
        for label, pair in list(i18n.COLUMN_FIX.items())[:3]:
            self.assertEqual(i18n.split_column(label), pair)
        for label, en in list(i18n.COLUMN_EN.items())[:3]:
            self.assertEqual(i18n.split_column(label), (label, en))


class TestManualTables(unittest.TestCase):
    def test_no_duplicate_keys(self):
        """🛑 dict 字面量里重复的 key **不报错**,后面那条静默覆盖前面的。
        2026-11-19 踩过:在表头加了一条,表尾早就有同 key 的一条,加的那条无效。"""
        import ast
        src = (HERE.parent / "i18n.py").read_text(encoding="utf-8")
        for node in ast.parse(src).body:
            if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)):
                continue
            name = node.targets[0].id
            if not name.startswith(("COLUMN_", "CUTOVERS_", "CHANGELOG_")):
                continue
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            dup = sorted({k for k in keys if keys.count(k) > 1})
            self.assertEqual(dup, [], f"{name} 里有重复的 key,后面那条会盖掉前面的")


class TestSplitNote(unittest.TestCase):
    def test_fullwidth_bar(self):
        zh, en = i18n.split_note("分母是装机设备。｜ Installed but never booted.")
        self.assertEqual(zh, "分母是装机设备。")
        self.assertEqual(en, "Installed but never booted.")

    def test_no_separator(self):
        self.assertEqual(i18n.split_note("只有中文")[1], None)


class TestBlockSwap(unittest.TestCase):
    def test_bi_emits_both_languages(self):
        html = i18n.bi("中文", "English")
        self.assertIn('data-en="English"', html)
        self.assertIn(">中文<", html)

    def test_bi_escapes_quotes(self):
        """英文里带引号不能把 data-en 属性提前闭合。"""
        html = i18n.bi("中文", 'say "hi"')
        self.assertNotIn('data-en="say "hi""', html)


class TestLarkIsTheOnlySource(unittest.TestCase):
    def test_changelog_and_cutover_tables_stay_empty(self):
        """2026-11-19 起这两张英文表由 render_dashboard._load_changes() 从 Lark 回填。
        常量里再写死就会和 Lark 的内容打架。"""
        import ast
        src = (HERE.parent / "i18n.py").read_text(encoding="utf-8")
        for node in ast.parse(src).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ("CHANGELOG_EN", "CUTOVERS_EN"):
                    self.assertEqual(ast.literal_eval(node.value), {},
                                     f"{name} 应该是空的,英文写 Lark 的「事项(EN)」列")


if __name__ == "__main__":
    unittest.main(verbosity=2)
