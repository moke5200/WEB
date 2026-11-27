#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a06 · GitHub Trending（每日热门开源项目，RSS 镜像）

源是英文，raw_lang=en → 核心层会自动翻成中文摘要（野哥：别给我看英文）。
保留原项目名/仓库名不翻（专有名词）。
"""
from sources._rss_base import RssSource


class GithubTrending(RssSource):
    id = "a06"
    name = "GitHub Trending"
    category = "开源"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "en"
    platform = "github"
    url = "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml"
    summary_prefix = "开源项目："
