#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置：零依赖，跨平台，路径集中管理。

云端（GitHub Actions）靠环境变量覆盖：
  STATE_DIR   仓库根 state/（台账要 commit 回去，必须在仓里）
  OUT_DIR     仓库根 out/（产物）
  OUT_001     本机跑时写 Google Drive；云端只写 out/，由本机同步
"""
import os

# ---- 仓库根目录（collector 的上级） ----
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # collector/

# ---- 状态与产物 ----
# 台账必须持久化在「仓里」，所以默认放 ROOT/state，Actions 里就是 <repo>/collector/state
# 但指令要求公共仓 state/seen_items.json —— 用 STATE_DIR 覆盖成仓库根 state/
STATE_DIR = os.environ.get("STATE_DIR", os.path.join(ROOT, "state"))
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(ROOT, "out"))

# 已抓记录台账（铁律 3，强制持久化）
LEDGER_FILE = os.environ.get("LEDGER_FILE", os.path.join(STATE_DIR, "seen_items.json"))

# ---- 真实落地路径（Google Drive，本机跑时写；云端不写这个盘） ----
# 一源一文件夹（铁律 5）：Agent 收集\<来源名>\
COLLECT_ROOT = os.environ.get("COLLECT_ROOT", r"E:\Google Drive\Agent 收集")
OUT_001 = os.environ.get("OUT_001",
                         os.path.join(COLLECT_ROOT, "linux.do", "linux.do资源收集-001.md"))

# 每日页原始 json（供 make_daily.py 组装）
DAILY_JSON_DIR = os.path.join(OUT_DIR, "daily_json")

# X 收集相关（给 X 源用，复用现有 _xlib.py 的路径）
X_SAVE_POS = os.path.join(COLLECT_ROOT, "X", "X 有用帖子整理")
X_SAVE_NEG = os.path.join(COLLECT_ROOT, "X", "X 排毒帖子整理")
X_DEDUP_FILE = os.path.join(COLLECT_ROOT, "X", "DSH用 已保存帖子ID.md")
X_REF_INDEX_FILE = os.path.join(COLLECT_ROOT, "X", "引用索引.json")
X_CITE_COUNT_FILE = os.path.join(COLLECT_ROOT, "X", "被引用计数.md")
X_INSTR = r"E:\Google Drive\Agent 规则\07-定时任务\00-DSH 取X帖子指令.md"

# Cookie / 登录态
SRC = r"F:\Program Files\DS Harness Space\测试薅羊毛 26-11-07"
COOKIE_POS = os.environ.get("X_COOKIE_POS", os.path.join(SRC, "X cookie.txt"))
COOKIE_NEG = os.environ.get("X_COOKIE_NEG", os.path.join(SRC, "X 小号 cookie.txt"))
RUIKE_COOKIE = os.environ.get("RUIKE_COOKIE", "")

# 是否写 Google Drive（云端关掉）
WRITE_LOCAL_DISK = os.environ.get("WRITE_LOCAL_DISK", "1") == "1"

# 云端（Actions）环境检测
IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(DAILY_JSON_DIR, exist_ok=True)

# 云端（Linux）没有 E 盘，本机路径只在 WRITE_LOCAL_DISK 时才用
if IS_CI:
    WRITE_LOCAL_DISK = False


def source_dir(name):
    """一源一文件夹：Agent 收集 / <来源名> /"""
    return os.path.join(COLLECT_ROOT, name)