#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS YouTube 频道数据：粉丝量 / 视频总播放（长短视频分别累计）

- key 读取顺序：环境变量 YOUTUBE_API_KEY（Streamlit Secrets）→ yida_config_local.YOUTUBE_API_KEY
- 本地 JSON 缓存 7 天（.yt_stats_cache.json），开详情秒出，不重复烧配额
- 长短分类：视频时长 ≤ 60s 记为短视频（Shorts），其余长视频
- 网络：先直连，失败回落 SOCKS（公司网）；云端直连可用
- 无 key / 非 UC 开头频道ID / 请求失败：返回 None 或旧缓存，页面显示占位
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "https://www.googleapis.com/youtube/v3"
SOCKS = {"https": "socks5h://127.0.0.1:13659",
         "http": "socks5h://127.0.0.1:13659"}
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".yt_stats_cache.json")
TTL = 7 * 86400
MAX_PAGES = 20  # 最多翻 20 页上传（1000 条视频），防配额爆炸


def get_key() -> str:
    k = os.environ.get("YOUTUBE_API_KEY", "")
    if k:
        return k
    try:
        from yida_config_local import YOUTUBE_API_KEY as local_key
        return local_key or ""
    except Exception:
        return ""


def _get(path: str, params: dict) -> dict:
    params = dict(params, key=get_key())
    try:
        r = requests.get(f"{BASE}/{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        r = requests.get(f"{BASE}/{path}", params=params, timeout=15,
                         proxies=SOCKS)
        r.raise_for_status()
        return r.json()


def _parse_secs(iso: str) -> int:
    secs = {"H": 0, "M": 0, "S": 0}
    for v, u in re.findall(r"(\d+)([HMS])", iso or ""):
        secs[u] = int(v)
    return secs["H"] * 3600 + secs["M"] * 60 + secs["S"]


def _load_cache() -> dict:
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def cached(channel_id: str) -> dict | None:
    """仅查缓存：新鲜命中返回记录，否则 None（不发网络请求）"""
    hit = _load_cache().get(channel_id)
    if hit and time.time() - hit.get("ts", 0) < TTL:
        return hit
    return None


def fetch_stats(channel_id: str) -> dict | None:
    """{subscribers, total_views, long_views, short_views, ts}；无key/失败=None"""
    if not channel_id or not channel_id.startswith("UC"):
        return None
    cache = _load_cache()
    hit = cache.get(channel_id)
    if hit and time.time() - hit.get("ts", 0) < TTL:
        return hit
    if not get_key():
        return hit
    try:
        ch = _get("channels", {"part": "statistics,contentDetails",
                               "id": channel_id})
        item = (ch.get("items") or [{}])[0]
        stats = item.get("statistics") or {}
        uploads = ((item.get("contentDetails") or {})
                   .get("relatedPlaylists", {}).get("uploads", ""))
        long_v, short_v = 0, 0
        if uploads:
            vids, pages = [], 0
            token = None
            while pages < MAX_PAGES:
                pl = _get("playlistItems", {
                    "part": "contentDetails", "playlistId": uploads,
                    "maxResults": 50, **({"pageToken": token} if token else {})})
                vids += [i["contentDetails"]["videoId"]
                         for i in pl.get("items", [])]
                token = pl.get("nextPageToken")
                pages += 1
                if not token:
                    break
            chunks = [vids[i:i + 50] for i in range(0, len(vids), 50)]
            with ThreadPoolExecutor(max_workers=6) as ex:
                for data in ex.map(
                        lambda ids: _get("videos", {
                            "part": "statistics,contentDetails",
                            "id": ",".join(ids)}), chunks):
                    for v in data.get("items", []):
                        views = int((v.get("statistics") or {})
                                    .get("viewCount", 0))
                        if _parse_secs((v.get("contentDetails") or {})
                                       .get("duration")) <= 60:
                            short_v += views
                        else:
                            long_v += views
        rec = {"subscribers": int(stats.get("subscriberCount") or 0),
               "total_views": int(stats.get("viewCount") or 0),
               "long_views": long_v, "short_views": short_v,
               "ts": time.time()}
        cache[channel_id] = rec
        _save_cache(cache)
        return rec
    except Exception:
        return hit
