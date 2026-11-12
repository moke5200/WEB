#!/usr/bin/env python3
"""english_collect_gh.py — 英文技术源采集（每天一次，GitHub Actions）

野哥 11-13 03:20 定：
  · 只给这批新加的英文源一天一次，其他源频率不动
  · 概要要翻译 —— GitHub Actions 里没有 AI，所以这里只负责「抓原文」，
    输出带 title + 原文摘要的结构化 JSON；取回本地后由大肥鱼翻译成中文概要。

源清单借鉴 Thysrael/Horizon 的 data/config.github.json（不装它，只抄 URL）：
  · Simon Willison 博客（Atom）
  · vLLM / sglang / triton 的 GitHub Releases（Atom）
  · Hacker News 近 24 小时 ≥80 分（Algolia API）
  · GitHub Trending 已有，不重复
砍掉：karpathy events（实测匿名 API 返回空列表）
"""
import re, os, sys, json, html, time, datetime, urllib.request, urllib.error

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

OUT_DIR = os.environ.get("EN_OUT_DIR", "out")
OUT_JSON = os.path.join(OUT_DIR, "english_all.json")
OUT_MD = os.path.join(OUT_DIR, "english_report.md")
MAX_ITEMS = int(os.environ.get("EN_MAX_ITEMS", "15"))
DELAY = float(os.environ.get("EN_DELAY", "2"))

SOURCES = [
    {"id": "simonwillison", "name": "Simon Willison 博客", "kind": "atom",
     "url": "https://simonwillison.net/atom/everything/",
     "note": "AI 工具圈独立开发者，更新极勤"},
    {"id": "vllm", "name": "vLLM Releases", "kind": "atom",
     "url": "https://github.com/vllm-project/vllm/releases.atom",
     "note": "大模型推理框架发版"},
    {"id": "sglang", "name": "SGLang Releases", "kind": "atom",
     "url": "https://github.com/sgl-project/sglang/releases.atom",
     "note": "推理框架发版"},
    {"id": "triton", "name": "Triton Releases", "kind": "atom",
     "url": "https://github.com/triton-lang/triton/releases.atom",
     "note": "GPU 编译器发版"},
    {"id": "hn", "name": "Hacker News 近24h≥80分", "kind": "hn",
     "url": "", "note": "当天真热帖，非历史最热"},
]

os.makedirs(OUT_DIR, exist_ok=True)


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def fetch(url, timeout=40, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            r = urllib.request.urlopen(req, timeout=timeout)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(15 * (attempt + 1)); continue
            return e.code, ""
        except Exception:
            if attempt < retries:
                time.sleep(8); continue
            return -1, ""
    return -1, ""


def clean(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # 截断到句子边界附近，避免半截话
    if len(s) > 420:
        cut = s[:420]
        p = max(cut.rfind("。"), cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
        if p > 200:
            s = cut[:p + 1]
        else:
            s = cut + "…"
    return s


def to_bj(s):
    s = (s or "").strip()
    if not s:
        return ""
    s = re.sub(r"\.\d+", "", s).replace("Z", "+0000")
    s = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", s)
    for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
              "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S"):
        try:
            d = datetime.datetime.strptime(s, f)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except Exception:
            continue
    return s[:16]


def parse_atom(body):
    """Atom feed：entry/title/link/summary|content/updated。"""
    items = []
    for ch in re.findall(r"<entry[ >].*?</entry>", body, re.S):
        tm = re.search(r"<title[^>]*>(.*?)</title>", ch, re.S)
        title = clean(tm.group(1)) if tm else ""
        lm = re.search(r'<link[^>]*rel="alternate"[^>]*href="([^"]+)"', ch)
        if not lm:
            lm = re.search(r'<link[^>]*href="([^"]+)"', ch)
        url = lm.group(1) if lm else ""
        dm = re.search(r"<(?:updated|published)>(.*?)</(?:updated|published)>", ch, re.S)
        sm = re.search(r"<(?:summary|content)[^>]*>(.*?)</(?:summary|content)>", ch, re.S)
        desc = clean(sm.group(1)) if sm else ""
        if title and url:
            items.append({"title": title, "url": url,
                          "time": to_bj(dm.group(1) if dm else ""),
                          "desc": desc})   # 原文摘要，留给我翻译
    return items


def parse_hn():
    """HN 近 24 小时、分数 ≥80，按热度排。"""
    since = int(time.time()) - 86400
    url = ("https://hn.algolia.com/api/v1/search_by_date?tags=story"
           f"&numericFilters=created_at_i>{since},points>=80&hitsPerPage=30")
    st, body = fetch(url)
    if st != 200:
        return [], st
    hits = json.loads(body).get("hits", [])
    items = []
    for h in hits[:MAX_ITEMS]:
        title = h.get("title") or h.get("story_title") or ""
        if not title:
            continue
        oid = h.get("objectID") or ""
        points = h.get("points") or 0
        ncomments = h.get("num_comments") or 0
        items.append({
            "title": title,
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
            "time": to_bj(h.get("created_at") or ""),
            "desc": "",
            "hn_url": f"https://news.ycombinator.com/item?id={oid}",
            "points": points,
            "comments": ncomments,
        })
    return items, st


def main():
    print(f"[1/2] 抓取 {len(SOURCES)} 个英文源", flush=True)
    result, lines = {}, [f"# 英文技术源 · {now_bj().strftime('%Y-%m-%d %H:%M')}", "",
                         "> 概要由大肥鱼取回后翻译，这里保留原文。", ""]

    for s in SOURCES:
        if s["kind"] == "hn":
            items, st = parse_hn()
        else:
            st, body = fetch(s["url"])
            items = parse_atom(body) if st == 200 else []
        items = items[:MAX_ITEMS]
        result[s["id"]] = {"status": st, "items": items, "note": s["note"]}
        print(f"  {s['name']}: {len(items)} 条 (http={st})", flush=True)

        lines.append(f"## {s['name']}（{len(items)} 条）")
        lines.append(f"> {s['note']}")
        lines.append("")
        if items:
            for it in items:
                lines.append(f"### {it['title']}")
                meta = []
                if it.get("time"): meta.append(it["time"])
                if it.get("points") is not None: meta.append(f"{it['points']} 分")
                if it.get("comments") is not None: meta.append(f"{it['comments']} 评论")
                if meta: lines.append("- " + " · ".join(meta))
                lines.append(f"- 链接：{it['url']}")
                if it.get("hn_url"): lines.append(f"- HN 讨论：{it['hn_url']}")
                if it.get("desc"): lines.append(f"- 原文摘要：{it['desc']}")
                lines.append("")
        else:
            lines.append("- 本轮无条目")
            lines.append("")
        time.sleep(DELAY)

    ts = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    total = sum(len(v["items"]) for v in result.values())
    json.dump({"fetched_at": ts, "sources": result, "total": total},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
    ok = sum(1 for v in result.values() if v["status"] == 200)
    print(f"[2/2] 成功源 {ok}/{len(SOURCES)}，共 {total} 条", flush=True)


if __name__ == "__main__":
    main()
