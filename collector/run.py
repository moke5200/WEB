#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调度入口：按注册表跑源，统一做去重 → 翻译 → 输出。

用法：
  python run.py --list                列出所有源和开关状态
  python run.py --source a01          只跑一个源
  python run.py --all                 跑所有 enabled 的云端源
  python run.py --source a01 --dry-run  只抓不去重、不写文件（调脚本用）

环境变量：
  OUT_DIR       输出目录（默认 ./out）
  STATE_DIR     状态目录（默认 ./state）
  OUT_001       001.md 的完整路径（不设则写到 OUT_DIR/001.md）
  DEDUP_FILE    去重状态文件（默认 STATE_DIR/dedup.json）
"""
import argparse
import importlib.util
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import translate, output, ledger as ledger_mod, schedule   # noqa: E402
from core.http import JINA_CALLS               # noqa: E402
from config import registry, settings          # noqa: E402

OUT_DIR = settings.OUT_DIR
STATE_DIR = settings.STATE_DIR
OUT_001 = settings.OUT_001

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)


def load_source_class(filename):
    """从 sources/<filename> 里加载 Source 子类。"""
    path = os.path.join(HERE, "sources", filename)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    modname = "src_" + filename.replace(".py", "")
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from sources.base import Source
    for v in vars(mod).values():
        if isinstance(v, type) and issubclass(v, Source) and v is not Source:
            return v
    raise RuntimeError("没在 %s 里找到 Source 子类" % filename)


def run_one(cfg, dry_run=False, lg=None):
    """跑一个源，返回统计字典。源内部异常不影响其他源。"""
    sid = cfg["id"]
    stat = {"id": sid, "name": cfg.get("name", sid), "ok": False,
            "fetched": 0, "new": 0, "dup": 0, "skipped": 0, "failed": []}
    try:
        cls = load_source_class(cfg["file"])
        src = cls()
        # 用注册表的字段覆盖类属性（注册表为准）
        for k in ("name", "category", "freq", "runs_on", "raw_lang", "platform"):
            if cfg.get(k):
                setattr(src, k, cfg[k])
        print("[%s] %s 开始" % (sid, src.name), flush=True)
        items, failed = src.fetch(cfg, seen=lg)
        stat["fetched"] = len(items or [])
        stat["failed"] = failed or []

        if dry_run:
            print("[%s] dry-run：抓到 %d 条，不写文件、不记台账" % (sid, stat["fetched"]), flush=True)
            for it in (items or [])[:5]:
                print("    · %s | %s" % (it.title[:50], it.url), flush=True)
            stat["ok"] = True
            return stat

        # 翻译（英文源）
        for it in items or []:
            try:
                translate.translate_item(it)
            except Exception:
                pass

        # 台账二次兜底（源内可能漏查，这里再挡一遍）
        fresh = []
        for it in items or []:
            plat = (it.extra or {}).get("platform") or src.platform or None
            pid = (it.extra or {}).get("post_id")
            if lg is not None and lg.is_seen(plat, pid, it.url):
                stat["dup"] += 1
                continue
            fresh.append(it)
        stat["new"] = len(fresh)

        # 输出
        if cfg.get("output") == "001.md":
            n = output.prepend_to_default_001(fresh, note="linux.do 云资源")
            print("[%s] 写入 001.md %d 条 → %s" % (sid, n, settings.OUT_001), flush=True)
        # 无论哪种，都留一份 json 供每日页组装
        output.dump_json(os.path.join(settings.DAILY_JSON_DIR, "%s.json" % sid),
                         {"id": sid, "name": src.name,
                          "fetched_at": output._now_bj().strftime("%Y-%m-%d %H:%M"),
                          "items": output.to_daily_json(fresh)})

        # 记台账（铁律 3：每轮必须更新）
        if lg is not None:
            marked = lg.mark_many(fresh, source=sid,
                                  platform=src.platform or None)
            stat["marked"] = marked
        stat["ok"] = True
        print("[%s] 完成：抓 %d / 新 %d / 台账重复 %d"
              % (sid, stat["fetched"], stat["new"], stat["dup"]), flush=True)
    except Exception as e:
        stat["failed"].append("%s: %s" % (type(e).__name__, str(e)[:150]))
        print("[%s] 异常：%s" % (sid, e), flush=True)
        traceback.print_exc()
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--source", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--due", action="store_true", help="只跑到点的源（云端用这个）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--runs-on", default="", help="只跑 cloud 或 local")
    a = ap.parse_args()

    if a.list:
        print("%-5s %-26s %-10s %-8s %-6s %s" % ("ID", "名称", "分类", "频率", "位置", "开关"))
        for s in registry.SOURCES:
            print("%-5s %-26s %-10s %-8s %-6s %s" % (
                s["id"], s["name"], s.get("category", ""), s.get("freq", ""),
                s.get("runs_on", "cloud"), "开" if s.get("enabled") else "关"))
        return

    targets = []
    if a.source:
        cfg = registry.by_id(a.source)
        if not cfg:
            print("没有这个源：%s" % a.source, file=sys.stderr)
            sys.exit(2)
        targets = [cfg]
    elif a.due:
        targets = schedule.due_sources(registry.SOURCES, only_runs_on=a.runs_on or "cloud")
        if not targets:
            print("本轮没有到点的源（各源按自己的 freq 跑）。")
            return
    elif a.all:
        targets = registry.enabled()
        if a.runs_on:
            targets = [s for s in targets if s.get("runs_on", "cloud") == a.runs_on]
    else:
        print("要给 --source <id> / --due / --all", file=sys.stderr)
        sys.exit(2)

    print("=" * 60)
    print("本轮跑 %d 个源：%s" % (len(targets), ", ".join(s["id"] for s in targets)))
    print("=" * 60)

    # 台账：全场只有一份，跑完统一保存（铁律 3）
    lg = ledger_mod.Ledger()
    st0 = lg.stats()
    print("台账 %s：已有 %d 条（更新于 %s）"
          % (os.path.basename(lg.path), st0["total"], st0["updated"]), flush=True)

    stats = []
    for cfg in targets:
        stats.append(run_one(cfg, dry_run=a.dry_run, lg=lg))

    if not a.dry_run:
        lg.save()
        # 记下这轮跑过的源，供下次 --due 判断（只记成功的，失败的下一轮还要补）
        schedule.mark_run([s["id"] for s in stats if s["ok"]])

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    for s in stats:
        flag = "OK " if s["ok"] else "FAIL"
        print("%s %-5s %-24s 抓 %3d 新 %3d 重复 %3d"
              % (flag, s["id"], s["name"], s["fetched"], s["new"], s["dup"]))
        if s["failed"]:
            for f in s["failed"][:3]:
                print("        ! %s" % f)
    print("\nJina 请求数：%d" % JINA_CALLS["count"])
    st1 = lg.stats()
    print("台账：%d 条 → %s" % (st1["total"], lg.path))


if __name__ == "__main__":
    main()