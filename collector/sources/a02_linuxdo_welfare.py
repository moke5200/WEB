#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a02 · linux.do 福利版（c/welfare/36）

抓法：同 a01，直连优先，被 Cloudflare 挡就走 Jina。
不用逐帖抓详情（福利帖标题基本能判断），只取列表，快、省 Jina 额度。

分两档（野哥 11-23 前定的口径）：
  · 强相关羊毛 → 打「强相关」标签，每日页单独一块，主动给野哥看
  · 其余       → 打「普通」标签，放普通列表，方便他批量扫删
输出：只进每日页 JSON，不写 001.md
"""
import html
import os
import re
import time

from sources.base import Source

CAT = "https://linux.do/c/welfare/36"
RSS = CAT + ".rss"
LIST_PAGES = int(os.environ.get("LDW_LIST_PAGES", "1"))
MAX_ITEMS = int(os.environ.get("LDW_MAX_ITEMS", "30"))
DELAY = float(os.environ.get("LDW_DELAY", "4"))

# 强相关羊毛：出现这些词基本就是能直接薅的东西
STRONG = ["免费", "限免", "0元", "零元", "白嫖", "领取", "额度", "公益",
          "赠送", "送", "折扣", "优惠", "薅", "试用", "白给", "白菜",
          "5折", "半价", "抵扣", "返现", "红包", "兑换码", "激活码"]

# 内容性质标签（只标注不过滤，方便扫读）
TAGS = [
    ("羊毛/优惠", STRONG),
    ("工具/软件", ["工具", "软件", "App", "插件", "客户端", "脚本", "开源", "下载"]),
    ("教程/方法", ["教程", "指南", "怎么", "如何", "技巧", "方法", "实践", "折腾"]),
    ("资讯/新闻", ["早报", "日报", "周报", "发布", "宣布", "上线", "更新", "泄露"]),
    ("求助/讨论", ["求助", "请问", "有没有", "推荐", "讨论", "大家"]),
]


def parse_feed(md):
    """Jina 转出的 Markdown 列表：### [标题](https://linux.do/t/topic/N)"""
    out, seen = [], set()
    for m in re.finditer(r"#{2,4} \[(.+?)\]\((https://linux\.do/t/topic/(\d+))\)", md or ""):
        title = html.unescape(m.group(1)).strip()
        url, tid = m.group(2), m.group(3)
        if tid in seen:
            continue
        seen.add(tid)
        # 抓标题后面那行日期
        tail = (md or "")[m.end():m.end() + 300]
        dm = re.search(r"\b\w{3}, \d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}\b", tail)
        out.append({"title": title, "url": url, "id": tid, "pub": dm.group(0) if dm else ""})
    return out


def to_bj(rfc822):
    import datetime
    t = " ".join((rfc822 or "").split())
    core = re.sub(r"^\w{3},\s*", "", t)
    for fmt in ("%d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S"):
        try:
            d = datetime.datetime.strptime(core, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return t[:16]


def tag_of(title):
    for name, kws in TAGS:
        if any(k in title for k in kws):
            return name
    return "其他"


def is_strong(title):
    return any(k in title for k in STRONG)


class LinuxDoWelfare(Source):
    id = "a02"
    name = "linux.do 福利版"
    category = "福利"
    freq = "3h"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "linux.do"

    def fetch(self, cfg=None, seen=None):
        items, failed = [], []
        rows, seen_ids = [], set()
        for pg in range(1, LIST_PAGES + 1):
            pure = RSS if pg == 1 else "%s?page=%d" % (RSS, pg)
            via, st, md = self.get(pure, prefer_direct=True, timeout=90)
            if st != 200 or "linux.do/t/topic/" not in (md or ""):
                print("    [a02] 列表 page%d 失败 http=%s via=%s" % (pg, st, via), flush=True)
                failed.append("列表 page%d http=%s" % (pg, st))
                continue
            got = parse_feed(md)
            added = 0
            for r in got:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"]); rows.append(r); added += 1
            print("    [a02] page%d 取 %d 条，新增 %d（via %s）" % (pg, len(got), added, via), flush=True)
            time.sleep(DELAY)

        if not rows:
            return [], failed or ["列表为空"]

        rows = rows[:MAX_ITEMS]
        skipped = 0
        for r in rows:
            if self.is_seen(seen, post_id=r["id"], url=r["url"]):
                skipped += 1
                continue
            tier = "强相关" if is_strong(r["title"]) else "普通"
            items.append(self.item(
                title=r["title"], url=r["url"], author="",
                published=to_bj(r["pub"]),
                tags=[tag_of(r["title"]), tier],
                summary="[%s] %s" % (tier, tag_of(r["title"])),
                extra={"post_id": r["id"], "platform": "linux.do", "tier": tier},
            ))
        if skipped:
            print("    [a02] 台账命中跳过 %d 条" % skipped, flush=True)
        strong = sum(1 for i in items if i.extra.get("tier") == "强相关")
        print("    [a02] 收 %d 条（强相关 %d / 普通 %d）"
              % (len(items), strong, len(items) - strong), flush=True)
        return items, failed