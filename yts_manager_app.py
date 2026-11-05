#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网红管理系统 - 管理者看板（独立分支网站，2026-08-26）

仅李鑫 / 艾薇李可见（Secrets: MANAGER_PASSWORD 专用密码门）。
功能：
  - 按组员分组，一览每位网红的阶段（已发邮件/洽谈中/履约中+进度/已闭环）
  - 字段：头像(点击跳主页) / 双垂类 / 粉丝数 / 月份 / 报价($) /
          近10条视频均播 / 近10条中位播
  - 已闭环网红：合作视频逐条跳转按钮 + CPM/ROI（宜搭视频子表现算，分析页同口径）
          + 商品跳转按钮（悬停看商品名+GMV）
  - 筛选：按阶段 + 按组员
  - 近10条数据：YouTube API 抓取（每人3配额单位），7天缓存，可手动强刷
"""
import html
import os
import re
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


# ============================ CPM / ROI（与分析页同口径） ============================
def _kol_metrics(c) -> dict:
    """指标全部来自宜搭记录本身（视频子表加总），口径与分析页一致：
    ROI = 总GMV($) ÷ 报价($)；CPM = 报价($) ÷ 总播放 × 1000。
    无视频子表的老数据回退主记录指标。"""
    vids = c.get("videos") or []
    tot_views = sum(int(v.get("views") or 0) for v in vids)
    tot_gmv = sum(float(v.get("gmv") or 0) for v in vids)
    if not vids:  # 老数据兜底
        tot_views = int(c.get("video_views") or 0)
        tot_gmv = float(c.get("gmv") or 0)
    price_usd = float(c.get("price") or 0) / USD_RATE
    return {
        "views": tot_views,
        "gmv": tot_gmv,
        "price_usd": price_usd,
        "cpm": round(price_usd / tot_views * 1000, 2)
        if (price_usd and tot_views) else 0,
        "roi": round(tot_gmv / price_usd, 2) if price_usd else 0,
    }


def _product_links(c) -> list:
    """商品跳转按钮：优先商品子表（有GMV可悬停展示），
    无子表时回退解析选品清单里的商品链接。返回 [(url, 悬停说明)] 去重。"""
    out = []
    for p in (c.get("products") or []):
        pid = str(p.get("pid") or "").strip()
        if not pid:
            continue
        gmv = float(p.get("gmv") or 0)
        tip = (p.get("name") or pid) + (f" · GMV ${gmv:,.0f}" if gmv else "")
        out.append((f"https://ko.aliexpress.com/item/{pid}.html", tip))
    if not out:
        for line in str(c.get("product_list") or "").splitlines():
            m = re.search(r"/item/(\d+)", line)
            if m:
                out.append((f"https://ko.aliexpress.com/item/{m.group(1)}.html",
                            line.strip()))
    seen, res = set(), []
    for u, t in out:
        if u not in seen:
            seen.add(u)
            res.append((u, t))
    return res


def recruiter_overview_rows(rows) -> list:
    """组员维度概览：每位组员一行——总数 / 各阶段 / 逾期 / 平均CPM·ROI。
    逾期 = 履约中且已过提交截止日仍未闭环。CPM/ROI 只对有数据的行取均值。"""
    today = datetime.now().strftime("%Y-%m-%d")
    agg = {}
    for r in rows:
        c = r["c"]
        g = (c.get("recruiter") or "").strip() or "（未分配）"
        a = agg.setdefault(g, {
            "g": g, "total": 0, "已发邮件": 0, "洽谈中": 0,
            "履约中": 0, "已闭环": 0, "逾期": 0, "_cpm": [], "_roi": []})
        a["total"] += 1
        st_ = r["stage"]
        if st_ in a:
            a[st_] += 1
        if st_ == "履约中":
            dl = str(c.get("submit_deadline") or "")[:10]
            if dl and dl < today and not c.get("is_closed"):
                a["逾期"] += 1
        m = _kol_metrics(c)
        if m["cpm"]:
            a["_cpm"].append(m["cpm"])
        if m["roi"]:
            a["_roi"].append(m["roi"])
    out = []
    for a in agg.values():
        a["avg_cpm"] = round(sum(a["_cpm"]) / len(a["_cpm"]), 2) if a["_cpm"] else 0
        a["avg_roi"] = round(sum(a["_roi"]) / len(a["_roi"]), 2) if a["_roi"] else 0
        out.append(a)
    out.sort(key=lambda x: -x["total"])
    return out


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


def load_all():
    """四阶段全量记录（宜搭）。
    不再加 st.cache_data：管理看板是独立于主站的另一个 Streamlit 进程，
    自己再叠一层 5 分钟缓存会让「主站刚改、看板还显示旧」翻倍恶化。
    直接走 YidaStore 的缓存（stale-while-revalidate），最新性交给
    页面顶部「🔄 重新同步」按钮手动强制回源，看到的变化即时可见。
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

f1, f2, f3, f4, f5 = st.columns([2.2, 1.45, 1.1, 1.1, 1.35])
with f1:
    stage_filter = st.pills("阶段筛选", ["全部"] + STAGES, default="全部",
                            key="mgr_stage")
with f2:
    member_filter = st.selectbox("组员筛选", ["全部组员"] + members, key="mgr_member")
with f3:
    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
    if st.button("🔄 重新同步", key="mgr_resync", use_container_width=True,
                 help="强制从宜搭重新拉取全部数据：主站/审核站刚改动后点这里，"
                      "看板立即反映最新阶段与记录（不受缓存时间影响）"):
        store._invalidate()
        st.rerun()
with f4:
    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
    if st.button("🎬 强刷近10条", key="mgr_force10", use_container_width=True,
                 help="无视7天缓存，重新调 YouTube API 抓全部网红的最新10条视频"
                      "（每人约3配额单位）"):
        st.session_state["mgr_force10_ts"] = time.time()
        st.session_state["mgr_force10"] = True
        st.rerun()
with f5:
    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
    if st.button("🧹 误判履约→洽谈退回", key="mgr_demote", use_container_width=True,
                 help="把「只填了归属月份、却没有任何实际进度」的网红从履约中退回洽谈中"
                      "（团队进度表常把归属月份整列预填导致误升级）。点开后先预览再确认。"):
        st.session_state["mgr_demote_ask"] = True
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

# 组员概览（管理每个人）
st.markdown(T.sub("👥 组员概览"), unsafe_allow_html=True)
_ov = recruiter_overview_rows(rows)
if not _ov:
    st.markdown(T.empty_hint("暂无组员数据"), unsafe_allow_html=True)
else:
    _ov_head = ["组员", "总数", "已发邮件", "洽谈中", "履约中", "已闭环",
                "⚠️ 逾期", "均CPM($)", "均ROI"]
    _ov_cells = []
    for a in _ov:
        over = a["逾期"]
        over_cell = (f'<span class="num" style="color:#c0392b;font-weight:700">{over}</span>'
                     if over else '<span class="num" style="color:#c7c7cc">0</span>')
        _ov_cells.append([
            f"<b>{esc(a['g'])}</b>",
            f"<span class='num'>{a['total']}</span>",
            f"<span class='num'>{a['已发邮件']}</span>",
            f"<span class='num'>{a['洽谈中']}</span>",
            f"<span class='num'>{a['履约中']}</span>",
            f"<span class='num'>{a['已闭环']}</span>",
            over_cell,
            f"<span class='num'>{a['avg_cpm']:.2f}</span>" if a["avg_cpm"]
            else "<span class='num' style='color:#c7c7cc'>-</span>",
            f"<span class='num'>{a['avg_roi']:.2f}</span>" if a["avg_roi"]
            else "<span class='num' style='color:#c7c7cc'>-</span>",
        ])
    T.component_html(T.table(_ov_head, _ov_cells, wrap=False),
                     height=96 + len(_ov) * 44, grow=False)

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
        store._soft_invalidate()  # 让宜搭缓存过期→下次渲染后台刷新（近10条抓取可能回写粉丝数等）

# ============================ 表格渲染 ============================
REC10_CACHE = CS._load_cache()  # 整页只读一次缓存文件


def _row_cells(r) -> list:
    c = r["c"]
    stage = r["stage"]
    cid = c.get("channel_id") or ""
    home = c.get("channel_url") or (f"https://www.youtube.com/channel/{cid}"
                                    if cid else "")
    name = esc(c.get("name") or cid or "-")
    # 头像（近10条抓取时顺带拿到）；缩略图被墙/拉不到时用名字首字彩色圆兜底
    rec10 = REC10_CACHE.get(cid) or {}
    avatar = rec10.get("avatar") or c.get("avatar") or ""
    raw_name = (c.get("name") or cid or "?").strip()
    letter = esc(raw_name[0]) if raw_name else "?"
    _pal = ["#d98cab", "#c2507a", "#7a5fd0", "#3f9ec9",
            "#1a7f4b", "#c98a3f", "#8a6db5", "#b56d8a"]
    _col = _pal[sum(ord(ch) for ch in raw_name) % len(_pal)]
    av_html = (
        f'<span style="position:relative;display:inline-flex;align-items:center;'
        f'justify-content:center;width:30px;height:30px;border-radius:50%;'
        f'vertical-align:middle;margin-right:8px;background:{_col};color:#fff;'
        f'font-weight:700;font-size:14px;overflow:hidden">{letter}'
        + (f'<img src="{esc(avatar)}" onerror="this.remove()" '
           f'style="position:absolute;inset:0;width:30px;height:30px;'
           f'border-radius:50%;object-fit:cover">' if avatar else '')
        + '</span>')
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
    # CPM / ROI（宜搭视频子表现算，口径同分析页）
    m = _kol_metrics(c)
    cpm_cell = (f'<span title="报价 ${m["price_usd"]:,.0f} ÷ 总播放 '
                f'{m["views"]:,} × 1000">{m["cpm"]:.2f}</span>'
                if m["cpm"] else "-")
    roi_show = m["roi"] or (stage == "已闭环" and m["price_usd"] > 0)
    roi_cell = (f'<span title="总GMV ${m["gmv"]:,.0f} ÷ 报价 '
                f'${m["price_usd"]:,.0f}">{m["roi"]:.2f}</span>'
                if roi_show else "-")
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
    # 商品链接（每个商品一个跳转按钮，悬停看商品名+GMV）
    plinks = _product_links(c)
    if plinks:
        prod_cell = " ".join(
            f'<a href="{esc(u)}" target="_blank" title="{esc(t)}" '
            f'style="display:inline-block;padding:2px 8px;margin:1px 3px 1px 0;'
            f'background:#f0f0f5;border-radius:10px;font-size:11px;'
            f'text-decoration:none;color:#1d1d1f">🛍 {i}</a>'
            for i, (u, t) in enumerate(plinks, 1))
    else:
        prod_cell = '<span style="color:#c7c7cc">-</span>'
    return [name_cell, stage_cell, esc(cat),
            f"<span class='num'>{_fmt_num(c.get('followers'))}</span>",
            esc(str(c.get("plan_month") or "-")),
            f"<span class='num'>{price_cell}</span>",
            f"<span class='num'>{cpm_cell}</span>",
            f"<span class='num'>{roi_cell}</span>",
            f"<span class='num'>{avg}</span>",
            f"<span class='num'>{med}</span>",
            vid_cell, prod_cell]


HEADERS = ["网红（点头像跳主页）", "阶段/进度", "双垂类", "粉丝数", "月份",
           "报价", "CPM($)", "ROI", "近10条均播", "近10条中位播",
           "合作视频", "商品链接"]
HEADERS_OPS = HEADERS + ["操作"]


# ============================ 行内操作（查看全部月份 / 删除网红） ============================
def _set_pending(kind, cid, name):
    """隐藏按钮 on_click 回调：只写 session_state，不调 st.rerun()
    （回调里 st.rerun 是 no-op 且告警）；回调结束后 Streamlit 自动 rerun，
    页面底部的分发块据此弹出对应对话框。"""
    st.session_state["mgr_pending"] = (kind, cid, name)


def _op_targets(entries, gi):
    """为一组表格的每个操作链接渲染一个「隐形」原生按钮（点击靶子）。
    顺序必须与表格里 #op=<idx> 的 idx 完全一致：iframe 内 JS 用
    followingButtons(本iframe, 靶子数) 找到紧跟其后的前 N 个 <button> 并按下
    第 idx 个。按钮加载后被 COMP_JS 隐藏，只作触发用。"""
    for i, (kind, cid, name) in enumerate(entries):
        st.button(f"op{gi}-{i}", key=f"mop_{gi}_{i}",
                  on_click=_set_pending, args=(kind, cid, name))


@st.dialog("🔍 该网红在宜搭的全部月份记录", width="large")
def _info_dialog(cid, name):
    recs = store.channel_rows(cid)
    st.markdown(f"**{esc(name)}**　<span style='color:#86868b'>频道ID "
                f"`{esc(cid)}`</span>", unsafe_allow_html=True)
    if not recs:
        st.success("该网红在宜搭已无月份记录。")
    else:
        st.caption(f"共 {len(recs)} 条月份记录。看板按「网红」去重只显示 1 张卡"
                   "（取其最高阶段），主站按月份逐条列，故两边条数口径不同；"
                   "这里可逐条精确删除某个月份的记录。")
        for rr in recs:
            c1, c2 = st.columns([4.4, 1])
            with c1:
                st.markdown(f"📅 **{esc(rr['month'])}**"
                            f"　—　阶段：{esc(rr['stage'])}")
            with c2:
                if rr["has_instance"]:
                    if st.button("🗑 删除此行",
                                 key=f"dl_{cid}_{rr['collab_id']}",
                                 use_container_width=True):
                        ok = store.delete_record(rr["collab_id"])
                        st.toast(("已删除 " if ok else "未删除（无实例）")
                                 + f"{name} · {rr['month']}")
                        st.rerun()  # 弹窗保持打开，重开显示剩余行
                else:
                    st.caption("无实例ID")
    if st.button("关闭", key=f"close_info_{cid}", use_container_width=True):
        st.session_state["mgr_pending"] = None
        st.rerun()


@st.dialog("⚠️ 彻底删除该网红", width="compact")
def _delall_dialog(cid, name):
    recs = store.channel_rows(cid)
    st.markdown(f"将从**宜搭彻底删除**网红「**{esc(name)}**」的**全部**合作记录。")
    if recs:
        st.caption(f"将一并删除以下 {len(recs)} 条月份记录：")
        for rr in recs:
            st.markdown(f"· {esc(rr['month'])}（{esc(rr['stage'])}）")
    else:
        st.info("该网红在宜搭已无可删除的月份记录。")
    st.error("此操作不可恢复：宜搭表单数据同步删除，主站与审核站也不再显示该网红。")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("取消", key=f"cx_del_{cid}", use_container_width=True):
            st.session_state["mgr_pending"] = None
            st.rerun()
    with c2:
        if st.button("确认彻底删除", key=f"ok_del_{cid}", type="primary",
                     use_container_width=True):
            n = store.remove_channel(cid)
            st.session_state["mgr_pending"] = None
            st.toast(f"已彻底删除 {name}（{n} 条记录）" if n
                     else f"{name}：无可删除的宜搭记录")
            st.rerun()


@st.dialog("🧹 误判履约 → 洽谈 一键退回", width="large")
def _demote_dialog():
    safe, conflict = store.demote_preview()
    if not safe and not conflict:
        st.info("没有需要退回的记录——当前所有「履约中」都有实际进度"
                "（Guideline/合同/下单/拍摄/视频/审核等），或没有只凭归属月份误升的记录。")
        if st.button("关闭", key="cx_demote_close", use_container_width=True):
            st.session_state["mgr_demote_ask"] = None
            st.rerun()
        return
    st.markdown(
        f"检测到 **{len(safe)}** 条记录只填了「归属月份」、却没有任何实际履约进度，"
        "多半是团队进度表把归属月份整列预填导致被误判成履约中。"
        "点确认后，系统会**清空这些行的归属月份并退回洽谈中**（不动有进度的网红）。")
    st.caption("将退回的记录（最多显示 30 条）：")
    for it in safe[:30]:
        st.markdown(f"· {esc(it['name'])}（归属月份 {esc(it['plan_month'])}）")
    if len(safe) > 30:
        st.caption(f"… 其余 {len(safe) - 30} 条一并退回")
    if conflict:
        st.warning(f"另有 {len(conflict)} 条同名网红已存在「无月份」洽谈记录，"
                   "清月份会与之重复，已跳过——可在该网红的「🔍 全部月份」里自行处理。")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("取消", key="cx_demote", use_container_width=True):
            st.session_state["mgr_demote_ask"] = None
            st.rerun()
    with c2:
        if st.button(f"确认退回 {len(safe)} 条", key="ok_demote", type="primary",
                     use_container_width=True, disabled=not safe):
            n, _ = store.demote_false_fulfilling()
            st.session_state["mgr_demote_ask"] = None
            st.toast(f"已把 {n} 条误判记录退回洽谈中")
            st.rerun()


if not visible:
    st.markdown(T.empty_hint("当前筛选条件下没有网红"), unsafe_allow_html=True)
else:
    # 按组员分组
    groups = {}
    for r in visible:
        g = (r["c"].get("recruiter") or "").strip() or "（未分配）"
        groups.setdefault(g, []).append(r)
    order = {s: i for i, s in enumerate(STAGES)}
    for gi, g in enumerate(sorted(groups, key=lambda x: -len(groups[x]))):
        grp = sorted(groups[g], key=lambda r: order.get(r["stage"], 9))
        g_cnt = {s: sum(1 for r in grp if r["stage"] == s) for s in STAGES}
        summary = " · ".join(f"{s} {n}" for s, n in g_cnt.items() if n)
        st.markdown(T.sub(f"🧑 {esc(g)}　"
                          f'<span style="font-size:12px;color:#86868b;'
                          f'font-weight:500">{summary}</span>'),
                    unsafe_allow_html=True)
        entries, cells = [], []
        for r in grp:
            rc = _row_cells(r)
            c = r["c"]
            cid = (c.get("channel_id") or c.get("influencer_id")
                   or str(c.get("collab_id") or "").split("#")[0])
            nm = c.get("name") or c.get("channel_name") or cid or "-"
            if cid:
                ii = len(entries)
                entries.append(("info", cid, nm))
                di = len(entries)
                entries.append(("delall", cid, nm))
                ops_cell = (f'<a class="act" data-nav="#op={ii}">🔍 全部月份</a> '
                            f'<a class="act act-del" '
                            f'data-nav="#op={di}">🗑 删除网红</a>')
            else:
                ops_cell = '<span style="color:#c7c7cc">-</span>'
            rc.append(ops_cell)
            cells.append(rc)
        # 长列表可滚动：给表格套一个「固定高 + 内部滚动」的容器 div。
        # 之前靠 iframe body 自身 overflow-y:auto 滚动，线上不生效（滚不动），
        # 改成显式滚动盒：div 有硬 max-height + overflow-y:auto，独立于 iframe
        # 的 scrolling 属性能正常滚动，表头 sticky 相对滚动盒吸顶。
        _cap = 600
        _box_css = ('<style>.yts-scroll{max-height:' + str(_cap) + 'px;'
                    'overflow-y:auto;overflow-x:hidden;border-radius:14px;'
                    'scrollbar-width:thin;scrollbar-color:#d9a7b8 #f6eef1;}'
                    '.yts-scroll::-webkit-scrollbar{width:10px;}'
                    '.yts-scroll::-webkit-scrollbar-thumb{background:#d9a7b8;'
                    'border-radius:6px;border:2px solid #f6eef1;}'
                    '.yts-scroll::-webkit-scrollbar-track{background:#f6eef1;}'
                    '.yts-scroll th{position:sticky;top:0;z-index:3;'
                    'background:#fff;box-shadow:0 1px 0 #f0e4e8}</style>')
        _box = (_box_css + '<div class="yts-scroll">'
                + T.table(HEADERS_OPS, cells, wrap=False) + '</div>')
        T.component_html(_box, height=_cap + 10, grow=False)
        _op_targets(entries, gi)

st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
st.caption("📌 数据口径：本看板按「网红」去重（一位网红一张卡，取其最高阶段），"
           "主站按「合作记录」逐月列，故两边条数可能不同——点每行「🔍 全部月份」"
           "可查看该网红的所有月份记录。本看板与主站是两个独立服务、各自缓存，"
           "主站/审核站刚改动后点顶部「🔄 重新同步」即可让看板立即反映最新。")
st.caption("🎬 近10条数据 7 天自动缓存；「强刷近10条」可立即拉最新。"
           "报价按 ₩1 = $1/1538 折算。CPM/ROI 与分析页同口径："
           "ROI = 总GMV($) ÷ 报价($)，CPM = 报价($) ÷ 播放 × 1000，"
           "鼠标悬停数字可看计算明细；🛍 按钮点击跳商品页，悬停看商品名+GMV。"
           "「🗑 删除网红」会从宜搭彻底删除该网红全部记录，二次确认后不可恢复。")

# ============================ 弹窗分发（隐藏按钮触发后打开） ============================
_pending = st.session_state.get("mgr_pending")
if _pending:
    _pk, _pcid, _pname = _pending
    if _pk == "info":
        _info_dialog(_pcid, _pname)
    elif _pk == "delall":
        _delall_dialog(_pcid, _pname)

if st.session_state.get("mgr_demote_ask"):
    _demote_dialog()
