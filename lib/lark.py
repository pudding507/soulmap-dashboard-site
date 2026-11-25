#!/usr/bin/env python3
"""Lark(larksuite.com)多维表格 / 文档 通用读写工具,不依赖任何项目。

凭据:环境变量 LARK_APP_ID / LARK_APP_SECRET;没有就读 ~/.lark_env(export LARK_APP_ID=... 格式)。
只用标准库。所有写操作默认只预览,加 --yes 才真正提交。

用法:
  lark.py url <链接>                                  # 从链接解析 app_token / table_id / view_id / wiki token
  lark.py tables <app_token>                          # 列出多维表格里的数据表
  lark.py fields <app_token> <table_id>               # 字段定义(类型、单选选项)
  lark.py records <app_token> <table_id> [--view V] [--out 文件.csv|.json] [--raw]
  lark.py wiki-node <wiki_token>                      # 知识库节点 → 实际对象类型和 obj_token
  lark.py doc <document_id> [--out 文件.txt]          # 普通文档纯文本
  lark.py create <app_token> <table_id> --json 文件 [--yes]   # 新增记录,文件为 [{"字段": 值}, ...]
  lark.py update <app_token> <table_id> --json 文件 [--yes]   # 更新记录,文件为 [{"record_id": "...", "fields": {...}}, ...]
不提供删除;删除请在 Lark 页面上手动操作。
"""
from __future__ import annotations
import argparse, csv, json, os, re, sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlparse, parse_qs, urlencode, quote
from urllib.request import Request, urlopen

LARK = 'https://open.larksuite.com/open-apis'      # 国际版;不要用 open.feishu.cn
CN = timezone(timedelta(hours=8))                  # 日期字段按 UTC+8 解析
WRITE_CHUNK = 500


def creds():
    i, s = os.environ.get('LARK_APP_ID'), os.environ.get('LARK_APP_SECRET')
    if not (i and s):
        p = os.path.expanduser('~/.lark_env')
        if os.path.exists(p):
            for line in open(p, encoding='utf-8'):
                m = re.match(r'\s*(?:export\s+)?(LARK_APP_ID|LARK_APP_SECRET)\s*=\s*["\']?([^"\'\s]+)', line)
                if m:
                    if m.group(1) == 'LARK_APP_ID': i = i or m.group(2)
                    else: s = s or m.group(2)
    if not (i and s):
        sys.exit('缺少凭据:设置 LARK_APP_ID / LARK_APP_SECRET,或写进 ~/.lark_env')
    return i, s


def call(method, path, token=None, body=None, query=None):
    url = f'{LARK}{path}' + (f'?{urlencode(query)}' if query else '')
    h = {'Content-Type': 'application/json; charset=utf-8'}
    if token: h['Authorization'] = f'Bearer {token}'
    req = Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    try:
        d = json.loads(urlopen(req, timeout=30).read())
    except HTTPError as e:
        try: d = json.loads(e.read())
        except Exception: sys.exit(f'HTTP {e.code} {method} {path}')
    if d.get('code') != 0:      # 只报 code 和 msg,不打印 token
        sys.exit(f'接口报错 {method} {path}: code={d.get("code")} msg={d.get("msg")}')
    return d.get('data', d)


def token():
    i, s = creds()
    req = Request(f'{LARK}/auth/v3/tenant_access_token/internal', data=json.dumps({'app_id': i, 'app_secret': s}).encode(),
                  headers={'Content-Type': 'application/json'}, method='POST')
    d = json.loads(urlopen(req, timeout=15).read())
    if d.get('code') != 0:
        sys.exit(f'取 tenant_access_token 失败: code={d.get("code")} msg={d.get("msg")}')
    return d['tenant_access_token']


def paged(method, path, tok, body=None, query=None, size=100):
    out, page = [], None
    while True:
        if method == 'POST':
            b = dict(body or {}); b['page_size'] = size
            if page: b['page_token'] = page
            d = call('POST', path, tok, body=b, query=query)
        else:
            q = dict(query or {}); q['page_size'] = size
            if page: q['page_token'] = page
            d = call('GET', path, tok, query=q)
        out += d.get('items') or []
        if not d.get('has_more'):
            return out
        page = d.get('page_token')


def as_text(v):
    """把 Bitable 返回的字段值转成文本:富文本拼接、人员取名字、多选用「、」连接、日期按 UTC+8。"""
    if v is None: return ''
    if isinstance(v, list):
        if v and all(isinstance(x, dict) and 'text' in x for x in v):
            return ''.join(x.get('text', '') for x in v)
        return '、'.join(as_text(x) for x in v if as_text(x))
    if isinstance(v, dict):
        for k in ('text', 'name', 'en_name', 'value', 'link'):
            if k in v: return as_text(v[k])
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def date_text(v):
    return datetime.fromtimestamp(v / 1000, tz=CN).strftime('%Y-%m-%d %H:%M') if isinstance(v, (int, float)) else as_text(v)


def try_call(method, path, token=None, query=None):
    """同 call,但接口报错返回 None 而不是退出(用于探测)。"""
    url = f'{LARK}{path}' + (f'?{urlencode(query)}' if query else '')
    req = Request(url, headers={'Authorization': f'Bearer {token}'}, method=method)
    try:
        d = json.loads(urlopen(req, timeout=30).read())
    except Exception:
        return None
    return d.get('data') if d.get('code') == 0 else None


def sheet_token(tok, t):
    """电子表格 token:知识库链接给的是 wiki node token,要换成 obj_token。"""
    n = (try_call('GET', '/wiki/v2/spaces/get_node', tok, query={'token': t}) or {}).get('node') or {}
    if n.get('obj_type') == 'sheet' and n.get('obj_token'):
        print(f"[wiki] {n.get('title')} → {n['obj_token']}", file=sys.stderr)
        return n['obj_token']
    return t


def parse_url(u):
    p = urlparse(u); q = parse_qs(p.query); parts = [x for x in p.path.split('/') if x]
    r = {'host': p.netloc}
    for kind in ('base', 'wiki', 'docx', 'sheets'):
        if kind in parts and parts.index(kind) + 1 < len(parts):
            r[kind] = parts[parts.index(kind) + 1]
    for k, n in (('table', 'table_id'), ('view', 'view_id'), ('sheet', 'sheet_id')):
        if q.get(k): r[n] = q[k][0]
    if 'base' in r: r['app_token'] = r['base']
    elif 'wiki' in r and 'table_id' in r: r['app_token'] = r['wiki']   # 知识库里的表:KiX 的做法是 wiki token 直接当 app_token
    return r


def load_rows(path):
    rows = json.load(open(path, encoding='utf-8'))
    if not isinstance(rows, list): sys.exit('--json 文件必须是数组')
    return rows


def main():
    ap = argparse.ArgumentParser(description='Lark 多维表格 / 文档 读写')
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('url').add_argument('link')
    sp.add_parser('tables').add_argument('app_token')
    a = sp.add_parser('fields'); a.add_argument('app_token'); a.add_argument('table_id')
    a = sp.add_parser('records'); a.add_argument('app_token'); a.add_argument('table_id')
    a.add_argument('--view'); a.add_argument('--out'); a.add_argument('--raw', action='store_true', help='输出接口原样 JSON,不转文本')
    sp.add_parser('wiki-node').add_argument('wiki_token')
    sp.add_parser('sheets').add_argument('token', help='电子表格 token,或知识库 wiki token')
    a = sp.add_parser('cells'); a.add_argument('token'); a.add_argument('sheet_id')
    a.add_argument('--range', default='A1:Z200', help='默认 A1:Z200'); a.add_argument('--out')
    a = sp.add_parser('doc'); a.add_argument('document_id'); a.add_argument('--out')
    for c in ('create', 'update'):
        a = sp.add_parser(c); a.add_argument('app_token'); a.add_argument('table_id')
        a.add_argument('--json', required=True); a.add_argument('--yes', action='store_true')
    # delete:--json 给 record_id 数组(或带 record_id 的对象数组)。
    # 🛑 删除不可逆,所以预览会把每行的真实内容也拉出来显示,不是只回显 id。
    a = sp.add_parser('delete'); a.add_argument('app_token'); a.add_argument('table_id')
    a.add_argument('--json', required=True); a.add_argument('--yes', action='store_true')
    x = ap.parse_args()

    if x.cmd == 'url':
        print(json.dumps(parse_url(x.link), ensure_ascii=False, indent=2)); return
    tok = token()
    if x.cmd == 'tables':
        for t in paged('GET', f'/bitable/v1/apps/{x.app_token}/tables', tok):
            print(f"{t.get('table_id')}\t{t.get('name')}")
    elif x.cmd == 'fields':
        for f in paged('GET', f'/bitable/v1/apps/{x.app_token}/tables/{x.table_id}/fields', tok):
            opts = [o.get('name') for o in ((f.get('property') or {}).get('options') or [])]
            print(f"{f.get('field_name')}\ttype={f.get('type')}" + (f"\t选项={'|'.join(opts)}" if opts else ''))
    elif x.cmd == 'records':
        body = {'view_id': x.view} if x.view else {}
        items = paged('POST', f'/bitable/v1/apps/{x.app_token}/tables/{x.table_id}/records/search', tok, body=body)
        if x.raw:
            rows = items
        else:
            types = {f['field_name']: f.get('type') for f in paged('GET', f'/bitable/v1/apps/{x.app_token}/tables/{x.table_id}/fields', tok)}
            rows = [{'record_id': it.get('record_id'),
                     **{k: (date_text(it['fields'].get(k)) if types.get(k) in (5, 1001, 1002) else as_text(it['fields'].get(k))) for k in types}}
                    for it in items]
        if x.out and x.out.endswith('.csv') and not x.raw:
            with open(x.out, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['record_id']); w.writeheader(); w.writerows(rows)
        elif x.out:
            json.dump(rows, open(x.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        else:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f'共 {len(rows)} 条' + (f',已写入 {x.out}' if x.out else ''), file=sys.stderr)
    elif x.cmd == 'wiki-node':
        n = call('GET', '/wiki/v2/spaces/get_node', tok, query={'token': x.wiki_token}).get('node', {})
        print(json.dumps({k: n.get(k) for k in ('title', 'obj_type', 'obj_token', 'space_id', 'node_type')}, ensure_ascii=False, indent=2))
    elif x.cmd == 'sheets':
        t = sheet_token(tok, x.token)
        for sh in call('GET', f'/sheets/v3/spreadsheets/{t}/sheets/query', tok).get('sheets', []):
            g = sh.get('grid_properties') or {}
            print(f"{sh.get('sheet_id')}\t{sh.get('title')}\t{g.get('row_count')} 行 × {g.get('column_count')} 列")
    elif x.cmd == 'cells':
        t = sheet_token(tok, x.token)
        rng = quote(f'{x.sheet_id}!{x.range}', safe='')
        d = call('GET', f'/sheets/v2/spreadsheets/{t}/values/{rng}', tok,
                 query={'valueRenderOption': 'ToString', 'dateTimeRenderOption': 'FormattedString'})
        vs = (d.get('valueRange') or {}).get('values') or []
        rows = [[as_text(c) for c in r] for r in vs]
        rows = [r for r in rows if any(c.strip() for c in r)]
        if x.out:
            with open(x.out, 'w', encoding='utf-8-sig', newline='') as f:
                csv.writer(f).writerows(rows)
        else:
            for r in rows: print('\t'.join(r))
        print(f'共 {len(rows)} 行' + (f',已写入 {x.out}' if x.out else ''), file=sys.stderr)
    elif x.cmd == 'doc':
        text = call('GET', f'/docx/v1/documents/{x.document_id}/raw_content', tok).get('content', '')
        if x.out: open(x.out, 'w', encoding='utf-8').write(text); print(f'已写入 {x.out}', file=sys.stderr)
        else: print(text)
    elif x.cmd in ('create', 'update'):
        rows = load_rows(x.json)
        if x.cmd == 'create':
            recs = [{'fields': r} for r in rows]
        else:
            bad = [r for r in rows if not r.get('record_id') or not isinstance(r.get('fields'), dict)]
            if bad: sys.exit(f'{len(bad)} 条缺 record_id 或 fields')
            recs = rows
        print(f'{x.cmd}: {len(recs)} 条 → {x.app_token}/{x.table_id}', file=sys.stderr)
        print(json.dumps(recs[:3], ensure_ascii=False, indent=1), file=sys.stderr)
        if not x.yes:
            print('预览模式,未提交。确认无误后加 --yes。', file=sys.stderr); return
        path = f'/bitable/v1/apps/{x.app_token}/tables/{x.table_id}/records/batch_{x.cmd}'
        done = 0
        for k in range(0, len(recs), WRITE_CHUNK):
            d = call('POST', path, tok, body={'records': recs[k:k + WRITE_CHUNK]})
            done += len(d.get('records') or [])
        print(f'已提交 {done} 条', file=sys.stderr)
    elif x.cmd == 'delete':
        rows = load_rows(x.json)
        ids = [r if isinstance(r, str) else r.get('record_id') for r in rows]
        bad = [i for i, v in enumerate(ids) if not isinstance(v, str) or not v.startswith('rec')]
        if bad: sys.exit(f'{len(bad)} 条不是合法 record_id(要么是字符串数组,要么对象里带 record_id)')
        if len(set(ids)) != len(ids): sys.exit('--json 里有重复的 record_id')
        # 🛑 删除不可逆:先把这些行现在长什么样拉出来给人看,再决定要不要删。
        want = set(ids)
        found = {}
        for rec in paged('POST', f'/bitable/v1/apps/{x.app_token}/tables/{x.table_id}/records/search',
                         tok, body={}):
            if rec.get('record_id') in want: found[rec['record_id']] = rec.get('fields') or {}
        print(f'delete: {len(ids)} 条 → {x.app_token}/{x.table_id}', file=sys.stderr)
        for rid in ids:
            f = found.get(rid)
            if f is None:
                print(f'  ⚠️ {rid} 在表里找不到(可能已被删)', file=sys.stderr); continue
            head = {k: v for k, v in list(f.items())[:4]}
            print(f'  {rid}  {json.dumps(head, ensure_ascii=False)[:150]}', file=sys.stderr)
        missing = [i for i in ids if i not in found]
        if missing and x.yes:
            sys.exit(f'有 {len(missing)} 条找不到,已中止。确认后把它们从 --json 里去掉再跑')
        if not x.yes:
            print('预览模式,未删除。确认无误后加 --yes。🛑 删除不可逆,表里没有回收站。', file=sys.stderr)
            return
        path = f'/bitable/v1/apps/{x.app_token}/tables/{x.table_id}/records/batch_delete'
        done = 0
        for k in range(0, len(ids), WRITE_CHUNK):
            d = call('POST', path, tok, body={'records': ids[k:k + WRITE_CHUNK]})
            done += len(d.get('records') or [])
        print(f'已删除 {done} 条', file=sys.stderr)


if __name__ == '__main__':
    main()
