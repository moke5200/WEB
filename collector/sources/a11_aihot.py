#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a11 · aihot.news（AI 免费额度汇总，RSS）"""
from sources._rss_base import RssSource


class Aihot(RssSource):
    id = "a11"
    name = "aihot.news"
    category = "AI 额度"
    freq = "12h"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "aihot"
    url = "https://aihot.news/rss"
    summary_prefix = "AI 额度："
