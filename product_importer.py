#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品效果数据导入模块

支持：
- CSV / Excel 一键上传
- 必含字段：channel_id（或 channel_name）
- 可选字段：product_link, ctr, conversion_rate, gmv
- 自动校验并返回导入结果
"""

import io
import json
from typing import Any

import pandas as pd


REQUIRED_COLS = ["channel_id"]  # 主键，优先用 channel_id
ALTERNATIVE_KEY = "channel_name"  # 备用匹配字段
METRIC_COLS = [
    "video_link", "video_views", "video_likes", "video_comments",
    "product_link", "product_views", "product_clicks", "product_conversions",
    "ctr", "conversion_rate", "gmv",
]


def _normalize_float(value: Any) -> float | None:
    """把百分比或小数统一转成 float"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    # 处理 12.5% -> 0.125
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_int(value: Any) -> int | None:
    """把字符串/浮点统一转成 int"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_upload_file(file_obj: Any) -> pd.DataFrame:
    """根据文件扩展名解析 CSV/Excel"""
    name = getattr(file_obj, "name", "").lower()
    content = file_obj.read()
    if isinstance(content, bytes):
        content = io.BytesIO(content)
    else:
        content = io.StringIO(content)

    if name.endswith(".csv"):
        return pd.read_csv(content)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(content)
    # 尝试自动识别
    try:
        return pd.read_csv(content)
    except Exception:
        return pd.read_excel(content)


def validate_and_transform(df: pd.DataFrame) -> dict:
    """
    校验并转换上传数据。
    返回：{
        "valid": [...],       # 可导入记录
        "invalid": [...],     # 错误记录及原因
        "total": int,
        "success_count": int,
        "error_count": int,
    }
    """
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    valid = []
    invalid = []

    for idx, row in df.iterrows():
        record = {"row": idx + 2}  # Excel 行号从 2 开始
        errors = []

        # 1. 找主键
        channel_id = None
        if "channel_id" in df.columns:
            channel_id = str(row.get("channel_id", "")).strip() if pd.notna(row.get("channel_id")) else ""
        if not channel_id and "channel_name" in df.columns:
            channel_name = str(row.get("channel_name", "")).strip() if pd.notna(row.get("channel_name")) else ""
            if channel_name:
                # 先记录 channel_name，后续由数据库层尝试匹配
                record["channel_name"] = channel_name
                channel_id = None  # 暂不强制

        if channel_id:
            record["channel_id"] = channel_id
        elif "channel_name" not in record:
            errors.append("缺少 channel_id 或 channel_name")

        # 2. 转换指标字段
        INT_METRICS = {"video_views", "video_likes", "video_comments", "product_views", "product_clicks", "product_conversions"}
        LINK_METRICS = {"video_link", "product_link"}
        for col in METRIC_COLS:
            if col in df.columns and pd.notna(row.get(col)):
                if col in LINK_METRICS:
                    record[col] = str(row[col]).strip()
                elif col in INT_METRICS:
                    val = _normalize_int(row[col])
                    if val is None:
                        errors.append(f"{col} 格式错误: {row[col]}")
                    else:
                        record[col] = val
                else:
                    val = _normalize_float(row[col])
                    if val is None:
                        errors.append(f"{col} 格式错误: {row[col]}")
                    else:
                        record[col] = val

        if errors:
            record["errors"] = errors
            invalid.append(record)
        else:
            # 只保留有效字段
            clean = {k: v for k, v in record.items() if k in ["channel_id", "channel_name"] + METRIC_COLS}
            clean["row"] = record["row"]
            valid.append(clean)

    return {
        "valid": valid,
        "invalid": invalid,
        "total": len(df),
        "success_count": len(valid),
        "error_count": len(invalid),
    }


def generate_template_df() -> pd.DataFrame:
    """生成导入模板"""
    return pd.DataFrame(columns=[
        "channel_id",
        "channel_name",
        "video_link",
        "video_views",
        "video_likes",
        "video_comments",
        "product_link",
        "product_views",
        "product_clicks",
        "product_conversions",
        "ctr",
        "conversion_rate",
        "gmv",
    ])


if __name__ == "__main__":
    # 自测
    sample = pd.DataFrame({
        "channel_id": ["UCxxx", "UCyyy", ""],
        "product_link": ["https://aliexpress.com/xxx", "https://aliexpress.com/yyy", "https://aliexpress.com/zzz"],
        "ctr": ["3.5%", 0.025, "invalid"],
        "conversion_rate": ["1.2%", "0.8%", "2%"],
        "gmv": [1200000, "980,000", 500000],
    })
    result = validate_and_transform(sample)
    print(json.dumps(result, ensure_ascii=False, indent=2))
