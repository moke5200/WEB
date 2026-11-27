#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B站 WBI 签名公共模块（从 bili_subtitle.py 提炼）。

用法：
    wbi = Wbi(jar)              # jar 是已加载的 CookieJar
    url = wbi.sign_url('/x/space/wbi/arc/search', {'mid': uid, 'ps': 10, 'pn': 1})
    data = wbi.get_json(url)    # 串行慢速请求

签名算法：nav 取 wbi_img → img_key+sub_key 按 MIXIN_TAB 重排得 mixin_key
         → 参数排序+URL编码 → md5(query + mixin_key) = w_rid
反爬：串行 + 每次请求间隔 GAP 秒，不并发、不重试轰炸。
"""
import hashlib
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request

MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
             61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62,
             11, 36, 20, 34, 44, 52]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122 Safari/537.36")
GAP = 6   # 请求间隔秒数（野哥要求：串行慢速，不并发）


class Wbi:
    def __init__(self, jar, gap=GAP):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.op.addheaders = [("User-Agent", UA), ("Referer", "https://www.bilibili.com/"),
                              ("Accept", "application/json, text/plain, */*")]
        self.gap = gap
        self._mixin = None
        self._nav = None

    def get_json(self, url, gap=None):
        time.sleep(self.gap if gap is None else gap)
        with self.op.open(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def login_ok(self):
        """验证登录 + 缓存 mixin_key，返回 (isLogin, uname)。"""
        self._nav = self.get_json("https://api.bilibili.com/x/web-interface/nav", gap=1)
        d = self._nav.get("data") or {}
        wbi = d.get("wbi_img") or {}
        if wbi.get("img_url") and wbi.get("sub_url"):
            self._mixin = self._mixin_key(wbi["img_url"], wbi["sub_url"])
        return bool(d.get("isLogin")), d.get("uname", "")

    @staticmethod
    def _mixin_key(img_url, sub_url):
        import re
        key = lambda u: re.split(r'[/?]', u)[-1].split(".")[0]
        raw = key(img_url) + key(sub_url)
        return "".join(raw[i] for i in MIXIN_TAB if i < len(raw))[:32]

    def sign_url(self, path, params):
        """给 /x/... 接口签名，返回完整 URL。"""
        if not self._mixin:
            self.login_ok()
        if not self._mixin:
            raise RuntimeError("mixin_key 为空，可能没登录")

        def enc(s):
            s = str(s)
            for ch in "!'()*":
                s = s.replace(ch, "")
            return urllib.parse.quote(s, safe="")

        p = dict(params)
        p["wts"] = int(time.time())
        q = "&".join("%s=%s" % (k, enc(p[k])) for k in sorted(p))
        w_rid = hashlib.md5((q + self._mixin).encode()).hexdigest()
        return "https://api.bilibili.com%s?%s&w_rid=%s" % (path, q, w_rid)
