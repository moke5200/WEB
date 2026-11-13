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
MAX_TOPICS = int(os.environ.get("LD_MAX_TOPICS", "50"))
# Muse 11-13 指出：RSS 一次只给 25 条，MAX_TOPICS=50 是虚的。
# 实测 ?page=1/2/3 走 Jina 各返回不同 25 条 → 改成翻页补全。
LIST_PAGES = int(os.environ.get("LD_LIST_PAGES", "2"))
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
    """只取【正文区】的标签。

    Muse 11-13 纠正：tag 链接在正文区（Related topics 之前）就有，
    扫全文不会漏收，但会把「相关帖」的标签混进来造成误收。
    所以这里在 Related topics 处截断，只扫它之前的部分。
    """
    head = md.split("### Related topics", 1)[0]
    tags = []
    for m in re.finditer(r"\[(百度网盘|夸克网盘|迅雷网盘|影视|动漫|人工智能|软件|教程|电子书)\]"
                         r"\(https://linux\.do/tag/", head):
        if m.group(1) not in tags:
            tags.append(m.group(1))
    return tags


# ============ 课程优先分类（野哥 11-13 02:10：要资源、课程优先）============
# 目的：全量保留资源，但按「课程 > 教程 > 软件 > 影视 > 其他」排序，
#       让他打开文件就先看到课程。
COURSE_KW = ["课", "教程", "训练营", "实战", "系统班", "全集", "全套", "精讲",
             "入门", "进阶", "从0到1", "从零", "速成", "系统课", "专栏", "讲座",
             "特训", "集训", "大师课", "必修", "研修", "游学", "分享会",
             # 补充（11-13 实测漏网）
             "开发", "精通", "学习", "讲解", "指南", "方法论", "体系", "陪跑",
             "第.期", "第.季", "V3.0", "Vol", "班", "营", "全套", "完整版"]
SOFT_KW = ["软件", "工具", "插件", "脚本", "破解", "绿色版", "便携版", "安装包",
           "播放器", "客户端", "编辑器", "管理器", "下载器", "转换器", "助手",
           "V2", "v2", "官方版", "汉化版", "免安装"]
VIDEO_KW = ["剧", "电影", "动漫", "综艺", "纪录片", "4K", "HDR", "中字", "中文字幕",
            "更新至", "更至", "完结", "S0", "S1", "EP", "季", "全集", "蓝光",
            "1080P", "2160P", "中英", "双语", "影视", "短剧", "漫剧", "国配",
            "画质", "高码", "臻享", "合集", "全合集"]
BOOK_KW = ["电子书", "PDF", "书籍", "epub", "mobi", "azw3", "文档合集", "资料包"]

# 纯编程教学类（野哥 11-13 01:46：纯教编程的不要，儿童编程也不要——
# 等孩子能看的时候语言早换了。但 AI 应用类不算编程，要留）
PROGRAMMING_KW = ["Java", "Python", "JavaScript", "TypeScript", "React", "Vue", "Angular",
                  "Node.js", "Nodejs", "Golang", " Go ", "Rust", "C++", "C语言", "PHP",
                  "前端", "后端", "全栈", "算法", "数据结构", "数据库", "MySQL", "Redis",
                  "微服务", "架构师", "源代码", "源码解析", "设计模式", "编程",
                  "爬虫", "自动化测试", "运维工程师", "Linux运维", "Docker", "Kubernetes",
                  "K8s", "Spring", "Django", "Flask", "Vue3", "React18", "Next.js",
                  "NestJS", "Web前端", "小程序开发", "安卓开发", "iOS开发", "鸿蒙开发",
                  "少儿编程", "Scratch", "Python编程", "信息学奥赛", "NOIP", "CSP"]
# 这些词出现时不算纯编程（AI 应用、工具使用类）
NOT_PURE_PROG = ["AI视频", "AI绘画", "AI写作", "AI剪辑", "数字人", "提示词", "Prompt",
                 "AI创作", "AI短剧", "AI漫剧", "AI配音", "AI换脸", "AI写真", "AI绘图"]

# 硬编程信号：出现语言/框架名，且带教学词 → 一定是编程课
LANG_NAMES = ["Python", "Java", "JavaScript", "TypeScript", "Golang", "Rust", "C++",
              "PHP", "React", "Vue", "Angular", "Node.js", "Nodejs", "Spring",
              "Django", "Flask", "Next.js", "NestJS", "Kubernetes", "K8s", "Docker"]
TEACH_WORDS = ["课", "教程", "训练营", "实战", "系统班", "精通", "入门", "进阶",
               "从0到1", "从零", "开发", "全栈", "工程师", "学习"]

def is_pure_programming(title):
    """判断是否是纯编程教学。
    规则：① 有语言名 + 教学词 → 编程；② 命中编程关键词且不含 AI 应用词 → 编程。"""
    has_lang = any(k in title for k in LANG_NAMES)
    has_teach = any(k in title for k in TEACH_WORDS)
    if has_lang and has_teach:
        return True
    if any(k in title for k in NOT_PURE_PROG):
        return False
    return any(k in title for k in PROGRAMMING_KW)


def classify(title):
    """返回 (分类, 优先级)。优先级数字越小越靠前。
    纯编程类排最后（野哥说不要），但仍然收，由他复核。"""
    t = title
    if is_pure_programming(t):
        return "纯编程(可忽略)", 9
    if any(k in t for k in COURSE_KW):
        return "课程/教程", 1
    if any(k in t for k in SOFT_KW):
        return "软件/工具", 2
    if any(k in t for k in VIDEO_KW):
        return "影视/动漫", 5
    if any(k in t for k in BOOK_KW):
        return "书籍/资料", 3
    return "其他资源", 5


# 分类显示顺序
COURIER_ORDER = ["课程/教程", "软件/工具", "书籍/资料", "其他资源", "影视/动漫", "纯编程(可忽略)"]


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

    # 1) 列表（翻页：每页 25 条，实测 page=1/2/3 内容不同）
    print(f"[1/3] 取列表（{LIST_PAGES} 页）", flush=True)
    rows, seen_ids = [], set()
    for pg in range(1, LIST_PAGES + 1):
        purl = RSS if pg == 1 else f"{RSS}?page={pg}"
        status, md, via = fetch_pages(purl, timeout=90)
        if status != 200 or "linux.do/t/topic/" not in md:
            print(f"  page {pg}: 失败 http={status} 长度={len(md)}", flush=True)
            continue
        got = parse_feed(md)
        added = 0
        for r in got:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"]); rows.append(r); added += 1
        print(f"  page {pg}: 取到 {len(got)} 条，新增 {added} 条，累计 {len(rows)} 条", flush=True)
        time.sleep(TOPIC_DELAY)
    print(f"  列表合计 {len(rows)} 条", flush=True)
    if not rows:
        _write_empty(status, "")
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
                cat_name, prio = classify(it["title"])
                keep.append({"title": it["title"], "topic_url": it["url"],
                             "author": author, "created": to_bj(it["pub"]),
                             "net_url": url, "net_type": ntype, "tags": tags,
                             "cat": cat_name, "prio": prio})
                print(f"  [{i}/{len(rows)}] 收 {it['title'][:28]} | {ntype}", flush=True)
        time.sleep(TOPIC_DELAY)

    print(f"  收 {len(keep)} / 丢弃 {len(dropped)} / 跳过 {len(skipped)}", flush=True)

    # 3) 落盘
    ts = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    json.dump({"cat": CAT, "fetched_at": ts, "via": "jina", "from_feed": len(rows),
               "kept": keep, "dropped": dropped, "skipped": skipped},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sorted(seen), open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False)

    # 按 分类优先级 → 发帖时间倒序 排列
    ordered = sorted(keep, key=lambda x: (x["prio"], x["created"]), reverse=False)
    ordered.sort(key=lambda x: x["prio"])

    # 统计各分类数量
    from collections import Counter
    cnt = Counter(r["cat"] for r in keep)
    summary = "、".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda x: COURIER_ORDER.index(x[0]) if x[0] in COURIER_ORDER else 99))

    lines = [f"# linux.do 云资源 · {ts}", "",
             f"本轮收 {len(keep)} 条｜{summary}", ""]

    if keep:
        cur = None
        for r in ordered:
            if r["cat"] != cur:
                cur = r["cat"]
                lines += ["", f"========== {cur}（{cnt[cur]} 条）==========", ""]
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
