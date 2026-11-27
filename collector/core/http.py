#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 抓取：带 UA、重试、可选 Jina 中转（绕 Cloudflare）。"""
import time
import urllib.request
import urllib.error
import os

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
JINA_PREFIX = "https://r.jina.ai/"

# 记录本次运行走了多少 Jina 请求，方便控制额度（免费档 20 RPM）
JINA_CALLS = {"count": 0}
JINA_MIN_INTERVAL = float(os.environ.get("JINA_MIN_INTERVAL", "4"))


def _sleep_jina():
    """Jina 免费档 20 RPM，调用间至少隔 JINA_MIN_INTERVAL 秒。"""
    time.sleep(JINA_MIN_INTERVAL)


def http_get(url, timeout=60, retries=3, headers=None, backoff=(2, 5, 10)):
    """直连 GET，失败按 backoff 重试。返回 (status, text)。"""
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if headers:
        h.update(headers)
    last = ""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code in (401, 403, 404):
                return e.code, ""
            time.sleep(backoff[min(i, len(backoff) - 1)])
        except Exception as e:
            last = type(e).__name__ + ": " + str(e)[:120]
            time.sleep(backoff[min(i, len(backoff) - 1)])
    return -1, last


def get_via_jina(url, timeout=90, retries=2):
    """通过 r.jina.ai 中转（Cloudflare 429 时用）。返回 (status, markdown_text)。"""
    target = JINA_PREFIX + url
    for i in range(retries):
        JINA_CALLS["count"] += 1
        status, text = http_get(target, timeout=timeout, retries=1,
                                headers={"X-Return-Format": "markdown"})
        if status == 200 and text and len(text) > 200:
            _sleep_jina()
            return 200, text
        time.sleep(3 + i * 3)
    return -1, ""


def get_smart(url, prefer_direct=True, timeout=60):
    """能直连就直连，被 429/403 挡住才走 Jina。返回 (via, status, text)。"""
    if prefer_direct:
        status, text = http_get(url, timeout=timeout, retries=1)
        if status == 200 and text:
            return "direct", status, text
        if status not in (429, 403, -1):
            return "direct", status, text
    status, text = get_via_jina(url, timeout=timeout + 30)
    return "jina", status, text