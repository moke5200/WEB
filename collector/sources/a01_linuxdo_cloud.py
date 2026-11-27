#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a01 · linux.do 云资源版（c/resource/cloud-asset/94）

抓法：直连优先，被 Cloudflare 429/403 挡住才走 r.jina.ai 中转。
            （GitHub Actions 的 IP 段长期被拦，云端基本都走 Jina。）
收的规则（野哥定稿）：
  · 标签含「夸克」或「百度」才收
  · 资源链接百度优先（保留提取码），没有才用夸克；两个都没有 → 整条丢弃
  · 按网盘链接 ID 去重（同资源不同人重发只收一次）
  · 列表 RSS 一次只给 25 条，靠 ?page=N 翻页补全
输出：001.md 5 行格式
"""
import html
import os
import re
import time

from sources.base import Source

CAT = "https://linux.do/c/resource/cloud-asset/94"
RSS = CAT + ".rss"
LIST_PAGES = int(os.environ.get("LD_LIST_PAGES", "2"))
MAX_TOPICS = int(os.environ.get("LD_MAX_TOPICS", "50"))
TOPIC_DELAY = float(os.environ.get("LD_TOPIC_DELAY", "4"))     # Jina 免费档 20 RPM，留余量
CONSEC_FAIL_LIMIT = 4


def to_bj(rfc822):
    """RFC822 → 北京时间字符串。"""
    import datetime
    t = " ".join((rfc822 or "").split())
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
    """从 Jina 转出的 Markdown 列表拆 (标题, url, id, 发布时间)。"""
    out, seen = [], set()
    chunks = re.split(r"^#{2,4} \[", md or "", flags=re.M)[1:]
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
    """单帖 Markdown：取作者 + 正文段（砍掉 Related topics）。"""
    author = ""
    m = re.search(r"post by (\S+)", md or "")
    if m:
        author = m.group(1)
    start = m.start() if m else 0
    seg = (md or "")[start:]
    tail = seg.find("### Related topics")
    if tail > 0:
        seg = seg[:tail]
    return author, seg


def extract_nets(seg):
    """抽网盘链接：百度优先（带提取码），否则夸克。返回 (url, 类型, ID)。"""
    bd = re.search(r"https?://pan\.baidu\.com/s/[\w-]+(?:\?pwd=([\w]{4,8}))?", seg)
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
        return url, "百度网盘", (nid.group(1) if nid else "")

    qk = re.search(r"https?://pan\.quark\.cn/s/[\w-]+", seg)
    if qk:
        url = qk.group(0)
        cmd = re.search(r"/~([0-9a-fA-F]+)~:/?", seg)
        if cmd:
            url += "  (口令 /~%s~:/)" % cmd.group(1)
        nid = re.search(r"/s/([\w-]+)", url)
        return url, "夸克网盘", (nid.group(1) if nid else "")
    return "", "", ""


def extract_tags(md):
    """只取正文区（Related topics 之前）的标签，避免把相关帖标签混进来。"""
    head = (md or "").split("### Related topics", 1)[0]
    tags = []
    for m in re.finditer(r"\[(百度网盘|夸克网盘|迅雷网盘|影视|动漫|人工智能|软件|教程|电子书)\]"
                         r"\(https://linux\.do/tag/", head):
        if m.group(1) not in tags:
            tags.append(m.group(1))
    return tags


# ---- 分类（课程优先，野哥 11-13 要求）----
COURSE_KW = ["课", "教程", "训练营", "实战", "系统班", "全集", "全套", "精讲", "入门",
             "进阶", "从0到1", "从零", "速成", "系统课", "专栏", "讲座", "特训", "集训",
             "大师课", "必修", "研修", "分享会", "开发", "精通", "学习", "讲解", "指南",
             "方法论", "体系", "陪跑", "班", "营", "完整版"]
SOFT_KW = ["软件", "工具", "插件", "脚本", "破解", "绿色版", "便携版", "安装包", "播放器",
           "客户端", "编辑器", "管理器", "下载器", "转换器", "助手", "官方版", "汉化版", "免安装"]
VIDEO_KW = ["剧", "电影", "动漫", "综艺", "纪录片", "4K", "HDR", "中字", "中文字幕",
            "更新至", "更至", "完结", "蓝光", "1080P", "2160P", "双语", "影视", "短剧", "漫剧"]
BOOK_KW = ["电子书", "PDF", "书籍", "epub", "mobi", "azw3", "资料包"]
PROG_KW = ["Java", "Python", "JavaScript", "TypeScript", "React", "Vue", "Golang", "Rust",
           "C++", "C语言", "PHP", "前端", "后端", "全栈", "算法", "数据结构", "数据库",
           "MySQL", "Redis", "微服务", "架构师", "编程", "爬虫", "运维", "Docker", "K8s",
           "Spring", "Django", "Flask", "小程序开发", "安卓开发", "iOS开发", "少儿编程", "Scratch"]
NOT_PURE_PROG = ["AI视频", "AI绘画", "AI写作", "AI剪辑", "数字人", "提示词", "Prompt",
                 "AI创作", "AI短剧", "AI漫剧", "AI配音", "AI换脸", "AI写真", "AI绘图"]


def classify(title):
    """返回 (分类, 优先级)，数字越小越靠前。纯编程排最后但仍收。"""
    t = title or ""
    if any(k in t for k in PROG_KW) and not any(k in t for k in NOT_PURE_PROG):
        return "纯编程(可忽略)", 9
    if any(k in t for k in COURSE_KW):
        return "课程/教程", 1
    if any(k in t for k in SOFT_KW):
        return "软件/工具", 2
    if any(k in t for k in BOOK_KW):
        return "书籍/资料", 3
    if any(k in t for k in VIDEO_KW):
        return "影视/动漫", 5
    return "其他资源", 5


class LinuxDoCloud(Source):
    id = "a01"
    name = "linux.do 云资源版"
    category = "云资源"
    freq = "6h"
    runs_on = "cloud"
    raw_lang = "zh"
    platform = "linux.do"

    def _get(self, url):
        via, st, txt = self.get(url, prefer_direct=True, timeout=90)
        return st, txt, via

    def fetch(self, cfg=None, seen=None):
        items, failed = [], []
        # 1) 列表（翻页）
        rows, seen_ids = [], set()
        for pg in range(1, LIST_PAGES + 1):
            pure = RSS if pg == 1 else "%s?page=%d" % (RSS, pg)
            st, md, via = self._get(pure)
            if st != 200 or "linux.do/t/topic/" not in (md or ""):
                print("    [a01] 列表 page%d 失败 http=%s via=%s" % (pg, st, via), flush=True)
                continue
            got = parse_feed(md)
            added = 0
            for r in got:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"]); rows.append(r); added += 1
            print("    [a01] page%d 取 %d 条，新增 %d（via %s）" % (pg, len(got), added, via), flush=True)
            time.sleep(TOPIC_DELAY)
        if not rows:
            return [], ["列表为空或抓取失败"]

        # 1.5) 台账过滤——命中直接跳过，不再抓详情页（省 Jina 额度）
        before = len(rows)
        rows = [r for r in rows if not self.is_seen(seen, post_id=r["id"], url=r["url"])]
        skipped = before - len(rows)
        if skipped:
            print("    [a01] 台账命中跳过 %d 条，剩 %d 条待抓" % (skipped, len(rows)), flush=True)
        if not rows:
            return [], []

        rows = rows[:MAX_TOPICS]
        # 2) 逐帖
        consec = 0
        for i, it in enumerate(rows, 1):
            if consec >= CONSEC_FAIL_LIMIT:
                failed.append("连续失败 %d 次，提前收尾" % consec)
                break
            st, tmd, _via = self._get(it["url"])
            if st != 200 or ("post by" not in (tmd or "") and "URL Source:" not in (tmd or "")):
                consec += 1
                failed.append("单帖失败 %s" % it["url"])
                time.sleep(TOPIC_DELAY)
                continue
            consec = 0
            author, seg = extract_body(tmd)
            net_url, net_type, nid = extract_nets(seg)
            tags = extract_tags(tmd)
            has_tag = any(("夸克" in t) or ("百度" in t) for t in tags)

            if has_tag and net_url:
                cat, prio = classify(it["title"])
                items.append(self.item(
                    title=it["title"], url=it["url"], author=author,
                    published=to_bj(it["pub"]), tags=tags,
                    summary="%s｜%s" % (cat, net_type),
                    extra={"dedup_key": "%s:%s" % (net_type, nid),
                           "net_url": net_url, "net_type": net_type,
                           "cat": cat, "prio": prio,
                           "post_id": it["id"], "platform": "linux.do"},
                ))
            else:
                # 没标签或没网盘链接：也要记台账，否则下一轮还会重复抓这个详情页
                if seen is not None:
                    seen.mark("linux.do", it["id"], it["url"], self.id)
            time.sleep(TOPIC_DELAY)
        print("    [a01] 收 %d 条" % len(items), flush=True)
        return items, failed