#!/usr/bin/env python3
"""fetch_artifacts.py — 从 GitHub 取回 artifact 并归档到本地。

野哥 11-13 02:10：本地都存下来，他自己从里面挑。
所以这个脚本做三件事：
  1. 拉最新 artifact 列表
  2. 下载并解压到本地目录
  3. 按类型追加到长期存档（linux.do 卷 / 效率向日报）
"""
import urllib.request, urllib.error, os, sys, json, zipfile, io, datetime, re, time

LOCAL_DIR = r"F:\Program Files\DS Harness Space\测试薅羊毛 26-11-07"
DATA_DIR = os.path.join(LOCAL_DIR, "_data")
ART_DIR = os.path.join(DATA_DIR, "gh_artifacts")
TOKEN_FILE = os.path.join(LOCAL_DIR, "Token.txt")
REPO = "moke5200/WEB"


def token():
    return open(TOKEN_FILE, encoding="utf-8").read().strip()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def api(path, raw=False, retries=3):
    """GitHub API 调用：15s 超时，失败按 2/4/8s 退避重试。"""
    tok = token()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        headers={"Authorization": "Bearer " + tok, "User-Agent": "fetch", "Accept": "application/vnd.github+json"})
    last = None
    for i in range(retries):
        try:
            r = urllib.request.urlopen(req, timeout=15)
            return r.read() if raw else json.load(r)
        except Exception as e:
            last = e
            if i < retries - 1:
                print(f"  [api] 失败 {type(e).__name__}，{2**(i+1)}s 后重试 ({i+1}/{retries})", flush=True)
                time.sleep(2 ** (i + 1))
    raise last


def download_artifact(url, retries=3):
    """下载 artifact：重定向 20s、内容 30s 超时，失败按 2/4/8s 退避重试。
    整个 302→Azure Blob 链路作为一个整体重试，避免半截状态。"""
    tok = token()
    last = None
    for i in range(retries):
        try:
            try:
                r = OPENER.open(urllib.request.Request(
                    url, headers={"Authorization": "Bearer " + tok, "User-Agent": "fetch"}), timeout=20)
                h = dict(r.headers)
            except urllib.error.HTTPError as e:
                h = dict(e.headers)
            loc = h.get("Location") or h.get("location")
            if not loc:
                raise RuntimeError("没有 Location 重定向头")
            return urllib.request.urlopen(
                urllib.request.Request(loc, headers={"User-Agent": "fetch"}), timeout=30).read()
        except Exception as e:
            last = e
            if i < retries - 1:
                print(f"  [dl] 失败 {type(e).__name__}，{2**(i+1)}s 后重试 ({i+1}/{retries})", flush=True)
                time.sleep(2 ** (i + 1))
    raise last


def update_seed_from_local():
    """扫 ART_DIR 下所有本地 json，把标题/URL/topic_id 并入去重种子。

    独立函数：不依赖本轮是否下载成功，也不依赖 fetched 字典。
    野哥 11-14 03:00「每一次往回取数据的时候就可以顺便更新了」。
    单独跑：python fetch_artifacts.py --seed-only
    """
    seed_path = os.path.join(os.path.dirname(DATA_DIR), "_github", "dedup_seed.json")
    added = {"t": 0, "u": 0, "i": 0}
    try:
        seed = json.load(open(seed_path, encoding="utf-8")) if os.path.exists(seed_path) else \
            {"titles": [], "urls": [], "topic_ids": [], "note": ""}
        T = set(seed.get("titles", [])); U = set(seed.get("urls", [])); I = set(seed.get("topic_ids", []))

        def norm(t):
            return re.sub(r"\s+", "", re.sub(r"[\-—·|｜!！?？,，。:：\[\]【】()（）]", "", t)).lower()

        def absorb(items):
            for it in items:
                if not isinstance(it, dict):
                    continue
                title = (it.get("title") or "").strip()
                if title:
                    k = norm(title)
                    if k and k not in T:
                        T.add(k); added["t"] += 1
                for key in ("url", "topic_url", "link"):
                    u = (it.get(key) or "").strip()
                    if u and u not in U:
                        U.add(u); added["u"] += 1
                        m = re.search(r"/topic/(\d+)", u)
                        if m and m.group(1) not in I:
                            I.add(m.group(1)); added["i"] += 1

        import glob
        files = glob.glob(os.path.join(ART_DIR, "**", "*.json"), recursive=True)
        for fp in files:
            try:
                d = json.load(open(fp, encoding="utf-8"))
            except Exception:
                continue
            if isinstance(d, dict):
                for key in ("items", "kept", "pushed", "all", "checked"):
                    if isinstance(d.get(key), list):
                        absorb(d[key])
                for sid, sv in (d.get("sources") or {}).items():
                    if isinstance(sv, dict) and isinstance(sv.get("items"), list):
                        absorb(sv["items"])
            elif isinstance(d, list):
                absorb(d)

        seed["titles"] = sorted(T); seed["urls"] = sorted(U); seed["topic_ids"] = sorted(I)
        seed["note"] = "最后自动更新 " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M") + "（取回时并入）"
        json.dump(seed, open(seed_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[2.5/3] 种子更新：扫 {len(files)} 个 json，+标题 {added['t']} / +URL {added['u']} / +topic {added['i']}", flush=True)
    except Exception as e:
        print(f"[2.5/3] 种子更新失败（不影响取回）：{type(e).__name__} {e}", flush=True)


def main():
    if "--seed-only" in sys.argv:
        print("[seed-only] 只用本地文件更新种子，不联网", flush=True)
        update_seed_from_local()
        return {}
    print("[1/3] 拉 artifact 列表", flush=True)
    arts = api("/actions/artifacts")["artifacts"]
    arts = [a for a in arts if not a["expired"]]
    print(f"  未过期共 {len(arts)} 份", flush=True)

    # 每类只取最新一份
    latest = {}
    for a in arts:
        kind = a["name"].rsplit("-", 1)[0]
        if kind not in latest or a["created_at"] > latest[kind]["created_at"]:
            latest[kind] = a

    os.makedirs(ART_DIR, exist_ok=True)
    print(f"[2/3] 下载 {len(latest)} 份最新 artifact", flush=True)
    fetched = {}
    ok_n = fail_n = 0
    for kind, a in sorted(latest.items()):
        try:
            data = download_artifact(a["archive_download_url"])
            z = zipfile.ZipFile(io.BytesIO(data))
            sub = os.path.join(ART_DIR, kind)
            os.makedirs(sub, exist_ok=True)
            files = {}
            for n in z.namelist():
                p = os.path.join(sub, n)
                os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(p) else None
                content = z.read(n)
                open(p, "wb").write(content)
                files[n] = len(content)
            fetched[kind] = {"dir": sub, "files": files, "created": a["created_at"]}
            ok_n += 1
            print(f"  {kind}: {len(files)} 个文件", flush=True)
        except Exception as e:
            fail_n += 1
            print(f"  {kind}: 重试后仍失败 {type(e).__name__} {e}", flush=True)
    print(f"  下载完成：成功 {ok_n} / 失败 {fail_n}", flush=True)

    update_seed_from_local()

    print("[3/3] 写入取回清单", flush=True)
    manifest = {
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "artifacts": fetched,
    }
    mf = os.path.join(DATA_DIR, "取回清单.json")
    json.dump(manifest, open(mf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  清单: {mf}", flush=True)
    return fetched


if __name__ == "__main__":
    main()
