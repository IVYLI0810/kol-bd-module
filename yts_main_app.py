#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网红管理系统 - 主管理后台（裸粉 · Apple 极简版）"""
import html
import io
import os
import re
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st

from yts_yida_store import get_yts_store, YidaFetchError
import yts_theme as T
import yts_guide_gen as G
import yts_roster as R
import yts_yt_stats as YT
import yts_gmc as GMC
import yts_contract as C
from yts_import_flow import norm_month, norm_date

st.set_page_config(page_title="YTS 全栈项目管理", page_icon="🎯", layout="wide",
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


def flash(level, msg):
    """存一条消息，下次渲染时显示（st.rerun 会冲掉当场的 st.success/warning）。
    level: ok / warn / err。用于展示待办发送结果等跨 rerun 提示"""
    st.session_state["_flash"] = (level, msg)


def _render_flash():
    f = st.session_state.pop("_flash", None)
    if f:
        {"ok": st.success, "warn": st.warning,
         "err": st.error}[f[0]](f[1])


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
        # 身份集合：(频道ID, 月份) → 判断每行是新增行还是更新已有行
        _, _ex_cid_m = getattr(store, "existing_url_months",
                               lambda: (set(), set()))()
        preview, pend = [], []
        for raw in rows:
            url = str(raw["channel_url"]).strip()
            cid, resolved, is_existing = ids[url]
            rec = FI.derive_record(raw, cid)
            # 归一化时没认出的拍摄状态原值：提示人工核对（不能带进库）
            raw_ss = rec.pop("_shoot_raw", "")
            if raw_ss:
                st.warning(f"「{rec['channel_name']}」的拍摄状态「{raw_ss}」不是系统写法，"
                           f"已按「{rec.get('shoot_status') or '-'}」导入，"
                           "导入后请到详情页拍摄节点核对")
            # 有进度但没填归属月份 → 已自动补月（否则进不了活动模块履约）
            auto_m = rec.pop("_plan_auto", "")
            if auto_m:
                st.warning(f"「{rec['channel_name']}」没填归属月份，已按进度自动补为"
                           f"「{auto_m}」以便流入履约；月份不对可到履约详情里改")
            # 一个单元格多条链接 → 已拆成多条视频行
            split_n = rec.pop("_split_n", 0)
            if split_n:
                st.info(f"「{rec['channel_name']}」填了 {split_n} 条视频链接，"
                        f"已自动拆为 {split_n} 条视频行（播放等指标先挂首链接）")
            # 标了已闭环但没填链接 → 先按未闭环导入
            if rec.pop("_closed_no_link", False):
                st.warning(f"「{rec['channel_name']}」标了已闭环但没填视频链接："
                           "闭环必须以视频链接为准，本行先按未闭环导入，"
                           "请到详情页登记发布视频后再闭环")
            # 新增 or 更新：按「频道ID+月份」身份判断
            # （老网红新月份 = 新增一条月份行；同月重传 = 更新原行）
            _m = str(rec.get("plan_month") or "").strip()
            is_new = ((cid, _m) not in _ex_cid_m) if _ex_cid_m else not is_existing
            if rec.get("stage") == "已完成":
                prog = "已闭环 → 分析模块"
            elif rec.get("shoot_status") == "已完成":
                prog = "履约中 · 拍摄已完成"
            elif rec.get("shoot_status") == "拍摄中":
                prog = "履约中 · 拍摄中"
            else:
                prog = rec.get("stage") or "挖掘池"
            preview.append({
                "频道名称": rec["channel_name"], "负责人": rec["recruiter"],
                "归属月份": rec.get("plan_month", "") or "-",
                "导入后进度": prog,
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


def product_import_panel():
    """选品清单批量导入：上传「网红×商品」Excel → 匹配系统网红 → 预览 → 写入"""
    import yts_product_import as PI
    with st.container(border=True):
        st.markdown("**🛒 选品清单批量导入** · 上传「网红×商品」表（如 7月/8月YTS网红x商品），"
                    "自动按频道匹配系统里的网红，把商品链接填进各自的选品清单。"
                    "上传后先预览匹配结果，确认后再写入。")
        up = st.file_uploader("上传「网红×商品」Excel", type=["xlsx", "xls"],
                              key="pi_up")
        if up is None:
            return
        groups, issues = PI.parse_product_workbook(up.read())
        for msg in issues[:8]:
            st.warning(msg)
        if not groups:
            st.error("没有解析到有效的网红×商品数据，请确认表格格式")
            return

        matched = PI.match_groups(groups, store.list_all())
        mode = st.radio("写入方式", ["合并（保留已有选品，追加新的）",
                                     "覆盖（清空旧选品，只留本次）"],
                        horizontal=True, key="pi_mode")
        preview = []
        for m in matched:
            g, rec = m["group"], m["matched"]
            preview.append({
                "月份": g["month"] or "-",
                "频道名称": g["name"],
                "负责人": g["recruiter"] or "-",
                "匹配结果": (f"✅ {rec['name']}" if rec else "❌ 未匹配"),
                "匹配方式": m["match_by"] or "-",
                "商品数": len(g["products"]),
            })
        st.dataframe(preview, use_container_width=True, hide_index=True)
        n_ok = sum(1 for m in matched if m["matched"])
        n_prod = sum(len(m["group"]["products"]) for m in matched if m["matched"])
        st.caption(f"共 {len(matched)} 位网红：匹配成功 {n_ok}（商品 {n_prod} 个）、"
                   f"未匹配 {len(matched) - n_ok}")
        if n_ok < len(matched):
            st.warning("未匹配的网红不会写入。请确认这些网红已在系统里"
                       "（可先到挖掘/活动模块导入），或核对表中频道名称")

        if st.button(f"✅ 确认写入 {n_ok} 位网红的选品清单", type="primary",
                     use_container_width=True, key="pi_go",
                     disabled=n_ok == 0):
            ok_n = 0
            for m in matched:
                rec = m["matched"]
                if not rec:
                    continue
                new_urls = [p["url"] for p in m["group"]["products"]]
                if mode.startswith("合并"):
                    final = PI.merge_product_lists(rec.get("product_list") or [],
                                                   new_urls)
                else:
                    final = new_urls
                store.set_products(rec["collab_id"], final)
                ok_n += 1
            st.session_state["product_import_open"] = False
            st.toast(f"已写入 {ok_n} 位网红的选品清单")
            st.rerun()


def _fix_zero_subscribers():
    """补频道粉丝数：找出粉丝为0的记录，从 YouTube 主页抓取真实粉丝数写回"""
    zero = [p["id"] for p in store.list_pool()
            if (p.get("followers") or 0) == 0]
    if not zero:
        st.toast("没有粉丝数为 0 的记录，无需补充")
        return
    if not YT.get_key():
        st.warning("未配置 YOUTUBE_API_KEY：无法抓取 YouTube 频道数据。"
                   "请在 Streamlit Cloud → Settings → Secrets 添加后重试")
        return
    with st.spinner(f"正在从 YouTube 抓取 {len(zero)} 个频道的粉丝数…"):
        n = store.sync_yt_subscribers(zero)
    if n:
        st.toast(f"已补充 {n} 个频道的粉丝数（其余频道可能未公开或链接无效）")
    else:
        st.warning("未能抓到任何粉丝数：请确认已配置 YOUTUBE_API_KEY，"
                   "且这些频道的粉丝数在 YouTube 上公开可见")


def page_dig():
    home_btn()
    h1, h2, h3 = st.columns([4, 1, 1])
    with h1:
        st.markdown(T.header("挖掘模块",
                             "挖掘站「已发邮件」自动入池；点右上「同步挖掘站」"
                             "把粉丝量等基础信息刷进宜搭"),
                    unsafe_allow_html=True)
    with h2:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        if st.button("🔄 同步挖掘站", key="btn_sync_dig", use_container_width=True,
                     help="把挖掘站基础信息刷进宜搭；粉丝量以挖掘站最新值覆盖更新，"
                          "邮箱仅空缺时补齐，不覆盖已有值"):
            st.session_state["dig_sync_ts"] = 0
            st.session_state["dig_force"] = True
            st.rerun()
    with h3:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        if _is_data_owner():
            if st.button("📡 补频道粉丝数", key="btn_fix_subs",
                         use_container_width=True,
                         help="对粉丝数为0的记录，从 YouTube 频道主页抓取真实粉丝数"
                              "写回宜搭（负责人专属）"):
                _fix_zero_subscribers()
        else:
            st.markdown('<div style="height:38px"></div>',
                        unsafe_allow_html=True)
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
            basic = store.sync_basic_info(force=force, progress=_cb,
                                          limit=0 if force else 30) \
                if getattr(store, "sync_basic_info", None) \
                else {"updated": 0, "emails_filled": 0}
        if bar:
            bar.empty()
        st.session_state["dig_sync_ts"] = time.time()
        if res["added"] or res["patched"] or back or basic["updated"]:
            st.toast(f"已同步挖掘站：新增 {res['added']} 位、补信息 {res['patched']} 位"
                     f"、回流已引入 {back} 位"
                     + (f"、基础信息同步 {basic['updated']} 位"
                        if basic["updated"] else "")
                     + (f"（其中补邮箱 {basic['emails_filled']} 位）"
                        if basic.get("emails_filled") else ""))
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
        mark_actions = []  # [(inf_id, act)]，与 #mark= 链接同序
        for p in rows[(cur - 1) * PAGE: cur * PAGE]:
            # 昵称 → 可点进 YouTube 主页
            url = (p.get("url") or "").strip()
            pid = (p.get("id") or "").strip()
            if not url and pid.startswith("UC"):
                url = f"https://www.youtube.com/channel/{pid}"
            elif not url and pid.startswith("@"):
                url = f"https://www.youtube.com/{pid}"
            if url:
                name_cell = (f'<a class="nl" title="打开YouTube主页" '
                             f'data-nav="#open={quote(url, safe="")}">'
                             f'{esc(p.get("name") or pid)}</a>')
            else:
                name_cell = f'<b>{esc(p.get("name") or pid)}</b>'

            if not p.get("emailed"):
                st_cell = (f'<a class="act act-y" data-nav="#mark={len(mark_actions)}">'
                           f'标记已发邮件</a>')
                mark_actions.append((p["id"], "mail"))
            elif (p.get("stage") or "") in ("", "已发邮件"):
                st_cell = (f'<a class="act act-b" data-nav="#mark={len(mark_actions)}">'
                           f'标记洽谈中</a>')
                mark_actions.append((p["id"], "neg"))
                st_cell += (f' <a class="act act-u" title="取消「已发邮件」标记" '
                            f'data-nav="#mark={len(mark_actions)}">↩ 取消</a>')
                mark_actions.append((p["id"], "unmail"))
            elif p.get("stage") == "洽谈中":
                st_cell = T.badge("洽谈中")
                st_cell += (f' <a class="act act-u" title="取消「洽谈中」，退回已发邮件" '
                            f'data-nav="#mark={len(mark_actions)}">↩ 取消</a>')
                mark_actions.append((p["id"], "unneg"))
            else:
                st_cell = T.badge("已流入活动")
            trows.append([
                name_cell,
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
        # 紧跟 iframe 的隐藏点击靶：JS 会隐藏它们，点表格里的标记链接
        # 时"按下"对应按钮 → 轻量 rerun（不整页跳转，消除点击卡顿）
        def _mark_cb(iid, act):
            if act == "mail":
                store.mark_emailed(iid)
                st.toast("已标记「已发邮件」，待标记「洽谈中」后流入活动")
            elif act == "neg":
                store.mark_negotiating(iid)
                st.toast("已标记「洽谈中」，网红已流入活动模块")
            elif act == "unmail":
                store.unmark_emailed(iid)
                st.toast("已取消「已发邮件」标记，回到未触达状态")
            elif act == "unneg":
                store.unmark_negotiating(iid)
                st.toast("已取消「洽谈中」，退回已发邮件状态")

        for i, (iid, act) in enumerate(mark_actions):
            st.button(f"mark{i}", key=f"digmark{i}",
                      on_click=_mark_cb, args=(iid, act))

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


def _export_all_data():
    """导出全量数据：网红汇总 + 视频明细两个 Sheet"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    with st.spinner("正在导出全量数据..."):
        all_recs = store.list_all()

        wb = Workbook()

        # Sheet 1: 网红汇总
        ws1 = wb.active
        ws1.title = "网红汇总"
        headers1 = [
            "频道ID", "频道名称", "负责人", "归属月份", "垂类", "报价",
            "频道链接", "联系邮箱", "粉丝数",
            "Guideline", "合同", "GMC校验",
            "下单", "收货", "拍摄状态", "审核状态", "闭环",
            "选品清单", "视频链接", "复审链接",
            "播放", "点赞", "评论", "点击", "CTR", "成交", "GMV",
            "备注",
        ]
        ws1.append(headers1)
        for r in all_recs:
            branches = r.get("branches", {})
            ws1.append([
                r.get("channel_id", ""),
                r.get("name", ""),
                r.get("recruiter", ""),
                r.get("plan_month", ""),
                r.get("category", ""),
                r.get("price", 0),
                r.get("channel_url", ""),
                r.get("email", ""),
                r.get("followers", 0),
                "已发送" if branches.get("guideline") else "",
                "已签" if branches.get("contract") else "",
                "校验通过" if branches.get("gmc") else "",
                "已下单" if r.get("order_done") else "",
                "已收货" if r.get("received") else "",
                r.get("shoot_status", ""),
                r.get("review_status", ""),
                "已闭环" if r.get("is_closed") else "",
                "\n".join(r.get("product_list") or []),
                r.get("video_url", ""),
                r.get("recheck_video_url", ""),
                r.get("video_views", 0),
                r.get("video_likes", 0),
                r.get("video_comments", 0),
                r.get("product_views", 0),
                r.get("ctr", 0),
                r.get("orders", 0),
                r.get("gmv", 0),
                r.get("notes", ""),
            ])

        # Sheet 2: 视频明细
        ws2 = wb.create_sheet("视频明细")
        headers2 = [
            "频道ID", "频道名称", "负责人", "归属月份",
            "视频链接", "视频类型", "挂载商品ID", "挂载商品数",
            "播放", "点赞", "评论", "点击", "CTR", "成交", "GMV",
        ]
        ws2.append(headers2)
        for r in all_recs:
            videos = r.get("videos") or []
            if videos:
                for v in videos:
                    ws2.append([
                        r.get("channel_id", ""),
                        r.get("name", ""),
                        r.get("recruiter", ""),
                        r.get("plan_month", ""),
                        v.get("video_url", ""),
                        v.get("video_type", ""),
                        v.get("product_ids", ""),
                        len([p for p in str(v.get("product_ids") or "").split(",") if p.strip()]),
                        v.get("views", 0),
                        v.get("likes", 0),
                        v.get("comments", 0),
                        v.get("clicks", 0),
                        v.get("ctr", 0),
                        v.get("orders", 0),
                        v.get("gmv", 0),
                    ])
            else:
                # 无视频子表的记录：用主链接占一行
                ws2.append([
                    r.get("channel_id", ""),
                    r.get("name", ""),
                    r.get("recruiter", ""),
                    r.get("plan_month", ""),
                    r.get("video_url", ""),
                    "",
                    "",
                    0,
                    r.get("video_views", 0),
                    r.get("video_likes", 0),
                    r.get("video_comments", 0),
                    r.get("product_views", 0),
                    r.get("ctr", 0),
                    r.get("orders", 0),
                    r.get("gmv", 0),
                ])

        # 样式
        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        for ws in [ws1, ws2]:
            for col_idx, _ in enumerate(ws[1], 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")
            ws.freeze_panes = "A2"

        # 保存
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "⬇ 下载 YTS 全量数据",
            data=buf.getvalue(),
            file_name=f"YTS全量数据_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_export_all",
            use_container_width=True,
        )
        st.toast(f"已导出 {len(all_recs)} 条网红记录")


def page_activity():
    home_btn()
    # 审核状态快速同步（写入就反馈）：审核站与主站是两个进程、缓存不通，
    # 这里每次打开活动模块就把「待审核/已驳回待复审」的记录逐条直查宜搭
    # （通常只有几条，1-2秒），审核站的驳回/通过几秒内即可见，无需手动刷新
    if getattr(store, "sync_review_states", None) and \
            time.time() - st.session_state.get("act_sync_ts", 0) > 20:
        st.session_state["act_sync_ts"] = time.time()
        try:
            changed = store.sync_review_states()
        except Exception:
            changed = []
        for nm in changed:
            st.toast(f"🔄 审核状态已更新：{nm}")
    h1, h2 = st.columns([5, 1])
    with h1:
        st.markdown(T.header("活动模块", "选择你的名字，管理你挖掘的网红"),
                    unsafe_allow_html=True)
    with h2:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        _fi_open = st.session_state.get("flow_import_open", False)
        _pi_open = st.session_state.get("product_import_open", False)
        if st.button("✕ 收起导入面板" if _fi_open else " 流程导入",
                     key="btn_flow_import", use_container_width=True):
            st.session_state["flow_import_open"] = not _fi_open
            st.session_state["product_import_open"] = False
            st.rerun()
        if st.button("✕ 收起选品导入" if _pi_open else "🛒 选品清单导入",
                     key="btn_product_import", use_container_width=True):
            st.session_state["product_import_open"] = not _pi_open
            st.session_state["flow_import_open"] = False
            st.rerun()
        if st.button(" 导出全量数据", key="btn_export_all",
                     use_container_width=True):
            _export_all_data()
    if st.session_state.get("flow_import_open"):
        flow_import_panel()
    if st.session_state.get("product_import_open"):
        product_import_panel()

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
            cid = c["collab_id"]
            # 点开卡片才出现表单（默认收起，页面更清爽）
            with st.expander(
                    f"**{c['name']}** · {esc(c.get('category') or '-')} · "
                    f"{c.get('followers', 0):,} 粉丝",
                    key=f"neg_exp_{cid}"):
                month = st.text_input("上线月份", NOW_MONTH, key=f"m_{cid}")
                price = st.number_input("报价（韩币）", min_value=0,
                                        step=10000,
                                        value=int(c.get("price") or 0),
                                        key=f"p_{cid}")
                reuse = st.radio("能否二次利用", ["请选择", "可二次利用", "不可二次利用"],
                                 horizontal=True, key=f"ru_{cid}",
                                 help="必填：该网红内容/账号后续能否二次利用"
                                      "（如剪辑复用、二次分发等）")
                note = st.text_input("结算备注（选填）",
                                     value=c.get("settlement_note") or "",
                                     key=f"sn_{cid}",
                                     placeholder="如：二次利用需另付50%费用等补充说明")
                if st.button("确认合作", key=f"ok_{cid}", type="primary",
                             use_container_width=True):
                    if price <= 0:
                        st.warning("请先填写报价（韩币）再确认合作")
                    elif reuse == "请选择":
                        st.warning("请先选择「能否二次利用」再确认合作")
                    else:
                        store.confirm_collab(cid, month, price,
                                             reusable=(reuse == "可二次利用"),
                                             settle_note=note)
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


def _auto_gmc_check(cid, c):
    """分支C 自动校验：提取选品商品ID → 逐个查 GMC 池 → 全在池才点亮分支C"""
    if not GMC.configured():
        st.error("未配置 GMC 凭证：请在 Streamlit Cloud → Settings → Secrets 添加 "
                 "[gmc] 段（client_email / private_key / merchant_id / feed_label），"
                 "配置方法见《GMC 自动校验配置指引》。配置前请继续用手动「GMC校验通过」")
        return
    prods = c.get("product_list") or []
    if not prods:
        st.warning("选品清单为空：先在下方「选品清单」填入商品链接并保存，再自动校验")
        return
    with st.spinner(f"正在校验 {len(prods)} 个商品是否在 GMC 池…"):
        results = GMC.check_products(prods)
    if not results:
        st.warning("未能从选品清单提取商品ID，请检查链接格式")
        return
    rows = [[oid, T.badge("在池 ✅" if r["ok"] else "不在池 ❌"),
             esc(r["msg"])] for oid, r in results.items()]
    st.markdown(T.table(["商品ID", "校验结果", "说明"], rows),
                unsafe_allow_html=True)
    if all(r["ok"] for r in results.values()):
        if not c["branches"]["gmc"]:
            store.set_branch(cid, "gmc", True)
        st.toast(f"✅ 全部 {len(results)} 个商品都在 GMC 池内，分支C 已自动点亮")
        st.rerun()
    else:
        bad = [oid for oid, r in results.items() if not r["ok"]]
        st.error(f"{len(bad)} 个商品不在池内：{'、'.join(bad)}。"
                 "请更换选品或联系 GMC 管理员入池后重试")


def _gen_guide(cid, c, req):
    """调 AI 生成「定制选题&爆款逻辑」，组装完整 guide 存 session"""
    with st.spinner("AI 正在生成选题&爆款逻辑建议（约1-3分钟，期间请勿操作页面）· 생성 중..."):
        try:
            script = G.call_dashscope(G.build_prompt(c, req))
        except RuntimeError as e:
            st.error(str(e))
            return
    st.session_state[f"guide_{cid}"] = G.assemble_full_guide(script)
    st.toast("Guide 生成完成 · 가이드 생성 완료")


def _gen_scripts(cid, c):
    """选品后：AI 结合商品+网红风格，出 3 个爆款脚本框架（只给框架不写全台词）"""
    with st.spinner("AI 正在根据选品制作脚本框架（约1-3分钟，期间请勿操作页面）· 생성 중..."):
        try:
            scr = G.call_dashscope(G.build_script_prompt(c))
        except RuntimeError as e:
            st.error(str(e))
            return
    st.session_state[f"scripts_{cid}"] = scr
    st.toast("脚本框架生成完成 · 스크립트 생성 완료")


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
            e7, e8 = st.columns(2)
            settle_v = e7.radio("能否二次利用",
                                ["请选择", "可二次利用", "不可二次利用"],
                                index=["", "可二次利用", "不可二次利用"].index(
                                    c.get("settlement") or "")
                                if (c.get("settlement") or "") in
                                ("可二次利用", "不可二次利用") else 0,
                                horizontal=True, key="ed_settle")
            settle_note_v = e8.text_input(
                "结算备注", value=c.get("settlement_note") or "", key="ed_snote",
                placeholder="如：二次利用需另付50%费用等")
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
                    "settlement": "" if settle_v == "请选择" else settle_v,
                    "settlement_note": settle_note_v,
                })
                # 月份变了 → 身份串跟着变（频道ID#月份），会话ID就地更新，
                # 否则 rerun 后按旧身份找不到记录
                _cid_part = cid.split("#", 1)[0]
                _old_m = cid.split("#", 1)[1] if "#" in cid else ""
                if month_s != _old_m:
                    st.session_state["collab_id"] = (
                        f"{_cid_part}#{month_s}" if month_s else _cid_part)
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
    c = store.get_collab(collab_id, fresh=True)  # 直查宜搭：审核状态实时，免手动刷新
    if not c:
        st.error("未找到该合作记录")
        return
    # 改过月份后身份串会变（频道ID#月份）：会话里的旧ID就地跟上，
    # 否则后续按钮操作会写空
    if c["collab_id"] != collab_id:
        collab_id = c["collab_id"]
        st.session_state["collab_id"] = collab_id
    _render_flash()  # 显示上一步操作的提示（如待办发送结果）
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
    _yt_cid = c.get("channel_id") or c["collab_id"]
    yt = YT.cached(_yt_cid)
    if yt is None and YT.get_key() and _yt_cid.startswith("UC"):
        with st.spinner("正在同步频道播放数据…"):
            yt = YT.fetch_stats(_yt_cid)
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
        ("提交审核", _flow_state(
            bool(c["video_url"]) or rs in ("已通过", "复审通过"),
            c["shoot_status"] == "已完成" and not c["video_url"]
            and rs not in ("已通过", "复审通过"))),
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
    _render_danger_zone(collab_id, c, sel, steps)


def _confirm_btn(key, label, confirm_label, fn, danger=False):
    """二次确认按钮：第一次点显示确认态，第二次点才执行"""
    ck = f"cfm_{key}"
    if st.session_state.get(ck):
        cols = st.columns([1, 1])
        if cols[0].button(confirm_label, key=f"{key}_yes",
                          type="primary" if danger else "secondary"):
            st.session_state.pop(ck, None)
            fn()
        if cols[1].button("取消", key=f"{key}_no"):
            st.session_state.pop(ck, None)
            st.rerun()
    else:
        if st.button(label, key=key):
            st.session_state[ck] = True
            st.rerun()


def _render_danger_zone(cid, c, sel, steps):
    """更多操作：步骤回退 / 取消合作 / 流回挖掘库 / 淘汰 / 彻底删除（均二次确认）"""
    with st.expander("⚙️ 更多操作（回退 / 取消 / 流回 / 淘汰 / 删除）"):
        st.caption("以下操作会改变流程状态，均需要二次确认，请谨慎操作")
        # 1) 回退当前步骤
        label, state = steps[sel]
        if state == "done":
            _confirm_btn(
                f"undo{sel}", f"↩ 回退「{label}」",
                f"确认回退「{label}」？该步骤将回到未完成",
                lambda: (store.undo_step(cid, sel), st.toast(f"已回退「{label}」"),
                         st.rerun()))
        elif sel == 4 and state == "doing" \
                and (c.get("shoot_status") or "") == "拍摄中":
            _confirm_btn(
                "undo4", "↩ 回退「拍摄中」",
                "确认回退「拍摄中」？回到收货·待拍摄",
                lambda: (store.undo_step(cid, 4),
                         st.toast("已回退：拍摄中 → 收货（待拍摄）"), st.rerun()))
        else:
            st.caption(f"当前步骤「{label}」未完成，无需回退")
        st.divider()
        # 2) 取消合作 / 流回挖掘库 / 淘汰
        c1, c2, c3 = st.columns(3)
        with c1:
            _confirm_btn(
                "cancel", "🚫 取消合作", "确认取消合作？退回洽谈中",
                lambda: (store.cancel_collab(cid), st.toast("已取消合作，退回洽谈中"),
                         go("activity")), danger=True)
        with c2:
            _confirm_btn(
                "backpool", "🔙 流回挖掘库", "确认流回挖掘库？合作进度清空",
                lambda: (store.back_to_pool(cid), st.toast("已流回挖掘库"),
                         go("dig")), danger=True)
        with c3:
            _confirm_btn(
                "remove", "🗑 淘汰网红", "确认淘汰？从挖掘库彻底移除",
                lambda: (store.remove_influencer(cid), st.toast("已淘汰该网红"),
                         go("dig")), danger=True)
        st.divider()
        # 3) 彻底删除记录（真删除，不可恢复，单独一行强调风险）
        month = c.get("plan_month") or ""
        tip = f"确认彻底删除「{c['name']}」" + (f"（{month}）" if month else "") + \
              " 这条记录？数据将从宜搭永久删除，无法恢复！"
        _confirm_btn(
            "harddelete", "💥 彻底删除此记录（不可恢复）", tip,
            lambda: (store.remove_record(cid),
                     st.toast(f"已删除「{c['name']}」" + (f"（{month}）" if month else "")),
                     go("activity")), danger=True)


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
            _settle = c.get("settlement") or ""
            if _settle:
                _badge = T.badge(_settle)
                _note = c.get("settlement_note") or ""
                _note_html = (f' · <span style="color:#86868b;font-size:12px">'
                              f'{esc(_note)}</span>') if _note else ""
                st.markdown(f'能否二次利用：{_badge}{_note_html}',
                            unsafe_allow_html=True)
            st.caption("下一步：三分支并行（发Guideline / 签合同 / 选品+GMC校验）")

    elif step == 1:
        # 三分支
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("三分支并行"), unsafe_allow_html=True)
            st.caption("发Guideline / 签合同 / 选品+GMC校验，三者全部完成才解锁下单；"
                       "点击下方对应模块展开相应工具")
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
            # ---- 三分支工具折叠化：点对应模块才展开内容，不再一屏全铺开 ----
            _default_open = None
            for _bk, _ek in (("guideline", "a"), ("contract", "b"), ("gmc", "c")):
                if not branches[_bk]:
                    _default_open = _ek
                    break
            _st_a = "✅ 已发送" if branches["guideline"] else "未发送"
            _st_b = "✅ 已签署" if branches["contract"] else "未签署"
            _st_c = "✅ 校验通过" if branches["gmc"] else "待校验"

            with st.expander(f"📤 分支A · 生成 Guide & 视频脚本推荐 · {_st_a}",
                             expanded=(_default_open == "a")
                             or bool(st.session_state.get(f"guide_{cid}"))
                             or bool(st.session_state.get(f"scripts_{cid}"))):
                # ---- 生成 Guide：原版韩文 guide + AI 定制选题&爆款逻辑 ----
                st.caption("基于原版韩文 가이드，由 AI 为该网红定制「选题 & 爆款逻辑」（选品前不给具体脚本）；"
                           "选品（分支C）保存后用下方「视频脚本推荐」出脚本框架；生成后可复制 / 下载 Word 发给网红，"
                           "再回到上方卡片标记已发送")
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

                # ---- 视频脚本推荐（选品后解锁）：AI 结合选品出 3 个爆款脚本框架 ----
                st.markdown(T.sub("视频脚本推荐 · 영상 스크립트 추천"),
                            unsafe_allow_html=True)
                has_prods = bool(c.get("product_list"))
                if has_prods:
                    st.caption("选品已保存，已解锁：AI 结合商品 + 该网红内容风格，出 3 个爆款脚本框架"
                               "（只给主题角度 / 时间轴结构 / 转化点框架，不写全台词）")
                else:
                    st.caption("在下方「分支C · 选品清单」保存商品链接后，这里解锁脚本框架生成"
                               "（选品前 Guide 只提供选题 & 爆款逻辑）")
                if st.button("🎬 生成视频脚本推荐", key="sg1", type="primary",
                             use_container_width=True, disabled=not has_prods):
                    _gen_scripts(cid, c)
                scr_md = st.session_state.get(f"scripts_{cid}")
                if scr_md:
                    st.markdown(scr_md)
                    with st.expander("📋 复制全文（点右上角复制按钮）· 전체 복사"):
                        st.code(scr_md, language=None, height=320)
                    st.download_button(
                        "⬇ 下载 Word 版 · Word 다운로드",
                        data=G.md_to_docx(scr_md),
                        file_name=f"YTS_스크립트_{c['name']}.docx",
                        mime="application/vnd.openxmlformats-officedocument"
                             ".wordprocessingml.document",
                        key="sdocx")

            with st.expander(f"📄 分支B · 合同生成 · {_st_b}",
                             expanded=(_default_open == "b")
                             or bool(st.session_state.get(f"ct_doc_{cid}"))):
                st.caption("已自动带出系统里的信息（网红名 / 报价 / 频道 / 交稿截止），"
                           "核对无误后生成正式合同 Word，发给网红签字")
                with st.container(border=True):
                    with st.form(f"ct_form_{cid}"):
                        f1, f2, f3 = st.columns(3)
                        ct_name = f1.text_input("网红名 · 크리에이터명",
                                                value=c["name"], key="ct_name")
                        ct_amount = f2.number_input(
                            "合同金额（韩币） · 계약금액", min_value=0, step=10000,
                            value=int(c.get("price") or 0), key="ct_amount")
                        ct_url = f3.text_input("频道链接 · 채널 URL",
                                               value=c.get("channel_url") or "",
                                               key="ct_url")
                        f4, f5, _f6 = st.columns(3)
                        ct_dl = f4.text_input("交付日期 · 납품일（YYYY-MM-DD）",
                                              value=c.get("submit_deadline") or "",
                                              key="ct_dl")
                        ct_sign = f5.text_input("签署日期 · 서명일（默认当天）",
                                                value=datetime.now().strftime("%Y-%m-%d"),
                                                key="ct_sign")
                        st.caption("平台默认填写 YouTube 영상；网红个人信息"
                                   "（生日 / 地址 / 收款账户 / 税类型）在合同中留空，"
                                   "由网红本人填写")
                        if st.form_submit_button("📄 核对完毕，生成合同",
                                                 type="primary",
                                                 use_container_width=True):
                            if not ct_name.strip():
                                st.error("网红名不能为空")
                            elif not ct_amount:
                                st.error("合同金额为 0，请先填写金额（或在上方编辑信息里补报价）")
                            else:
                                try:
                                    doc_bytes = C.generate_contract({
                                        "name": ct_name.strip(),
                                        "amount": ct_amount,
                                        "channel_url": ct_url.strip(),
                                        "delivery_date": ct_dl.strip(),
                                        "sign_date": ct_sign.strip(),
                                    })
                                    st.session_state[f"ct_doc_{cid}"] = (
                                        doc_bytes, C.contract_filename(ct_name.strip()))
                                    st.toast("合同已生成，点下方按钮下载")
                                except FileNotFoundError:
                                    st.error("未找到合同模板文件，请联系管理员")
                                except Exception as e:
                                    st.error(f"合同生成失败：{e}")
                ct_saved = st.session_state.get(f"ct_doc_{cid}")
                if ct_saved:
                    st.download_button(
                        f"⬇ 下载合同 · {ct_saved[1]}",
                        data=ct_saved[0], file_name=ct_saved[1],
                        mime="application/vnd.openxmlformats-officedocument"
                             ".wordprocessingml.document",
                        key="ct_dl_btn", use_container_width=True)
                    st.caption("网红签回后，回到上方卡片点「标记已签署」")

            with st.expander(f"🛍 分支C · 选品 + GMC 校验 · {_st_c}",
                             expanded=(_default_open == "c")):
                prods = st.text_area("选品清单（每行一个链接）",
                                     value="\n".join(c["product_list"]), key="prods",
                                     height=80)
                if st.button("💾 保存选品清单", key="sp", use_container_width=True):
                    store.set_products(cid, [p.strip() for p in prods.splitlines()
                                             if p.strip()])
                    st.toast("清单已保存")
                    st.rerun()

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
                if c["shoot_status"] == "拍摄中":
                    st.markdown("")
                    _confirm_btn(
                        "undo_shoot", "↩ 回退到收货（撤销拍摄中）",
                        "确认撤销「拍摄中」？回到收货·待拍摄",
                        lambda: (store.undo_step(cid, 4),
                                 st.toast("已回退：拍摄中 → 收货（待拍摄）"),
                                 st.rerun()))

    elif step == 5:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(T.sub("提交审核"), unsafe_allow_html=True)
            if c["shoot_status"] != "已完成":
                st.markdown(T.empty_hint("拍摄完成后，在此录入未公开视频链接推送到审核站"),
                            unsafe_allow_html=True)
            elif not c["video_url"] and rs not in ("已通过", "复审通过"):
                url = st.text_input("未公开视频链接", key="vurl")
                if st.button("📨 提交审核", key="sr", type="primary") and url.strip():
                    ok, msg = store.submit_review(cid, url.strip())
                    flash("ok" if ok else "warn",
                          "已推送至审核站，状态：待审核 · " + msg)
                    st.rerun()
            elif not c["video_url"]:
                st.caption("审核已通过，无需补填送审链接；"
                           "正式发布链接在「闭环」节点登记即可")
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
            if not c["video_url"] and rs not in ("已通过", "复审通过"):
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
                    ok, msg = store.recheck_pass(cid)
                    flash("ok" if ok else "warn", "复审已通过 · " + msg)
                    st.rerun()
                reason = a2.text_input("仍不合格的原因", key="rr")
                if a2.button("❌ 仍不合格", key="rr2") and reason.strip():
                    ok, msg = store.recheck_reject(cid, reason.strip())
                    flash("ok" if ok else "warn", "复审已驳回 · " + msg)
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
        # 闭环：视频登记（一行一条视频，可挂商品）+ 发布确认
        _render_step7_videos(cid, c, rs)


def _offer_options(product_list):
    """选品清单 → [(显示名, 商品ID)]，供视频挂商品选择"""
    opts = []
    for p in product_list or []:
        oid = GMC.extract_offer_id(p) or str(p).strip()
        opts.append((oid[-6:] and f"…{oid[-6:]}" or oid, oid))
    return opts


def _init_video_rows(cid, c):
    """初始化视频登记行：已有登记 → 按子表还原；否则带入审核链接一行。
    每行带稳定 rid，避免删行后控件 key 错位串数据"""
    key = f"vrows_{cid}"
    if key in st.session_state:
        return st.session_state[key]
    rows = []
    for v in c.get("videos") or []:
        rows.append({
            "url": v.get("video_url") or "",
            "type": v.get("video_type") or "自动识别",
            "prods": [p for p in str(v.get("product_ids") or "").split(",")
                      if p.strip()],
            "manual_views": v.get("views") or 0,  # TikTok/Instagram 手动播放量回显
        })
    if not rows:
        rows.append({"url": c.get("video_url") or "",
                     "type": "自动识别", "prods": [], "manual_views": 0})
    st.session_state[key] = rows
    return rows


def _clear_video_row_widgets(cid):
    """清空视频登记行的所有控件状态（删除/新增行后调用，防止控件值错位串数据）"""
    for prefix in ("vurl_", "vtype_", "vprods_", "vprod_"):
        for k in [x for x in st.session_state.keys()
                  if str(x).startswith(f"{prefix}{cid}")]:
            del st.session_state[k]


def _render_step7_videos(cid, c, rs):
    rows_key = f"vrows_{cid}"
    with st.container():
        st.markdown(T.ycard_open(), unsafe_allow_html=True)
        st.markdown(T.sub("视频登记 & 闭环"), unsafe_allow_html=True)

        if c["is_closed"] and not st.session_state.get(f"vedit_{cid}"):
            # 已闭环：展示已登记视频
            vids = c.get("videos") or []
            if vids:
                vrows = [[T.badge(v.get("video_type") or "长视频"),
                          f'<a class="yts-link" href="{esc(v.get("video_url") or "")}" '
                          f'target="_blank">{esc(v.get("video_url") or "")}</a>',
                          esc(v.get("product_ids") or "-"),
                          f'<span class="num">{int(v.get("views") or 0):,}</span>']
                         for v in vids]
                st.markdown(T.table(["类型", "视频链接", "挂的商品", "播放量"],
                                    vrows), unsafe_allow_html=True)
            elif c["video_url"]:
                st.markdown(f'发布链接：<a class="yts-link" href="{esc(c["video_url"])}" '
                            f'target="_blank">{esc(c["video_url"])}</a>',
                            unsafe_allow_html=True)
            st.markdown('<div class="closed-tag" style="font-size:13px">'
                        '✨ 已确认发布 · 流程闭环'
                        + ('　📣 需要投放' if c.get("ad_needed") else '')
                        + '</div>', unsafe_allow_html=True)
            if st.button("✏️ 修改视频登记", key="vedit_open"):
                st.session_state[f"vedit_{cid}"] = True
                st.session_state.pop(rows_key, None)
                _clear_video_row_widgets(cid)  # 防止旧控件值与还原行冲突
                st.rerun()
            return

        if rs not in ("已通过", "复审通过"):
            st.markdown(T.empty_hint("审核通过后，在此登记已发布视频并完成闭环"),
                        unsafe_allow_html=True)
            return

        st.caption("登记本次合作发布的所有视频（一条长视频+一条Shorts就登记两行）；"
                   "每条视频勾选它挂载的商品，分析模块将按视频分别统计数据")
        opts = _offer_options(c.get("product_list"))
        oid_labels = {oid: f"商品 {lab}" for lab, oid in opts}
        all_oids = [oid for _, oid in opts]

        rows = _init_video_rows(cid, c)
        for i, row in enumerate(rows):
            st.markdown(f"**视频 {i + 1}**")
            col_url, col_type, col_del = st.columns([4, 1.6, 0.6])
            new_url = col_url.text_input(
                "视频链接（必填）", value=row["url"], key=f"vurl_{cid}_{i}",
                placeholder="https://youtube.com/watch?v=… 或 /shorts/…")
            new_type = col_type.selectbox(
                "类型", ["自动识别", "长视频", "Shorts", "TikTok", "Instagram"],
                index=["自动识别", "长视频", "Shorts", "TikTok", "Instagram"].index(row["type"])
                if row["type"] in ("自动识别", "长视频", "Shorts", "TikTok", "Instagram") else 0,
                key=f"vtype_{cid}_{i}")
            if col_del.button("🗑", key=f"vdel_{cid}_{i}",
                              help="删除这条视频",
                              disabled=len(rows) <= 1):
                rows.pop(i)
                st.session_state[rows_key] = rows
                _clear_video_row_widgets(cid)  # 防控件值错位串数据
                st.rerun()
            new_prods = st.multiselect(
                "该视频挂载的商品（关联 GMV 归因）", all_oids,
                default=[p for p in row["prods"] if p in all_oids],
                format_func=lambda oid: oid_labels.get(oid, oid),
                key=f"vprods_{cid}_{i}")
            # TikTok/Instagram 播放量无法自动抓取 → 手动填写
            new_views = row.get("manual_views")
            if new_type in ("TikTok", "Instagram"):
                new_views = st.number_input(
                    "播放量（手动填写）", min_value=0, step=1000,
                    value=int(row.get("manual_views") or 0),
                    key=f"vviews_{cid}_{i}",
                    help="TikTok/Instagram 的播放量无法自动抓取，请手动填写")
            if new_url != row["url"] or new_type != row["type"] \
                    or new_prods != row["prods"] \
                    or new_views != row.get("manual_views"):
                row.update({"url": new_url.strip(), "type": new_type,
                            "prods": new_prods, "manual_views": new_views})
                st.session_state[rows_key] = rows
            st.divider()

        if st.button("➕ 添加视频", key="vadd"):
            rows.append({"url": "", "type": "自动识别", "prods": []})
            st.session_state[rows_key] = rows
            st.rerun()

        # 投放需求：闭环时由运营选择 → 进审核站「投放模块」待投放清单
        ad_choice = st.radio(
            "是否需要投放（短视频投，长视频不投）",
            ["不需要投放", "需要投放"],
            index=1 if c.get("ad_needed") else 0,
            horizontal=True, key=f"adneed_{cid}",
            help="选择「需要投放」后，该网红会进入审核站投放模块，"
                 "每天 10:00 / 16:00 定时提醒投放负责人")

        if st.button("✅ 已确认发布，流程闭环", key="up", type="primary",
                     use_container_width=True):
            filled = [r for r in rows if r["url"].strip()]
            if not filled:
                st.warning("请先登记至少一条已发布视频链接，再闭环")
            else:
                videos = _build_video_payload(cid, c, filled)
                if videos is None:
                    pass  # 类型识别失败，错误已提示
                else:
                    store.save_videos(cid, videos)
                    store.confirm_uploaded(cid, filled[0]["url"].strip(),
                                           ad_needed=(ad_choice == "需要投放"))
                    st.session_state.pop(rows_key, None)
                    st.session_state.pop(f"vedit_{cid}", None)
                    st.toast("🎉 流程闭环，视频明细已登记，分析模块将按视频统计")
                    st.rerun()
        if st.session_state.get(f"vedit_{cid}"):
            if st.button("取消修改", key="vedit_cancel"):
                st.session_state.pop(f"vedit_{cid}", None)
                st.session_state.pop(rows_key, None)
                st.rerun()


def _build_video_payload(cid, c, filled_rows):
    """登记行 → 视频明细子表数据；自动识别类型，保留已有指标"""
    old_by_url = {v.get("video_url"): v for v in c.get("videos") or []}
    videos = []
    for r in filled_rows:
        url = r["url"].strip()
        vtype = r["type"]
        if vtype == "自动识别":
            vtype = YT.detect_video_type(url)
            if not vtype:
                st.error(f"无法自动识别视频类型（链接 {url}）：请手动选择"
                         "「长视频」或「Shorts」后重试")
                return None
        old = old_by_url.get(url, {})
        # TikTok/Instagram 播放量：手动填写值优先；其余保留已有抓取值
        mv = r.get("manual_views")
        views = (int(mv) if mv else (old.get("views") or 0))
        videos.append({
            "video_type": vtype,
            "video_url": url,
            "product_ids": ",".join(r.get("prods") or []),
            "views": views,
            "likes": old.get("likes") or 0,
            "comments": old.get("comments") or 0,
            "clicks": old.get("clicks") or 0,
            "ctr": old.get("ctr") or 0,
            "orders": old.get("orders") or 0,
            "gmv": old.get("gmv") or 0,
        })
    return videos


# ============================ 分析模块 ============================
def _pull_product_metrics(closed_recs):
    """从 GMC 报表拉取闭环视频选品的点击/CTR/成交/GMV（近30天）并回写宜搭"""
    if not GMC.configured():
        st.error("未配置 GMC 凭证：请在 Streamlit Cloud → Settings → Secrets 添加 "
                 "[gmc] 段（client_email / private_key / merchant_id / feed_label）。"
                 "配置前商品指标请回宜搭表单手工回填")
        return
    with st.spinner("正在从 GMC 拉取商品效果数据…"):
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        hit_n = 0
        for r in closed_recs:
            prods = r.get("product_list") or []
            if not prods:
                continue
            perf = GMC.fetch_performance(prods, start, end)
            if not perf:
                continue
            clicks = sum(v["clicks"] for v in perf.values())
            orders = sum(v["orders"] for v in perf.values())
            gmv = sum(v["gmv"] for v in perf.values())
            ctr = round(sum(v["ctr"] for v in perf.values()) / len(perf), 2)
            try:
                store.update_product_metrics(r, clicks, ctr, orders, gmv)
                hit_n += 1
            except Exception:
                pass
    if hit_n:
        st.toast(f"已回写 {hit_n} 条闭环记录的商品效果数据（近30天）")
        st.rerun()
    else:
        st.warning("未拉到数据：请检查 GMC 凭证是否有效、选品是否已入池")


# ---------------------------------------------------------------------------
# 汇率与货币换算（2026-08-24 审查修复）
# 背景：商品报表的销售额/佣金是美金(≈)，网红报价存的是韩币。
# 此前 ROI=GMV/报价、CPM=报价/播放×1000 直接混用两种货币，差约1538倍。
# 现统一换算成美金口径。汇率可在 Secrets 配 USD_RATE（默认1538韩币/美金）。
# 宜搭无需新增美金列（汇率波动，存快照会过时），网站按汇率实时换算。
# ---------------------------------------------------------------------------
def _usd_rate() -> float:
    try:
        v = float(os.environ.get("USD_RATE", "") or 1538)
        return v if v > 0 else 1538
    except ValueError:
        return 1538


def _krw_to_usd(krw) -> float:
    """韩币 → 美金"""
    try:
        return float(krw) / _usd_rate()
    except (TypeError, ValueError):
        return 0.0


# 数据更新权限：视频数据（YouTube）与商品数据（GMC）的刷新/拉取
# 仅限负责人操作；其他成员可查看已同步的数据，但不能触发刷新。
# 网红基础信息（编辑表单）不受此限制，全员可编辑。
DATA_OWNER = "艾薇李"


def _is_data_owner() -> bool:
    """当前会话是否为数据负责人：以活动页选定的名字为准（与 URL ?rec= 一致）"""
    name = st.session_state.get("activity_recruiter") \
        or st.query_params.get("rec") or ""
    return R.match_name(str(name), [DATA_OWNER]) == DATA_OWNER


def _refresh_videos_granular(closed_recs, force=False):
    """按视频粒度刷新：videos 子表每一行抓 YouTube 互动 + GMC 商品数据，回写对应行。

    性能要点（10人共用）：
    1. 数据无变化时不写回宜搭（否则每次打开分析页都产生写入风暴）
    2. 一个网红的所有视频行合并为一次 save_videos（原来每行写一次）
    3. 相同商品集的 GMC 报表请求本轮去重（同批多视频挂同组商品只查一次）
    返回 (有数据更新并回写成功的记录数, 抓取失败列表[(网红名, 链接)])"""
    updated, failed = 0, []
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    perf_cache = {}  # 本轮 GMC 请求去重：商品集 -> 报表结果
    for r in closed_recs:
        vids = r.get("videos") or []
        if not vids:
            # ---- 老记录兜底：无视频子表时按主 video_url 抓取，回写主字段 ----
            url = r.get("video_url") or ""
            if not url:
                continue
            stats = YT.fetch_video_stats(url, force=force)
            if stats is None:
                if YT.get_key():
                    failed.append((r["name"], url))
                continue
            patch = {}
            for src_k, dst_k in (("views", "video_views"),
                                 ("likes", "video_likes"),
                                 ("comments", "video_comments")):
                if int(r.get(dst_k) or 0) != int(stats[src_k] or 0):
                    patch[dst_k] = stats[src_k]
            if patch:
                try:
                    store.update_video_metrics(r,
                                               patch.get("video_views", r.get("video_views") or 0),
                                               patch.get("video_likes", r.get("video_likes") or 0),
                                               patch.get("video_comments", r.get("video_comments") or 0))
                    r.update(patch)  # 页面快照同步
                    updated += 1
                except Exception:
                    failed.append((r["name"], "回写失败"))
            continue
        changed = False
        new_videos = []
        for v in vids:
            nv = dict(v)
            url = v.get("video_url") or ""
            # TikTok/Instagram 播放量为手动填写，跳过 YouTube 抓取（避免误报失败）
            if (v.get("video_type") or "") in ("TikTok", "Instagram"):
                new_videos.append(nv)
                continue
            if url:
                stats = YT.fetch_video_stats(url, force=force)
                if stats is not None:
                    for k in ("views", "likes", "comments"):
                        if int(nv.get(k) or 0) != int(stats[k] or 0):
                            nv[k] = stats[k]
                            changed = True
                elif YT.get_key():
                    failed.append((r["name"], url))
                # 按该视频关联的商品拉 GMC 数据（未配置 GMC 时跳过）
                pids = tuple(sorted(p.strip()
                                    for p in str(v.get("product_ids") or "").split(",")
                                    if p.strip()))
                if pids and GMC.configured():
                    perf = perf_cache.get(pids)
                    if perf is None:
                        perf = GMC.fetch_performance(list(pids), start, end)
                        perf_cache[pids] = perf
                    if perf:
                        clicks = sum(x["clicks"] for x in perf.values())
                        orders = sum(x["orders"] for x in perf.values())
                        gmv = sum(x["gmv"] for x in perf.values())
                        ctr = round(sum(x["ctr"] for x in perf.values())
                                    / len(perf), 2)
                        for k, val in (("clicks", clicks), ("ctr", ctr),
                                       ("orders", orders), ("gmv", gmv)):
                            if abs(float(nv.get(k) or 0) - float(val)) > 0.01:
                                nv[k] = val
                                changed = True
            new_videos.append(nv)
        if changed:
            try:
                # 并发合并（宜搭版 store）：fresh 重读子表做并集合并，
                # 合并结果与宜搭现状完全相同则跳过写库，避免无意义写入
                if getattr(store, "merge_videos", None):
                    merged, fresh = store.merge_videos(r["collab_id"], new_videos)
                    if merged == fresh:
                        r["videos"] = fresh  # 宜搭侧已是最新：仅同步页面快照
                        continue
                    new_videos = merged
                store.save_videos(r["collab_id"], new_videos)
                r["videos"] = new_videos  # 页面快照同步，避免缓存延迟
                updated += 1
            except Exception:
                failed.append((r["name"], "回写失败"))
    return updated, failed


def _aggregate_kols(recs, vrows_data):
    """按网红聚合（四象限/KPI 数据源，与网红维度同口径）：
    播放/点赞=视频加总；订单/GMV=商品子表加总（新导入的商品数据）；
    报价换算美金；ROI=GMV($)/报价($)；CPM=报价($)/播放×1000。
    返回 [{cid, name, views, likes, orders, gmv, price, price_usd, roi, cpm}]"""
    agg = {}
    for r in recs:
        vids = r.get("videos") or []
        prods = r.get("products") or []
        tot_views = sum(int(v.get("views") or 0) for v in vids)
        tot_likes = sum(int(v.get("likes") or 0) for v in vids)
        tot_orders = sum(float(p.get("orders") or 0) for p in prods)
        tot_gmv = sum(float(p.get("gmv") or 0) for p in prods)
        # 老数据兜底：无视频子表/商品子表时用主记录指标
        if not vids:
            tot_views = int(r.get("video_views") or 0)
            tot_likes = int(r.get("video_likes") or 0)
        if not prods:
            tot_orders = float(r.get("orders") or 0)
            tot_gmv = float(r.get("gmv") or 0)
        price = float(r.get("price") or 0)
        price_usd = _krw_to_usd(price)
        agg[r["collab_id"]] = {
            "cid": r["collab_id"], "name": r["name"],
            "views": tot_views, "likes": tot_likes,
            "orders": int(tot_orders), "gmv": tot_gmv,
            "price": price, "price_usd": round(price_usd, 2),
            "roi": round(tot_gmv / price_usd, 2) if price_usd else 0,
            "cpm": round(price_usd / tot_views * 1000, 2)
            if (price_usd and tot_views) else 0,
        }
    return list(agg.values())


def _render_kpi(kols, vrows_data):
    """KPI 大数字卡（10项）：两行各5张等宽满宽卡。
    第一行=声量侧，第二行=GMV/成本侧"""
    tot_views = sum(a["views"] for a in kols)
    tot_likes = sum(a["likes"] for a in kols)
    eng = (tot_likes / tot_views * 100) if tot_views else 0
    tot_gmv = sum(a["gmv"] for a in kols)
    tot_orders = sum(a["orders"] for a in kols)
    tot_cost = sum(a["price_usd"] for a in kols)  # 美金口径（韩币已换算）
    roi = (tot_gmv / tot_cost) if tot_cost else 0
    cpm = (tot_cost / tot_views * 1000) if tot_views else 0
    # 第一行：声量侧
    st.markdown(T.stats_row([
        ("🔊 总声量（播放）", f"{tot_views:,}", "c-pink"),
        ("❤️ 总点赞", f"{tot_likes:,}", "c-purple"),
        ("✨ 平均互动率", f"{eng:.1f}%", "c-green"),
        ("👥 闭环网红数", str(len(kols)), "c-amber"),
        ("🎬 视频总数", str(len(vrows_data)), "c-pink"),
    ]), unsafe_allow_html=True)
    # 第二行：GMV / 成本侧（与第一行等宽满宽，卡片大小一致）
    st.markdown(T.stats_row([
        ("💰 总GMV($)", f"{tot_gmv:,.0f}", "c-green"),
        ("🛒 总成交", f"{tot_orders:,}", "c-amber"),
        ("💵 总报价花费($)", f"{tot_cost:,.0f}", "c-purple"),
        ("📈 整体ROI", f"{roi:.2f}", "c-green"),
        ("🎯 整体CPM($/千次播放)", f"{cpm:.2f}", "c-pink"),
    ]), unsafe_allow_html=True)


def _render_quadrant(kols):
    """四象限散点图：横轴GMV、纵轴播放量，象限=运营动作"""
    pts = [a for a in kols if a["views"] > 0]
    if not pts:
        st.markdown(T.empty_hint("暂无有播放量的数据，无法绘制四象限图"),
                    unsafe_allow_html=True)
        return
    # 分界线：GMV 用中位数（无成交时退化为0.1），播放用中位数
    gmvs = sorted(a["gmv"] for a in pts)
    views_s = sorted(a["views"] for a in pts)
    x_mid = gmvs[len(gmvs) // 2] if gmvs[-1] > 0 else 0
    y_mid = views_s[len(views_s) // 2]
    x_max = max(a["gmv"] for a in pts) * 1.15 if gmvs[-1] > 0 else 1
    y_max = max(a["views"] for a in pts) * 1.15

    def quad(a):
        if a["views"] >= y_mid and a["gmv"] >= x_mid and a["gmv"] > 0:
            return "⭐优质·继续合作"
        if a["views"] >= y_mid and a["gmv"] < x_mid:
            return "⚠️高播低转化·查链接/话术"
        if a["views"] < y_mid and a["gmv"] >= x_mid and a["gmv"] > 0:
            return "💎低播高转化·值得放量"
        return "❌双低·考虑淘汰"

    colors = {"⭐优质·继续合作": "#1a7f4b",
              "⚠️高播低转化·查链接/话术": "#b26a09",
              "💎低播高转化·值得放量": "#7a5fd0",
              "❌双低·考虑淘汰": "#c2507a"}
    # 画布
    W, H, pad = 760, 420, 50
    def sx(v): return pad + (v / x_max) * (W - 2 * pad) if x_max else W / 2
    def sy(v): return H - pad - (v / y_max) * (H - 2 * pad)
    dots = ""
    for a in pts:
        c = colors[quad(a)]
        dots += (f'<circle cx="{sx(a["gmv"]):.1f}" cy="{sy(a["views"]):.1f}" r="7" '
                 f'fill="{c}" fill-opacity="0.75" stroke="#fff" stroke-width="1.5">'
                 f'<title>{a["name"]}｜播放 {a["views"]:,}｜GMV {a["gmv"]:,.0f}'
                 f'｜{quad(a)}</title></circle>')
    legend = "".join(
        f'<span style="display:inline-block;margin-right:14px;font-size:12px;'
        f'color:#555"><span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:50%;background:{c};margin-right:4px"></span>{q}</span>'
        for q, c in colors.items())
    svg = f'''<svg viewBox="0 0 {W} {H}" style="width:100%;background:#fff;
border:1px solid #f1e4e8;border-radius:14px">
<line x1="{pad}" y1="{sy(y_mid):.1f}" x2="{W-pad}" y2="{sy(y_mid):.1f}"
 stroke="#eee" stroke-dasharray="5,4"/>
<line x1="{sx(x_mid):.1f}" y1="{pad}" x2="{sx(x_mid):.1f}" y2="{H-pad}"
 stroke="#eee" stroke-dasharray="5,4"/>
<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="#ddd"/>
<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="#ddd"/>
{dots}
<text x="{W-pad}" y="{H-pad+30}" text-anchor="end" font-size="12"
 fill="#86868b">GMV →（右越好）</text>
<text x="{pad-38}" y="{pad}" font-size="12" fill="#86868b"
 transform="rotate(-90 {pad-38} {pad+40})">声量↑（上越好）</text>
</svg>'''
    st.markdown(f'<div style="text-align:center;margin-bottom:6px">{legend}</div>',
                unsafe_allow_html=True)
    st.markdown(svg, unsafe_allow_html=True)
    st.caption("分界线 = 当前数据的中位数；鼠标悬停圆点看详情。"
               "GMV 数据接通前，多数点会集中在左侧（有声量未转化）。")


def _render_issue_list(kols):
    """问题清单：自动列出需要处理的网红 + 建议动作。
    用自然高度表格（st.markdown）而非固定高度 iframe——
    建议文字长会换行，固定高度会裁掉底部行（曾导致清单显示不全）"""
    issues = []
    for a in kols:
        if a["views"] == 0:
            issues.append(("🔴", a, "视频播放量为 0：检查视频是否公开/链接是否正确"))
        elif a["views"] >= 50000 and a["gmv"] == 0:
            issues.append(("🟠", a, "高播放但零 GMV：检查商品链接、折扣码口播、挂车是否正确"))
        elif a["price"] and a["roi"] < 1:
            issues.append(("🟡", a, f"ROI 仅 {a['roi']}（花 ${a['price_usd']:,.0f} 赚 ${a['gmv']:,.0f}）："
                                    "考虑降报价或换选品"))
    if not issues:
        st.markdown(T.empty_hint("✅ 暂无异常：所有闭环网红数据正常"),
                    unsafe_allow_html=True)
        return
    rows = [[lv, f'<b>{esc(a["name"])}</b>',
             f'<span class="num">{a["views"]:,}</span>',
             f'<span class="num">{a["gmv"]:,.0f}</span>',
             esc(msg)] for lv, a, msg in issues]
    # wrap=True：外框 div 自然撑高，不裁行
    st.markdown(T.table(["级别", "网红", "播放", "GMV($)", "问题与建议"],
                        rows, wrap=True), unsafe_allow_html=True)


# ============================ 数据健康检查 ============================

def _health_facts(r):
    """单条记录的闭环数据事实：
    返回 (有视频链接, 有商品链接, 播放, 成交, GMV)。
    有子表 videos 时按子表汇总，否则用主记录级老字段兜底。"""
    vids = r.get("videos") or []
    has_video = bool((r.get("video_url") or "").strip()) or any(
        (v.get("video_url") or "").strip() for v in vids)
    has_product = bool(r.get("product_list")) or any(
        str(v.get("product_ids") or "").strip() for v in vids)
    if vids:
        views = sum(int(v.get("views") or 0) for v in vids)
        orders = sum(int(v.get("orders") or 0) for v in vids)
        gmv = sum(float(v.get("gmv") or 0) for v in vids)
    else:
        views = int(r.get("video_views") or 0)
        orders = int(r.get("orders") or 0)
        gmv = float(r.get("gmv") or 0)
    return has_video, has_product, views, orders, gmv


def _data_health(all_recs):
    """跑 6 条数据健康规则，返回 [{icon,title,hint,fix,rows,status}]。
    rows=命中该规则的记录列表，status=每条记录的缺失明细。"""
    closed = [r for r in all_recs if r.get("is_closed")]
    facts = {r["collab_id"]: _health_facts(r) for r in closed}

    def has_url(r):
        return bool((r.get("channel_url") or "").strip())

    # 规则1：缺主页链接（所有网红）
    r1 = [r for r in all_recs if not has_url(r)]
    # 规则2：有链接但缺频道信息（名称/粉丝数）
    r2 = []
    for r in all_recs:
        if not has_url(r):
            continue  # 已在规则1计过
        name_missing = (not r.get("name")) or r.get("name") == r.get("channel_id")
        if name_missing or not r.get("followers"):
            r2.append(r)
    # 规则3~6：仅已闭环
    r3, r4, r5, r6 = [], [], [], []
    for r in closed:
        hv, hp, views, orders, gmv = facts[r["collab_id"]]
        if not hv:
            r3.append(r)
        else:
            if not hp:
                r4.append(r)
            if views <= 0:
                r5.append(r)
            # 规则6 仅在已有播放（数据在流）但无成交时报，
            # 播放为 0 的根因已在规则5报过，避免重复
            if hp and views > 0 and orders <= 0 and gmv <= 0:
                r6.append(r)

    def st2(r):  # 规则2明细
        miss = []
        if (not r.get("name")) or r.get("name") == r.get("channel_id"):
            miss.append("频道名")
        if not r.get("followers"):
            miss.append("粉丝数")
        return "缺 " + "、".join(miss)

    return [
        {"icon": "🔗", "title": "缺主页链接",
         "hint": "所有网红必须有 YouTube 主页链接",
         "fix": "在详情页补主页链接",
         "rows": r1, "status": lambda r: "无主页链接"},
        {"icon": "📇", "title": "有链接但缺频道信息",
         "hint": "有主页链接却没抓到频道名称 / 粉丝数",
         "fix": "重新抓取或手填频道信息",
         "rows": r2, "status": st2},
        {"icon": "🎬", "title": "已闭环·缺视频链接",
         "hint": "闭环必须有视频链接",
         "fix": "在详情页补视频链接",
         "rows": r3, "status": lambda r: "无视频链接"},
        {"icon": "🛒", "title": "已闭环·缺商品链接",
         "hint": "闭环必须有挂载商品",
         "fix": "在视频行补挂载商品ID",
         "rows": r4, "status": lambda r: "视频未挂商品"},
        {"icon": "📉", "title": "已闭环·缺视频数据",
         "hint": "有视频但播放量为 0（未抓取或视频未公开）",
         "fix": "点「一键刷新」抓取，或检查视频是否公开",
         "rows": r5, "status": lambda r: "播放量为 0"},
        {"icon": "💸", "title": "已闭环·缺商品数据",
         "hint": "挂了商品但无成交 / GMV",
         "fix": "点「一键拉取商品效果数据」或等 GMC 回流",
         "rows": r6, "status": lambda r: "无成交/GMV"},
    ]


def _health_name_link(r):
    return (f'<a data-nav="?detail={quote(str(r["collab_id"]), safe="")}&from=analysis" '
            f'style="color:#d76a8c;font-weight:700;text-decoration:none">'
            f'{esc(r["name"])}</a>'
            + (' <span class="closed-tag">已闭环</span>' if r.get("is_closed") else ""))


def _render_health(all_recs):
    """数据健康 Tab：逐条规则列出问题记录，点名字跳详情页修改。"""
    checks = _data_health(all_recs)
    total_issues = sum(len(c["rows"]) for c in checks)
    n_closed = sum(1 for r in all_recs if r.get("is_closed"))
    st.markdown(T.stats_row([
        ("🧾 检查记录数", f"{len(all_recs):,}", "c-pink"),
        ("✅ 已闭环", f"{n_closed:,}", "c-purple"),
        ("🚨 问题项", f"{total_issues:,}", "c-amber" if total_issues else "c-green"),
    ]), unsafe_allow_html=True)
    st.caption("检查全量数据（不受月份筛选影响）· 点网红名字直接跳详情页修改。")
    if total_issues == 0:
        st.markdown(T.empty_hint("🎉 全部合规：所有网红主页链接、频道信息、"
                                 "闭环视频/商品/数据都齐了"),
                    unsafe_allow_html=True)
        return
    for c in checks:
        rows, st_fn = c["rows"], c["status"]
        head = f'{c["icon"]} {c["title"]}（{len(rows)} 人）'
        st.markdown(T.sub(head), unsafe_allow_html=True)
        if not rows:
            st.markdown(T.empty_hint(f'✅ 无此问题 · {c["hint"]}'),
                        unsafe_allow_html=True)
            continue
        st.caption(f'{c["hint"]} · 建议：{c["fix"]}')
        trows = []
        for r in sorted(rows, key=lambda x: (x.get("plan_month") or "",
                                             x.get("name") or "")):
            trows.append([
                _health_name_link(r),
                esc(r.get("recruiter") or "-"),
                esc(r.get("plan_month") or "-"),
                f'<span class="num">{esc(st_fn(r))}</span>',
            ])
        T.component_html(
            T.table(["网红", "负责人", "归属月份", "缺失项"], trows, wrap=False),
            height=52 + len(trows) * 36)


def _export_mapping_bytes():
    """导出「网红×视频×商品」映射表（2个sheet），供离线匹配 CSV 用"""
    import yts_product_match as PM
    sel, vids = PM.build_mapping_records(store.list_all())
    return PM.mapping_to_excel_bytes(sel, vids)


def _import_matched_xlsx(xlsx_file):
    """上传离线匹配后的「导入表」：按 channel_id 直接写宜搭。
    每个网红合并为 1 次写入（商品子表+视频子表+主记录指标），带进度条"""
    import yts_product_match as PM
    try:
        data = PM.parse_import_excel(xlsx_file.read())
    except ValueError as e:
        st.error(str(e))
        return
    if not data:
        st.error("导入表里没有有效数据行，请确认文件正确")
        return
    rec_by_cid = {r["collab_id"]: r for r in store.list_all()}
    # 旧映射表里是裸频道ID（无#月份）：同频道多条时按商品重合度挑目标行
    bare_map = {}
    for r in rec_by_cid.values():
        bare_map.setdefault(r.get("channel_id") or "", []).append(r)

    def _pick_rec(cid, g):
        rec = rec_by_cid.get(cid)
        if rec or "#" in cid:
            return rec
        cands = bare_map.get(cid) or []
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        gpids = {str(p.get("pid") or "") for p in g["products"]}

        def _score(r):
            rpids = {PM.norm_pid(u) for u in r.get("product_list") or []}
            return (len(gpids & rpids), r.get("plan_month") or "")
        return max(cands, key=_score)

    prog = st.progress(0.0, text="正在写入宜搭…")
    hit, n_prod = 0, 0
    for i, (cid, g) in enumerate(data.items()):
        prog.progress(i / len(data), text=f"正在写入（{i + 1}/{len(data)}）")
        rec = _pick_rec(cid, g)
        if not rec:
            continue
        cid = rec["collab_id"]  # 后续写入统一走复合身份
        patch = {"products": g["products"]}
        if g["videos_patch"] and rec.get("videos"):
            patch["videos"] = PM.apply_video_patch(rec["videos"],
                                                   g["videos_patch"])
        clicks, orders, gmv = g["summary"]
        patch.update({
            "product_views": int(clicks), "ctr": 0.0,
            "orders": int(orders),
            "conversion_rate": round(orders / clicks * 100, 2) if clicks else 0.0,
            "gmv": float(gmv),
        })
        ctrs = [p.get("ctr") or 0 for p in g["products"]]
        if ctrs:
            patch["ctr"] = round(sum(ctrs) / len(ctrs), 2)
        store._upd(cid, patch)  # 单次 HTTP 写入
        hit += 1
        n_prod += len(g["products"])
    prog.progress(1.0, text="完成")
    if hit == 0:
        st.warning("没有写入任何数据：导入表里的网红在系统中不存在")
        return
    st.toast(f"✅ 已更新 {hit} 位网红、{n_prod} 个商品的效果数据")


# ============================ 分析模块 · 五维度构建 ============================
def _pids_of(v):
    """视频行的关联商品ID列表"""
    return [p.strip() for p in str(v.get("product_ids") or "").split(",")
            if p.strip()]


def _build_video_dim(recs):
    """📹 视频维度：一条视频一行。口径（定稿）：
    点击/订单 = 该网红全部商品总和 ÷ 视频数（每条视频相同）；
    GMV = 按商品挂品均摊（商品销售额 ÷ 挂它的视频数）；
    CPM = 报价($) ÷ 播放 × 1000"""
    rows = []
    for r in recs:
        vids = r.get("videos") or []
        if not vids:
            continue
        prods = r.get("products") or []
        n = len(vids)
        tot_clicks = sum(float(p.get("clicks") or 0) for p in prods)
        tot_orders = sum(float(p.get("orders") or 0) for p in prods)
        avg_clicks = tot_clicks / n
        avg_orders = tot_orders / n
        price_usd = _krw_to_usd(r.get("price"))
        gmv_by_id = {str(p.get("pid") or ""): float(p.get("gmv") or 0)
                     for p in prods}
        holder = {}
        for v in vids:
            for pid in _pids_of(v):
                if pid in gmv_by_id:
                    holder[pid] = holder.get(pid, 0) + 1
        for v in vids:
            pids = _pids_of(v)
            vgmv = sum(gmv_by_id[p] / holder[p]
                       for p in pids if holder.get(p))
            views = int(v.get("views") or 0)
            rows.append({
                "网红": r["name"], "_cid": r["collab_id"],
                "月份": r.get("plan_month") or "",
                "视频类型": v.get("video_type") or "长视频",
                "视频链接": v.get("video_url") or "",
                "挂品数": len(pids),
                "播放": views, "点赞": int(v.get("likes") or 0),
                "评论": int(v.get("comments") or 0),
                "点击": round(avg_clicks, 1), "订单": round(avg_orders, 1),
                "GMV($)": round(vgmv, 2),
                "报价($)": round(price_usd, 2),
                "CPM($/千次)": round(price_usd / views * 1000, 2)
                if (price_usd and views) else 0,
                "能否二次利用": r.get("settlement") or "",
            })
    return rows


def _build_prod_dim(recs):
    """🛍 商品维度：一个商品一行；多网红选同一商品合并一行（名字并列）；
    选品清单里有但商品子表无数据的商品也显示（填0）"""
    prod = {}  # pid -> 数据行
    for r in recs:
        for p in r.get("products") or []:
            pid = str(p.get("pid") or "")
            if not pid:
                continue
            row = prod.setdefault(pid, {
                "pid": pid, "names": [], "name": p.get("name") or "",
                "p_category": p.get("p_category") or "",
                "video_views": 0.0, "impressions": 0.0, "clicks": 0.0,
                "orders": 0.0, "gmv": 0.0, "net_sales": 0.0, "commission": 0.0,
            })
            if r["name"] not in row["names"]:
                row["names"].append(r["name"])
            if p.get("name"):
                row["name"] = p["name"]
            for k in ("video_views", "impressions", "clicks", "orders",
                      "gmv", "net_sales", "commission"):
                row[k] += float(p.get(k) or 0)
    # 选品清单里有、但商品子表没数据的商品 → 填0展示
    for r in recs:
        for item in r.get("product_list") or []:
            m = re.search(r"/item/(\d+)", str(item))
            pid = m.group(1) if m else str(item).strip()
            if not pid.isdigit():
                continue
            row = prod.setdefault(pid, {
                "pid": pid, "names": [], "name": "", "p_category": "",
                "video_views": 0.0, "impressions": 0.0, "clicks": 0.0,
                "orders": 0.0, "gmv": 0.0, "net_sales": 0.0, "commission": 0.0,
            })
            if r["name"] not in row["names"]:
                row["names"].append(r["name"])
    out = []
    for pid, row in prod.items():
        imp, clk, vv = row["impressions"], row["clicks"], row["video_views"]
        ord_ = row["orders"]
        out.append({
            "网红": "、".join(row["names"]) if row["names"] else "未归属",
            "_names": row["names"],
            "商品名称": (row["name"] or "-")[:30],
            "商品ID": pid,
            "商品链接": f"https://ko.aliexpress.com/item/{pid}.html",
            "商品类目": row["p_category"] or "",
            "视频观看次数": int(vv), "展示次数": int(imp), "点击次数": int(clk),
            "点击率(%)": round(clk / imp * 100, 2) if imp else 0,
            "订单数": int(ord_),
            "视频转化率(%)": round(ord_ / vv * 100, 2) if vv else 0,
            "商品转化率(%)": round(ord_ / clk * 100, 2) if clk else 0,
            "销售额($)": round(row["gmv"], 2),
            "净销售额($)": round(row["net_sales"], 2),
            "佣金($)": round(row["commission"], 2),
        })
    return out


def _build_kol_dim(recs):
    """👤 网红维度：一位网红×月份一行。点击/订单/销售额/佣金=名下商品直接加总；
    互动率=(点赞+评论)÷播放；ROI=总GMV($)÷报价($)"""
    rows = []
    for r in recs:
        prods = r.get("products") or []
        vids = r.get("videos") or []
        tot_views = sum(int(v.get("views") or 0) for v in vids)
        tot_likes = sum(int(v.get("likes") or 0) for v in vids)
        tot_comments = sum(int(v.get("comments") or 0) for v in vids)
        eng = ((tot_likes + tot_comments) / tot_views * 100) if tot_views else 0
        tot_clicks = sum(float(p.get("clicks") or 0) for p in prods)
        tot_orders = sum(float(p.get("orders") or 0) for p in prods)
        tot_gmv = sum(float(p.get("gmv") or 0) for p in prods)
        tot_comm = sum(float(p.get("commission") or 0) for p in prods)
        price_usd = _krw_to_usd(r.get("price"))
        n_prod = len([p for p in (r.get("product_list") or []) if str(p).strip()])
        rows.append({
            "网红": r["name"], "_cid": r["collab_id"],
            "挖掘人": r.get("recruiter") or "",
            "月份": r.get("plan_month") or "",
            "内容垂类": r.get("category") or "",
            "带货类目": r.get("sales_category") or "",
            "视频数": len(vids), "商品数": n_prod,
            "总播放": tot_views, "总点赞": tot_likes, "总评论": tot_comments,
            "互动率(%)": round(eng, 2),
            "总点击": int(tot_clicks), "总订单": int(tot_orders),
            "总GMV($)": round(tot_gmv, 2),
            "总佣金($)": round(tot_comm, 2),
            "报价($)": round(price_usd, 2),
            "ROI": round(tot_gmv / price_usd, 2) if price_usd else 0,
        })
    return rows


def _dim_filter_bar(df, key, filters, search_cols, sort_cols):
    """通用筛选条：下拉筛选 + 排序 + 关键词搜索，返回过滤排序后的 DataFrame"""
    cols = st.columns(len(filters) + 2)
    out = df
    for i, (label, field) in enumerate(filters):
        opts = ["全部"] + sorted({str(v) for v in df[field] if str(v).strip()})
        with cols[i]:
            sel = st.selectbox(label, opts, key=f"flt_{key}_{field}")
            if sel != "全部":
                out = out[out[field] == sel]
    with cols[len(filters)]:
        sopts = [f"{c} ↓" for c in sort_cols] + [f"{c} ↑" for c in sort_cols]
        ssel = st.selectbox("排序", sopts, key=f"sort_{key}")
        scol = ssel[:-2]
        out = out.sort_values(scol, ascending=ssel.endswith("↑"),
                              kind="mergesort")
    with cols[len(filters) + 1]:
        q = st.text_input("🔍 搜索", key=f"q_{key}", placeholder="输入名称关键词")
        if q.strip():
            mask = None
            for sc in search_cols:
                m = out[sc].astype(str).str.contains(q.strip(), case=False, na=False)
                mask = m if mask is None else (mask | m)
            if mask is not None:
                out = out[mask]
    return out


def _kol_link(cid, name):
    """网红名 → 可点击跳转履约详情页的链接"""
    return (f'<a data-nav="?detail={quote(str(cid), safe="")}&from=analysis" '
            f'style="color:#d76a8c;font-weight:700;text-decoration:none">'
            f'{esc(name)}</a>')


def page_analysis():
    home_btn()
    st.markdown(T.header("分析模块", "数据看板（声量×GMV 四象限）+ 全量数据 + 商品维度 + 数据健康"),
                unsafe_allow_html=True)
    recs = [r for r in store.list_all() if r.get("plan_month") or r.get("is_closed")]
    # 自动抓取范围仅闭环记录（履约中链接多为未公开审核链接，抓了也是"待回填"）
    closed_recs = [r for r in recs if r.get("is_closed")]
    # ---- 数据更新权限门：仅负责人(艾薇李)可触发抓取/刷新；其他人只读 ----
    is_owner = _is_data_owner()
    _force = st.session_state.pop("force_refresh", False)
    if is_owner:
        if closed_recs and (YT.get_key() or GMC.configured()):
            with st.spinner("正在同步视频数据…" if _force
                            else "正在同步视频数据（每日一次）…"):
                n_upd, failed = _refresh_videos_granular(closed_recs, force=_force)
            if _force:
                st.toast(f"已强制刷新 {n_upd} 条视频记录的数据")
            if failed and not YT.get_key():
                st.warning("未配置 YOUTUBE_API_KEY：播放/点赞/评论无法抓取。"
                           "请在 Streamlit Cloud → Settings → Secrets 添加后使用一键刷新")
        elif closed_recs:
            st.warning("未配置 YOUTUBE_API_KEY 与 GMC 凭证：视频数据无法自动抓取")
    if is_owner:
        fb1, fb2 = st.columns(2)
        if fb1.button("🔄 一键刷新闭环视频数据", key="force_refresh_btn",
                      help="无视24小时缓存，按视频粒度重新抓取播放/点赞/评论，"
                           "并按各视频关联商品拉取点击/CTR/成交/GMV（近30天）"):
            st.session_state["force_refresh"] = True
            st.rerun()
        if fb2.button("📦 一键拉取商品效果数据", key="gmc_perf_btn",
                      help="从 GMC 报表按合作选品拉取点击/CTR/成交/GMV（近30天），"
                           "写入主记录指标（兼容老数据）"):
            _pull_product_metrics(closed_recs)
        # ---- 商品数据两步导入：①导出映射表 → 离线匹配 → ②上传导入表 ----
        mc1, mc2 = st.columns(2)
        with mc1:
            st.download_button(
                "① 📤 导出网红×视频×商品映射表",
                data=_export_mapping_bytes(),
                file_name=f"YTS映射表_{datetime.now():%Y%m%d}.xlsx",
                key="ana_map_export", use_container_width=True,
                help="导出系统里的选品和视频挂品清单，发给助手离线匹配 "
                     "YouTube Shopping 全量数据")
        with mc2:
            xlsx_up = st.file_uploader(
                "② 上传匹配后的导入表（xlsx）",
                type=["xlsx"], key="ana_matched_up",
                help="上传助手匹配生成的「YTS商品导入表」，快速写入宜搭")
            if xlsx_up is not None:
                _import_matched_xlsx(xlsx_up)
                st.rerun()
    elif closed_recs:
        st.caption("📊 视频与商品数据由负责人统一更新；如需刷新请联系艾薇李。"
                   "下方为最新已同步的数据。")
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

    # ===== 五 Tab：四象限 / 网红维度 / 视频维度 / 商品维度 / 数据健康 =====
    tab_dash, tab_kol, tab_video, tab_prod, tab_health = st.tabs(
        ["🎯 四象限", "👤 网红维度", "📹 视频维度", "🛍 商品维度", "🩺 数据健康"])

    closed_recs = [r for r in recs if r.get("is_closed")]

    # ---- 🎯 四象限：KPI(10项) + 四象限 + 问题清单 + GMV Top ----
    with tab_dash:
        dash_recs = closed_recs
        if not dash_recs:
            st.markdown(T.empty_hint("暂无已闭环的网红：完成合作流程并闭环后，"
                                     "自动进入分析看板追踪声量与 GMV"),
                        unsafe_allow_html=True)
        else:
            dash_rows = []  # [(记录, 视频dict或None)]
            for r in dash_recs:
                vids = r.get("videos") or []
                if vids:
                    for v in vids:
                        dash_rows.append((r, v))
                else:
                    dash_rows.append((r, None))
            kols = _aggregate_kols(dash_recs, dash_rows)
            _render_kpi(kols, dash_rows)
            st.markdown(T.sub("🎯 四象限：声量 × GMV"), unsafe_allow_html=True)
            _render_quadrant(kols)
            st.markdown(T.sub("🚨 问题清单（需要处理）"), unsafe_allow_html=True)
            _render_issue_list(kols)
            top = [a for a in sorted(kols, key=lambda x: x["gmv"],
                                     reverse=True)[:10] if a["gmv"] > 0]
            if top:
                df = pd.DataFrame({"GMV($)": [a["gmv"] for a in top]},
                                  index=[a["name"] for a in top])
                st.markdown(T.sub("💰 GMV Top10"), unsafe_allow_html=True)
                st.bar_chart(df, horizontal=True, height=300,
                             color=["#dd8fa8"])
            st.markdown(T.foot("仅统计已闭环网红 · 四象限分界线 = 全体播放/GMV 中位数 · "
                               "GMV/订单来自商品子表（与网红维度同口径）"),
                        unsafe_allow_html=True)

    # ---- 👤 网红维度：一位网红×月份一行（汇总+筛选+排序+搜索+跳转） ----
    with tab_kol:
        st.caption("一位网红×月份一行 · 仅已闭环 · 点网红名进履约详情 · "
                   "互动率(%) = (点赞+评论) ÷ 播放 × 100 · "
                   "ROI = 总GMV($) ÷ 报价($)")
        kdim = pd.DataFrame(_build_kol_dim(closed_recs))
        if kdim.empty:
            st.markdown(T.empty_hint("暂无已闭环网红"),
                        unsafe_allow_html=True)
        else:
            st.markdown(T.stats_row([
                ("网红数", f"{len(kdim):,}", "c-pink"),
                ("总播放", f"{int(kdim['总播放'].sum()):,}", "c-purple"),
                ("总GMV($)", f"{kdim['总GMV($)'].sum():,.0f}", "c-green"),
                ("总报价($)", f"{kdim['报价($)'].sum():,.0f}", "c-amber"),
            ]), unsafe_allow_html=True)
            fdf = _dim_filter_bar(kdim, "kd",
                                  [("月份", "月份"), ("内容垂类", "内容垂类"),
                                   ("带货类目", "带货类目"), ("挖掘人", "挖掘人")],
                                  ["网红"],
                                  ["总GMV($)", "总播放", "ROI", "总订单", "报价($)"])
            krows = [[_kol_link(r["_cid"], r["网红"]),
                      esc(r["挖掘人"] or "-"), esc(r["月份"] or "-"),
                      esc(r["内容垂类"] or "-"), esc(r["带货类目"] or "-"),
                      f'<span class="num">{r["视频数"]}</span>',
                      f'<span class="num">{r["商品数"]}</span>',
                      f'<span class="num">{r["总播放"]:,}</span>',
                      f'<span class="num">{r["总点赞"]:,}</span>',
                      f'<span class="num">{r["互动率(%)"]:.2f}%</span>',
                      f'<span class="num">{r["总点击"]:,}</span>',
                      f'<span class="num">{r["总订单"]:,}</span>',
                      f'<span class="num"><b>{r["总GMV($)"]:,.0f}</b></span>',
                      f'<span class="num">{r["总佣金($)"]:,.0f}</span>',
                      f'<span class="num">{r["报价($)"]:,.0f}</span>',
                      f'<span class="num"><b>{r["ROI"]:.2f}</b></span>']
                     for _, r in fdf.iterrows()]
            T.component_html(
                T.table(["网红", "挖掘人", "月份", "内容垂类", "带货类目",
                         "视频数", "商品数", "总播放", "总点赞", "互动率(%)",
                         "总点击", "总订单", "总GMV($)", "总佣金($)",
                         "报价($)", "ROI"], krows, wrap=False),
                height=52 + len(krows) * 36)
            st.markdown(T.foot(f"报价($) = 韩币报价 ÷ 汇率{_usd_rate():,.0f} · "
                               "金额为美元($) · 点击/订单/销售额/佣金 = 名下商品直接加总"),
                        unsafe_allow_html=True)

    # ---- 📹 视频维度：一条视频一行（汇总+筛选+排序+搜索+跳转） ----
    with tab_video:
        st.caption("一条视频一行 · 仅已闭环 · 点网红名进履约详情 · "
                   "点击/订单 = 网红全部商品总和 ÷ 视频数（均摊）；"
                   "GMV($) = 按挂品均摊；CPM($) = 报价($) ÷ 播放 × 1000")
        vdim = pd.DataFrame(_build_video_dim(closed_recs))
        if vdim.empty:
            st.markdown(T.empty_hint("暂无已闭环视频数据"),
                        unsafe_allow_html=True)
        else:
            st.markdown(T.stats_row([
                ("视频数", f"{len(vdim):,}", "c-pink"),
                ("总播放", f"{int(vdim['播放'].sum()):,}", "c-purple"),
                ("总GMV($)", f"{vdim['GMV($)'].sum():,.0f}", "c-green"),
                ("总订单", f"{int(vdim['订单'].sum()):,}", "c-amber"),
            ]), unsafe_allow_html=True)
            fdf = _dim_filter_bar(vdim, "vd",
                                  [("月份", "月份"), ("视频类型", "视频类型"),
                                   ("能否二次利用", "能否二次利用")],
                                  ["网红"],
                                  ["GMV($)", "播放", "订单", "CPM($/千次)"])
            vrows = [[_kol_link(r["_cid"], r["网红"]),
                      esc(r["月份"] or "-"),
                      T.badge(r["视频类型"]),
                      (f'<a class="yts-link" href="{esc(r["视频链接"])}" '
                       f'target="_blank">视频↗</a>') if r["视频链接"] else "-",
                      f'<span class="num">{r["挂品数"]}</span>',
                      f'<span class="num">{r["播放"]:,}</span>',
                      f'<span class="num">{r["点赞"]:,}</span>',
                      f'<span class="num">{r["评论"]:,}</span>',
                      f'<span class="num">{r["点击"]:,.1f}</span>',
                      f'<span class="num">{r["订单"]:,.1f}</span>',
                      f'<span class="num"><b>{r["GMV($)"]:,.0f}</b></span>',
                      f'<span class="num">{r["报价($)"]:,.0f}</span>',
                      f'<span class="num">{r["CPM($/千次)"]:.2f}</span>',
                      esc(r["能否二次利用"] or "-")]
                     for _, r in fdf.iterrows()]
            T.component_html(
                T.table(["网红", "月份", "类型", "视频", "挂品数", "播放", "点赞",
                         "评论", "点击", "订单", "GMV($)", "报价($)",
                         "CPM($/千次)", "能否二次利用"], vrows, wrap=False),
                height=52 + len(vrows) * 36)
            st.markdown(T.foot("金额单位均为美元($) · 报价($) = 韩币报价 ÷ "
                               f"汇率{_usd_rate():,.0f} · 播放为0时CPM显示0"),
                        unsafe_allow_html=True)

    # ---- 🛍 商品维度：一个商品一行（汇总+筛选+排序+搜索） ----
    with tab_prod:
        st.caption("一个商品一行 · 多网红选同一商品时合并一行（名字并列）· "
                   "选品清单有、但报表无数据的商品显示0")
        pdim = pd.DataFrame(_build_prod_dim(closed_recs))
        if pdim.empty:
            st.markdown(T.empty_hint("暂无商品数据：请先在分析模块顶部上传"
                                     "「表现最好的链接商品」CSV"),
                        unsafe_allow_html=True)
        else:
            tot_g = pdim["销售额($)"].sum()
            tot_o = int(pdim["订单数"].sum())
            tot_c = int(pdim["点击次数"].sum())
            st.markdown(T.stats_row([
                ("商品数", f"{len(pdim):,}", "c-pink"),
                ("销售额合计($)", f"{tot_g:,.0f}", "c-green"),
                ("订单合计", f"{tot_o:,}", "c-purple"),
                ("点击合计", f"{tot_c:,}", "c-amber"),
            ]), unsafe_allow_html=True)
            fdf = _dim_filter_bar(pdim, "pd", [("商品类目", "商品类目")],
                                  ["网红", "商品名称", "商品ID"],
                                  ["销售额($)", "订单数", "点击次数", "视频观看次数"])
            prows = [[esc(r["网红"]),
                      esc(r["商品名称"]),
                      esc(r["商品ID"]),
                      (f'<a class="yts-link" href="{esc(r["商品链接"])}" '
                       f'target="_blank">商品↗</a>'),
                      esc(r["商品类目"] or "-"),
                      f'<span class="num">{r["视频观看次数"]:,}</span>',
                      f'<span class="num">{r["展示次数"]:,}</span>',
                      f'<span class="num">{r["点击次数"]:,}</span>',
                      f'<span class="num">{r["点击率(%)"]:.2f}%</span>',
                      f'<span class="num">{r["订单数"]:,}</span>',
                      f'<span class="num">{r["视频转化率(%)"]:.2f}%</span>',
                      f'<span class="num">{r["商品转化率(%)"]:.2f}%</span>',
                      f'<span class="num"><b>{r["销售额($)"]:,.0f}</b></span>',
                      f'<span class="num">{r["净销售额($)"]:,.0f}</span>',
                      f'<span class="num">{r["佣金($)"]:,.0f}</span>']
                     for _, r in fdf.iterrows()]
            T.component_html(
                T.table(["网红", "商品名称", "商品ID", "商品链接", "商品类目",
                         "视频观看次数", "展示次数", "点击次数", "点击率(%)",
                         "订单数", "视频转化率(%)", "商品转化率(%)",
                         "销售额($)", "净销售额($)", "佣金($)"], prows, wrap=False),
                height=52 + len(prows) * 36)
            st.markdown(T.foot("点击率(%) = 点击 ÷ 展示 × 100 · "
                               "视频转化率(%) = 订单 ÷ 视频观看次数 × 100 · "
                               "商品转化率(%) = 订单 ÷ 点击 × 100 · 金额单位为美元($)"),
                        unsafe_allow_html=True)

    # ---- 🩺 数据健康：全量数据质量检查（不受月份筛选影响） ----
    with tab_health:
        _render_health(store.list_all())


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
elif _qp.get("act") == "mail" and _qp.get("id"):
    _i = _qp.get("id")
    del st.query_params["act"]
    del st.query_params["id"]
    store.mark_emailed(_i)
    st.session_state.page = "dig"
    st.toast("已标记「已发邮件」，留在挖掘池，待标记「洽谈中」")

page = st.session_state.page
try:
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
except YidaFetchError as e:
    # 宜搭首次连接失败：不整页崩溃，显示友好提示+重试按钮
    st.error("⚠️ 宜搭数据暂时连不上，页面未能加载。\n\n"
             "这通常是宜搭接口短暂波动，**不是你的操作问题**。")
    st.caption(f"详情：{e}")
    if st.button("🔄 重试加载", type="primary"):
        st.rerun()
