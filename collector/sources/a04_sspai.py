#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a04 · 少数派 sspai（RSS，数字产品与效率资讯）"""
from sources._rss_base import RssSource


class Sspai(RssSource):
    id = "a04"
    name = "少数派"
    category = "资讯"
    freq = "3h"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "sspai"
    url = "https://sspai.com/feed"
