#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看板刷新管线的 Lark 告警(三个项目通用)。

    python3 notify.py --project CityPLX "抓数失败" "正文,可多行"
    python3 notify.py "标题" "正文"          # 项目名从 DASHBOARD_PROJECT 或当前目录推断

🛑 **这个脚本自己绝不能让流水线失败**:webhook 没配、网络不通、URL 写错,
   一律只打印、返回 0。告警是辅助,不是关卡(三种情况都实测过)。

webhook 按这个顺序找,第一个找到的生效:
  1. 环境变量 DASHBOARD_ALERT_WEBHOOK      ← 三个项目共用,推荐
  2. 环境变量 <项目名大写>_ALERT_WEBHOOK     ← 例如 SOULMAP_ALERT_WEBHOOK
  3. 文件 ~/.dashboard_alert_webhook        ← 一行一个 URL

🛑 **不要把 webhook 存进任何会提交的文件。** soulmap-upload 是公开仓库,
   webhook URL 等于谁都能往群里发消息。放环境变量或家目录下的文件。
"""
from __future__ import annotations
import argparse
import json
import os
import pathlib
import socket
import sys
import urllib.request

HOST = socket.gethostname()
HOME_FILE = pathlib.Path.home() / ".dashboard_alert_webhook"


def guess_project() -> str:
    """没指定项目名时,从当前目录推断 —— cityplx-dashboard → CityPLX。"""
    env = (os.environ.get("DASHBOARD_PROJECT") or "").strip()
    if env:
        return env
    name = pathlib.Path.cwd().name
    for suffix in ("-dashboard", "-upload", "_dashboard"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name or "看板"


def find_webhook(project: str) -> str:
    for key in ("DASHBOARD_ALERT_WEBHOOK",
                f"{project.upper().replace('-', '_')}_ALERT_WEBHOOK"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    try:
        if HOME_FILE.exists():
            return HOME_FILE.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except Exception:
        pass
    return ""


def send(title: str, body: str, project: str = "") -> bool:
    project = project or guess_project()
    hook = find_webhook(project)
    runner = "actions" if os.environ.get("GITHUB_ACTIONS") == "true" else HOST
    text = f"【{project} 看板】{title}\n机器:{runner}\n\n{body}".strip()
    if not hook:
        print(f"[未推送:没找到 webhook]\n{text}")
        return False
    try:
        req = urllib.request.Request(
            hook,
            data=json.dumps({"msg_type": "text", "content": {"text": text}}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8", "replace") or "{}")
        ok = resp.get("StatusCode") == 0 or resp.get("code") == 0
        print("[告警已推送]" if ok else f"[告警推送失败] {resp}")
        return ok
    except Exception as ex:                      # 🛑 吞掉,绝不往上抛
        print(f"[告警推送异常,忽略] {type(ex).__name__}: {ex}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="看板刷新的 Lark 告警(通用)")
    ap.add_argument("--project", default="", help="项目名,不给就从目录推断")
    ap.add_argument("title", nargs="?", default="")
    ap.add_argument("body", nargs="?", default="")
    a = ap.parse_args()
    if not a.title:
        print(__doc__)
        return 0
    send(a.title, a.body, a.project)
    return 0                                     # 🛑 永远 0


if __name__ == "__main__":
    sys.exit(main())
