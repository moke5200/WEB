#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a20 · B站指定 UP 主投稿（需 Cookie）

盯野哥指定的一批 UP 主新发视频。
流程：UP 名 → 搜索 API 解析 UID（缓存）→ 投稿 API 取最新视频。
内容处理：本源只记视频条目（标题/链接/时间）。
字幕转写由 a19 底层模块 + 06 号私人 Skill 另做，不在本源重复。
"""
import datetime
import http.cookiejar
import json
import os
import urllib.parse
import urllib.request

from sources.base import Source

CK = r"E:\Google Drive\Agent 规则\Cookies 账号信息\www.bilibili.com_cookies.txt"
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "state", "bili_uids.json")
UPS = ["3Blue1Brown", "AI超元域", "双尾彗星", "固液", "国仁全球大学堂",
       "小王Albert", "席亚洲", "所长林超", "数字生命卡兹克", "施展世界",
       "波士顿圆脸", "程序员鱼皮", "翟东升老师", "观视频工作室",
       "金灿荣教授", "麒元视界"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class BiliUp(Source):
    id = "a20"
    name = "B站指定UP主投稿"
    category = "视频"
    freq = "1d"
    runs_on = "local"
    needs_login = True
    raw_lang = "zh"
    platform = "bilibili"

    def _opener(self):
        path = os.environ.get("BILI_COOKIE_FILE", CK)
        jar = http.cookiejar.MozillaCookieJar(path)
        jar.load(ignore_discard=True, ignore_expires=True)
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.addheaders = [("User-Agent", UA), ("Referer", "https://www.bilibili.com/")]
        return op

    def _uid(self, op, name):
        cache = {}
        if os.path.exists(CACHE):
            try:
                cache = json.load(open(CACHE, encoding="utf-8"))
            except Exception:
                pass
        if name in cache:
            return cache[name]
        url = ("https://api.bilibili.com/x/web-interface/search/type?search_type=bili_user&keyword="
               + urllib.parse.quote(name))
        with op.open(url, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        res = (d.get("data") or {}).get("result") or []
        uid = str(res[0].get("mid")) if res else ""
        if uid:
            cache[name] = uid
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            json.dump(cache, open(CACHE, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        return uid

    def fetch(self, cfg=None, seen=None):
        op = self._opener()
        items, failed = [], []
        for name in UPS:
            try:
                uid = self._uid(op, name)
                if not uid:
                    failed.append("解析UID失败:" + name)
                    continue
                url = ("https://api.bilibili.com/x/space/wbi/arc/search?mid=%s&ps=10&pn=1" % uid)
                with op.open(url, timeout=30) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                vlist = (((d.get("data") or {}).get("list") or {}).get("vlist") or [])
                for v in vlist:
                    bvid = v.get("bvid") or ""
                    if self.is_seen(seen, post_id=bvid, url=None):
                        continue
                    items.append(self.item(
                        title=v.get("title") or "", url="https://www.bilibili.com/video/%s" % bvid,
                        published=datetime.datetime.fromtimestamp(
                            v.get("created", 0), datetime.timezone(datetime.timedelta(hours=8))
                        ).strftime("%Y-%m-%d %H:%M") if v.get("created") else "",
                        author=name,
                        summary="B站新视频 · %s" % name,
                        tags=["视频", name],
                        extra={"post_id": bvid, "platform": "bilibili", "up": name},
                    ))
            except Exception as e:
                failed.append("%s:%s" % (name, str(e)[:50]))
        print("    [a20] %d 个UP → 收 %d 条新视频" % (len(UPS), len(items)), flush=True)
        return items, failed