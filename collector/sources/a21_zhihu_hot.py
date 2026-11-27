#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a21 · 知乎热榜（需 Cookie，公开接口）

文档要求：过滤掉娱乐八卦水贴，只留有工具/行业价值的条目。
链接修正：API 返回 api.zhihu.com/questions/<id> → www.zhihu.com/question/<id>
"""
import http.cookiejar
import json
import os
import re
import urllib.request

from sources.base import Source

CK = r"E:\Google Drive\Agent 规则\Cookies 账号信息\www.zhihu.com_cookies.txt"
API = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50&desktop=true"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 娱乐八卦/情绪水贴特征（命中就丢）
NOISE = [
    # 娱乐圈
    r"如何评价.*明星", r"娱乐圈", r"恋情", r"官宣", r"粉丝", r"综艺", r"演唱会",
    r"网红", r"塌房", r"狗仔", r"坐姿", r"穿搭", r"颜值", r"恋爱", r"分手",
    # 社会八卦/家长里短
    r"孩子.*索赔", r"酒店.*摆件", r"女子.*男子", r"婆婆", r"婆媳", r"相亲",
    r"为什么.*女生", r"如何评价.*演员", r"获赔.*万", r"索赔.*万",
    r"如何看待.*结婚", r"离婚", r"出轨", r"彩礼",
]


class ZhihuHot(Source):
    id = "a21"
    name = "知乎热榜"
    category = "资讯"
    freq = "6h"
    runs_on = "local"
    needs_login = True
    raw_lang = "zh"
    platform = "zhihu"

    def fetch(self, cfg=None, seen=None):
        path = os.environ.get("ZHIHU_COOKIE_FILE", CK)
        jar = http.cookiejar.MozillaCookieJar(path)
        jar.load(ignore_discard=True, ignore_expires=True)
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.addheaders = [("User-Agent", UA), ("Referer", "https://www.zhihu.com/")]
        with op.open(API, timeout=40) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        rows = d.get("data") or []

        items, dropped = [], 0
        for x in rows:
            tgt = x.get("target") or {}
            title = tgt.get("title") or ""
            if not title:
                continue
            # 娱乐八卦过滤（用正则，别太宽松）
            if any(re.search(k, title) for k in NOISE):
                dropped += 1
                continue
            qid = str(tgt.get("id") or "")
            # 链接归一
            url = tgt.get("url") or ""
            m = re.search(r"/questions?/(\d+)", url)
            if m:
                url = "https://www.zhihu.com/question/%s" % m.group(1)
                qid = m.group(1)
            elif qid:
                url = "https://www.zhihu.com/question/%s" % qid
            if self.is_seen(seen, post_id=qid or None, url=url):
                continue
            items.append(self.item(
                title=title, url=url, published="",
                summary="知乎热榜 · %s" % (x.get("detail_text") or ""),
                tags=["热榜", "行业"],
                extra={"post_id": qid, "platform": "zhihu",
                       "hot": x.get("detail_text", "")},
            ))
        print("    [a21] 知乎热榜 %d 条 → 收 %d（过滤水贴 %d）"
              % (len(rows), len(items), dropped), flush=True)
        return items, []