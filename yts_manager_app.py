#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网红管理系统 - 管理者看板（独立分支网站，2026-08-26）

仅李鑫 / 艾薇李可见（Secrets: MANAGER_PASSWORD 专用密码门）。
功能：
  - 按组员分组，一览每位网红的阶段（已发邮件/洽谈中/履约中+进度/已闭环）
  - 字段：头像(点击跳主页) / 双垂类 / 粉丝数 / 月份 / 报价($) /
          近10条视频均播 / 近10条中位播
  - 已闭环网红：合作视频逐条跳转按钮
  - 筛选：按阶段 + 按组员
  - 近10条数据：YouTube API 抓取（每人3配额单位），7天缓存，可手动强刷
"""
import html
import os
import time
from datetime import datetime

import streamlit as st

from yts_yida_store import get_yts_store, YidaFetchError
import yts_theme as T
import yts_channel_stats as CS

st.set_page_config(page_title="YTS 매니저 대시보드 · YTS 管理看板",
                   page_icon="👑", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(T.THEME_CSS, unsafe_allow_html=True)

esc = html.escape
USD_RATE = float(os.environ.get("USD_RATE", "1538"))

STAGES = ["已发邮件", "洽谈中", "履约中", "已闭环"]
STAGE_COLOR = {"已发邮件": "c-gray", "洽谈中": "c-amber",
               "履约中": "c-purple", "已闭环": "c-green"}


# ============================ 管理者密码门 ============================
def _manager_password() -> str:
    try:
        return str(st.secrets.get("MANAGER_PASSWORD", "") or "")
    except Exception:
        return os.environ.get("MANAGER_PASSWORD", "")


def require_manager():
    """管理者专用门禁：session → cookie → 登录页（30天免重复）"""
    import hashlib
    import hmac
    from streamlit import components as comp

    pwd = _manager_password()
    if not pwd:
        st.error("⚠️ 未配置管理者密码（Secrets: MANAGER_PASSWORD），"
                 "看板暂不可用。请联系配置人。")
        st.stop()

    def _token(p):
        return hmac.new(b"yts-manager", p.encode(), hashlib.sha256).hexdigest()

    if st.session_state.get("mgr_authed"):
        return
    # cookie 恢复
    try:
        cookies = st.context.cookies
    except Exception:
        cookies = {}
    if cookies.get("yts_mgr_auth") == _token(pwd):
        st.session_state["mgr_authed"] = True
        return
    # 登录页
    st.markdown('<div style="height:14vh"></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown('<div style="text-align:center;font-size:40px">👑</div>',
                    unsafe_allow_html=True)
        st.markdown('<div style="text-align:center;font-size:20px;font-weight:800;'
                    'margin-bottom:4px">YTS 管理看板</div>'
                    '<div style="text-align:center;color:#86868b;font-size:13px;'
                    'margin-bottom:20px">관리자 전용 · 管理者专用</div>',
                    unsafe_allow_html=True)
        inp = st.text_input("管理者密码", type="password", key="mgr_pwd",
                            label_visibility="collapsed",
                            placeholder="관리자 비밀번호 입력 · 输入管理者密码")
        if st.button("进入看板", use_container_width=True, type="primary") and inp:
            if hmac.compare_digest(inp, pwd):
                st.session_state["mgr_authed"] = True
                tok = _token(pwd)
                comp.v1.html(
                    f"<script>document.cookie='yts_mgr_auth={tok};"
                    f"max-age={30*24*3600};path=/';"
                    f"try{{window.parent.document.cookie='yts_mgr_auth={tok};"
                    f"max-age={30*24*3600};path=/';}}catch(e){{}}</script>",
                    height=0)
                st.rerun()
            else:
                st.error("密码错误，请重试")
    st.stop()


require_manager()
store = get_yts_store()


# ============================ 阶段与进度 ============================
def _node(c) -> str:
    """履约中网红的当前节点（与主站活动模块口径一致）"""
    if c["is_closed"]:
        return "已闭环"
    if not all(c["branches"].values()):
        miss = [k for k, v in c["branches"].items() if not v]
        name = {"guideline": "指引", "contract": "合同", "gmc": "GMC"}
        return "三分支待办:" + "/".join(name.get(m, m) for m in miss)
    if not c["order_done"]:
        return "待下单"
    if not c["received"]:
        return "待收货"
    if c["shoot_status"] != "已完成":
        return "拍摄中" if c["shoot_status"] == "拍摄中" else "待拍摄"
    if not c["video_url"]:
        return "待提交视频"
    rs = c["review_status"]
    if rs == "待审核":
        return "待审核"
    if rs == "已驳回":
        return "已驳回"
    if rs == "复审中":
        return "复审中"
    if rs in ("已通过", "复审通过"):
        return "待闭环"
    return "待提交视频"


def _fmt_num(n) -> str:
    n = int(n or 0)
    if n >= 100000000:
        return f"{n/100000000:.1f}亿"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:,}"


# ============================ 数据装载 ============================
def _norm_pool(c) -> dict:
    """挖掘池卡片 → 与履约记录同构的字段名（channel_id/channel_url/...）"""
    return {
        "channel_id": c.get("id") or "",
        "name": c.get("name") or "",
        "channel_url": c.get("url") or "",
        "followers": c.get("followers") or 0,
        "category": c.get("category") or "",
        "sales_category": c.get("sales_category") or "",
        "avatar": c.get("avatar") or "",
        "recruiter": c.get("recruiter") or "",
        "plan_month": "",
        "price": 0,
        "videos": [],
    }


_PRIO = {"已闭环": 4, "履约中": 3, "洽谈中": 2, "已发邮件": 1}


@st.cache_data(ttl=300, show_spinner=False)
def load_all():
    """四阶段全量记录（宜搭），5分钟缓存。
    同一频道可能同时在挖掘池(已发邮件)和活动(履约中)，按阶段优先级去重。"""
    pool = store.list_pool()                      # 挖掘池（含已发邮件标记）
    negs = store.list_negotiating()               # 洽谈中
    fuls = store.list_fulfilling()                # 履约中（含已闭环）
    seen = {}  # key -> (priority, row)

    def add(stage, c):
        key = c.get("channel_id") or c.get("name") or ""
        p = _PRIO[stage]
        if key in seen and seen[key][0] >= p:
            return
        seen[key] = (p, {"stage": stage, "c": c})

    for c in fuls:
        add("已闭环" if c["is_closed"] else "履约中", c)
    for c in negs:
        add("洽谈中", c)
    for c in pool:
        if not c.get("emailed"):          # 未发邮件的不纳入看板
            continue
        add("已发邮件", _norm_pool(c))
    return [v[1] for v in seen.values()]


try:
    rows = load_all()
except YidaFetchError as e:
    st.error(f"宜搭数据加载失败：{e}")
    st.stop()

# 组员列表（按记录里的 recruiter 汇总）
members = sorted({(r["c"].get("recruiter") or "").strip()
                  for r in rows if (r["c"].get("recruiter") or "").strip()})

# ============================ 顶部：筛选 + 汇总 ============================
st.markdown(T.header("管理看板",
                     f"管理者视角 · 共 {len(rows)} 位网红 · "
                     f"数据时间 {datetime.now().strftime('%m-%d %H:%M')}"),
            unsafe_allow_html=True)

f1, f2, f3 = st.columns([2.4, 1.8, 1.4])
with f1:
    stage_filter = st.pills("阶段筛选", ["全部"] + STAGES, default="全部",
                            key="mgr_stage")
with f2:
    member_filter = st.selectbox("组员筛选", ["全部组员"] + members, key="mgr_member")
with f3:
    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
    if st.button("🔄 强刷近10条", key="mgr_force10", use_container_width=True,
                 help="无视7天缓存，重新调 YouTube API 抓全部网红的最新10条视频"
                      "（每人约3配额单位）"):
        st.session_state["mgr_force10_ts"] = time.time()
        st.session_state["mgr_force10"] = True
        st.rerun()

# 汇总卡
stage_cnt = {s: 0 for s in STAGES}
for r in rows:
    stage_cnt[r["stage"]] += 1
st.markdown(T.stats_row([
    ("📧 已发邮件", stage_cnt["已发邮件"], "c-gray"),
    ("💬 洽谈中", stage_cnt["洽谈中"], "c-amber"),
    ("🚀 履约中", stage_cnt["履约中"], "c-purple"),
    ("✅ 已闭环", stage_cnt["已闭环"], "c-green"),
]), unsafe_allow_html=True)

# ============================ 近10条：自动补抓 ============================
visible = rows
if stage_filter != "全部":
    visible = [r for r in visible if r["stage"] == stage_filter]
if member_filter != "全部组员":
    visible = [r for r in visible
               if (r["c"].get("recruiter") or "").strip() == member_filter]

force_all = st.session_state.pop("mgr_force10", False)
_cache_now = {} if force_all else CS._load_cache()
need = []
for r in visible:
    cid = r["c"].get("channel_id") or ""
    if not cid.startswith("UC"):
        continue
    hit = _cache_now.get(cid)
    if force_all or not hit or time.time() - hit.get("ts", 0) > CS.TTL:
        need.append(cid)
need = list(dict.fromkeys(need))  # 去重保序

if need:
    if not CS.YT.get_key():
        st.warning("⚠️ 未配置 YouTube API Key（Secrets: YOUTUBE_API_KEY），"
                   "近10条数据无法抓取。")
    else:
        bar = st.progress(0, text=f"正在抓取近10条视频数据 0/{len(need)}…")
        for i, cid in enumerate(need, 1):
            CS.fetch_recent10(cid, force=force_all)
            bar.progress(int(i * 100 / len(need)),
                         text=f"正在抓取近10条视频数据 {i}/{len(need)}…")
        bar.empty()
        load_all.clear()

# ============================ 表格渲染 ============================
REC10_CACHE = CS._load_cache()  # 整页只读一次缓存文件


def _row_cells(r) -> list:
    c = r["c"]
    stage = r["stage"]
    cid = c.get("channel_id") or ""
    home = c.get("channel_url") or (f"https://www.youtube.com/channel/{cid}"
                                    if cid else "")
    name = esc(c.get("name") or cid or "-")
    # 头像（近10条抓取时顺带拿到）
    rec10 = REC10_CACHE.get(cid) or {}
    avatar = rec10.get("avatar") or c.get("avatar") or ""
    av_html = (f'<img src="{esc(avatar)}" style="width:30px;height:30px;'
               f'border-radius:50%;vertical-align:middle;margin-right:8px">'
               if avatar else
               '<span style="display:inline-block;width:30px;height:30px;'
               'border-radius:50%;background:#e8e8ed;vertical-align:middle;'
               'margin-right:8px"></span>')
    name_cell = (f'<a href="{esc(home)}" target="_blank" '
                 f'style="text-decoration:none;color:inherit">{av_html}'
                 f'<b>{name}</b></a>' if home else f"{av_html}<b>{name}</b>")
    # 阶段 + 进度
    if stage == "履约中":
        stage_cell = (f'{T.badge(stage)}<div style="font-size:11px;'
                      f'color:#86868b;margin-top:2px">{esc(_node(c))}</div>')
    else:
        stage_cell = T.badge(stage)
    # 双垂类
    cat = " · ".join(t for t in ((c.get("category") or "").strip(),
                                 (c.get("sales_category") or "").strip()) if t) or "-"
    # 报价（韩币 → 美金，与分析模块同口径）
    price_krw = float(c.get("price") or 0)
    price_cell = (f"${price_krw/USD_RATE:,.0f}"
                  f'<div style="font-size:10px;color:#b0b0b5">'
                  f'₩{price_krw:,.0f}</div>' if price_krw else "-")
    # 近10条
    avg = _fmt_num(rec10.get("avg")) if rec10 else "-"
    med = _fmt_num(rec10.get("median")) if rec10 else "-"
    # 合作视频（每条一个跳转按钮）
    vids = [v for v in (c.get("videos") or []) if v.get("video_url")]
    if vids:
        vid_cell = " ".join(
            f'<a href="{esc(v["video_url"])}" target="_blank" '
            f'style="display:inline-block;padding:2px 8px;margin:1px 3px 1px 0;'
            f'background:#f0f0f5;border-radius:10px;font-size:11px;'
            f'text-decoration:none;color:#1d1d1f">🎬 {i}</a>'
            for i, v in enumerate(vids, 1))
    else:
        vid_cell = '<span style="color:#c7c7cc">-</span>'
    return [name_cell, stage_cell, esc(cat),
            f"<span class='num'>{_fmt_num(c.get('followers'))}</span>",
            esc(str(c.get("plan_month") or "-")),
            f"<span class='num'>{price_cell}</span>",
            f"<span class='num'>{avg}</span>",
            f"<span class='num'>{med}</span>",
            vid_cell]


HEADERS = ["网红（点头像跳主页）", "阶段/进度", "双垂类", "粉丝数", "月份",
           "报价", "近10条均播", "近10条中位播", "合作视频"]

if not visible:
    st.markdown(T.empty_hint("当前筛选条件下没有网红"), unsafe_allow_html=True)
else:
    # 按组员分组
    groups = {}
    for r in visible:
        g = (r["c"].get("recruiter") or "").strip() or "（未分配）"
        groups.setdefault(g, []).append(r)
    order = {s: i for i, s in enumerate(STAGES)}
    for g in sorted(groups, key=lambda x: -len(groups[x])):
        grp = sorted(groups[g], key=lambda r: order.get(r["stage"], 9))
        g_cnt = {s: sum(1 for r in grp if r["stage"] == s) for s in STAGES}
        summary = " · ".join(f"{s} {n}" for s, n in g_cnt.items() if n)
        st.markdown(T.sub(f"🧑 {esc(g)}　"
                          f'<span style="font-size:12px;color:#86868b;'
                          f'font-weight:500">{summary}</span>'),
                    unsafe_allow_html=True)
        T.component_html(T.table(HEADERS, [_row_cells(r) for r in grp],
                                 wrap=False),
                         height=72 + len(grp) * 46)

st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
st.caption("📌 近10条数据 7 天自动缓存；「强刷近10条」可立即拉最新。"
           "报价按 ₩1 = $1/1538 折算。")
