#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS - 团队成员名单（唯一数据源 = 挖掘站 Supabase members 表）

活动/挖掘模块下拉、流程导入负责人匹配共用这份名单，避免两边名字不一致出错。
网络不可用时返回空列表（或旧缓存），调用方自行兜底。
"""
import difflib
import time

import requests

# 与挖掘站 kol-finder 同一项目、同一团队公共 key
SUPABASE_URL = "https://webjrwzorxxlqrcrrnro.supabase.co"
SUPABASE_KEY = "sb_publishable_eUDicGLoUiNhPO04S6iz8g_UX_SkSCH"

_cache = {"t": 0.0, "names": []}
TTL = 300  # 秒


def get_members(force: bool = False) -> list:
    """拉取挖掘站成员名单；失败时退回旧缓存，再退 []"""
    now = time.time()
    if not force and _cache["names"] and now - _cache["t"] < TTL:
        return _cache["names"]
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/members",
                         params={"select": "name"},
                         headers={"apikey": SUPABASE_KEY,
                                  "Authorization": f"Bearer {SUPABASE_KEY}"},
                         timeout=8)
        r.raise_for_status()
        names = [str(x.get("name")).strip() for x in r.json() if x.get("name")]
        if names:
            _cache["t"], _cache["names"] = now, names
            return names
    except Exception:
        pass
    return _cache["names"]


def match_name(raw, roster) -> str:
    """模糊匹配名单：精确 → 包含(≥2字) → 相似度≥0.8。返回规范名，匹配不到返回 ''"""
    s = str(raw or "").strip()
    if not s or not roster:
        return ""
    for n in roster:
        if s == n:
            return n
    cands = []
    for n in roster:
        if len(s) >= 2 and (s in n or n in s):
            cands.append((1.0 - abs(len(n) - len(s)) * 0.01, n))
        else:
            ratio = difflib.SequenceMatcher(None, s, n).ratio()
            if ratio >= 0.8:
                cands.append((ratio, n))
    if not cands:
        return ""
    cands.sort(key=lambda x: -x[0])
    return cands[0][1]
