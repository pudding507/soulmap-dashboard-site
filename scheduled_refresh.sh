#!/bin/bash
# SoulMap 看板 · 定时抓数 → 渲染 → 推 GitHub(Cloudflare Pages 监听仓库自动部署)
#
# 2026-11-19 新建。此前这条管线跑在 GitHub Actions 上,账号 billing 限制后跑不了,
# 改成跑在公司常开的那台机器(地址见本地 CLAUDE.md,**本仓库公开所以不写在这里**)。时间沿用原来的四次:
# 新加坡 12:20 / 14:20 / 17:20 / 21:20 —— 全排在 firebase ETL(实测 11:02 上下)之后,
# 早于 12:20 会拿到**前天**的埋点数,而页面上没有任何标记。
#
# 手动跑:bash scheduled_refresh.sh
#
# 凭据放在 ~/.soulmap_env 和 ~/.lark_env(chmod 600),不写进代码:
#   ~/.soulmap_env : METABASE_USER / METABASE_PASSWORD
#   ~/.lark_env    : 拉变更登记表用;缺了不致命,changes.json 会沿用上一次
#
# 推送用 SSH deploy key(~/.ssh/id_ed25519_soulmap),只对这一个仓库有写权限。
set -uo pipefail
cd "$(dirname "$0")"

# 🛑 launchd 不带语言环境。系统自带的 Python 3.9 在 LANG 未设时,
#    读「超过 1024 字节且含中文」的行会报 Non-UTF-8 语法错误 ——
#    本项目几乎每个文件都是中文注释,不设这两行必炸(CityPLX 11-18 踩过)。
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
[ -f "$HOME/.soulmap_env" ] && . "$HOME/.soulmap_env"
[ -f "$HOME/.lark_env" ]    && . "$HOME/.lark_env"

# 推哪个远程:必须是 GitHub —— Cloudflare Pages 监听的是它。
# 本机的远程叫 github / gitlab,别处可能叫 origin,这里自动认。
REMOTE=$(git remote | grep -x github || git remote | grep -x origin || git remote | head -1)

mkdir -p logs; LOG="logs/refresh.log"
log(){ echo "$(date '+%F %T') $*" >> "$LOG"; }

# 旧锁清理:一次完整抓数约 25 分钟,超过 70 分钟还占着锁就是上次卡死了
if [ -d logs/.lock ] && [ $(( $(date +%s) - $(stat -f %m logs/.lock) )) -gt 4200 ]; then
  log "锁已超过 70 分钟,当成旧锁清掉"; rmdir logs/.lock 2>/dev/null
fi
if ! mkdir logs/.lock 2>/dev/null; then log "上一次还在跑,跳过"; exit 0; fi
trap 'rmdir logs/.lock 2>/dev/null' EXIT

log "===== 开始 ====="
for v in METABASE_USER METABASE_PASSWORD; do
  if [ -z "${!v:-}" ]; then log "缺少 $v(写进 ~/.soulmap_env),退出"; exit 3; fi
done

# 机器刚唤醒时网络可能还没好,先等(最多 2 分钟)
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null --max-time 10 https://metabase.stylepedia.co/ && break
  log "网络还没好(第 $i 次),20 秒后再看"; sleep 20
done

# 取最新代码。有本地改动就不动 —— 主机上不改代码,改了说明有人手工动过,先弄清楚再说
if [ -n "$(git status --porcelain -- ':!site/' ':!logs/' ':!raw_metrics.json' ':!raw_energy_ab.json')" ]; then
  log "⚠️ 主机上有未提交的代码改动,跳过 git pull(代码只在本机改)"
else
  git pull -q --rebase --autostash "$REMOTE" main >> "$LOG" 2>&1 || log "⚠️ git pull 失败,用本地这版继续"
fi

# 🛑 测试在抓数**之前**跑。卡没登记、fmt 写错、列名拆不出英文这类
#    等渲染完才发现,一整轮卡就白抓了(约 25 分钟)。
# 🛑 测试输出单独写一个文件,**不要并进 refresh.log** ——
#    test_log_run 会故意喂坏文件、用假的「抓到 71/88 卡」做夹具,
#    混进运行日志里,以后排查的人会把夹具数据当成真的抓数结果(2026-11-20 踩过)。
if ! python3 -m unittest discover -s tests > logs/tests.log 2>&1; then
  log "❌ 单元测试没过,不抓数也不发布;详见 logs/tests.log"
  tail -15 logs/tests.log >> "$LOG"; exit 1
fi
log "测试通过($(grep -c . logs/tests.log) 行输出在 logs/tests.log)"

# 变更登记表(页头的改动日志和读数切点)。拉不到不致命:changes.json 会沿用上一次
python3 fetch_changes.py >> "$LOG" 2>&1 || log "⚠️ 拉 Lark 变更失败,沿用上一次的 changes.json"

# macOS 没有 timeout 命令,用 perl 的 alarm。一次抓数封顶 40 分钟
fetch(){ perl -e 'alarm shift; exec @ARGV' 2400 python3 fetch_metabase.py --out raw_metrics.json >> "$LOG" 2>&1; }
log "开始抓数"
if ! fetch; then log "抓数出错或超过 40 分钟,不发布"; python3 log_run.py >> "$LOG" 2>&1; exit 1; fi

# 这一轮抓了多久、哪几张慢、哪几张没抓到 → logs/runs.jsonl
python3 log_run.py >> "$LOG" 2>&1 || log "⚠️ 记录运行日志失败(不影响发布)"

# 护栏:抓到的卡太少就不发布,线上保留上一版,别出半截页面
n=$(python3 -c "import json;print(len(json.load(open('raw_metrics.json')).get('metrics',{})))" 2>/dev/null || echo 0)
if [ "$n" -lt 35 ]; then log "❌ 只抓到 $n 张卡(门槛 35),不发布,线上保留上一版"; exit 1; fi
log "抓到 $n 张卡"

# 抓完数再跑一次:百分比量纲那条要有 raw_metrics.json 才验得了
python3 -m unittest discover -s tests > logs/tests-with-data.log 2>&1 \
  || { log "❌ 带数据的测试没过,不发布;详见 logs/tests-with-data.log"
       tail -15 logs/tests-with-data.log >> "$LOG"; exit 1; }

# --history:把今天上榜的卡记进 anomaly_history.json,连续上榜的压制规则靠它
python3 render_dashboard.py --raw raw_metrics.json --out site/index.html --history >> "$LOG" 2>&1 \
  || { log "❌ 渲染主页出错,不发布"; exit 1; }
python3 render_energy_ab.py --raw raw_metrics.json --out site/energy-ab.html >> "$LOG" 2>&1 \
  || log "⚠️ 能量实验页渲染失败,主页照发"

# 🛑 要提交的不只是 site/ —— logs/runs.jsonl、anomaly_history.json、changes.json
#    都是跨轮次的状态,漏了它们连续上榜的压制规则会永远读到空历史。
#    (GitHub Actions 那版原来就漏了这三个,2026-11-19 才发现)
git add -A site/ logs/runs.jsonl anomaly_history.json changes.json
if git diff --cached --quiet; then log "没有变化,不提交"; exit 0; fi
git -c user.name=soulmap-bot -c user.email=bot@users.noreply.github.com \
    commit -q -m "dashboard $(date -u +%F_%H%M)" || { log "提交失败"; exit 1; }

# Cloudflare Pages 监听 GitHub 仓库,push 上去就会自动部署
for i in 1 2 3; do
  if git push -q "$REMOTE" main 2>>"$LOG"; then log "已推送到 $REMOTE,Pages 会自动部署"; exit 0; fi
  log "push 被拒(第 $i 次),拉一下再试"
  git pull -q --rebase --autostash -X ours "$REMOTE" main >> "$LOG" 2>&1
  sleep 5
done
# 🛑 push 失败不删本地提交 —— 下一轮会连着一起推。
#    deploy key 还没配好的时候,这里每轮都会失败,但抓数和渲染的成果都留在本地,
#    钥匙配好后第一轮就会把积攒的提交一起推上去。
log "❌ push 失败三次($REMOTE),本地已提交,下一轮会带上"
exit 1
