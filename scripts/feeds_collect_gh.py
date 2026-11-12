#!/usr/bin/env python3
"""feeds_collect_gh.py — 多源福利/优惠 feed 采集（GitHub Actions）

源清单参考 luobinger/PerkRadar 的 source-defs.ts（11-12 借鉴）。
特点：这些都是公开 RSS/Atom，直连可用，不需要 Jina，也不占 Jina 额度。

采集方式：只取 feed 条目（标题 + 链接 + 时间 + 摘要），不逐条抓详情页。
理由：这些源的详情页要么无网盘链接，要么与福利信息无关；
      逐条抓会成倍消耗请求，收益低。

输出 out/feeds_report.md（按源分组）+ out/feeds_all.json（全量，供台账）。
"""
import re, os, sys, json, html, time, datetime, urllib.request, urllib.error

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

OUT_DIR = os.environ.get("FD_OUT_DIR", "out")
OUT_JSON = os.path.join(OUT_DIR, "feeds_all.json")
OUT_MD = os.path.join(OUT_DIR, "feeds_report.md")
MAX_ITEMS = int(os.environ.get("FD_MAX_ITEMS", "20"))
DELAY = float(os.environ.get("FD_DELAY", "2"))

"""抓取方式约定（野哥 11-12 23:16 拍板）
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
"""

# 源清单（野哥 11-12 23:16 拍板后精简）
# 砍掉：V2EX 推广（20 条全是机场/代充/卖号广告，没有真福利）
# 砍掉：小众软件（资讯站，非福利）、果核剥壳（软件下载站，非福利）
# 保留：异次元（实测有「双11打折整理」「夸克SVIP年卡」「iCloud+ 85折」这类真福利）
SOURCES = [
    {"id": "nodeseek", "name": "NodeSeek", "url": "https://rss.nodeseek.com/"},
    {"id": "iplaysoft", "name": "异次元软件世界", "url": "https://www.iplaysoft.com/feed"},
    {"id": "epic", "name": "Epic 免费游戏", "url": "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=zh-CN&country=CN&allowCountries=CN"},
]

# 噪声过滤（野哥 11-12：V2EX 推广版块机场/代充/卖号刷屏，这些不是福利）
NOISE = [
    "中转站", "机场", "代充", "代充值", "原生 IP", "住宅 IP", "静态 IP", "动态 IP",
    "IP 低至", "CDK 赠送", "开号", "卖号", "账号出售", "共享号", "合租",
    "流量包", "订阅套餐", "首单免费", "免费试用", "五折起", "低至",
    "V 友咨询", "欢迎咨询", "私聊", "加微信", "加 QQ", "TG 群",
    "代理 IP", "科学上网", "翻墙", "梯子",
    # 补充（11-12 实测漏网）
    "倍率", "聚合站", "注册赠送", "体验额度", "赠送", "不降智",
    "开户", "充值", "续费", "实名账户", "自助",
    "稳定中转", "中转[", "满血", "原生 Claude", "免费用",
    "IP 低至", "首单", "五折", "折扣码", "优惠码",
]

def is_noise(title):
    return any(k in title for k in NOISE)

os.makedirs(OUT_DIR, exist_ok=True)


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def fetch(url, timeout=30, retries=2):
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
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def pick(pattern, text):
    m = re.search(pattern, text, re.S)
    return strip_tags(m.group(1)) if m else ""


def to_bj(s):
    """多种 feed 时间格式 → 北京时间 YYYY-MM-DD HH:MM"""
    s = s.strip()
    if not s:
        return ""
    s = re.sub(r"\.\d+", "", s)          # 去掉毫秒
    s = s.replace("Z", "+0000")           # Z → +0000
    s = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", s)   # +08:00 → +0800
    fmts = ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"]
    for f in fmts:
        try:
            d = datetime.datetime.strptime(s, f)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except Exception:
            continue
    return s[:16]


def parse_feed(body):
    """兼容 RSS 2.0 与 Atom。"""
    items = []
    chunks = re.findall(r"<item[ >].*?</item>", body, re.S)
    is_atom = False
    if not chunks:
        chunks = re.findall(r"<entry[ >].*?</entry>", body, re.S)
        is_atom = True
    for ch in chunks:
        title = pick(r"<title[^>]*>(.*?)</title>", ch)
        if is_atom:
            lm = re.search(r'<link[^>]*href="([^"]+)"', ch)
            url = lm.group(1) if lm else ""
        else:
            url = pick(r"<link>(.*?)</link>", ch)
        date = (pick(r"<pubDate[^>]*>(.*?)</pubDate>", ch) or
                pick(r"<published[^>]*>(.*?)</published>", ch) or
                pick(r"<updated[^>]*>(.*?)</updated>", ch))
        desc = (pick(r"<description[^>]*>(.*?)</description>", ch) or
                pick(r"<summary[^>]*>(.*?)</summary>", ch))
        if title and url:
            items.append({"title": title, "url": url, "time": to_bj(date),
                          "desc": desc[:160]})
    return items


def parse_epic(body):
    """Epic 免费游戏：只取当前促销窗口且折扣价为 0 的。"""
    out = []
    try:
        d = json.loads(body)
        els = (d.get("data", {}).get("Catalog", {})
                .get("searchStore", {}).get("elements", []) or [])
        for e in els:
            promos = (e.get("promotions") or {}).get("promotionalOffers") or []
            if not promos:
                continue
            cur = e.get("price", {}).get("totalPrice", {})
            if cur.get("discountPrice") != 0:
                continue
            title = e.get("title", "")
            slug = ""
            for k in ("productSlug", "urlSlug"):
                v = e.get(k)
                if v:
                    slug = str(v).split("/")[0]
                    break
            url = f"https://store.epicgames.com/zh-CN/p/{slug}" if slug else "https://store.epicgames.com/zh-CN/free-games"
            end = ""
            try:
                end = to_bj(promos[0]["promotionalOffers"][0]["endDate"])
            except Exception:
                pass
            out.append({"title": title, "url": url, "time": end, "desc": "限时免费"})
    except Exception as e:
        print(f"    Epic 解析失败 {type(e).__name__}", flush=True)
    return out


def main():
    print(f"[1/2] 抓取 {len(SOURCES)} 个源", flush=True)
    result, lines = {}, [f"# 多源福利 feed · {now_bj().strftime('%Y-%m-%d %H:%M')}", ""]

    for s in SOURCES:
        status, body = fetch(s["url"])
        if status != 200 or not body:
            print(f"  {s['name']}: 失败 http={status}", flush=True)
            result[s["id"]] = {"status": status, "items": []}
            lines.append(f"## {s['name']} —— 抓取失败（http={status}）")
            lines.append("")
            time.sleep(DELAY)
            continue

        items = parse_epic(body) if s["id"] == "epic" else parse_feed(body)
        before = len(items)
        items = [x for x in items if not is_noise(x["title"])]
        filtered = before - len(items)
        items = items[:MAX_ITEMS]
        result[s["id"]] = {"status": status, "items": items}
        extra = f"（滤掉 {filtered} 条广告）" if filtered else ""
        print(f"  {s['name']}: {len(items)} 条{extra}", flush=True)

        lines.append(f"## {s['name']}（{len(items)} 条）")
        if items:
            for it in items:
                lines.append(f"- **{it['title']}**")
                if it.get("time"):
                    lines.append(f"  - 时间：{it['time']}")
                if it.get("desc"):
                    lines.append(f"  - 摘要：{it['desc']}")
                lines.append(f"  - 链接：{it['url']}")
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
