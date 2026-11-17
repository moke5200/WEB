"""羊毛清单 —— FastAPI + PostgreSQL（含整理报告页）

页面：
  /          清单页（表格 + 筛选）
  /report    整理报告页（静态，好看版）
  /daily     每日羊毛页（数据库里的当日 HTML，野哥标注用）
接口：
  POST /api/ingest        写入数据（需 token）
  POST /api/report/html   上传每日 HTML（需 token）
  POST /api/feedback      上传标注（公开，用户浏览器直传）
  GET  /api/feedback      读取标注（公开，供采集端拉取）
  POST /api/self-update   远程更新本文件源码（需 token）
  GET  /api/items         查询
  GET  /api/stats         统计
  GET  /api/ping          探针
"""
import html
import os

import psycopg
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

DATABASE_URL = os.environ["DATABASE_URL"]
INGEST_TOKEN = os.environ.get("INGEST_TOKEN") or "wool2026dsh"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          serial PRIMARY KEY,
    url         text NOT NULL UNIQUE,
    title       text NOT NULL,
    cat         text,
    days        int,
    end_date    text,
    status      text,
    source      text,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS items_cat_idx ON items (cat);
CREATE INDEX IF NOT EXISTS items_status_idx ON items (status);
CREATE INDEX IF NOT EXISTS items_last_seen_idx ON items (last_seen DESC);
CREATE TABLE IF NOT EXISTS feedback (
    id          serial PRIMARY KEY,
    item_id     text NOT NULL,
    day         text NOT NULL,
    pri         text,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_day_idx ON feedback (day DESC);
CREATE TABLE IF NOT EXISTS daily_html (
    day         text PRIMARY KEY,
    content     text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
"""


def connect():
    return psycopg.connect(DATABASE_URL)


with connect() as _c:
    _c.execute(SCHEMA)

app = FastAPI(title="羊毛清单")


class Row(BaseModel):
    url: str
    title: str
    cat: str | None = None
    days: int | None = None
    end: str | None = None
    status: str | None = None
    source: str | None = None


class FeedbackIn(BaseModel):
    """一条标注。item_id 是页面上 data-id，day 是页面日期。"""
    item_id: str
    day: str
    pri: str | None = None
    note: str | None = None


class ReportHtml(BaseModel):
    day: str
    html: str


UPSERT = """
INSERT INTO items (url, title, cat, days, end_date, status, source, last_seen)
VALUES (%(url)s, %(title)s, %(cat)s, %(days)s, %(end)s, %(status)s, %(source)s, now())
ON CONFLICT (url) DO UPDATE SET
    title     = EXCLUDED.title,
    cat       = EXCLUDED.cat,
    days      = EXCLUDED.days,
    end_date  = EXCLUDED.end_date,
    status    = EXCLUDED.status,
    source    = EXCLUDED.source,
    last_seen = now()
"""

COLS = ("SELECT url, title, cat, days, end_date, status, source, "
        "to_char(last_seen, 'YYYY-MM-DD HH24:MI') AS last_seen FROM items WHERE 1=1")


def fetch(cat=None, status=None, q=None, limit=500):
    sql = COLS
    params = {}
    if cat:
        sql += " AND cat = %(cat)s"
        params["cat"] = cat
    if status:
        sql += " AND status = %(status)s"
        params["status"] = status
    if q:
        sql += " AND (title ILIKE %(q)s OR url ILIKE %(q)s)"
        params["q"] = "%" + q + "%"
    sql += " ORDER BY last_seen DESC, id DESC LIMIT %(limit)s"
    params["limit"] = limit
    with connect() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            names = [d.name for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]


def counts():
    with connect() as c:
        with c.cursor() as cur:
            cur.execute("SELECT count(*), to_char(max(last_seen), 'YYYY-MM-DD HH24:MI') FROM items")
            total, last = cur.fetchone()
    return total or 0, last or "—"


@app.post("/api/ingest")
def ingest(rows: list[Row], authorization: str = Header(default="")):
    if authorization != "Bearer " + INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="bad token")
    if not rows:
        return {"ok": True, "written": 0}
    payload = [r.model_dump() for r in rows]
    with connect() as c:
        with c.cursor() as cur:
            cur.executemany(UPSERT, payload)
    return {"ok": True, "written": len(payload)}


@app.post("/api/report/html")
def upload_report(payload: ReportHtml, authorization: str = Header(default="")):
    """存每日 HTML。同 day 覆盖（当日重推不堆行）。限 512KB。"""
    if authorization != "Bearer " + INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="bad token")
    h = payload.html or ""
    if len(h) < 500:
        raise HTTPException(status_code=400, detail="html too short")
    if len(h) > 512 * 1024:
        raise HTTPException(status_code=400, detail="html too large")
    with connect() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO daily_html (day, content, updated_at) VALUES (%s,%s,now()) "
                "ON CONFLICT (day) DO UPDATE SET content=EXCLUDED.content, updated_at=now()",
                (payload.day, h))
    return {"ok": True, "day": payload.day, "bytes": len(h)}


@app.get("/daily", response_class=HTMLResponse)
def daily_page(day: str | None = None):
    """从数据库读每日 HTML 展示。没有就提示。"""
    with connect() as c:
        with c.cursor() as cur:
            if day:
                cur.execute("SELECT content FROM daily_html WHERE day=%s", (day,))
            else:
                cur.execute("SELECT content FROM daily_html ORDER BY day DESC LIMIT 1")
            row = cur.fetchone()
    if not row:
        return HTMLResponse("<h1>当日页面还没上传</h1><p>等采集任务推一次就好。</p>")
    return HTMLResponse(row[0])


@app.post("/api/feedback")
def save_feedback(fb: FeedbackIn):
    """标注回传。公开接口：只写 feedback 表，且 upsert——同一条反复改只留最新。"""
    if fb.pri not in (None, "up", "down"):
        raise HTTPException(status_code=400, detail="pri must be up/down")
    with connect() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO feedback (item_id, day, pri, note) VALUES (%s,%s,%s,%s) "
                "RETURNING id", (fb.item_id, fb.day, fb.pri, fb.note))
            fid = cur.fetchone()[0]
            # 同 item 同 day 保留最新一条，删旧的
            cur.execute(
                "DELETE FROM feedback WHERE item_id=%s AND day=%s AND id<>%s",
                (fb.item_id, fb.day, fid))
    return {"ok": True, "id": fid}


@app.get("/api/feedback")
def get_feedback(day: str | None = None, limit: int = Query(default=500, ge=1, le=2000)):
    """拉标注。采集端每次出新一页前来读。"""
    with connect() as c:
        with c.cursor() as cur:
            if day:
                cur.execute(
                    "SELECT item_id, day, pri, note, to_char(created_at,'YYYY-MM-DD HH24:MI') "
                    "FROM feedback WHERE day=%s ORDER BY id DESC LIMIT %s", (day, limit))
            else:
                cur.execute(
                    "SELECT item_id, day, pri, note, to_char(created_at,'YYYY-MM-DD HH24:MI') "
                    "FROM feedback ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    names = ["item_id", "day", "pri", "note", "created_at"]
    return {"ok": True, "count": len(rows),
            "items": [dict(zip(names, r)) for r in rows]}


@app.post("/api/self-update")
def self_update(payload: dict, authorization: str = Header(default="")):
    if authorization != "Bearer " + INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="bad token")
    code = (payload or {}).get("code") or ""
    if len(code) < 500 or "FastAPI" not in code:
        raise HTTPException(status_code=400, detail="code looks wrong")
    target = os.path.abspath(__file__)
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            old = f.read()
        with open(target + ".bak", "w", encoding="utf-8") as f:
            f.write(old)
    tmp = target + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(code)
    os.replace(tmp, target)
    return {"ok": True, "bytes": len(code), "path": target, "backup": target + ".bak"}


DIAG_CMDS = {
    "free": "free -m",
    "cgroup": "cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.max 2>/dev/null || "
              "cat /sys/fs/cgroup/memory/memory.usage_in_bytes /sys/fs/cgroup/memory.limit_in_bytes",
    "ps_mem": "ps aux --sort=-%mem | head -20",
    "ps_procs": "ps aux | grep -E 'uvicorn|python|postgres' | grep -v grep",
    "requirements": "cat requirements.txt 2>/dev/null",
    "start_cmd": "grep -iE 'worker|uvicorn|gunicorn' Dockerfile docker-compose.yml main.py 2>/dev/null",
    "db_refs": "grep -iE 'DATABASE_URL|sqlalchemy|psycopg|asyncpg|database|postgres|create_engine' "
               "main.py requirements.txt docker-compose.yml Dockerfile 2>/dev/null",
    "cmdline": "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' '; echo; "
               "ps -eo pid,ppid,rss,comm,args --sort=-rss | head -15",
    "rss_sum": "ps -eo rss --no-headers | awk '{s+=$1} END {print s \" KB total RSS\"}'",
    "files": "ls -la /home/uppcoder/app 2>/dev/null | head -25",
    "cg_all": "cat /proc/self/cgroup; echo '--- 本级 ---'; "
              "for f in memory.current memory.max memory.peak memory.swap.current; do "
              "printf '%s=' $f; cat /sys/fs/cgroup/$f 2>/dev/null || echo NA; done; "
              "echo '--- 上级 ---'; "
              "for d in /sys/fs/cgroup/.. /sys/fs/cgroup; do printf '%s ' $d; "
              "cat /d/memory.current 2>/dev/null || echo NA; done",
    "stat_total": "grep -E '^(anon|file|kernel|slab|sock|shmem|total_)' /sys/fs/cgroup/memory.stat 2>/dev/null",
    "events": "cat /sys/fs/cgroup/memory.events 2>/dev/null; echo '--- oom ---'; "
              "cat /sys/fs/cgroup/memory.oom.group 2>/dev/null; "
              "dmesg 2>/dev/null | grep -i 'killed process' | tail -3 || echo 'dmesg 不可读'",
    "top_detail": "ps -eo pid,ppid,rss,vsz,etime,args --sort=-rss | head -12",
    "memstat": "head -25 /sys/fs/cgroup/memory.stat 2>/dev/null",
    "mempeak": "cat /sys/fs/cgroup/memory.peak 2>/dev/null; "
               "cat /sys/fs/cgroup/memory.max 2>/dev/null",
    "compose": "cat docker-compose.yml 2>/dev/null; echo '--- Dockerfile ---'; cat Dockerfile 2>/dev/null",
    "docker": "ps aux | grep -iE 'dockerd|containerd' | grep -v grep | head -5; "
              "ls /var/run/docker.sock 2>/dev/null && echo 'docker.sock 存在' || echo '无 docker.sock'",
    "pgconn": "grep -o 'postgresql://[^ ]*' docker-compose.yml 2>/dev/null | head -2; "
              "env | grep -iE 'DATABASE_URL|POSTGRES' | sed 's/:\\/\\/[^@]*@/:\\/\\/***@/'",
    "pg_mem": "__PG__",
}


@app.get("/api/diag")
def api_diag(authorization: str = Header(default=""), only: str | None = None):
    """只读诊断：把内存相关的命令跑一遍，返回结果。需要 token。"""
    if authorization != "Bearer " + INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="bad token")
    import subprocess

    out = {}
    names = [only] if only else list(DIAG_CMDS)
    for name in names:
        if name == "pg_mem":
            out[name] = pg_mem_report()
            continue
        cmd = DIAG_CMDS.get(name)
        if not cmd:
            out[name] = "unknown key"
            continue
        try:
            r = subprocess.run(
                ["/bin/sh", "-c", cmd],
                capture_output=True, text=True, timeout=25,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            out[name] = (r.stdout or "")[:6000] + (
                (("\n[stderr] " + r.stderr[:600]) if r.stderr.strip() else "")
            )
        except Exception as exc:
            out[name] = f"{type(exc).__name__}: {exc}"
    return {"ok": True, "cwd": os.path.dirname(os.path.abspath(__file__)), "results": out}


def pg_mem_report() -> str:
    """问数据库自己：连了多少、吃了多少、表多大。只读查询。"""
    out = []
    try:
        with connect() as c:
            with c.cursor() as cur:
                for label, sql in (
                    ("版本", "SELECT version()"),
                    ("连接数", "SELECT count(*) FROM pg_stat_activity"),
                    ("连接明细", "SELECT pid, state, backend_start::text, "
                                 "coalesce(query,'') FROM pg_stat_activity ORDER BY backend_start"),
                    ("库大小", "SELECT pg_size_pretty(pg_database_size(current_database()))"),
                    ("表大小", "SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) "
                               "FROM pg_class WHERE relkind='r' ORDER BY pg_total_relation_size(oid) DESC LIMIT 10"),
                    ("缓存命中", "SELECT sum(blks_hit) AS hit, sum(blks_read) AS read "
                                 "FROM pg_stat_database"),
                ):
                    try:
                        cur.execute(sql)
                        rows = cur.fetchall()
                        out.append(f"[{label}]")
                        for row in rows[:12]:
                            out.append("  " + " | ".join(str(x)[:90] for x in row))
                    except Exception as exc:
                        out.append(f"[{label}] 查询失败 {type(exc).__name__}: {exc}")
    except Exception as exc:
        out.append(f"连接失败 {type(exc).__name__}: {exc}")
    return "\n".join(out)[:6000]


@app.get("/api/ping")
def api_ping():
    total, _ = counts()
    return {"ok": True, "total": total}


@app.get("/api/items")
def api_items(
    cat: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
):
    rows = fetch(cat, status, q, limit)
    total, last = counts()
    return JSONResponse(
        {"ok": True, "count": len(rows), "total": total, "last_seen": last, "items": rows},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/stats")
def api_stats():
    total, last = counts()
    with connect() as c:
        with c.cursor() as cur:
            cur.execute("SELECT cat, count(*) FROM items GROUP BY cat ORDER BY 2 DESC")
            cats = [{"cat": k, "n": v} for k, v in cur.fetchall()]
    return {"total": total, "last_seen": last, "by_category": cats}


# ─────────────────────────── 清单页 ───────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>羊毛清单</title>
<style>
:root{{
  color-scheme: dark light;
  --bg-l:#f6f8fc; --bg-d:#16191f;
  --text-l:#172033; --text-d:#f2f5fb;
  --muted-l:#5b6475; --muted-d:#a9b3c4;
  --line-l:#d8deea; --line-d:#333a47;
  --card-l:#ffffff; --card-d:#20242f;
  --link-l:#1558c0; --link-d:#8fc0ff;
  --bg:var(--bg-l); --text:var(--text-l); --muted:var(--muted-l);
  --line:var(--line-l); --card:var(--card-l); --link:var(--link-l);
}}
@media (prefers-color-scheme: dark){{
  :root{{ --bg:var(--bg-d); --text:var(--text-d); --muted:var(--muted-d);
    --line:var(--line-d); --card:var(--card-d); --link:var(--link-d); }}
}}
@supports (color: light-dark(white, black)){{
  :root{{
    --bg:light-dark(var(--bg-l), var(--bg-d));
    --text:light-dark(var(--text-l), var(--text-d));
    --muted:light-dark(var(--muted-l), var(--muted-d));
    --line:light-dark(var(--line-l), var(--line-d));
    --card:light-dark(var(--card-l), var(--card-d));
    --link:light-dark(var(--link-l), var(--link-d));
  }}
}}
*{{box-sizing:border-box}}
body{{margin:0;padding:1.5rem 1rem 4rem;background:var(--bg);color:var(--text);
  font:1rem/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  max-inline-size:80rem;margin-inline:auto}}
nav{{display:flex;gap:.35rem;margin-bottom:1.5rem;padding-bottom:.9rem;
  border-bottom:1px solid var(--line)}}
nav a{{padding:.28rem .85rem;border-radius:999rem;font-size:.9rem;text-decoration:none;
  color:var(--muted);border:1px solid transparent}}
nav a:hover{{color:var(--link);border-color:var(--line)}}
nav a[aria-current]{{background:var(--card);border-color:var(--line);color:var(--text);font-weight:600}}
h1{{font-size:clamp(1.5rem,1.1rem + 1.6vw,2.1rem);line-height:1.25;text-wrap:balance;margin:0 0 .35rem}}
.meta{{color:var(--muted);font-size:.9rem;display:flex;flex-wrap:wrap;gap:.4rem 1.1rem;margin-bottom:1rem}}
.banner{{display:block;padding:.7rem 1rem;margin-bottom:1.25rem;border-radius:.6rem;
  border:1px solid var(--line);background:var(--card);font-size:.92rem;text-decoration:none;
  color:var(--text)}}
.banner:hover{{border-color:var(--link)}}
.banner b{{color:var(--link)}}
form{{display:flex;flex-wrap:wrap;gap:.6rem;align-items:end;margin-block:1rem 1.5rem;
  padding:1rem 1.1rem;background:var(--card);border:1px solid var(--line);border-radius:.75rem}}
label{{display:flex;flex-direction:column;gap:.25rem;font-size:.85rem;color:var(--muted)}}
input,select{{font:inherit;padding:.4rem .6rem;border:1px solid var(--line);border-radius:.45rem;
  background:var(--bg);color:var(--text);min-inline-size:9rem}}
button{{font:inherit;font-weight:600;padding:.45rem 1.1rem;border:1px solid var(--line);
  border-radius:.45rem;background:var(--card);color:var(--text);cursor:pointer}}
button:hover{{border-color:var(--link);color:var(--link)}}
:focus-visible{{outline:3px solid var(--link);outline-offset:2px}}
.wrap{{overflow:auto;max-inline-size:100%;max-block-size:min(34rem,78vh);
  container-type:inline-size;border:1px solid var(--line);border-radius:.75rem;
  background:var(--card);scrollbar-gutter:stable}}
table{{border-collapse:separate;border-spacing:0;inline-size:100%}}
th,td{{padding:.6rem .8rem;border-block-end:1px solid var(--line);text-align:start;
  vertical-align:top;overflow-wrap:anywhere}}
thead th{{position:sticky;inset-block-start:0;z-index:2;background:var(--card);
  font-size:.85rem;color:var(--muted);text-wrap:balance}}
tbody tr:hover{{background:rgba(127,127,127,.08)}}
a{{color:var(--link);text-underline-offset:.2em}}
.empty{{padding:2rem;text-align:center;color:var(--muted)}}
@container (width < 42rem){{
  table,tbody,tr,td{{display:block}}
  thead{{display:none}}
  tbody tr{{border:1px solid var(--line);border-radius:.6rem;margin-block-end:.75rem;overflow:hidden}}
  td{{display:grid;grid-template-columns:minmax(4.5rem,7rem) minmax(0,1fr);gap:.5rem;padding:.45rem .7rem}}
  td::before{{font-weight:700;color:var(--muted)}}
  td:nth-child(1)::before{{content:"标题"}}
  td:nth-child(2)::before{{content:"分类"}}
  td:nth-child(3)::before{{content:"剩余"}}
  td:nth-child(4)::before{{content:"截止"}}
  td:nth-child(5)::before{{content:"来源"}}
}}
</style>
</head>
<body>
<nav><a href="/" aria-current="page">清单</a><a href="/report">整理</a><a href="/daily">每日</a></nav>
<h1>羊毛清单</h1>
<div class="meta">
  <span>共 <b>{total}</b> 条</span>
  <span>最后更新 {last_seen}</span>
  <span>当前筛出 <b>{filtered}</b> 条</span>
</div>
<a class="banner" href="/daily">每日羊毛（带标注功能）→</a>
<form method="get" action="/">
  <label>关键词<input type="search" name="q" value="{q}" placeholder="标题或网址"></label>
  <label>分类<select name="cat">{cat_options}</select></label>
  <label>状态<select name="status">{status_options}</select></label>
  <button type="submit">筛选</button>
  <a href="/" style="align-self:center;font-size:.9rem">清空</a>
</form>
{body}
</body>
</html>"""


def esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def options(values, selected):
    out = ['<option value="">全部</option>']
    for v in values:
        sel = " selected" if selected == v else ""
        out.append(f'<option value="{esc(v)}"{sel}>{esc(v)}</option>')
    return "".join(out)


@app.get("/", response_class=HTMLResponse)
def page(cat: str | None = None, status: str | None = None, q: str | None = None):
    rows = fetch(cat, status, q)
    total, last = counts()

    with connect() as c:
        with c.cursor() as cur:
            cur.execute("SELECT DISTINCT cat FROM items WHERE cat IS NOT NULL ORDER BY 1")
            cats = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT DISTINCT status FROM items WHERE status IS NOT NULL ORDER BY 1")
            sts = [r[0] for r in cur.fetchall()]

    if rows:
        trs = []
        for r in rows:
            d = r["days"]
            trs.append(
                "<tr>"
                f'<td><a href="{esc(r["url"])}" target="_blank" rel="noopener noreferrer">{esc(r["title"])}</a></td>'
                f'<td>{esc(r["cat"])}</td>'
                f'<td>{esc(str(d) + " 天") if d is not None else "—"}</td>'
                f'<td>{esc(r["end_date"])}</td>'
                f'<td>{esc(r["source"])}</td>'
                "</tr>"
            )
        body = ('<div class="wrap" tabindex="0" role="region" aria-label="羊毛清单"><table>'
                '<thead><tr><th scope="col">标题</th><th scope="col">分类</th>'
                '<th scope="col">剩余</th><th scope="col">截止</th>'
                '<th scope="col">来源</th></tr></thead><tbody>'
                + "".join(trs) + "</tbody></table></div>")
    else:
        body = '<div class="empty">还没有数据。等采集脚本推一次就有了。</div>'

    return PAGE.format(
        total=total,
        last_seen=esc(last),
        filtered=len(rows),
        q=esc(q or ""),
        cat_options=options(cats, cat),
        status_options=options(sts, status),
        body=body,
    )


# ─────────────────────────── 整理报告页 ───────────────────────────

REPORT = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="robots" content="noindex">
<title>羊毛清单整理 · 26-11-16</title>
<style>
:root{
  color-scheme: dark light;
  --bg-l:#f7f9fc; --bg-d:#15181e;
  --text-l:#1b2436; --text-d:#eef2f9;
  --muted-l:#5c6677; --muted-d:#a3aec1;
  --line-l:#dde3ee; --line-d:#2f3644;
  --card-l:#ffffff; --card-d:#1d222b;
  --soft-l:#eef2f9; --soft-d:#232a35;
  --link-l:#1456bd; --link-d:#8bbcff;
  --ok-l:#11693a; --ok-d:#74dda0;
  --warn-l:#8a5300; --warn-d:#ffc44d;
  --bad-l:#a52a1e; --bad-d:#ff9585;
  --bg:var(--bg-l); --text:var(--text-l); --muted:var(--muted-l);
  --line:var(--line-l); --card:var(--card-l); --soft:var(--soft-l);
  --link:var(--link-l); --ok:var(--ok-l); --warn:var(--warn-l); --bad:var(--bad-l);
}
@media (prefers-color-scheme: dark){
  :root{ --bg:var(--bg-d); --text:var(--text-d); --muted:var(--muted-d);
    --line:var(--line-d); --card:var(--card-d); --soft:var(--soft-d);
    --link:var(--link-d); --ok:var(--ok-d); --warn:var(--warn-d); --bad:var(--bad-d); }
}
@supports (color: light-dark(white, black)){
  :root{
    --bg:light-dark(var(--bg-l), var(--bg-d));
    --text:light-dark(var(--text-l), var(--text-d));
    --muted:light-dark(var(--muted-l), var(--muted-d));
    --line:light-dark(var(--line-l), var(--line-d));
    --card:light-dark(var(--card-l), var(--card-d));
    --soft:light-dark(var(--soft-l), var(--soft-d));
    --link:light-dark(var(--link-l), var(--link-d));
    --ok:light-dark(var(--ok-l), var(--ok-d));
    --warn:light-dark(var(--warn-l), var(--warn-d));
    --bad:light-dark(var(--bad-l), var(--bad-d));
  }
}
*{box-sizing:border-box}
body{
  margin:0; padding:1.5rem 1.15rem 5rem; background:var(--bg); color:var(--text);
  font:1.02rem/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  max-inline-size:64rem; margin-inline:auto;
}
nav{display:flex;gap:.35rem;margin-bottom:1.75rem;padding-bottom:.9rem;border-bottom:1px solid var(--line)}
nav a{padding:.28rem .85rem;border-radius:999rem;font-size:.9rem;text-decoration:none;
  color:var(--muted);border:1px solid transparent}
nav a:hover{color:var(--link);border-color:var(--line)}
nav a[aria-current]{background:var(--card);border-color:var(--line);color:var(--text);font-weight:600}

header{margin-bottom:2rem}
h1{font-size:clamp(1.6rem,1.2rem + 2vw,2.35rem);line-height:1.22;text-wrap:balance;
  margin:0 0 .6rem;letter-spacing:-.01em}
.lede{color:var(--muted);font-size:.95rem;margin:0}
.lede code{font-size:.88em}

h2{font-size:clamp(1.2rem,1rem + 1vw,1.5rem);line-height:1.3;text-wrap:balance;
  margin:2.6rem 0 .9rem;padding-bottom:.45rem;border-bottom:2px solid var(--line)}
h3{font-size:1.06rem;line-height:1.4;margin:1.8rem 0 .6rem;text-wrap:balance}
p{margin:0 0 .85rem;text-wrap:pretty}
ul,ol{margin:0 0 1rem;padding-inline-start:1.35rem}
li{margin-block-end:.4rem;text-wrap:pretty}
a{color:var(--link);text-underline-offset:.18em}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
  background:var(--soft);padding:.08em .36em;border-radius:.28rem;overflow-wrap:anywhere}

.callout{
  padding:1rem 1.15rem;margin:0 0 1rem;border-radius:.7rem;
  background:var(--card);border:1px solid var(--line);border-inline-start-width:4px;
}
.callout.bad{border-inline-start-color:var(--bad)}
.callout.warn{border-inline-start-color:var(--warn)}
.callout.ok{border-inline-start-color:var(--ok)}
.callout h3{margin:0 0 .5rem;font-size:1rem}
.callout p:last-child{margin-bottom:0}
.tagline{display:inline-block;font-size:.78rem;font-weight:700;padding:.05rem .5rem;
  border-radius:999rem;border:1px solid currentColor;margin-inline-end:.4rem}
.t-bad{color:var(--bad)} .t-warn{color:var(--warn)} .t-ok{color:var(--ok)}

.tablewrap{overflow:auto;max-inline-size:100%;border:1px solid var(--line);border-radius:.7rem;
  background:var(--card);container-type:inline-size;margin-block:.4rem 1.1rem}
table{border-collapse:separate;border-spacing:0;inline-size:100%}
caption{caption-side:top;text-align:start;font-size:.85rem;color:var(--muted);padding:.6rem .85rem}
th,td{padding:.6rem .8rem;border-block-end:1px solid var(--line);text-align:start;
  vertical-align:top;overflow-wrap:anywhere}
thead th{background:var(--soft);font-size:.85rem;color:var(--muted);text-wrap:balance}
tbody th{font-weight:650}
tbody tr:last-child th,tbody tr:last-child td{border-block-end:none}
tbody tr:hover{background:rgba(127,127,127,.06)}

details{background:var(--card);border:1px solid var(--line);border-radius:.7rem;
  margin-block:.7rem 1.1rem;overflow:hidden}
summary{cursor:pointer;padding:.8rem 1rem;font-weight:650;list-style:none;
  display:flex;align-items:center;gap:.6rem;text-wrap:balance}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";color:var(--muted);transition:transform .15s ease}
details[open] summary::before{transform:rotate(90deg);color:var(--link)}
details[open] summary{border-block-end:1px solid var(--line)}
summary:focus-visible{outline:3px solid var(--link);outline-offset:-3px}
.dbody{padding:.9rem 1rem 1.1rem}
.dbody p:last-child,.dbody ul:last-child{margin-bottom:0}

footer{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--line);
  color:var(--muted);font-size:.88rem;line-height:1.8}
:focus-visible{outline:3px solid var(--link);outline-offset:2px}

@container (width < 34rem){
  table,tbody,tr,th,td{display:block}
  thead{display:none}
  tbody tr{border:1px solid var(--line);border-radius:.55rem;margin-block-end:.7rem;overflow:hidden}
  tbody th,tbody td{padding:.5rem .8rem}
  tbody th{background:var(--soft);font-size:.95rem}
}
@media (prefers-reduced-motion: reduce){ summary::before{transition:none} }
</style>
</head>
<body>

<nav><a href="/">清单</a><a href="/report" aria-current="page">整理</a><a href="/daily">每日</a></nav>

<header>
  <h1>羊毛清单整理 · 26-11-16</h1>
  <p class="lede">
    数据来自本页同站的 <code>/api/items</code>，共 139 条，源站最后更新 2026-11-15 17:33。
    下面按用途分了类，剔掉两条脏数据，并把「哪些已经过期」按<b>今天的实际日期</b>重算了一遍。
  </p>
</header>

<h2>一、数据本身的两个问题</h2>

<div class="callout bad">
  <h3><span class="tagline t-bad">问题 1</span>剩余天数没跟着日期走</h3>
  <p>
    源站的 <code>last_seen</code> 停在 11-15 17:33，而 <code>end_date</code> 大量落在 11-08 ~ 11-12。
    按今天 11-16 算：<b>139 条里 85 条已过截止日，其中 71 条状态还标着 <code>active</code></b>。
  </p>
  <p>也就是说，清单页那些「3 天 / 5 天」的绿色提示，现在大半不准了。</p>
</div>

<div class="callout warn">
  <h3><span class="tagline t-warn">问题 2</span>两条脏数据混进了分类</h3>
  <p>
    <code>ai</code> 和 <code>open-source</code> 里各混进一条小黑盒论坛帖，
    标题是一整段正文（<code>玩家25206450 … 十八款恐怖游戏…</code>），不是羊毛条目。
    下面已剔除。
  </p>
</div>

<h2>二、值得看的部分</h2>

<p>
  筛选口径是「<b>能提高效率的东西</b>——好用的软件、实用方法、真羊毛」。
  游戏限免（57 条）和中转站/机场广告（15 条）兴趣不大，放到最后折叠起来，一条没删。
</p>

<h3>1）开源 / 好用软件（21 条，最有价值）</h3>

<div class="tablewrap">
<table>
<caption>按「能不能直接用在你的活儿上」排的，不按热度。</caption>
<thead>
<tr><th scope="col">工具</th><th scope="col">干什么</th><th scope="col">对你的用处</th></tr>
</thead>
<tbody>
<tr><th scope="row">安卓去广告神器</th><td>开源、免 ROOT，一键关国产系统内置广告</td><td>直接能用</td></tr>
<tr><th scope="row">MarkText</th><td>开源轻量 Markdown 编辑器，Typora 平替</td><td>免费好用</td></tr>
<tr><th scope="row">Konode</th><td>跨 Chrome / Edge / Firefox 同步书签、标签、历史</td><td>多浏览器同步</td></tr>
<tr><th scope="row">Tailcat</th><td>Tailscale 开源，两台设备临时直连的内网穿透</td><td>传文件、临时连</td></tr>
<tr><th scope="row">Scrcpy 5</th><td>电脑显示并控制安卓手机，免 Root</td><td>闲置手机利用</td></tr>
<tr><th scope="row">MicYou for iOS</th><td>老 iPhone 变电脑麦克风</td><td>闲置 iPhone 7 有新用途</td></tr>
<tr><th scope="row">TinyPlay</th><td>闲置电脑变客厅电视盒子</td><td>旧办公电脑那条线</td></tr>
<tr><th scope="row">FluentCleaner</th><td>开源清理工具，CCleaner 替代</td><td>系统维护</td></tr>
<tr><th scope="row">FSearch</th><td>开源全盘文件搜索</td><td>效率</td></tr>
<tr><th scope="row">拼音注音小工具</th><td>单网页纯离线，33.7 万词典</td><td>备用</td></tr>
<tr><th scope="row">ArtCraft</th><td>开源版 Adobe 全家桶，复刻 PS / AE / PR / AI</td><td>出视频可能用得上</td></tr>
<tr><th scope="row">ylih 耳机里程表</th><td>记录蓝牙耳机续航衰减</td><td>你关心耳机</td></tr>
<tr><th scope="row">reinstall</th><td>操作系统自己重装自己</td><td>折腾向</td></tr>
<tr><th scope="row">Steamac</th><td>Mac 装 SteamOS 玩 Windows 游戏</td><td>玩票</td></tr>
<tr><th scope="row">Search 浏览器</th><td>仅 6MB 的极简 Mac 浏览器</td><td>备用</td></tr>
<tr><th scope="row">VMware Workstation Pro</th><td>免费虚拟机专业版</td><td>备用</td></tr>
<tr><th scope="row">Trae / Copilot Free</th><td>免费 AI 编程 IDE 与扩展</td><td>不写代码，略过</td></tr>
</tbody>
</table>
</div>

<p><small>另剔掉 2 条：小黑盒论坛帖（标题是正文）、Neovim 收 10 BTC 捐赠（资讯不是工具）。</small></p>

<h3>2）AI 免费额度（46 条）</h3>

<div class="tablewrap">
<table>
<caption>只列「无截止日或长周期」的，能接进 DSH 的排在前面。</caption>
<thead>
<tr><th scope="col">项</th><th scope="col">说明</th></tr>
</thead>
<tbody>
<tr><th scope="row">智谱 GLM-4-Flash 免费 API</th><td>永久免费，可接</td></tr>
<tr><th scope="row">Groq 免费 API</th><td>Llama 3.1 超快推理</td></tr>
<tr><th scope="row">Google Gemini 免费 API</th><td>1.5 Flash，可接</td></tr>
<tr><th scope="row">DeepSeek 新用户</th><td>送 500 万 tokens</td></tr>
<tr><th scope="row">Kimi / MiniMax / 讯飞 / 千帆 / 混元 / 360智脑 / 百炼</th><td>各家新用户额度，多数要实名</td></tr>
<tr><th scope="row">ChatGPT / Gemini / Coze / WorkBuddy 免费版</th><td>长期免费档</td></tr>
</tbody>
</table>
</div>

<details>
<summary>有时限的那批（按 11-16 算，多数已过期）</summary>
<div class="dbody">
<ul>
  <li>腾讯云 / 阿里云 / 华为云一批「24 天」的，源站写到 12-01——那是 11-15 算的，实际要重算。</li>
  <li>
    复旦「学术版 Codex」送 1 万积分、WorkBuddy 白嫖 DeepSeek、WPS / B站 / iCloud 年卡打折，
    都是 11-09 ~ 11-14 截止的双 11 尾巴，<b>现在多半已结束</b>。
  </li>
  <li>已明确 <code>ended</code> 的 4 条：ZCode 5 亿 Token、CloudCone 充值赠送、VideoProc 限免、OpenCode 免费 Flash。</li>
  <li>AutoClaw / Qoder / 复旦 Codex 这类「客户端内额度」用不到，同类的也一并标了。</li>
</ul>
</div>
</details>

<h3>3）游戏限免（57 条）</h3>

<details>
<summary>兴趣不大，全压这里，一条没删</summary>
<div class="dbody">
<p>
  itch.io 约 25 条、Epic 约 20 条、Steam / GOG / Indiegala 加 Reddit FreeGameFindings 约 12 条。
</p>
<p>
  <b>共同问题</b>：截止日集中在 11-08 ~ 11-12，按今天 11-16 <b>全部已过期</b>，状态还标着 active。
</p>
<p>唯一还有价值的：<b>Epic 免费游戏「浮游世界」</b>——Epic 每周一轮，值得保留每周看一眼。</p>
</div>
</details>

<h3>4）中转站 / 机场 / V2EX 推广（15 条）</h3>

<details>
<summary>历来不推，15 条里 10 条已结束</summary>
<div class="dbody">
<p>
  Zooproxy、Midalo 米搭、我享云、HyperAPI、grok 半价成品号、LabEx 双十一特惠等。
  按「V2EX 推广版块全是机场 / 代充广告」的口径，整类不推。
</p>
</div>
</details>

<h2>三、给这个网页的三条建议</h2>

<ol>
  <li>
    <b><code>status</code> 按 <code>end_date</code> 重算。</b>
    现在 71 条过期仍标 active，绿字误导。每天跑一次
    <code>UPDATE items SET status='ended' WHERE end_date &lt; today</code> 就能修。
  </li>
  <li>
    <b>过滤脏数据。</b>
    入库前按「标题含换行或超过 80 字」拦掉，论坛帖就不会混进列表。
  </li>
  <li>
    <b><code>days</code> 改成按当天算。</b>
    别存写死的「5 天」，只存 <code>end_date</code>，页面按今天算剩余，才不会越放越假。
  </li>
</ol>

<h2>四、数据口径</h2>

<div class="tablewrap">
<table>
<caption>下面每个数都来自源站 API 实测，不是估的。</caption>
<tbody>
<tr><th scope="row">源站</th><td><code>/api/items</code></td></tr>
<tr><th scope="row">取回时间</th><td>2026-11-16 01:55</td></tr>
<tr><th scope="row">源站 last_seen</th><td>2026-11-15 17:33</td></tr>
<tr><th scope="row">总条数</th><td>139</td></tr>
<tr><th scope="row">分类</th><td>games 57 / ai 46 / open-source 21 / drive 15</td></tr>
<tr><th scope="row">状态（源站标）</th><td>active 125 / ended 14</td></tr>
<tr><th scope="row">按实际日期判定已过期</th><td><b>85 条</b>，其中 71 条源站仍标 active</td></tr>
</tbody>
</table>
</div>

<footer>
  事实与推测分开：上面「139 条 / 分类 / 状态 / 日期」全部来自源站接口实测；
  「哪些对你有用」是判断，按历次反馈来的，还在继续纠正。
  <br>
  页面由 <code>main.py</code> 里的静态模板渲染，改内容直接改那段 HTML。
</footer>

</body>
</html>"""


@app.get("/report", response_class=HTMLResponse)
def report():
    return REPORT
