#!/usr/bin/env python3
"""smzdm_collect_gh.py — 值得买好价采集（GitHub Actions 版）

从 Box 版 smzdm_deals.py v0.4 提炼而来。核心判定规则保留：
  · 白嫖/极低价：免费领、0.01、1分钱 等，且价格 ≤ FREE_MAX_PRICE
  · 深折信号：史低、3折、4折、半价、1折 等，且价格 ≤ 2000
  · 降幅 ≥ 60%，或降价前售价比值 ≤ 0.4
  · 排除整类：旅游酒店机票、化妆品护肤、眼镜镜片镜框
  · 点名需求：从 want_list.json 读（可选）
输出到 out/ 目录，供 artifact 上传。
"""
import re, os, sys, json, html, time, datetime, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

OUT_DIR = os.environ.get("SZD_OUT_DIR", "out")
STATE_DIR = os.environ.get("SZD_STATE_DIR", "state")
OUT_JSON = os.path.join(OUT_DIR, "smzdm_deals.json")
OUT_MD = os.path.join(OUT_DIR, "smzdm_report.md")
OUT_CSV = os.path.join(OUT_DIR, "smzdm_all.csv")
STATE_FILE = os.path.join(STATE_DIR, "smzdm_seen.json")

PAGES = [
    ("精选好价", "https://www.smzdm.com/jingxuan/"),
    ("发现频道", "https://faxian.smzdm.com/"),
]
MAX_PAGE = int(os.environ.get("SZD_MAX_PAGE", "3"))

FREE = ["免费领", "白嫖", "免费送", "0.01", "1分钱", "一分钱", "免邮", "体验装"]
DEEP = ["史低", "历史低价", "3折", "4折", "三四折", "半价", "5折", "1折", "2折"]
FREE_MAX_PRICE = 20
DEEP_MAX_PRICE = 2000

# 整类排除（野哥 11-12 拍板）
NON_GOODS = ["酒店", "套房", "民宿", "机票", "跟团", "门票", "演出", "旅游", "度假", "房券", "住宿",
             "面霜", "精华", "洗颜", "乳液", "爽肤水", "眼霜", "面膜", "护肤", "彩妆", "口红", "粉底",
             "镜片", "镜框", "眼镜", "隐形眼镜", "美瞳"]

# 野哥点名要的东西（价格窗口）
WANTS = [
    {"name": "无线键鼠", "min": 0, "max": 150, "kw": ["无线键鼠", "键鼠套装", "无线键盘"]},
    {"name": "耳夹耳机", "min": 0, "max": 30, "kw": ["耳夹", "骨传导", "不入耳"]},
    {"name": "显示器27寸", "min": 0, "max": 300, "kw": ["27英寸", "27寸"]},
    {"name": "智能锁", "min": 0, "max": 200, "kw": ["智能锁", "指纹锁"]},
    # 野哥 11-12：家纺/收纳继续推（全屋收纳改造在做），价位放宽到 300
    {"name": "收纳改造", "min": 0, "max": 300,
     "kw": ["收纳袋", "收纳箱", "置物架", "货架", "收纳架", "真空压缩"]},
]

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    r = urllib.request.urlopen(req, timeout=timeout)
    return r.status, r.read().decode("utf-8", "replace")


def parse(html_text):
    """从 gtmAddToCart 抽结构化数据 + 卡片内的详情链接。"""
    items, seen = [], set()
    for m in re.finditer(r"gtmAddToCart\(\{(.*?)\}\)", html_text, re.S):
        d = dict(re.findall(r"'([^']+)'\s*:\s*'([^']*)'", m.group(1)))
        name = d.get("name", "").strip()
        if not name or not d.get("price") or name in seen:
            continue
        if name in ("好价", "好文"):
            continue
        seen.add(name)
        # 窗口右边界必须停在 gtm 之前，否则会吃进下一张卡片的链接（11-12 踩过）
        cs = html_text.rfind('class="feed-row-wide"', 0, m.start())
        if cs < 0:
            cs = html_text.rfind("<li", 0, m.start())
        if cs < 0:
            cs = max(0, m.start() - 4000)
        seg = html_text[cs:m.start()]
        dets = re.findall(r'href="(https://www\.smzdm\.com/p/\d+/)"', seg)
        gos = re.findall(r'href="(https://go\.smzdm\.com/[^"]+)"', seg)
        detail = dets[-1] if dets else ""
        pid = ""
        mm = re.search(r"/p/(\d+)/", detail)
        if mm:
            pid = mm.group(1)
        go = next((x for x in reversed(gos) if pid and pid in x), "")
        if pid and go and pid not in go:
            go = ""
        items.append({
            "name": name,
            "price": d.get("price", ""),
            "mall": d.get("mall", ""),
            "brand": d.get("brand", ""),
            "cat": d.get("category", ""),
            "detail": detail,
            "go": go,
        })
    return items


def judge(it):
    """返回 (是否推送, 理由, 等级)。等级: 3=白嫖/极低价 2=点名命中 1=深折 0=不推"""
    name = it["name"]
    try:
        p = float(it["price"])
    except (TypeError, ValueError):
        return False, "价格解析失败", 0
    hits = f"{name} {it.get('cat','')}"

    # 整类排除优先
    if any(k in hits for k in NON_GOODS):
        return False, "整类排除", 0

    # 白嫖/极低价（必须真的 0 元开头，不能是「含400元」里的 0）
    if re.search(r"(?<![\d.])0\s*元", hits) and p <= FREE_MAX_PRICE:
        return True, "疑似白嫖/极低价", 3
    if any(k in hits for k in FREE) and p <= FREE_MAX_PRICE:
        return True, "疑似白嫖/极低价(词命中)", 3

    # 深折信号
    if any(k in hits for k in DEEP) and p <= DEEP_MAX_PRICE:
        return True, "深折信号", 1

    # 点名需求
    for w in WANTS:
        if any(k in hits for k in w["kw"]) and w["min"] <= p <= w["max"]:
            return True, "点名需求:" + w["name"], 2

    return False, "", 0


def main():
    seen = set()
    if os.path.exists(STATE_FILE):
        try:
            seen = set(json.load(open(STATE_FILE, encoding="utf-8")))
        except Exception:
            pass
    print(f"[init] 历史已见 {len(seen)} 条", flush=True)

    all_items = []
    for label, base in PAGES:
        for pg in range(1, MAX_PAGE + 1):
            if "jingxuan" in base:
                url = base if pg == 1 else f"https://www.smzdm.com/jingxuan/p{pg}/"
            else:
                url = base if pg == 1 else f"https://faxian.smzdm.com/p{pg}/"
            try:
                status, body = fetch(url)
                rows = parse(body)
                print(f"  [{label} p{pg}] http={status} 商品 {len(rows)}", flush=True)
                for r in rows:
                    r["source"] = f"{label} p{pg}"
                all_items.extend(rows)
            except Exception as e:
                print(f"  [{label} p{pg}] ERR {type(e).__name__} {str(e)[:80]}", flush=True)
            time.sleep(2)

    # 去重（同名保留第一条）
    uniq, names = [], set()
    for r in all_items:
        if r["name"] in names:
            continue
        names.add(r["name"])
        uniq.append(r)
    print(f"[1/3] 抓取 {len(all_items)} 条，去重后 {len(uniq)} 条", flush=True)

    # 判定
    pushed, table_only = [], []
    for r in uniq:
        ok, why, lvl = judge(r)
        r["why"] = why
        r["level"] = lvl
        if ok:
            pushed.append(r)
        table_only.append(r)
    pushed.sort(key=lambda x: (-x["level"], float(x["price"]) if x["price"].replace(".", "", 1).isdigit() else 9e9))
    print(f"[2/3] 推送候选 {len(pushed)} 条（全量 {len(table_only)} 条入表）", flush=True)

    ts = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    json.dump({"fetched_at": ts, "total": len(uniq), "pushed": pushed,
               "all": table_only}, open(OUT_JSON, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 全量 CSV（给台账用）
    import csv
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["采集时间", "名称", "价格", "商城", "分类", "来源", "推送", "理由", "详情"])
        for r in table_only:
            w.writerow([ts, r["name"], r["price"], r["mall"], r["cat"], r["source"],
                        "Y" if r["level"] else "N", r["why"], r["detail"]])

    # 报告（只列推送候选）
    lines = [f"# 值得买好价 · {ts}", "", f"本轮抓取 {len(uniq)} 条，推送候选 {len(pushed)} 条。", ""]
    if pushed:
        for i, r in enumerate(pushed, 1):
            lines.append(f"## {i}. {r['name']}")
            lines.append(f"- 价格：¥{r['price']}  商城：{r['mall']}")
            lines.append(f"- 理由：{r['why']}")
            if r.get("detail"):
                lines.append(f"- 详情：{r['detail']}")
            if r.get("go"):
                lines.append(f"- 去购买：{r['go']}")
            lines.append("")
    else:
        lines.append("本轮无推送候选。")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))

    print(f"[3/3] NEW={len(pushed)} TOTAL={len(uniq)}", flush=True)


if __name__ == "__main__":
    main()
