#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a20 · B站指定 UP 主投稿（需 Cookie + WBI 签名）

发现新视频 = 转写任务的上游（对应「DSH用 B站转写水位线.md」里每个UP扫到哪条）。
本源只做「发现」，不取字幕、不转写（那是独立任务 bili_subtitle.py 的事）。

UID 来源：优先读水位线文件里的 space.bilibili.com/<uid>（现成 24 个，避开搜索API风控）。
"""
import datetime
import http.cookiejar
import io
import os
import re

from sources.base import Source
from core.wbi import Wbi

CK = r"E:\Google Drive\Agent 规则\Cookies 账号信息\www.bilibili.com_cookies.txt"
WATERLINE = r"E:\Google Drive\Agent 收集\B站\DSH用 B站转写水位线.md"


def load_ups():
    """从水位线文件读 (UP名, uid) 列表。"""
    ups = []
    if not os.path.exists(WATERLINE):
        return ups
    txt = io.open(WATERLINE, encoding="utf-8").read()
    for m in re.finditer(r'\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*https://space\.bilibili\.com/(\d+)', txt):
        ups.append((m.group(1).strip(), m.group(2)))
    return ups


class BiliUp(Source):
    id = "a20"
    name = "B站指定UP主投稿"
    category = "视频"
    freq = "1d"
    runs_on = "local"
    needs_login = True
    raw_lang = "zh"
    platform = "bilibili"

    def fetch(self, cfg=None, seen=None):
        ups = load_ups()
        if not ups:
            return [], ["水位线文件没读到 UP 列表"]
        path = os.environ.get("BILI_COOKIE_FILE", CK)
        jar = http.cookiejar.MozillaCookieJar(path)
        jar.load(ignore_discard=True, ignore_expires=True)
        wbi = Wbi(jar, gap=6)          # 串行慢速，野哥要求不并发
        ok, uname = wbi.login_ok()
        if not ok:
            return [], ["B站登录态失效"]
        print("    [a20] 登录 OK: %s | %d 个UP" % (uname, len(ups)), flush=True)

        items, failed = [], []
        for name, uid in ups:
            try:
                url = wbi.sign_url("/x/space/wbi/arc/search",
                                   {"mid": uid, "ps": 10, "pn": 1})
                d = wbi.get_json(url)
                if d.get("code") != 0:
                    failed.append("%s:code%s" % (name, d.get("code")))
                    continue
                vlist = (((d.get("data") or {}).get("list") or {}).get("vlist") or [])
                for v in vlist:
                    bvid = v.get("bvid") or ""
                    if self.is_seen(seen, post_id=bvid, url=None):
                        continue
                    created = v.get("created") or 0
                    pub = (datetime.datetime.fromtimestamp(
                        created, datetime.timezone(datetime.timedelta(hours=8))
                    ).strftime("%Y-%m-%d %H:%M") if created else "")
                    items.append(self.item(
                        title=v.get("title") or "",
                        url="https://www.bilibili.com/video/%s" % bvid,
                        published=pub, author=name,
                        summary="B站新视频 · %s" % name,
                        tags=["视频", name],
                        extra={"post_id": bvid, "platform": "bilibili", "up": name},
                    ))
            except Exception as e:
                failed.append("%s:%s" % (name, str(e)[:40]))
        print("    [a20] %d 个UP → 收 %d 条新视频（失败 %d）"
              % (len(ups), len(items), len(failed)), flush=True)
        return items, failed