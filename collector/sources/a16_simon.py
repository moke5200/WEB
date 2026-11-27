#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a16 · Simon Willison 博客（英文 Atom，自动翻中文大白话）"""
from sources._rss_base import RssSource


class Simon(RssSource):
    id = "a16"
    name = "Simon Willison"
    category = "英文资讯"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "en"
    platform = "simonw"
    url = "https://simonwillison.net/atom/everything/"
    summary_prefix = "技术博客："
