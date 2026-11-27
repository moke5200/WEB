#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""输出层：所有格式化集中在这里，源只产 Item。

目前有：
  · to_001_lines()   linux.do 类资源的 5 行格式（写进 001.md）
  · to_daily_json()  每日页用的 JSON 结构（feed_artifacts.json / x / radar 等）
"""
import datetime
import json
import os

from config import settings   # noqa: E402


def _now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def to_001_lines(items, collected_at=None):
    """001.md 的 5 行格式。

    【标题】xxx
    链接：xxx
    发帖人：xxx
    发帖时间：YYYY-MM-DD HH:MM
    收集时间：YYYY-MM-DD HH:MM
    """
    stamp = collected_at or _now_bj().strftime("%Y-%m-%d %H:%M")
    blocks = []
    for it in items:
        title = (it.title or "").replace("\n", " ").strip()
        blocks.append(
            "【标题】%s\n链接：%s\n发帖人：%s\n发帖时间：%s\n收集时间：%s"
            % (title, it.url, it.author or "-", it.published or "-", stamp)
        )
    return "\n\n".join(blocks) + ("\n\n" if blocks else "")


def prepend_to_001(path, items, note=""):
    """把新条目插到 001.md 的第 1 行水位线之后，并更新水位线。

    返回写入条数。文件不存在则新建。
    """
    if not items:
        return 0
    stamp = _now_bj().strftime("%Y-%m-%d %H:%M")
    day = _now_bj().strftime("%Y-%m-%d")
    new_block = to_001_lines(items, stamp)

    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()

    # 拆出旧的水位线行
    lines = old.split("\n")
    wm_idx = 0 if (lines and lines[0].startswith("水位线：")) else -1
    if wm_idx >= 0:
        body = "\n".join(lines[1:]).lstrip("\n")
    else:
        body = old

    wm = "水位线：最后收集时间 %s，本次新增 %s %d 条%s" % (
        stamp, note or "条目", len(items), "" if not note else "")
    if not note:
        wm = "水位线：最后收集时间 %s，本次新增 %d 条" % (stamp, len(items))

    out = wm + "\n\n" + new_block + (body if body.strip() else "")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out.rstrip("\n") + "\n")
    return len(items)


def prepend_to_default_001(items, note=""):
    """写入 001.md。

    本机（WRITE_LOCAL_DISK=1）写 Google Drive 真实路径；
    云端（WRITE_LOCAL_DISK=0）写 OUT_DIR/001.md，由本机后续同步。
    """
    if settings.WRITE_LOCAL_DISK:
        target = settings.OUT_001
    else:
        target = os.path.join(settings.OUT_DIR, "001.md")
    return prepend_to_001(target, items, note)


def to_daily_json(items):
    """每日页用的通用结构（尽量兼容旧 make_daily.py 的字段）。"""
    return [{
        "title": it.title,
        "url": it.url,
        "summary": it.summary,
        "published": it.published,
        "author": it.author,
        "source": it.source_id,
        "tags": it.tags,
        "media": it.media,
    } for it in items]


def dump_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)