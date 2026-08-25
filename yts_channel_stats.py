#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 管理者看板 - 频道「近10条视频」播放统计（2026-08-26）

每个网红 3 次 API 调用（共 3 配额单位，极省）：
  1. channels.list   → 拿 uploads 播放列表ID + 头像
  2. playlistItems   → 取最新 10 条视频ID（一页搞定）
  3. videos.list     → 批量拿这 10 条的播放量

返回 {avg, median, views, avatar, ts}；7 天缓存 + 手动 force 刷新。
缓存/防重入机制与 yts_yt_stats.py 一致（原子写 + 同进程锁）。
"""
import json
import os
import statistics
import threading
import time
import uuid

import yts_yt_stats as YT

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".yt_recent10_cache.json")
TTL = 7 * 24 * 3600  # 7 天
RECENT_N = 10

_lock = threading.Lock()
_inflight = set()


def _load_cache() -> dict:
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        tmp = f"{CACHE_PATH}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except Exception:
        pass


def fetch_recent10(channel_id: str, force: bool = False) -> dict | None:
    """抓频道最新10条视频的播放量，算均值/中位数。

    返回 {"avg", "median", "views": [10条播放量], "avatar": 头像URL, "ts"}；
    无 key / 频道无效 / 无视频 → None。force=True 无视7天缓存强制重抓。
    """
    if not channel_id or not str(channel_id).startswith("UC"):
        return None
    cache = _load_cache()
    hit = cache.get(channel_id)
    if not force and hit and time.time() - hit.get("ts", 0) < TTL:
        return hit
    if not YT.get_key():
        return hit
    # 防重入：多人同时打开同一频道只发一次请求
    with _lock:
        if channel_id in _inflight:
            return hit
        _inflight.add(channel_id)
    try:
        # ① 频道信息：uploads 播放列表ID + 头像（1 unit）
        ch = YT._get("channels", {
            "part": "contentDetails,snippet", "id": channel_id})
        item = (ch.get("items") or [{}])[0]
        uploads = ((item.get("contentDetails") or {})
                   .get("relatedPlaylists", {}).get("uploads", ""))
        thumbs = ((item.get("snippet") or {}).get("thumbnails") or {})
        avatar = ((thumbs.get("medium") or thumbs.get("default") or {})
                  .get("url", ""))
        if not uploads:
            return hit
        # ② 最新10条视频ID（1 unit，一页搞定）
        pl = YT._get("playlistItems", {
            "part": "contentDetails", "playlistId": uploads,
            "maxResults": RECENT_N})
        vids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        if not vids:
            return hit
        # ③ 批量拿播放量（1 unit）
        data = YT._get("videos", {
            "part": "statistics", "id": ",".join(vids)})
        views = [int((v.get("statistics") or {}).get("viewCount") or 0)
                 for v in data.get("items", [])]
        if not views:
            return hit
        rec = {
            "avg": round(sum(views) / len(views)),
            "median": round(statistics.median(views)),
            "views": views,
            "avatar": avatar,
            "ts": time.time(),
        }
        cache[channel_id] = rec
        _save_cache(cache)
        return rec
    except Exception:
        return hit
    finally:
        with _lock:
            _inflight.discard(channel_id)
