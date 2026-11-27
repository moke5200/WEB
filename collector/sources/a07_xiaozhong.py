#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a07 · 小众软件（RSS，与 a05/a08 跨源去重）"""
from sources._rss_base import RssSource


class Xiaozhong(RssSource):
    id = "a07"
    name = "小众软件"
    category = "软件"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "xiaozhong"
    url = "https://www.appinn.com/feed/"
