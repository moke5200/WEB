#!/usr/bin/env python3
"""bluev_viral_collect_gh.py — BlueV 爆文雷达（游客档）

野哥 11-15 13:58：「A 不用了，能拿多少是多少，没关系」——
即：不折腾 BlueV 登录，用免登录的 /api/public/tweets，游客档每天刷新 5 条。

实测（11-15）：
  · GET https://bluev.fun/api/public/tweets → 200，guest_preview=true，锁死 5 条
  · 所有参数（limit/page/category）对游客档无效，total 恒为 5
  · 带 X cookie 也仍是 5 条（BlueV 用 Supabase 自己的会话，与 X cookie 无关）
  · 每条带：作者/粉丝数/正文/点赞/转发/浏览/分类标签/原文链接
"""
import re, os, sys, json, time, datetime, urllib.request, urllib.error
import watermark as wm

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
API = "https://bluev.fun/api/public/tweets"

OUT_DIR = os.environ.get("BV_OUT_DIR", "out")
OUT_JSON = os.path.join(OUT_DIR, "bluev_viral.json")
OUT_MD = os.path.join(OUT_DIR, "bluev_viral.md")
os.makedirs(OUT_DIR, exist_ok=True)


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def fetch(url, timeout=25, retries=3):
    for i in range(retries + 1):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json",
                              "Referer": "https://bluev.fun/viral"}), timeout=timeout)
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < retries:
                time.sleep(8 * (i + 1)); continue
            return e.code, {}
        except Exception:
            if i < retries:
                time.sleep(5 * (i + 1)); continue
            return -1, {}
    return -1, {}


def main():
    ts = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    print("[1/2] 抓 BlueV 游客档", flush=True)
    st, d = fetch(API)
    tweets = d.get("tweets", []) if st == 200 else []
    print(f"  http={st} 拿到 {len(tweets)} 条 guest_preview={d.get('guest_preview')}", flush=True)

    items = []
    for t in tweets:
        a = t.get("author") or {}
        items.append({
            "title": (t.get("text") or "")[:60].replace("\n", " ").strip(),
            "text": t.get("text") or "",
            "url": t.get("tweet_url") or "",
            "author": a.get("name") or "",
            "screen_name": a.get("screen_name") or "",
            "followers": a.get("followers") or 0,
            "likes": t.get("likes") or 0,
            "retweets": t.get("retweets") or 0,
            "views": t.get("views") or 0,
            "score": t.get("signal_score") or 0,
            "category": (t.get("category_ids") or [None])[0] or t.get("source_category") or "",
            "time": t.get("created_at") or "",
        })

    items, wm_msg = wm.filter_new("bluev_viral", items, time_field="time")
    print(f"  {wm_msg}", flush=True)

    json.dump({"fetched_at": ts, "guest_preview": d.get("guest_preview"),
               "total": len(items), "items": items},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lines = [f"# BlueV 爆文雷达（游客档） · {ts}", "",
             "> 免登录档，每天刷新 5 条，不分标签。有新的才推。", ""]
    if items:
        for it in items:
            lines.append(f"### @{it['screen_name']}（{it['author']}）· {it['category']}")
            lines.append(f"- 粉丝 {it['followers']} ｜ 赞 {it['likes']} ｜ 转 {it['retweets']} ｜ 浏览 {it['views']} ｜ 分数 {it['score']}")
            lines.append(f"- {it['text'][:200]}")
            lines.append(f"- 原文：{it['url']}")
            lines.append("")
    else:
        lines.append("本轮无新增。")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[2/2] 产出 {len(items)} 条", flush=True)


if __name__ == "__main__":
    main()
