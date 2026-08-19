#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网红管理系统 - 主管理后台（裸粉 · Apple 极简版）"""
import html
import io
import re
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from yts_yida_store import get_yts_store
import yts_theme as T
import yts_guide_gen as G
import yts_roster as R
import yts_yt_stats as YT
from yts_import_flow import norm_month, norm_date

st.set_page_config(page_title="YTS 网红管理库", page_icon="🎯", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(T.THEME_CSS, unsafe_allow_html=True)

store = get_yts_store()
if getattr(store, "demo", False):
    st.error("⚠️ 未连接到宜搭数据库，当前显示演示数据。"
             "请到 Streamlit Cloud → 本应用 → Settings → Secrets，"
             "确认 YIDA_ACCESS_KEY_ID / YIDA_ACCESS_KEY_SECRET 两行存在后保存重启。")
esc = html.escape
NOW_MONTH = datetime.now().strftime("%Y-%m")

if "page" not in st.session_state:
    st.session_state.page = "home"


def go(page, **kw):
    st.session_state.page = page
    st.session_state.update(kw)
    st.rerun()


def home_btn():
    if st.button("⬅ 返回首页", key="home_btn"):
        go("home")


# ============================ 首页 ============================
def page_home():
    st.markdown(T.header("YTS 全栈项目管理",
                         "网红全生命周期管理 · 挖掘 → 合作 → 履约 → 审核 → 数据",
                         center=True),
                unsafe_allow_html=True)
    pool = store.list_pool()
    negs = store.list_negotiating()
    fuls = store.list_fulfilling()
    closed = [c for c in fuls if c["is_closed"]]
    pending = store.list_pending_reviews()
    st.markdown(T.stats_row([
        ("挖掘池", len(pool), "c-pink"),
        ("洽谈中", len(negs), "c-amber"),
        ("履约中", len(fuls) - len(closed), "c-purple"),
        ("已闭环", len(closed), "c-green"),
    ]), unsafe_allow_html=True)

    entries = [
        ("dig", "🔍", "挖掘", "维护挖掘池：已发邮件 → 标记洽谈中，两步流入活动"),
        ("activity", "📋", "活动", "确认合作 → 三分支 → 下单 → 拍摄 → 审核 → 闭环"),
        ("analysis", "📊", "分析", "播放 / 点击率 / 成交量 / GMV 概览"),
    ]
    cols = st.columns(3)
    for col, (pg, icon, title, desc) in zip(cols, entries):
        with col:
            with st.container():
                st.markdown(T.ycard_open(), unsafe_allow_html=True)
                st.markdown(
                    f'<div style="text-align:center;padding:6px 0 10px">'
                    f'<div style="font-size:26px">{icon}</div>'
                    f'<div style="font-size:15px;font-weight:700;margin-top:6px">'
                    f'{title}</div>'
                    # 描述区固定两行高度：三张卡片描述长短不一，
                    # 不固定会导致卡片高度参差、底部按钮不对齐
                    f'<div style="font-size:12px;color:#86868b;font-weight:500;'
                    f'margin-top:4px;line-height:1.5;height:36px;overflow:hidden">'
                    f'{desc}</div></div>',
                    unsafe_allow_html=True)
                if st.button("进入", key=f"hb_{pg}", use_container_width=True):
                    go(pg)


# ============================ 挖掘模块 ============================
@st.dialog("➕ 新增网红", width="large")
def dlg_add():
    with st.form("add_form"):
        a1, a2 = st.columns(2)
        cid = a1.text_input("频道ID（必填）", placeholder="UC_xxx")
        cname = a2.text_input("昵称（必填）")
        b1, b2, b3 = st.columns(3)
        cat = b1.text_input("垂类", placeholder="뷰티")
        subs = b2.number_input("粉丝数", min_value=0, step=1000)
        recruiter = b3.text_input("挖掘人（你的名字）")
        email = st.text_input("联系邮箱")
        if st.form_submit_button("💾 保存", type="primary", use_container_width=True):
            if not cid.strip() or not cname.strip():
                st.error("频道ID 和昵称为必填项")
            else:
                store.add_influencer({
                    "channel_id": cid.strip(), "channel_name": cname.strip(),
                    "category": cat.strip(), "subscribers": subs,
                    "recruiter": recruiter.strip(), "email": email.strip(),
                })
                st.toast(f"{cname} 已加入挖掘池")
                st.rerun()


def _import_template_bytes() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "导入模板"
    ws.append(["频道ID", "昵称", "垂类", "粉丝数", "挖掘人", "联系邮箱"])
    ws.append(["UC_example001", "예시채널", "뷰티", 12000, "艾薇李",
               "hello@example.com"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@st.dialog("📥 批量导入网红", width="large")
def dlg_import():
    st.markdown("先下载模板，按列填好后上传。带 * 为必填，已存在的频道ID会更新而非重复新增。")
    st.download_button("⬇ 下载导入模板", _import_template_bytes(),
                       file_name="YTS批量导入模板.xlsx", use_container_width=True)
    up = st.file_uploader("上传填好的模板", type=["xlsx", "xls"])
    if up is not None:
        try:
            df = pd.read_excel(up)
        except Exception:
            st.error("文件解析失败，请确认使用的是模板格式")
            return
        col_map = {"频道ID": "channel_id", "昵称": "channel_name", "垂类": "category",
                   "粉丝数": "subscribers", "挖掘人": "recruiter", "联系邮箱": "email"}
        df = df.rename(columns=col_map)
        if "channel_id" not in df.columns:
            st.error("模板缺「频道ID」列，请下载最新模板")
            return
        recs = []
        for _, r in df.iterrows():
            cid = str(r.get("channel_id") or "").strip()
            if not cid or cid == "nan":
                continue
            def num(v):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return 0
            recs.append({
                "channel_id": cid,
                "channel_name": str(r.get("channel_name") or "").strip(),
                "category": str(r.get("category") or "").strip(),
                "subscribers": num(r.get("subscribers")),
                "recruiter": str(r.get("recruiter") or "").strip(),
                "email": str(r.get("email") or "").strip(),
            })
        if not recs:
            st.error("没有可导入的行，请检查「频道ID」列")
            return
        st.caption(f"共 {len(recs)} 行待导入： " + "、".join(
            esc(r["channel_name"] or r["channel_id"]) for r in recs[:5]) +
            (" 等" if len(recs) > 5 else ""))
        if st.button(f"✅ 确认导入 {len(recs)} 位网红", type="primary",
                     use_container_width=True):
            n = store.import_influencers(recs)
            st.toast(f"导入完成，共写入 {n} 条")
            st.rerun()


def flow_import_panel():
    import yts_import_flow as FI
    with st.container(border=True):
        st.markdown("**📥 流程导入** · 按月上线 / 存量迁移 —— 运营按模板填写"
                    "（**只填到当前进度**，空着=还没到），上传后先预览再写库。"
                    "团队现有进度表也可直接传，识别到几列映射几列。"
                    "「已闭环」填 Y 的直接进 📊 分析模块，只追踪数据。")
        st.download_button("⬇ 下载万能模板", FI.build_template_bytes(R.get_members()),
                           file_name="YTS流程导入模板.xlsx", key="fi_tpl",
                           use_container_width=True)
        up = st.file_uploader("上传填好的模板 / 现有进度表", type=["xlsx", "xls"],
                              key="fi_up")
        if up is None:
            return
        rows, issues = FI.parse_workbook(up.read())
        for msg in issues[:8]:
            st.warning(msg)
        roster = R.get_members()
        for raw in rows:
            r0 = str(raw.get("recruiter") or "").strip()
            m = R.match_name(r0, roster)
            if m and m != r0:
                st.info(f"负责人「{r0}」已自动匹配为名单里的「{m}」")
                raw["recruiter"] = m
            elif not m and r0 and roster:
                st.warning(f"负责人「{r0}」不在名单，将按原值导入"
                           "（新成员请先到挖掘站登记）")
        if not rows:
            st.error("没有识别到有效行：请确认表里有「频道链接」「频道名称」「负责人」")
            return
        with st.spinner("正在反查频道ID（云端约几秒）…"):
            existing = getattr(store, "url_index", lambda: {})()
            ids = FI.resolve_ids(rows, existing)
        preview, pend = [], []
        for raw in rows:
            url = str(raw["channel_url"]).strip()
            cid, resolved = ids[url]
            rec = FI.derive_record(raw, cid)
            is_new = url not in existing
            preview.append({
                "频道名称": rec["channel_name"], "负责人": rec["recruiter"],
                "归属月份": rec.get("plan_month", "") or "-",
                "导入后进度": "已闭环 → 分析模块"
                if rec.get("stage") == "已完成"
                else (rec.get("stage") or "挖掘池"),
                "新增/更新": "新增" if is_new else "更新",
                "频道ID": cid if resolved else f"{cid}（待反查）",
            })
            pend.append((rec, is_new))
        st.dataframe(preview, use_container_width=True, hide_index=True)
        n_new = sum(1 for _, n in pend if n)
        st.caption(f"共 {len(pend)} 行：新增 {n_new}、更新 {len(pend) - n_new}。"
                   "「待反查」表示暂用链接别名做ID，不影响进流程")
        if st.button(f"✅ 确认导入 {len(pend)} 行", type="primary",
                     use_container_width=True, key="fi_go"):
            for rec, _ in pend:
                store.import_flow(rec)
            st.session_state["flow_import_open"] = False
            st.toast(f"导入完成：{len(pend)} 位网红已入库"
                     f"（已闭环的在 📊 分析模块查看）")
            st.rerun()


def page_dig():
    home_btn()
    h1, h2 = st.columns([5, 1])
    with h1:
        st.markdown(T.header("挖掘模块",
                             "挖掘站「已发邮件」自动入池；点右上「同步挖掘站」"
                             "把粉丝量等基础信息刷进宜搭"),
                    unsafe_allow_html=True)
    with h2:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        if st.button("🔄 同步挖掘站", key="btn_sync_dig", use_container_width=True):
            st.session_state["dig_sync_ts"] = 0
            st.session_state["dig_force"] = True
            st.rerun()
    if getattr(store, "sync_from_discovery", None) and \
            time.time() - st.session_state.get("dig_sync_ts", 0) > 300:
        force = st.session_state.pop("dig_force", False)
        bar = st.progress(0, text="正在同步挖掘站数据…") if force else None

        def _cb(i, n):
            if bar:
                bar.progress(int(i * 100 / max(n, 1)),
                             text=f"正在把粉丝量等基础信息写进宜搭 {i}/{n}")

        with st.spinner("正在与挖掘站双向同步…"):
            res = store.sync_from_discovery(force=force)
            back = store.push_back_introduced(force=force) \
                if getattr(store, "push_back_introduced", None) else 0
            basic = store.sync_basic_info(force=force, progress=_cb) \
                if force and getattr(store, "sync_basic_info", None) \
                else {"updated": 0}
        if bar:
            bar.empty()
        st.session_state["dig_sync_ts"] = time.time()
        if res["added"] or res["patched"] or back or basic["updated"]:
            st.toast(f"已同步挖掘站：新增 {res['added']} 位、补信息 {res['patched']} 位"
                     f"、回流已引入 {back} 位"
                     + (f"、粉丝量等基础信息同步 {basic['updated']} 位"
                        if basic["updated"] else ""))
    pool = store.list_pool()

    c1, c2, c3, c4, c5, c6 = st.columns([2.2, 1.1, 1.1, 1.9, 1.1, 1.1])
    q = c1.text_input("搜索昵称 / 频道ID", key="dig_q", placeholder="🔍 输入关键词")
    cats = sorted({p.get("category") for p in pool if p.get("category")})
    cat = c2.selectbox("垂类", ["全部垂类"] + cats, key="dig_cat")
    recs_data = sorted({p.get("recruiter") for p in pool if p.get("recruiter")})
    roster_d = R.get_members()
    recs = list(roster_d) + [n for n in recs_data if not R.match_name(n, roster_d)]
    rec = c3.selectbox("挖掘人", ["全部挖掘人"] + recs, key="dig_rec")
    status = c4.pills("状态", ["全部", "未发邮件", "已发邮件", "洽谈中"],
                      default="全部", key="dig_status")
    with c5:
        st.markdown('<div style="height:26px"></div>', unsafe_allow_html=True)
        if st.button("📥 批量导入", use_container_width=True, key="btn_import"):
            dlg_import()
    with c6:
        st.markdown('<div style="height:26px"></div>', unsafe_allow_html=True)
        if st.button("➕ 新增", type="primary", use_container_width=True,
                     key="btn_add"):
            dlg_add()

    rows = pool
    if q.strip():
        kw = q.strip().lower()
        rows = [p for p in rows if kw in (p.get("name") or "").lower()
                or kw in (p.get("id") or "").lower()]
    if cat != "全部垂类":
        rows = [p for p in rows if p.get("category") == cat]
    if rec != "全部挖掘人":
        rows = [p for p in rows
                if (p.get("recruiter") or "") == rec
                or R.match_name(p.get("recruiter"), [rec]) == rec]
    if status == "未发邮件":
        rows = [p for p in rows if not p.get("emailed")]
    elif status == "已发邮件":
        rows = [p for p in rows if p.get("emailed")
                and (p.get("stage") or "") in ("", "已发邮件")]
    elif status == "洽谈中":
        rows = [p for p in rows if (p.get("stage") or "") == "洽谈中"]

    PAGE = 20
    total = len(rows)
    pages = max(1, (total + PAGE - 1) // PAGE)
    cur = min(st.session_state.get("dig_page", 1), pages)
    st.session_state.dig_page = cur

    if not rows:
        st.markdown(T.empty_hint("没有符合条件的网红，点右上「新增」或「批量导入」开始"),
                    unsafe_allow_html=True)
    else:
        trows = []
        for p in rows[(cur - 1) * PAGE: cur * PAGE]:
            if not p.get("emailed"):
                st_cell = (f'<a class="act act-y" data-nav="?act=mail&id={esc(p["id"])}">'
                           f'标记已发邮件</a>')
            elif (p.get("stage") or "") in ("", "已发邮件"):
                st_cell = (f'<a class="act act-b" data-nav="?act=neg&id={esc(p["id"])}">'
                           f'标记洽谈中</a>')
            elif p.get("stage") == "洽谈中":
                st_cell = T.badge("洽谈中")
            else:
                st_cell = T.badge("已流入活动")
            trows.append([
                f'<b>{esc(p.get("name") or p.get("id"))}</b>',
                esc(p.get("category") or "-"),
                f'<span class="num">{p.get("followers", 0):,}</span>',
                esc(p.get("recruiter") or "-"),
                f'<span style="color:#86868b">{esc(p.get("email") or "-")}</span>',
                st_cell,
            ])
        T.component_html(
            T.table(["昵称", "垂类", "粉丝数", "挖掘人", "邮箱", "操作"],
                    trows, wrap=False),
            height=48 + len(trows) * 38)

    p1, p2, p3 = st.columns([1, 3, 1])
    with p1:
        if st.button("‹ 上一页", disabled=cur <= 1, key="pg_prev",
                     use_container_width=True):
            st.session_state.dig_page = cur - 1
            st.rerun()
    p2.markdown(f'<div style="text-align:center;color:#86868b;font-size:12px;'
                f'font-weight:600;padding-top:6px">第 {cur} / {pages} 页 · '
                f'共 {total} 位</div>', unsafe_allow_html=True)
    with p3:
        if st.button("下一页 ›", disabled=cur >= pages, key="pg_next",
                     use_container_width=True):
            st.session_state.dig_page = cur + 1
            st.rerun()


# ============================ 活动模块 ============================
def _current_node(c):
    if c["is_closed"]:
        return "已闭环"
    if not all(c["branches"].values()):
        return "三分支"
    if not c["order_done"]:
        return "待下单"
    if not c["received"]:
        return "待收货"
    if c["shoot_status"] != "已完成":
        return "拍摄中" if c["shoot_status"] == "拍摄中" else "待拍摄"
    if not c["video_url"]:
        return "待提交"
    rs = c["review_status"]
    if rs == "待审核":
        return "待审核"
    if rs == "已驳回":
        return "已驳回"
    if rs == "复审中":
        return "复审中"
    if rs in ("已通过", "复审通过"):
        return "待闭环"
    return "待提交"


def page_activity():
    home_btn()
    h1, h2 = st.columns([5, 1])
    with h1:
        st.markdown(T.header("活动模块", "选择你的名字，管理你挖掘的网红"),
                    unsafe_allow_html=True)
    with h2:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        _fi_open = st.session_state.get("flow_import_open", False)
        if st.button("✕ 收起导入面板" if _fi_open else "📥 流程导入",
                     key="btn_flow_import", use_container_width=True):
            st.session_state["flow_import_open"] = not _fi_open
            st.rerun()
    if st.session_state.get("flow_import_open"):
        flow_import_panel()

    roster = R.get_members()
    # 静默对账（5分钟一次）：履约中的网红回流挖掘站标「已引入」
    # 后台线程跑，不挡页面渲染
    if getattr(store, "push_back_introduced", None) and \
            time.time() - st.session_state.get("act_push_ts", 0) > 300:
        st.session_state["act_push_ts"] = time.time()
        threading.Thread(target=store.push_back_introduced,
                         daemon=True).start()
    data_names = sorted({p.get("recruiter") for p in store.list_pool()
                         if p.get("recruiter")})
    recruiters = list(roster) + [n for n in data_names
                                 if not R.match_name(n, roster)]
    filter_by = None
    # 名字选择 + 统计卡同一行横向铺满：左1/4放名字，右3/4放三张统计卡
    name_col, stats_col = st.columns([1, 3])
    with name_col:
        if recruiters:
            cur = st.session_state.get("activity_recruiter") \
                or st.query_params.get("rec")
            options = recruiters if cur in recruiters else ["（请选择）"] + recruiters
            sel = st.selectbox("🧑 我的名字", options,
                               index=options.index(cur) if cur in options else 0,
                               key="activity_recruiter")
            # 名字写进 URL，iframe 跳转整页刷新后不丢
            if sel in recruiters:
                st.query_params["rec"] = sel
            elif "rec" in st.query_params:
                del st.query_params["rec"]
            filter_by = None if sel == "（请选择）" else sel
        else:
            manual = st.text_input("🧑 输入你的名字", key="activity_recruiter_manual")
            filter_by = manual.strip() or None

    def by_me(lst):
        if filter_by is None:
            return []
        return [c for c in lst
                if (c.get("recruiter") or "") == filter_by
                or R.match_name(c.get("recruiter"), [filter_by]) == filter_by]

    negs = by_me(store.list_negotiating())
    fuls = by_me(store.list_fulfilling())
    closed = [c for c in fuls if c["is_closed"]]

    with stats_col:
        st.markdown(T.stats_row([
            ("💬 洽谈中", len(negs), "c-amber"),
            ("🚀 履约中", len(fuls) - len(closed), "c-purple"),
            ("✅ 已闭环", len(closed), "c-green"),
        ]), unsafe_allow_html=True)

    left, right = st.columns([1, 2])

    with left:
        st.markdown(T.sub("💬 洽谈中"), unsafe_allow_html=True)
        if filter_by is None:
            st.markdown(T.empty_hint("请先在上方选择你的名字"), unsafe_allow_html=True)
        elif not negs:
            st.markdown(T.empty_hint("暂无洽谈中网红，去挖掘模块标记「洽谈中」即可流入"),
                        unsafe_allow_html=True)
        for c in negs:
            with st.container():
                st.markdown(T.ycard_open(), unsafe_allow_html=True)
                st.markdown(
                    f'<div class="nm" style="font-size:13px;font-weight:700">'
                    f'{esc(c["name"])}</div>'
                    f'<div class="mt" style="font-size:11px;color:#86868b;'
                    f'margin-top:2px">{esc(c.get("category") or "-")} · '
                    f'{c.get("followers", 0):,} 粉丝</div>',
                    unsafe_allow_html=True)
                m1, m2 = st.columns(2)
                month = m1.text_input("上线月份", NOW_MONTH,
                                      key=f"m_{c['collab_id']}")
                price = m2.number_input("报价（韩币）", min_value=0,
                                        step=10000,
                                        value=int(c.get("price") or 0),
                                        key=f"p_{c['collab_id']}")
                if st.button("确认合作", key=f"ok_{c['collab_id']}",
                             type="primary"):
                    if price <= 0:
                        st.warning("请先填写报价（韩币）再确认合作")
                    else:
                        store.confirm_collab(c["collab_id"], month, price)
                        st.toast(f"{c['name']} 已进入右栏（{month}）")
                        st.rerun()

    with right:
        st.markdown(T.sub("🚀 履约中（按月份分组）"), unsafe_allow_html=True)
        st.caption("已闭环的网红不再留在这里，自动去 📊 分析模块追踪数据")
        open_fuls = [c for c in fuls if not c["is_closed"]]
        if filter_by is None:
            st.markdown(T.empty_hint("请先在上方选择你的名字"), unsafe_allow_html=True)
        elif not open_fuls:
            st.markdown(T.empty_hint("暂无履约中网红，在左栏「确认合作」后进入此栏"),
                        unsafe_allow_html=True)
        months = sorted({c["plan_month"] for c in open_fuls})
        for i in range(0, len(months), 3):
            cols = st.columns(3)
            for col, m in zip(cols, months[i:i + 3]):
                rows = [x for x in open_fuls if x["plan_month"] == m]
                html = T.month_tag(m)
                for c in rows:
                    html += T.name_card(c, _current_node(c),
                                        nav_extra="&from=activity")
                # 卡片固定 64px 高 + 上下 margin 16px = 80px/卡；
                # 月份标签约 32px；公式贴合实际，避免底部积空白
                full = 36 + len(rows) * 80
                with col:
                    # 卡片少的月份按内容撑开；多的封顶 520px，内部滚动不裁剪
                    T.component_html(html, height=min(full, 520))


# ============================ 履约详情 ============================
def _flow_state(cond_done, cond_doing):
    return "done" if cond_done else ("doing" if cond_doing else "todo")


def _set_detail_step(cid, i):
    st.session_state.setdefault("detail_steps", {})[cid] = i


def _gen_guide(cid, c, req):
    """调千问生成「内容方向&强带货脚本建议」，组装完整 guide 存 session"""
    with st.spinner("千问正在生成脚本建议（约10-20秒）· 생성 중..."):
        try:
            script = G.call_dashscope(G.build_prompt(c, req))
        except RuntimeError as e:
            st.error(str(e))
            return
    st.session_state[f"guide_{cid}"] = G.assemble_full_guide(script)
    st.toast("Guide 生成完成 · 가이드 생성 완료")


def _edit_info_form(cid, c):
    """编辑基本信息：报价 / 上线月份 / 联系邮箱 / 频道链接 / 群链接 / 交稿截止 / 备注"""
    with st.container(border=True):
        st.markdown(T.sub("✏️ 编辑基本信息"), unsafe_allow_html=True)
        with st.form(f"edit_{cid}"):
            e1, e2, e3 = st.columns(3)
            price_v = e1.number_input(
                "报价（韩币）", min_value=0, step=10000,
                value=int(c.get("price") or 0), key="ed_price")
            month_v = e2.text_input("上线月份（如 2026-09）",
                                    value=c.get("plan_month") or "", key="ed_month")
            email_v = e3.text_input("联系邮箱",
                                    value=c.get("email") or "", key="ed_email")
            e4, e5, e6 = st.columns(3)
            curl_v = e4.text_input("频道链接",
                                   value=c.get("channel_url") or "", key="ed_curl")
            grp_v = e5.text_input("群链接",
                                  value=c.get("group_link") or "", key="ed_grp")
            dl_v = e6.text_input("交稿截止（YYYY-MM-DD）",
                                 value=c.get("submit_deadline") or "", key="ed_dl")
            notes_v = st.text_input("备注", value=c.get("notes") or "", key="ed_notes")
            if st.form_submit_button("💾 保存修改", type="primary",
                                     use_container_width=True):
                month_s = norm_month(month_v)
                if month_s and not re.match(r"^\d{4}-\d{2}$", month_s):
                    st.error("上线月份格式无法识别，请用 2026-09 或 9月 这样的写法")
                    return
                dl_s = norm_date(dl_v)
                if dl_s and not re.match(r"^\d{4}-\d{2}-\d{2}$", dl_s):
                    st.error("交稿截止格式无法识别，请用 2026-09-21 这样的写法")
                    return
                store.update_info(cid, {
                    "price": price_v, "plan_month": month_s,
                    "email": email_v, "channel_url": curl_v,
                    "group_link": grp_v, "submit_deadline": dl_s,
                    "notes": notes_v,
                })
                st.toast("基本信息已保存")
                st.session_state[f"edit_open_{cid}"] = False
                st.rerun()


def page_detail(collab_id):
    _from = st.session_state.get("detail_from", "activity")
    _back_labels = {"activity": "⬅ 返回活动", "dig": "⬅ 返回挖掘",
                    "analysis": "⬅ 返回分析", "home": "⬅ 返回首页"}
    # 工具栏式：返回/首页靠左，编辑靠右，中间留白作为分隔 → 对称不局促
    b1, b2, _mid, b3 = st.columns([1.2, 1.0, 3.6, 1.4])
    if b1.button(_back_labels.get(_from, "⬅ 返回"), key="back_btn"):
        go(_from)
    if b2.button("🏠 首页", key="home_btn_d"):
        go("home")
    _edit_key = f"edit_open_{collab_id}"
    if b3.button("✕ 关闭编辑" if st.session_state.get(_edit_key) else "✏️ 编辑信息",
                 key="edit_btn"):
        st.session_state[_edit_key] = not st.session_state.get(_edit_key, False)
        st.rerun()
    c = store.get_collab(collab_id)
    if not c:
        st.error("未找到该合作记录")
        return
    st.markdown(T.header(f"履约详情 · {c['name']}",
                         f'挖掘人 {c.get("recruiter") or "-"}'),
                unsafe_allow_html=True)

    price_on = bool(c.get("price"))
    st.markdown(T.stats_row([
        ("报价（韩币）",
         f"₩{int(c['price']):,}" if price_on else "未填",
         "c-pink" if price_on else "c-amber"),
        ("上线月份", esc(c.get("plan_month") or "-"), "c-purple"),
        ("交稿截止", esc(c.get("submit_deadline") or "-"), "c-green"),
        ("联系邮箱",
         f'<span style="font-size:13px;font-weight:600">{esc(c["email"])}</span>'
         if c.get("email") else "未填",
         "c-green" if c.get("email") else "c-amber"),
    ]), unsafe_allow_html=True)
    yt = YT.cached(c["collab_id"])
    if yt is None and YT.get_key() and c["collab_id"].startswith("UC"):
        with st.spinner("正在同步频道播放数据…"):
            yt = YT.fetch_stats(c["collab_id"])
    fol = c.get("followers") or (yt or {}).get("subscribers") or 0
    st.markdown(T.stats_row([
        ("粉丝量", f"{fol:,}", "c-pink"),
        ("垂类", esc(c.get("category") or "-"), "c-purple"),
        ("长视频总播放", f'{yt["long_views"]:,}' if yt else "-", "c-green"),
        ("短视频总播放", f'{yt["short_views"]:,}' if yt else "-", "c-amber"),
    ]), unsafe_allow_html=True)
    if not YT.get_key():
        st.caption("配置 YOUTUBE_API_KEY 后自动同步长/短总播放（缓存 7 天）")
    _meta = []
    if c.get("channel_url"):
        _meta.append(f'频道 <a class="yts-link" href="{esc(c["channel_url"])}" '
                     f'target="_blank">主页↗</a>')
    if c.get("group_link"):
        _meta.append(f'群 <a class="yts-link" href="{esc(c["group_link"])}" '
                     f'target="_blank">链接↗</a>')
    if c.get("notes"):
        _meta.append(f'备注：{esc(c["notes"])}')
    if _meta:
        st.markdown('<div style="font-size:12.5px;font-weight:500;'
                    'color:#86868b;margin:-8px 0 10px">'
                    + "　·　".join(_meta) + "</div>",
                    unsafe_allow_html=True)

    if st.session_state.get(f"edit_open_{collab_id}"):
        _edit_info_form(collab_id, c)

    branches = c["branches"]
    unlocked = all(branches.values())
    rs = c["review_status"]

    steps = [
        ("确认合作", "done"),
        ("三分支", _flow_state(unlocked, True)),
        ("下单", _flow_state(c["order_done"], unlocked and not c["order_done"])),
        ("收货", _flow_state(c["received"], c["order_done"] and not c["received"])),
        ("拍摄", _flow_state(c["shoot_status"] == "已完成",
                             c["received"] and c["shoot_status"] != "已完成")),
        ("提交审核", _flow_state(bool(c["video_url"]),
                                 c["shoot_status"] == "已完成" and not c["video_url"])),
        ("审核", _flow_state(rs in ("已通过", "复审通过"), bool(c["video_url"]))),
        ("闭环", _flow_state(c["is_closed"],
                             rs in ("已通过", "复审通过") and not c["is_closed"])),
    ]
    # 点节点展开对应详情：默认停在当前进行中的步骤
    cur_default = next((i for i, (_, s) in enumerate(steps) if s == "doing"),
                       len(steps) - 1)
    sel = st.session_state.setdefault("detail_steps", {}) \
        .get(collab_id, cur_default)
    sel = max(0, min(sel, len(steps) - 1))
    T.component_html(T.steps_bar(steps, selected=sel, nav_id=collab_id),
                     height=68)
    # 紧跟流程条的 8 个原生按钮：iframe JS 会隐藏它们，并在点节点时"按下"对应按钮
    # → 轻量 rerun，不整页刷新
    for i, (label, _state) in enumerate(steps):
        st.button(label, key=f"stepnav{i}",
                  on_click=_set_detail_step, args=(collab_id, i))

    _render_actions(collab_id, c, sel)


def _render_actions(cid, c, step):
    branches = c["branches"]
    unlocked = all(branches.values())
    rs = c["review_status"]

    if step == 0:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("确认合作"), unsafe_allow_html=True)
            st.markdown(f'合作已确认 · 计划上线 {T.badge(c["plan_month"] or "-")}',
                        unsafe_allow_html=True)
            st.caption("下一步：三分支并行（发Guideline / 签合同 / 选品+GMC校验）")

    elif step == 1:
        # 三分支
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("三分支并行"), unsafe_allow_html=True)
            st.caption("发Guideline / 签合同 / 选品+GMC校验，三者全部完成才解锁下单")
            b1, b2, b3 = st.columns(3)
            with b1:
                st.markdown(T.branch_card("分支A · 发Guideline", branches["guideline"],
                                          "已发送" if branches["guideline"] else "未发送"),
                            unsafe_allow_html=True)
                st.button("撤销" if branches["guideline"] else "标记已发送", key="gb",
                          use_container_width=True,
                          on_click=store.set_branch,
                          args=(cid, "guideline", not branches["guideline"]))
            with b2:
                st.markdown(T.branch_card("分支B · 签合同", branches["contract"],
                                          "已签署" if branches["contract"] else "未签署"),
                            unsafe_allow_html=True)
                st.button("撤销" if branches["contract"] else "标记已签署", key="cb",
                          use_container_width=True,
                          on_click=store.set_branch,
                          args=(cid, "contract", not branches["contract"]))
            with b3:
                st.markdown(T.branch_card("分支C · 选品+GMC校验", branches["gmc"],
                                          "校验通过" if branches["gmc"] else "待校验"),
                            unsafe_allow_html=True)
                st.button("撤销" if branches["gmc"] else "✅ GMC校验通过", key="gc",
                          use_container_width=True,
                          on_click=store.set_branch,
                          args=(cid, "gmc", not branches["gmc"]))
            prods = st.text_area("选品清单（每行一个链接）",
                                 value="\n".join(c["product_list"]), key="prods",
                                 height=80)
            if st.button("💾 保存选品清单", key="sp"):
                store.set_products(cid, [p.strip() for p in prods.splitlines()
                                         if p.strip()])
                st.toast("清单已保存，可增减后重新校验")
                st.rerun()

            # ---- 生成 Guide（分支A 配套）：原版韩文 guide + 千问强带货脚本建议 ----
            st.markdown(T.sub("生成 Guide · 가이드 생성"), unsafe_allow_html=True)
            st.caption("基于原版韩文 가이드，由千问为该网红追加「内容方向 & 强带货脚本建议」；"
                       "生成后可复制 / 下载 Word 发给网红，再回到分支A 标记已发送")
            req = st.text_area("附加要求（选填，「按要求生成」时生效）· 추가 요청 (선택)",
                               key="guide_req", height=70,
                               placeholder="例：这次想强推厨房小物，视频控制在30秒内，"
                                           "重点强调折扣码；网红擅长开箱风格…")
            g1, g2 = st.columns(2)
            if g1.button("⚡ 一键生成 Guide", key="gg1", type="primary",
                         use_container_width=True):
                _gen_guide(cid, c, "")
            if g2.button("📝 按要求生成", key="gg2", use_container_width=True):
                if not req.strip():
                    st.error("请先填写要求，再点「按要求生成」· "
                             "요구사항을 입력한 후 생성하세요")
                else:
                    _gen_guide(cid, c, req.strip())
            guide_md = st.session_state.get(f"guide_{cid}")
            if guide_md:
                st.markdown(guide_md)
                with st.expander("📋 复制全文（点右上角复制按钮）· 전체 복사"):
                    st.code(guide_md, language=None, height=320)
                st.download_button(
                    "⬇ 下载 Word 版 · Word 다운로드",
                    data=G.md_to_docx(guide_md),
                    file_name=f"YTS_가이드_{c['name']}.docx",
                    mime="application/vnd.openxmlformats-officedocument"
                         ".wordprocessingml.document",
                    key="gdocx")

    elif step == 2:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("下单"), unsafe_allow_html=True)
            if not unlocked:
                st.markdown(T.empty_hint("三分支未全部完成，暂不可下单"),
                            unsafe_allow_html=True)
            else:
                st.markdown(f'当前状态：{T.badge("已下单" if c["order_done"] else "未下单")}',
                            unsafe_allow_html=True)
                if st.button("📦 标记已下单", key="od", type="primary",
                             disabled=c["order_done"]):
                    store.mark_order(cid)
                    st.rerun()

    elif step == 3:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("收货"), unsafe_allow_html=True)
            if not c["order_done"]:
                st.markdown(T.empty_hint("先完成「下单」，才能标记收货"),
                            unsafe_allow_html=True)
            else:
                st.markdown(f'当前状态：{T.badge("已收货" if c["received"] else "未收货")}',
                            unsafe_allow_html=True)
                if st.button("🏠 标记已收货", key="rv", type="primary",
                             disabled=c["received"]):
                    store.mark_received(cid)
                    st.rerun()

    elif step == 4:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("拍摄"), unsafe_allow_html=True)
            if not c["received"]:
                st.markdown(T.empty_hint("先完成「收货」，才能开始拍摄"),
                            unsafe_allow_html=True)
            else:
                st.markdown(f'当前状态：{T.badge(c["shoot_status"] or "未开始")}',
                            unsafe_allow_html=True)
                s1, s2 = st.columns(2)
                if s1.button("🎬 拍摄中", key="s1",
                             disabled=c["shoot_status"] == "已完成"):
                    store.mark_shoot(cid, "拍摄中")
                    st.rerun()
                if s2.button("✅ 拍摄完成", key="s2", type="primary",
                             disabled=c["shoot_status"] == "已完成"):
                    store.mark_shoot(cid, "已完成")
                    st.rerun()

    elif step == 5:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("提交审核"), unsafe_allow_html=True)
            if c["shoot_status"] != "已完成":
                st.markdown(T.empty_hint("拍摄完成后，在此录入未公开视频链接推送到审核站"),
                            unsafe_allow_html=True)
            elif not c["video_url"]:
                url = st.text_input("未公开视频链接", key="vurl")
                if st.button("📨 提交审核", key="sr", type="primary") and url.strip():
                    store.submit_review(cid, url.strip())
                    st.toast("已推送至审核站，状态：待审核")
                    st.rerun()
            else:
                st.markdown(f'初审链接：<a class="yts-link" href="{esc(c["video_url"])}" '
                            f'target="_blank">{esc(c["video_url"])}</a>　'
                            + T.badge(rs or "待审核"), unsafe_allow_html=True)
                if rs == "待审核":
                    st.caption("审核进行中 · 视频重新剪辑后可在下方直接换链接，无需撤回重提")
                    with st.expander("🔁 更换初审链接"):
                        new_url = st.text_input("新的未公开视频链接", key="vurl_new")
                        if st.button("💾 保存新链接", key="sv", type="primary") \
                                and new_url.strip():
                            store.update_video_link(cid, new_url.strip())
                            st.toast("初审链接已更新，审核同学将看到新链接")
                            st.rerun()
                else:
                    st.caption("审核进度见「审核」节点")

    elif step == 6:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("审核"), unsafe_allow_html=True)
            if not c["video_url"]:
                st.markdown(T.empty_hint("尚未提交审核，先在「提交审核」节点录入视频链接"),
                            unsafe_allow_html=True)
            elif rs == "待审核":
                st.markdown(f'{T.badge("待审核")}　⏳ 等待审核同学在审核站操作…',
                            unsafe_allow_html=True)
            elif rs == "已驳回":
                st.error(f"驳回原因：{c['review_comment']}")
                st.caption("复审（运营操作）：网红修改后重新提交链接")
                new_url = st.text_input("复审视频链接", key="rurl")
                if st.button("🔄 提交复审", key="rc", type="primary") \
                        and new_url.strip():
                    store.start_recheck(cid, new_url.strip())
                    st.rerun()
            elif rs == "复审中":
                st.warning(f"复审中 · 复审链接：{c['recheck_video_url']}")
                a1, a2 = st.columns([1, 2])
                if a1.button("✅ 复审通过", key="rp", type="primary"):
                    store.recheck_pass(cid)
                    st.rerun()
                reason = a2.text_input("仍不合格的原因", key="rr")
                if a2.button("❌ 仍不合格", key="rr2") and reason.strip():
                    store.recheck_reject(cid, reason.strip())
                    st.rerun()
            else:
                st.markdown(T.badge(rs or "待审核"), unsafe_allow_html=True)
            log = c.get("audit_log") or []
            if log:
                with st.expander(f"📜 审核历史（{len(log)} 条）"):
                    lrows = [[esc(r.get("audit_date", "")),
                              T.badge("已通过" if r.get("audit_result") == "已通过"
                                      else "未通过"),
                              esc(r.get("audit_opinion", ""))] for r in log]
                    st.markdown(T.table(["日期", "结果", "意见"], lrows),
                                unsafe_allow_html=True)

    elif step == 7:
        # 闭环
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("上传视频 & 闭环"), unsafe_allow_html=True)
            if c["is_closed"]:
                st.markdown('<div class="closed-tag" style="font-size:13px">'
                            '✨ 已确认发布 · 流程闭环</div>', unsafe_allow_html=True)
                if c["video_url"]:
                    st.markdown(f'发布链接：<a class="yts-link" href="{esc(c["video_url"])}" '
                                f'target="_blank">{esc(c["video_url"])}</a>',
                                unsafe_allow_html=True)
            elif rs in ("已通过", "复审通过"):
                pub = st.text_input("已发布视频链接（闭环必填）",
                                    value=c["video_url"] or "", key="purl")
                if st.button("✅ 已确认（视频已发布，流程闭环）", key="up", type="primary",
                             use_container_width=True):
                    if not pub.strip():
                        st.warning("请先粘贴已发布视频链接，再闭环")
                    else:
                        store.confirm_uploaded(cid, pub.strip())
                        st.toast("🎉 流程闭环，活动页卡片点亮绿色光晕")
                        st.rerun()
            else:
                st.markdown(T.empty_hint("审核通过后，在此确认视频正式发布，完成闭环"),
                            unsafe_allow_html=True)


# ============================ 分析模块 ============================
def _refresh_video_metrics(recs):
    """闭环视频的播放/点赞/评论每日自动抓取（本地缓存 24h）并回写宜搭。

    返回 collab_id -> 数据来源标记（"auto" 自动抓取 / "待回填" 抓取失败）"""
    states = {}
    if not YT.get_key():
        return states
    for r in recs:
        url = r.get("video_url") or ""
        if not url:
            continue
        stats = YT.fetch_video_stats(url)
        if stats is None:
            states[r["collab_id"]] = "待回填"
            continue
        if (int(stats["views"]) != int(r.get("video_views") or 0)
                or int(stats["likes"]) != int(r.get("video_likes") or 0)
                or int(stats["comments"]) != int(r.get("video_comments") or 0)):
            try:
                store.update_video_metrics(r, stats["views"], stats["likes"],
                                           stats["comments"])
            except Exception:
                pass
        # 页面先用最新值展示（写回宜搭有缓存延迟，这里直接覆盖快照）
        r["video_views"], r["video_likes"], r["video_comments"] = (
            stats["views"], stats["likes"], stats["comments"])
        states[r["collab_id"]] = "auto"
    return states


def page_analysis():
    home_btn()
    st.markdown(T.header("分析模块", "视频互动 + 商品转化概览（播放 / 点击率 / 成交量 / GMV）"),
                unsafe_allow_html=True)
    recs = [r for r in store.list_all() if r.get("plan_month") or r.get("is_closed")]
    closed_recs = [r for r in recs if r.get("is_closed") and r.get("video_url")]
    if closed_recs:
        if YT.get_key():
            with st.spinner("正在同步闭环视频数据（每日一次）…"):
                src_states = _refresh_video_metrics(closed_recs)
        else:
            src_states = {}
            st.caption("配置 YOUTUBE_API_KEY（Secrets）后，闭环视频的播放/点赞/"
                       "评论将每日自动同步")
    else:
        src_states = {}
    months = sorted({r["plan_month"] for r in recs if r.get("plan_month")},
                    reverse=True)
    if months:
        sel = st.pills("月份", ["全部"] + months, default="全部", key="ana_month")
        if sel != "全部":
            recs = [r for r in recs if r["plan_month"] == sel]

    if not recs:
        st.markdown(T.empty_hint("暂无履约/闭环记录：确认合作或流程导入「已闭环」后，"
                                 "自动进这里追踪数据"),
                    unsafe_allow_html=True)
        return

    has_data = [r for r in recs if (r.get("video_views") or r.get("gmv")
                                   or r.get("orders"))]
    tot_gmv = sum(r.get("gmv") or 0 for r in recs)
    tot_orders = sum(r.get("orders") or 0 for r in recs)
    tot_views = sum(r.get("video_views") or 0 for r in recs)
    ctrs = [r["ctr"] for r in recs if r.get("ctr")]
    avg_ctr = sum(ctrs) / len(ctrs) if ctrs else 0
    st.markdown(T.stats_row([
        ("GMV 合计", f"{tot_gmv:,.0f}", "c-green"),
        ("成交量合计", f"{tot_orders:,.0f}", "c-purple"),
        ("播放量合计", f"{tot_views:,.0f}", "c-pink"),
        ("平均 CTR", f"{avg_ctr:.1f}%", "c-amber"),
    ]), unsafe_allow_html=True)

    if not has_data:
        st.caption("指标待回填：闭环后把播放/点赞/成交/GMV 补进宜搭表单，这里自动汇总")

    rows = sorted(recs, key=lambda r: r.get("gmv") or 0, reverse=True)
    trows = []
    for r in rows:
        tag = ' <span class="closed-tag">已闭环</span>' if r.get("is_closed") else ""
        src = src_states.get(r["collab_id"])
        src_tag = ""
        if src == "auto":
            src_tag = ' <span style="color:#1a7f4b;font-size:11px;font-weight:600">自动</span>'
        elif src == "待回填":
            src_tag = (' <span style="color:#b26a09;font-size:11px;font-weight:600"'
                       ' title="视频链接无法抓取：请确认闭环节点填的是正式发布链接">'
                       '待回填</span>')
        trows.append([
            f'<a data-nav="?detail={r["collab_id"]}&from=analysis" '
            f'style="color:#d76a8c;font-weight:700;text-decoration:none">'
            f'{esc(r["name"])}</a>{tag}',
            esc(r.get("plan_month") or "-"),
            f'<span class="num">{r.get("video_views", 0):,}</span>{src_tag}',
            f'<span class="num">{r.get("video_likes", 0):,}</span>',
            f'<span class="num">{r.get("ctr", 0):.1f}%</span>',
            f'<span class="num">{r.get("orders", 0):,}</span>',
            f'<span class="num">{r.get("conversion_rate", 0):.1f}%</span>',
            f'<span class="num"><b>{r.get("gmv", 0):,.0f}</b></span>',
        ])
    # 行内名字带 data-nav 跳转，必须用 iframe 组件渲染（st.markdown 会吞掉点击）
    T.component_html(
        T.table(["昵称", "月份", "播放量", "点赞", "CTR", "成交量",
                 "转化率", "GMV"], trows, wrap=False),
        height=52 + len(trows) * 36)
    if any(v == "待回填" for v in src_states.values()):
        st.caption("「待回填」：视频链接无法抓取（多为未公开/失效链接），"
                   "请到详情页「编辑信息」更换为正式发布链接，或回宜搭手工回填")

    top = [r for r in rows if r.get("gmv")][:10]
    if top:
        df = pd.DataFrame({"GMV": [r["gmv"] for r in top]},
                          index=[r["name"] for r in top])
        st.markdown(T.sub("GMV Top"), unsafe_allow_html=True)
        st.bar_chart(df, horizontal=True, height=320, color=["#dd8fa8"])

    st.markdown(T.foot("指标由运营回填至宜搭表单后自动展示"), unsafe_allow_html=True)


# ============================ 路由 ============================
_qp = st.query_params
if _qp.get("detail"):
    _d = _qp.get("detail")
    del st.query_params["detail"]
    if _qp.get("step"):
        try:
            st.session_state.setdefault("detail_steps", {})[_d] = int(_qp.get("step"))
        except ValueError:
            pass
        del st.query_params["step"]
    _frm = _qp.get("from") or ""
    st.session_state["detail_from"] = (
        _frm if _frm in ("activity", "dig", "analysis", "home")
        else st.session_state.get("page", "home"))
    if _qp.get("from"):
        del st.query_params["from"]
    go("detail", collab_id=_d)
elif _qp.get("act") == "neg" and _qp.get("id"):
    _i = _qp.get("id")
    del st.query_params["act"]
    del st.query_params["id"]
    store.mark_negotiating(_i)
    st.session_state.page = "dig"
    st.toast("已标记「洽谈中」，网红已流入活动模块")
    st.rerun()
elif _qp.get("act") == "mail" and _qp.get("id"):
    _i = _qp.get("id")
    del st.query_params["act"]
    del st.query_params["id"]
    store.mark_emailed(_i)
    st.session_state.page = "dig"
    st.toast("已标记「已发邮件」，留在挖掘池，待标记「洽谈中」")
    st.rerun()

page = st.session_state.page
if page == "dig":
    page_dig()
elif page == "activity":
    page_activity()
elif page == "detail":
    page_detail(st.session_state.get("collab_id"))
elif page == "analysis":
    page_analysis()
else:
    page_home()
