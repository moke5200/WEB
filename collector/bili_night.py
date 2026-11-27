#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""B站凌晨流程（每天 03:00）：转写白天排队的音频 → 存文稿 → 删音频。

队列：collector/state/audio_queue/<BV号>.m4a + <BV号>.json(元数据)
转写：调用本地 shared-video-transcriber 的 /api/local/jobs（path + mode:transcript）
完成后：
  · 文稿存到 E:\Google Drive\Agent 收集\B站\B站 视频文稿\<UP>\<标题>.md
  · 删除音频 .m4a 和 .json
  · 记录到台账（source=bili_transcribed）

串行处理，一个转完再下一个。转写服务在 127.0.0.1:7860。
用法：python bili_night.py [--dry-run]
"""
import datetime
import io
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core.ledger import Ledger

BASE = "http://127.0.0.1:7860"
AUDIO_Q = os.path.join(HERE, "state", "audio_queue")
OUTROOT = r"E:\Google Drive\Agent 收集\B站\B站 视频文稿"
POLL_SEC = 15
MAX_WAIT = 3600     # 单视频最长 1 小时


def token():
    with urllib.request.urlopen(urllib.request.Request(BASE + "/api/health"), timeout=15) as r:
        return json.loads(r.read().decode()).get("token")


def api(tk, method, path, body=None):
    h = {"Content-Type": "application/json", "X-Video-Token": tk}
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body else None,
                                 headers=h, method=method)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def safe_name(s, n=80):
    return re.sub(r'[\\/:*?"<>|]', '-', (s or '').strip())[:n]


def save_md(owner, title, bvid, transcript, source_note):
    outdir = os.path.join(OUTROOT, owner)
    os.makedirs(outdir, exist_ok=True)
    # 繁转简（可选，opencc 装了就用）
    try:
        from opencc import OpenCC
        transcript = OpenCC("t2s").convert(transcript)
    except Exception:
        pass
    lines = [l.strip() for l in (transcript or "").split("\n") if l.strip()]
    fp = os.path.join(outdir, safe_name(title) + ".md")
    base = fp[:-3]; i = 1
    while os.path.exists(fp):
        i += 1; fp = "%s_%02d.md" % (base, i)
    head = ("# %s\n\n- BV：%s\n- UP：%s\n- 来源：%s\n- 转写：%s\n\n---\n\n"
            % (title, bvid, owner, source_note,
               datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    io.open(fp, "w", encoding="utf-8").write(head + "\n".join(lines) + "\n")
    return fp, len(lines)


def transcribe_audio(tk, audio_path, meta):
    """建本地转写任务并轮询到完成。返回 transcript 或 None。"""
    res = api(tk, "POST", "/api/local/jobs", {
        "path": audio_path, "mode": "transcript", "profile": "balanced",
        "language": "zh", "cleanup_after": False,
        "reference_url": meta.get("url", ""),
        "context_notes": "UP主：%s；标题：%s" % (meta.get("up", ""), meta.get("title", "")),
    })
    jid = res.get("id")
    if not jid:
        print("    建任务失败: %s" % str(res)[:200], flush=True)
        return None
    print("    job=%s 转写中..." % jid, flush=True)
    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        time.sleep(POLL_SEC)
        try:
            j = api(tk, "GET", "/api/jobs/" + jid)
        except Exception:
            continue
        st = j.get("status")
        if st in ("done",):
            return j.get("transcript") or ""
        if st in ("error", "cancelled", "interrupted"):
            print("    转写失败: %s %s" % (st, str(j.get("error"))[:150]), flush=True)
            return None
    print("    转写超时", flush=True)
    return None


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.isdir(AUDIO_Q):
        print("没有音频队列，退出", flush=True)
        return
    metas = [f for f in os.listdir(AUDIO_Q) if f.endswith(".json")]
    if not metas:
        print("音频队列为空，退出", flush=True)
        return
    print("B站凌晨流程 | 待转写 %d 个音频" % len(metas), flush=True)

    tk = token()
    lg = Ledger()
    ok_n = fail_n = 0
    for mf in sorted(metas):
        bvid = mf[:-5]
        af = os.path.join(AUDIO_Q, bvid + ".m4a")
        # 也接受 .webm/.mp3
        if not os.path.exists(af):
            for ext in (".webm", ".mp3", ".wav", ".m4a"):
                p = os.path.join(AUDIO_Q, bvid + ext)
                if os.path.exists(p):
                    af = p; break
        if not os.path.exists(af):
            print("    %s 音频文件不存在，跳过" % bvid, flush=True)
            continue
        meta = json.load(io.open(os.path.join(AUDIO_Q, mf), encoding="utf-8"))
        if dry:
            print("    [dry] %s | %s | %s" % (bvid, meta.get("up"), meta.get("title", "")[:40]), flush=True)
            continue
        print("  处理 %s | %s | %s" % (bvid, meta.get("up"), meta.get("title", "")[:40]), flush=True)
        transcript = transcribe_audio(tk, af, meta)
        if transcript:
            fp, n = save_md(meta.get("up", "未分类"), meta.get("title") or bvid,
                            bvid, transcript, "B站音频转写")
            lg.mark("bilibili", bvid, meta.get("url", ""), "bili_transcribed")
            print("    ✓ %d 行 → %s" % (n, os.path.basename(fp)), flush=True)
            ok_n += 1
        else:
            fail_n += 1
        # 无论成功失败都删音频（失败的可从台账看出没转写成功）
        for ext in (".m4a", ".webm", ".mp3", ".wav"):
            p = os.path.join(AUDIO_Q, bvid + ext)
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
        try: os.remove(os.path.join(AUDIO_Q, mf))
        except Exception: pass

    if not dry:
        lg.save()
    print("完成：成功 %d / 失败 %d" % (ok_n, fail_n), flush=True)


if __name__ == "__main__":
    main()