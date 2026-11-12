#!/usr/bin/env python3
"""x_probe.py — 探测 GitHub Actions 环境下 X（Twitter）各条路径的通达性。

目的：搞清楚在 Actions 上到底能不能取 X，能取到什么程度。
不涉及任何账号凭据，只测公开可访问的端点。
"""
import urllib.request, urllib.error, sys, json, time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

TESTS = [
    ("x.com 首页",            "https://x.com/",                                                  "无登录，看能不能连通"),
    ("syndication 时间线",     "https://cdn.syndication.twimg.com/timeline/profile?screen_name=elonmusk", "公开端点，无需登录"),
    ("syndication 旧接口",     "https://syndication.twitter.com/srv/timeline-profile/screen-name/elonmusk", "公开，返回 HTML"),
    ("X API v2",              "https://api.x.com/2/tweets/search/recent?query=test",              "需要 Bearer，预期 401"),
    ("RSSHub 公共实例",        "https://rsshub.app/twitter/user/elonmusk",                        "第三方，可能已限流"),
    ("Nitter 实例",           "https://nitter.net/elonmusk",                                      "多数已死"),
    ("abs 备用实例",           "https://abs.twimg.com/",                                          "CDN，测基础连通"),
]

def probe(url, timeout=25):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        r = urllib.request.urlopen(req, timeout=timeout)
        body = r.read()
        return r.status, len(body), body[:200]
    except urllib.error.HTTPError as e:
        try:
            b = e.read()[:200]
        except Exception:
            b = b""
        return e.code, 0, b
    except Exception as e:
        return -1, 0, f"{type(e).__name__}: {str(e)[:60]}".encode()


def main():
    print("=== X 通达性探测（GitHub Actions 环境）===", flush=True)
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')} UTC", flush=True)
    print()
    results = []
    for name, url, note in TESTS:
        st, size, head = probe(url)
        text = head.decode("utf-8", "replace") if isinstance(head, bytes) else str(head)
        snippet = " ".join(text.split())[:110]
        ok = "✓" if st == 200 else "✗"
        print(f"{ok} {name}", flush=True)
        print(f"    http={st}  bytes={size}   {note}", flush=True)
        if snippet:
            print(f"    片段: {snippet}", flush=True)
        results.append({"name": name, "url": url, "status": st, "bytes": size,
                        "note": note, "snippet": snippet})
        print()
        time.sleep(1)

    # 结论区
    print("=== 判定 ===", flush=True)
    reachable = [r for r in results if r["status"] == 200]
    if not reachable:
        print("全部不可达 → X 在 GitHub Actions 上取不到", flush=True)
    else:
        for r in reachable:
            print(f"可用路径: {r['name']} ({r['bytes']} 字节)", flush=True)

    import os
    out = os.environ.get("OUT_DIR", "out")
    os.makedirs(out, exist_ok=True)
    json.dump(results, open(os.path.join(out, "x_probe.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with open(os.path.join(out, "x_probe.md"), "w", encoding="utf-8") as f:
        f.write("# X 通达性探测\n\n")
        for r in results:
            f.write(f"- **{r['name']}** http={r['status']} bytes={r['bytes']}\n")
            f.write(f"  - {r['note']}\n")
            if r["snippet"]:
                f.write(f"  - `{r['snippet']}`\n")
    print("已写出 out/x_probe.json / out/x_probe.md", flush=True)


if __name__ == "__main__":
    main()
