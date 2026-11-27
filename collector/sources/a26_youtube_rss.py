#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a26 · YouTube 精选博主更新（免 Key RSS）

配置 CHANNELS：@用户名 或 UC... 频道 ID 都行。
@用户名 会自动解析成频道 ID（解析结果缓存到 state/yt_channels.json）。
抓 videos.xml?channel_id=...，标题/摘要翻中文。

野哥给频道时只需报 @用户名，不用自己找 UC 那串 ID。
"""
import datetime
import json
import os
import re
import urllib.parse
import urllib.request

from sources.base import Source
from core import rss, translate

# 要盯的频道（野哥给 @用户名，程序解析 ID）
CHANNELS = [
    "@luananye",     # ㄨ广野（主号频道）
]
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "state", "yt_channels.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def resolve_channel(ref):
    """@用户名 或 UC... → 频道 ID。"""
    if ref.startswith("UC") and len(ref) >= 24:
        return ref
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            pass
    if ref in cache:
        return cache[ref]
    url = "https://www.youtube.com/%s/about" % ref.lstrip("@")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read().decode("utf-8", "replace")
        m = re.search(r'"(?:channelId|externalId)":"(UC[a-zA-Z0-9_-]{22})"', t)
        if m:
            cid = m.group(1)
            cache[ref] = cid
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            return cid
    except Exception:
        pass
    return ""


class YoutubeRss(Source):
    id = "a26"
    name = "YouTube 精选博主"
    category = "视频"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "en"
    platform = "youtube"

    def fetch(self, cfg=None, seen=None):
        items = []
        for ref in CHANNELS:
            cid = resolve_channel(ref)
            if not cid:
                print("    [a26] 解析频道失败: %s" % ref, flush=True)
                continue
            url = "https://www.youtube.com/feeds/videos.xml?channel_id=%s" % cid
            via, st, body = self.get(url, prefer_direct=True, timeout=40)
            if st != 200 or not body:
                print("    [a26] %s RSS 失败 http=%s" % (ref, st), flush=True)
                continue
            entries = re.findall(r"<entry>.*?</entry>", body, re.S)
            print("    [a26] %s 取 %d 条视频" % (ref, len(entries)), flush=True)
            for e in entries:
                title = rss.pick(r"<title>(.*?)</title>", e)
                link = rss.pick(r"<link[^>]*href=\"([^\"]+)\"", e)
                vid = rss.pick(r"<yt:videoId>(.*?)</yt:videoId>", e)
                pub = rss.pick(r"<published>(.*?)</published>", e)
                desc = rss.pick(r"<media:description>(.*?)</media:description>", e)[:150]
                if self.is_seen(seen, post_id=vid or None, url=link):
                    continue
                zh = translate.to_zh(desc) if desc else ""
                items.append(self.item(
                    title=title, url=link, published=rss.to_bj(pub),
                    summary=("视频简介：%s" % zh) if zh else "YouTube 新视频",
                    tags=["视频", ref],
                    extra={"post_id": vid, "platform": "youtube", "channel": ref},
                ))
        return items, []
