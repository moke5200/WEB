#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a08 · 异次元 iplaysoft（RSS，与 a05/a07 跨源去重）"""
from sources._rss_base import RssSource


class Iplaysoft(RssSource):
    id = "a08"
    name = "异次元"
    category = "软件"
    freq = "2h"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "iplaysoft"
    url = "https://www.iplaysoft.com/feed"
