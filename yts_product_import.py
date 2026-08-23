#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 选品清单批量导入：解析「网红×商品」Excel（合并行格式）

表格格式（7月/8月YTS网红x商品表）：
- 表头行：第 0 列为 "MONTH"
- 每个网红占一组行：首行含频道名称/负责人/渠道链接等，
  后续行频道名称为空（Excel 合并单元格），属于同一网红
- 列：0=MONTH 1=负责人 2=频道名称 3=渠道链接 4=类目 5=视频类型
      10=商品名 11=商品ID 12=一级类目 13=商品链接

解析结果：[{name, recruiter, channel_url, month, products:[{id, name, url}]}]
"""
import io
import re

import pandas as pd

ITEM_URL = "https://ko.aliexpress.com/item/{pid}.html"


def _norm_pid(v) -> str:
    """商品ID 规范化：兼容 float/int/str，返回纯数字字符串"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    try:
        return str(int(float(s)))
    except (ValueError, OverflowError):
        m = re.search(r"(\d{13,})", s)
        return m.group(1) if m else ""


def _norm_url(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def parse_product_workbook(data: bytes) -> tuple:
    """解析网红×商品 Excel。
    返回 (groups, issues)：
      groups: [{name, recruiter, channel_url, month, products:[{id,name,url}]}]
      issues: 解析过程中的提示（表头未找到等）
    """
    issues = []
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=0, header=None)
    except Exception as e:
        return [], [f"Excel 读取失败：{e}"]

    # 定位表头行（第 0 列 == MONTH）
    header_row = None
    for i in range(min(10, len(df))):
        if str(df.iloc[i, 0]).strip().upper() == "MONTH":
            header_row = i
            break
    if header_row is None:
        return [], ["未找到表头行（第 1 列应为 MONTH），请确认是「网红×商品」表"]
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    if df.shape[1] < 12:
        return [], [f"列数不足（{df.shape[1]} 列），请确认表格完整"]

    groups = []
    cur = None
    for _, row in df.iterrows():
        name = _norm_url(row[2])
        if name:  # 新网红组开始
            month = _norm_url(row[0])
            cur = {
                "name": name,
                "recruiter": _norm_url(row[1]),
                "channel_url": _norm_url(row[3]),
                "month": month,
                "products": [],
            }
            groups.append(cur)
        if cur is None:
            continue
        pid = _norm_pid(row[11] if df.shape[1] > 11 else None)
        if not pid:
            continue
        pname = _norm_url(row[10] if df.shape[1] > 10 else None)
        purl = _norm_url(row[13] if df.shape[1] > 13 else None) or ITEM_URL.format(pid=pid)
        # 同一网红内去重
        if any(p["id"] == pid for p in cur["products"]):
            continue
        cur["products"].append({"id": pid, "name": pname, "url": purl})

    empty = [g["name"] for g in groups if not g["products"]]
    if empty:
        issues.append(f"以下 {len(empty)} 位网红没有商品行，将跳过：" +
                      "、".join(empty[:8]))
    return [g for g in groups if g["products"]], issues


def match_groups(groups, records) -> list:
    """把解析出的网红组匹配到系统记录。
    records: store.list_all() 的结果（含 name/channel_url/collab_id/product_list）
    匹配优先级：频道链接（规范化后精确）→ 频道名精确 → 频道名模糊。
    返回 [{group, matched: collab字典或None, match_by}]
    """
    import difflib

    def norm_u(u):
        return re.sub(r"^https?://(www\.)?", "", str(u or "").strip().rstrip("/"))

    url_map, name_map = {}, {}
    for r in records:
        u = norm_u(r.get("channel_url"))
        if u:
            url_map.setdefault(u, r)
        nm = str(r.get("name") or "").strip()
        if nm:
            name_map.setdefault(nm, r)
    names = list(name_map.keys())

    out = []
    for g in groups:
        matched, by = None, ""
        u = norm_u(g["channel_url"])
        if u and u in url_map:
            matched, by = url_map[u], "链接"
        elif g["name"] in name_map:
            matched, by = name_map[g["name"]], "名称"
        else:
            best, best_ratio = None, 0.0
            for nm in names:
                ratio = difflib.SequenceMatcher(None, g["name"], nm).ratio()
                if ratio > best_ratio:
                    best, best_ratio = name_map[nm], ratio
            if best_ratio >= 0.75:
                matched, by = best, f"模糊({best_ratio:.0%})"
        out.append({"group": g, "matched": matched, "match_by": by})
    return out


def merge_product_lists(existing: list, new_urls: list) -> list:
    """合并选品清单：保留已有 + 追加新的（按商品ID去重）"""
    def pid_of(u):
        m = re.search(r"/item/(\d+)", str(u))
        return m.group(1) if m else str(u).strip()
    seen = {pid_of(u) for u in existing if str(u).strip()}
    merged = [u for u in existing if str(u).strip()]
    for u in new_urls:
        if pid_of(u) not in seen:
            seen.add(pid_of(u))
            merged.append(u)
    return merged
