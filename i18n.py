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
    "延迟最大(分) max":             ("延迟最大(分)", "Max Delay (min)"),
    "延迟中位(分) p50":             ("延迟中位(分)", "Median Delay (min)"),
    "占能量用户 % of Energy":        ("占能量用户 %", "% of Energy Users"),
    "到期时刻(SGT)":                ("到期时刻(SGT)", "Expiry (SGT)"),
    "首购时刻(SGT)":                ("首购时刻(SGT)", "First Purchase (SGT)"),
    "读得出? Readable":            ("读得出?", "Readable"),
    "阿语模板残留 AR /ة":            ("阿语模板残留", "Arabic Template Left"),
    "每条收入(现价)Rev/Msg $":       ("每条收入(现价)", "Revenue / Msg $"),
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
  const PATTERNS = [
    [/^展开全部 (\d+) 行 ↓$/,        m => 'Show all ' + m[1] + ' rows ↓'],
    [/^收起 · 只看前 (\d+) 行$/,      m => 'Collapse to first ' + m[1] + ' rows'],
    [/^最新 (.+)$/,                  m => 'Latest ' + m[1]],
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
# 🔴 与 CUTOVERS 一样冻结在 2026-11-19 —— 新切点的英文写 Lark「事项(EN)」列。
CUTOVERS_EN = {
    "埋点侧缺这一天(服务端不缺);画趋势留空,不补零不插值":
        "Client telemetry is missing this day (server data is not); the trend is left blank, "
        "neither zero-filled nor interpolated",
    "印度启动墙上线(18:37)": "Launch wall went live in India (18:37)",
    "全球免费额度 10 → 20(印度 A 类 30)":
        "Global free allowance 10 → 20 (30 for Type A in India)",
    "印度以外的 A 类额度也放到 30;first_message_gate 上线(16:16);「买 3 天」通行证开始有真实购买——它和月订阅共用 purchase_* 事件,付费口径从这天起必须按 product_id 限定":
        "Type A allowance raised to 30 outside India too; first_message_gate shipped (16:16); the 3-day "
        "pass started getting real purchases — it shares the purchase_* events with the monthly "
        "subscription, so from this day on any payment metric must be filtered by product_id",
    "AN 渠道关停(18:30)—— 装机分母清理,整体数会跳,不是产品变好":
        "The AN channel was shut off (18:30) — this cleans up the install denominator, so overall "
        "numbers jump; the product did not get better",
    "能量系统全球放开(14:21,10-26 18:25 起印度已开);14:32:20 第一笔能量入账;同日 14:21 Type B 回复变快(4~7秒→约2秒)、16:46 Type A 变慢(6.3→10.5秒),两类反向动,混着看会互相抵消;18:22 搜索全量重排不留对照组":
        "Energy opened globally (14:21; India had it from 10-26 18:25); first Energy credited at "
        "14:32:20. The same day Type B replies got faster (4–7s → about 2s) at 14:21 and Type A got "
        "slower (6.3 → 10.5s) at 16:46 — the two move in opposite directions and cancel out if read "
        "together. At 18:22 search was fully re-ranked with no control group",
    "12:14 能量改价 聊天 2→4、免费能量翻倍(之前的能量数 ÷2 才能和之后比);13:13 App 3.9.0 上线;18:11 SoulMap_TypeA_ 判 A 类、被邀请人 120→60;18:26 SoulMap_TypeB_ 判 B 类":
        "12:14 Energy repriced: chat 2 → 4 and free Energy doubled (earlier Energy counts must be "
        "halved to compare with later ones); 13:13 App 3.9.0 shipped; 18:11 SoulMap_TypeA_ became the "
        "Type A marker and invitee rewards went 120 → 60; 18:26 SoulMap_TypeB_ became the Type B marker",
    "11:57「研究」模式从入口移除,入口只剩想象/分忧/练习;11:27 Type B 三语统一到 G62Z;15:13 英语提示词改可缓存(成本降,质量无差别)":
        "11:57 the Research mode was removed from the entry, leaving Imagine / Vent / Practice; 11:27 "
        "Type B unified on G62Z across three languages; 15:13 the English prompt became cacheable "
        "(lower cost, no quality difference)",
    "投放侧:Meta 开始收到 purchase 回传(此前「Meta 应用内购买」列全是 0);🛑 Meta 收到的只有服务端实际成交的一半左右(它看到 3~6 笔/天,服务端实际 9~13 笔)—— 学习期门槛是按它看到的那一半算的":
        "Marketing: Meta began receiving purchase postbacks (the in-app purchase column had been all "
        "zeros). 🛑 Meta sees only about half of what the server actually bills (3–6 a day versus 9–13 "
        "on the server) — the learning-phase threshold is counted against that half",
    "🛑 投放侧:Meta 优化目标 install -> purchase 的切换**从这天开始**,不是一次性 —— TypeB_F_Lucien / TypeB_F_Kabir 当天先切;TypeA_M_Divya 当天两种结果都报(347 install + 1 purchase)说明中途切。旧结构(A 类 mobile_app_install / B 类 subscribe_mobile_app)从这天起消失":
        "🛑 Marketing: the move of Meta's optimisation goal from install to purchase **started** on this "
        "day and was not a single switch — TypeB_F_Lucien and TypeB_F_Kabir moved first; TypeA_M_Divya "
        "reported both kinds that day (347 installs + 1 purchase), meaning it switched mid-day. The old "
        "structure (mobile_app_install for Type A, subscribe_mobile_app for Type B) disappears from here",
    "投放侧:切换进行中(Divya 退回只报 install、Sander 仍 install)。装机 630 -> 172、CPI 0.195 -> 0.605。🛑 这是改优化目标的定义性后果,不是投放效率崩了":
        "Marketing: switch still in progress (Divya fell back to install only, Sander still on install). "
        "Installs 630 → 172, CPI 0.195 → 0.605. 🛑 That is the definitional consequence of changing the "
        "optimisation goal, not a collapse in efficiency",
    "投放侧:TypeA_F_Sander 与 TypeB_M_Yui 切过来。装机 75(最低)、CPI 1.051。按注册日队列的 D0 付费率已回到 1.65%":
        "Marketing: TypeA_F_Sander and TypeB_M_Yui moved over. Installs 75 (the lowest), CPI 1.051. "
        "D0 payment rate by signup-day cohort is back to 1.65%",
    "🛑 投放侧:五个系列**第一次全部是 purchase**,切换完成(11-02 起历时四天)。CPI 1.228;但 D0 付费率 3.97%,连续四天上升(0.67 -> 0.78 -> 1.65 -> 3.97),已超放量前的 1.6~2.0%。⇒ 跨 11-02~11-05 这段不能比装机 / CPI / 新注册 / 按注册日的队列指标;能比成交笔数 / 每笔成交成本 / 每日毛额。首个成熟 D7 队列要到 11-12。另:安卓 3.9.3 也在 11-05 01:58 过审放量(当日占 59.7%,11-06 到 88.5%),**两件事叠在同一天**,归因时要分开":
        "🛑 Marketing: all five campaigns are on purchase **for the first time**; the switch is complete "
        "(four days from 11-02). CPI 1.228, but the D0 payment rate is 3.97% after rising four days "
        "running (0.67 → 0.78 → 1.65 → 3.97), above the 1.6–2.0% from before the scale-up. ⇒ Across "
        "11-02 to 11-05 do not compare installs, CPI, signups or signup-day cohort metrics; purchases, "
        "cost per purchase and daily gross are comparable. The first mature D7 cohort lands 11-12. Also "
        "Android 3.9.3 was approved and rolled out at 11-05 01:58 (59.7% share that day, 88.5% by "
        "11-06) — **two things fall on the same day**, so separate them when attributing",
}


def cutover_html(zh: str) -> str:
    """切点描述:配英文,并把原文里的 **粗体** 转成 <b>(这些文本直接拼进 HTML)。"""
    bold = lambda t: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return bi(bold(zh), bold(CUTOVERS_EN.get(zh, zh)))
