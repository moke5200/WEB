#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a12 · AgentUseCases（英文源，自动翻中文大白话）"""
from sources._rss_base import RssSource


class AUC(RssSource):
    id = "a12"
    name = "AgentUseCases"
    category = "Agent 案例"
    freq = "12h"
    runs_on = "cloud"
    raw_lang = "en"
    platform = "auc"
    url = "https://agentusecases.ai/feed.xml"
    summary_prefix = "Agent 案例："
