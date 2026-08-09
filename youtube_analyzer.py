#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube 数据分析模块

能力：
- 解析 YouTube 视频/频道链接
- 获取单个视频数据（播放量/点赞/评论数）
- 获取频道近期上传视频列表
- 获取视频评论文本（通过 Data API commentThreads）
- 爆款分析：曝光 / 互动 / 转化 三个维度
"""

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

BASE_URL = "https://www.googleapis.com/youtube/v3"

# 韩国评论区高转化信号词
CONVERSION_KEYWORDS = {
    "求链接": ["링크", "링크요", "링크 주세요", "더보기란", "고정댓글", "링크좀", "링크좀요"],
    "求价格": ["가격", "얼마", "얼마에요", "가격이 어떻게 돼요", "얼마인가요", "가격대", "얼마인지"],
    "求购买渠道": ["어디서 샀어요", "구매처", "구매 방법", "사고 싶어요", "어디서 사요", "구매링크", "어디서 파나요"],
    "已购买/想下单": ["샀어요", "주문했어요", "구매 완료", "바로 구매", "구매했어요", "주문완료", "구매할게요"],
    "询问产品细节": ["제품명", "브랜드", "색상", "사이즈", "용량", "종류", "모델명", "어떤 제품"],
}

ALL_SIGNAL_WORDS = [w for group in CONVERSION_KEYWORDS.values() for w in group]

VIEW_WEIGHT = 1
LIKE_WEIGHT = 10
COMMENT_WEIGHT = 20


# ---------------------------------------------------------------------------
# 配额追踪
# ---------------------------------------------------------------------------

class QuotaTracker:
    """简单配额追踪器"""
    DAILY_LIMIT = 10000

    def __init__(self):
        self.used = 0

    def charge(self, cost: int):
        self.used += cost

    def remaining(self) -> int:
        return self.DAILY_LIMIT - self.used

    def check(self, cost: int) -> bool:
        return self.remaining() >= cost


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def extract_video_id(url_or_id: str) -> str | None:
    """从 YouTube 链接或各种 id 中提取 videoId"""
    if not url_or_id:
        return None
    s = url_or_id.strip()
    # 直接是 videoId（11 位）
    if re.match(r"^[A-Za-z0-9_-]{11}$", s):
        return s
    # 标准 watch?v=
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", s)
    if m:
        return m.group(1)
    # Shorts
    m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", s)
    if m:
        return m.group(1)
    # 嵌入链接
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", s)
    if m:
        return m.group(1)
    return None


def extract_channel_id(url_or_handle: str) -> str | None:
    """从频道链接或 @handle 中提取 channel_id（需要后续 resolve）"""
    s = url_or_handle.strip()
    # UC ID
    m = re.search(r"(UC[A-Za-z0-9_-]{22})", s)
    if m:
        return m.group(1)
    # @handle
    m = re.search(r"youtube\.com/@([A-Za-z0-9_.-]+)", s)
    if m:
        return f"@{m.group(1)}"
    if s.startswith("@"):
        return s
    return None


def _iso_to_date(iso_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_duration(iso_duration: str) -> int | None:
    """PT4M13S -> 253 秒"""
    if not iso_duration:
        return None
    total = 0
    m = re.search(r"(\d+)H", iso_duration)
    if m:
        total += int(m.group(1)) * 3600
    m = re.search(r"(\d+)M", iso_duration)
    if m:
        total += int(m.group(1)) * 60
    m = re.search(r"(\d+)S", iso_duration)
    if m:
        total += int(m.group(1))
    return total


# ---------------------------------------------------------------------------
# API 调用封装
# ---------------------------------------------------------------------------

class YouTubeAnalyzer:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.quota = QuotaTracker()

    def _get(self, endpoint: str, params: dict, cost: int) -> dict | None:
        if not self.quota.check(cost):
            raise RuntimeError(f"YouTube API 配额不足，剩余 {self.quota.remaining()}，需要 {cost}")
        params["key"] = self.api_key
        url = f"{BASE_URL}/{endpoint}"
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            self.quota.charge(cost)
            return resp.json()
        except requests.HTTPError as e:
            # 返回更友好的错误
            err = ""
            try:
                err = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise RuntimeError(f"YouTube API 请求失败: {err or str(e)}")

    def get_video_stats(self, video_id: str) -> dict:
        """获取单个视频统计信息，花费 1 unit"""
        data = self._get("videos", {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
        }, cost=1)
        items = data.get("items", [])
        if not items:
            raise RuntimeError(f"找不到视频: {video_id}")
        item = items[0]
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        duration = _parse_duration(item.get("contentDetails", {}).get("duration", ""))
        return {
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "published_at": snippet.get("publishedAt", ""),
            "view_count": int(stats.get("viewCount", 0) or 0),
            "like_count": int(stats.get("likeCount", 0) or 0),
            "comment_count": int(stats.get("commentCount", 0) or 0),
            "duration": duration,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "is_shorts": duration is not None and duration <= 60,
        }

    def get_channel_id_by_handle(self, handle: str) -> str | None:
        """把 @handle 解析成 UC ID，花费 1 unit"""
        if handle.startswith("@"):
            handle = handle[1:]
        data = self._get("search", {
            "part": "snippet",
            "q": handle,
            "type": "channel",
            "maxResults": 1,
        }, cost=100)
        items = data.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
        return None

    def get_channel_stats(self, channel_id: str) -> dict:
        """获取频道统计信息：订阅数、总播放量，花费 1 unit"""
        ch_data = self._get("channels", {
            "part": "statistics,snippet",
            "id": channel_id,
        }, cost=1)
        if not ch_data.get("items"):
            raise RuntimeError(f"找不到频道: {channel_id}")
        item = ch_data["items"][0]
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        return {
            "channel_id": channel_id,
            "title": snippet.get("title", ""),
            "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
            "view_count": int(stats.get("viewCount", 0) or 0),
            "video_count": int(stats.get("videoCount", 0) or 0),
        }

    def get_channel_uploads(self, channel_id: str, max_results: int = 30) -> list[dict]:
        """
        获取频道最近上传视频。
        1 unit (channels 拿 uploads playlist) + 1 unit (playlistItems) + 1 unit (videos stats，最多 50 个一批)
        """
        # 1. 获取 uploads playlist id
        ch_data = self._get("channels", {
            "part": "contentDetails,snippet,statistics",
            "id": channel_id,
        }, cost=1)
        if not ch_data.get("items"):
            raise RuntimeError(f"找不到频道: {channel_id}")
        uploads_id = ch_data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # 2. 获取视频列表
        pl_data = self._get("playlistItems", {
            "part": "snippet,contentDetails",
            "playlistId": uploads_id,
            "maxResults": max_results,
        }, cost=1)
        items = pl_data.get("items", [])
        if not items:
            return []

        video_ids = [it["contentDetails"]["videoId"] for it in items]
        titles = {it["contentDetails"]["videoId"]: it["snippet"]["title"] for it in items}

        # 3. 批量拿 stats（每批 50 个）
        stats_map = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            v_data = self._get("videos", {
                "part": "statistics,contentDetails,snippet",
                "id": ",".join(batch),
            }, cost=1)
            for v in v_data.get("items", []):
                vid = v["id"]
                stats = v.get("statistics", {})
                duration = _parse_duration(v.get("contentDetails", {}).get("duration", ""))
                snippet = v.get("snippet", {})
                stats_map[vid] = {
                    "video_id": vid,
                    "title": snippet.get("title", titles.get(vid, "")),
                    "description": snippet.get("description", ""),
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "view_count": int(stats.get("viewCount", 0) or 0),
                    "like_count": int(stats.get("likeCount", 0) or 0),
                    "comment_count": int(stats.get("commentCount", 0) or 0),
                    "duration": duration,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "is_shorts": duration is not None and duration <= 60,
                }
        return [stats_map[vid] for vid in video_ids if vid in stats_map]

    def get_comments(self, video_id: str, max_results: int = 100) -> list[str]:
        """
        获取视频评论文本，花费 1 unit（maxResults<=100 时）。
        只取顶层评论，不含回复。
        """
        data = self._get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": min(max_results, 100),
            "order": "relevance",  # 相关性排序，更易抓到代表性评论
        }, cost=1)
        comments = []
        for item in data.get("items", []):
            text = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {}).get("textDisplay", "")
            if text:
                comments.append(text)
        return comments

    # -----------------------------------------------------------------------
    # 分析层
    # -----------------------------------------------------------------------

    def detect_conversion_signals(self, comments: list[str]) -> dict:
        signals = {k: 0 for k in CONVERSION_KEYWORDS.keys()}
        signal_comments = []
        for comment in comments:
            if not comment:
                continue
            found = False
            for signal_type, keywords in CONVERSION_KEYWORDS.items():
                for kw in keywords:
                    if kw in comment:
                        signals[signal_type] += 1
                        found = True
                        break
            if found:
                signal_comments.append(comment)
        return {
            "signals": signals,
            "total_signal_comments": len(signal_comments),
            "signal_comments": signal_comments[:20],
        }

    def is_high_conversion(self, signals: dict, total_comments: int) -> bool:
        total = sum(signals.values())
        if total >= 3:
            return True
        if total_comments > 0 and total / total_comments >= 0.05:
            return True
        return False

    def score_video(self, video: dict) -> float:
        return (
            video.get("view_count", 0) * VIEW_WEIGHT
            + video.get("like_count", 0) * LIKE_WEIGHT
            + video.get("comment_count", 0) * COMMENT_WEIGHT
        )

    def analyze_channel(self, channel_input: str, max_videos: int = 30, max_comments: int = 100) -> dict:
        """
        综合 analyze：给频道链接或 @handle，返回爆款/互动/转化分析结果
        """
        channel_id = extract_channel_id(channel_input)
        if channel_id and channel_id.startswith("@"):
            resolved = self.get_channel_id_by_handle(channel_id)
            if not resolved:
                raise RuntimeError(f"无法解析频道: {channel_input}")
            channel_id = resolved

        if not channel_id:
            raise RuntimeError(f"无法识别频道链接: {channel_input}")

        videos = self.get_channel_uploads(channel_id, max_results=max_videos)

        # 给每个视频加评论信号
        for v in videos:
            if v.get("comment_count", 0) > 0:
                try:
                    comments = self.get_comments(v["video_id"], max_results=max_comments)
                    v["comments"] = comments
                    v["conversion_signals"] = self.detect_conversion_signals(comments)
                except Exception as e:
                    v["comments"] = []
                    v["conversion_signals"] = {"signals": {}, "total_signal_comments": 0, "signal_comments": []}
                    v["comment_error"] = str(e)
            else:
                v["comments"] = []
                v["conversion_signals"] = {"signals": {}, "total_signal_comments": 0, "signal_comments": []}

        # 三个维度排序
        by_views = sorted(videos, key=lambda x: x.get("view_count", 0), reverse=True)[:5]
        by_engagement = sorted(
            videos,
            key=lambda x: x.get("like_count", 0) + x.get("comment_count", 0) * 2,
            reverse=True,
        )[:5]
        by_conversion = sorted(
            [v for v in videos if v.get("conversion_signals", {}).get("total_signal_comments", 0) > 0],
            key=lambda x: x.get("conversion_signals", {}).get("total_signal_comments", 0),
            reverse=True,
        )[:5]

        # 最佳参考视频：优先高转化 + Shorts
        best_reference = None
        for v in by_conversion:
            if v.get("is_shorts"):
                best_reference = v
                break
        if not best_reference and by_conversion:
            best_reference = by_conversion[0]
        if not best_reference:
            for v in by_engagement:
                if v.get("is_shorts"):
                    best_reference = v
                    break
        if not best_reference and by_views:
            best_reference = by_views[0]

        return {
            "channel_id": channel_id,
            "total_videos": len(videos),
            "quota_used": self.quota.used,
            "top_exposure": by_views,
            "top_engagement": by_engagement,
            "top_conversion": by_conversion,
            "best_reference": best_reference,
        }


if __name__ == "__main__":
    import os
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("请设置 YOUTUBE_API_KEY 环境变量")
        raise SystemExit(1)
    analyzer = YouTubeAnalyzer(key)
    vid = "jE6XlbFowCc"  # 이프 if 的爆款视频
    print(analyzer.get_video_stats(vid))
