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
# 野哥 11-13 22:50：「你看着办，可以自己看情况调整」——
# 按各源更新节奏分开定，慢源放宽、快源收紧。
MAX_AGE_DAYS_DEFAULT = int(os.environ.get("WM_MAX_AGE_DAYS", "3"))
AGE_BY_SOURCE = {
    "iplaysoft": 7,      # 异次元：一周更一两篇，3 天会把它全滤掉
    "sspai":     3,      # 少数派：一天数篇
    "apprcn":   14,      # 反斗软件：更新极慢（实测最近三条跨 10 个月）
    "ghtrending": 2,     # GitHub Trending 每天换榜，超 2 天就是旧榜
    "ldwelfare": 2,      # linux.do 福利：时效性强
    "nodeseek":  2,      # 论坛帖，过两天就没价值
    "epic":      7,      # Epic 免费游戏一周一轮，按活动周期
}
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


# 历史去重种子（仓库里的 data/dedup_seed.json）。
# 野哥 11-14 02:18：「C 可以」——让 GitHub 采集自动查本地整理好的历史台账。
# 本地台账推到仓库后，这里加载它作为「初始已见」，旧线报就不会再冒出来。
DEDUP_SEED = os.environ.get("WM_DEDUP_SEED", "data/dedup_seed.json")


def load_history_seed():
    """返回历史条目的键集合（标题归一化 / URL / topic id）。"""
    keys = set()
    if not os.path.exists(DEDUP_SEED):
        return keys, 0
    try:
        d = json.load(open(DEDUP_SEED, encoding="utf-8"))
        for t in d.get("titles", []):
            keys.add("t:" + t)
        for u in d.get("urls", []):
            keys.add(u.strip())
        for i in d.get("topic_ids", []):
            keys.add("topic:" + str(i))
    except Exception as e:
        print(f"[wm] 历史种子加载失败: {e}", flush=True)
    return keys, len(keys)


def norm_title(t):
    return re.sub(r"\s+", "", re.sub(r"[\-—·|｜!！?？,，。:：\[\]【】()（）]", "", t)).lower()


def item_keys(item):
    """一条内容对应多个可能的键，任一命中历史即算重复。"""
    out = set()
    u = (item.get("url") or item.get("topic_url") or "").strip()
    if u:
        out.add(u)
        m = re.search(r"/topic/(\d+)", u)
        if m:
            out.add("topic:" + m.group(1))
    t = item.get("title", "").strip()
    if t:
        out.add("t:" + norm_title(t))
    return out


def load_seen(source_id):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{source_id}_seen.json")
    if not os.path.exists(path):
        seed_keys, _ = load_history_seed()
        return seed_keys, True  # 首轮基线 = 全部历史条目
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
    age_days = AGE_BY_SOURCE.get(source_id, MAX_AGE_DAYS_DEFAULT)
    cutoff = now_bj() - datetime.timedelta(days=age_days)

    fresh, too_old, hist_hit = [], 0, 0
    for it in items:
        t = parse_time(it.get(time_field, ""))
        if t and t < cutoff:
            too_old += 1
            continue
        keys = item_keys(it)
        k = item_key(it)
        # 任一键命中历史种子/已见库 → 重复
        if keys & seen:
            hist_hit += 1
        else:
            fresh.append(it)
        if k:
            seen.add(k)
        seen |= keys

    save_seen(source_id, seen, {"baseline": first, "too_old_dropped": too_old,
                                "history_hit": hist_hit, "max_age_days": age_days})

    if first:
        if BASELINE_SILENT:
            return [], f"首轮建基线：{len(seen)} 条记为已见，本轮不产出（避免旧文当新货）"
        return items, f"首轮建基线：{len(seen)} 条"

    return fresh, (f"新增 {len(fresh)} 条 / 本轮 {len(items)} 条 / 命中历史 {hist_hit} 条 / "
                   f"超龄丢弃 {too_old} 条 / 已见库 {len(seen)}")
