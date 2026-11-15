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


def parse_free_tokens(body):
    """从 free-tokens 页抽「今天还能领 / 卡片标题」。页面是 SSR HTML，
    结构可能变，抽不到就给个摘要数字，不硬报成功。"""
    out = []
    # 标题/卡片名
    for m in re.finditer(r"<h[23][^>]*>(.*?)</h[23]>", body, re.S):
        t = clean(m.group(1))
        if t and len(t) < 80 and not any(k in t for k in ["登录", "关于", "导航"]):
            out.append(t)
    # 关键数字（页面写成「今天还能领 ¥ 2433」，数字前有空格）
    flat = clean(body)
    m = re.search(r"今天还能领\s*[¥￥]?\s*([\d,\.]+)", flat)
    today = m.group(1) if m else ""
    m2 = re.search(r"本月已领到\s*[¥￥]?\s*([\d,\.]+)", flat)
    month = m2.group(1) if m2 else ""
    m3 = re.search(r"下次刷新\s*还有\s*([\d:]+)", flat)
    refresh = m3.group(1) if m3 else ""
    return {"cards": out[:30], "today_remaining": today,
            "month_claimed": month, "next_refresh": refresh, "raw_bytes": len(body)}


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
    print(f"  free-tokens http={st2} 卡片 {len(free.get('cards',[]))} 今日剩余 {free.get('today_remaining','-')}", flush=True)

    json.dump({"fetched_at": ts, "total": len(items), "items": items,
               "free_tokens": free},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lines = [f"# aihot.news · {ts}", "",
             f"token 羊毛主源（野哥 11-09 定）。RSS 新增 {len(items)} 条。", ""]
    lines.append("## 免费额度页（/free-tokens）")
    lines.append(f"- 今日还能领：{free.get('today_remaining') or '未解析到'}")
    for c in free.get("cards", [])[:20]:
        lines.append(f"- {c}")
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
