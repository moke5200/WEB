#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a03 · 什么值得买好价（不带 Cookie，从列表页 Nuxt 数据抠图）

抓法：直连列表页（精选好价 + 发现频道），不请求详情页
      （批量抓详情页会被 smzdm 限流返回 JS 验证页）。

判定（野哥定稿）：
  · 白嫖/极低价（免费领/0元/1分钱，且 ≤20）→ 等级3，强相关
  · 点名需求（键鼠≤150、耳夹耳机≤30、27寸显示器≤300、智能锁≤200、收纳≤300）→ 等级2，强相关
  · 深折信号（史低/3折/半价，且 ≤2000）→ 等级1，强相关
  · 整类排除（旅游/美妆/眼镜/母婴/儿童/书籍/摆件）→ 直接丢
  · 其余 → 普通档，进表方便批量扫

分两档：summary 里带「[强相关]」的主动推，其余普通列表。
输出：只进每日页 JSON + 一源一文件夹落盘，不写 001.md。
"""
import html
import os
import re
import time
import urllib.request

from sources.base import Source

PAGES = [
    ("精选好价", "https://www.smzdm.com/jingxuan/"),
    ("发现频道", "https://faxian.smzdm.com/"),
]
MAX_PAGE = int(os.environ.get("SZD_MAX_PAGE", "2"))
DELAY = float(os.environ.get("SZD_DELAY", "2"))

FREE = ["免费领", "白嫖", "免费送", "0.01", "1分钱", "一分钱", "免邮", "体验装"]
DEEP = ["史低", "历史低价", "3折", "4折", "三四折", "半价", "5折", "1折", "2折"]
FREE_MAX_PRICE = 20
DEEP_MAX_PRICE = 2000

NON_GOODS = [
    "酒店", "套房", "民宿", "机票", "跟团", "门票", "演出", "旅游", "度假", "房券", "住宿",
    "面霜", "精华", "洗颜", "乳液", "爽肤水", "眼霜", "面膜", "护肤", "彩妆", "口红", "粉底",
    "镜片", "镜框", "眼镜", "隐形眼镜", "美瞳",
    "儿童", "婴", "宝宝", "母婴", "童装", "童鞋", "奶粉", "尿裤", "睡袋", "学步",
    "玩具", "绘本", "早教", "孕", "奶瓶", "辅食", "中老年",
    "图书", "书籍", "教材", "教辅", "课外", "字帖", "童书", "文具", "书包", "阅读",
    "摆件", "手把件", "解压", "挂件", "香插", "隔热垫", "风铃", "把玩", "手办",
]
WANTS = [
    {"name": "键鼠", "min": 0, "max": 150, "kw": ["鼠标", "键盘", "键鼠"],
     "ex": ["鼠标垫", "键盘膜", "键帽", "贴膜", "支架"]},
    {"name": "耳夹耳机", "min": 0, "max": 30, "kw": ["耳夹", "骨传导", "不入耳"]},
    {"name": "显示器27寸", "min": 0, "max": 300, "kw": ["27英寸", "27寸"]},
    {"name": "智能锁", "min": 0, "max": 200, "kw": ["智能锁", "指纹锁"]},
    {"name": "收纳改造", "min": 0, "max": 300,
     "kw": ["收纳袋", "收纳箱", "置物架", "货架", "收纳架", "真空压缩"]},
]

IMG_RE = re.compile(r'(https://y\.zdmimg\.com/[^"\'\\ )]+?\.(?:jpg|png|webp)(?:_[a-z]\d+\.jpg)?)')
DEV_PAIR = re.compile(
    r'(https:\\u002F\\u002Fy\.zdmimg\.com\\u002F[^"]+?\.jpg(?:_[a-z]\d+\.jpg)?)"\s*,\s*'
    r'"(https:\\u002F\\u002Fwww\.smzdm\.com\\u002Fp\\u002F\d+\\u002F)"')


def build_img_map(t):
    m = {}
    for pic, url in DEV_PAIR.findall(t):
        m.setdefault(url.replace("\\u002F", "/"), pic.replace("\\u002F", "/"))
    for url, inner in re.findall(
            r'<a[^>]+href="(https://www\.smzdm\.com/p/\d+/)"[^>]*>(.*?)</a>', t, re.S):
        if url in m:
            continue
        im = IMG_RE.search(inner)
        if im:
            m[url] = im.group(1)
    return m


def norm_img(u):
    if not u:
        return ""
    base = re.sub(r"_[a-z]\d+\.jpg$", "", u)
    return base + "_a320.jpg"


def parse(t):
    items, seen = [], set()
    img_map = build_img_map(t)
    for m in re.finditer(r"gtmAddToCart\(\{(.*?)\}\)", t, re.S):
        d = dict(re.findall(r"'([^']+)'\s*:\s*'([^']*)'", m.group(1)))
        name = d.get("name", "").strip()
        if not name or not d.get("price") or name in seen:
            continue
        if name in ("好价", "好文"):
            continue
        seen.add(name)
        cs = t.rfind('class="feed-row-wide"', 0, m.start())
        if cs < 0:
            cs = t.rfind("<li", 0, m.start())
        if cs < 0:
            cs = max(0, m.start() - 4000)
        seg = t[cs:m.start()]
        dets = re.findall(r'href="(https://www\.smzdm\.com/p/\d+/)"', seg)
        gos = re.findall(r'href="(https://go\.smzdm\.com/[^"]+)"', seg)
        detail = dets[-1] if dets else ""
        pid = ""
        mm = re.search(r"/p/(\d+)/", detail)
        if mm:
            pid = mm.group(1)
        go = next((x for x in reversed(gos) if pid and pid in x), "")
        if pid and go and pid not in go:
            go = ""
        items.append({"name": name, "price": d.get("price", ""), "mall": d.get("mall", ""),
                      "cat": d.get("category", ""), "detail": detail, "go": go,
                      "img": norm_img(img_map.get(detail, "")), "pid": pid})
    return items


def judge(it):
    """返回 (是否推送, 理由, 等级)。"""
    name = it["name"]
    try:
        p = float(it["price"])
    except (TypeError, ValueError):
        return False, "价格解析失败", 0
    hits = name + " " + it.get("cat", "")
    if any(k in hits for k in NON_GOODS):
        return False, "整类排除", 0
    if re.search(r"(?<![\d.])0\s*元", hits) and p <= FREE_MAX_PRICE:
        return True, "白嫖/极低价", 3
    if any(k in hits for k in FREE) and p <= FREE_MAX_PRICE:
        return True, "白嫖/极低价(词命中)", 3
    if any(k in hits for k in DEEP) and p <= DEEP_MAX_PRICE:
        return True, "深折信号", 1
    for w in WANTS:
        if w.get("ex") and any(e in hits for e in w["ex"]):
            continue
        if any(k in hits for k in w["kw"]) and w["min"] <= p <= w["max"]:
            return True, "点名需求:" + w["name"], 2
    return False, "", 0


class Smzdm(Source):
    id = "a03"
    name = "什么值得买"
    category = "好价"
    freq = "30m"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "smzdm"

    def fetch(self, cfg=None, seen=None):
        all_items = []
        for label, base in PAGES:
            for pg in range(1, MAX_PAGE + 1):
                if "jingxuan" in base:
                    url = base if pg == 1 else "https://www.smzdm.com/jingxuan/p%d/" % pg
                else:
                    url = base if pg == 1 else "https://faxian.smzdm.com/p%d/" % pg
                try:
                    # 直连（smzdm 不需 Cookie，Jina 反而取不到 Nuxt 数据）
                    via, st, body = self.get(url, prefer_direct=True, timeout=30)
                    if st != 200 or not body:
                        print("    [a03] %s p%d 失败 http=%s" % (label, pg, st), flush=True)
                        time.sleep(DELAY)
                        continue
                    rows = parse(body)
                    print("    [a03] %s p%d 商品 %d" % (label, pg, len(rows)), flush=True)
                    for r in rows:
                        r["source"] = "%s p%d" % (label, pg)
                    all_items.extend(rows)
                except Exception as e:
                    print("    [a03] %s p%d ERR %s" % (label, pg, str(e)[:80]), flush=True)
                time.sleep(DELAY)

        # 同名去重
        uniq, names = [], set()
        for r in all_items:
            if r["name"] in names:
                continue
            names.add(r["name"])
            uniq.append(r)

        items, dropped = [], 0
        for r in uniq:
            ok, why, lvl = judge(r)
            if why == "整类排除":
                dropped += 1
                continue
            pid = r.get("pid")
            url = r.get("detail") or ""
            if self.is_seen(seen, post_id=pid or None, url=url):
                continue
            tier = "强相关" if ok else "普通"
            media = []
            if r.get("img"):
                media.append(("photo", r["img"]))
            items.append(self.item(
                title=r["name"], url=url or ("https://www.smzdm.com/p/%s/" % pid if pid else r["name"]),
                author="", published="",
                summary="[%s] ¥%s · %s · %s" % (tier, r["price"], r["mall"] or "-", why or "普通好价"),
                tags=[tier, r["cat"] or "好价"], media=media,
                extra={"post_id": pid, "platform": "smzdm", "tier": tier,
                       "price": r["price"], "level": lvl, "why": why,
                       "go": r.get("go", ""), "source_page": r["source"]},
            ))
        strong = sum(1 for i in items if i.extra.get("tier") == "强相关")
        print("    [a03] 抓 %d → 收 %d（强相关 %d / 普通 %d，整类排除 %d）"
              % (len(uniq), len(items), strong, len(items) - strong, dropped), flush=True)
        return items, []
