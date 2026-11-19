#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置自检 —— 不连库、不连 Metabase,只看 SECTIONS / KEY_OVERRIDE / i18n 对不对得上。

2026-11-19 新建。这里每一条都对应一个**已经犯过**的错:
  · 卡在 KEY_OVERRIDE 里漏登记 → 页面上那张卡静默消失,日志里不报错
  · fmt 写错 → 百分比印成 0.0(pct* 吃 0~1,SQL 给的是 0~100)
  · note 里写 **粗体** / 反引号 → 页面上显示成字面星号(note 是直接拼 HTML 的)
  · 卡名的全角括号后漏一个空格 → ' · ' 分隔符失效,中英拆不开
"""
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import fetch_metabase as fm        # noqa: E402
import i18n                        # noqa: E402
import render_dashboard as rd      # noqa: E402

CJK = r"一-鿿"
# 渲染层认得的列格式。改这个集合之前先看 render_dashboard 的 fmt_cell —— 多出来的值
# 不会报错,会走到 else 分支按原样输出,页面上看着像没格式化。
VALID_FMT = {"text", "int", "d1", "d2", "d4", "d6", "pct0", "pct1"}
VALID_KIND = {"table", "line", "rate", "funnel", "long_dim"}


def _num(v):
    """表格里的数字可能是 '1,234' 这样的字符串(Metabase 给 ≥1000 的数加千分位)。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    return None


def all_cards():
    for section, cards in rd.SECTIONS:
        for mid, title, kind, params in cards:
            yield section, mid, title, kind, params


class TestCards(unittest.TestCase):
    def test_card_id_unique(self):
        seen, dup = set(), []
        for _s, mid, _t, _k, _p in all_cards():
            if mid in seen:
                dup.append(mid)
            seen.add(mid)
        self.assertEqual(dup, [], "SECTIONS 里有重复的卡 id,后一张会盖掉前一张")

    def test_every_card_registered_in_key_override(self):
        """🛑 这条最重要。KEY_OVERRIDE 把 card_id 钉到 key 上,漏登记的卡抓不到数,
        页面上那一格是空的,而抓数日志只说「抓到 N 张」不说少了谁。"""
        keys = set(fm.KEY_OVERRIDE.values())
        missing = sorted({mid for _s, mid, _t, _k, _p in all_cards()} - keys)
        self.assertEqual(missing, [],
                         "这些卡在 SECTIONS 里用了,但 fetch_metabase.KEY_OVERRIDE 里没登记")

    def test_kind_is_known(self):
        bad = [(mid, kind) for _s, mid, _t, kind, _p in all_cards() if kind not in VALID_KIND]
        self.assertEqual(bad, [])

    def test_column_fmt_is_known(self):
        bad = []
        for _s, mid, _t, _k, p in all_cards():
            for col in p.get("cols", []):
                if len(col) > 2 and col[2] not in VALID_FMT:
                    bad.append((mid, col[0], col[2]))
        self.assertEqual(bad, [], "fmt 不在合法集合里,渲染时会按原样输出")

    def test_percent_scale_matches_fmt(self):
        """🛑 本项目最贵的一个坑:pct0/pct1 吃 0~1,d1 吃 0~100,两边的 SQL 都有。
        光看配置分不出谁对 —— 得拿真数据比。所以这条**只在 raw_metrics.json 在场时跑**。

        🛑 只验 pct* 这一侧:pct* 列出现 >1.5 的值,显示出来一定是错的(100% 封顶)。
           反过来「d1 列的值都 ≤1」**不能**判定写错了 —— 兜底率 0.01%、
           崩溃率这类本来就这么小(对话质量每日告警的 fallback_pct 就是,
           SQL 里 ROUND(100.0 * …) 已经乘过 100)。那一侧只能人工看。"""
        raw_path = HERE.parent / "raw_metrics.json"
        if not raw_path.exists():
            self.skipTest("没有 raw_metrics.json,跳过")
        raw = json.loads(raw_path.read_text(encoding="utf-8")).get("metrics", {})
        bad = []
        for _s, mid, _t, _k, p in all_cards():
            rows = raw.get(mid)
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                continue
            for col in p.get("cols", []):
                if len(col) < 3 or "%" not in col[1]:
                    continue
                vals = [v for v in (_num(r.get(col[0])) for r in rows) if v is not None]
                if not vals:
                    continue
                top = max(vals)
                if col[2].startswith("pct") and top > 1.5:
                    bad.append((mid, col[0], col[2], f"最大值 {top} —— 像 0~100,该用 d1"))
        self.assertEqual(bad, [])

    def test_note_has_no_markdown(self):
        """note 是直接拼进 HTML 的,**粗体** 和反引号会原样显示成字面字符。"""
        bad = []
        for _s, mid, _t, _k, p in all_cards():
            note = p.get("note") or ""
            if "**" in note or "`" in note:
                bad.append((mid, note[:50]))
        self.assertEqual(bad, [])


class TestTitles(unittest.TestCase):
    def test_card_title_splits_into_two_languages(self):
        bad = []
        for _s, mid, title, _k, _p in all_cards():
            zh, en = i18n.split_title(title)
            if not en:
                bad.append((mid, title, "拆不出英文"))
            elif re.search(f"[{CJK}]", en):
                # 三段式卡名用 rsplit 取最后一个 ' · ',中文留在英文侧就是这里报
                bad.append((mid, title, "英文侧有中文"))
        self.assertEqual(bad, [])

    def test_section_title_splits_into_two_languages(self):
        # 本来就没有中文的板块名(⑫ Super Power)不用拆
        bad = [s for s, _c in rd.SECTIONS
               if re.search(f"[{CJK}]", s) and not i18n.split_title(s)[1]]
        self.assertEqual(bad, [])

    def test_chinese_only_columns_are_translatable(self):
        """🛑 I18N 是「页面原文 → English」,靠文本节点整串查表。
        所以拆出来的中文侧**必须等于页面上的原文**,否则查不到表,
        英文模式下那一列仍是中文 —— 不报错,切到英文才看得出来。

        只管**一个拉丁字母都没有**的列名:那种必须靠 I18N 翻译,查不到就整列是中文。
        混排列名(装机日 Install Date、组 Arm)原文自带英文,英文读者读得懂,
        不在这条管辖内 —— 把它们算进来会报出 58 条噪音,测试就没人看了。

        🛑 这条抓不到带缩写的:「装机→QCD」「延迟中位(分) p50」里的 QCD / p50 是字母,
           会被当成自带英文跳过,但它们不是中文那半的翻译 —— 英文模式下仍是中文。
           这类只能人工看,发现了就补进 COLUMN_FIX(第一项写原文全串)。"""
        bad = []
        for _s, mid, _t, _k, p in all_cards():
            for col in p.get("cols", []):
                label = col[1]
                if not re.search(f"[{CJK}]", label):
                    continue
                if re.search(r"[A-Za-z]", label):       # 自带英文的混排列名
                    continue
                if i18n.split_column(label)[0] != label:
                    bad.append((mid, label, i18n.split_column(label)))
        self.assertEqual(bad, [],
                         "这些列的中文侧和原文对不上,补进 i18n.COLUMN_FIX(第一项写原文全串)")

    def test_column_labels_have_no_trailing_space(self):
        """列名末尾多一个空格,I18N 的 key 就和页面原文差一个字符,整条查不到。"""
        bad = [(mid, repr(col[1])) for _s, mid, _t, _k, p in all_cards()
               for col in p.get("cols", []) if col[1] != col[1].strip()]
        self.assertEqual(bad, [])

    def test_column_labels_have_english(self):
        """带中文的列名都要能查到英文 —— 查不到不报错,只是英文模式下那一格仍是中文。"""
        bad = []
        for _s, mid, _t, _k, p in all_cards():
            for col in p.get("cols", []):
                label = col[1]
                if not re.search(f"[{CJK}]", label):
                    continue
                if not i18n.split_column(label)[1]:
                    bad.append((mid, label))
        self.assertEqual(bad, [],
                         "这些列名拆不出英文,补进 i18n.COLUMN_FIX 或 COLUMN_EN")


class TestChangelogSource(unittest.TestCase):
    def test_constants_stay_empty(self):
        """2026-11-19 起 changelog 和切点只从 Lark 来。常量里再写就会重复显示。"""
        import ast
        src = (HERE.parent / "render_dashboard.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        literal = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ("CUTOVERS", "CHANGELOG"):
                    literal[name] = ast.literal_eval(node.value)
        self.assertEqual(literal.get("CUTOVERS"), {},
                         "CUTOVERS 常量应该是空的,新切点写 Lark「数据表」或「soulmap详细记录」")
        self.assertEqual(literal.get("CHANGELOG"), [],
                         "CHANGELOG 常量应该是空的,新变更写 Lark「数据表」")


if __name__ == "__main__":
    unittest.main(verbosity=2)
