#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把云端仓里的采集结果全部拉回本地（野哥要看的落地动作）。

云端 → 本地：
  1) out/daily_json/<源>.json → Agent 收集\<来源名>\<源>_YYYY-MM-DD.md（一源一文件夹，铁律5）
  2) state/seen_items.json     → collector/state/seen_items.json（台账）
  3) out/001.md                → Agent 收集\linux.do\linux.do资源收集-001.md（合并，按链接判重）

幂等：同一条链接不重复写；每天一个 md，重复同步会覆盖当天文件。

用法：
  python sync_local.py              # 全部同步
  python sync_local.py --pull-ledger  # 只拉台账
"""
import base64
import datetime
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 让 core 可导入

TOKEN_FILE = r'F:\Program Files\DS Harness Space\测试薅羊毛 26-11-07\Token.txt'
COLLECT_ROOT = r'E:\Google Drive\Agent 收集'
LOCAL_001 = os.path.join(COLLECT_ROOT, 'linux.do', 'linux.do资源收集-001.md')
REPO = 'moke5200/WEB'


def token():
    t = io.open(TOKEN_FILE, encoding='utf-8').read().strip()
    return t.split('=')[-1].strip() if '=' in t else t


def fetch_remote_file(path, repo=REPO):
    h = {'Authorization': 'Bearer ' + token(),
         'Accept': 'application/vnd.github+json', 'User-Agent': 'dsh-sync'}
    url = 'https://api.github.com/repos/%s/contents/%s' % (repo, path)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
            d = json.loads(r.read().decode())
        return base64.b64decode(d['content']).decode('utf-8')
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print('  拉 %s 失败：%s %s' % (path, e.code, e.read().decode()[:120]))
        return ''


def list_remote_dir(path, repo=REPO):
    h = {'Authorization': 'Bearer ' + token(),
         'Accept': 'application/vnd.github+json', 'User-Agent': 'dsh-sync'}
    url = 'https://api.github.com/repos/%s/contents/%s' % (repo, path)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
            return json.loads(r.read().decode())
    except Exception:
        return []


def pull_ledger():
    remote = fetch_remote_file('state/seen_items.json')
    if not remote:
        print('  云端没台账，跳过')
        return 0
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state', 'seen_items.json')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, 'w', encoding='utf-8').write(remote)
    n = len(json.loads(remote).get('items', {}))
    print('  台账 → 本地 %d 条' % n)
    return n


def item_to_md(it):
    """一条 Item → md 段落。英文源在本地落盘时补翻译（云端 IP 翻不了）。"""
    title = it.get('title') or '无标题'
    summary = it.get('summary') or ''
    tags = it.get('tags') or []
    # 云端没翻成的，本地补翻
    if '未翻译' in tags:
        try:
            from core import translate as tr
            zh_t = tr.to_zh(title)
            zh_s = tr.to_zh(summary) if summary else ''
            if zh_t:
                title = zh_t
            if zh_s:
                summary = zh_s
            if zh_t or zh_s:
                tags = [x for x in tags if x != '未翻译'] + ['已翻译(本地)']
        except Exception as e:
            print('    翻译失败：%s' % str(e)[:60])

    lines = ['## ' + title, '']
    if summary:
        lines += [summary, '']
    meta = []
    if it.get('author'):
        meta.append('作者：' + it['author'])
    if it.get('published'):
        meta.append('时间：' + it['published'])
    if meta:
        lines += [' · '.join(meta), '']
    if it.get('url'):
        lines += ['链接：' + it['url'], '']
    for m in it.get('media') or []:
        if isinstance(m, dict):
            lines.append('图片：%s' % m.get('url', ''))
        elif isinstance(m, (list, tuple)) and len(m) >= 2:
            lines.append('%s：%s' % (m[0], m[1]))
    if any(str(x).startswith('图片：') for x in lines):
        lines.append('')
    if tags:
        lines += ['标签：' + '、'.join(tags), '']
    return '\n'.join(lines)


def pull_sources():
    """拉所有源的 JSON，按一源一文件夹落地。"""
    files = [x for x in list_remote_dir('out/daily_json') if x.get('name', '').endswith('.json')]
    if not files:
        print('  云端没有源 JSON')
        return 0
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    total = 0
    for f in files:
        sid = f['name'][:-5]
        txt = fetch_remote_file('out/daily_json/' + f['name'])
        if not txt:
            continue
        try:
            j = json.loads(txt)
        except Exception:
            continue
        items = j.get('items') or []
        # 一源一文件夹：用源名作文件夹名（a01 → linux.do云资源，简单起见用 ID + 名称）
        name = j.get('name') or sid
        folder = re.sub(r'[\\/:*?"<>|]', '-', ('%s %s' % (sid, name)))[:60]
        outdir = os.path.join(COLLECT_ROOT, folder)
        os.makedirs(outdir, exist_ok=True)
        outfile = os.path.join(outdir, '%s_%s.md' % (sid, today))
        head = ('# %s · %s\n\n> 源：%s ｜ 抓取：%s ｜ 条数：%d\n\n---\n\n'
                % (name, today, sid, j.get('fetched_at', ''), len(items)))
        body = '\n\n'.join(item_to_md(it) for it in items)
        io.open(outfile, 'w', encoding='utf-8').write(head + body + '\n')
        print('  %-4s %-24s %3d 条 → %s\\%s' % (sid, name, len(items), folder, os.path.basename(outfile)))
        total += len(items)
    return total


def parse_entries(text):
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    out = []
    pat = (r'【标题】[^\n]*\n链接：([^\n]+)\n'
           r'(?:(?!【标题】)[^\n]*\n)*?'
           r'发帖人：[^\n]*\n发帖时间：[^\n]*\n收集时间：[^\n]*')
    for m in re.finditer(pat, text):
        out.append((m.group(1).strip(), m.group(0)))
    return out


def pull_001():
    remote = fetch_remote_file('out/001.md')
    if not remote:
        return 0
    r_entries = parse_entries(remote)
    local = io.open(LOCAL_001, encoding='utf-8').read() if os.path.exists(LOCAL_001) else ''
    l_links = {ln for ln, _ in parse_entries(local)}
    new = [(ln, b) for ln, b in r_entries if ln not in l_links]
    if not new:
        print('  001.md 无新条目')
        return 0
    lines = local.split('\n')
    body = '\n'.join(lines[1:]).lstrip('\n') if lines and lines[0].startswith('水位线：') else local
    wm = '水位线：最后收集时间 %s，本次同步 %d 条' % (
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), len(new))
    out = wm + '\n\n' + '\n\n'.join(b for _, b in new) + ('\n\n' + body if body.strip() else '')
    io.open(LOCAL_001, 'w', encoding='utf-8').write(out.rstrip('\n') + '\n')
    print('  001.md 新增 %d 条' % len(new))
    return len(new)


WATERMARK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'state', 'sync_watermark.json')


def load_watermark():
    try:
        return json.load(io.open(WATERMARK, encoding='utf-8'))
    except Exception:
        return {}


def save_watermark(wm):
    os.makedirs(os.path.dirname(WATERMARK), exist_ok=True)
    wm['last_sync'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    json.dump(wm, io.open(WATERMARK, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, sort_keys=True)


def main():
    print('=== 同步云端 → 本地 ===')
    prev = load_watermark()
    print('上次同步：%s' % prev.get('last_sync', '（首次）'))

    print('[1/3] 台账')
    pull_ledger()

    print('[2/3] 各源产物（一源一文件夹）')
    n = pull_sources()

    print('[3/3] 001.md')
    n001 = pull_001()

    # 记水位线：各源条数 + 001条数，供下轮对比是否有新数据
    src_stats = {}
    for f in (list_remote_dir('out/daily_json') or []):
        if f.get('name', '').endswith('.json'):
            j = safe_load('out/daily_json/' + f['name'])
            src_stats[f['name'][:-5]] = len(j.get('items') or [])
    wm = {
        'last_sync': '',
        'sources': src_stats,
        'total_items': n,
        'md001_new': n001,
        'prev_sync': prev.get('last_sync', ''),
    }
    save_watermark(wm)
    print('水位线已记 → %s' % WATERMARK)
    print('完成：各源共 %d 条已落地，001 新增 %d 条' % (n, n001))


def safe_load(path):
    txt = fetch_remote_file(path)
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except Exception:
        return {}


if __name__ == '__main__':
    main()