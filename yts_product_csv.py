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


# ---------------------------------------------------------------------------
# 多语言表头兼容（2026-09-02）
# YouTube Shopping 后台按登录语言导出：中文表头 / 韩文表头都出现过。
# 旧代码只认中文 → 韩文表头下定位不到表头行，解析直接返回空（全部未匹配）。
# 解法：把韩文列名统一映射回「规范中文名」，下游解析逻辑零改动。
# 注意必须按「整格精确相等」映射，不能用子串替换——
# 「태그가 지정된 SKU ID」含 "SKU ID"，子串替换会把它误改成规范名。
# ---------------------------------------------------------------------------
KR2ZH = {
    # ---- 内容(热门内容/人气页面)报表 ----
    "콘텐츠 제목": "内容标题",
    "콘텐츠 URL": "内容网址",
    "콘텐츠 유형": "内容类型",
    "게시일": "发布日期",
    "채널 이름": "频道名称",
    "채널 URL": "频道网址",
    "채널 구독자": "频道订阅人数",
    "태그가 지정된 SKU ID": "链接的 SKU ID",
    "동영상 조회수": "视频观看次数",
    "노출수": "展示次数",
    "클릭수": "点击次数",
    "주문": "订单数",
    "전환율": "转化率",
    # ---- 商品报表 ----
    "이름": "名称",
    # ---- 两份报表共用 ----
    "총매출": "销售总额",
    "순매출": "净销售额",
    "수수료": "佣金",
    "SKU ID": "SKU ID",
    "링크를 추가한 크리에이터 수": "添加了链接的创作者数量",
    "태그가 지정된 콘텐츠 수": "带有标记的内容数量",
}

# 规范中文名 -> 内部字段名（用于探测"这份CSV到底有哪些指标"）
CANON_FIELDS = {
    "名称": "name", "SKU ID": "sku",
    "销售总额": "gmv", "净销售额": "net_sales", "佣金": "commission",
    "视频观看次数": "video_views", "展示次数": "impressions",
    "点击次数": "clicks", "订单数": "orders", "转化率": "cvr",
    "内容标题": "title", "内容网址": "url", "内容类型": "ctype",
    "发布日期": "pub_date", "频道名称": "channel_name",
    "频道网址": "channel_url", "频道订阅人数": "subscribers",
    "链接的 SKU ID": "tagged_skus",
}

# 商品CSV表头行首列可能的取值（用于定位表头行）
_PRODUCT_FIRST_CELLS = ("名称", "이름")


def _decode(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8-sig", errors="replace")
    return data


def _norm_cell(s) -> str:
    return str(s or "").strip().lstrip("\ufeff").strip()


def _map_header(cells: list) -> list:
    """把表头各格映射为规范中文名；未知列原样保留（不影响取值）"""
    return [KR2ZH.get(_norm_cell(c), _norm_cell(c)) for c in cells]


def _find_header(lines: list, kind: str):
    """在前若干行里定位表头行，返回 (索引, 规范中文表头列表) 或 (None, None)。

    kind="product"：首格是 名称/이름 且含 SKU 列
    kind="content"：含 内容网址/콘텐츠 URL
    """
    for i, l in enumerate(lines[:8]):
        try:
            cells = next(csv.reader(io.StringIO(l)))
        except Exception:
            continue
        if not cells:
            continue
        head = _map_header(cells)
        first = _norm_cell(cells[0])
        if kind == "product":
            if first in _PRODUCT_FIRST_CELLS and "SKU ID" in head:
                return i, head
        else:
            if "内容网址" in head:
                return i, head
    return None, None


def _rewrite_header(lines: list, idx: int) -> list:
    """把第 idx 行替换为规范中文表头行，返回可交给 DictReader 的行列表"""
    cells = next(csv.reader(io.StringIO(lines[idx])))
    out = io.StringIO()
    csv.writer(out, lineterminator="").writerow(_map_header(cells))
    return [out.getvalue()] + lines[idx + 1:]


def detect_product_columns(data) -> set:
    """探测商品CSV实际提供了哪些指标字段（内部字段名集合）。
    用于防止"报表缺列 → 解析成0 → 覆盖宜搭里已有的真实值"。"""
    _idx, head = _find_header(_decode(data).splitlines(), "product")
    if head is None:
        return set()
    return {CANON_FIELDS[h] for h in head if h in CANON_FIELDS}


def detect_content_columns(data) -> set:
    """探测内容CSV实际提供了哪些字段（内部字段名集合）"""
    _idx, head = _find_header(_decode(data).splitlines(), "content")
    if head is None:
        return set()
    return {CANON_FIELDS[h] for h in head if h in CANON_FIELDS}


def parse_product_csv(data) -> dict:
    """解析全量商品 CSV，返回 {纯商品ID: {name,gmv,net_sales,commission,
    video_views,impressions,clicks,orders,cvr,ctr}}。

    兼容中文/韩文表头；表头行动态定位（跳过 '名称：'/'时间段：' 等前置说明行）。

    【缺列语义 2026-09-02】报表若不含某列（如「최다 판매 제품」只有6列，
    无 展示次数/点击次数/视频观看次数/转化率），该字段返回 **None** 而非 0，
    让调用方能区分「报表没给」和「真实值就是0」，避免用0覆盖宜搭已有数据。
    """
    lines = _decode(data).splitlines()
    header_idx, head = _find_header(lines, "product")
    if header_idx is None:
        return {}
    have = {CANON_FIELDS[h] for h in head if h in CANON_FIELDS}

    def _opt(row, col):
        """列存在→取数值；列不存在→None（不污染成0）。
        col 传规范中文列名，内部转成字段名再与 have 比对。"""
        if CANON_FIELDS.get(col) not in have:
            return None
        return _f(row.get(col))

    reader = csv.DictReader(io.StringIO("\n".join(
        _rewrite_header(lines, header_idx))))
    out = {}
    for row in reader:
        pid = _norm_pid(row.get("SKU ID") or "")
        if not pid:
            continue
        impressions = _opt(row, "展示次数")
        clicks = _opt(row, "点击次数")
        video_views = _opt(row, "视频观看次数")
        orders = _opt(row, "订单数")
        cvr = _opt(row, "转化率")
        out[pid] = {
            "name": (row.get("名称") or "").strip()[:400],
            "gmv": _f(row.get("销售总额")),
            "net_sales": _f(row.get("净销售额")),
            "commission": _f(row.get("佣金")),
            "video_views": video_views,
            "impressions": impressions,
            "clicks": clicks,
            "orders": orders,
            "cvr": cvr,
            # 点击率：点击÷展示（任一缺失或展示为0 → None，不写0）
            "ctr": round(clicks / impressions * 100, 2)
            if (impressions and clicks is not None) else None,
            # 视频转化率：订单÷视频观看（同上）
            "video_cvr": round(orders / video_views * 100, 2)
            if (video_views and orders is not None) else None,
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

    def _z(v):
        """None（报表缺列）→ 0，避免旧均摊路径算出 None"""
        return 0.0 if v is None else float(v)

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
        gmv = sum(_z(prods_by_id[p]["gmv"]) / holder_count[p]
                  for p in pids if p in prods_by_id and holder_count.get(p))
        orders = sum(_z(prods_by_id[p]["orders"]) / holder_count[p]
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
    返回 (clicks, orders, gmv)。报表缺列(None)按0计，不参与汇总。"""
    def _z(v):
        return 0.0 if v is None else float(v)
    clicks = sum(_z(r.get("clicks")) for r in product_rows)
    orders = sum(_z(r.get("orders")) for r in product_rows)
    gmv = sum(_z(r.get("gmv")) for r in product_rows)
    return int(clicks), int(orders), round(gmv, 2)
