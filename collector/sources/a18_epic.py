#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a18 · Epic 喜加一（每周五，只取当前免费的游戏，附 B 站搜索链接）

用 Epic 官方 JSON（locale=zh-CN），只取当前促销窗口且折扣价为 0 的。
"""
import json
import urllib.parse

from sources.base import Source

EPIC_API = ("https://store-site-backend-static.ak.epicgames.com/"
            "freeGamesPromotions?locale=zh-CN&country=CN&allowCountries=CN")


class Epic(Source):
    id = "a18"
    name = "Epic 喜加一"
    category = "免费游戏"
    freq = "weekly-fri"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "epic"

    def fetch(self, cfg=None, seen=None):
        via, st, body = self.get(EPIC_API, prefer_direct=True, timeout=40)
        if st != 200 or not body:
            return [], ["Epic API 失败 http=%s" % st]
        try:
            d = json.loads(body)
            els = (d.get("data", {}).get("Catalog", {})
                     .get("searchStore", {}).get("elements", []) or [])
        except Exception as e:
            return [], ["Epic 解析失败 %s" % str(e)[:80]]

        items = []
        for e in els:
            promos = (e.get("promotions") or {}).get("promotionalOffers") or []
            if not promos:
                continue
            cur = e.get("price", {}).get("totalPrice", {})
            if cur.get("discountPrice") != 0:
                continue
            title = e.get("title") or ""
            slug = e.get("productSlug") or ""
            if not title:
                continue
            link = ("https://store.epicgames.com/zh-CN/p/%s" % slug
                    if slug else "https://store.epicgames.com/zh-CN/free-games")
            oid = e.get("id") or slug or title
            if self.is_seen(seen, post_id=oid, url=link):
                continue
            bili = ("https://search.bilibili.com/all?keyword="
                    + urllib.parse.quote(title))
            items.append(self.item(
                title=title, url=link, published="",
                summary="Epic 免费游戏 · B站评测：%s" % bili,
                tags=["免费游戏", "喜加一"],
                extra={"post_id": oid, "platform": "epic", "bili": bili},
            ))
        print("    [a18] Epic 取 %d 个游戏 → 收 %d 个免费" % (len(els), len(items)), flush=True)
        return items, []
