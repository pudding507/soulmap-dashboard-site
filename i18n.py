#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主看板的中英切换 · Bilingual support for the main dashboard

页面默认中文,右上角按钮切英文。切换不是两份页面,是同一份 DOM 换文本:
这里把每条文案拆成「中文 → English」塞进页面,JS 遍历文本节点按表替换。

文案本来就是双语并排的,格式有三种,拆法各不相同:
  · 区名 / 卡名   「中文 · English」      按 ' · ' 拆
  · note          「中文 ｜ English」      按 ' ｜ ' 拆
  · 列名 / 维度名 「中文 English」         没有分隔符,按「最后一个中文字之后」拆

🛑 列名那条规则对 410 个列名有效,另外两类要手工兜:
   COLUMN_FIX  —— 自动拆会切坏的(中文里本来就夹着 query / token / 0.99 这类)
   COLUMN_EN   —— 压根没写英文的纯中文列名
   两张表都按「原文 → 结果」精确匹配,改列名时要同步改这里,否则那一列切英文时不变。
"""
from __future__ import annotations
import re

CJK = r'一-鿿'
CJK_PUNCT = r'，。？！：；、「」『』（）【】·…—'
_BOUND = CJK + CJK_PUNCT

# ---------- 自动拆会切坏的列名:原文 → (中文, 英文);英文为 None 表示整条就是中文 ----------
COLUMN_FIX = {
    # 2026-11-19 补:这三条自动拆会把中文留在页面上(英文模式下仍显示中文)。
    # 拆分规则是「最后一个中文字之后是英文」,QCD 这种纯大写缩写会被当成英文切走,
    # 「延迟中位(分) p50」的 p50 同理(那两条在下面,2026-11-19 把中文侧补全了)——
    # 切走之后 I18N 的 key 和页面上的原文对不上,查不到表就不翻译。
    "装机→QCD": ("装机→QCD", "Install → QCD"),
    "开聊→QCD": ("开聊→QCD", "Chat → QCD"),
    "不同 query Distinct":        ("不同 query", "Distinct"),
    "拿到 token Token":           ("拿到 token", "Token"),
    "无效 token Invalid":         ("无效 token", "Invalid"),
    "没 token No Token":          ("没 token", "No Token"),
    "没 token %":                 ("没 token %", "No Token %"),
    "没授权但有token No-Grant Token": ("没授权但有 token", "No-Grant Token"),
    "注册率(÷token) Reg %":       ("注册率(÷token)", "Reg % (÷token)"),
    "占有token的 %":               ("占有token的 %", "% of With Token"),
    "应发(真实0.99) Should":       ("应发(真实 0.99)", "Should Grant"),
    "开过订阅(试用或0.99) Sub Started": ("开过订阅(试用或 0.99)", "Sub Started"),
    "延迟最大(分) max":             ("延迟最大(分) max", "Max Delay (min)"),
    "延迟中位(分) p50":             ("延迟中位(分) p50", "Median Delay (min) p50"),
    "占能量用户 % of Energy":        ("占能量用户 %", "% of Energy Users"),
    "到期时刻(SGT)":                ("到期时刻(SGT)", "Expiry (SGT)"),
    "首购时刻(SGT)":                ("首购时刻(SGT)", "First Purchase (SGT)"),
    "读得出? Readable":            ("读得出?", "Readable"),
    "阿语模板残留 AR /ة":            ("阿语模板残留", "Arabic Template Left"),
    "每条收入(现价)Rev/Msg $":       ("每条收入(现价)", "Revenue / Msg $"),
}

# ---------- 2026-11-25 新增:英文模式下仍是中文的,按页面原文精确给英文 ----------
# 🛑 key 必须是**页面上显示的那一整串原文**,不是拆过的中文侧。
#    COLUMN_FIX 的第一项是「修正后的中文」,和页面原文往往差一个空格或括号,
#    所以那张表对这些列不起作用 —— 这里按原文兜。
#
# 🛑 广告素材名 / 系列名(SoulMap_CH15_..._想象_...)**故意不翻译**:
#    它们是标识符,要和 Meta 导出对得上,翻了就对不上。
EXACT_EN = {
    # —— 列名:英文侧以数字或符号开头,自动规则不敢切 ——
    "10+轮 10+ Turns": "10+ Turns",
    "5+轮 5+ Turns": "5+ Turns",
    ">3句 >3 msgs": ">3 msgs",
    "≥10句 ≥10 msgs": "≥10 msgs",
    "≥20句 ≥20 msgs": "≥20 msgs",
    "≥20条 ≥20 msgs": "≥20 msgs",
    "≥5条 ≥5 msgs": "≥5 msgs",
    "其中 0.99 Intro": "0.99 Intro",
    "应发(真实0.99) Should": "Should Grant",
    "开过订阅(试用或0.99) Sub Started": "Sub Started",
    "拒:接口非200 Non-200": "Declined: Non-200",
    "每能量到手 $/Energy": "Takehome $/Energy",
    "注册·满72h Registered": "Registered (72h+)",
    "注册率(÷token) Reg %": "Reg % (÷token)",

    # —— 来源 / 归因 ——
    "广告": "Ad",
    "自然量": "Organic",
    "(无归因)": "(No attribution)",
    "(自然量/无素材)": "(Organic / no creative)",
    "(查不到版本)": "(Version unknown)",
    "(查不到)": "(Unknown)",
    "(未分组)": "(Unassigned)",
    "(未标档位)": "(No tier)",
    "(未登记)": "(Not registered)",
    "(未上线)": "(Not live)",
    "(未传)": "(Not sent)",
    "(认不出)": "(Unrecognized)",

    # —— 退订与挽回链路 ——
    "A · 扣款失败挽回": "A · Billing-failure recovery",
    "B · 主动取消挽回": "B · User-cancel recovery",
    "C · 两条链都不管": "C · Neither chain",

    # —— 0.99 首月到期逐人结果 ——
    "1_扣全价成功": "1_Full price charged",
    "2_扣款失败已失效": "2_Billing failed, expired",
    "3_退订后到期失效": "3_Canceled, then expired",
    "4_扣款失败重试中": "4_Billing failed, retrying",
    "5_已关自动续费待到期": "5_Auto-renew off, pending expiry",
    "7_已到期待回执": "7_Expired, awaiting receipt",

    # —— 播放与没出声 ——
    "1 播放结果": "1 Playback result",
    "2 没出声的原因": "2 Why no audio",
    "正常播完": "Played to end",
    "被额度拦住": "Blocked by quota",
    "没有音频可播": "No audio to play",
    "出声前被用户放弃": "Abandoned before audio",
    "模型回的是空": "Model returned empty",
    "就绪但没有音频": "Ready but no audio",
    "结束时没有音频": "No audio at end",
    "结束时没有音频流": "No audio stream at end",

    # —— 兑换结果按来源 ——
    "用户手输": "Typed by user",
    "深链接自动": "Deep link (auto)",
    "绑定成功": "Bound",
    "查无此码": "Code not found",
    "自己邀请自己": "Self-invite",
    "已经绑过": "Already bound",
    "同一台设备(反自邀)": "Same device (anti self-invite)",
    "双方互邀(字面,待确认)": "Mutual invite (literal, unconfirmed)",
    "绑上但未发奖(字面,待确认)": "Bound, reward not granted (literal, unconfirmed)",

    # —— 角色类型 ——
    "A 类": "Type A",
    "B 类": "Type B",
    "A_仅真实": "A_Realistic only",
    "B_仅幻想": "B_Fictional only",
    "AB_两类都进过": "AB_Both types",
    "未知类型": "Unknown type",
    "用户自建": "User-created",
    "没开口": "Never messaged",
    "Divya (A 类)": "Divya (Type A)",
    "Sander (A 类)": "Sander (Type A)",
    "Lucien (B 类)": "Lucien (Type B)",
    "Yui (B 类)": "Yui (Type B)",
    "Kabir (B 类)": "Kabir (Type B)",

    # —— 付费墙 / 撞墙 ——
    "额度硬墙": "Hard quota wall",
    "软墙(印度·可关)": "Soft wall (India, dismissible)",
    "首条消息门": "First-message gate",
    "Me 页": "Me page",
    "见过启动墙": "Saw launch wall",
    "没见过": "Not seen",
    "否": "No",
    "1 · 第10条": "1 · Msg 10",
    "2 · 第20条": "2 · Msg 20",
    "点订阅分子<10，该格读不出": "Tap-subscribe numerator <10, not readable",
    "🛑 24 小时窗口未走完，下游各列偏低，不要做趋势判断":
        "🛑 24h window not complete; downstream columns read low — do not infer a trend",

    # —— 订阅类型 / 档位 ——
    "全价": "Full price",
    "免费试用": "Free trial",
    "0.99 首期": "0.99 intro",
    "月卡": "Monthly plan",
    "只买过 1 次": "Bought once only",
    "买过 2 次及以上": "Bought 2+ times",
    "活动 每条 2": "Activity, 2 per msg",
    "🛑 赠送月 Promotional(无换算规则)": "🛑 Promotional month (no conversion rule)",
    "🛑 0.99 首月 Intro(无换算规则)": "🛑 0.99 intro month (no conversion rule)",

    # —— 能量钱包三层 ——
    "① 买来的 Purchased(永不过期)": "① Purchased (never expires)",
    "② 订阅额度 Plan(🛑 月底清零)": "② Plan (🛑 resets at month end)",
    "③ 赠送 Bonus(14 天过期)": "③ Bonus (expires in 14 days)",

    # —— 复购与月卡的分块标题 ——
    "① 购买次序": "① Purchase order",
    "② 买了什么": "② What was bought",
    "③ 月卡到手后逐日消耗": "③ Daily burn after plan grant",
    "④ 月卡到手合计": "④ Plan grants total",
    "⑤ 月卡到期再买": "⑤ Repurchase after plan expiry",

    # —— 口径分段(切点) ——
    "① 旧墙(10-29 前注册)": "① Old wall (signed up before 10-29)",
    "② 能量上线后(10-29 起注册)": "② After Energy launch (signed up from 10-29)",
    "② 语义搜索(10-26 15:14 起)": "② Semantic search (from 10-26 15:14)",
    "③ 语义+打分重排(10-28 18:22 起)": "③ Semantic + rerank (from 10-28 18:22)",
    "🛑 切换当天 新旧混合": "🛑 Switch day — old and new mixed",

    # —— 版本入口 ——
    "3.8.x 「＋」": "3.8.x \u201c+\u201d",
    "3.9+ 胶囊": "3.9+ capsule",
    "能看到 0.99 (>=3.7.0)": "Can see 0.99 (>=3.7.0)",

    # —— 免费语音体验 ——
    "语音消息 🔊 TTS(免费 4 次)": "Voice message 🔊 TTS (4 free)",
    "语音回复 Voice Reply(免费 4 次)": "Voice reply (4 free)",

    # —— 语音随机分桶对照 ——
    "开口(首日 ≥1 条)": "Messaged (≥1 on day 0)",
    "首日 ≥10 条": "≥10 msgs on day 0",
    "首日 ≥20 条": "≥20 msgs on day 0",
    "首日用过语音(= 依从率)": "Used voice on day 0 (= compliance)",
    "区间重叠 ⇒ 读不出": "Intervals overlap ⇒ not readable",
    "🔴 区间不重叠 ⇒ 读得出": "🔴 Intervals do not overlap ⇒ readable",

    # —— 结账链路的实验臂 ——
    "half 半屏": "half",
    "full 全屏": "full",
    "未进组": "Not in experiment",

    # —— 队列成熟度 ——
    "仅 7d 可读 7d only": "7d only",
}

# ---------- 压根没写英文的列名 ----------
COLUMN_EN = {
    # 句数 / 深度
    "20句率": "20-Msg Rate %", "6句率": "6-Msg Rate %", ">3句 %": ">3 Msgs %",
    ">3句 % ": ">3 Msgs %", "≥10句 %": "≥10 Msgs %", "≥20句 %": "≥20 Msgs %",
    "≥100句 %": "≥100 Msgs %", "≥20率 %": "≥20 Rate %", "≥5率 %": "≥5 Rate %",
    "累计 20 句": "Cumulative 20 Msgs", "累计≥20句": "Cumulative ≥20",
    "累计≥6句": "Cumulative ≥6", "聊到10条 %": "Reached 10 Msgs %",
    "聊到30条 %": "Reached 30 Msgs %", "聊深率 %": "Deep Chat %",
    "装机→20句": "Install → 20 Msgs", "装机→发消息": "Install → First Msg",
    "达成 QCD (6句)": "QCD Reached (6 msgs)", "首日≥5条 %": "Day-0 ≥5 Msgs %",
    "碰到每日额度 ≥100": "Hit Daily Cap ≥100",
    # 搜索结果档
    "1-20 结果": "1-20 Results", "21-399 结果": "21-399 Results", "400+ 结果": "400+ Results",
    # 时延
    "ASR 中位(秒)": "ASR Median (s)", "ASR后等待 中位(秒)": "Wait After ASR, Median (s)",
    "首个音频 中位(秒)": "First Audio, Median (s)", ">10 秒 %": ">10s %",
    "其中3秒内 <3s": "of which Within 3s",
    # 留存
    "D1 回同一角色": "D1 Same Host", "D1 回访 D1": "D1 Return", "D1 回访率": "D1 Return Rate",
    "D1率 %": "D1 %", "D7窗 回同一角色": "D7 Same Host", "D7窗 回访率 (5–9d)": "D7 Return Rate (5–9d)",
    "有效D1 %": "Effective D1 %", "次日发消息 D1": "D1 Messaged", "次日回来 D1": "D1 Returned",
    "回来率 %": "Return Rate %", "回访率 %": "Revisit Rate %", "第7天还在聊 %": "Still Chatting on D7 %",
    # 付费
    "3天通行证 Pass(笔)": "3-Day Pass (txns)", "能量包 Energy(笔)": "Energy Pack (txns)",
    "其中 0.99 收入": "of which $0.99", "其中 全价收入": "of which Full Price",
    "占总收入 %": "% of Revenue", "占买过的人 %": "% of Buyers", "又买比例 %": "Repeat Purchase %",
    "用完后买 %": "Bought After Run-out %", "首购率 %": "First Purchase %", "续费率 %": "Renewal %",
    "点订阅 %": "Tapped Subscribe %", "看到墙 %": "Saw Paywall %",
    "老商品新开 New (目标0)": "New on Old SKU (target 0)",
    "毛利率 %": "Margin %", "毛利率(D-594)%": "Margin % (D-594)", "毛利率(现价)%": "Margin % (current)",
    # 失败 / 质量
    "其中 其他错误": "of which Other Errors", "其中 用户取消": "of which User Cancel",
    "取消占失败 %": "Cancel % of Failures", "无效 %": "Invalid %", "空回复率 %": "Empty Reply %",
    "漏回率 %": "Miss Rate %", "错配率 %": "Mismatch %", "兜底率 %": "Fallback %",
    # 实验
    "实验 %": "Treatment %", "实验 分子 k": "Treatment k", "实验 分母 n": "Treatment n",
    "对照 %": "Control %", "对照 分子 k": "Control k", "对照 分母 n": "Control n",
    # 归因 / 覆盖
    "其中事后回填 %": "of which Backfilled %", "有归因率 %": "Attributed %",
    "设备口径覆盖率 %": "Device-Level Coverage %", "账号口径覆盖率 %": "Account-Level Coverage %",
    "回写率 %": "Writeback %",
    # 漏斗 / 转化
    "占上一步 %": "% of Previous Step", "曝光→发起": "Impression → Start",
    "打开→选角色 %": "Open → Pick Host %", "建号率 %": "Account Created %",
    "开口率 %": "First Msg %", "成功率 %": "Success %", "正常启动率 %": "Normal Launch %",
    # 2026-11-23 新增:结账两张卡(Metabase 477 / 478)
    "到账率 %": "Credited %", "取消率 %": "Cancel %",
    "推进率 %": "Advance %", "投入率 %": "Engaged %", "入戏率 %": "In-Character %",
    "接受率 %": "Accept %", "发放率 %": "Grant %", "实发率 %": "Actual Grant %",
    "落地率(全部)%": "Landing % (all)", "落地率(说过话的)%": "Landing % (spoke)",
    "点开率(7天滚动)%": "Open Rate % (7d rolling)", "回复率": "Reply Rate",
    "没说话就退 %": "Left Without Speaking %", "关掉率 %": "Dismiss %",
    "聊过天 %": "Chatted %", "社区占比 %": "Community Share %", "组内占比 %": "Share within Group %",
    "占比 %": "Share %", "语音消息占比 %": "Voice Msg Share %", "语音用户占比 %": "Voice User Share %",
    "人均影子消耗": "Shadow Spend per User",
}


def split_title(text: str):
    """区名 / 卡名:「中文 · English」

    🛑 用 rsplit 取**最后一个** ' · ' —— 有的卡名本身带一个中文的 ' · ',
       例如「按装机日明细 · Meta 素材全链路 · Meta Funnel by Install Date」,
       按第一个拆会把「Meta 素材全链路」留在英文侧,切到英文时那里仍显示中文。"""
    if " · " in text:
        zh, en = text.rsplit(" · ", 1)
        return zh.strip(), en.strip()
    return text, None


def split_note(text: str):
    """note:「中文 ｜ English」"""
    for sep in (" ｜ ", "｜"):
        if sep in text:
            zh, en = text.split(sep, 1)
            return zh.strip(), en.strip()
    return text, None


def split_column(text: str):
    """列名 / 维度名:「中文 English」,没有分隔符。
    规则:最后一个中文字(或中文标点)之后的部分是英文。两张手工表优先。"""
    t = (text or "").strip()
    if not t:
        return t, None
    if t in COLUMN_FIX:
        return COLUMN_FIX[t]
    if t in COLUMN_EN:
        return t, COLUMN_EN[t]
    if not re.search(rf"[{CJK}]", t):      # 本来就是纯英文,中英一样
        return t, None
    idxs = [i for i, ch in enumerate(t) if re.match(rf"[{_BOUND}]", ch)]
    if not idxs:
        return t, None
    last = max(idxs)
    zh, en = t[: last + 1].strip(), t[last + 1 :].strip()
    en = en.lstrip("·|｜/ ").strip()
    # 箭头和半角标点归还中文侧:「装机→QCD」不该被拆成「装机」+「→QCD」
    lead = re.match(r"^[?？!！%()（）\[\]:：,，.。→←↑↓\-–—\s]+", en)
    if lead:                                # 半角标点归还中文侧
        zh, en = (zh + lead.group(0)).strip(), en[lead.end():].strip()
    if not en or not re.search(r"[A-Za-z]{2,}", en):
        return t, None
    return zh, en


def build(sections) -> dict:
    """遍历渲染好的 sections,产出「页面上的中文原文 → English」对照表。"""
    table: dict[str, str] = {}

    def put(zh, en):
        if zh and en and zh != en:
            table[zh] = en

    for sec in sections:
        put(*split_title(sec.get("title", "")))
        for card in sec.get("cards", []):
            put(*split_title(card.get("title", "")))
            if card.get("note"):
                put(*split_note(card["note"]))
            for col in card.get("cols", []) or []:
                if isinstance(col, dict):
                    put(*split_column(col.get("label", "")))
            for dim in card.get("dims", []) or []:
                if isinstance(dim, dict):
                    put(*split_column(dim.get("label", "")))
    # 2026-11-25:按页面原文精确兜的那批(列名英文侧以数字开头的、单元格里的枚举值)
    table.update(EXACT_EN)
    return table


# ---------- 整块替换:页头 / Movers / Changelog 这类拼好的 HTML ----------
# 卡片那套是按文本节点查表替换,但页头这些块里有 <b> 标签和 {} 插值,
# 拆成文本节点后既碎又翻不准。这里改成整块换 innerHTML:
#   bi("中文 <b>带标签</b>", "English <b>with tags</b>")
# 产出 <span class="i18n-swap" data-en="...">中文</span>,切换时整块换掉。
import html as _html


def bi(zh_html: str, en_html: str) -> str:
    return (f'<span class="i18n-swap" data-en="{_html.escape(en_html, quote=True)}">'
            f'{zh_html}</span>')


# ---------- 切换按钮的样式与脚本(主看板和能量实验页共用)----------
CSS = """
#langToggle{position:fixed;top:12px;right:14px;z-index:99;cursor:pointer;
  padding:6px 14px;border-radius:999px;border:1px solid var(--bd,#d0d5dd);
  background:var(--surface,#fff);color:var(--tp,#222);font:600 13px/1 system-ui,sans-serif}
#langToggle:hover{border-color:#8a94a6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark}}
:root[data-theme=dark]{color-scheme:dark}
"""

BUTTON = '<button id="langToggle" type="button">EN</button>'

JS = r"""
// ---------- 中英切换 ----------
// 同一份 DOM 换文本:I18N 是「页面上的中文原文 → English」,逐个文本节点查表替换。
// 🛑 每个文本节点第一次处理时把原文存进 __zh —— 不存的话切回中文就没有原文可还原。
// 🛑 图表切维度 / 表格展开会重建 DOM,新节点没经过替换,所以要用 MutationObserver 补。
(function () {
  if (typeof I18N === 'undefined') return;
  let lang = localStorage.getItem('smDashLang') || 'zh';
  let applying = false;

  // 带数字的文案登记不进 I18N(数字每天在变),用正则兜。
  // 2026-11-25:英文模式要「尽量只有英文」。页面上大量文案是中英并排的一整串
  //   (卡名「中文 · English」· note「中文 ｜ English」· 列名「中文 English」),
  //   它们在 I18N 里的 key 只是中文那半,整串查不到表 ⇒ 切到英文仍然两边都显示。
  //   下面按格式把英文那半切出来。🛑 三条规则的顺序不能换:
  //   note 必须排在卡名前面(note 的英文半边里也可能出现 ' · ',会被卡名规则截断)。
  const CJ  = '\\u4e00-\\u9fff\\u3000-\\u303f\\uff00-\\uffef';   // 中文 + 中文标点
  const NM  = '\\u24ea\\u2460-\\u24ff';                            // ⓪ 和 ①-⑳,要保留
  const GAP = '[\\s)\\]）】」》\\?？!！%、,，\\.。:：/]*';            // 中英之间允许夹的东西
  const EN2 = '[^' + CJ + ']*[A-Za-z]{2,}[^' + CJ + ']*';       // 英文半边(可以数字开头)
  const ENL = '[A-Za-z][^' + CJ + ']*';                         // 英文半边(必须字母开头)
  const PATTERNS = [
    [/^展开全部 (\d+) 行 ↓$/,        m => 'Show all ' + m[1] + ' rows ↓'],
    [/^收起 · 只看前 (\d+) 行$/,      m => 'Collapse to first ' + m[1] + ' rows'],
    [/^最新 (.+)$/,                  m => 'Latest ' + m[1]],
    // 单元格里带数字的几种,先于下面三条
    [/^(.+) USD \/ (.+) 能量$/,       m => m[1] + ' USD / ' + m[2] + ' Energy'],
    [/^第 (\d+) 天$/,                m => 'Day ' + m[1]],
    [/^第 (\d+) 次$/,                m => 'Purchase ' + m[1]],
    [/^第 (\d+) 次及以后$/,           m => 'Purchase ' + m[1] + '+'],
    [/^到账 (.+) 能量$/,              m => 'Granted ' + m[1] + ' Energy'],
    // note:「中文 ｜ English」—— 必须排在卡名规则前面
    [new RegExp('^(.+?)\\s*｜\\s*(' + EN2 + ')$'),
       m => m[2].trim()],
    // 区名 / 卡名:「中文 · English」,英文侧不含中文(所以 'A · 主动取消挽回' 不会被误切)
    [new RegExp('^([' + NM + '\\s]*)(.+) · (' + EN2 + ')$'),
       m => (m[1] + m[3]).trim()],
    // 列名 / 维度名:「中文English」,英文侧必须字母开头
    //   🛑 中英之间不许夹下划线 —— 否则广告素材名 'SoulMap_..._想象_career (1202…)'
    //      会被切成 '_career (1202…)',那是标识符,翻了就和 Meta 导出对不上。
    [new RegExp('^([' + NM + '\\s]*)(.*[' + CJ + '])' + GAP + '(' + ENL + ')$'),
       m => (/[A-Za-z]{2,}/.test(m[3]) ? (m[1] + m[3]).trim() : null)],
  ];

  function translate(zh) {
    const hit = I18N[zh];
    if (hit) return hit;
    for (const [re, fn] of PATTERNS) { const m = re.exec(zh); if (m) return fn(m); }
    return null;
  }

  function apply() {
    applying = true;
    // ① 整块替换:页头 / Movers / Changelog 这类带标签的块
    document.querySelectorAll('.i18n-swap').forEach(function (el) {
      if (el.__zhHtml === undefined) el.__zhHtml = el.innerHTML;
      const want = (lang === 'en' && el.dataset.en) ? el.dataset.en : el.__zhHtml;
      if (el.innerHTML !== want) el.innerHTML = want;
    });
    // ② 文本节点替换:卡名 / 列名 / note
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      // 整块替换管辖的区域跳过,免得两套机制互相覆盖
      if (node.parentElement && node.parentElement.closest('.i18n-swap')) continue;
      if (node.__zh === undefined) node.__zh = node.nodeValue;
      const en = translate(node.__zh);
      const want = (lang === 'en' && en) ? en : node.__zh;
      if (node.nodeValue !== want) node.nodeValue = want;
    }
    document.documentElement.lang = (lang === 'en') ? 'en' : 'zh';
    const btn = document.getElementById('langToggle');
    if (btn) btn.textContent = (lang === 'en') ? '中文' : 'EN';
    applying = false;
  }

  function init() {
    const btn = document.getElementById('langToggle');
    if (btn) btn.addEventListener('click', function () {
      lang = (lang === 'en') ? 'zh' : 'en';
      localStorage.setItem('smDashLang', lang);
      apply();
    });
    apply();
    const root = document.getElementById('root');
    if (root) new MutationObserver(function () { if (!applying) apply(); })
      .observe(root, { childList: true, subtree: true });
  }

  // 脚本在正文之后,DOMContentLoaded 可能已经过了 —— 只挂监听会一次都不执行。
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
"""


# ---------- Changelog 里的团队名与状态 ----------
_TEAM = {"服务端": "Server", "客户端": "Client", "算法": "Algo", "投放": "Marketing", "数据": "Data"}
_STATUS = {
    "已生效": "Live",
    "表结构已改 · 写入逻辑未上线": "Schema changed · writes not shipped",
    "代码完成 · 生产未启用": "Code done · not enabled",
    "开关关着": "Switch off",
}


def team_en(team: str) -> str:
    return bi(team, _TEAM.get(team, team))


def status_en(status: str) -> str:
    """状态文案种类不多,表里没有的原样显示(不硬翻,免得翻错)。"""
    return bi(status, _STATUS.get(status, status))


# ---------- Changelog 每条改动的英文 ----------
# key 是 CHANGELOG 里 what 字段的原文(含 <b>/<code> 标签),要逐字一致。
# 🛑 只需要覆盖**最近 CHANGELOG_DAYS 天**会显示的那些;更早的条目页头不再渲染,
#    表里没有的原样显示中文,不会报错。加新改动时顺手补一条,别留到以后补。
# 🔴 2026-11-19 起为空:changelog 的英文改从 Lark「事项(EN)」列来,
#    render_dashboard._load_changes() 启动时回填进来。不要再往这里写。
CHANGELOG_EN = {}


def changelog_en(what: str) -> str:
    return bi(what, CHANGELOG_EN.get(what, what))


# ---------- 切点描述(CUTOVERS)的英文 ----------
# 显示在 Movers 行末的 ⚠ 提示里。key 是 CUTOVERS 的值,要逐字一致。
# 🛑 这些文本是**直接拼进 HTML** 的,原文里的 `**粗体**` 会显示成字面星号 ——
#    cutover_html() 渲染时统一转成 <b>,所以 CUTOVERS 原文不用动。
# 🔴 2026-11-19 起为空:切点的英文改从 Lark 来 ——
#    新切点写「数据表」的「事项(EN)」列,历史切点写「soulmap详细记录」的
#    「切点说明(EN)」列,render_dashboard._load_changes() 启动时回填。
CUTOVERS_EN = {}


def cutover_html(zh: str) -> str:
    """切点描述:配英文,并把原文里的 **粗体** 转成 <b>(这些文本直接拼进 HTML)。"""
    bold = lambda t: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return bi(bold(zh), bold(CUTOVERS_EN.get(zh, zh)))
