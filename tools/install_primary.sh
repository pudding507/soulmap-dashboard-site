#!/bin/bash
# 在主机器上装 / 重载 SoulMap 看板的定时任务。
# 2026-11-19 新建。在主机器上跑:bash ~/DataGripProjects/soulmap-upload/tools/install_primary.sh
#
# 🛑 这个脚本只装定时任务,不碰凭据 —— ~/.soulmap_env 和 ~/.lark_env 要本人放上去。
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
PLIST="$HOME/Library/LaunchAgents/com.soulmap.dashboard.refresh.plist"

echo "== 检查前置条件 =="
fail=0
for f in "$HOME/.soulmap_env"; do
  if [ -f "$f" ]; then echo "  ✓ $f"; else echo "  ✗ 缺 $f(里面要有 METABASE_USER / METABASE_PASSWORD)"; fail=1; fi
done
[ -f "$HOME/.lark_env" ] && echo "  ✓ ~/.lark_env" \
  || echo "  ⚠ 缺 ~/.lark_env —— 页头的改动日志会沿用上一次,不致命"
REMOTE=$(git -C "$REPO" remote | grep -x github || git -C "$REPO" remote | grep -x origin || git -C "$REPO" remote | head -1)
if [ -n "$REMOTE" ]; then
  echo "  ✓ git remote: $REMOTE → $(git -C "$REPO" remote get-url "$REMOTE")"
else
  echo "  ✗ 一个 git remote 都没有"; fail=1
fi
# 🛑 这条只警告不拦:抓数和渲染不依赖推送能力。钥匙没配好时照样可以先跑起来,
#    成果留在本地提交里,钥匙配好后第一轮自动补推。
if git -C "$REPO" ls-remote --heads "$REMOTE" main >/dev/null 2>&1; then
  echo "  ✓ 能访问 $REMOTE"
else
  echo "  ⚠ 访问不了 $REMOTE(deploy key 还没配)—— 定时任务照装,抓数渲染会正常跑,"
  echo "    但产物推不出去、线上不会更新。配好钥匙后下一轮自动补推。"
fi
python3 -c "import sys; assert sys.version_info >= (3, 9)" 2>/dev/null \
  && echo "  ✓ python3 $(python3 --version 2>&1 | cut -d' ' -f2)" \
  || { echo "  ✗ python3 版本太低(要 3.9+)"; fail=1; }
[ "$fail" = 0 ] || { echo "❌ 前置条件没满足,不装定时任务"; exit 1; }

echo "== 跑一遍测试 =="
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python3 -m unittest discover -s tests 2>&1 | tail -3

echo "== 装定时任务 =="
mkdir -p "$HOME/Library/LaunchAgents" logs
sed "s|__HOME__|$HOME|g" com.soulmap.dashboard.refresh.plist > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "  已装 $PLIST"
launchctl list | grep com.soulmap.dashboard || echo "  ⚠️ launchctl list 里没看到,检查 plist"

cat <<EOF

装好了。时间:新加坡 12:20 / 14:20 / 17:20 / 21:20(机器时区要是新加坡)。
  手动跑一次 : bash $REPO/scheduled_refresh.sh
  看日志     : tail -40 $REPO/logs/refresh.log
  看每轮耗时 : python3 $REPO/log_run.py --show 7
  停掉       : launchctl unload $PLIST
EOF
