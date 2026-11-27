#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已抓记录台账（强制持久化，指令铁律 3）。

文件：state/seen_items.json（放公共仓，Actions 每轮 commit & push 回去）
只记四样：平台、帖子ID、去掉追踪参数的标准 URL、首次抓取日期。

为什么单独做一层：
  · 容器一销毁内存就没了，必须落文件
  · 跨日、跨源都要认同一份台账（反斗/小众/异次元/linux.do/NodeSeek 互斥）
  · 台账在「抓详情页之前」就要查——命中直接跳过，省请求（尤其 Jina 额度）

结构：
{
  "version": 1,
  "updated": "2026-11-27 20:30",
  "items": {
    "linux.do:3258633": {
      "platform": "linux.do",
      "post_id": "3258633",
      "url": "https://linux.do/t/topic/3258633",
      "first_seen": "2026-11-27",
      "source": "a01"
    }
  }
}
"""
import datetime
import json
import os
import re
import sys
import urllib.parse

# 允许直接 python core/ledger.py 运行
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import settings   # noqa: E402

KEEP_DAYS = int(os.environ.get("SEEN_KEEP_DAYS", "90"))     # 60~90 天滚动，取上限
VERSION = 1

# 追踪参数：一律从标准 URL 里去掉
TRACKING = re.compile(
    r'^(utm_[a-z]+|spm|ref|ref_src|ref_url|from|from_source|share_source|'
    r'share_medium|share_from|fbclid|gclid|yclid|msclkid|_hsenc|_hsmi|'
    r'guccounter|guce_referrer|guce_referrer_sig|campaign|aff|affiliate)$',
    re.I)


def now_bj(fmt="%Y-%m-%d %H:%M"):
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime(fmt)


def today():
    return now_bj("%Y-%m-%d")


def norm_url(url):
    """去掉追踪参数、统一 host 小写、去掉尾部斜杠。保留业务必需的参数（如 pwd）。"""
    if not url:
        return ""
    u = url.strip()
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        return u.lower()
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if not TRACKING.match(k)]
    path = p.path.rstrip('/') or '/'
    return urllib.parse.urlunsplit((p.scheme.lower() or 'https', p.netloc.lower(),
                                    path, urllib.parse.urlencode(q), ''))


def _platform_of(url):
    try:
        host = urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return "unknown"
    host = host.replace("www.", "")
    return host or "unknown"


def key_for(platform, post_id, url):
    """唯一键：优先 平台+帖子ID，没有 ID 就用标准 URL。"""
    if post_id:
        return "%s:%s" % (platform, post_id)
    return "%s:%s" % (platform, norm_url(url))


class Ledger:
    def __init__(self, path=None):
        self.path = path or settings.LEDGER_FILE
        self.data = {"version": VERSION, "updated": now_bj(), "items": {}}
        self.dirty = False
        self._index = {}          # norm_url -> key，用于 URL 兜底匹配
        self.load()

    # ---------- 读写 ----------
    def load(self):
        if not os.path.exists(self.path):
            return self
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("items"), dict):
                self.data = d
                self.data.setdefault("version", VERSION)
                self.data.setdefault("updated", now_bj())
        except Exception:
            # 台账坏了不能静默当空——留个备份再从空开始
            try:
                os.replace(self.path, self.path + ".broken-" + now_bj("%Y%m%d%H%M%S"))
            except Exception:
                pass
        self._rebuild_index()
        return self

    def _rebuild_index(self):
        self._index = {}
        for k, v in self.data["items"].items():
            u = v.get("url")
            if u:
                self._index.setdefault(norm_url(u), k)

    def save(self):
        if not self.dirty:
            return False
        self.data["version"] = VERSION
        self.data["updated"] = now_bj()
        # 滚动清理
        cutoff = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
                  - datetime.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        before = len(self.data["items"])
        self.data["items"] = {k: v for k, v in self.data["items"].items()
                              if (v.get("first_seen") or "9999-99-99") >= cutoff}
        pruned = before - len(self.data["items"])

        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
        self.dirty = False
        print("    [台账] 写入 %s：%d 条%s"
              % (os.path.basename(self.path), len(self.data["items"]),
                 "（清掉过期 %d 条）" % pruned if pruned else ""), flush=True)
        return True

    # ---------- 查询 / 登记 ----------
    def is_seen(self, platform=None, post_id=None, url=None):
        """查过没有。ID 命中或标准 URL 命中都算。"""
        if post_id:
            plat = platform or _platform_of(url or "")
            if key_for(plat, post_id, url) in self.data["items"]:
                return True
        if url:
            if norm_url(url) in self._index:
                return True
            plat = platform or _platform_of(url)
            if key_for(plat, None, url) in self.data["items"]:
                return True
        return False

    def mark(self, platform, post_id, url, source=""):
        """登记一条。已存在则跳过（保留首次抓取日期）。"""
        k = key_for(platform, post_id, url)
        if k in self.data["items"]:
            return False
        self.data["items"][k] = {
            "platform": platform,
            "post_id": str(post_id or ""),
            "url": norm_url(url),
            "first_seen": today(),
            "source": source,
        }
        if url:
            self._index[norm_url(url)] = k
        self.dirty = True
        return True

    def mark_many(self, items, source="", platform=None):
        """批量登记 Item 列表。"""
        n = 0
        for it in items:
            plat = platform or (it.extra or {}).get("platform") or _platform_of(it.url)
            pid = (it.extra or {}).get("post_id")
            if self.mark(plat, pid, it.url, source):
                n += 1
        return n

    def stats(self):
        return {"total": len(self.data["items"]), "updated": self.data.get("updated", "")}


if __name__ == "__main__":
    import sys
    lg = Ledger()
    print(json.dumps(lg.stats(), ensure_ascii=False, indent=1))
    if len(sys.argv) > 1 and sys.argv[1] == "--prune":
        lg.dirty = True
        lg.save()