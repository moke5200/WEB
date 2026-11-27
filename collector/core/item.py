#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标准数据单元：所有源统一产出 Item，下游只认这个结构。"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import hashlib
import re


@dataclass
class Item:
    source_id: str                 # 源编号，如 a01
    title: str                     # 标题（中文；英文源必须已翻译）
    url: str                       # 主链接
    summary: str = ""              # 摘要（中文）
    published: str = ""            # 发布时间 YYYY-MM-DD HH:MM（北京时间）
    collected: str = ""            # 收集时间 YYYY-MM-DD HH:MM
    author: str = ""               # 发帖人
    tags: List[str] = field(default_factory=list)
    media: List[Dict[str, str]] = field(default_factory=list)   # [{type,url}]
    extra: Dict[str, Any] = field(default_factory=dict)         # 源私有字段（盘链接等）
    raw_lang: str = "zh"           # 原文语言，en 表示需要翻译

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # ---- 去重指纹 ----
    def url_fingerprint(self) -> str:
        """URL 规范化后的指纹（去掉 utm/ref 等参数）。"""
        u = (self.url or "").strip()
        u = re.sub(r'[?&](utm_[^=&]*|ref|from|spm)=[^&]*', '', u)
        u = u.rstrip('?&/')
        return u.lower()

    def content_fingerprint(self) -> str:
        """标题+链接组合指纹，用于跨源判重。"""
        norm = re.sub(r'[\s\-—_【】\[\]（）()《》「」·.,，。!！?？:：;；]', '', (self.title or '').lower())
        h = hashlib.md5((norm + '|' + self.url_fingerprint()).encode('utf-8')).hexdigest()
        return h

    def key(self) -> str:
        """本源的唯一键：优先用 extra.dedup_key（如网盘链接 ID），否则 URL 指纹。"""
        k = (self.extra or {}).get("dedup_key")
        return k if k else self.url_fingerprint()