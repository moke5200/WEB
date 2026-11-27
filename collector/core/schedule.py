#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""频率调度：一个 workflow 定时触发，内部判断本轮哪些源「到点了」。

这样加源不用改 yml，删源也不会留下僵尸 cron。

state/last_run.json:
{ "a01": "2026-11-27 20:22", "a03": "2026-11-27 19:00" }
"""
import datetime
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import settings    # noqa: E402

LAST_RUN_FILE = os.path.join(settings.STATE_DIR, "last_run.json")

FREQ_MIN = {
    "30m": 30, "1h": 60, "2h": 120, "3h": 180, "6h": 360,
    "12h": 720, "1d": 1440,
}


def _now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def load():
    try:
        with open(LAST_RUN_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(d):
    os.makedirs(os.path.dirname(LAST_RUN_FILE) or ".", exist_ok=True)
    with open(LAST_RUN_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)


def _parse(ts):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(ts, fmt).replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        except Exception:
            pass
    return None


def is_due(cfg, last_run):
    """判断某个源这轮该不该跑。"""
    freq = (cfg.get("freq") or "6h").strip()
    sid = cfg["id"]
    last = _parse(last_run.get(sid, ""))
    now = _now()

    if freq in ("on-demand", ""):
        return False                      # 只在手动指定时跑
    if freq == "weekly-fri":
        # 每周五跑一次；且距上次至少 6 天
        if now.weekday() != 4:
            return False
        return (last is None) or ((now - last).days >= 6)
    if freq not in FREQ_MIN:
        return True                       # 认不出就每轮都跑，别漏
    if last is None:
        return True
    return (now - last).total_seconds() >= FREQ_MIN[freq] * 60


def mark_run(ids):
    d = load()
    ts = _now().strftime("%Y-%m-%d %H:%M")
    for i in ids:
        d[i] = ts
    save(d)


def due_sources(sources, only_runs_on=None):
    """返回本轮该跑的源列表。"""
    lr = load()
    out = []
    for s in sources:
        if not s.get("enabled"):
            continue
        if only_runs_on and s.get("runs_on", "cloud") != only_runs_on:
            continue
        if is_due(s, lr):
            out.append(s)
    return out