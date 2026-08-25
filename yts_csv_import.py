#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 分析模块「一键直导」（2026-08-26 重构）

替代旧的"导出映射表 → 离线匹配 → 上传导入表"三步流程，改为网站一条龙：

    上传 2 个 YouTube Shopping 后台原始 CSV
        ① 热门内容 CSV   → 视频维度（按视频链接匹配）
        ② 链接商品 CSV   → 商品维度（按 SKU ID 匹配）
    → 先调 YouTube API 强制重抓 播放/点赞/评论
    → 再写入 CSV 的 点击/订单/GMV（视频）与商品全字段
    → 网红维度 = 视频维度聚合（呈现层实时计算，无需单独导入）
    → 返回三维度「未匹配清单」供页面展示

三个维度相互独立，谁也不推谁（不再做商品均摊推视频、视频推网红）。
"""
import csv
import io
import re

# 复用既有的商品 CSV 解析与视频ID提取（已在线上验证）
import yts_product_csv as PC
import yts_yt_stats as YT


# ---------------------------------------------------------------------------
# 视频链接归一化
# ---------------------------------------------------------------------------
def _vid(url: str) -> str:
    """任意形态 YouTube 链接 → 11位 videoId（提取不到返回 ''）"""
    return YT.extract_video_id(url)


# ---------------------------------------------------------------------------
# 解析两个原始 CSV
# ---------------------------------------------------------------------------
def parse_content_csv(data, wanted_ids=None):
    """解析「热门内容」CSV → {videoId: {clicks, orders, gmv, title}}

    只保留 needed（系统已登记）的视频，21万行大文件也只挑出相关的几十行。
    表头动态定位（前5行里找含「内容网址」的行）。
    """
    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data
    lines = text.splitlines()
    header_idx = None
    for i, l in enumerate(lines[:5]):
        if "内容网址" in l:
            header_idx = i
            break
    if header_idx is None:
        return {}
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    out = {}
    for row in reader:
        vid = _vid(row.get("内容网址") or "")
        if not vid:
            continue
        if wanted_ids is not None and vid not in wanted_ids:
            continue
        out[vid] = {
            "clicks": PC._f(row.get("点击次数")),
            "orders": PC._f(row.get("订单数")),
            "gmv": PC._f(row.get("销售总额")),
            "title": (row.get("内容标题") or "").strip()[:60],
        }
    return out


def parse_product_csv(data):
    """解析「链接商品」CSV → {pid: {...}}（直接复用既有解析器）"""
    return PC.parse_product_csv(data)


# ---------------------------------------------------------------------------
# 主流程：API 重抓 + CSV 匹配 + 写入 + 未匹配报告
# ---------------------------------------------------------------------------
def run_direct_import(content_bytes, product_bytes, closed_recs, store,
                      progress_cb=None):
    """一键直导。closed_recs: 已闭环记录列表。

    progress_cb(stage_text, done, total) 用于页面进度条（可为 None）。

    返回报告 dict：
      {
        "api_ok": 抓到API的视频数, "api_fail": [(网红, 链接)],
        "video_matched": n, "video_unmatched": [(网红, 链接)],
        "prod_matched": n, "prod_unmatched": [(网红, 商品ID)],
        "kol_empty": [网红...],          # 无任何视频匹配的网红（网红维度为0）
        "written_kols": n,
        "has_api_key": bool,
      }
    """
    def _prog(txt, done, total):
        if progress_cb:
            progress_cb(txt, done, total)

    # ---- 0) 解析两个 CSV ----
    # 先收集系统已登记的全部 videoId，热门内容大CSV只挑相关行
    wanted = set()
    for r in closed_recs:
        for v in r.get("videos") or []:
            vid = _vid(v.get("video_url") or "")
            if vid:
                wanted.add(vid)
    content_map = parse_content_csv(content_bytes, wanted_ids=wanted) \
        if content_bytes else {}
    product_map = parse_product_csv(product_bytes) if product_bytes else {}

    has_api_key = bool(YT.get_key())
    content_provided = content_bytes is not None
    product_provided = product_bytes is not None
    report = {
        "api_ok": 0, "api_fail": [],
        "video_matched": 0, "video_unmatched": [],
        "prod_matched": 0, "prod_unmatched": [],
        "kol_empty": [], "written_kols": 0,
        "has_api_key": has_api_key,
        "content_provided": content_provided,
        "product_provided": product_provided,
    }

    total = len(closed_recs)
    for i, r in enumerate(closed_recs):
        _prog(f"处理 {r['name']}（{i + 1}/{total}）", i, total)
        cid = r["collab_id"]
        price_usd = PC.krw_to_usd(r.get("price"))
        vids = r.get("videos") or []

        # ---------------- 视频维度 ----------------
        new_videos = []
        kol_matched = 0
        for v in vids:
            v = dict(v)
            url = (v.get("video_url") or "").strip()
            vid = _vid(url)

            # ① API 强制重抓 播放/点赞/评论（不用旧缓存）
            if has_api_key and url:
                stats = YT.fetch_video_stats(url, force=True)
                if stats:
                    v["views"] = int(stats.get("views") or 0)
                    v["likes"] = int(stats.get("likes") or 0)
                    v["comments"] = int(stats.get("comments") or 0)
                    report["api_ok"] += 1
                else:
                    report["api_fail"].append((r["name"], url))

            # ② 热门内容CSV 匹配 点击/订单/GMV（整行真实数据，不均摊）
            hit = content_map.get(vid) if vid else None
            if hit:
                v["clicks"] = round(hit["clicks"], 2)
                v["orders"] = round(hit["orders"], 2)
                v["gmv"] = round(hit["gmv"], 2)
                # ③ CPM = 报价($) ÷ 播放(API) × 1000（播放为0记0）
                views = int(v.get("views") or 0)
                v["cpm"] = round(price_usd / views * 1000, 2) \
                    if (price_usd and views) else 0
                report["video_matched"] += 1
                kol_matched += 1
            elif content_provided:
                report["video_unmatched"].append((r["name"], url))
            new_videos.append(v)

        if vids and content_provided and kol_matched == 0:
            report["kol_empty"].append(r["name"])

        # ---------------- 商品维度 ----------------
        new_products = []
        seen_pids = set()
        # 保留已有的商品类目（手动维护的字段，导入不覆盖成空）
        existing_cat = {str(p.get("pid") or ""): p.get("p_category") or ""
                        for p in r.get("products") or []}
        for item in r.get("product_list") or []:
            pid = PC._norm_pid(item)
            if not pid or pid in seen_pids:
                continue
            seen_pids.add(pid)
            d = product_map.get(pid)
            if not d:
                if product_provided:
                    report["prod_unmatched"].append((r["name"], pid))
                continue
            imp = d["impressions"]
            clicks = d["clicks"]
            vv = d["video_views"]
            od = d["orders"]
            new_products.append({
                "pid": pid, "name": d["name"],
                "p_category": existing_cat.get(pid, ""),
                "gmv": round(d["gmv"], 2),
                "net_sales": round(d["net_sales"], 2),
                "commission": round(d["commission"], 2),
                "video_views": int(vv), "impressions": int(imp),
                "clicks": int(clicks), "orders": int(od),
                "cvr": round(d["cvr"], 4),
                "ctr": round(clicks / imp * 100, 2) if imp else 0.0,
                "video_cvr": round(od / vv * 100, 2) if vv else 0.0,
            })
            report["prod_matched"] += 1

        # ---------------- 写入宜搭（每网红各 1 次） ----------------
        wrote = False
        if vids:
            store.save_videos(cid, new_videos)
            wrote = True
        if new_products:
            store.save_products(cid, new_products)
            wrote = True
        if wrote:
            report["written_kols"] += 1

    _prog("完成", total, total)
    return report
