#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""B站白天流程（跟着采集轮跑）：

对每个 UP 的新视频：
  1) 查字幕（WBI）：有 ai-zh 字幕 → 直接取回存文稿（.md）
  2) 无字幕 → yt-dlp 下载音频到 audio_queue/ 排队，等凌晨3点转写
  3) 充电专属 → 跳过（拿不到音频）

去重：全部记进统一台账（platform=bilibili, post_id=BV号），处理过的不再碰。
输出文稿：E:\Google Drive\Agent 收集\B站\B站 视频文稿\<UP名>\<标题>.md
音频队列：collector/state/audio_queue/ 下 <BV号>.m4a + <BV号>.json(元数据)

用法：python bili_daily.py [--dry-run] [--max N]
"""
import datetime
import http.cookiejar
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core.wbi import Wbi
from core.ledger import Ledger

CK = r"E:\Google Drive\Agent 规则\Cookies 账号信息\www.bilibili.com_cookies.txt"
INSTR = r"E:\Google Drive\Agent 规则\07-定时任务\00-DSH-多源信息收集指令.md"
WATERLINE = r"E:\Google Drive\Agent 收集\B站\DSH用 B站转写水位线.md"
OUTROOT = r"E:\Google Drive\Agent 收集\B站\B站 视频文稿"
AUDIO_Q = os.path.join(HERE, "state", "audio_queue")
PY = sys.executable


def load_ups():
    """从整合指令「UP主名单」表读（29 个，含 11-28 新加的瓜子项目社/网赚库）。
    他们的 UID 在表里；没写的从水位线表补。"""
    ups, seen = [], set()
    # 1) 新指令：| # | UP主 | UID | 备注 |
    if os.path.exists(INSTR):
        txt = io.open(INSTR, encoding='utf-8').read()
        sec = txt.split('### UP主名单', 1)[-1].split('### 待转写链接清单', 1)[0] \
            if '### UP主名单' in txt else ''
        for m in re.finditer(r'\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*(\d+)?\s*\|', sec):
            name, uid = m.group(1).strip(), (m.group(2) or '').strip()
            if name and name not in seen:
                seen.add(name); ups.append((name, uid))
    # 1.5) 新指令的「UP主清单」表（27 个带主页 URL）
    if os.path.exists(INSTR):
        txt = io.open(INSTR, encoding='utf-8').read()
        sec = txt.split('### UP主清单', 1)[-1].split('---', 1)[0] if '### UP主清单' in txt else ''
        for m in re.finditer(r'\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*https://space\.bilibili\.com/(\d+)', sec):
            name, uid = m.group(1).strip(), m.group(2)
            if name not in seen:
                seen.add(name); ups.append((name, uid))
            else:
                idx = [u[0] for u in ups].index(name)
                if not ups[idx][1]:
                    ups[idx] = (name, uid)
    # 2) 水位线：| # | UP主 | 主页URL | ...
    if os.path.exists(WATERLINE):
        txt = io.open(WATERLINE, encoding='utf-8').read()
        for m in re.finditer(r'\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*https://space\.bilibili\.com/(\d+)', txt):
            name, uid = m.group(1).strip(), m.group(2)
            if name in seen:
                # 补 UID（新指令表里很多人 UID 空着）
                idx = [u[0] for u in ups].index(name)
                if not ups[idx][1]:
                    ups[idx] = (name, uid)
            else:
                seen.add(name); ups.append((name, uid))
    # 别名归一（指令里简称 vs 水位线全称）——按 UID 补齐后保留
    return [(n, u) for n, u in ups if u]


def safe_name(s, n=80):
    return re.sub(r'[\\/:*?"<>|]', '-', (s or '').strip())[:n]


def save_subtitle_md(owner, title, bvid, lines):
    """存字幕文稿到 UP 文件夹。"""
    outdir = os.path.join(OUTROOT, owner)
    os.makedirs(outdir, exist_ok=True)
    fp = os.path.join(outdir, safe_name(title) + ".md")
    base = fp[:-3]; i = 1
    while os.path.exists(fp):
        i += 1; fp = "%s_%02d.md" % (base, i)
    head = ("# %s\n\n- 原视频：https://www.bilibili.com/video/%s/\n"
            "- UP主：%s\n- 来源：B站 AI 字幕\n- 转存：%s\n\n---\n\n") % (
        title, bvid, owner, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    io.open(fp, 'w', encoding='utf-8').write(head + "\n".join(lines) + "\n")
    return fp


def get_subtitle(wbi, bvid):
    """返回 (title, subtitle_lines) 或 (title, None)。None=无字幕。"""
    v = wbi.get_json("https://api.bilibili.com/x/web-interface/view?bvid=" + bvid, gap=2)
    d = v.get("data") or {}
    if d.get("is_upower_exclusive"):
        return (d.get("title") or bvid), "CHARGE"
    aid, cid = d.get("aid"), d.get("cid")
    if not aid or not cid:
        return (d.get("title") or bvid), None
    u = wbi.sign_url("/x/player/wbi/v2", {"aid": aid, "bvid": bvid, "cid": cid})
    p = wbi.get_json(u, gap=2)
    pd = p.get("data") or {}
    subs = ((pd.get("subtitle") or {}).get("subtitles") or [])
    if not subs:
        return (d.get("title") or bvid), None
    target = next((s for s in subs if s.get("lan") == "ai-zh"), subs[0])
    url = target.get("subtitle_url") or ""
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        return (d.get("title") or bvid), None
    sj = wbi.get_json(url, gap=2)
    body = sj.get("body") or []
    lines = [x.get("content", "") for x in body if x.get("content")]
    return (d.get("title") or bvid), lines


def download_audio(bvid, meta):
    """yt-dlp 下音频到队列。返回是否成功。"""
    outtmpl = os.path.join(AUDIO_Q, bvid + ".%(ext)s")
    cmd = [PY, "-m", "yt_dlp", "-f", "bestaudio", "-o", outtmpl, "--no-warnings",
           "https://www.bilibili.com/video/%s/" % bvid]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0:
            print("    [bili] yt-dlp 失败 %s: %s" % (bvid, r.stderr.decode('utf-8', 'replace')[-200:]), flush=True)
            return False
        # 写元数据
        mf = os.path.join(AUDIO_Q, bvid + ".json")
        io.open(mf, 'w', encoding='utf-8').write(json.dumps(meta, ensure_ascii=False, indent=1))
        return True
    except Exception as e:
        print("    [bili] 下载异常 %s: %s" % (bvid, str(e)[:100]), flush=True)
        return False


def main():
    dry = '--dry-run' in sys.argv
    full_scan = '--full-scan' in sys.argv   # 新UP回填：翻页直到 2026-06-01
    import datetime as _dt
    CUTOFF_TS = int(_dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc).timestamp())
    max_n = 10
    if '--max' in sys.argv:
        try:
            max_n = int(sys.argv[sys.argv.index('--max') + 1])
        except Exception:
            pass

    ups = load_ups()
    if '--ups' in sys.argv:
        only = sys.argv[sys.argv.index('--ups') + 1].split(',')
        ups = [(n, u) for n, u in ups if n in only]
        print('只处理指定UP：%s' % ', '.join(n for n, _ in ups), flush=True)
    os.makedirs(AUDIO_Q, exist_ok=True)
    jar = http.cookiejar.MozillaCookieJar(CK)
    jar.load(ignore_discard=True, ignore_expires=True)
    wbi = Wbi(jar, gap=6)
    ok, uname = wbi.login_ok()
    if not ok:
        print("B站登录态失效，退出", flush=True)
        sys.exit(1)
    print("B站白天流程 | 登录 %s | %d 个UP" % (uname, len(ups)), flush=True)

    lg = Ledger()
    # 收集每个UP最新视频（只处理水位线之后的）
    wl = {}
    if os.path.exists(WATERLINE):
        t = io.open(WATERLINE, encoding='utf-8').read()
        for m in re.finditer(r'\|\s*\d+\s*\|\s*([^|]+?)\s*\|[^|]*\|\s*(BV[0-9A-Za-z]+)\s*\|', t):
            wl[m.group(1).strip()] = m.group(2).strip()

    processed = 0
    newest_bv = {}      # name -> (bv, date) 本轮扫到的最新
    for name, uid in ups:
        if processed >= max_n:
            break
        try:
            vlist = []
            # full_scan：翻页直到 6/1（新UP回填）；否则只取第 1 页
            max_pages = 30 if full_scan else 1
            for pn in range(1, max_pages + 1):
                url = wbi.sign_url("/x/space/wbi/arc/search",
                                   {"mid": uid, "ps": 30, "pn": pn})
                d = wbi.get_json(url)
                page = (((d.get("data") or {}).get("list") or {}).get("vlist") or [])
                if not page:
                    break
                vlist.extend(page)
                if not full_scan:
                    break
                # 翻到 6/1 之前就停
                if page[-1].get("created", 0) < CUTOFF_TS:
                    break
            # 从最新往下，遇到水位线就停（full_scan 时用 6/1 截止）
            for v in vlist:
                if processed >= max_n:
                    break
                bvid = v.get("bvid") or ""
                if not bvid:
                    continue
                created = v.get("created") or 0
                if full_scan and created and created < CUTOFF_TS:
                    break
                if bvid == wl.get(name):
                    break
                if lg.is_seen("bilibili", bvid, None):
                    continue
                if dry:
                    print("    [dry] %s | %s | %s" % (name, bvid, (v.get('title') or '')[:40]), flush=True)
                    processed += 1
                    continue
                title, subs = get_subtitle(wbi, bvid)
                if subs == "CHARGE":
                    lg.mark("bilibili", bvid, "https://www.bilibili.com/video/%s" % bvid, "bili_charge")
                    print("    [bili] %s 充电专属，跳过" % bvid, flush=True)
                elif subs:
                    fp = save_subtitle_md(name, title, bvid, subs)
                    lg.mark("bilibili", bvid, "https://www.bilibili.com/video/%s" % bvid, "bili_subtitle")
                    print("    [bili] %s 字幕 %d 行 → %s" % (bvid, len(subs), os.path.basename(fp)), flush=True)
                else:
                    meta = {"bvid": bvid, "up": name, "title": title,
                            "url": "https://www.bilibili.com/video/%s" % bvid,
                            "queued": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
                    if download_audio(bvid, meta):
                        lg.mark("bilibili", bvid, meta["url"], "bili_audio_queued")
                        print("    [bili] %s 无字幕 → 音频已排队" % bvid, flush=True)
                processed += 1
        except Exception as e:
            print("    [bili] %s 处理失败: %s" % (name, str(e)[:100]), flush=True)
        # 记本轮该 UP 扫到的最新 BV（第一条即最新，无论是否已处理过）
        if vlist:
            top = vlist[0]
            tb = top.get("bvid") or ""
            tc = top.get("created") or 0
            if tb and tc:
                newest_bv[name] = (tb, datetime.datetime.fromtimestamp(
                    tc, datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d'))
                if dry:
                    print("    [dry] 水位线 %s → %s (%s)" % (name, tb, newest_bv[name][1]), flush=True)

    if not dry:
        lg.save()
        # 更新水位线：每个 UP 记本轮扫到的最新 BV 和日期
        if newest_bv:
            update_waterline(newest_bv)
    print("本轮处理 %d 个视频" % processed, flush=True)


def update_waterline(newest_bv):
    """把本轮每个 UP 扫到的最新 BV 写回水位线（保留 UID 和未扫到的行）。"""
    if not os.path.exists(WATERLINE):
        return
    t = io.open(WATERLINE, encoding='utf-8').read()
    lines = t.splitlines()
    out = []
    for ln in lines:
        m = re.match(r'\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*(https://space\.bilibili\.com/\d+)\s*\|'
                     r'\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|', ln)
        if m:
            idx, name, home, bv, dt = m.groups()
            if name.strip() in newest_bv:
                nbv, ndt = newest_bv[name.strip()]
                ln = '| %s | %s | %s | %s | %s |' % (idx, name.strip(), home, nbv, ndt)
        out.append(ln)
    io.open(WATERLINE, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print("  水位线已更新 %d 个 UP" % len(newest_bv), flush=True)


if __name__ == '__main__':
    main()