#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""翻译层：英文源统一过这里，输出中文（野哥要求：别给我看英文）。

后端优先级：
  1) 配了 TRANSLATE_API（OpenAI 兼容）→ 用模型翻
  2) 否则用 Google 翻译免费端点（不要 key）
  3) 都失败 → 保留原文并把 lang 标成 en-failed，输出层会标注「未翻译」
"""
import os
import json
import re
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
API_BASE = os.environ.get("TRANSLATE_API", "").rstrip("/")
API_KEY = os.environ.get("TRANSLATE_KEY", "")
API_MODEL = os.environ.get("TRANSLATE_MODEL", "gpt-4o-mini")

_CACHE = {}


def _has_cjk(s):
    return bool(re.search(r'[\u4e00-\u9fff]', s or ''))


def _google(text, target="zh-CN"):
    """Google 翻译免费端点（无需 key）。"""
    q = urllib.parse.quote(text[:4500])
    url = ("https://translate.googleapis.com/translate_a/single"
           "?client=gtx&sl=auto&tl=%s&dt=t&q=%s" % (target, q))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        parts = [seg[0] for seg in (data[0] or []) if seg and seg[0]]
        return "".join(parts).strip()
    except Exception:
        return ""


def _llm(text, target="zh-CN"):
    """OpenAI 兼容接口翻译。"""
    if not (API_BASE and API_KEY):
        return ""
    body = {
        "model": API_MODEL,
        "messages": [
            {"role": "system", "content": "你是翻译。把用户给的英文翻成简洁自然的中文，"
                                          "保留专有名词原文。只输出译文，不要解释。"},
            {"role": "user", "content": text[:6000]},
        ],
        "temperature": 0,
    }
    req = urllib.request.Request(
        API_BASE + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return (d["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


def to_zh(text):
    """把一段英文变中文。已经是中文的原样返回。"""
    if not text or not text.strip():
        return ""
    if _has_cjk(text) and not re.search(r'[A-Za-z]{4,}', text[:200]):
        return text
    key = text[:200]
    if key in _CACHE:
        return _CACHE[key]
    out = _llm(text) or _google(text)
    if out:
        _CACHE[key] = out
        time.sleep(0.3)
    return out


def translate_item(it):
    """就地翻译 Item 的 title/summary，返回是否翻译成功。"""
    if it.raw_lang != "en":
        return True
    ok = True
    new_title = to_zh(it.title)
    if new_title:
        it.title = new_title
    else:
        ok = False
    if it.summary:
        new_sum = to_zh(it.summary)
        if new_sum:
            it.summary = new_sum
        else:
            ok = False
    if not ok:
        it.tags.append("未翻译")
    return ok