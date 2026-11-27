#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a05 · 反斗软件 apprcn（RSS，限免/App Store 工具/macOS 小工具）
与 a07 小众软件、a08 异次元 跨源去重（同类软件站）。"""
from sources._rss_base import RssSource


class Apprcn(RssSource):
    id = "a05"
    name = "反斗软件"
    category = "软件"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "apprcn"
    url = "https://www.apprcn.com/feed"
