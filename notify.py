#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新管线的 Lark 告警。

    python3 notify.py "标题" "正文(可多行)"

🛑 **这个脚本自己绝不能让流水线失败**:webhook 没配、网络不通、Lark 返回错误,
   一律只打印、返回 0。告警是辅助,不是关卡。

webhook 从环境变量 `SOULMAP_ALERT_WEBHOOK` 读(写在 `~/.soulmap_env` 里)。
🛑 **不要存成仓库里的文件** —— 本仓库是公开的,webhook URL 等于谁都能往群里发消息。
   成本预警那条管线用的是同目录 `webhook.txt`,那个仓库不公开,这里不能照抄。

没配的时候只打印不推送,所以本地跑、新机器上跑都不会炸。
"""
from __future__ import annotations
import json
import os
import socket
import sys
import urllib.request

HOST = socket.gethostname()


def send(title: str, body: str) -> bool:
    """推一条文本消息。返回有没有推出去 —— 调用方可以不管。"""
    hook = (os.environ.get("SOULMAP_ALERT_WEBHOOK") or "").strip()
    runner = "actions" if os.environ.get("GITHUB_ACTIONS") == "true" else HOST
    text = f"【SoulMap 看板】{title}\n机器:{runner}\n\n{body}".strip()
    if not hook:
        print(f"[未推送:没配 SOULMAP_ALERT_WEBHOOK]\n{text}")
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
        print(f"[告警已推送]" if ok else f"[告警推送失败] {resp}")
        return ok
    except Exception as ex:                      # 🛑 吞掉,绝不往上抛
        print(f"[告警推送异常,忽略] {type(ex).__name__}: {ex}")
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    send(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    return 0                                     # 🛑 永远 0


if __name__ == "__main__":
    sys.exit(main())
