#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能量定价实验看板 · Energy Pricing A/B dashboard

Javier《修改后的能量定价计划》(2026-11-18)第 6 节「看板(Chris)」要的那一页:
  · 独立于主看板的一页 —— 数据源是 Metabase 看板 **25**,抓数走单独一轮,
    和主看板的 18/24 完全隔离(混进去会让主看板页头的「变化最大的 5 个数」算进实验卡)。
  · **带中英切换** —— Javier 看英文。切换不是两份页面,是同一份 DOM 换文本:
    Python 侧把每条文案登记成「中文 → English」对照表塞进页面,
    JS 侧遍历文本节点按表替换,配合 MutationObserver 在图表重绘后重新应用。
    这样不用改 render_dashboard.py 的 APP_JS,主看板一行都不受影响。

用法:
  python3 fetch_metabase.py --dashboard-ids 25 --out raw_energy_ab.json
  python3 render_energy_ab.py --raw raw_energy_ab.json --out site/energy-ab.html

🛑 加卡:先在 Metabase 看板 25 建卡 → fetch_metabase.py 的 KEY_OVERRIDE 加一行 →
   这里的 SECTIONS 加一行。三处漏一处那张卡会静默不显示。
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import render_dashboard as RD

HERE = Path(__file__).resolve().parent

# ---------- 中英对照表 ----------
# T("中文", "English") 登记一条并返回中文。页面默认中文,点 EN 时整页按这张表换文本。
# 🛑 同一句中文只能有一个英文译法 —— 表是按中文原文做 key 的,重复登记后一个会覆盖前一个。
I18N: dict[str, str] = {}


def T(zh: str, en: str) -> str:
    I18N[zh] = en
    return zh


# ---------- 注册表 ----------
# 和主看板同一套 build_card:("metric_id", "标题", "table", dict(top=, cols=[(列, 列名, 格式)], note=))
# 格式:text 原样 · int 整数 · d1/d4/d6 固定小数位(百分比列一律用 d1 并把 % 写进列名)
SECTIONS = [
 (T("① 分组是否均衡 · Are the arms balanced", "① Are the arms balanced"), [
   ("energy_ab_arms", T("分组概况 · Arms Overview", "Arms Overview"), "table",
     dict(top=10,
          cols=[("arm", T("组 Arm", "Arm"), "text"),
                ("users_assigned", T("人数 Users", "Users"), "int"),
                ("first_signup_date", T("最早注册 First Signup", "First signup"), "text"),
                ("last_signup_date", T("最晚注册 Last Signup", "Last signup"), "text"),
                ("countries", T("国家数 Countries", "Countries"), "int"),
                ("users_who_chatted", T("聊过天 Chatted", "Chatted"), "int"),
                ("chatted_pct", T("聊过天 %", "Chatted %"), "d1"),
                ("messages_per_user", T("人均消息 Msgs/User", "Msgs / user"), "d1"),
                ("energy_spent_per_user", T("人均耗能量 Energy/User", "Energy / user"), "d1")],
          bar=["users_assigned", "messages_per_user"],
          note=T("分母是实验开始后注册的新用户,已排掉 CityPLX 的游戏账号。先看两组人数差多少,"
                 "50/50 分组下相差超过 5% 说明分组偏了,后面几张卡的对比都不成立。"
                 "实验开始前所有人显示在 unassigned 一行。",
                 "New users who signed up after the start, excluding CityPLX accounts. "
                 "A headcount gap above 5% under a 50/50 split means the split is skewed."))),
 ]),
 (T("② 钱 · Money", "② Money"), [
   ("energy_ab_net_revenue", T("主指标:每新用户 14 天净收入 · Net Revenue per User (14d)",
                               "Main metric — net revenue per new user (14d)"), "table",
     dict(top=10,
          cols=[("arm", T("组 Arm", "Arm"), "text"),
                ("cohort_maturity", T("队列成熟度 Maturity", "Cohort maturity"), "text"),
                ("users", T("人数 Users", "Users"), "int"),
                ("takehome_usd", T("到手 Takehome $", "Takehome $"), "d2"),
                ("cost_usd", T("服务成本 Cost $", "Serving cost $"), "d2"),
                ("net_usd", T("净额 Net $", "Net $"), "d2"),
                ("net_usd_per_user_capped50", T("人均净额 封顶 Net/User capped", "Net / user (capped $50)"), "d4"),
                ("net_usd_per_user", T("人均净额 不封顶 Net/User uncapped", "Net / user (uncapped)"), "d4"),
                ("buyers", T("买过的人 Buyers", "Buyers"), "int")],
          bar=["users", "net_usd_per_user_capped50"],
          note=T("分母是注册满 14 天的新用户,判定用封顶 50 美元那一列。成本从 11-06 中午才记齐,"
                 "第一个完整的 14 天队列要到 11-20 才出现,在那之前只有 7 天那一列能读。"
                 "净额不含广告花费。",
                 "New users whose first 14 days are complete. The decision uses the capped column. "
                 "Cost logging is complete only from 11-06, so read the 7-day column until 11-20."))),
   ("energy_ab_purchase", T("首购与再购 · Purchase Funnel", "Purchase funnel"), "table",
     dict(top=10,
          cols=[("arm", T("组 Arm", "Arm"), "text"),
                ("users_total", T("人数 Users", "Users"), "int"),
                ("buyers", T("买过 Buyers", "Buyers"), "int"),
                ("first_purchase_pct", T("首购率 %", "First-purchase %"), "d2"),
                ("hit_first_runout", T("用完过额度 Ran Out", "Ran out"), "int"),
                ("bought_after_runout", T("用完后买 Bought After", "Bought after"), "int"),
                ("bought_after_runout_pct", T("用完后买 %", "Bought after %"), "d2"),
                ("repeat_buyers", T("又买过 Repeat", "Repeat buyers"), "int"),
                ("repeat_purchase_pct", T("又买比例 %", "Repeat %"), "d2")],
          bar=["buyers", "first_purchase_pct"],
          note=T("分母是实验期注册的新用户。买的定义是服务端有金额的成交记录,订单表的金额和国家列是空的,"
                 "用不了。又买比例的分母是买过的人,不是全部用户。用完后买这一列分子只有 12,现在读不出。",
                 "Denominator is new users in the experiment window. Purchases come from the "
                 "server-side billing log. The repeat rate is over buyers, not over all users."))),
   ("energy_ab_margin_band", T("按条数分段的每条毛利 · Margin by Message Number",
                               "Margin by message number"), "table",
     dict(top=20,
          cols=[("arm", T("组 Arm", "Arm"), "text"),
                ("message_band", T("第几条 Message No.", "Message no."), "text"),
                ("messages", T("消息数 Messages", "Messages"), "int"),
                ("users", T("人数 Users", "Users"), "int"),
                ("cost_per_message_usd", T("每条成本 Cost/Msg $", "Cost / msg $"), "d6"),
                ("revenue_per_message_now_usd", T("每条收入(现价)Rev/Msg $", "Revenue / msg $ (now)"), "d6"),
                ("margin_pct_now", T("毛利率(现价)%", "Margin % (now)"), "d1"),
                ("avg_energy_if_d594", T("D-594 每条能量 Energy", "Energy / msg under D-594"), "d2"),
                ("margin_pct_if_d594", T("毛利率(D-594)%", "Margin % under D-594"), "d1")],
          bar=["messages", "margin_pct_now"],
          note=T("一行一个条数档,分母是该档内的消息数。聊得越久每条成本越高,毛利率从前 10 条的 39% "
                 "降到第 101 条以后的 4.5%。右边两列是静态模拟,同样这批消息按 D-594 曲线会收多少能量,"
                 "它假设用户行为不变,而涨价本身会让人少聊,不能当成改价后的预期收入。",
                 "One row per message band. The right-hand columns simulate the D-594 curve on the "
                 "same messages, assuming behaviour does not change."))),
   ("energy_ab_country", T("分国家每能量到手 · Revenue per Energy by Country",
                           "Revenue per energy by country"), "table",
     dict(top=25,
          cols=[("country_code", T("国家 Country", "Country"), "text"),
                ("arm", T("组 Arm", "Arm"), "text"),
                ("users", T("人数 Users", "Users"), "int"),
                ("buyers", T("买过 Buyers", "Buyers"), "int"),
                ("energy_consumed", T("消耗能量 Energy", "Energy spent"), "int"),
                ("takehome_usd", T("到手 Takehome $", "Takehome $"), "d2"),
                ("takehome_usd_per_energy", T("每能量到手 $/Energy", "$ per energy"), "d6"),
                ("numerator_over_denominator", T("分子/分母 Numerator", "Numerator / denominator"), "text"),
                ("net_usd", T("净额 Net $", "Net $"), "d2")],
          bar=["energy_consumed", "takehome_usd_per_energy"],
          note=T("一行一个国家,国家取注册国家不是商店国家。每能量到手等于该国到手收入除以该国消耗的能量,"
                 "同样 1 能量印度值 0.0053 美元、美国 0.0031、英国 0.0023。消耗不足 100 能量的标读不出,"
                 "净额不含广告花费。",
                 "One row per signup country. Revenue per energy is that country's takehome divided by "
                 "its energy spent. Under 100 energy spent is marked unreadable."))),
 ]),
 (T("③ 用户还聊不聊 · Do they keep chatting", "③ Do they keep chatting"), [
   ("energy_ab_engagement", T("参与度与留存 · Engagement & Retention", "Engagement & retention"), "table",
     dict(top=10,
          cols=[("arm", T("组 Arm", "Arm"), "text"),
                ("users_total", T("人数 Users", "Users"), "int"),
                ("sent_1_plus", T("发过消息 Sent ≥1", "Sent ≥1"), "int"),
                ("sent_10_plus_pct", T("聊到10条 %", "Reached 10 msgs %"), "d1"),
                ("sent_30_plus_pct", T("聊到30条 %", "Reached 30 msgs %"), "d1"),
                ("messages_per_user", T("人均消息 Msgs/User", "Msgs / user"), "d1"),
                ("active_days_per_chatter", T("活跃天数 Active Days", "Active days"), "d2"),
                ("day7_denominator", T("第7天分母 D7 Denom", "D7 denominator"), "int"),
                ("still_messaging_day7_pct", T("第7天还在聊 %", "Still chatting on D7 %"), "d1")],
          bar=["users_total", "sent_30_plus_pct"],
          note=T("分母是实验期注册的新用户。第 7 天这一列按账号算,口径是注册后第 7 天还在发消息,"
                 "和主看板那张按设备算的留存卡不是一回事,两边的数不要互相对。"
                 "人均活跃天数只有 1.3 天,多数新用户只来一天,第 7 天的数低是这个结构决定的。",
                 "Day 7 here counts accounts still sending messages, not devices. It is a different "
                 "definition from the main dashboard's retention card."))),
   ("energy_ab_conversation_length", T("对话长度与第30条附近换角色 · Conversation Length",
                                       "Conversation length & switching"), "table",
     dict(top=20,
          cols=[("arm", T("组 Arm", "Arm"), "text"),
                ("final_length_band", T("最终聊了多少条 Final Length", "Final length"), "text"),
                ("conversations", T("对话数 Conversations", "Conversations"), "int"),
                ("pct_of_conversations", T("占比 %", "Share %"), "d1"),
                ("users", T("人数 Users", "Users"), "int")],
          bar=["conversations", "pct_of_conversations"],
          note=T("一行一个档位,分母是对话数不是人数,一个人可以有多个角色对话。免费额度正好 30 条,"
                 "所以 26 到 30 这一档本来就偏高;D-594 的涨价点也在第 30 条,两件事落在同一条消息上,"
                 "单看一组分不清堆积是哪一件造成的,只能比两组在同一档的占比差。",
                 "One row per final-length band; the denominator is conversations, not people. "
                 "The free allowance and the D-594 price step both fall on message 30."))),
 ]),
 (T("④ 成本与大客户 · Cost and top users", "④ Cost and top users"), [
   ("energy_voice_per_charge", T("语音生成 ÷ 扣费 · Voice Generations per Charge",
                                 "Voice generations per charge"), "table",
     dict(top=30,
          cols=[("activity_date", T("日期 Date", "Date"), "text"),
                ("voice_kind", T("类型 Kind", "Kind"), "text"),
                ("shadow_charges", T("生成时记账 Shadow", "Logged at generation"), "int"),
                ("energy_charges", T("实际扣费 Charged", "Actually charged"), "int"),
                ("vendor_calls", T("厂商调用 Vendor Calls", "Vendor calls"), "int"),
                ("vendor_calls_per_charge", T("每次扣费几次生成 Ratio", "Generations per charge"), "d2"),
                ("numerator_over_denominator", T("分子/分母 Numerator", "Numerator / denominator"), "text"),
                ("vendor_cost_usd", T("厂商成本 Cost $", "Vendor cost $"), "d2")],
          bar=["vendor_calls", "vendor_calls_per_charge"],
          note=T("一行一天,分母是当天的扣费次数。生成时记账和厂商调用两列几乎逐日相等,"
                 "而实际扣费比它们低四成,说明语音在检查能量之前就已经生成了。"
                 "11-13 之前老 Plus 用户不扣费,分母接近 0,那几天的比值读不出。",
                 "One row per day; the denominator is that day's charges. Generations run about 40% "
                 "above charges, so audio is produced before the energy check."))),
   ("energy_company_margin", T("全公司逐日毛利 · Company Margin Daily", "Company margin, daily"), "table",
     dict(top=21,
          cols=[("activity_date", T("日期 Date", "Date"), "text"),
                ("purchases", T("成交笔数 Purchases", "Purchases"), "int"),
                ("paying_users", T("付费人数 Payers", "Paying users"), "int"),
                ("takehome_usd", T("到手 Takehome $", "Takehome $"), "d2"),
                ("cost_chat_usd", T("聊天成本 Chat $", "Chat cost $"), "d2"),
                ("cost_voice_usd", T("语音成本 Voice $", "Voice cost $"), "d2"),
                ("cost_usd", T("成本合计 Cost $", "Total cost $"), "d2"),
                ("margin_usd", T("毛利 Margin $", "Margin $"), "d2"),
                ("margin_pct", T("毛利率 %", "Margin %"), "d1")],
          bar=["takehome_usd", "margin_usd"],
          note=T("一行一天。毛利等于到手收入减服务成本,不含广告花费和人力。成本从 11-06 中午起才记齐,"
                 "更早的日子毛利率会偏高。当天没有成交也照样出一行,跳过会让趋势看起来比实际好。",
                 "One row per day. Margin is takehome less serving cost, excluding ad spend. "
                 "Days with no sales still get a row."))),
   ("energy_top_spenders", T("大客户与取消 · Top Spenders & Cancellations",
                             "Top spenders & cancellations"), "table",
     dict(top=20,
          cols=[("spend_rank", T("排名 Rank", "Rank"), "int"),
                ("user_id", T("用户 User", "User"), "text"),
                ("country_code", T("国家 Country", "Country"), "text"),
                ("purchases", T("成交笔数 Purchases", "Purchases"), "int"),
                ("takehome_usd", T("到手 Takehome $", "Takehome $"), "d2"),
                ("pct_of_all_takehome", T("占总收入 %", "Share of revenue %"), "d1"),
                ("cost_usd", T("服务成本 Cost $", "Serving cost $"), "d2"),
                ("net_usd", T("净额 Net $", "Net $"), "d2"),
                ("user_messages", T("消息数 Messages", "Messages"), "int"),
                ("last_message_date", T("最后一次聊 Last Chat", "Last chat"), "text"),
                ("cancellations", T("取消续费 Cancellations", "Cancellations"), "int")],
          bar=["takehome_usd", "net_usd"],
          note=T("一行一个人,近 30 天按到手收入排序,占比的分母是全部到手收入,不是前 20 名的和。"
                 "净额出现负数不是算错,聊得多的人服务成本会高过他付的钱。取消续费不是退款,"
                 "关掉自动续费时这一期的钱并没有退回去,真正的退款现在没有数据源。",
                 "One row per person, ranked by takehome over 30 days. Negative net is not an error. "
                 "Cancellations are not refunds."))),
 ]),
]

# APP_JS 内部生成的文案:它们不经过 SECTIONS,登记不到 I18N,只能在这里补。
# 静态的直接登记;带数字的(展开全部 N 行)登记不了,走 LANG_JS 里的 PATTERNS 正则。
for _zh, _en in [("◐ 主题 Theme", "◐ Theme"),
                 ("展开 Expand", "Expand"),
                 ("收起 Collapse", "Collapse")]:
    T(_zh, _en)

LANG_JS = r"""
// ---------- 中英切换 ----------
// 不改 APP_JS,也不做两份页面:同一份 DOM 换文本。
// I18N 是「页面上的中文原文 → English」,逐个文本节点查表替换。
// 🛑 每个文本节点第一次被处理时把原文存进 __zh —— 不存的话切回中文就没有原文可还原了。
// 🛑 图表切维度会重建 DOM,新节点没经过替换,所以要用 MutationObserver 在重建后补上。
(function () {
  let lang = localStorage.getItem('energyAbLang') || 'zh';
  let applying = false;

  // APP_JS 把行数拼进按钮文字("展开全部 20 行 ↓"),这种带数字的登记不进 I18N,用正则兜。
  const PATTERNS = [
    [/^展开全部 (\d+) 行 ↓$/, m => 'Show all ' + m[1] + ' rows \u2193'],
    [/^收起 · 只看前 (\d+) 行$/, m => 'Collapse to first ' + m[1] + ' rows'],
    [/^最新 (.+)$/, m => 'Latest ' + m[1]],
  ];

  function translate(zh) {
    const hit = I18N[zh];
    if (hit) return hit;
    for (const [re, fn] of PATTERNS) {
      const m = re.exec(zh);
      if (m) return fn(m);
    }
    return null;
  }

  function applyTo(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.__zh === undefined) node.__zh = node.nodeValue;
      const en = translate(node.__zh);
      const want = (lang === 'en' && en) ? en : node.__zh;
      if (node.nodeValue !== want) node.nodeValue = want;
    }
  }

  function apply() {
    applying = true;
    applyTo(document.body);
    document.documentElement.lang = (lang === 'en') ? 'en' : 'zh';
    const btn = document.getElementById('langToggle');
    if (btn) { btn.textContent = (lang === 'en') ? '中文' : 'EN'; btn.__zh = undefined; }
    applying = false;
  }

  function toggle() {
    lang = (lang === 'en') ? 'zh' : 'en';
    localStorage.setItem('energyAbLang', lang);
    apply();
  }

  function init() {
    const btn = document.getElementById('langToggle');
    if (btn) btn.addEventListener('click', toggle);
    apply();
    const root = document.getElementById('root');
    if (root) {
      new MutationObserver(function () { if (!applying) apply(); })
        .observe(root, { childList: true, subtree: true });
    }
  }

  // Artifact 把脚本放在正文之后,DOMContentLoaded 可能已经过了 —— 只挂监听会一次都不执行。
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
"""

EXTRA_CSS = """
/* Artifact 的外壳在 :root 上钉了 color-scheme:light,不补这两段的话
   暗色主题下滚动条和表单控件仍然是亮的。本地那版多写这两行也无害。 */
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark}}
:root[data-theme=dark]{color-scheme:dark}
#langToggle{position:fixed;top:12px;right:14px;z-index:99;cursor:pointer;
  padding:6px 14px;border-radius:999px;border:1px solid var(--bd,#d0d5dd);
  background:var(--surface,#fff);color:var(--tp,#222);font:600 13px/1 system-ui,sans-serif;}
#langToggle:hover{border-color:#8a94a6;}
header .plan{margin-top:6px;font-size:12px;opacity:.75;line-height:1.6;}
"""


def render(raw_path: Path, out_path: Path, artifact: bool = False):
    D = json.loads(raw_path.read_text(encoding="utf-8"))
    meta = D.get("_meta", {})
    metrics = D.get("metrics", D)

    sections = []
    for sec, cards in SECTIONS:
        built = []
        for spec in cards:
            card = RD.build_card(metrics, *spec)
            if card:
                built.append(card)
            else:
                print(f"   ⚠️ 没建出来(抓失败或无数据):{spec[0]}")
        if built:
            sections.append({"title": sec, "cards": built})

    if not sections:
        raise SystemExit("✗ 一张卡都没建出来,拒绝写出 —— 保留上一版页面。")

    chartjs = (HERE / "lib" / "chart.umd.min.js").read_text(encoding="utf-8")
    payload = json.dumps({"sections": sections, "pal": RD.PAL, "wkpal": RD.WKPAL,
                          "run_date": meta.get("run_date")}, ensure_ascii=False)

    title = T("SoulMap 能量定价实验 · Energy Pricing A/B",
              "SoulMap Energy Pricing A/B")
    plan_note = T("口径出自 Javier《修改后的能量定价计划》2026-11-18 第 6 节。"
                  "A 组 = 现价(每条 1 能量);B 组 = D-594(前 30 条每条 1,之后 1 + 2.5 × (1 − e^(−(n−30)/30)),上限约 3.5)。"
                  "语音两组都是每条 5 能量,免费额度两组一样。",
                  "Definitions follow section 6 of Javier's revised energy pricing plan, 2026-11-18. "
                  "Arm A is the current price, 1 energy per message. Arm B is D-594: 1 per message for the "
                  "first 30, then 1 + 2.5 × (1 − e^(−(n−30)/30)), capped near 3.5. Voice stays at 5 energy "
                  "per message in both arms, and the free allowance is the same in both.")
    dry_run = T("实验还没上线, 所有人现在落在 unassigned 一行,这就是计划里说的「看板空跑对账」。"
                "分组一旦开始写入,每张卡会自动分成两行,不用改 SQL;"
                "但分组用的实验名现在是占位 energy_curve_d594_v1,Kang / Liwen 定下真名后十张卡都要改。",
                "The experiment has not started: everyone currently sits in a single unassigned row, which "
                "is the dry-run reconciliation the plan calls for. Once assignments start being written "
                "each card splits into two rows on its own, with no SQL change — but the experiment key is "
                "a placeholder, energy_curve_d594_v1, and all ten cards must be updated once Kang and "
                "Liwen settle on the real name.")
    if artifact:
        # 🛑 Artifact 是**静态快照**,不会自己刷新 —— 不写清楚的话,过几天看的人
        #    会把旧数当当天的数读。线上那版才是每天刷 4 次的。
        freshness = T(f"这一页是 {meta.get('run_date', '?')} 抓的静态快照,不会自动更新。"
                      "要最新的数,让 Chris 重跑一次管线重新发布。",
                      f"This page is a static snapshot taken on {meta.get('run_date', '?')} and does not "
                      "refresh on its own. Ask Chris to re-run the pipeline and republish for current numbers.")
    else:
        freshness = T("数据直接查生产库,实时。每天跟主看板一起刷新 4 次(新加坡时间 12:20 / 14:20 / 17:20 / 21:20)。",
                      "All cards query the production database live. Refreshed four times a day alongside the "
                      "main dashboard (12:20 / 14:20 / 17:20 / 21:20 SGT).")

    hdr = (f'<button id="langToggle" type="button">EN</button>'
           f'<header><h1>{title}</h1>'
           f'<div class="meta">{T("数据", "Data")} {meta.get("run_date", "?")} · '
           f'Metabase {T("看板", "dashboard")} 25 · '
           f'{sum(len(s["cards"]) for s in sections)} {T("卡", "cards")}</div>'
           f'<div class="meta plan">{plan_note}</div>'
           f'<div class="meta plan">{dry_run}</div>'
           f'<div class="meta lag">{freshness}</div>'
           f'</header>')

    scripts = (f'<script>{chartjs}</script>\n'
               f'<script>const DATA={payload};</script>\n'
               f'<script>const I18N={json.dumps(I18N, ensure_ascii=False)};</script>\n'
               f'<script>{RD.APP_JS}</script>\n'
               f'<script>{LANG_JS}</script>')

    if artifact:
        # Artifact 发布时外面会套一层 <!doctype html><head>…</head><body>,
        # 所以这里**不能**写 html / head / body 标签,直接从 <title> 开始。
        doc = (f"<title>{title}</title>\n"
               f"<style>{RD.CSS}{EXTRA_CSS}</style>\n"
               f"{hdr}<div id=\"root\"></div>\n{scripts}")
    else:
        doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>{RD.CSS}{EXTRA_CSS}</style></head><body>{hdr}<div id="root"></div>
{scripts}</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    print(f"写出 {out_path} ({len(sections)} 板块, "
          f"{sum(len(s['cards']) for s in sections)} 卡, I18N {len(I18N)} 条)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(HERE / "raw_energy_ab.json"))
    ap.add_argument("--out", default=str(HERE / "site" / "energy-ab.html"))
    ap.add_argument("--artifact", action="store_true",
                    help="输出 Claude Artifact 用的版本:不带 html/head/body 外壳,"
                         "页头标注成静态快照")
    a = ap.parse_args()
    render(Path(a.raw), Path(a.out), artifact=a.artifact)


if __name__ == "__main__":
    main()
