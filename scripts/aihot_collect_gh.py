#!/usr/bin/env python3
"""aihot_collect_gh.py — aihot.news 补回 GitHub

野哥 11-09 21:05 原话把它定为「token 羊毛主源」，Box 时代一直在跑
（日志里常年 [aihot free-tokens ★主源] 无变化）。Box 清空后断了，
11-15 发现 GitHub 6 个脚本里没有它，补回。

两个源：
  · /rss  标准 RSS，50 条 AI 资讯（变化兜底）
  · /free-tokens  HTML 页，428KB，「今天还能领 ¥xxx / 本月已领 / 下次刷新」
"""
import re, os, sys, json, html, time, datetime, urllib.request, urllib.error
import watermark as wm

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
RSS = "https://aihot.news/rss"
FREE = "https://aihot.news/free-tokens"

OUT_DIR = os.environ.get("AH_OUT_DIR", "out")
OUT_JSON = os.path.join(OUT_DIR, "aihot_all.json")
OUT_MD = os.path.join(OUT_DIR, "aihot_report.md")
MAX_ITEMS = int(os.environ.get("AH_MAX_ITEMS", "40"))

os.makedirs(OUT_DIR, exist_ok=True)


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def fetch(url, timeout=30, retries=2):
    for i in range(retries + 1):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < retries:
                time.sleep(10 * (i + 1)); continue
            return e.code, ""
        except Exception:
            if i < retries:
                time.sleep(6); continue
            return -1, ""
    return -1, ""


def clean(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = html.unescape(s)
    return re.sub(r"<[^>]+>", " ", s).strip()


def parse_rss(body):
    items = []
    for ch in re.findall(r"<item[ >].*?</item>", body, re.S):
        tm = re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", ch, re.S)
        lm = re.search(r"<link>(.*?)</link>", ch, re.S)
        dm = re.search(r"<pubDate>(.*?)</pubDate>", ch, re.S)
        sm = re.search(r"<description[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", ch, re.S)
        title = clean(tm.group(1)) if tm else ""
        url = lm.group(1).strip() if lm else ""
        desc = clean(sm.group(1)) if sm else ""
        if title and url:
            items.append({"title": title, "url": url, "desc": desc[:180],
                          "time": dm.group(1) if dm else "", "kind": "rss"})
    return items


# 野哥 11-15 16:37：「按我的需求给我就行，那种只能在客户端里面用的，我可能用不到」
# 所以只保留能接 API / 通用额度的卡片，「限产品内使用 / 仅客户端 / 客户端内额度」的排除。
CLIENT_ONLY_MARKERS = ["限产品内使用", "客户端内", "仅电脑端", "客户端或微信小程序",
                       "客户端签到", "客户端领取"]


def parse_free_tokens(body):
    """抽 61 张卡片，按「能不能当 API 用」分两组。
    卡片结构（实测）：<button class="group min-w-0 ..."> 内含
      · span.text-[15px].font-semibold = 标题
      · span[title] = 说明
      · span.whitespace-nowrap = 限制标签
    """
    blocks = re.findall(r'<button[^>]*class="[^"]*group min-w-0[^"]*"[^>]*>(.*?)</button>', body, re.S)
    usable, skipped = [], []
    for blk in blocks:
        tm = re.search(r'text-\[15px\] font-semibold[^>]*>(.*?)</span>', blk, re.S)
        title = clean(tm.group(1)) if tm else ""
        if not title:
            continue
        tags = [clean(t) for t in re.findall(r'whitespace-nowrap[^>]*>(.*?)</span>', blk)]
        tags = [t for t in tags if t]
        joined = " ".join(tags)
        rec = {"title": title, "tags": tags}
        if any(k in joined for k in CLIENT_ONLY_MARKERS) and "API" not in joined:
            skipped.append(rec)
        else:
            usable.append(rec)

    flat = clean(body)
    m = re.search(r"今天还能领\s*[¥￥]?\s*([\d,\.]+)", flat)
    today = m.group(1) if m else ""
    m2 = re.search(r"本月已领到\s*[¥￥]?\s*([\d,\.]+)", flat)
    month = m2.group(1) if m2 else ""
    m3 = re.search(r"下次刷新\s*还有\s*([\d:]+)", flat)
    refresh = m3.group(1) if m3 else ""
    return {"usable": usable, "client_only": skipped,
            "usable_count": len(usable), "client_only_count": len(skipped),
            "today_remaining": today, "month_claimed": month,
            "next_refresh": refresh, "raw_bytes": len(body)}


def main():
    ts = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    print("[1/2] 抓 aihot /rss", flush=True)
    st, body = fetch(RSS)
    items = parse_rss(body) if st == 200 else []
    print(f"  rss http={st} 拿到 {len(items)} 条", flush=True)

    # 水位线：只出新条目
    items, wm_msg = wm.filter_new("aihot", items[:MAX_ITEMS], time_field="time")
    print(f"  {wm_msg}", flush=True)

    print("[2/2] 抓 aihot /free-tokens", flush=True)
    st2, fbody = fetch(FREE)
    free = parse_free_tokens(fbody) if st2 == 200 else {"error": st2}
    print(f"  free-tokens http={st2} 可用 {free.get('usable_count',0)} / 排除客户端内 {free.get('client_only_count',0)} / 今日剩 {free.get('today_remaining','-')}", flush=True)

    json.dump({"fetched_at": ts, "total": len(items), "items": items,
               "free_tokens": free},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lines = [f"# aihot.news · {ts}", "",
             f"token 羊毛主源（野哥 11-09 定）。RSS 新增 {len(items)} 条。", ""]
    lines.append("## 免费额度页（/free-tokens）")
    lines.append(f"- 今日还能领：{free.get('today_remaining') or '未解析到'} ｜ 本月已领：{free.get('month_claimed') or '-'} ｜ 下次刷新：{free.get('next_refresh') or '-'}")
    lines.append(f"- 按野哥需求筛选：**可当 API/通用额度 {free.get('usable_count',0)} 条**，排除「限产品内/客户端内」{free.get('client_only_count',0)} 条")
    lines.append("")
    lines.append("### 可用额度（按你的需求保留）")
    for c in free.get("usable", []):
        lines.append(f"- **{c['title']}** ｜ {' / '.join(c['tags'][:5])}")
    lines.append("")
    lines.append("## RSS 新增")
    if items:
        for it in items:
            lines.append(f"- **{it['title']}**")
            if it.get("desc"): lines.append(f"  - {it['desc']}")
            lines.append(f"  - {it['url']}")
    else:
        lines.append("- 本轮无新增（首轮基线或无更新）")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
    print(f"完成，产出 {len(items)} 条", flush=True)


if __name__ == "__main__":
    main()
