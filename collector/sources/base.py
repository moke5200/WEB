#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源基类：每个源只需实现 fetch()，其余（去重/翻译/输出）由核心层统一做。"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.item import Item          # noqa: E402
from core import http, translate, output   # noqa: E402


def now_bj(fmt="%Y-%m-%d %H:%M"):
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime(fmt)


class Source:
    # ---- 子类必须覆盖 ----
    id = ""                 # 如 a01
    name = ""               # 中文名，如「linux.do 云资源」
    category = ""           # 分类，用于页面分区
    freq = "6h"             # 频率标记（调度器用）
    runs_on = "cloud"       # cloud | local
    cross_source_dedup = True    # 默认参与跨源判重（指令铁律 3：全源统一台账）
    needs_login = False     # 是否需要 cookie/登录态
    raw_lang = "zh"         # 源默认语言，en 的会自动翻中文
    platform = ""           # 台账里的平台名（不填则从 URL 推断）

    def fetch(self, cfg=None, seen=None):
        """返回 (items, failed_msgs)。

        seen: Ledger 实例。抓详情页之前先 seen.is_seen(...) 查台账，
              命中就跳过（省请求，尤其 Jina 额度）。子类实现。
        """
        raise NotImplementedError

    # ---- 供子类用 ----
    def item(self, **kw):
        kw.setdefault("source_id", self.id)
        kw.setdefault("raw_lang", self.raw_lang)
        kw.setdefault("collected", now_bj())
        return Item(**kw)

    def is_seen(self, seen, post_id=None, url=None):
        """查台账。seen 为 None 时一律当没抓过。"""
        if seen is None:
            return False
        return seen.is_seen(self.platform or None, post_id, url)

    @staticmethod
    def get(url, prefer_direct=True, timeout=60):
        return http.get_smart(url, prefer_direct=prefer_direct, timeout=timeout)

    @staticmethod
    def clean(s):
        import re
        if not s:
            return ""
        s = re.sub(r'<[^>]+>', '', s)
        s = (s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
              .replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' '))
        return re.sub(r'\s+', ' ', s).strip()