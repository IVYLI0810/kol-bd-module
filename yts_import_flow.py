#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 流程导入：万能模板 + 表头识别 + 字段推导 + 频道ID反查

- 模板列覆盖全生命周期：运营只填到当前进度，空着=还没到
- 解析时按表头子串匹配，团队现有进度表（频道名称/频道链接/负责人/归属月份…）
  也能直接上传，识别到几列映射几列
- 频道ID：云端反查 YouTube（公司网连不上时自动兜底为 HDL_ 前缀ID，预览里标注）
"""
import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

NOW_YEAR = datetime.now().year

# key, 模板表头, 必填, 匹配子串（小写）
COLS = [
    ("channel_url",  "频道链接*",        True,  ["频道链接", "channel_url", "youtube"]),
    ("channel_name", "频道名称*",        True,  ["频道名称", "昵称", "channel_name"]),
    ("recruiter",    "负责人*",          True,  ["负责人", "挖掘人", "recruiter"]),
    ("plan_month",   "归属月份",         False, ["归属月份", "计划上线", "plan_month"]),
    ("category",     "核心类目",         False, ["核心类目", "类目", "垂类", "category"]),
    ("email",        "联系邮箱",         False, ["邮箱", "email"]),
    ("emailed",      "已发邮件(Y/N)",    False, ["已发邮件"]),
    ("negotiating",  "洽谈中(Y/N)",      False, ["洽谈中", "洽谈"]),
    ("guideline",    "Guideline已发(Y/N)", False, ["guideline", "guide"]),
    ("contract",     "合同已签(Y/N)",    False, ["合同"]),
    ("gmc",          "GMC校验(Y/N)",     False, ["gmc"]),
    ("ordered",      "已下单(Y/N)",      False, ["下单"]),
    ("received",     "已收货(Y/N)",      False, ["收货"]),
    ("shoot_status", "拍摄状态",         False, ["拍摄"]),
    ("video_link",   "上传视频链接",     False, ["视频链接", "video_link"]),
    ("submit_deadline", "视频上传时间",  False, ["视频上传时间", "交稿截止", "上传时间"]),
    ("audit",        "审核结果",         False, ["审核结果", "审核状态"]),
    ("recheck",      "复审链接",         False, ["复审"]),
    ("video_views",  "播放量",           False, ["播放"]),
    ("video_likes",  "点赞数",           False, ["点赞"]),
    ("video_comments", "评论数",         False, ["评论"]),
    ("product_views", "点击量",          False, ["点击"]),
    ("orders",       "成交量",           False, ["成交量", "成交"]),
    ("gmv",          "GMV",              False, ["gmv"]),
    ("closed",       "已闭环(Y/N)",      False, ["闭环"]),
    ("notes",        "备注",             False, ["备注", "notes"]),
]

_EXAMPLES = [
    # 刚开始（挖掘/洽谈阶段，不填归属月份）
    ["https://youtube.com/@example_beauty", "예시채널A", "艾薇李", "",
     "뷰티", "a@example.com", "Y", "Y", "", "", "", "", "", "", "", "", "", "",
     "", "", "", "", "", "", "", "新洽谈，待确认合作"],
    # 履约中（三分支完成、已下单）
    ["https://youtube.com/@example_home", "예시채널B", "崔士杰", "2026-09",
     "홈&가든", "", "Y", "", "Y", "Y", "Y", "Y", "Y", "拍摄中", "",
     "2026-09-21", "", "", "", "", "", "", "", "", "", ""],
    # 已闭环（回填数据）
    ["https://youtube.com/@example_pet", "예시채널C", "梁泳妍", "2026-08",
     "애완동물", "", "Y", "Y", "Y", "Y", "Y", "Y", "Y", "已完成",
     "https://youtube.com/shorts/xxx", "2026-08-21", "已通过", "",
     120000, 5400, 210, 8000, 96, 2100, "Y", "闭环示例"],
]


def build_template_bytes() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "流程导入"
    ws.append([c[1] for c in COLS])
    for row in _EXAMPLES:
        ws.append(row)
    ws2 = wb.create_sheet("填写说明")
    for line in [
        "带*为必填；Y/N 列填 Y 或留空；归属月份形如 2026-09 或 9月。",
        "只填到当前进度即可：刚洽谈就只填前几列，已闭环就把数据列补满。",
        "团队现有进度表也可直接上传，能识别的列（频道名称/频道链接/负责人/"
        "归属月份/视频上传时间/核心类目等）会自动映射。",
    ]:
        ws2.append([line])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
def yn(v) -> bool:
    return str(v or "").strip().lower() in ("y", "yes", "是", "1", "true", "✅")


def norm_month(v) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.match(r"^(20\d{2})[-年/.](\d{1,2})月?$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{1,2})月$", s)
    if m:
        return f"{NOW_YEAR}-{int(m.group(1)):02d}"
    return s


def norm_date(v) -> str:
    """Excel 日期格/文本 → YYYY-MM-DD"""
    if v is None or str(v).strip() == "":
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.match(r"^(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def _num(v):
    try:
        f = float(str(v).replace(",", "").strip())
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return None


def _match_header(cell) -> str:
    s = str(cell or "").strip().lower().replace("*", "")
    if not s:
        return ""
    for key, _hdr, _req, subs in COLS:
        for sub in subs:
            if sub.lower() in s:
                return key
    return ""


def parse_workbook(data: bytes):
    """返回 (rows, issues)：rows=[{key: 原始值}], issues=[str]"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active
    grid = [[c.value for c in row] for row in ws.iter_rows(max_row=15)]
    head_idx, col_map = -1, {}
    for i, row in enumerate(grid):
        mapped = {}
        for j, cell in enumerate(row):
            k = _match_header(cell)
            if k and k not in mapped:
                mapped[k] = j
        if "channel_url" in mapped and "channel_name" in mapped:
            head_idx, col_map = i, mapped
            break
    if head_idx < 0:
        return [], ["未识别到表头：请至少包含「频道链接」「频道名称」两列，"\
                    "或直接使用下载的模板"]
    rows, issues = [], []
    # 遍历表头之后的所有行
    for row in list(ws.iter_rows(min_row=head_idx + 2)):
        vals = [c.value for c in row]
        rec = {}
        for key, j in col_map.items():
            if j < len(vals) and vals[j] not in (None, ""):
                rec[key] = vals[j]
        url = str(rec.get("channel_url") or "").strip().lower()
        name = str(rec.get("channel_name") or "").strip()
        if url and not url.startswith(("http", "www.", "@", "youtube",
                                       "m.youtube")):
            rec.pop("channel_url", None)
            url = ""
        if not url and not name:
            continue
        if not url:
            issues.append(f"行「{name}」缺频道链接，已跳过")
            continue
        if not rec.get("recruiter"):
            issues.append(f"行「{name}」缺负责人，已跳过")
            continue
        rows.append(rec)
    return rows, issues


# ---------------------------------------------------------------------------
def _fetch_channel_id(url: str):
    try:
        r = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        t = r.text
    except Exception:
        return None
    m = re.search(r'"channelId"\s*:\s*"(UC[\w-]{20,})"', t) \
        or re.search(r"channelId=(UC[\w-]{20,})", t) \
        or re.search(r'itemprop="identifier"[^>]*content="(UC[\w-]{20,})"', t)
    return m.group(1) if m else None


def _fallback_id(url: str) -> str:
    m = re.search(r"youtube\.com/@([\w.-]+)", url) \
        or re.search(r"youtube\.com/(?:channel/|c/)?([\w.-]+)", url)
    slug = m.group(1) if m else re.sub(r"\W+", "_", url)[-24:]
    return "HDL_" + slug


def resolve_ids(rows: list, existing_by_url: dict):
    """url -> (channel_id, resolved:bool)；已有记录复用其ID"""
    out = {}
    todo = []
    for r in rows:
        url = str(r["channel_url"]).strip()
        if url in existing_by_url:
            out[url] = (existing_by_url[url], True)
        else:
            todo.append(url)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for url, cid in zip(todo, ex.map(_fetch_channel_id, todo)):
            out[url] = (cid or _fallback_id(url), bool(cid))
    return out


# ---------------------------------------------------------------------------
def derive_record(raw: dict, channel_id: str) -> dict:
    rec = {
        "channel_id": channel_id,
        "channel_url": str(raw.get("channel_url", "")).strip(),
        "channel_name": str(raw.get("channel_name", "")).strip(),
        "recruiter": str(raw.get("recruiter", "")).strip(),
    }
    plan = norm_month(raw.get("plan_month"))
    if plan:
        rec["plan_month"] = plan
    for key in ("category", "email", "video_link", "recheck"):
        if raw.get(key):
            rec[key if key != "recheck" else "recheck_video_url"] = \
                str(raw[key]).strip()
    if raw.get("email"):
        rec["email"] = str(raw["email"]).strip()
    if yn(raw.get("emailed")):
        rec["email_status"] = "已发送"
    if yn(raw.get("negotiating")):
        rec["stage"] = "洽谈中"
    if yn(raw.get("guideline")):
        rec["guideline_status"] = "已发送"
    if yn(raw.get("contract")):
        rec["contract_status"] = "已签署"
    if yn(raw.get("gmc")):
        rec["gmc_status"] = "校验通过"
    if yn(raw.get("ordered")):
        rec["order_status"] = "已下单"
    if yn(raw.get("received")):
        rec["order_status"] = "已收货"
    if raw.get("shoot_status"):
        rec["shoot_status"] = str(raw["shoot_status"]).strip()
    dl = norm_date(raw.get("submit_deadline"))
    if dl:
        rec["submit_deadline"] = dl
    audit = str(raw.get("audit") or "").strip()
    if audit in ("已通过", "未通过", "待审核", "复审中"):
        rec["audit_status"] = audit
    elif audit in ("驳回", "不通过"):
        rec["audit_status"] = "未通过"
    elif raw.get("video_link"):
        rec["audit_status"] = "待审核"
    for key in ("video_views", "video_likes", "video_comments",
                "product_views", "orders", "gmv"):
        n = _num(raw.get(key))
        if n is not None:
            rec[key] = n
    if yn(raw.get("closed")):
        rec["stage"] = "已完成"
    elif plan:
        rec["stage"] = "已确认"
    if raw.get("notes"):
        rec["notes"] = str(raw["notes"]).strip()
    return rec
