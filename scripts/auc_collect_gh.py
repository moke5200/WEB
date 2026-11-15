#!/usr/bin/env python3
"""auc_collect_gh.py — Agent Use Cases 采集（agentusecases.ai）

野哥 11-15 10:27 给的站：「试试看，找到我可以做的事情」。
定位：真实的人在用 AI Agent 做的具体案例（不理论、不新闻），每天扫描全网。
有官方 RSS：https://agentusecases.ai/feed.xml（60 条，标准 RSS 2.0）

结构实测：
  · 每条 title / link / description（"Done with Claude Code, Codex." 开头，
    后接案例描述）
  · 首页有「The daily 5」每天 5 条精选
  · 首页分类是前端 JS 筛选按钮，没有独立分类页 → RSS 全量抓即可
  · 按标题归一化去重 + 水位线只出新条目
"""
import re, os, sys, json, html, time, datetime, urllib.request, urllib.error
import watermark as wm

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
FEED = "https://agentusecases.ai/feed.xml"

OUT_DIR = os.environ.get("AUC_OUT_DIR", "out")
OUT_JSON = os.path.join(OUT_DIR, "auc_all.json")
OUT_MD = os.path.join(OUT_DIR, "auc_report.md")
MAX_ITEMS = int(os.environ.get("AUC_MAX_ITEMS", "40"))

os.makedirs(OUT_DIR, exist_ok=True)


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def fetch(url, timeout=30, retries=2):
    for i in range(retries + 1):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": UA}), timeout=timeout)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < retries:
                time.sleep(15 * (i + 1)); continue
            return e.code, ""
        except Exception:
            if i < retries:
                time.sleep(8); continue
            return -1, ""
    return -1, ""


def clean(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main():
    print("[1/2] 抓 feed", flush=True)
    status, body = fetch(FEED)
    if status != 200:
        print(f"  feed 失败 http={status}", flush=True)
        json.dump({"error": status, "items": []}, open(OUT_JSON, "w", encoding="utf-8"))
        return

    items = []
    for ch in re.findall(r"<item[ >].*?</item>", body, re.S):
        tm = re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", ch, re.S)
        lm = re.search(r"<link>(.*?)</link>", ch, re.S)
        dm = re.search(r"<pubDate>(.*?)</pubDate>", ch, re.S)
        sm = re.search(r"<description[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", ch, re.S)
        title = clean(tm.group(1)) if tm else ""
        url = (lm.group(1).strip() if lm else "").replace("&amp;", "&")
        desc = clean(sm.group(1)) if sm else ""
        # description 前半段通常是「Done with Gemini, Claude.」→ 提取用的工具
        tools = ""
        m = re.match(r"(Done with [^.]+\.?)", desc)
        if m:
            tools = m.group(1).rstrip(".")
            desc = desc[len(m.group(1)):].strip()
        if title and url:
            items.append({"title": title, "url": url, "desc": desc[:200],
                          "tools": tools, "time": (dm.group(1) if dm else "")})

    print(f"  feed {len(items)} 条", flush=True)

    # 水位线：首轮建基线，之后只给新条目
    items, wm_msg = wm.filter_new("agentusecases", items[:MAX_ITEMS], time_field="time")
    print(f"  {wm_msg}", flush=True)

    ts = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    json.dump({"fetched_at": ts, "total": len(items), "items": items},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lines = [f"# Agent Use Cases · {ts}", "",
             f"来源 https://agentusecases.ai/ ｜ 真实的人在用 AI Agent 做的事", ""]
    if items:
        for it in items:
            lines.append(f"### {it['title']}")
            if it.get("tools"):
                lines.append(f"- 用的工具：{it['tools']}")
            if it.get("desc"):
                lines.append(f"- 做法：{it['desc']}")
            lines.append(f"- 链接：{it['url']}")
            lines.append("")
    else:
        lines.append("本轮无新增（首轮基线或无更新）。")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[2/2] 产出 {len(items)} 条", flush=True)


if __name__ == "__main__":
    main()
