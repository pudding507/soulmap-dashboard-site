# SoulMap 线上看板

每日自动刷新的静态看板。数据源 Metabase,渲染成单文件 HTML,发布到 Cloudflare Pages。

## 仓库结构(参考 kix,但代码+输出合一)

```
fetch_metabase.py            # 抓数:Metabase → raw_metrics.json(只走 HTTPS,不碰 DB)
render_dashboard.py          # 渲染:raw_metrics.json → site/index.html(内嵌 Chart.js)
lib/chart.umd.min.js         # 内嵌的图表库(离线)
site/index.html              # ★ 输出网页 —— Cloudflare Pages 部署这个目录
.github/workflows/daily.yml  # 定时机器人:每天 SGT 04:00 跑 抓数→渲染→push
```

> kix 是"代码仓库(GitLab)+ 输出仓库(GitHub)"两个;我们用 GitHub Actions 合成一个仓库更省事。

## 首次设置(一次性)

1. **建这个 GitHub 仓库**,把本目录所有文件 push 上去。
2. 仓库 **Settings → Secrets and variables → Actions → New repository secret**,加两条:
   - `METABASE_USER` = Metabase 账号
   - `METABASE_PASSWORD` = Metabase 密码
3. **Cloudflare** → Pages → **Connect to Git** → 选这个仓库 →
   - Build command:留空
   - Build output directory:`site`
   - 部署后得到 `xxx.pages.dev`,看板就在这。
4. 之后每天 04:00 机器人自动更新;想立刻刷新:仓库 **Actions → SoulMap dashboard daily → Run workflow**。

## 本地跑

```bash
export METABASE_USER=... METABASE_PASSWORD=...
python3 fetch_metabase.py                 # → raw_metrics.json
python3 render_dashboard.py --raw raw_metrics.json --out site/index.html
```

## 加卡 / 改图

只改 `render_dashboard.py` 里的 `SECTIONS` 注册表(每卡一行)。
