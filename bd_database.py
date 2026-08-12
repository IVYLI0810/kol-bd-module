#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BD 网红底库数据层

设计目标：
- 支持 Supabase（生产环境）
- 支持本地 SQLite（独立 demo / 本机调试）
- 提供 BD 网红的增删改查、商品数据导入接口
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 表结构定义
# ---------------------------------------------------------------------------

BD_INFLUENCERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bd_influencers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT UNIQUE,
    channel_name TEXT,
    channel_url TEXT,
    category TEXT,
    recruiter TEXT,
    subscribers INTEGER DEFAULT 0,
    status TEXT DEFAULT '已引入',
    notes TEXT,
    -- 追踪视频（给网红参考/回链）
    video_link TEXT,
    video_views INTEGER DEFAULT 0,
    video_likes INTEGER DEFAULT 0,
    video_comments INTEGER DEFAULT 0,
    -- 商品效果数据
    product_link TEXT,
    product_views INTEGER DEFAULT 0,
    ctr REAL,
    orders INTEGER DEFAULT 0,
    conversion_rate REAL,
    gmv REAL DEFAULT 0,
    price REAL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
"""


# ---------------------------------------------------------------------------
# 本地 SQLite 实现
# ---------------------------------------------------------------------------

class LocalBDDB:
    """基于 SQLite 的本地 BD 底库，适合 demo 和本机调试"""

    def __init__(self, db_path: str = "bd_influencers.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(BD_INFLUENCERS_SCHEMA)
            conn.commit()

    def add(self, record: dict) -> dict:
        """新增或更新 BD 网红记录"""
        now = datetime.now().isoformat()
        record.setdefault("created_at", now)
        record["updated_at"] = now

        # 仅保留表内存在的字段
        allowed = {
            "channel_id", "channel_name", "channel_url", "category",
            "recruiter", "subscribers", "status", "notes",
            "video_link", "video_views", "video_likes", "video_comments",
            "product_link", "product_views", "ctr", "orders",
            "conversion_rate", "gmv", "price",
            "created_at", "updated_at",
        }
        data = {k: v for k, v in record.items() if k in allowed}

        keys = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"""
            INSERT INTO bd_influencers ({keys})
            VALUES ({placeholders})
            ON CONFLICT(channel_id) DO UPDATE SET
                updated_at=excluded.updated_at,
                channel_name=COALESCE(excluded.channel_name, bd_influencers.channel_name),
                channel_url=COALESCE(excluded.channel_url, bd_influencers.channel_url),
                category=COALESCE(excluded.category, bd_influencers.category),
                recruiter=COALESCE(excluded.recruiter, bd_influencers.recruiter),
                subscribers=COALESCE(excluded.subscribers, bd_influencers.subscribers),
                status=COALESCE(excluded.status, bd_influencers.status),
                notes=COALESCE(excluded.notes, bd_influencers.notes),
                video_link=COALESCE(excluded.video_link, bd_influencers.video_link),
                video_views=COALESCE(excluded.video_views, bd_influencers.video_views),
                video_likes=COALESCE(excluded.video_likes, bd_influencers.video_likes),
                video_comments=COALESCE(excluded.video_comments, bd_influencers.video_comments),
                product_link=COALESCE(excluded.product_link, bd_influencers.product_link),
                product_views=COALESCE(excluded.product_views, bd_influencers.product_views),
                ctr=COALESCE(excluded.ctr, bd_influencers.ctr),
                orders=COALESCE(excluded.orders, bd_influencers.orders),
                conversion_rate=COALESCE(excluded.conversion_rate, bd_influencers.conversion_rate),
                gmv=COALESCE(excluded.gmv, bd_influencers.gmv),
                price=COALESCE(excluded.price, bd_influencers.price)
        """
        with self._connect() as conn:
            conn.execute(sql, list(data.values()))
            conn.commit()
            row = conn.execute(
                "SELECT * FROM bd_influencers WHERE channel_id = ?",
                (data["channel_id"],)
            ).fetchone()
        return self._row_to_dict(row)

    def get_all(self, filters: dict | None = None) -> list[dict]:
        """获取所有 BD 网红，支持简单过滤"""
        sql = "SELECT * FROM bd_influencers WHERE 1=1"
        params = []
        if filters:
            for key, value in filters.items():
                if value is not None and value != "":
                    sql += f" AND {key} = ?"
                    params.append(value)
        sql += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_by_channel_id(self, channel_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bd_influencers WHERE channel_id = ?",
                (channel_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def update(self, channel_id: str, updates: dict) -> dict | None:
        updates["updated_at"] = datetime.now().isoformat()
        allowed = {
            "channel_name", "channel_url", "category", "recruiter",
            "subscribers", "status", "notes",
            "video_link", "video_views", "video_likes", "video_comments",
            "product_link", "product_views", "ctr", "orders",
            "conversion_rate", "gmv", "price", "updated_at",
        }
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return self.get_by_channel_id(channel_id)

        set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
        values = list(fields.values()) + [channel_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE bd_influencers SET {set_clause} WHERE channel_id = ?",
                values,
            )
            conn.commit()
        return self.get_by_channel_id(channel_id)

    def delete(self, channel_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM bd_influencers WHERE channel_id = ?",
                (channel_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    def bulk_update_metrics(self, records: list[dict]) -> int:
        """批量更新商品与视频指标：channel_id + 视频/商品各字段"""
        now = datetime.now().isoformat()
        count = 0
        metric_fields = {
            "video_link", "video_views", "video_likes", "video_comments",
            "product_link", "product_views", "ctr", "orders",
            "conversion_rate", "gmv", "price",
        }
        with self._connect() as conn:
            for r in records:
                cid = r.get("channel_id")
                if not cid:
                    continue
                fields = {k: v for k, v in r.items() if k in metric_fields and v is not None and v != ""}
                if not fields:
                    continue
                fields["updated_at"] = now
                set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
                values = list(fields.values()) + [cid]
                conn.execute(
                    f"UPDATE bd_influencers SET {set_clause} WHERE channel_id = ?",
                    values,
                )
                count += 1
            conn.commit()
        return count

    def sync_from_discovery(self, records: list[dict]) -> int:
        """
        从 kol-finder 挖掘库同步状态为「已引入」的网红到底库。
        records: 挖掘库记录列表，字段需至少包含 channel_id/channel_name/channel_url。
        """
        count = 0
        for rec in records:
            if rec.get("status") != "已引入":
                continue
            mapped = {
                "channel_id": rec.get("channel_id"),
                "channel_name": rec.get("channel_name"),
                "channel_url": rec.get("channel_url"),
                "category": rec.get("category", ""),
                "recruiter": rec.get("discovered_by", ""),
                "subscribers": rec.get("subscribers", 0) or 0,
                "status": "已引入",
            }
            if not mapped["channel_id"]:
                continue
            self.add(mapped)
            count += 1
        return count

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return {key: row[idx] for idx, key in enumerate(row.keys())}


# ---------------------------------------------------------------------------
# Supabase 实现（生产环境）
# ---------------------------------------------------------------------------

class SupabaseBDDB:
    """基于 Supabase 的 BD 底库，集成到 kol-finder 时使用"""

    def __init__(self, url: str, key: str, table_name: str = "bd_influencers"):
        from supabase import create_client
        self.client = create_client(url, key)
        self.table = table_name

    def add(self, record: dict) -> dict:
        now = datetime.now().isoformat()
        record.setdefault("created_at", now)
        record["updated_at"] = now
        res = self.client.table(self.table).upsert(
            record, on_conflict="channel_id"
        ).execute()
        return res.data[0] if res.data else record

    def get_all(self, filters: dict | None = None) -> list[dict]:
        q = self.client.table(self.table).select("*").order("updated_at", desc=True)
        if filters:
            for key, value in filters.items():
                if value is not None and value != "":
                    q = q.eq(key, value)
        res = q.execute()
        return res.data or []

    def get_by_channel_id(self, channel_id: str) -> dict | None:
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("channel_id", channel_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def update(self, channel_id: str, updates: dict) -> dict | None:
        updates["updated_at"] = datetime.now().isoformat()
        res = (
            self.client.table(self.table)
            .update(updates)
            .eq("channel_id", channel_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def delete(self, channel_id: str) -> bool:
        res = (
            self.client.table(self.table)
            .delete()
            .eq("channel_id", channel_id)
            .execute()
        )
        return bool(res.data)

    def sync_from_discovery(self, discovery_url: str, discovery_key: str, discovery_table: str = "influencers") -> int:
        """
        从 kol-finder 挖掘库（另一个 Supabase 项目或同一项目的不同表）
        同步状态为「已引入」的网红到底库。
        """
        from supabase import create_client
        discovery_client = create_client(discovery_url, discovery_key)
        res = (
            discovery_client.table(discovery_table)
            .select("channel_id,channel_name,channel_url,category,subscribers,discovered_by,status")
            .eq("status", "已引入")
            .execute()
        )
        records = res.data or []
        count = 0
        for rec in records:
            mapped = {
                "channel_id": rec.get("channel_id"),
                "channel_name": rec.get("channel_name"),
                "channel_url": rec.get("channel_url"),
                "category": rec.get("category", ""),
                "recruiter": rec.get("discovered_by", ""),
                "subscribers": rec.get("subscribers", 0) or 0,
                "status": "已引入",
            }
            if not mapped["channel_id"]:
                continue
            self.add(mapped)
            count += 1
        return count

    def bulk_update_metrics(self, records: list[dict]) -> int:
        count = 0
        now = datetime.now().isoformat()
        metric_fields = {
            "video_link", "video_views", "video_likes", "video_comments",
            "product_link", "product_views", "ctr", "orders",
            "conversion_rate", "gmv", "price",
        }
        for r in records:
            cid = r.get("channel_id")
            if not cid:
                continue
            updates = {k: v for k, v in r.items() if k in metric_fields and v is not None and v != ""}
            if not updates:
                continue
            updates["updated_at"] = now
            self.client.table(self.table).update(updates).eq("channel_id", cid).execute()
            count += 1
        return count


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def get_bd_db(use_supabase: bool = False, supabase_url: str = "", supabase_key: str = "",
              db_path: str = "bd_influencers.db",
              use_yida: bool = False, yida_config: dict | None = None):
    """工厂函数：根据配置返回对应的数据库实例

    优先级：宜搭 > Supabase > 本地 SQLite
    yida_config 需包含（阿里钉 aliding 网关）：
      access_key_id, access_key_secret, app_type, system_token, form_uuid, account_id
    """
    if use_yida and yida_config:
        from yida_bd_database import YidaBDDB
        return YidaBDDB(**yida_config)
    if use_supabase and supabase_url and supabase_key:
        return SupabaseBDDB(supabase_url, supabase_key)
    return LocalBDDB(db_path)


# ---------------------------------------------------------------------------
# SQL 迁移脚本（给 Supabase 用）
# ---------------------------------------------------------------------------

SUPABASE_MIGRATION_SQL = """
-- BD 网红底库表（与 kol-finder 挖掘库联动）
CREATE TABLE IF NOT EXISTS bd_influencers (
  id BIGSERIAL PRIMARY KEY,
  channel_id TEXT UNIQUE NOT NULL,
  channel_name TEXT DEFAULT '',
  channel_url TEXT DEFAULT '',
  category TEXT DEFAULT '',
  recruiter TEXT DEFAULT '',
  subscribers BIGINT DEFAULT 0,
  status TEXT DEFAULT '已引入',
  notes TEXT DEFAULT '',
  -- 追踪视频（给网红参考/回链）
  video_link TEXT DEFAULT '',
  video_views BIGINT DEFAULT 0,
  video_likes BIGINT DEFAULT 0,
  video_comments BIGINT DEFAULT 0,
  -- 商品效果数据
  product_link TEXT DEFAULT '',
  product_views BIGINT DEFAULT 0,
  ctr REAL,
  orders BIGINT DEFAULT 0,
  conversion_rate REAL,
  gmv REAL DEFAULT 0,
  price REAL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 可选：RLS 策略（如果 Supabase 项目已开启）
-- ALTER TABLE bd_influencers ENABLE ROW LEVEL SECURITY;
""".strip()


if __name__ == "__main__":
    # 简单自测
    db = LocalBDDB(":memory:")
    r = db.add({
        "channel_id": "UCxxxx",
        "channel_name": "테스트",
        "channel_url": "https://youtube.com/xxx",
        "category": "뷰티",
        "recruiter": "아이비",
        "subscribers": 15000,
    })
    print(json.dumps(r, ensure_ascii=False, indent=2))
