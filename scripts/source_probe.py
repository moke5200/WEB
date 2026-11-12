#!/usr/bin/env python3
"""source_probe.py — 按「提高效率」标准筛选信源的可行性探测。

野哥 11-13 00:11 定的标准：
  · 稍微好一点儿的羊毛（不是垃圾白嫖）
  · 好点儿的使用方法（教程/技巧）
  · 好用点儿的软件（工具推荐）
  · 共同点：都能提高效率

本脚本只测通达性和内容质量，不写正式采集逻辑。
"""
import urllib.request, urllib.error, urllib.parse, json, sys, time, re, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def get(url, timeout=25):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()[:400]
        except Exception:
            return e.code, b""
    except Exception as e:
        return -1, f"{type(e).__name__}: {str(e)[:60]}".encode()


def show(name, url, hint=""):
    st, body = get(url)
    text = body.decode("utf-8", "replace")
    ok = st == 200 and len(body) > 200
    print(f"{'✓' if ok else '✗'} {name}  http={st} bytes={len(body)}  {hint}", flush=True)
    return ok, text


def main():
    print("=== 信源探测：按「提高效率」标准 ===", flush=True)
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')} UTC", flush=True)
    print()

    print("【A. AI 趋势类】", flush=True)
    # HuggingFace 趋势模型
    ok, t = show("HF 趋势模型 API", "https://huggingface.co/api/models?sort=trending&direction=-1&limit=10")
    if ok:
        try:
            d = json.loads(t)
            print(f"      拿到 {len(d)} 个模型，前 3：", flush=True)
            for m in d[:3]:
                print(f"        {m.get('modelId')}  ♥{m.get('likes',0)}", flush=True)
        except Exception as e:
            print(f"      解析失败 {e}", flush=True)

    # HuggingFace 每日论文
    ok2, t2 = show("HF 每日论文", "https://huggingface.co/api/daily_papers?limit=5")
    if ok2:
        try:
            d = json.loads(t2)
            print(f"      拿到 {len(d)} 篇，前 3：", flush=True)
            for p in d[:3]:
                print(f"        {str(p.get('title',''))[:70]}", flush=True)
        except Exception as e:
            print(f"      解析失败 {e}", flush=True)

    # arXiv
    ok3, t3 = show("arXiv cs.AI 最新", "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=5")
    if ok3:
        titles = re.findall(r"<title>(.*?)</title>", t3, re.S)[1:4]
        for ti in titles:
            print(f"        {' '.join(ti.split())[:70]}", flush=True)
    print()

    print("【B. 中文效率/软件类】", flush=True)
    # 少数派
    ok4, t4 = show("少数派 sspai", "https://sspai.com/feed")
    if ok4:
        titles = re.findall(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", t4, re.S)[1:5]
        for ti in titles:
            print(f"        {re.sub(r'\\s+',' ',ti).strip()[:66]}", flush=True)

    # LINUX DO 福利羊毛（走 Jina，避开 Cloudflare）
    ok5, t5 = show("LINUX DO 福利羊毛（Jina）", "https://r.jina.ai/https://linux.do/c/welfare/36.rss")
    if ok5:
        items = re.findall(r"### \[(.+?)\]\(https://linux\.do/t/topic/\d+\)", t5)[:5]
        for it in items:
            print(f"        {it[:66]}", flush=True)

    # NodeSeek 分类
    ok6, t6 = show("NodeSeek 主 feed", "https://rss.nodeseek.com/")
    print()

    print("【C. Reddit 镜像（试几个）】", flush=True)
    reddit_urls = [
        ("reddit .json", "https://www.reddit.com/r/LocalLLaMA/hot.json?limit=5"),
        ("old.reddit .json", "https://old.reddit.com/r/LocalLLaMA/hot.json?limit=5"),
        ("reddit .rss", "https://www.reddit.com/r/LocalLLaMA/.rss"),
        ("libreddit 实例1", "https://redlib.catsarch.com/r/LocalLLaMA"),
        ("redlib 实例2", "https://safereddit.com/r/LocalLLaMA"),
    ]
    for name, url in reddit_urls:
        show(name, url)
        time.sleep(2)
    print()

    print("【D. 其他候选】", flush=True)
    others = [
        ("GitHub Trending", "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml"),
        ("Hacker News RSS", "https://hnrss.org/frontpage"),
        ("Product Hunt RSS", "https://www.producthunt.com/feed"),
        ("反斗软件", "https://www.apprcn.com/feed"),
        ("小刀娱乐网", "https://www.xiaodao.la/feed"),
    ]
    for name, url in others:
        show(name, url)
        time.sleep(1)

    out = os.environ.get("OUT_DIR", "out")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "probe.md"), "w", encoding="utf-8").write("# 探测完成，详见日志\n")
    print("\n=== 完 ===", flush=True)


if __name__ == "__main__":
    main()
