#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a24 · AI 平台免费额度聚合（只追踪长期、每天可领的）

野哥口径（2026-11-28）：
  · 只考虑「长期的、每天可领的」额度
  · 一次性的积分有无无所谓
  · 数据源：https://aihot.news/free-tokens（每轮重抓，对比变动）

卡片结构（实测 67 张）：
  <button class="group min-w-0 ...">
    <span class="text-ui-body font-semibold text-ink">标题</span>
    <span title="说明">...</span>
    <span class="whitespace-nowrap">标签</span> ...
  </button>

筛选：标题/说明/标签里出现「每日/每天/签到/长期/每月」且不是「限时/一次性/活动」的才算。
只报「新增或变动」的额度（对比上次快照），避免每轮重复推同样内容。
"""
import datetime
import html
import io
import json
import os
import re

from sources.base import Source

FREE = "https://aihot.news/free-tokens"
STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "state", "ai_quota_snapshot.json")

# 长期/每日信号
LONGTERM = ["每日", "每天", "签到", "长期", "每月", "日常", "持续", "每日可领", "每天可领", "自动发放"]
# 一次性/限时信号（命中就排除）
ONESHOT = ["一次性", "限时", "限免", "限时活动", "活动截止", "报名至", "仅活动", "单次", "体验一次"]


def clean(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def parse_cards(body):
    out = []
    blocks = re.findall(r'<button[^>]*class="[^"]*group min-w-0[^"]*"[^>]*>(.*?)</button>',
                        body or '', re.S)
    for blk in blocks:
        tm = re.search(r'font-semibold[^>]*>(.*?)</span>', blk, re.S)
        title = clean(tm.group(1)) if tm else ''
        if not title:
            continue
        desc_m = re.search(r'<span[^>]*title="([^"]*)"', blk)
        desc = clean(html.unescape(desc_m.group(1))) if desc_m else ''
        tags = [clean(t) for t in re.findall(r'whitespace-nowrap[^>]*>(.*?)</span>', blk)]
        tags = [t for t in tags if t]
        blob = ' '.join([title, desc] + tags)
        is_long = any(k in blob for k in LONGTERM)
        is_one = any(k in blob for k in ONESHOT)
        if is_long and not is_one:
            out.append({"title": title, "desc": desc, "tags": tags})
    return out


class AiQuota(Source):
    id = "a24"
    name = "AI 平台免费额度（长期）"
    category = "AI 额度"
    freq = "1d"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "aihot"

    def fetch(self, cfg=None, seen=None):
        via, st, body = self.get(FREE, prefer_direct=True, timeout=60)
        if st != 200 or not body:
            return [], ["aihot 免费额度页失败 http=%s via=%s" % (st, via)]
        cards = parse_cards(body)

        # 对比上次快照，只报新增或变动
        prev = {}
        if os.path.exists(STATE):
            try:
                prev = {x['title']: x for x in json.load(io.open(STATE, encoding='utf-8')).get('items', [])}
            except Exception:
                pass
        changed = []
        for c in cards:
            old = prev.get(c['title'])
            if not old or old.get('tags') != c['tags'] or old.get('desc') != c['desc']:
                changed.append(c)

        # 存快照
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump({"updated": datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
                   "items": cards}, io.open(STATE, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)

        items = []
        for c in changed:
            if self.is_seen(seen, post_id=None, url=None):
                pass
            items.append(self.item(
                title=c['title'], url=FREE + "#" + str(abs(hash(c['title'])) % 100000),
                summary=(("长期可领 ｜ " + c['desc'] + " ｜ " + " · ".join(c['tags']))
                         if c['desc'] else ("长期可领 ｜ " + " · ".join(c['tags'])))[:200],
                tags=["AI 额度", "长期可领"],
                extra={"platform": "aihot", "post_id": "quota:" + c['title'][:40]},
            ))
        print("    [a24] 长期可领额度 %d 张，本次变动 %d 张" % (len(cards), len(items)), flush=True)
        return items, []