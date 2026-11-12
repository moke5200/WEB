#!/usr/bin/env python3
"""ld_collect_gh.py — linux.do 云资源收集（GitHub Actions 版）
派生自 Box 上的 ld_collect.py v0.2，改动只有三处：
  ① 路径全部改成 环境变量或 ./ 相对路径（Actions 里没有 /workspace）
  ② 去重库 seen 通过 artifact/缓存 传递，不由仓库跟踪
  ③ 每收一条增量落盘
业务逻辑（标签筛选、百度优先、七行格式、断档补采）一律不动。
"""
import subprocess, re, json, html, time, os, sys, datetime

CAT = "https://linux.do/c/resource/cloud-asset/94"
RSS = CAT + ".rss"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

OUT_DIR   = os.environ.get("LD_OUT_DIR", "out")
STATE_DIR = os.environ.get("LD_STATE_DIR", "state")
OUT_JSON  = os.path.join(OUT_DIR, "ld_deals.json")
OUT_MD    = os.path.join(OUT_DIR, "ld_report.md")
SEEN_FILE = os.path.join(STATE_DIR, ".ld_seen.json")
BACKFILL_FROM = os.environ.get("LD_BACKFILL_FROM", "2026-11-07 04:53")
PAGE_LIMIT    = int(os.environ.get("LD_PAGE_LIMIT", "45"))
BACKFILL_MAX  = int(os.environ.get("LD_BACKFILL_MAX", "60"))
CONSEC_FAIL_LIMIT = 3

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

def curl(url, timeout=30):
    r = subprocess.run(["curl", "-sS", "-L", "--max-time", str(timeout), "-A", UA, url],
                       capture_output=True)
    return r.returncode, r.stdout

def to_bj(utc_str):
    try:
        d = datetime.datetime.strptime(utc_str[:19], "%Y-%m-%dT%H:%M:%S")
        return (d + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return utc_str[:16].replace("T", " ")

def parse_rss(xml):
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def g(p):
            m = re.search(p, it, re.S)
            return m.group(1).strip() if m else ""
        link = g(r"<link>(.*?)</link>")
        m = re.search(r"/t/[^/]+/(\d+)", link)
        out.append({"title": html.unescape(g(r"<title>(.*?)</title>")),
                    "url": link, "id": m.group(1) if m else "",
                    "pub": g(r"<pubDate>(.*?)</pubDate>")})
    return out

def clean_body(cooked):
    t = html.unescape(re.sub(r"<[^>]+>", " ", cooked))
    t = re.sub(r"[\u200b-\u200f\u2060-\u2064\ufeff\u2066-\u2069]", "", t)
    return re.sub(r"\s+", " ", t).strip()

def fetch_topic(tid, retries=2):
    for attempt in range(retries + 1):
        code, raw = curl(f"https://linux.do/t/topic/{tid}.json")
        if raw.strip().startswith(b"{"):
            try: return json.loads(raw.decode("utf-8", "replace"))
            except Exception: pass
        head = raw[:400].decode("utf-8", "replace")
        limited = ("Just a moment" in head) or ("too many" in head.lower())
        if attempt < retries: time.sleep(10 * (attempt + 1) if limited else 3)
        else: return None
    return None

def extract_nets(cooked, body):
    links = [html.unescape(x) for x in re.findall(r'href="([^"]+)"', cooked)]
    baidu = next((l for l in links if "pan.baidu.com" in l), "")
    quark = next((l for l in links if "pan.quark.cn" in l), "")
    pwd = ""
    if baidu:
        m = re.search(r"pwd=([A-Za-z0-9]{4,8})", baidu)
        if m: pwd = m.group(1)
    if not pwd and baidu:
        m = re.search(r"(?:提取码|密码|pwd)[:：\s]*([A-Za-z0-9]{4,8})", body)
        if m: pwd = m.group(1)
    qk = re.search(r"/~([A-Za-z0-9]+)~:/", body)
    if baidu:
        link = baidu if "pwd=" in baidu else (baidu + ("&pwd=" if "?" in baidu else "?pwd=") + pwd if pwd else baidu)
        return link, "百度网盘", baidu.split("/s/")[-1].split("?")[0].split("&")[0]
    if quark:
        link = quark
        if qk: link += f"  (口令 /~{qk.group(1)}~:/)"
        return link, "夸克网盘", quark.split("/s/")[-1].split("?")[0]
    return "", "", ""

def net_key(url, typ):
    m = re.search(r"/s/([A-Za-z0-9_-]+)", url)
    return f"{typ}:{m.group(1)}" if m else ""

def build_topic(d):
    tags = [t.get("name", "") for t in (d.get("tags") or [])]
    posts = d.get("post_stream", {}).get("posts", [])
    cooked = posts[0].get("cooked", "") if posts else ""
    body = clean_body(cooked)
    url, typ, nid = extract_nets(cooked, body)
    return {"id": d.get("id"), "title": d.get("title"), "tags": tags,
            "author": (d.get("details") or {}).get("created_by", {}).get("username", ""),
            "created": to_bj(d.get("created_at", "")),
            "net_url": url, "net_type": typ, "net_id": nid,
            "net_key": net_key(url, typ),
            "body": body[:800], "topic_url": f"https://linux.do/t/topic/{d.get('id')}"}

def load_json(p, default):
    if os.path.exists(p):
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: pass
    return default

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    seen_keys = set(load_json(SEEN_FILE, []))
    print(f"[init] 已收网盘ID {len(seen_keys)}", flush=True)

    pages = [1] if mode == "normal" else list(range(1, PAGE_LIMIT + 1))
    lst, seen_ids = [], set()
    for pg in pages:
        u = f"{RSS}?page={pg}"
        code, raw = curl(u)
        xml = raw.decode("utf-8", "replace")
        if "<item>" not in xml:
            print(f"  page {pg}: 空/限流，跳过", flush=True)
            time.sleep(12); continue
        rows = parse_rss(xml)
        if mode == "backfill":
            rows = [r for r in rows if r["pub"] and to_bj(r["pub"].replace(" +0000","")) >= BACKFILL_FROM]
        for r in rows:
            if r["id"] and r["id"] not in seen_ids:
                seen_ids.add(r["id"]); lst.append(r)
        if rows:
            print(f"  page {pg}: {len(rows)} 条, 累计 {len(lst)}", flush=True)
        if mode == "backfill" and rows and to_bj(rows[-1]["pub"].replace(" +0000","")) < BACKFILL_FROM:
            print("  已翻过断档起点，停止", flush=True); break
        time.sleep(8)
    print(f"[1/3] 列表 {len(lst)} 条", flush=True)
    if mode == "backfill" and len(lst) > BACKFILL_MAX:
        lst = lst[:BACKFILL_MAX]
        print(f"[limit] 补档限量取前 {BACKFILL_MAX} 条", flush=True)

    keep, dropped, skipped = [], [], []
    consec_fail = 0
    for i, it in enumerate(lst, 1):
        if consec_fail >= CONSEC_FAIL_LIMIT:
            print(f"[stop] 连续失败 {consec_fail} 次，提前收尾", flush=True); break
        d = fetch_topic(it["id"])
        if not d:
            consec_fail += 1
            skipped.append({"title": it["title"], "why": "单帖抓取失败"}); continue
        consec_fail = 0
        rec = build_topic(d)
        has_tag = any(("夸克" in x) or ("百度" in x) for x in rec["tags"])
        if not has_tag:
            skipped.append({"title": rec["title"], "why": "标签无夸克/百度"}); continue
        if not rec["net_url"]:
            dropped.append({"title": rec["title"], "why": "无百度/夸克资源链接"}); continue
        if rec["net_key"] in seen_keys:
            skipped.append({"title": rec["title"], "why": "资源链接已收(同资源)"}); continue
        seen_keys.add(rec["net_key"])
        keep.append(rec)
        print(f"  [{i}/{len(lst)}] 收 {rec['title'][:34]} | {rec['net_type']}", flush=True)
        time.sleep(8)

    print(f"[2/3] 收 {len(keep)} / 丢弃 {len(dropped)} / 跳过 {len(skipped)}", flush=True)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    json.dump({"cat": CAT, "mode": mode, "fetched_at": now,
               "from_rss": len(lst), "kept": keep, "dropped": dropped, "skipped": skipped},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sorted(seen_keys), open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False)

    lines = [f"# linux.do 云资源 · {now}", ""]
    for r in sorted(keep, key=lambda x: x["created"]):
        lines += [f"【标题】{r['title']}", f"链接：{r['topic_url']}",
                  f"资源链接：{r['net_url']}", f"标签：{','.join(r['tags'])}",
                  f"发帖人：{r['author']}", f"发帖时间：{r['created']}",
                  f"收集时间：{now[:16]}", ""]
    if not keep:
        lines.append("本轮无新增。")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[3/3] NEW_COUNT={len(keep)} DROP_COUNT={len(dropped)} SKIP_COUNT={len(skipped)}", flush=True)

if __name__ == "__main__": main()
