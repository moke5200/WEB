#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSS/Atom 公共解析：a04/a05/a07/a08/a09/a10/a11 等标准 feed 源共用。"""
import datetime
import html
import re


def strip_tags(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s or "", flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def pick(pattern, text):
    m = re.search(pattern, text or "", re.S)
    return strip_tags(m.group(1)) if m else ""


def to_bj(s):
    """各种 feed 时间格式 → 北京时间 YYYY-MM-DD HH:MM"""
    s = (s or "").strip()
    if not s:
        return ""
    s = re.sub(r"\.\d+", "", s)
    s = s.replace("Z", "+0000")
    s = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", s)
    for f in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S",
              "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
              "%Y-%m-%d %H:%M:%S", "%d %b %Y %H:%M:%S %z"):
        try:
            d = datetime.datetime.strptime(s, f)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except Exception:
            continue
    return s[:16]


def parse_feed(body, desc_len=180):
    """兼容 RSS 2.0 与 Atom，返回 [{title,url,time,desc}]"""
    items = []
    chunks = re.findall(r"<item[ >].*?</item>", body or "", re.S)
    is_atom = False
    if not chunks:
        chunks = re.findall(r"<entry[ >].*?</entry>", body or "", re.S)
        is_atom = True
    for ch in chunks:
        title = pick(r"<title[^>]*>(.*?)</title>", ch)
        if is_atom:
            lm = re.search(r'<link[^>]*href="([^"]+)"', ch)
            url = lm.group(1) if lm else ""
        else:
            url = pick(r"<link>(.*?)</link>", ch)
            if not url:
                lm = re.search(r'<link[^>]*href="([^"]+)"', ch)
                url = lm.group(1) if lm else ""
        date = (pick(r"<pubDate[^>]*>(.*?)</pubDate>", ch) or
                pick(r"<published[^>]*>(.*?)</published>", ch) or
                pick(r"<updated[^>]*>(.*?)</updated>", ch))
        desc = (pick(r"<description[^>]*>(.*?)</description>", ch) or
                pick(r"<summary[^>]*>(.*?)</summary>", ch))
        if title and url:
            items.append({"title": title, "url": url,
                          "time": to_bj(date), "desc": desc[:desc_len]})
    return items


def post_id_from(url):
    """从常见 URL 里抽帖子 ID，用于台账。"""
    m = re.search(r"/(?:p|topic|post|archives)/?(\d+)", url or "")
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=(\d+)", url or "")
    return m.group(1) if m else ""
