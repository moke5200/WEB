#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSS 源通用基类：配 URL 就能用，减少重复代码。

子类只需设 id/name/url/keyword 过滤等，fetch() 已实现。
"""
from sources.base import Source
from core import rss
import time
import os

MAX_ITEMS = int(os.environ.get("RSS_MAX_ITEMS", "25"))


class RssSource(Source):
    url = ""
    keep_all = True          # False 时只用 keywords 过滤
    keywords = []            # 命中才收（keep_all=False 时）
    exclude = []             # 命中就丢
    platform = ""
    summary_prefix = ""

    def fetch(self, cfg=None, seen=None):
        if not self.url:
            return [], ["没配 URL"]
        via, st, body = self.get(self.url, prefer_direct=True, timeout=40)
        if st != 200 or not body:
            return [], ["抓取失败 http=%s via=%s" % (st, via)]
        rows = rss.parse_feed(body)
        print("    [%s] RSS 取 %d 条（via %s）" % (self.id, len(rows), via), flush=True)

        items, dropped = [], 0
        for r in rows[:MAX_ITEMS]:
            hits = r["title"] + " " + r["desc"]
            if any(k in hits for k in self.exclude):
                dropped += 1
                continue
            if not self.keep_all and self.keywords and not any(k in hits for k in self.keywords):
                dropped += 1
                continue
            pid = rss.post_id_from(r["url"])
            if self.is_seen(seen, post_id=pid or None, url=r["url"]):
                continue
            summary = (self.summary_prefix + r["desc"]).strip()[:180]
            items.append(self.item(
                title=r["title"], url=r["url"], published=r["time"],
                author="", summary=summary, tags=[self.category or "资讯"],
                extra={"post_id": pid, "platform": self.platform or self.id},
            ))
        print("    [%s] 收 %d 条（过滤 %d）" % (self.id, len(items), dropped), flush=True)
        return items, []
