#!/usr/bin/env python3
"""watermark.py — 通用水位线模块（野哥 11-13 21:20 定）

背景：异次元那条「WorkBuddy 白嫖 DeepSeek」发布于 2026-10-19、免费至 10-31，
      11-13 首次抓取时因为「标题合适」被收进来了，其实是过期的旧文。
      根因是几个采集脚本只按「取最新 N 条」，没有判断这条是不是新出现的。

规则（野哥原话）：「现在这不是有了水位线了嘛，以后就有新的再拿」。
  · 每个源维护一个 seen（已见条目 ID 集合）
  · 第一次运行 = 建立基线，把当前所有条目记为已见，但**不产出**（避免把陈年旧文当新货）
  · 之后每轮：只输出 seen 里没有的新条目
  · 同时按发布日期过滤：超过 MAX_AGE_DAYS 天的条目直接不看（双保险）

状态存 state/<source>_seen.json，由 GitHub Actions cache 传递，不进仓库。
"""
import os, json, datetime, re

STATE_DIR = os.environ.get("WM_STATE_DIR", "state")
# 超过这个天数的条目不收（野哥口径：只关心新东西）
MAX_AGE_DAYS = int(os.environ.get("WM_MAX_AGE_DAYS", "3"))
# 基线模式：首次运行只建基线不产出
BASELINE_SILENT = os.environ.get("WM_BASELINE_SILENT", "1") == "1"


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def parse_time(s):
    """把各种 feed 时间转成 aware datetime（北京时间）。解析不了返回 None。"""
    if not s:
        return None
    s = str(s).strip()
    # 已经是 YYYY-MM-DD HH:MM 格式
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", s)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M").replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        except Exception:
            pass
    # ISO / RFC822
    t = re.sub(r"\.\d+", "", s).replace("Z", "+0000").replace("GMT", "+0000")
    t = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", t)
    for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
              "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S"):
        try:
            d = datetime.datetime.strptime(t, f)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        except Exception:
            continue
    return None


def item_key(item):
    """条目唯一键：优先用 url，没有就用标题。"""
    return (item.get("url") or item.get("topic_url") or item.get("title") or "").strip()


def load_seen(source_id):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{source_id}_seen.json")
    if not os.path.exists(path):
        return set(), True  # (seen, is_first_run)
    try:
        return set(json.load(open(path, encoding="utf-8"))), False
    except Exception:
        return set(), True


def save_seen(source_id, seen, meta=None):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{source_id}_seen.json")
    json.dump(sorted(seen), open(path, "w", encoding="utf-8"), ensure_ascii=False)
    mpath = os.path.join(STATE_DIR, f"{source_id}_meta.json")
    info = {"updated_at": now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(seen)}
    if meta:
        info.update(meta)
    json.dump(info, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def filter_new(source_id, items, time_field="time"):
    """返回 (新条目列表, 状态说明)。
    逻辑：
      1. 首轮（无 seen 文件）→ 建立基线，按 BASELINE_SILENT 决定是否产出
      2. 非首轮 → 只留 seen 里没有的
      3. 两轮都按 MAX_AGE_DAYS 过滤太旧的条目
    """
    seen, first = load_seen(source_id)
    cutoff = now_bj() - datetime.timedelta(days=MAX_AGE_DAYS)

    fresh, too_old = [], 0
    for it in items:
        t = parse_time(it.get(time_field, ""))
        if t and t < cutoff:
            too_old += 1
            continue
        k = item_key(it)
        if k and k not in seen:
            fresh.append(it)
        if k:
            seen.add(k)

    save_seen(source_id, seen, {"baseline": first, "too_old_dropped": too_old})

    if first:
        if BASELINE_SILENT:
            return [], f"首轮建基线：{len(seen)} 条记为已见，本轮不产出（避免旧文当新货）"
        return items, f"首轮建基线：{len(seen)} 条"

    return fresh, f"新增 {len(fresh)} 条 / 本轮 {len(items)} 条 / 超龄丢弃 {too_old} 条 / 已见库 {len(seen)}"
