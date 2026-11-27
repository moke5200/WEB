#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""b29 · 瑞客论坛（需 Cookie）：每日签到 + 资源杂烩版新帖

Cookie: Cookie 账号信息/www.ruike1.com_cookies.txt（Netscape 格式）
用 HTTPCookieProcessor 加载，不走 Jina（Jina 没有登录态）。
版块：forum-51 = 资源杂烩（GBK 编码页面）。

签到：只报告状态，不擅自签（野哥有专门签到流程在跑）。
"""
import datetime
import http.cookiejar
import os
import re
import sys
import urllib.request

from sources.base import Source

BASE = "https://www.ruike1.com"
FORUM = BASE + "/forum-51-1.html"
DEFAULT_CK = r"E:\Google Drive\Agent 规则\Cookies 账号信息\www.ruike1.com_cookies.txt"


class Ruike(Source):
    id = "b29"
    name = "瑞客论坛"
    category = "论坛"
    freq = "1d"
    runs_on = "cloud"
    needs_login = True
    raw_lang = "zh"
    platform = "ruike"

    def _opener(self):
        path = os.environ.get("RUIKE_COOKIE_FILE", DEFAULT_CK)
        if not os.path.exists(path):
            raise FileNotFoundError("瑞客 cookie 不存在: %s" % path)
        jar = http.cookiejar.MozillaCookieJar(path)
        jar.load(ignore_discard=True, ignore_expires=True)
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.addheaders = [("User-Agent", self.__class__.UA if hasattr(self.__class__, 'UA')
                          else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 Chrome/131.0 Safari/537.36")]
        return op

    def fetch(self, cfg=None, seen=None):
        op = self._opener()
        with op.open(FORUM, timeout=40) as r:
            raw = r.read()
        html = raw.decode("gbk", "replace")

        items = []
        # 帖子链接：thread-<tid>-1-1.html
        for m in re.finditer(r'href="thread-(\d+)-1-1\.html"[^>]*>([^<]{4,120})', html):
            tid, title = m.group(1), m.group(2).strip()
            if not title or self.is_seen(seen, post_id=tid, url=None):
                continue
            link = "%s/thread-%s-1-1.html" % (BASE, tid)
            items.append(self.item(
                title=title, url=link, published="",
                summary="瑞客资源杂烩 · 新帖",
                tags=["论坛", "资源"],
                extra={"post_id": tid, "platform": "ruike"},
            ))
        print("    [b29] 资源杂烩取 %d 条新帖" % len(items), flush=True)
        return items, []