#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a10 · V2EX 推广（独立开发者工具与优惠，带噪声过滤）
注意：早期测试发现推广版块机场/代充广告刷屏，已加过滤。"""
from sources._rss_base import RssSource

NOISE = ["中转站", "机场", "代充", "原生 IP", "住宅 IP", "静态 IP", "动态 IP",
         "IP 低至", "CDK 赠送", "开号", "卖号", "账号出售", "共享号", "合租",
         "私聊", "加微信", "加 QQ", "TG 群", "代理 IP", "科学上网", "翻墙", "梯子"]


class V2ex(RssSource):
    id = "a10"
    name = "V2EX 推广"
    category = "独立开发"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "v2ex"
    url = "https://www.v2ex.com/feed/tab/promotions.xml"
    exclude = NOISE
