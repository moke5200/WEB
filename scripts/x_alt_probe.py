#!/usr/bin/env python3
"""x_alt_probe.py — 验证 trawlx 那套「零登录取推文」链路在本环境是否可行。

链路：DuckDuckGo 搜 site:x.com → 拿到推文 URL → fxtwitter API 取结构化 JSON
不涉及任何账号，全是公开端点。

同时测几个备选聚合渠道，看哪个真能给出可用内容。
"""
import urllib.request, urllib.error, urllib.parse, json, sys, time, re, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def get(url, timeout=25, headers=None):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()[:600]
        except Exception:
            return e.code, b""
    except Exception as e:
        return -1, f"{type(e).__name__}: {str(e)[:70]}".encode()


def test_fxtwitter():
    """fxtwitter / vxtwitter：给推文 ID 返回 JSON，无需登录。"""
    print("--- 1. fxtwitter 取单条推文 ---", flush=True)
    for host in ("api.fxtwitter.com", "api.vxtwitter.com"):
        url = f"https://{host}/elonmusk/status/1849429398342689119"
        st, body = get(url)
        ok = st == 200 and b'"text"' in body
        print(f"  {'✓' if ok else '✗'} {host} http={st} bytes={len(body)}", flush=True)
        if ok:
            try:
                d = json.loads(body)
                t = d.get("tweet", {})
                print(f"      作者: {t.get('author',{}).get('screen_name')}", flush=True)
                print(f"      内容: {str(t.get('text',''))[:100]}", flush=True)
                print(f"      点赞: {t.get('likes')} 转发: {t.get('retweets')}", flush=True)
            except Exception as e:
                print(f"      解析失败 {e}", flush=True)
        time.sleep(1)


def test_ddg_search():
    """DuckDuckGo：搜 site:x.com，看能不能拿到推文链接。"""
    print("--- 2. DuckDuckGo 搜 site:x.com ---", flush=True)
    queries = ["site:x.com claude code", "site:x.com AI agent 教程"]
    for q in queries:
        # html 版端点，无需 JS
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)
        st, body = get(url)
        text = body.decode("utf-8", "replace")
        links = re.findall(r'https?://(?:www\.)?x\.com/[\w]+/status/\d+', text)
        uniq = list(dict.fromkeys(links))
        print(f"  {'✓' if st == 200 and uniq else '✗'} {q!r} http={st} bytes={len(body)} 推文链接={len(uniq)}", flush=True)
        for u in uniq[:3]:
            print(f"      {u}", flush=True)
        time.sleep(2)


def test_ddg_api():
    """DuckDuckGo 的 lite 版，有时比 html 版宽松。"""
    print("--- 3. DuckDuckGo lite ---", flush=True)
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote("site:x.com claude code")
    st, body = get(url)
    text = body.decode("utf-8", "replace")
    links = re.findall(r'https?://(?:www\.)?x\.com/[\w]+/status/\d+', text)
    print(f"  http={st} bytes={len(body)} 推文链接={len(set(links))}", flush=True)


def test_aggregators():
    """几个公开的热榜/聚合端点。"""
    print("--- 4. 其他聚合渠道 ---", flush=True)
    sites = [
        ("Hacker News 前端", "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=5"),
        ("GitHub Trending 镜像", "https://gh-trending-api.de.a9sapp.eu/repositories?since=daily&spokenLanguage=zh"),
        ("Product Hunt RSS", "https://www.producthunt.com/feed"),
        ("Reddit r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/hot.json?limit=5"),
    ]
    for name, url in sites:
        st, body = get(url)
        ok = st == 200 and len(body) > 100
        print(f"  {'✓' if ok else '✗'} {name} http={st} bytes={len(body)}", flush=True)
        time.sleep(1)


def main():
    print("=== 零登录取 X 内容 + 备选渠道探测 ===", flush=True)
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')} UTC", flush=True)
    print()
    test_fxtwitter()
    print()
    test_ddg_search()
    print()
    test_ddg_api()
    print()
    test_aggregators()
    out = os.environ.get("OUT_DIR", "out")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "x_alt_probe.md"), "w", encoding="utf-8").write(
        "# 零登录取 X 内容探测\n\n见 Actions 日志。\n")
    print("\n=== 完 ===", flush=True)


if __name__ == "__main__":
    main()
