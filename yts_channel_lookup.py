#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS · 频道链接自动识别（Phase 2「新增网红」用）

输入任意形态的 YouTube 频道标识（主页链接 / @handle / UC 频道ID），
用官方 Data API 反查，返回：最新粉丝数、频道昵称、真实 UC 频道ID，
并尽力从频道简介里正则扫出一个联系邮箱（YouTube 官方不公开邮箱，
扫不到就返回空，交回人工填写）。

依赖 yts_yt_stats（已在跑"补频道粉丝数"功能），共用同一把
YOUTUBE_API_KEY（Streamlit Secrets / 环境变量），无需另配。
所有网络/解析异常一律降级为 ok=False，绝不抛出打断弹窗。
"""
import re

import yts_yt_stats as YT


# 简介里常见形态：xxx@gmail.com / business@品牌.kr 等
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 明显不是真联系邮箱的噪声后缀，命中就跳过
_EMAIL_JUNK = ("example.com", "sentry.io", "youtube.com", "google.com",
               "schema.org", "w3.org")


def _resolve_channel_id(raw: str) -> str:
    """把链接/handle/ID 归一成真实 UC 频道ID；拿不到返回 ''。"""
    s = (raw or "").strip()
    if not s:
        return ""
    # 1) 已是 UC id（或链接里直接含 UC…）
    m = re.search(r"(UC[\w\-]{20,})", s)
    if m:
        return m.group(1)
    # 2) 取 handle / @别名 / 裸 handle
    ident = YT.handle_from_url(s) or s.lstrip("@").strip()
    # 去掉可能残留的路径/查询串
    ident = re.split(r"[/?#]", ident)[0].strip()
    if not ident or not YT.get_key():
        return ""
    # 3) forHandle 反查（@别名/自定义频道名均可）
    try:
        data = YT._get("channels", {"part": "id", "forHandle": ident})
    except Exception:
        return ""
    items = (data or {}).get("items") or []
    return (items[0].get("id") if items else "") or ""


def _scan_email(description: str) -> str:
    for line in (description or "").splitlines():
        for m in _EMAIL_RE.finditer(line):
            e = m.group(0).strip().rstrip(".,;)]")
            if any(j in e.lower() for j in _EMAIL_JUNK):
                continue
            return e
    return ""


def lookup(raw: str) -> dict:
    """返回 {ok, channel_id, name, subscribers, email}。
    无 key / 解析失败 / 查不到 → {ok: False}。"""
    out = {"ok": False, "channel_id": "", "name": "",
           "subscribers": 0, "email": ""}
    cid = _resolve_channel_id(raw)
    if not cid or not YT.get_key():
        return out
    try:
        data = YT._get("channels",
                       {"part": "snippet,statistics", "id": cid})
        items = (data or {}).get("items") or []
        if not items:
            return out
        it = items[0]
        sn = it.get("snippet") or {}
        st = it.get("statistics") or {}
        out.update({
            "ok": True,
            "channel_id": it.get("id") or cid,
            "name": (sn.get("title") or "").strip(),
            "subscribers": int(st.get("subscriberCount") or 0),
            "email": _scan_email(sn.get("description") or ""),
        })
        return out
    except Exception:
        return out
