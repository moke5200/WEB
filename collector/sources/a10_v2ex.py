#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a10 · V2EX 推广/创造（独立开发者工具与优惠）

V2EX 的 promotions.xml 已空（官方取消该 tab feed），改用官方 API：
  https://www.v2ex.com/api/topics/latest.json
节点：create（创造，独立开发者作品）+ promotions（推广）
过滤：代充/机场/卖号/翻墙等纯广告，只留工具与优惠。
"""
import json
import re
import time
import urllib.parse

from sources.base import Source

API = "https://www.v2ex.com/api/topics/latest.json"
KEEP_NODES = {"create", "promotions"}
NOISE = ["中转站", "机场", "代充", "代充值", "原生 IP", "住宅 IP", "静态 IP",
         "IP 低至", "CDK 赠送", "开号", "卖号", "账号出售", "共享号", "合租",
         "流量包", "私聊", "加微信", "加 QQ", "TG 群", "代理 IP", "科学上网",
         "翻墙", "梯子", "自助充值", "最高减", "优惠码", "折扣码", "首单",
         "注册送", "返佣", "代理", "引流"]


class V2ex(Source):
    id = "a10"
    name = "V2EX 推广"
    category = "独立开发"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "v2ex"

    def fetch(self, cfg=None, seen=None):
        via, st, body = self.get(API, prefer_direct=True, timeout=40)
        if st != 200 or not body:
            return [], ["V2EX API 失败 http=%s via=%s" % (st, via)]
        try:
            topics = json.loads(body)
        except Exception as e:
            return [], ["V2EX 解析失败 %s" % str(e)[:80]]

        items, dropped = [], 0
        for t in topics:
            node = (t.get("node") or {}).get("name", "")
            if node not in KEEP_NODES:
                dropped += 1
                continue
            title = t.get("title") or ""
            if any(k in title for k in NOISE):
                dropped += 1
                continue
            url = t.get("url") or ""
            oid = str(t.get("id") or "")
            if self.is_seen(seen, post_id=oid, url=url):
                continue
            # 时间是 Unix 时间戳
            pub = ""
            try:
                import datetime
                pub = datetime.datetime.fromtimestamp(
                    t["created"], datetime.timezone(datetime.timedelta(hours=8))
                ).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
            items.append(self.item(
                title=title, url=url, published=pub,
                summary="V2EX %s · %s" % (node, (t.get("content") or "")[:100]),
                tags=["独立开发", node],
                extra={"post_id": oid, "platform": "v2ex", "node": node,
                       "replies": t.get("replies", 0)},
            ))
        print("    [a10] V2EX 取 %d 条 → 收 %d 条（过滤 %d）"
              % (len(topics), len(items), dropped), flush=True)
        return items, []
