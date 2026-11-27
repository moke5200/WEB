#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把云端仓里的 out/001.md 合并进本地 Google Drive 的 001.md。

为什么需要：Actions 跑完写在仓里（out/001.md），野哥看的是 E 盘那份。
合并规则：
  · 按「链接」判重，本地已有的不再加
  · 新条目插到水位线下面（最新的在上）
  · 保留历史全部内容，只更新水位线
"""
import base64
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')

TOKEN_FILE = r'F:\Program Files\DS Harness Space\测试薅羊毛 26-11-07\Token.txt'
LOCAL_001 = r'E:\Google Drive\Agent 收集\linux.do\linux.do资源收集-001.md'
REPO = 'moke5200/WEB'
REMOTE_PATH = 'out/001.md'


def token():
    t = io.open(TOKEN_FILE, encoding='utf-8').read().strip()
    return t.split('=')[-1].strip() if '=' in t else t


def fetch_remote_file(path):
    h = {'Authorization': 'Bearer ' + token(),
         'Accept': 'application/vnd.github+json', 'User-Agent': 'dsh-sync'}
    url = 'https://api.github.com/repos/%s/contents/%s' % (REPO, path)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
            d = json.loads(r.read().decode())
        return base64.b64decode(d['content']).decode('utf-8')
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print('拉 %s 失败：%s %s' % (path, e.code, e.read().decode()[:120]))
        return ''


def pull_ledger():
    """把云端的 seen_items.json 拉到本地，保证本地跑时用的是同一份台账。"""
    remote = fetch_remote_file('state/seen_items.json')
    if not remote:
        print('云端没台账，跳过')
        return 0
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state', 'seen_items.json')
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    io.open(local_path, 'w', encoding='utf-8').write(remote)
    n = len(json.loads(remote).get('items', {}))
    print('台账已拉到本地：%d 条 → %s' % (n, local_path))
    return n


def parse_entries(text):
    """拆成 [(link, block)]。

    兼容三种历史格式变体（都出现在 001.md 里）：
      1) 【标题】/链接/发帖人/发帖时间/收集时间
      2) 多一行「标签：」
      3) 多一行「资源链接：」+「标签：」
    也兼容 CRLF/LF。做法：链接行之后、发帖人之前的行都吃掉（但不能吃下一个【标题】）。
    """
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    out = []
    pat = (r'【标题】[^\n]*\n'
           r'链接：([^\n]+)\n'
           r'(?:(?!【标题】)[^\n]*\n)*?'
           r'发帖人：[^\n]*\n'
           r'发帖时间：[^\n]*\n'
           r'收集时间：[^\n]*')
    for m in re.finditer(pat, text):
        out.append((m.group(1).strip(), m.group(0)))
    return out


def main():
    if '--pull-ledger' in sys.argv:
        return 0 if pull_ledger() else 1

    remote = fetch_remote_file(REMOTE_PATH)
    if not remote:
        return 1
    r_entries = parse_entries(remote)
    print('云端条目：%d' % len(r_entries))

    local = ''
    if os.path.exists(LOCAL_001):
        local = io.open(LOCAL_001, encoding='utf-8').read()
    l_entries = parse_entries(local)
    l_links = {ln for ln, _ in l_entries}
    print('本地条目：%d' % len(l_entries))

    new = [(ln, b) for ln, b in r_entries if ln not in l_links]
    if not new:
        print('没有新条目，跳过')
        return 0
    print('新增：%d 条' % len(new))

    # 水位线取云端第一行里的时间
    wm = '水位线：最后收集时间 %s，本次同步 %d 条' % (
        __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'), len(new))

    # 旧正文（去掉原水位线行）
    body = local
    lines = body.split('\n')
    if lines and lines[0].startswith('水位线：'):
        body = '\n'.join(lines[1:]).lstrip('\n')

    block = '\n\n'.join(b for _, b in new)
    out = wm + '\n\n' + block + ('\n\n' + body if body.strip() else '')

    io.open(LOCAL_001, 'w', encoding='utf-8').write(out.rstrip('\n') + '\n')
    print('已合并 → %s' % LOCAL_001)
    return 0


if __name__ == '__main__':
    sys.exit(main())