#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 商品数据匹配流程（轻量版）：

新流程（重活离线干，网站只做轻量写入）：
  1. 网站「导出映射表」→ 下载 Excel（网红选品 + 视频挂品 两个sheet）
  2. 把映射表 + YouTube Shopping 全量 CSV 发给助手，离线匹配
  3. 助手产出「导入表」(YTS商品导入表_*.xlsx)：
     - sheet1 商品明细：一行一个（网红, 商品）
     - sheet2 视频分摊：一行一条视频（销售额/订单已均摊好 + CPM）
  4. 上传导入表 → 网站按 channel_id 直接写宜搭（带进度条，很快）
"""
import re

import pandas as pd

SHEET_PRODUCTS = "商品明细"
SHEET_VIDEOS = "视频分摊"


def norm_pid(s) -> str:
    """商品ID归一化：去 ko 前缀、从链接提取纯数字"""
    s = str(s or "").strip()
    if not s or s.lower() == "nan":
        return ""
    m = re.search(r"/item/(\d+)", s)
    if m:
        return m.group(1)
    s2 = re.sub(r"^ko", "", s, flags=re.IGNORECASE)
    m = re.search(r"(\d{6,})", s2)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# 第1步：网站侧导出映射表
# ---------------------------------------------------------------------------
def build_mapping_records(recs: list) -> tuple:
    """从系统记录构建映射表两个 sheet 的行。
    返回 (选品行列表, 视频行列表)"""
    sel, vids = [], []
    for r in recs:
        cid = r.get("collab_id") or ""
        name = r.get("name") or ""
        price = float(r.get("price") or 0)
        sc = r.get("sales_category") or ""  # 带货类目（网红级）
        for item in r.get("product_list") or []:
            pid = norm_pid(item)
            if pid:
                sel.append({"channel_id": cid, "网红": name, "报价": price,
                            "带货类目": sc,
                            "商品ID": pid, "选品链接": str(item).strip()})
        for v in r.get("videos") or []:
            vids.append({"channel_id": cid, "网红": name,
                         "视频链接": v.get("video_url") or "",
                         "视频类型": v.get("video_type") or "",
                         "播放量": int(v.get("views") or 0),
                         "挂的商品": v.get("product_ids") or ""})
    return sel, vids


def mapping_to_excel_bytes(sel_rows: list, video_rows: list) -> bytes:
    """映射表 → Excel 字节（两个 sheet）"""
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(sel_rows or [{}]).to_excel(w, sheet_name="网红选品",
                                                index=False)
        pd.DataFrame(video_rows or [{}]).to_excel(w, sheet_name="视频挂品",
                                                  index=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 第2步：离线匹配（助手侧运行，用真实大 CSV）
# ---------------------------------------------------------------------------
def match_to_import_file(mapping_xlsx: str, big_csv: str, out_xlsx: str) -> dict:
    """离线匹配：映射表 + 全量 CSV → 导入表。
    返回统计 {hit_kols, hit_products, match_products, miss_products}"""
    import yts_product_csv as PC

    map_xl = pd.ExcelFile(mapping_xlsx)
    sel_df = map_xl.parse("网红选品")
    vid_df = map_xl.parse("视频挂品")

    with open(big_csv, "rb") as f:
        csv_data = PC.parse_product_csv(f.read())

    # ---- sheet1 商品明细：每个网红的选品 → 命中 CSV 的写入 ----
    prod_rows, kol_groups = [], {}
    for _, row in sel_df.iterrows():
        cid = str(row["channel_id"])
        pid = norm_pid(row.get("商品ID"))
        if not pid or pid not in csv_data:
            continue
        d = csv_data[pid]
        vv = int(d["video_views"])
        od = int(d["orders"])
        prod_rows.append({
            "channel_id": cid, "网红": row.get("网红", ""),
            "商品ID": pid, "商品名称": d["name"],
            # 商品类目：若映射表有「商品类目」列则带上，否则空（可在导入表中手动补）
            "商品类目": row.get("商品类目") if "商品类目" in sel_df.columns else "",
            "销售总额": round(d["gmv"], 2), "净销售额": round(d["net_sales"], 2),
            "佣金": round(d["commission"], 2), "观看次数": vv,
            "展示次数": int(d["impressions"]), "点击次数": int(d["clicks"]),
            "订单数": od,
            "转化率": round(d["cvr"], 4), "点击率": round(d["ctr"], 2),
            # 视频转化率 = 订单数 ÷ 视频观看次数 × 100（观看为0记0）
            "视频转化率": round(od / vv * 100, 2) if vv else 0,
        })
        kol_groups.setdefault(cid, {"name": row.get("网红", ""),
                                    "price": float(row.get("报价") or 0),
                                    "rows": []})
        kol_groups[cid]["rows"].append({"pid": pid, **{k: d[k] for k in (
            "gmv", "net_sales", "commission", "video_views", "impressions",
            "clicks", "orders", "cvr", "ctr")}})

    # ---- sheet2 视频分摊：按网红分组整体均摊（共挂商品按视频数平分）+ CPM
    # 注意必须整组传入：逐条单视频调用会让 holder_count 恒为1，
    # 两个视频挂同一商品时 GMV 会被重复归属两份。
    def _s(row, col):
        v = row.get(col)
        return "" if v is None or pd.isna(v) else str(v)

    vids_by_cid = {}
    for _, row in vid_df.iterrows():
        cid = str(row["channel_id"])
        views = row.get("播放量")
        vids_by_cid.setdefault(cid, []).append({
            "video_type": _s(row, "视频类型"),
            "video_url": _s(row, "视频链接"),
            "product_ids": _s(row, "挂的商品"),
            "views": int(views) if views is not None and pd.notna(views) else 0,
        })
    video_rows = []
    for cid, vlist in vids_by_cid.items():
        g = kol_groups.get(cid)
        if not g or not g["rows"]:
            continue
        allocs = PC.allocate_to_videos(vlist, g["rows"], g["price"])
        for v, alloc in zip(vlist, allocs):
            video_rows.append({
                "channel_id": cid, "网红": g["name"],
                "视频链接": v["video_url"], "视频类型": v["video_type"],
                "播放量": v["views"],
                "分摊销售额": float(alloc.get("gmv") or 0),
                "分摊订单": float(alloc.get("orders") or 0),
                "CPM": float(alloc.get("cpm") or 0),
            })

    df_prod = pd.DataFrame(prod_rows or [{}])
    df_vid = pd.DataFrame(video_rows or [{}])
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as w:
        df_prod.to_excel(w, sheet_name=SHEET_PRODUCTS, index=False)
        df_vid.to_excel(w, sheet_name=SHEET_VIDEOS, index=False)

    return {
        "hit_kols": len(kol_groups),
        "hit_products": len(prod_rows),
        "match_products": len(csv_data),
        "miss_products": int((sel_df["商品ID"].map(norm_pid) != "")
                             .sum() - len(prod_rows)),
    }


# ---------------------------------------------------------------------------
# 第3步：网站侧解析导入表（轻量，只读 Excel 按 channel_id 分组）
# ---------------------------------------------------------------------------
def parse_import_excel(data: bytes) -> dict:
    """解析导入表 → {channel_id: {"products": [...], "videos_patch": [...],
    "summary": (clicks, orders, gmv)}}"""
    import io
    import yts_product_csv as PC
    xl = pd.ExcelFile(io.BytesIO(data))
    if SHEET_PRODUCTS not in xl.sheet_names:
        raise ValueError(f"缺少「{SHEET_PRODUCTS}」sheet：请上传匹配后的导入表")
    prod_df = xl.parse(SHEET_PRODUCTS)
    vid_df = (xl.parse(SHEET_VIDEOS)
              if SHEET_VIDEOS in xl.sheet_names else pd.DataFrame())

    col = {"商品ID": ("pid", str), "商品名称": ("name", str),
           "商品类目": ("p_category", str),
           "销售总额": ("gmv", float), "净销售额": ("net_sales", float),
           "佣金": ("commission", float), "观看次数": ("video_views", float),
           "展示次数": ("impressions", float), "点击次数": ("clicks", float),
           "订单数": ("orders", float), "转化率": ("cvr", float),
           "点击率": ("ctr", float)}
    out = {}
    for _, row in prod_df.iterrows():
        cid = str(row.get("channel_id") or "").strip()
        pid = norm_pid(row.get("商品ID"))
        if not cid or not pid:
            continue
        p = {"pid": pid}
        for cname, (code, cast) in col.items():
            if cname in ("商品ID",):
                continue
            try:
                v = row.get(cname)
                p[code] = "" if cast is str and (v is None or pd.isna(v)) \
                    else cast(v if not pd.isna(v) else 0)
            except (TypeError, ValueError):
                continue
        out.setdefault(cid, {"products": [], "videos_patch": [],
                             "summary": [0, 0, 0.0]})
        out[cid]["products"].append(p)
        s = out[cid]["summary"]
        s[0] += int(p.get("clicks") or 0)
        s[1] += int(p.get("orders") or 0)
        s[2] += float(p.get("gmv") or 0)

    # 视频分摊：按 channel_id + 视频链接 组装补丁
    # 「点击」列可选：视频级真实数据导入表带该列时写入视频子表 clicks
    for _, row in vid_df.iterrows():
        cid = str(row.get("channel_id") or "").strip()
        if not cid or cid not in out:
            continue
        out[cid]["videos_patch"].append({
            "video_url": str(row.get("视频链接") or "").strip(),
            "gmv": float(row.get("分摊销售额") or 0),
            "orders": float(row.get("分摊订单") or 0),
            "cpm": float(row.get("CPM") or 0),
            "clicks": float(row.get("点击") or 0),
        })
    return out


def apply_video_patch(videos: list, patch: list) -> list:
    """把视频分摊结果合进现有视频子表行（按视频链接匹配）"""
    by_url = {p["video_url"]: p for p in patch if p["video_url"]}
    merged = []
    for v in videos or []:
        v = dict(v)
        p = by_url.get((v.get("video_url") or "").strip())
        if p:
            if p["gmv"] or p["orders"]:
                v["gmv"] = round(p["gmv"], 2)
                v["orders"] = round(p["orders"], 2)
            if p["cpm"]:
                v["cpm"] = round(p["cpm"], 2)
            if p.get("clicks"):
                v["clicks"] = round(p["clicks"], 2)
        merged.append(v)
    return merged
