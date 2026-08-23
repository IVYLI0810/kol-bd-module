#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 商品效果数据导入：解析 YouTube Shopping 全量 CSV → 匹配各网红选品 →
算点击率/均摊视频 → 写入宜搭商品子表 + 视频子表。

数据链路（与用户确认的方案）：
- 商品维度：一个商品一行，写入该网红的「商品明细」子表
- 视频维度（均摊方案B）：商品销售额 ÷ 挂它的视频数，平分到各视频
- 视频 CPM：网红报价 ÷ 播放量 × 1000（播放为0时不写）
"""
import csv
import io
import os
import re

# ---------------------------------------------------------------------------
# 汇率：网红报价存韩币，商品报表销售额是美金。
# CPM 等成本指标统一换算成美金口径（汇率可配，默认1538韩币/美金）。
# ---------------------------------------------------------------------------
def usd_rate() -> float:
    try:
        v = float(os.environ.get("USD_RATE", "") or 1538)
        return v if v > 0 else 1538
    except ValueError:
        return 1538


def krw_to_usd(krw) -> float:
    try:
        return float(krw) / usd_rate()
    except (TypeError, ValueError):
        return 0.0


def _norm_pid(s: str) -> str:
    """商品ID归一化：去 ko 前缀、取纯数字。兼容链接/裸ID"""
    s = str(s or "").strip()
    m = re.search(r"/item/(\d+)", s)
    if m:
        return m.group(1)
    s2 = re.sub(r"^ko", "", s, flags=re.IGNORECASE)
    m = re.search(r"(\d{6,})", s2)
    return m.group(1) if m else ""


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_product_csv(data) -> dict:
    """解析全量商品 CSV，返回 {纯商品ID: {name,gmv,net_sales,commission,
    video_views,impressions,clicks,orders,cvr}}。
    表头可能在前 2 行（名称：/时间段：），动态定位 '名称,SKU ID' 表头行。"""
    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data
    lines = text.splitlines()
    header_idx = None
    for i, l in enumerate(lines[:5]):
        if l.lstrip("\ufeff").startswith("名称") and "SKU" in l:
            header_idx = i
            break
    if header_idx is None:
        return {}
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    out = {}
    for row in reader:
        pid = _norm_pid(row.get("SKU ID") or "")
        if not pid:
            continue
        impressions = _f(row.get("展示次数"))
        clicks = _f(row.get("点击次数"))
        out[pid] = {
            "name": (row.get("名称") or "").strip()[:400],
            "gmv": _f(row.get("销售总额")),
            "net_sales": _f(row.get("净销售额")),
            "commission": _f(row.get("佣金")),
            "video_views": _f(row.get("视频观看次数")),
            "impressions": impressions,
            "clicks": clicks,
            "orders": _f(row.get("订单数")),
            "cvr": _f(row.get("转化率")),
            # 点击率自动计算：点击÷展示（展示为0则0）
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0.0,
        }
    return out


def build_product_rows(csv_data: dict, product_list: list) -> list:
    """按某网红的选品清单，从 CSV 里取出对应商品行（写入商品子表用）。
    product_list 里每项是链接或ID，先归一化成纯ID。"""
    rows = []
    for item in product_list or []:
        pid = _norm_pid(item)
        if not pid or pid not in csv_data:
            continue
        d = csv_data[pid]
        rows.append({
            "pid": pid, "name": d["name"], "gmv": d["gmv"],
            "net_sales": d["net_sales"], "commission": d["commission"],
            "video_views": d["video_views"], "impressions": d["impressions"],
            "clicks": d["clicks"], "orders": d["orders"],
            "cvr": d["cvr"], "ctr": d["ctr"],
        })
    # 同商品去重（选品清单里重复列同一商品只留一条）
    seen, uniq = set(), []
    for r in rows:
        if r["pid"] in seen:
            continue
        seen.add(r["pid"])
        uniq.append(r)
    return uniq


def allocate_to_videos(videos: list, product_rows: list, price: float) -> list:
    """均摊方案B：把每个商品的销售额/订单按「挂它的视频数」平分到各视频，
    并按 报价(美金)÷播放量×1000 计算各视频 CPM。返回更新后的 videos 列表。

    videos 每项含 product_ids（逗号分隔的ID或链接）。
    price: 网红报价（韩币），内部自动换算美金（销售额是美金，成本口径统一）。
    """
    prods_by_id = {r["pid"]: r for r in product_rows}
    # 统计每个商品被几个视频挂（用于均摊分母）
    holder_count = {}
    for v in videos or []:
        pids = {_norm_pid(p) for p in str(v.get("product_ids") or "").split(",")
                if p.strip()}
        for pid in pids:
            if pid in prods_by_id:
                holder_count[pid] = holder_count.get(pid, 0) + 1

    updated = []
    for v in videos or []:
        v = dict(v)
        pids = {_norm_pid(p) for p in str(v.get("product_ids") or "").split(",")
                if p.strip()}
        gmv = sum(prods_by_id[p]["gmv"] / holder_count[p]
                  for p in pids if p in prods_by_id and holder_count.get(p))
        orders = sum(prods_by_id[p]["orders"] / holder_count[p]
                     for p in pids if p in prods_by_id and holder_count.get(p))
        if gmv or orders:
            v["gmv"] = round(gmv, 2)
            v["orders"] = round(orders, 2)
        # CPM：报价(韩币→美金)÷播放量×1000（播放为0跳过）
        views = _f(v.get("views"))
        price_usd = krw_to_usd(price)
        if price_usd and views:
            v["cpm"] = round(price_usd / views * 1000, 2)
        updated.append(v)
    return updated


def summarize_kol(product_rows: list) -> tuple:
    """汇总某网红全部商品的 点击/成交/销售额（回写主记录用）。
    返回 (clicks, orders, gmv)"""
    clicks = sum(r["clicks"] for r in product_rows)
    orders = sum(r["orders"] for r in product_rows)
    gmv = sum(r["gmv"] for r in product_rows)
    return int(clicks), int(orders), round(gmv, 2)
