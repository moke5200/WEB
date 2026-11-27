#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a15 · HackerNews（近 24h ≥80 分，过滤纯捧场/灌水，翻中文）

用 Algolia API，不用 RSS。
原文要求：先过滤掉纯名人捧场/情绪灌水高赞贴，只留有实操/工具价值的并翻译。
"""
import json
import time
import urllib.parse

from sources.base import Source
from core import translate

NOISE = ["Show HN: just for fun", "Ask HN: what's your favorite", " RIP ",
         "passes away", "obituary", "rest in peace", "celebrates", "birthday"]
# 有实操价值的信号（命中优先留）
VALUE = ["github.com", "tool", "open source", "released", "launch", "how to",
         "tutorial", "guide", "benchmark", "library", "framework", "api"]


class HackerNews(Source):
    id = "a15"
    name = "HackerNews"
    category = "英文资讯"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "en"
    platform = "hn"
    summary_prefix = "HN 热帖："

    def fetch(self, cfg=None, seen=None):
        since = int(time.time()) - 86400
        url = ("https://hn.algolia.com/api/v1/search_by_date?tags=story"
               "&numericFilters=created_at_i>%d,points>=80&hitsPerPage=40" % since)
        via, st, body = self.get(url, prefer_direct=True, timeout=40)
        if st != 200 or not body:
            return [], ["HN API 失败 http=%s" % st]
        try:
            hits = json.loads(body).get("hits", [])
        except Exception as e:
            return [], ["HN 解析失败 %s" % str(e)[:80]]

        items = []
        for h in hits:
            title = h.get("title") or ""
            if not title:
                continue
            low = title.lower()
            if any(n.lower() in low for n in NOISE):
                # 捧场/灌水：没有实操信号就丢
                if not any(v in low for v in VALUE):
                    continue
            oid = str(h.get("objectID") or "")
            link = h.get("url") or ("https://news.ycombinator.com/item?id=%s" % oid)
            if self.is_seen(seen, post_id=oid, url=link):
                continue
            points = h.get("points") or 0
            # 摘要翻中文（只翻标题本身，HN 没描述）
            zh = translate.to_zh(title)
            items.append(self.item(
                title=title, url=link, published="",
                summary="%s%d 分 · %s" % (self.summary_prefix, points, zh or title),
                tags=["英文资讯", "已翻译" if zh != title else "未翻译"],
                extra={"post_id": oid, "platform": "hn", "points": points,
                       "hn_url": "https://news.ycombinator.com/item?id=%s" % oid},
            ))
        print("    [a15] HN 取 %d 条 → 收 %d 条" % (len(hits), len(items)), flush=True)
        return items, []
