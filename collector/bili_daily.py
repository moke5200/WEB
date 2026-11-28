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
WATERLINE = r"E:\Google Drive\Agent 收集\B站\DSH用 B站转写水位线.md"
OUTROOT = r"E:\Google Drive\Agent 收集\B站\B站 视频文稿"
AUDIO_Q = os.path.join(HERE, "state", "audio_queue")
PY = sys.executable


def load_ups():
    ups = []
    if not os.path.exists(WATERLINE):
        return ups
    txt = io.open(WATERLINE, encoding="utf-8").read()
    for m in re.finditer(r'\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*https://space\.bilibili\.com/(\d+)', txt):
        ups.append((m.group(1).strip(), m.group(2)))
    return ups


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
    max_n = 10
    if '--max' in sys.argv:
        try:
            max_n = int(sys.argv[sys.argv.index('--max') + 1])
        except Exception:
            pass

    ups = load_ups()
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
    for name, uid in ups:
        if processed >= max_n:
            break
        try:
            url = wbi.sign_url("/x/space/wbi/arc/search", {"mid": uid, "ps": 10, "pn": 1})
            d = wbi.get_json(url)
            vlist = (((d.get("data") or {}).get("list") or {}).get("vlist") or [])
            # 从最新往下，遇到水位线就停
            for v in vlist:
                if processed >= max_n:
                    break
                bvid = v.get("bvid") or ""
                if not bvid:
                    continue
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

    if not dry:
        lg.save()
    # 更新水位线（每个UP扫到的最新BV）
    print("本轮处理 %d 个视频" % processed, flush=True)


if __name__ == '__main__':
    main()