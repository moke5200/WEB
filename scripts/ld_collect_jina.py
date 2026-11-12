#!/usr/bin/env python3
"""ld_collect_gh.py — linux.do 云资源收集（GitHub Actions · Jina 中转版）

为什么走 Jina：
  GitHub Actions 的 IP 段被 linux.do 的 Cloudflare 持续 429，直连不通。
  （实测：2026-11-12 21:11 起按 5/10/15/20 分钟退避重试四次，全部 429。）
  参考 luobinger/PerkRadar 的做法，改用 r.jina.ai 代理抓取：
  请求打到 Jina，由 Jina 取 linux.do 并转成 Markdown，绕开 IP 风控。

抓取方式约定（野哥 11-12 23:16 拍板）
=====================================
优先级：能直连就直连，被挡才走 Jina。

为什么这么定：
  · 直连最快、最省事，且不把第三方纳入链路
  · Jina 是外部代理，它的可用性不由我们控制（PerkRadar 文档同样标注此风险）
  · 只有 Cloudflare 拦截时（实测 linux.do 直连持续 429），才改用 Jina 中转

Jina 额度核算（官方 2026-11-12 查证）：
  · 免费档：20 RPM（每分钟 20 次请求），平均延迟 7.9 秒
  · 我们的用量：每 6 小时一轮，1 次列表 + 最多 30 次单帖 = 31 次
  · 每天 4 轮 = 124 次；20 RPM 允许 28,800 次/天 → 占用约 0.4%
  · 脚本内每帖间隔设 4 秒（而非 3 秒），确保不贴 20 RPM 上限
  · 结论：不需要付费 Key，额度长期够用

当前各源走法：
  · linux.do   → Jina 中转（直连 429）
  · smzdm      → 直连（正常）
  · NodeSeek / 异次元 / Epic → 直连（正常，不占 Jina 额度）

Jina 返回格式（实测）：
  列表页：### [标题](https://linux.do/t/topic/<id>)  换行  链接重复行  换行  RFC822 日期
  单帖页：Title / URL Source / Published Time，正文在 `post by <作者>` 之后，
          网盘链接形如 [百度网盘 请输入提取码](https://pan.baidu.com/s/xxx?pwd=yyy) 提取码: yyy

业务规则不变（野哥 11-11 定稿）：
  · 标签含「夸克」或「百度」才收
  · 资源链接百度优先（保留提取码），否则用夸克
  · 两个都没有 → 整条丢弃
  · 七行格式输出
  · 按网盘链接 ID 去重（同资源不同人重发不重复收）
"""
import re, json, html, time, os, sys, datetime, urllib.request, urllib.error

CAT = "https://linux.do/c/resource/cloud-asset/94"
RSS = CAT + ".rss"
JINA = "https://r.jina.ai/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

OUT_DIR = os.environ.get("LD_OUT_DIR", "out")
STATE_DIR = os.environ.get("LD_STATE_DIR", "state")
OUT_JSON = os.path.join(OUT_DIR, "ld_deals.json")
OUT_MD = os.path.join(OUT_DIR, "ld_report.md")
SEEN_FILE = os.path.join(STATE_DIR, ".ld_seen.json")
TOPIC_DELAY = float(os.environ.get("LD_TOPIC_DELAY", "4"))   # Jina 免费档 20 RPM，4 秒留余量   # 每帖间隔秒
MAX_TOPICS = int(os.environ.get("LD_MAX_TOPICS", "30"))
CONSEC_FAIL_LIMIT = 4

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def http_get(url, timeout=60, retries=2):
    """返回 (status, text)。429/5xx 时短暂退避重试。"""
    last = (0, "")
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            r = urllib.request.urlopen(req, timeout=timeout)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = (e.code, "")
            if e.code in (429, 500, 502, 503, 504):
                wait = 20 * (attempt + 1)
                print(f"    http {e.code}，{wait}s 后重试 ({attempt+1}/{retries})", flush=True)
                time.sleep(wait)
                continue
            return e.code, ""
        except Exception as e:
            last = (-1, str(e)[:80])
            time.sleep(10)
    return last


def fetch_pages(path, timeout=60):
    """按约定的优先级取页面：直连优先，被 Cloudflare 拦（403/429/503）才走 Jina。
    path 形如 'https://linux.do/c/resource/cloud-asset/94.rss'。
    返回 (status, text, via)，via 是 'direct' 或 'jina'。"""
    st, body = http_get(path, timeout=timeout)
    ok = st == 200 and len(body) > 500
    if ok and "linux.do/t/topic/" in body:
        return st, body, "direct"
    if ok and ("post by" in body or "URL Source:" in body):
        return st, body, "direct"
    # 直连不通 → 走 Jina
    jst, jbody = http_get(JINA + path, timeout=max(timeout, 90))
    if jst == 200:
        return jst, jbody, "jina"
    return jst, jbody, "jina-failed"


def to_bj(rfc822):
    """RFC822 时间 → 北京时间字符串。例：Thu, 12 Nov 2026 14:43:11 +0000 → 2026-11-12 22:43"""
    t = " ".join(rfc822.split())
    # 去掉星期前缀，剩下 12 Nov 2026 14:43:11 +0000
    core = re.sub(r"^\w{3},\s*", "", t)
    for fmt in ("%d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S"):
        try:
            d = datetime.datetime.strptime(core, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return t[:16]


def parse_feed(md):
    """从 Jina 转出的 Markdown 列表里拆出 (标题, url, id, 北京时间)。"""
    out, seen = [], set()
    chunks = re.split(r"^#{2,4} \[", md, flags=re.M)[1:]
    for ch in chunks:
        m = re.match(r"([^\]]*)\]\((https://linux\.do/t/topic/(\d+))\)", ch)
        if not m:
            continue
        title, url, tid = m.group(1).strip(), m.group(2), m.group(3)
        if tid in seen:
            continue
        seen.add(tid)
        dm = re.search(r"\b\w{3}, \d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}\b", ch)
        out.append({"title": html.unescape(title), "url": url, "id": tid,
                    "pub": dm.group(0) if dm else ""})
    return out


def extract_body(md):
    """单帖 Markdown 里取「作者」和「正文段」。正文从 post by 之后开始，
    去掉目录树代码块、图片、导航等噪声。"""
    author = ""
    m = re.search(r"post by (\S+)", md)
    if m:
        author = m.group(1)

    start = m.start() if m else 0
    seg = md[start:]
    # 砍掉尾部的 Related topics
    tail = seg.find("### Related topics")
    if tail > 0:
        seg = seg[:tail]
    return author, seg


def extract_nets(seg):
    """从正文段抽网盘链接。百度优先（保留提取码），否则夸克。"""
    bd = re.search(r"https?://pan\.baidu\.com/s/[\w-]+(?:\?pwd=([\w]{4,8}))?", seg)
    qk_link = re.search(r"https?://pan\.quark\.cn/s/[\w-]+", seg)
    qk_cmd = re.search(r"/~([0-9a-fA-F]+)~:/?", seg)

    if bd:
        url = bd.group(0)
        pwd = bd.group(1) or ""
        if not pwd:
            pm = re.search(r"提取码[:：\s]*([\w]{4,8})", seg)
            if pm:
                pwd = pm.group(1)
                url += ("&pwd=" if "?" in url else "?pwd=") + pwd
        elif "pwd=" not in url:
            url += "?pwd=" + pwd
        nid = re.search(r"/s/([\w-]+)", url)
        return url, "百度网盘", nid.group(1) if nid else ""

    if qk_link:
        url = qk_link.group(0)
        if qk_cmd:
            url += f"  (口令 /~{qk_cmd.group(1)}~:/)"
        nid = re.search(r"/s/([\w-]+)", url)
        return url, "夸克网盘", nid.group(1) if nid else ""

    return "", "", ""


def extract_tags(md):
    """标签从 Related topics 那一段的 tag 链接里取（单帖页本身没标签）。"""
    tags = []
    for m in re.finditer(r"\[(百度网盘|夸克网盘|迅雷网盘|影视|动漫|人工智能|软件|教程|电子书)\]"
                         r"\(https://linux\.do/tag/", md):
        if m.group(1) not in tags:
            tags.append(m.group(1))
    return tags


def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            return set(json.load(open(SEEN_FILE, encoding="utf-8")))
        except Exception:
            pass
    return set()


def main():
    seen = load_seen()
    print(f"[init] 已收网盘ID {len(seen)}", flush=True)

    # 1) 列表
    print(f"[1/3] 取列表", flush=True)
    status, md, via = fetch_pages(RSS, timeout=90)
    if status != 200 or "linux.do/t/topic/" not in md:
        print(f"  列表获取失败 http={status} 长度={len(md)}", flush=True)
        print(f"  片段: {' '.join(md.split())[:150]}", flush=True)
        _write_empty(status, md)
        return
    rows = parse_feed(md)
    print(f"  列表 {len(rows)} 条", flush=True)
    if not rows:
        _write_empty(status, md)
        return

    rows = rows[:MAX_TOPICS]
    if rows:
        print(f"  时间范围 {rows[-1]['pub'][:22]} ~ {rows[0]['pub'][:22]}", flush=True)

    # 2) 逐帖
    print(f"[2/3] 逐帖抓取 {len(rows)} 条（每帖间隔 {TOPIC_DELAY}s）", flush=True)
    keep, dropped, skipped = [], [], []
    consec = 0
    for i, it in enumerate(rows, 1):
        if consec >= CONSEC_FAIL_LIMIT:
            print(f"  连续失败 {consec} 次，提前收尾", flush=True)
            break
        st, tmd, _via = fetch_pages(it["url"], timeout=90)
        if st != 200 or ("post by" not in tmd and "URL Source:" not in tmd):
            consec += 1
            skipped.append({"title": it["title"], "why": f"单帖抓取失败 http={st}"})
            print(f"  [{i}/{len(rows)}] 失败 {it['title'][:26]} http={st}", flush=True)
            time.sleep(TOPIC_DELAY)
            continue
        consec = 0

        author, seg = extract_body(tmd)
        url, ntype, nid = extract_nets(seg)
        tags = extract_tags(tmd)
        has_tag = any(("夸克" in t) or ("百度" in t) for t in tags)

        if not has_tag:
            skipped.append({"title": it["title"], "why": "标签无夸克/百度"})
        elif not url:
            dropped.append({"title": it["title"], "why": "无百度/夸克资源链接"})
            print(f"  [{i}/{len(rows)}] 丢 {it['title'][:26]}（无网盘链接）", flush=True)
        else:
            key = f"{ntype}:{nid}"
            if key in seen:
                skipped.append({"title": it["title"], "why": "资源链接已收(同资源)"})
            else:
                seen.add(key)
                keep.append({"title": it["title"], "topic_url": it["url"],
                             "author": author, "created": to_bj(it["pub"]),
                             "net_url": url, "net_type": ntype, "tags": tags})
                print(f"  [{i}/{len(rows)}] 收 {it['title'][:28]} | {ntype}", flush=True)
        time.sleep(TOPIC_DELAY)

    print(f"  收 {len(keep)} / 丢弃 {len(dropped)} / 跳过 {len(skipped)}", flush=True)

    # 3) 落盘
    ts = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    json.dump({"cat": CAT, "fetched_at": ts, "via": "jina", "from_feed": len(rows),
               "kept": keep, "dropped": dropped, "skipped": skipped},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sorted(seen), open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False)

    lines = [f"# linux.do 云资源 · {ts}", ""]
    if keep:
        for r in sorted(keep, key=lambda x: x["created"]):
            lines += [f"【标题】{r['title']}", f"链接：{r['topic_url']}",
                      f"资源链接：{r['net_url']}",
                      f"标签：{','.join(r['tags']) if r['tags'] else r['net_type']}",
                      f"发帖人：{r['author']}", f"发帖时间：{r['created']}",
                      f"收集时间：{ts[:16]}", ""]
    else:
        lines.append("本轮无新增。")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[3/3] NEW={len(keep)} DROP={len(dropped)} SKIP={len(skipped)}", flush=True)


def _write_empty(status, md):
    ts = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    json.dump({"cat": CAT, "fetched_at": ts, "via": "jina", "error": f"http={status}",
               "snippet": " ".join(md.split())[:300], "kept": [], "dropped": [], "skipped": []},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(OUT_MD, "w", encoding="utf-8").write(
        f"# linux.do 云资源 · {ts}\n\n列表获取失败（http={status}）。\n")
    print("[3/3] NEW=0（列表失败）", flush=True)


if __name__ == "__main__":
    main()
