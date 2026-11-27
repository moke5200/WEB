#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a09 · NodeSeek RSS（免费云电脑/VPS 羊毛，带噪声过滤）"""
from sources._rss_base import RssSource

# 服务器买卖交易广告太多，野哥要的是免费羊毛
NOISE = ["中转站", "机场", "代充", "原生 IP", "住宅 IP", "静态 IP", "动态 IP",
         "IP 低至", "CDK 赠送", "开号", "卖号", "账号出售", "共享号", "合租",
         "流量包", "订阅套餐", "私聊", "加微信", "加 QQ", "TG 群", "倍率",
         "聚合站", "开户", "充值", "续费", "实名账户", "折扣码", "优惠码",
         "服务器出售", "转让", "收购", "续费券", "［收］", "[收]", "高价收", "求购"]


class NodeSeek(RssSource):
    id = "a09"
    name = "NodeSeek"
    category = "羊毛"
    freq = "2h"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "nodeseek"
    url = "https://rss.nodeseek.com/"
    exclude = NOISE
