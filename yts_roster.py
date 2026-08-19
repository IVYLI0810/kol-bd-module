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


_emailed_cache = {"t": 0.0, "rows": []}


def fetch_emailed_channels(force: bool = False) -> list:
    """拉挖掘站里状态=已发邮件的网红（轻量字段），供 YTS 自动同步"""
    now = time.time()
    if not force and _emailed_cache["rows"] and now - _emailed_cache["t"] < TTL:
        return _emailed_cache["rows"]
    rows, off = [], 0
    try:
        while True:
            r = requests.get(f"{SUPABASE_URL}/rest/v1/influencers",
                             params={"select": "channel_id,channel_name,channel_url,"
                                               "category,subscribers,discovered_by",
                                     "status": "eq.已发邮件",
                                     "offset": off, "limit": 200},
                             headers={"apikey": SUPABASE_KEY,
                                      "Authorization": f"Bearer {SUPABASE_KEY}"},
                             timeout=15)
            r.raise_for_status()
            b = r.json()
            rows += b
            off += len(b)
            if len(b) < 200:
                break
        if rows:
            _emailed_cache["t"], _emailed_cache["rows"] = now, rows
            return rows
    except Exception:
        pass
    return _emailed_cache["rows"]


_allch_cache = {"t": 0.0, "rows": []}


def fetch_all_channels(force: bool = False) -> list:
    """拉挖掘站全部网红的基础信息（粉丝量/垂类等），供 YTS 同步"""
    now = time.time()
    if not force and _allch_cache["rows"] and now - _allch_cache["t"] < TTL:
        return _allch_cache["rows"]
    rows, off = [], 0
    try:
        while True:
            r = requests.get(f"{SUPABASE_URL}/rest/v1/influencers",
                             params={"select": "channel_id,channel_name,channel_url,"
                                               "category,subscribers",
                                     "offset": off, "limit": 500},
                             headers={"apikey": SUPABASE_KEY,
                                      "Authorization": f"Bearer {SUPABASE_KEY}"},
                             timeout=15)
            r.raise_for_status()
            b = r.json()
            rows += b
            off += len(b)
            if len(b) < 500:
                break
        if rows:
            _allch_cache["t"], _allch_cache["rows"] = now, rows
            return rows
    except Exception:
        pass
    return _allch_cache["rows"]


_status_cache = {"t": 0.0, "v": None}


def fetch_statuses(force: bool = False) -> dict:
    """挖掘站全部网红 channel_id -> status 映射；失败时退回旧缓存"""
    now = time.time()
    if not force and _status_cache["v"] is not None and now - _status_cache["t"] < TTL:
        return _status_cache["v"]
    out, off = {}, 0
    try:
        while True:
            r = requests.get(f"{SUPABASE_URL}/rest/v1/influencers",
                             params={"select": "channel_id,status",
                                     "offset": off, "limit": 500},
                             headers={"apikey": SUPABASE_KEY,
                                      "Authorization": f"Bearer {SUPABASE_KEY}"},
                             timeout=15)
            r.raise_for_status()
            b = r.json()
            for x in b:
                out[x.get("channel_id")] = x.get("status") or ""
            off += len(b)
            if len(b) < 500:
                break
        if out:
            _status_cache["t"], _status_cache["v"] = now, out
            return out
    except Exception:
        pass
    return _status_cache["v"] or out


def mark_introduced(channel_id: str) -> bool:
    """回写挖掘站：把指定网红标记为「已引入」"""
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/influencers",
                       params={"channel_id": f"eq.{channel_id}"},
                       json={"status": "已引入"},
                       headers={"apikey": SUPABASE_KEY,
                                "Authorization": f"Bearer {SUPABASE_KEY}",
                                "Content-Type": "application/json",
                                "Prefer": "return=minimal"},
                       timeout=15)
    r.raise_for_status()
    if _status_cache["v"] is not None:
        _status_cache["v"][channel_id] = "已引入"
    return True


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
