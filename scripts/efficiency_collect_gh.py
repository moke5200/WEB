#!/usr/bin/env python3
"""efficiency_collect_gh.py — 效率向信源采集（GitHub Actions）

野哥 11-13 01:24 定稿的源清单（标准：能提高效率的东西）
================================================================
1. 少数派 sspai        —— 中文实用向，Mac 选购/Home Assistant/效率工具
2. 反斗软件 apprcn     —— 苹果限免监控、App Store 工具、macOS 小工具
3. linux.do 福利羊毛   —— 公益站/免费额度/羊毛（走 Jina，避开 Cloudflare）
4. GitHub Trending     —— 每日热门项目（RSS 镜像）
砍掉：NodeSeek（实测 20 条里 13 条是服务器买卖交易，不符合标准）
砍掉：Hugging Face / arXiv（太学术，野哥「看不懂所以不知道」）
砍掉：V2EX 推广（机场/代充广告）

输出 out/efficiency_report.md（按源分组）+ out/efficiency_all.json（全量）
"""
import re, os, sys, json, html, time, datetime, urllib.request, urllib.error
import watermark as wm   # 水位线：只给新条目（野哥 11-13 21:20）

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

OUT_DIR = os.environ.get("EF_OUT_DIR", "out")
OUT_JSON = os.path.join(OUT_DIR, "efficiency_all.json")
OUT_MD = os.path.join(OUT_DIR, "efficiency_report.md")
MAX_ITEMS = int(os.environ.get("EF_MAX_ITEMS", "15"))
DELAY = float(os.environ.get("EF_DELAY", "2"))

SOURCES = [
    {"id": "sspai", "name": "少数派", "url": "https://sspai.com/feed",
     "kind": "rss", "note": "中文实用向，讲怎么用"},
    {"id": "apprcn", "name": "反斗软件", "url": "https://www.apprcn.com/feed",
     "kind": "rss", "note": "限免监控、App Store 工具、macOS 小工具"},
    {"id": "ldwelfare", "name": "linux.do 福利羊毛",
     "url": "https://r.jina.ai/https://linux.do/c/welfare/36.rss",
     "kind": "markdown", "note": "走 Jina，羊毛/免费额度"},
    {"id": "ghtrending", "name": "GitHub Trending",
     "url": "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml",
     "kind": "rss", "note": "每日热门项目"},
]

# 与「提高效率」无关的标题特征（野哥 11-13：要好用的东西，不是资讯/游记）
# 野哥 11-13 02:10：先都搞下来，他慢慢告诉我哪些没兴趣，再逐步提高筛选准确性。
# 所以这里默认不过滤，只保留结构。等他反馈后再往里加关键词。
OFFTOPIC = {
    # "sspai": ["城市漫步", "游记", ...],   ← 暂时全放开
}

def is_offtopic(sid, title):
    return any(k in title for k in OFFTOPIC.get(sid, []))

# 内容性质标记（不做过滤，只标注，方便野哥快速扫读）
TAG_RULES = [
    ("工具/软件", ["工具", "软件", "App", "插件", "客户端", "脚本", "开源", "下载"]),
    ("教程/方法", ["教程", "指南", "怎么", "如何", "技巧", "方法", "实践", "折腾"]),
    ("羊毛/优惠", ["免费", "限免", "优惠", "折扣", "羊毛", "领", "送", "额度", "公益"]),
    ("资讯/新闻", ["早报", "日报", "周报", "发布", "宣布", "上线", "更新", "泄露"]),
]

def tag_of(title, desc=""):
    t = title + " " + desc
    for name, kws in TAG_RULES:
        if any(k in t for k in kws):
            return name
    return "其他"


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
                time.sleep(15 * (attempt + 1))
                continue
            return e.code, ""
        except Exception:
            if attempt < retries:
                time.sleep(8)
                continue
            return -1, ""
    return -1, ""


def strip_tags(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = html.unescape(s)                    # 先反转义，&lt;a&gt; → <a>
    s = re.sub(r"<[^>]+>", " ", s)           # 再去标签
    s = re.sub(r"查看全文|阅读全文|Read more", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def to_bj(s):
    """多种时间格式 → 北京时间 YYYY-MM-DD HH:MM"""
    s = (s or "").strip()
    if not s:
        return ""
    s = re.sub(r"\.\d+", "", s)
    s = s.replace("Z", "+0000").replace("GMT", "+0000")
    s = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", s)
    for f in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S",
              "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
              "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.datetime.strptime(s, f)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except Exception:
            continue
    return s[:16]


def parse_rss(body):
    """兼容 RSS 2.0 与 Atom。"""
    items = []
    chunks = re.findall(r"<item[ >].*?</item>", body, re.S)
    atom = False
    if not chunks:
        chunks = re.findall(r"<entry[ >].*?</entry>", body, re.S)
        atom = True
    for ch in chunks:
        title = strip_tags(re.search(r"<title[^>]*>(.*?)</title>", ch, re.S).group(1)) \
            if re.search(r"<title[^>]*>(.*?)</title>", ch, re.S) else ""
        if atom:
            lm = re.search(r'<link[^>]*href="([^"]+)"', ch)
            url = lm.group(1) if lm else ""
        else:
            lm = re.search(r"<link>(.*?)</link>", ch, re.S)
            url = strip_tags(lm.group(1)) if lm else ""
        dm = re.search(r"(?:<pubDate>|<published>|<updated>)(.*?)(?:</pubDate>|</published>|</updated>)", ch, re.S)
        desc_m = re.search(r"(?:<description>|<summary>|<content[^>]*>)(.*?)(?:</description>|</summary>|</content>)", ch, re.S)
        desc = strip_tags(desc_m.group(1)) if desc_m else ""
        if title and url:
            items.append({"title": title, "url": url,
                          "time": to_bj(dm.group(1) if dm else ""),
                          "desc": desc[:180]})
    return items


def parse_markdown(body):
    """Jina 转出的 Markdown：### [标题](链接)"""
    out = []
    for m in re.finditer(r"### \[(.+?)\]\((https://linux\.do/t/topic/\d+)\)", body):
        out.append({"title": html.unescape(m.group(1)).strip(),
                    "url": m.group(2), "time": "", "desc": ""})
    return out


def main():
    print(f"[1/2] 抓取 {len(SOURCES)} 个源", flush=True)
    result, lines = {}, [f"# 效率向信息 · {now_bj().strftime('%Y-%m-%d %H:%M')}", ""]

    for s in SOURCES:
        status, body = fetch(s["url"])
        if status != 200 or len(body) < 100:
            print(f"  {s['name']}: 失败 http={status}", flush=True)
            result[s["id"]] = {"status": status, "items": []}
            lines.append(f"## {s['name']} —— 抓取失败（http={status}）")
            lines.append("")
            time.sleep(DELAY)
            continue

        items = parse_markdown(body) if s["kind"] == "markdown" else parse_rss(body)
        before = len(items)
        items = [x for x in items if not is_offtopic(s["id"], x["title"])]
        filtered = before - len(items)
        items = items[:MAX_ITEMS]
        # 水位线：首轮建基线不产出；之后只给新条目，且超龄（默认 3 天）的直接不看
        items, wm_msg = wm.filter_new(s["id"], items, time_field="time")
        result[s["id"]] = {"status": status, "items": items, "note": s["note"],
                           "watermark": wm_msg}
        print(f"  {s['name']}: {wm_msg}", flush=True)

        lines.append(f"## {s['name']}（{len(items)} 条）")
        if s.get("note"):
            lines.append(f"> {s['note']}")
            lines.append("")
        if items:
            for it in items:
                tag = tag_of(it["title"], it.get("desc", ""))
                lines.append(f"### [{tag}] {it['title']}")
                if it.get("time"):
                    lines.append(f"- 时间：{it['time']}")
                if it.get("desc"):
                    lines.append(f"- 摘要：{it['desc']}")
                lines.append(f"- 链接：{it['url']}")
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
