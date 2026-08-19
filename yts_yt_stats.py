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
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "https://www.googleapis.com/youtube/v3"
SOCKS = {"https": "socks5h://127.0.0.1:13659",
         "http": "socks5h://127.0.0.1:13659"}
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".yt_stats_cache.json")
TTL = 7 * 86400
MAX_PAGES = 20  # 最多翻 20 页上传（1000 条视频），防配额爆炸


# 视频数据缓存 TTL：1天（分析模块每日自动刷新）
VIDEO_TTL = 86400


def get_key() -> str:
    k = os.environ.get("YOUTUBE_API_KEY", "")
    if k:
        return k
    try:
        from yida_config_local import YOUTUBE_API_KEY as local_key
        return local_key or ""
    except Exception:
        return ""


def extract_video_id(url: str) -> str:
    """从任意形态的 YouTube 链接提取 videoId；无法提取返回 ''。

    覆盖：watch?v= / youtu.be/ / shorts/ / embed/ / live/ / 裸ID
    （注意 Shorts 和短链格式，仅匹配 watch?v= 会漏抓）
    """
    s = str(url or "").strip()
    if not s:
        return ""
    # 1) ?v= 参数（watch / m.youtube / 带其它参数）
    m = re.search(r"[?&]v=([\w-]{11})", s)
    if m:
        return m.group(1)
    # 2) 路径形态：youtu.be/ID · shorts/ID · embed/ID · live/ID · v/ID
    m = re.search(r"(?:youtu\.be/|/shorts/|/embed/|/live/|/v/)([\w-]{11})", s)
    if m:
        return m.group(1)
    # 3) 裸 videoId
    if re.fullmatch(r"[\w-]{11}", s):
        return s
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
    # 原子写：先写唯一临时文件再 rename；临时文件名带随机后缀，
    # 防止两个会话同时写同一个 .tmp 互相截断产生半截JSON
    try:
        tmp = f"{CACHE_PATH}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except Exception:
        pass


# 同进程内防重入：10人同时打开同一频道时只发一次真实请求
_lock = threading.Lock()
_inflight = set()        # 频道级进行中标记
_inflight_video = set()  # 视频级进行中标记（分析页自动抓取用）


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
    # 防重入：10人共用下，若另一个会话正在抓同一频道，
    # 本会话先返回旧缓存，不重复发起几十次翻页请求
    with _lock:
        if channel_id in _inflight:
            return hit
        _inflight.add(channel_id)
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
    finally:
        # 无论成功失败都释放防重入标记，避免抓取失败后频道被永久跳过
        with _lock:
            _inflight.discard(channel_id)


# ---------------------------------------------------------------------------
# 单条视频指标（分析模块自动抓取用，TTL 1天）
# ---------------------------------------------------------------------------
VIDEO_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".yt_video_cache.json")


def _load_video_cache() -> dict:
    try:
        with open(VIDEO_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_video_cache(cache: dict):
    # 原子写：临时文件名带随机后缀，防止并发会话互相截断同一临时文件
    try:
        tmp = f"{VIDEO_CACHE_PATH}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, VIDEO_CACHE_PATH)
    except Exception:
        pass


def fetch_video_stats(url: str, force: bool = False) -> dict | None:
    """抓取单条视频的播放/点赞/评论/时长。

    返回 {"views", "likes", "comments", "duration", "published_at", "ts"}；
    无 key / 视频不可见 / 未公开链接等失败返回 None（错误结果也缓存1天，
    避免同一条坏链接反复烧配额）。force=True 时无视24h缓存强制重抓。
    """
    vid = extract_video_id(url)
    if not vid:
        return None
    cache = _load_video_cache()
    hit = cache.get(vid)
    if not force and hit and time.time() - hit.get("ts", 0) < VIDEO_TTL:
        return hit if not hit.get("err") else None
    if not get_key():
        return hit if hit and not hit.get("err") else None
    # 双重检查：缓存过期瞬间10个会话并发进分析页，只让1个会话发起请求；
    # 其他会话等它写回缓存文件后直接读取
    with _lock:
        if vid in _inflight_video:
            return hit if hit and not hit.get("err") else None
        _inflight_video.add(vid)
    try:
        cache = _load_video_cache()  # 重读：可能已被先完成的会话写回
        fresh = cache.get(vid)
        if fresh and time.time() - fresh.get("ts", 0) < VIDEO_TTL:
            return fresh if not fresh.get("err") else None
        data = _get("videos", {"part": "statistics,contentDetails,snippet",
                               "id": vid})
        items = data.get("items") or []
        if not items:  # 视频不存在/不可见
            cache[vid] = {"err": True, "ts": time.time()}
            _save_video_cache(cache)
            return None
        stats = items[0].get("statistics") or {}
        rec = {
            "views": int(stats.get("viewCount") or 0),
            "likes": int(stats.get("likeCount") or 0),
            "comments": int(stats.get("commentCount") or 0),
            "duration": _parse_secs((items[0].get("contentDetails") or {})
                                    .get("duration")),
            "published_at": (items[0].get("snippet") or {}).get("publishedAt", "")[:10],
            "ts": time.time(),
        }
        cache[vid] = rec
        _save_video_cache(cache)
        return rec
    except Exception:
        # 网络/配额异常不写错误缓存：下次进入分析页会自动重试
        return hit if hit and not hit.get("err") else None
    finally:
        with _lock:
            _inflight_video.discard(vid)
