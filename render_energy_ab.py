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
          note=T("先看两组人数差多少。50/50 分组下相差超过 5% 就是分组偏了,后面九张卡的对比都不成立。"
                 "实验上线前所有人落在 unassigned 一行,这是空跑对账用的,不是出错。"
                 "分母已排掉 CityPLX(VivoCity 游戏账号,近 14 天 2,659 个,全在 SG)。",
                 "Check the headcount gap first. Under a 50/50 split, more than 5% apart means the "
                 "assignment is skewed and none of the other nine cards can be compared. Before the "
                 "experiment starts everyone sits in a single unassigned row — that is the dry run, not a "
                 "fault. CityPLX accounts (2,659 in the last 14 days, all in SG) are excluded."))),
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
                ("net_usd_per_user_capped50", T("人均净额(封顶$50)Net/User", "Net / user (capped $50)"), "d4"),
                ("net_usd_per_user", T("人均净额(不封顶)Uncapped", "Net / user (uncapped)"), "d4"),
                ("buyers", T("买过的人 Buyers", "Buyers"), "int")],
          bar=["users", "net_usd_per_user_capped50"],
          note=T("判定主指标,用封顶 $50 那一列,不封顶的并列只作参考。"
                 "🔴 14 天那一档今天是空的,不是 bug —— 成本表 11-06 中午才全部开始记,"
                 "第一个满 14 天的完整队列要到 11-20 才出现;在那之前只有 7 天那一列能读。"
                 "净额不含广告花费。",
                 "The decision metric is the $50-capped column; the uncapped one is listed for reference "
                 "only. The 14-day row is empty today by design — cost logging only became complete at "
                 "midday on 11-06, so the first full 14-day cohort appears on 11-20. Until then read the "
                 "7-day column. Net excludes ad spend."))),
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
          note=T("早停规则看的就是首购率和又买比例:B 组比 A 组低 30% 以上且有 95% 把握就停。"
                 "「买」取服务端成交记录(有金额的那一类),不取订单表 —— 订单表的金额和国家列是空的。"
                 "「用完后买」现在分子只有 12,读不出,等量起来。",
                 "The early-stop rule watches first-purchase and repeat-purchase rates: stop if arm B is "
                 "more than 30% below arm A at 95% confidence. A purchase is taken from the server-side "
                 "billing log, not the order table, whose price and country columns are empty. "
                 "Bought-after-runout has a numerator of 12 — too small to read yet."))),
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
          note=T("这是 D-594 涨价理由的直接验证:聊得越久,每条成本越高、毛利率越低 —— "
                 "实测从前 10 条的 39% 一路降到第 101 条以后的 4.5%。"
                 "🛑 右边两列是静态模拟:按现在这批消息,如果改用 D-594 曲线会收多少能量。"
                 "它假设用户行为完全不变,而涨价本来就会让人少聊,"
                 "所以不能当成「改了就能赚这么多」,它只说明曲线本身的形状。",
                 "This is the direct check on the case for D-594: the longer a conversation runs, the more "
                 "each message costs and the thinner the margin — measured at 39% for the first ten "
                 "messages, falling to 4.5% beyond message 101. The two right-hand columns are a static "
                 "simulation of what the same messages would have been charged under the D-594 curve. It "
                 "assumes behaviour does not change, whereas a price rise is exactly what makes people "
                 "chat less, so read it as the shape of the curve, not as expected earnings."))),
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
          note=T("同样消耗 1 能量,各国贡献的钱差 2 倍以上 —— 实测印度 $0.0053、美国 $0.0031、英国 $0.0023。"
                 "国家取注册国家,不是商店国家:订单表的商店国家列是空的,"
                 "而成交记录里的国家只有买过的人才有,拿它当分母会把没买的人全漏掉。"
                 "消耗不足 100 能量的国家标「读不出」。净额不含广告花费。",
                 "The same unit of energy is worth more than twice as much in one market as another: "
                 "$0.0053 in India, $0.0031 in the US, $0.0023 in the UK. Country is the signup country, "
                 "not the store country — the order table's store country is empty, and the country on a "
                 "billing record exists only for people who bought, which would drop everyone else from "
                 "the denominator. Countries under 100 energy spent are marked unreadable. Net excludes "
                 "ad spend."))),
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
          note=T("涨价最直接的副作用是「用户少聊了」,这张卡就是看这个。"
                 "🛑 这里的第 7 天不是主看板那张留存卡的口径,两张卡的数不要互相对:"
                 "主看板按设备算(要和装机对齐),这里按账号算(实验是按账号分组的),"
                 "用的是「注册后第 7 天还在发消息」。"
                 "人均活跃天数实测只有 1.3 天,大多数新用户只来一天,第 7 天的数低是这个结构决定的。",
                 "The most direct side effect of a price rise is that people chat less; this card watches "
                 "that. The day-7 figure here is not the main dashboard's retention definition and the two "
                 "should not be compared: the main dashboard counts devices to line up with installs, "
                 "while this one counts accounts, because that is how the experiment assigns people, and "
                 "asks whether they were still sending messages on day 7. Average active days is 1.3 — "
                 "most new users come once, which is why the day-7 number is low."))),
   ("energy_ab_conversation_length", T("对话长度与第30条附近换角色 · Conversation Length",
                                       "Conversation length & switching"), "table",
     dict(top=20,
          cols=[("arm", T("组 Arm", "Arm"), "text"),
                ("final_length_band", T("最终聊了多少条 Final Length", "Final length"), "text"),
                ("conversations", T("对话数 Conversations", "Conversations"), "int"),
                ("pct_of_conversations", T("占比 %", "Share %"), "d1"),
                ("users", T("人数 Users", "Users"), "int")],
          bar=["conversations", "pct_of_conversations"],
          note=T("D-594 从第 30 条开始涨价,而换角色会让条数从第 1 条重新数 ⇒ "
                 "用户可能在第 30 条附近换角色避价。看 26-30 这一档有没有异常堆积。"
                 "🔴 现在还没有任何涨价,26-30 档就已经高于两边(21-25 档 4.2%、26-30 档 5.1%、31-35 档 2.4%),"
                 "原因几乎可以肯定是免费额度正好是 30 条(注册送 20 + 第一次用完送 10)。"
                 "⇒ D-594 的涨价点和免费额度耗尽点落在同一条消息上,"
                 "这张卡读出的堆积分不清是哪一件造成的,只能靠和 A 组比同一档位的占比差。",
                 "D-594 starts raising the price at message 30, and switching character restarts the count "
                 "at one, so people may switch around message 30 to avoid the rise. Watch the 26-30 band "
                 "for a pile-up. Note that with no price rise in place at all, 26-30 already stands above "
                 "both neighbours (4.2% / 5.1% / 2.4%), almost certainly because the free allowance is "
                 "exactly 30 messages (20 at signup plus 10 at first run-out). The price step and the "
                 "allowance running out therefore land on the same message, and this card alone cannot "
                 "separate them — only the gap against arm A in the same band can."))),
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
          note=T("Javier 要查的那个比值:每扣一次能量,背后约 1.7 次语音生成,多出来的那 0.7 次没扣到费。"
                 "🔴 实测可以定位到原因:「生成时记账」和「厂商调用」两列几乎逐日完全相等"
                 "(11-18 是 255/255、11-16 是 733/733),而「实际扣费」比它们少四成 —— "
                 "⇒ 语音是在检查能量之前就已经生成了,能量不够的用户也触发了生成。"
                 "🛑 只读 11-14 起的行:老 Plus 用户 11-13 17:33 才转能量,在那之前他们无限畅聊不扣费,"
                 "分母几乎是 0,比值会高到几十上百倍。",
                 "The ratio Javier asked about: roughly 1.7 voice generations behind every energy charge, "
                 "with the extra 0.7 never charged for. The cause is visible here — the generation-time "
                 "log and the vendor call count match almost exactly day by day (255/255 on 11-18, 733/733 "
                 "on 11-16) while the actual charges run about 40% below both, which means the audio is "
                 "generated before the energy check, so users without enough energy still trigger it. Read "
                 "only from 11-14 onward: legacy Plus users moved onto energy at 17:33 on 11-13, and "
                 "before that they chatted without being charged, leaving a near-zero denominator."))),
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
          note=T("毛利 = 到手收入减服务成本,不含广告花费、不含人力 —— 它只回答「这些对话本身赚不赚」。"
                 "实测 11-12 到 11-18 的七天里有六天是负的。这是现价下的基线,D-594 要改的就是这个。"
                 "成本从 11-06 中午起才全部记齐,更早的日子毛利率会虚高。"
                 "当天没有成交的日子照样出一行(收入 0),不跳过 —— 跳过会让趋势看起来比实际好。",
                 "Margin is takehome revenue less serving cost; it excludes ad spend and salaries, so it "
                 "answers only whether the conversations themselves pay for themselves. Six of the seven "
                 "days from 11-12 to 11-18 were negative. That is the baseline under current pricing and "
                 "what D-594 sets out to change. Cost logging is only complete from midday on 11-06, so "
                 "earlier days show a flattering margin. Days with no sales still get a row rather than "
                 "being skipped, which would make the trend look better than it is."))),
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
          note=T("计划第 2 节:这次改价最坏的情况不是少赚,是丢掉现在的大客户,所以前几名要每周单独看。"
                 "🔴 净额会出现负数,那不是算错 —— 实测排第 3 的大客户 30 天聊了 18,931 条,"
                 "服务成本高于他付的钱,净 −$15.79。这正是 D-594 针对的那类人:买得不少,但聊得更多。"
                 "🛑 「取消续费」不是退款 —— 用户关掉自动续费时这一期的钱并没有退回去。"
                 "真正的退款和「骂价格」现在都没有数据源,这张卡做不了。",
                 "Section 2 of the plan: the worst case of this change is not earning less but losing the "
                 "current top users, so the leaders are reviewed individually each week. Negative net is "
                 "not an error — the third-ranked user sent 18,931 messages in 30 days and cost more to "
                 "serve than they paid, netting −$15.79. That is exactly who D-594 is aimed at: buys a "
                 "fair amount, chats a great deal more. Cancellations are not refunds; turning off "
                 "auto-renewal does not return the current period's money. Actual refunds and price "
                 "complaints have no data source today, so this card cannot show them."))),
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

  document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('langToggle');
    if (btn) btn.addEventListener('click', toggle);
    apply();
    const root = document.getElementById('root');
    if (root) {
      new MutationObserver(function () { if (!applying) apply(); })
        .observe(root, { childList: true, subtree: true });
    }
  });
})();
"""

EXTRA_CSS = """
#langToggle{position:fixed;top:12px;right:14px;z-index:99;cursor:pointer;
  padding:6px 14px;border-radius:999px;border:1px solid var(--bd,#d0d5dd);
  background:var(--surface,#fff);color:var(--tp,#222);font:600 13px/1 system-ui,sans-serif;}
#langToggle:hover{border-color:#8a94a6;}
header .plan{margin-top:6px;font-size:12px;opacity:.75;line-height:1.6;}
"""


def render(raw_path: Path, out_path: Path):
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
    dry_run = T("🛑 实验还没上线 —— 所有人现在落在 unassigned 一行,这就是计划里说的「看板空跑对账」。"
                "分组一旦开始写入,每张卡会自动分成两行,不用改 SQL;"
                "但分组用的实验名现在是占位 energy_curve_d594_v1,Kang / Liwen 定下真名后十张卡都要改。",
                "The experiment has not started: everyone currently sits in a single unassigned row, which "
                "is the dry-run reconciliation the plan calls for. Once assignments start being written "
                "each card splits into two rows on its own, with no SQL change — but the experiment key is "
                "a placeholder, energy_curve_d594_v1, and all ten cards must be updated once Kang and "
                "Liwen settle on the real name.")
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

    doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>{RD.CSS}{EXTRA_CSS}</style></head><body>{hdr}<div id="root"></div>
<script>{chartjs}</script>
<script>const DATA={payload};</script>
<script>const I18N={json.dumps(I18N, ensure_ascii=False)};</script>
<script>{RD.APP_JS}</script>
<script>{LANG_JS}</script></body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    print(f"写出 {out_path} ({len(sections)} 板块, "
          f"{sum(len(s['cards']) for s in sections)} 卡, I18N {len(I18N)} 条)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(HERE / "raw_energy_ab.json"))
    ap.add_argument("--out", default=str(HERE / "site" / "energy-ab.html"))
    a = ap.parse_args()
    render(Path(a.raw), Path(a.out))


if __name__ == "__main__":
    main()
