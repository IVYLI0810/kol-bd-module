#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BD 网红底库 - 独立 Streamlit Demo

大表单目标：
- 与 kol-finder 挖掘库联动，状态为「已引入」的网红自动进入 BD 底库
- 一页展示所有关键字段：
  昵称 / 状态 / 粉丝 / 总播放 / 垂类 / 主页链接 / 分析 / 邮件 / 视频回链 / 播放 / 点赞 / 评论 / 商品链接 / 浏览 / 点击 / 转化 / GMV
- 支持单个编辑、批量导入（CSV/Excel）、视频数据追踪后回写

说明：
- 默认使用本地 SQLite，方便 demo
- 生产环境可切到 Supabase（在侧边栏配置）
"""

import json
import os
from collections import Counter
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from bd_database import LocalBDDB, SupabaseBDDB, SUPABASE_MIGRATION_SQL, get_bd_db
from youtube_analyzer import YouTubeAnalyzer, extract_channel_id, extract_video_id
from ai_email_generator import AIEmailGenerator
from product_importer import generate_template_df, parse_upload_file, validate_and_transform


# ---------------------------------------------------------------------------
# 常量 & 默认数据
# ---------------------------------------------------------------------------

SAMPLE_PRODUCT = {
    "name": "메이크업 브러쉬 10종 세트",
    "price": "12,900",
    "original_price": "28,900",
    "selling_points": [
        "부드러운 인조모가 피부에 자극이 적어요",
        "파우치 포함이라 여행/외출할 때 편해요",
        "초보자도 바로 쓸 수 있는 기본 구성",
        "세척 후에도 털이 빠지지 않아요",
    ],
}

# 默认不再自动写入示例数据；需要演示时设置环境变量 SEED_SAMPLE_DATA=1
SEED_SAMPLE_DATA = os.environ.get("SEED_SAMPLE_DATA", "0") == "1"

# 演示数据：把 kol-finder 里「已引入」的网红同步过来后的样子
DEFAULT_BD_INFLUENCERS = [
    {
        "channel_id": "UC_sample_chiljjang",
        "channel_name": "칠짱이",
        "channel_url": "https://www.youtube.com/@7nolgo",
        "category": "뷰티 & 헬스",
        "recruiter": "아이비",
        "subscribers": 15000,
        "total_views": 2500000,
        "status": "已引入",
        "video_link": "https://www.youtube.com/shorts/xxx",
        "video_views": 120000,
        "video_likes": 5600,
        "video_comments": 320,
        "product_link": "https://ko.aliexpress.com/item/xxx",
        "product_views": 45000,
        "product_clicks": 1200,
        "product_conversions": 180,
        "gmv": 2322000,
    },
    {
        "channel_id": "UC_sample_nailjip",
        "channel_name": "네일집착걸",
        "channel_url": "https://www.youtube.com/@obsess_nail",
        "category": "뷰티 & 헬스",
        "recruiter": "아이비",
        "subscribers": 22000,
        "total_views": 4800000,
        "status": "已引入",
        "video_link": "https://www.youtube.com/watch?v=yyy",
        "video_views": 89000,
        "video_likes": 4100,
        "video_comments": 210,
        "product_link": "https://ko.aliexpress.com/item/yyy",
        "product_views": 32000,
        "product_clicks": 950,
        "product_conversions": 140,
        "gmv": 1806000,
    },
    {
        "channel_id": "UC_sample_if",
        "channel_name": "이프 if",
        "channel_url": "https://www.youtube.com/@ifyoulovemeornot",
        "category": "뷰티 & 헬스",
        "recruiter": "아이비",
        "subscribers": 18000,
        "total_views": 1200000,
        "status": "已引入",
        "video_link": "",
        "video_views": 0,
        "video_likes": 0,
        "video_comments": 0,
        "product_link": "",
        "product_views": 0,
        "product_clicks": 0,
        "product_conversions": 0,
        "gmv": 0,
    },
]


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

def init_db():
    """初始化数据库连接"""
    if "bd_db" not in st.session_state:
        use_supabase = st.session_state.get("use_supabase", False)
        if use_supabase:
            st.session_state.bd_db = get_bd_db(
                use_supabase=True,
                supabase_url=st.session_state.get("supabase_url", ""),
                supabase_key=st.session_state.get("supabase_key", ""),
            )
        else:
            st.session_state.bd_db = LocalBDDB("bd_influencers_demo.db")


def seed_sample_data():
    """如果没有数据，写入三位示例网红"""
    db = st.session_state.bd_db
    existing = db.get_all()
    if not existing:
        for inf in DEFAULT_BD_INFLUENCERS:
            db.add(inf)


# ---------------------------------------------------------------------------
# UI 组件
# ---------------------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.title("⚙️ 配置")

        st.session_state.use_supabase = st.toggle("使用 Supabase", value=False)
        if st.session_state.use_supabase:
            st.session_state.supabase_url = st.text_input("Supabase URL", value="")
            st.session_state.supabase_key = st.text_input("Supabase Key", value="", type="password")
            with st.expander("查看 Supabase 建表 SQL"):
                st.code(SUPABASE_MIGRATION_SQL, language="sql")
        else:
            st.info("当前使用本地 SQLite 数据库（bd_influencers_demo.db）")

        st.divider()
        st.session_state.youtube_api_key = st.text_input(
            "YouTube Data API Key",
            value=os.environ.get("YOUTUBE_API_KEY", ""),
            type="password",
        )

        st.divider()
        st.subheader("AI 邮件生成配置")
        st.session_state.ai_provider = st.selectbox(
            "AI Provider",
            ["openai", "gemini", "dashscope"],
            index=2,
        )
        st.session_state.ai_api_key = st.text_input(
            f"{st.session_state.ai_provider.upper()} API Key",
            value=os.environ.get(f"{st.session_state.ai_provider.upper()}_API_KEY", ""),
            type="password",
        )
        st.session_state.ai_model = st.text_input(
            "模型名（留空用默认）",
            value="",
            placeholder="qwen-turbo / gpt-4o-mini / gemini-1.5-flash",
        )
        st.session_state.sender_name = st.text_input("发件人姓名", value="아이비")


def fmt_num(v):
    """把数字格式化成易读形式"""
    if v is None:
        return "-"
    try:
        n = int(v)
    except (TypeError, ValueError):
        return str(v)
    if n >= 10000:
        return f"{n / 10000:.1f}w"
    return f"{n:,}"


def fmt_money(v):
    """把金额格式化成韩元样式"""
    if v is None or v == "":
        return "-"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if n >= 1000000:
        return f"{n / 1000000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return f"{n:,.0f}"


@st.dialog("视频详情")
def video_detail_dialog(record: dict):
    """弹窗展示视频回链与播放/点赞/评论，并支持更新/删除"""
    vlink = record.get("video_link", "")
    if vlink:
        st.markdown(f"**视频回链**：[打开]({vlink})")
    else:
        st.markdown("**视频回链**：-")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("播放", fmt_num(record.get("video_views")))
    with c2:
        st.metric("点赞", fmt_num(record.get("video_likes")))
    with c3:
        st.metric("评论", fmt_num(record.get("video_comments")))

    st.divider()
    new_link = st.text_input(
        "更新视频链接",
        value=vlink,
        key=f"upd_video_link_{record['channel_id']}",
    )
    b1, b2 = st.columns(2)
    with b1:
        if st.button("更新链接", use_container_width=True, key=f"upd_video_{record['channel_id']}"):
            db = st.session_state.bd_db
            db.update(record["channel_id"], {"video_link": new_link})
            st.success("已更新")
            st.rerun()
    with b2:
        if st.button("删除视频回链", use_container_width=True, key=f"del_video_{record['channel_id']}"):
            db = st.session_state.bd_db
            db.update(
                record["channel_id"],
                {
                    "video_link": "",
                    "video_views": 0,
                    "video_likes": 0,
                    "video_comments": 0,
                },
            )
            st.success("已删除")
            st.rerun()


@st.dialog("添加视频回链")
def add_video_dialog(record: dict):
    """弹窗为网红添加视频回链，可选自动抓取数据"""
    st.markdown(f"**{record.get('channel_name', '-')}")
    video_url = st.text_input(
        "YouTube 视频链接",
        placeholder="https://www.youtube.com/watch?v=... 或 /shorts/...",
        key=f"add_video_url_{record['channel_id']}",
    )
    fetch_stats = st.toggle(
        "自动抓取播放/点赞/评论",
        value=True,
        key=f"add_video_fetch_{record['channel_id']}",
    )
    if st.button("保存", use_container_width=True, key=f"add_video_save_{record['channel_id']}"):
        if not video_url:
            st.error("请输入视频链接")
            return
        update = {"video_link": video_url}
        if fetch_stats:
            api_key = st.session_state.get("youtube_api_key", "")
            if not api_key:
                st.error("请先配置 YouTube API Key")
                return
            try:
                analyzer = YouTubeAnalyzer(api_key)
                video_id = extract_video_id(video_url)
                if not video_id:
                    st.error("无法识别视频链接")
                    return
                stats = analyzer.get_video_stats(video_id)
                update.update({
                    "video_views": stats["view_count"],
                    "video_likes": stats["like_count"],
                    "video_comments": stats["comment_count"],
                })
            except Exception as e:
                st.error(f"抓取失败：{e}")
                return
        db = st.session_state.bd_db
        db.update(record["channel_id"], update)
        st.success("已保存")
        st.rerun()


@st.dialog("确认删除")
def bulk_delete_dialog(selected: list):
    """批量删除确认弹窗"""
    if not selected:
        st.info("没有选中的网红")
        return
    st.markdown(f"确定删除以下 **{len(selected)}** 位网红吗？")
    names = ", ".join(r.get("channel_name", "-") for r in selected)
    st.caption(names)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("取消", use_container_width=True, key="bulk_delete_cancel"):
            st.rerun()
    with c2:
        if st.button("确认删除", use_container_width=True, key="bulk_delete_confirm"):
            db = st.session_state.bd_db
            for r in selected:
                db.delete(r["channel_id"])
            # 清除选择状态
            st.session_state["bd_selected_ids"] = []
            st.success(f"已删除 {len(selected)} 位网红")
            st.rerun()


@st.dialog("转化详情")
def conversion_detail_dialog(record: dict):
    """弹窗展示商品链接与浏览/点击/转化/GMV"""
    plink = record.get("product_link", "")
    if plink:
        st.markdown(f"**商品链接**：[打开]({plink})")
    else:
        st.markdown("**商品链接**：-")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("浏览", fmt_num(record.get("product_views")))
    with c2:
        st.metric("点击", fmt_num(record.get("product_clicks")))
    with c3:
        st.metric("转化", fmt_num(record.get("product_conversions")))
    with c4:
        st.metric("GMV", fmt_money(record.get("gmv")))


@st.dialog("爆款分析")
def viral_dialog(record: dict):
    """弹窗展示爆款分析结果"""
    run_viral_analysis(record)


@st.dialog("脚本 + 邮件")
def script_email_dialog(record: dict):
    """弹窗展示拍摄框架与邀请邮件"""
    run_script_email(record)


@st.dialog("编辑数据")
def edit_metrics_dialog(record: dict):
    """弹窗直接修改数字指标"""
    st.markdown(f"**{record.get('channel_name', '-')}**")
    c1, c2 = st.columns(2)
    with c1:
        subscribers = st.number_input(
            "粉丝", min_value=0, value=int(record.get("subscribers") or 0), step=1000
        )
        total_views = st.number_input(
            "总播放", min_value=0, value=int(record.get("total_views") or 0), step=1000
        )
        video_views = st.number_input(
            "播放", min_value=0, value=int(record.get("video_views") or 0), step=1000
        )
        video_likes = st.number_input(
            "点赞", min_value=0, value=int(record.get("video_likes") or 0), step=100
        )
        video_comments = st.number_input(
            "评论", min_value=0, value=int(record.get("video_comments") or 0), step=100
        )
    with c2:
        product_views = st.number_input(
            "浏览", min_value=0, value=int(record.get("product_views") or 0), step=1000
        )
        product_clicks = st.number_input(
            "点击", min_value=0, value=int(record.get("product_clicks") or 0), step=100
        )
        product_conversions = st.number_input(
            "转化", min_value=0, value=int(record.get("product_conversions") or 0), step=10
        )
        gmv = st.number_input(
            "GMV (KRW)", min_value=0.0, value=float(record.get("gmv") or 0), step=10000.0
        )

    if st.button("保存", key=f"save_edit_{record['channel_id']}"):
        db = st.session_state.bd_db
        db.update(
            record["channel_id"],
            {
                "subscribers": int(subscribers),
                "total_views": int(total_views),
                "video_views": int(video_views),
                "video_likes": int(video_likes),
                "video_comments": int(video_comments),
                "product_views": int(product_views),
                "product_clicks": int(product_clicks),
                "product_conversions": int(product_conversions),
                "gmv": float(gmv),
            },
        )
        st.success("已保存")
        st.rerun()


@st.dialog("网红详情")
def row_detail_dialog(record: dict):
    """点击表格行打开的详情弹窗，集中所有行级操作"""
    st.markdown(f"### {record.get('channel_name', '-')}")
    st.caption(f"状态：{record.get('status', '-')} ｜ 垂类：{record.get('category', '-')} ｜ 挖掘人：{record.get('recruiter', '-')}")

    channel_url = record.get("channel_url", "")
    if channel_url:
        st.markdown(f"[🌐 打开 YouTube 主页]({channel_url})")

    st.divider()

    tab_names = ["数据总览", "爆款分析", "脚本 + 邮件"]
    if record.get("video_link"):
        tab_names.append("视频回链")
    else:
        tab_names.append("添加视频")
    if record.get("product_link"):
        tab_names.append("转化详情")
    tab_names.append("编辑 / 删除")

    tabs = st.tabs(tab_names)
    idx = 0

    with tabs[idx]:
        idx += 1
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("粉丝", fmt_num(record.get("subscribers")))
            st.metric("播放", fmt_num(record.get("video_views")))
        with c2:
            st.metric("总播放", fmt_num(record.get("total_views")))
            st.metric("点赞", fmt_num(record.get("video_likes")))
        with c3:
            st.metric("浏览", fmt_num(record.get("product_views")))
            st.metric("评论", fmt_num(record.get("video_comments")))
        with c4:
            st.metric("点击", fmt_num(record.get("product_clicks")))
            st.metric("转化", fmt_num(record.get("product_conversions")))
        st.metric("GMV", fmt_money(record.get("gmv")))

    with tabs[idx]:
        idx += 1
        run_viral_analysis(record)

    with tabs[idx]:
        idx += 1
        run_script_email(record)

    if record.get("video_link"):
        with tabs[idx]:
            idx += 1
            video_detail_dialog(record)
    else:
        with tabs[idx]:
            idx += 1
            add_video_dialog(record)

    if record.get("product_link"):
        with tabs[idx]:
            idx += 1
            conversion_detail_dialog(record)
    else:
        idx += 1

    with tabs[idx]:
        idx += 1
        c1, c2 = st.columns(2)
        with c1:
            if st.button("编辑数据", use_container_width=True, key=f"detail_edit_{record['channel_id']}"):
                st.session_state[f"open_edit_{record['channel_id']}"] = True
                st.rerun()
        with c2:
            if st.button("删除网红", type="primary", use_container_width=True, key=f"detail_delete_{record['channel_id']}"):
                db = st.session_state.bd_db
                db.delete(record["channel_id"])
                st.success("已删除")
                st.rerun()

    if st.session_state.pop(f"open_edit_{record['channel_id']}", False):
        edit_metrics_dialog(record)


@st.dialog("筛选 & 排序")
def filter_dialog(records: list):
    """弹窗集中设置所有筛选条件和排序"""
    statuses = sorted({r.get("status", "-") for r in records})
    categories = sorted({r.get("category", "-") for r in records})
    recruiters = sorted({r.get("recruiter", "-") for r in records})

    c1, c2 = st.columns(2)
    with c1:
        st.multiselect(
            "状态",
            options=statuses,
            default=st.session_state.get("filter_status", []),
            key="dlg_status",
        )
        st.multiselect(
            "垂类",
            options=categories,
            default=st.session_state.get("filter_category", []),
            key="dlg_category",
        )
        st.number_input(
            "粉丝 ≥",
            min_value=0,
            value=int(st.session_state.get("filter_sub_min", 0)),
            step=1000,
            key="dlg_sub_min",
        )
        st.number_input(
            "GMV ≥",
            min_value=0.0,
            value=float(st.session_state.get("filter_gmv_min", 0.0)),
            step=100000.0,
            key="dlg_gmv_min",
        )
        st.selectbox(
            "视频回链",
            options=["全部", "有", "无"],
            index=["全部", "有", "无"].index(st.session_state.get("filter_has_video", "全部")),
            key="dlg_has_video",
        )
    with c2:
        st.multiselect(
            "挖掘人",
            options=recruiters,
            default=st.session_state.get("filter_recruiter", []),
            key="dlg_recruiter",
        )
        st.selectbox(
            "排序",
            options=[
                "默认",
                "GMV 从高到低",
                "GMV 从低到高",
                "总播放 从高到低",
                "播放量 从高到低",
                "点赞数 从高到低",
                "评论数 从高到低",
            ],
            index=[
                "默认",
                "GMV 从高到低",
                "GMV 从低到高",
                "总播放 从高到低",
                "播放量 从高到低",
                "点赞数 从高到低",
                "评论数 从高到低",
            ].index(st.session_state.get("filter_sort", "默认")),
            key="dlg_sort",
        )
        st.number_input(
            "粉丝 ≤",
            min_value=0,
            value=int(st.session_state.get("filter_sub_max", 0)),
            step=1000,
            help="0 表示不限",
            key="dlg_sub_max",
        )
        st.number_input(
            "GMV ≤",
            min_value=0.0,
            value=float(st.session_state.get("filter_gmv_max", 0.0)),
            step=100000.0,
            help="0 表示不限",
            key="dlg_gmv_max",
        )
        st.selectbox(
            "商品链接",
            options=["全部", "有", "无"],
            index=["全部", "有", "无"].index(st.session_state.get("filter_has_product", "全部")),
            key="dlg_has_product",
        )

    b1, b2 = st.columns(2)
    with b1:
        if st.button("应用", use_container_width=True, key="dlg_apply"):
            st.session_state.filter_status = st.session_state.get("dlg_status", [])
            st.session_state.filter_category = st.session_state.get("dlg_category", [])
            st.session_state.filter_recruiter = st.session_state.get("dlg_recruiter", [])
            st.session_state.filter_sub_min = st.session_state.get("dlg_sub_min", 0)
            st.session_state.filter_sub_max = st.session_state.get("dlg_sub_max", 0)
            st.session_state.filter_gmv_min = st.session_state.get("dlg_gmv_min", 0.0)
            st.session_state.filter_gmv_max = st.session_state.get("dlg_gmv_max", 0.0)
            st.session_state.filter_has_video = st.session_state.get("dlg_has_video", "全部")
            st.session_state.filter_has_product = st.session_state.get("dlg_has_product", "全部")
            st.session_state.filter_sort = st.session_state.get("dlg_sort", "默认")
            st.rerun()
    with b2:
        if st.button("重置", use_container_width=True, key="dlg_reset"):
            for k in [
                "filter_status", "filter_category", "filter_recruiter",
                "filter_sub_min", "filter_sub_max", "filter_gmv_min", "filter_gmv_max",
                "filter_has_video", "filter_has_product", "filter_sort",
            ]:
                st.session_state.pop(k, None)
            st.rerun()


def _build_bd_table_html(records: list, selected_ids: list) -> str:
    """用真实 HTML <table> 渲染 BD 底库表格，保证跨行严格对齐"""
    # 列定义：(表头, 宽度 px, 对齐, 取值函数, 额外 class)
    cols = [
        ("", 66, "center", lambda r: r['channel_id'], ""),
        ("昵称", 192, "left", lambda r: _html_escape(r.get("channel_name", "-")), ""),
        ("状态", 96, "left", lambda r: _html_escape(r.get("status", "-")), lambda r: "bd-status" if r.get("status") == "已引入" else ("bd-empty" if not r.get("status") or r.get("status") == "-" else "")),
        ("粉丝", 96, "right", lambda r: fmt_num(r.get("subscribers")), "bd-num"),
        ("总播放", 96, "right", lambda r: fmt_num(r.get("total_views")), "bd-num"),
        ("垂类", 140, "left", lambda r: _html_escape(r.get("category", "-")), ""),
        ("主页", 88, "center", lambda r: _bd_home_cell(r.get("channel_url", "")), ""),
        ("回链", 96, "center", lambda r: _bd_video_cell(r), ""),
        ("播放", 88, "right", lambda r: fmt_num(r.get("video_views")), "bd-num"),
        ("点赞", 88, "right", lambda r: fmt_num(r.get("video_likes")), "bd-num"),
        ("评论", 88, "right", lambda r: fmt_num(r.get("video_comments")), "bd-num"),
        ("商品链接", 96, "center", lambda r: _bd_product_cell(r.get("product_link", "")), ""),
        ("浏览", 88, "right", lambda r: fmt_num(r.get("product_views")), "bd-num"),
        ("点击", 88, "right", lambda r: fmt_num(r.get("product_clicks")), "bd-num"),
        ("转化", 88, "right", lambda r: fmt_num(r.get("product_conversions")), "bd-num"),
        ("GMV", 104, "right", lambda r: fmt_money(r.get("gmv")), "bd-num"),
    ]

    selected_set = set(selected_ids)

    def _th(header, width, align):
        if header == "":
            return f"<th style='width:{width}px;text-align:center;'><input type='checkbox' id='bd-select-all'></th>"
        return f"<th style='width:{width}px;text-align:{align};'>{header}</th>"

    def _td(content, width, align, cid=None, extra_class=""):
        cls = "bd-td"
        if align == "right":
            cls += " bd-num"
        elif align == "center":
            cls += " bd-center"
        if extra_class:
            cls += f" {extra_class}"
        attrs = f"style='width:{width}px;text-align:{align};'"
        if cid:
            attrs += f" data-cid='{cid}'"
        return f"<td {attrs}><p class='{cls}'>{content}</p></td>"

    thead = "<thead><tr>" + "".join(_th(h, w, a) for h, w, a, _, _ in cols) + "</tr></thead>"

    rows = []
    for r in records:
        cid = r["channel_id"]
        cells = []
        for (h, w, a, fn, extra) in cols:
            if h == "":
                checked = "checked" if cid in selected_set else ""
                cells.append(f"<td style='width:{w}px;text-align:center;'><input type='checkbox' class='bd-row-checkbox' value='{cid}' {checked} onclick='event.stopPropagation(); toggleRow(\"{cid}\")'></td>")
            else:
                ec = extra(r) if callable(extra) else extra
                cells.append(_td(fn(r), w, a, cid=cid, extra_class=ec))
        rows.append(f"<tr class='bd-row' data-cid='{cid}'>" + "".join(cells) + "</tr>")

    tbody = "<tbody>" + "".join(rows) + "</tbody>"
    table = f"<table class='bd-table'>{thead}{tbody}</table>"

    script = f"""
    <script>
    (function() {{
        var selected = new Set({json.dumps(list(selected_set))});
        var lastClicked = null;

        function send() {{
            var payload = JSON.stringify({{
                selected: Array.from(selected),
                clicked: lastClicked
            }});
            if (window.parent) {{
                window.parent.postMessage({{
                    type: 'streamlit:setComponentValue',
                    value: payload
                }}, '*');
            }}
            lastClicked = null;
        }}

        function toggleRow(cid) {{
            if (selected.has(cid)) selected.delete(cid);
            else selected.add(cid);
            send();
        }}

        function selectAll(checked) {{
            var rows = document.querySelectorAll('.bd-row');
            rows.forEach(function(row) {{
                var cid = row.getAttribute('data-cid');
                var cb = row.querySelector('.bd-row-checkbox');
                if (checked) selected.add(cid);
                else selected.delete(cid);
                if (cb) cb.checked = checked;
            }});
            send();
        }}

        document.querySelectorAll('.bd-row').forEach(function(row) {{
            row.addEventListener('click', function(e) {{
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'A') return;
                var cid = row.getAttribute('data-cid');
                lastClicked = cid;
                send();
            }});
        }});

        var selectAllCb = document.getElementById('bd-select-all');
        if (selectAllCb) {{
            selectAllCb.addEventListener('change', function(e) {{
                selectAll(e.target.checked);
            }});
        }}

        // 初始化时同步一次
        send();
    }})();
    </script>
    """

    inline_css = """
    <style>
    /* 组件 iframe 内不能依赖外部字体，否则网络受阻时整表会白屏 */
    * { box-sizing: border-box; }
    body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', 'Noto Sans KR', 'Microsoft YaHei', sans-serif; }
    .bd-table-wrapper {
        overflow-x: auto;
        width: 100%;
        border-radius: 8px;
        padding-bottom: 4px;
    }
    .bd-table-wrapper::-webkit-scrollbar { height: 8px; }
    .bd-table-wrapper::-webkit-scrollbar-track { background: #F9EEF1; border-radius: 4px; }
    .bd-table-wrapper::-webkit-scrollbar-thumb { background: #E8B4C0; border-radius: 4px; }
    .bd-table-wrapper::-webkit-scrollbar-thumb:hover { background: #B8989E; }
    .bd-table {
        table-layout: fixed;
        width: 1600px;
        border-collapse: collapse;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', 'Noto Sans KR', 'Microsoft YaHei', sans-serif;
    }
    .bd-table th {
        font-size: 11px;
        font-weight: 800;
        color: #7A4A55;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        padding: 12px 8px;
        line-height: 1.4;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        border-bottom: 3px solid #D97A8A;
        background: #FFFFFF;
        text-align: left;
        vertical-align: middle;
    }
    .bd-table th input[type="checkbox"] {
        width: 18px;
        height: 18px;
        accent-color: #D97A8A;
        cursor: pointer;
        margin: 0;
    }
    .bd-table td {
        padding: 0;
        border-bottom: 2px solid #F9EEF1;
        vertical-align: middle;
    }
    .bd-table td p {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', 'Noto Sans KR', 'Microsoft YaHei', sans-serif;
        font-size: 13px;
        font-weight: 500;
        color: #111827;
        margin: 0;
        padding: 11px 8px;
        line-height: 1.5;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .bd-table td p.bd-num {
        font-variant-numeric: tabular-nums;
        text-align: right;
        font-weight: 600;
    }
    .bd-table td p.bd-center {
        text-align: center;
    }
    .bd-table td p.bd-empty {
        color: #B8989E;
        font-weight: 400;
    }
    .bd-table td p.bd-status {
        color: #D97A8A;
        font-weight: 700;
    }
    .bd-table td a {
        color: #D97A8A;
        text-decoration: none;
        font-weight: 600;
    }
    .bd-table td a:hover {
        text-decoration: underline;
    }
    .bd-table tbody tr {
        cursor: pointer;
        transition: background 0.15s ease;
    }
    .bd-table tbody tr:hover {
        background: #FDF6F8;
    }
    .bd-table tbody tr td:first-child {
        text-align: center;
    }
    .bd-table tbody tr td:first-child input[type="checkbox"] {
        width: 18px;
        height: 18px;
        accent-color: #D97A8A;
        cursor: pointer;
        margin: 0;
    }
    </style>
    """

    return f"""
    {inline_css}
    <div class='bd-table-wrapper'>
        {table}
    </div>
    {script}
    """


def _html_escape(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    return (s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _bd_home_cell(url: str) -> str:
    if url:
        return f"<a href='{_html_escape(url)}' target='_blank' onclick='event.stopPropagation()'>主页</a>"
    return "-"


def _bd_video_cell(r: dict) -> str:
    vlink = r.get("video_link", "")
    if vlink:
        return f"<a href='{_html_escape(vlink)}' target='_blank' onclick='event.stopPropagation()'>视频</a>"
    return "-"


def _bd_product_cell(url: str) -> str:
    if url:
        return f"<a href='{_html_escape(url)}' target='_blank' onclick='event.stopPropagation()'>商品</a>"
    return "-"


def render_bd_table():
    db = st.session_state.bd_db
    records = db.get_all()

    # 顶部操作：同步挖掘库（演示用）
    c1, c2 = st.columns([1, 4])
    with c1:
        if st.button("同步 kol-finder 挖掘库", use_container_width=True):
            _sync_discovery_demo(db)
    with c2:
        st.caption("只同步挖掘库中状态为「已引入」的网红。生产环境会自动触发，无需手动点击。")

    if not records:
        st.info("底库为空，先去「添加网红」页添加，或点击上方「同步挖掘库」。")
        return

    st.divider()

    # 搜索 + 筛选入口
    sc1, sc2 = st.columns([4, 1])
    with sc1:
        search = st.text_input(
            "搜索昵称 / 垂类 / 挖掘人",
            placeholder="输入关键词筛选...",
            key="bd_search",
            label_visibility="collapsed",
        )
    with sc2:
        if st.button("筛选", use_container_width=True, key="bd_filter_btn"):
            filter_dialog(records)

    # 从弹窗读取筛选条件
    sel_status = st.session_state.get("filter_status", [])
    sel_category = st.session_state.get("filter_category", [])
    sel_recruiter = st.session_state.get("filter_recruiter", [])
    sub_min = int(st.session_state.get("filter_sub_min", 0) or 0)
    sub_max = int(st.session_state.get("filter_sub_max", 0) or 0)
    gmv_min = float(st.session_state.get("filter_gmv_min", 0.0) or 0.0)
    gmv_max = float(st.session_state.get("filter_gmv_max", 0.0) or 0.0)
    has_video = st.session_state.get("filter_has_video", "全部")
    has_product = st.session_state.get("filter_has_product", "全部")
    sort_by = st.session_state.get("filter_sort", "默认")

    # 应用筛选
    def _match(rec):
        if sel_status and rec.get("status") not in sel_status:
            return False
        if sel_category and rec.get("category") not in sel_category:
            return False
        if sel_recruiter and rec.get("recruiter") not in sel_recruiter:
            return False
        s = int(rec.get("subscribers") or 0)
        if sub_min and s < sub_min:
            return False
        if sub_max and s > sub_max:
            return False
        g = float(rec.get("gmv") or 0)
        if gmv_min and g < gmv_min:
            return False
        if gmv_max and g > gmv_max:
            return False
        if has_video == "有" and not rec.get("video_link"):
            return False
        if has_video == "无" and rec.get("video_link"):
            return False
        if has_product == "有" and not rec.get("product_link"):
            return False
        if has_product == "无" and rec.get("product_link"):
            return False
        return True

    records = [r for r in records if _match(r)]

    if search:
        query = search.lower()
        records = [
            r for r in records
            if any(query in str(r.get(k, "")).lower() for k in ("channel_name", "category", "recruiter"))
        ]

    # 排序
    if sort_by == "GMV 从高到低":
        records = sorted(records, key=lambda x: float(x.get("gmv") or 0), reverse=True)
    elif sort_by == "GMV 从低到高":
        records = sorted(records, key=lambda x: float(x.get("gmv") or 0))
    elif sort_by == "总播放 从高到低":
        records = sorted(records, key=lambda x: int(x.get("total_views") or 0), reverse=True)
    elif sort_by == "播放量 从高到低":
        records = sorted(records, key=lambda x: int(x.get("video_views") or 0), reverse=True)
    elif sort_by == "点赞数 从高到低":
        records = sorted(records, key=lambda x: int(x.get("video_likes") or 0), reverse=True)
    elif sort_by == "评论数 从高到低":
        records = sorted(records, key=lambda x: int(x.get("video_comments") or 0), reverse=True)

    st.caption(f"共 {len(records)} 条")

    # 读取 HTML 组件上一次返回的选中状态
    selected_ids = st.session_state.get("bd_selected_ids", [])

    # 批量操作栏
    bulk_cols = st.columns([0.12, 0.88])
    with bulk_cols[0]:
        if st.button("删除选中", key="bulk_delete_btn", type="primary"):
            selected = [r for r in records if r["channel_id"] in selected_ids]
            bulk_delete_dialog(selected)
    with bulk_cols[1]:
        if selected_ids:
            st.caption(f"已选中 {len(selected_ids)} 位网红")

    # 真实 HTML 表格：表头和数据在同一 <table> 内，严格对齐
    table_html = _build_bd_table_html(records, selected_ids)
    row_height = 42
    header_height = 40
    table_height = max(200, header_height + len(records) * row_height + 20)

    result = components.html(table_html, height=table_height, scrolling=False)

    # 处理表格组件返回的状态
    if result:
        try:
            data = json.loads(result) if isinstance(result, str) else result
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        new_selected = data.get("selected", [])
        clicked_id = data.get("clicked")

        if new_selected != selected_ids:
            st.session_state.bd_selected_ids = new_selected
            st.rerun()

        if clicked_id:
            clicked_record = next((r for r in records if r["channel_id"] == clicked_id), None)
            if clicked_record:
                row_detail_dialog(clicked_record)


def _sync_discovery_demo(db):
    """演示：模拟从 kol-finder 挖掘库同步「已引入」网红"""
    demo_discovery = [
        {
            "channel_id": "UC_demo_sync_1",
            "channel_name": "同步示例网红",
            "channel_url": "https://www.youtube.com/@sync_example",
            "category": "뷰티",
            "subscribers": 30000,
            "total_views": 1500000,
            "discovered_by": "아이비",
            "status": "已引入",
        },
    ]
    try:
        count = db.sync_from_discovery(demo_discovery)
        st.success(f"已同步 {count} 条记录")
        st.rerun()
    except Exception as e:
        st.error(f"同步失败：{e}")


def _extract_dna_from_result(record: dict, result: dict) -> dict:
    """从 YouTube 分析结果中解析内容 DNA"""
    videos = []
    for key in ("top_exposure", "top_engagement", "top_conversion"):
        videos.extend(result.get(key, []))
    # 去重
    seen = set()
    unique_videos = []
    for v in videos:
        vid = v.get("video_id")
        if vid and vid not in seen:
            seen.add(vid)
            unique_videos.append(v)

    # 合并标题、描述、评论
    titles = [v.get("title", "") for v in unique_videos]
    descriptions = [v.get("description", "") for v in unique_videos]
    comments = []
    for v in unique_videos:
        comments.extend(v.get("comments", []))

    corpus_text = " ".join(titles + descriptions + comments)

    # 1. 内容基调
    tone_keywords = {
        "真实测评型": ["리뷰", "솔직", "후기", "정말", "진짜", "사용해", "써봤"],
        "好物种草/推荐型": ["추천", "인생", "베스트", "TOP", "필수템", "템"],
        "折扣拼团型": ["공구", "할인", "쿠폰", "세일", "가격", "원", "공동구매"],
        "日常Vlog型": ["브이로그", "vlog", "일상", "하루", "루틴"],
        "教程/干货型": ["꿀팁", "방법", "정리", "팁", "사용법", "설명"],
        "对比/挑战型": ["VS", "비교", "차이", "대결", "테스트"],
    }
    tone_scores = Counter()
    for tone, kws in tone_keywords.items():
        for kw in kws:
            tone_scores[tone] += corpus_text.lower().count(kw.lower())
    content_tone = tone_scores.most_common(1)[0][0] if tone_scores else "亲切闺蜜型"

    # 2. 粉丝称呼
    fan_calls = ["여러분", "구독자님", "언니", "누나", "언님", "오빠", "형", "누님", "동생", "친구", "우리"]
    fan_scores = Counter()
    for c in fan_calls:
        fan_scores[c] += corpus_text.count(c)
    # 若评论区有明确称呼，优先用评论
    for c in comments:
        for call in fan_calls:
            if call in c:
                fan_scores[call] += 2
    fan_nickname = fan_scores.most_common(1)[0][0] if fan_scores else "여러분"

    # 3. 常用钩子
    hook_keywords = {
        "价格/折扣钩子": ["할인", "쿠폰", "세일", "공구", "가격", "원", "얼마"],
        "提问/对比钩子": ["?", "왜", "어떻게", "VS", "비교", "차이", "뭐가"],
        "震惊/好奇钩子": ["충격", "대박", "헐", "미친", "이런", "사실", "공개", "드디어"],
        "推荐/种草钩子": ["추천", "인생", "필수템", "템", "베스트", "TOP"],
    }
    hook_scores = Counter()
    for t in titles:
        lower_t = t.lower()
        for hook, kws in hook_keywords.items():
            for kw in kws:
                if kw.lower() in lower_t:
                    hook_scores[hook] += 1
                    break
    top_hooks = dict(hook_scores.most_common(3))

    # 4. 常用 CTA
    cta_keywords = {
        "구독/좋아요 요청": ["구독", "좋아요", "알림", "댓글"],
        "더보기란/링크 언급": ["더보기", "링크", "고정댓글", "구매", "구매링크"],
        "할인/쿠폰 안내": ["할인코드", "쿠폰", "코드"],
    }
    cta_scores = Counter()
    for text in titles + descriptions + comments:
        lower = text.lower()
        for cta, kws in cta_keywords.items():
            for kw in kws:
                if kw.lower() in lower:
                    cta_scores[cta] += 1
                    break
    top_ctas = dict(cta_scores.most_common(3))

    # 5. 内容垂类/支柱
    pillar_keywords = {
        "뷰티/메이크업": ["메이크업", "화장", "스킨케어", "화장품", "립", "섀도우", "마스칼라"],
        "패션/코디": ["옷", "패션", "코디", "룩", "ootd", "원피스", "가방"],
        "라이프/홈": ["홈", "인테리어", "정리", "집", "생활", "주방", "청소"],
        "푸드/요리": ["음식", "먹방", "요리", "레시피", "맛집", "디저트"],
        "펫/반려동물": ["강아지", "고양이", "반려", "펫", "애견"],
        "학생/데스크": ["학생", "학교", "데스크", "공부", "필기", "문구"],
    }
    pillar_scores = Counter()
    for text in titles + descriptions:
        lower = text.lower()
        for pillar, kws in pillar_keywords.items():
            for kw in kws:
                if kw.lower() in lower:
                    pillar_scores[pillar] += 1
                    break
    top_pillars = [p for p, _ in pillar_scores.most_common(3)]
    if not top_pillars and record.get("category"):
        top_pillars = [record.get("category")]

    # 6. 视频形式
    shorts_count = sum(1 for v in unique_videos if v.get("is_shorts"))
    long_count = len(unique_videos) - shorts_count

    return {
        "content_tone": content_tone,
        "fan_nickname": fan_nickname,
        "top_hook_patterns": top_hooks,
        "top_cta_patterns": top_ctas,
        "content_pillars": top_pillars,
        "shorts_count": shorts_count,
        "long_count": long_count,
        "best_reference": result.get("best_reference"),
        "total_videos": result.get("total_videos", 0),
    }


def _fmt_dna_for_prompt(dna: dict) -> str:
    """把 DNA 字典整理成给 AI 润色的 prompt"""
    ref = dna.get("best_reference") or {}
    ref_line = f"{ref.get('title', '-')} ({ref.get('view_count', 0):,} 播放)" if ref else "-"
    return f"""你是一位韩国 YouTube 内容策略专家。请根据以下由程序从该博主近期视频中提取的初稿，生成一份更精炼、地道的内容 DNA 卡片。

要求：
1. 用中文输出，关键词可保留韩语原文。
2. 包含：内容基调、粉丝称呼、Top 3 钩子类型、Top 3 CTA 方式、内容支柱、适合的视频形式。
3. 语气像给 BD 团队看的内部画像，简洁有力。

博主：{dna.get('channel_name', '')}
初稿：
- 内容基调：{dna.get('content_tone', '')}
- 粉丝称呼：{dna.get('fan_nickname', '')}
- 钩子类型：{', '.join(dna.get('top_hook_patterns', {}).keys()) or '-'}
- CTA 方式：{', '.join(dna.get('top_cta_patterns', {}).keys()) or '-'}
- 内容支柱：{', '.join(dna.get('content_pillars', [])) or '-'}
- 视频形式：Shorts {dna.get('shorts_count', 0)} 支 / 长视频 {dna.get('long_count', 0)} 支
- 最佳参考视频：{ref_line}
"""


def run_content_dna(record: dict, result: dict):
    """内容 DNA：基于爆款分析结果生成博主内容画像"""
    dna = _extract_dna_from_result(record, result)
    dna["channel_name"] = record.get("channel_name", "-")

    st.markdown("#### 🧬 内容 DNA 卡片")
    st.caption("基于近期 30 条视频与评论自动提取，可在邮件/脚本生成时直接复用")

    c1, c2 = st.columns(2)
    with c1:
        st.metric("内容基调", dna["content_tone"])
        st.metric("粉丝称呼", dna["fan_nickname"])
    with c2:
        st.metric("Shorts / 长视频", f"{dna['shorts_count']} / {dna['long_count']}")
        ref = dna.get("best_reference")
        if ref:
            st.metric("最佳参考", f"{'Shorts' if ref.get('is_shorts') else '长视频'}")
        else:
            st.metric("最佳参考", "-")

    st.markdown("**常用钩子类型**")
    if dna["top_hook_patterns"]:
        for hook, cnt in dna["top_hook_patterns"].items():
            st.markdown(f"- {hook}（{cnt} 次）")
    else:
        st.markdown("- 暂无明确信号")

    st.markdown("**常用 CTA 方式**")
    if dna["top_cta_patterns"]:
        for cta, cnt in dna["top_cta_patterns"].items():
            st.markdown(f"- {cta}（{cnt} 次）")
    else:
        st.markdown("- 暂无明确信号")

    st.markdown("**内容支柱**")
    if dna["content_pillars"]:
        st.markdown(", ".join([f"**{p}**" for p in dna["content_pillars"]]))
    else:
        st.markdown("- 暂无明确信号")

    if ref:
        st.markdown("**推荐参考视频**")
        title = ref.get("title", "-")
        url = ref.get("url", "")
        st.markdown(f"[{title}]({url})")
        st.caption(
            f"播放量 {ref.get('view_count', 0):,} ｜ 点赞 {ref.get('like_count', 0):,} ｜ "
            f"评论 {ref.get('comment_count', 0):,}"
        )

    # AI 润色（可选）
    ai_key = st.session_state.get("ai_api_key", "")
    provider = st.session_state.get("ai_provider", "dashscope")
    model = st.session_state.get("ai_model", "") or None
    if ai_key:
        if st.button("✨ AI 精炼 DNA", key=f"refine_dna_{record['channel_id']}"):
            with st.spinner("正在用 AI 精炼内容 DNA..."):
                try:
                    generator = AIEmailGenerator(provider=provider, api_key=ai_key, model=model)
                    refined = generator.generate(_fmt_dna_for_prompt(dna))
                    st.markdown("#### AI 精炼版")
                    st.markdown(refined)
                except Exception as e:
                    st.error(f"AI 精炼失败：{e}")
    else:
        st.info("侧边栏配置 AI API Key 后可点击「AI 精炼 DNA」获得更地道的结果")


def run_viral_analysis(record: dict):
    """爆款分析：曝光 + 互动 + 内容 DNA"""
    api_key = st.session_state.get("youtube_api_key", "")
    if not api_key:
        st.error("请先配置 YouTube API Key")
        return

    with st.spinner("正在分析爆款视频与内容 DNA..."):
        try:
            analyzer = YouTubeAnalyzer(api_key)
            result = analyzer.analyze_channel(record["channel_url"], max_videos=30, max_comments=30)

            st.subheader(f"🔥 {record['channel_name']} 爆款分析")
            st.caption(f"本次消耗配额：{result['quota_used']} units")

            tab1, tab2, tab3 = st.tabs(["曝光最高", "互动最高", "内容 DNA"])
            with tab1:
                for i, v in enumerate(result["top_exposure"], 1):
                    st.markdown(f"{i}. [{v['title']}]({v['url']})")
                    st.caption(f"播放量 {v['view_count']:,} ｜ 点赞 {v['like_count']:,} ｜ {'Shorts' if v['is_shorts'] else '长视频'}")
            with tab2:
                for i, v in enumerate(result["top_engagement"], 1):
                    st.markdown(f"{i}. [{v['title']}]({v['url']})")
                    st.caption(f"点赞 {v['like_count']:,} ｜ 评论 {v['comment_count']:,} ｜ {'Shorts' if v['is_shorts'] else '长视频'}")
            with tab3:
                run_content_dna(record, result)
        except Exception as e:
            st.error(f"分析失败：{e}")


def run_conversion_analysis(record: dict):
    """转化分析：评论区信号"""
    api_key = st.session_state.get("youtube_api_key", "")
    if not api_key:
        st.error("请先配置 YouTube API Key")
        return

    with st.spinner("正在抓取评论区并检测购买信号..."):
        try:
            analyzer = YouTubeAnalyzer(api_key)
            result = analyzer.analyze_channel(record["channel_url"], max_videos=30, max_comments=100)

            st.subheader(f"💰 {record['channel_name']} 转化分析")
            st.caption(f"本次消耗配额：{result['quota_used']} units")

            if not result["top_conversion"]:
                st.warning("未检测到明显的购买意向评论信号")
                return

            for i, v in enumerate(result["top_conversion"], 1):
                signals = v.get("conversion_signals", {}).get("signals", {})
                signal_text = ", ".join([f"{k}: {c}" for k, c in signals.items() if c > 0])
                st.markdown(f"{i}. [{v['title']}]({v['url']})")
                st.caption(f"转化信号：{signal_text} ｜ {'Shorts' if v['is_shorts'] else '长视频'}")
                with st.expander("查看信号评论"):
                    for c in v.get("conversion_signals", {}).get("signal_comments", [])[:5]:
                        st.markdown(f"- {c}")
        except Exception as e:
            st.error(f"分析失败：{e}")


def run_script_email(record: dict):
    """脚本创作 + 韩文邮件生成"""
    api_key = st.session_state.get("ai_api_key", "")
    provider = st.session_state.get("ai_provider", "dashscope")
    model = st.session_state.get("ai_model", "") or None
    sender = st.session_state.get("sender_name", "아이비")

    if not api_key:
        st.error(f"请先配置 {provider.upper()} API Key")
        return

    with st.spinner("正在生成韩文拍摄框架和邮件..."):
        try:
            # 构造一个简化版 DNA 卡片
            dna_card = {
                "channel_name": record["channel_name"],
                "content_tone": "亲切闺蜜型",
                "fan_nicknames": ["여러분"],
                "top_hook_patterns": {"价格/折扣钩子": 1},
                "top_cta_patterns": {"더보기란/링크 언급": 1},
            }
            generator = AIEmailGenerator(provider=provider, api_key=api_key, model=model)
            res = generator.generate_framework_and_email(
                dna_card=dna_card,
                product_info=SAMPLE_PRODUCT,
                sender_name=sender,
            )

            st.subheader(f"✉️ {record['channel_name']} 脚本 + 邮件")
            tab1, tab2 = st.tabs(["拍摄框架", "邀请邮件"])
            with tab1:
                st.markdown(res["framework"])
            with tab2:
                st.text_area("邮件正文（可复制）", res["email"], height=400)
        except Exception as e:
            st.error(f"生成失败：{e}")


def render_add_influencer():
    st.header("➕ 添加网红到 BD 底库")

    with st.form("add_influencer_form"):
        channel_name = st.text_input("昵称")
        channel_url = st.text_input("YouTube 主页链接")
        category = st.text_input("垂类", value="뷰티 & 헬스")
        recruiter = st.text_input("挖掘人", value=st.session_state.get("sender_name", "아이비"))
        subscribers = st.number_input("粉丝数", min_value=0, value=0, step=1000)
        auto_fetch = st.toggle(
            "自动抓取粉丝数+总播放（需配置 YouTube API Key）",
            value=True,
            help="开启后会自动从 YouTube Data API 抓取该频道的最新粉丝数和总播放量。",
        )
        submitted = st.form_submit_button("添加")

    if submitted:
        if not channel_name or not channel_url:
            st.error("昵称和主页链接必填")
            return

        channel_id = extract_channel_id(channel_url) or channel_url
        subscribers_value = int(subscribers)
        total_views_value = 0

        if auto_fetch:
            api_key = st.session_state.get("youtube_api_key", "")
            if not api_key:
                st.error("请先配置 YouTube Data API Key")
                return

            with st.spinner("正在抓取频道数据..."):
                try:
                    analyzer = YouTubeAnalyzer(api_key)
                    resolved_id = channel_id
                    # 如果输入的是 @handle，先解析成 UC ID
                    if isinstance(resolved_id, str) and resolved_id.startswith("@"):
                        resolved_id = analyzer.get_channel_id_by_handle(resolved_id)
                        if not resolved_id:
                            st.error("无法从主页链接解析出频道 ID")
                            return

                    stats = analyzer.get_channel_stats(resolved_id)
                    subscribers_value = stats.get("subscriber_count", subscribers_value)
                    total_views_value = stats.get("view_count", 0)
                    st.info(f"已抓取：粉丝 {subscribers_value:,} · 总播放 {total_views_value:,}")
                except Exception as e:
                    st.error(f"自动抓取失败：{e}")
                    return

        db = st.session_state.bd_db
        db.add({
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_url": channel_url,
            "category": category,
            "recruiter": recruiter,
            "subscribers": int(subscribers_value),
            "total_views": int(total_views_value),
            "status": "已引入",
        })
        st.success(f"已添加 {channel_name} 到 BD 底库")
        st.rerun()


def render_video_tracker():
    st.header("📹 视频数据追踪")

    db = st.session_state.bd_db
    records = db.get_all()
    if not records:
        st.info("底库为空，先去「添加网红」页添加。")
        return

    names = [r["channel_name"] for r in records]
    selected_name = st.selectbox("关联到网红", names)
    selected = next(r for r in records if r["channel_name"] == selected_name)

    video_url = st.text_input(
        "输入 YouTube 视频链接",
        value=selected.get("video_link", ""),
        placeholder="https://www.youtube.com/watch?v=... 或 /shorts/..."
    )

    c1, c2 = st.columns([1, 4])
    with c1:
        track_clicked = st.button("追踪数据并回写", use_container_width=True)
    with c2:
        st.caption("抓取后会自动把播放/点赞/评论写回该网红的「视频回链」字段。")

    if track_clicked:
        api_key = st.session_state.get("youtube_api_key", "")
        if not api_key:
            st.error("请先配置 YouTube API Key")
            return
        if not video_url:
            st.error("请输入视频链接")
            return

        video_id = extract_video_id(video_url)
        if not video_id:
            st.error("无法识别视频链接")
            return

        with st.spinner("抓取中..."):
            try:
                analyzer = YouTubeAnalyzer(api_key)
                stats = analyzer.get_video_stats(video_id)

                # 回写到数据库
                db.update(selected["channel_id"], {
                    "video_link": stats["url"],
                    "video_views": stats["view_count"],
                    "video_likes": stats["like_count"],
                    "video_comments": stats["comment_count"],
                })

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("播放量", f"{stats['view_count']:,}")
                m2.metric("点赞", f"{stats['like_count']:,}")
                m3.metric("评论", f"{stats['comment_count']:,}")
                m4.metric("类型", "Shorts" if stats["is_shorts"] else "长视频")
                st.markdown(f"**标题**：{stats['title']}")
                st.success("已回写到 BD 底库")
            except Exception as e:
                st.error(f"追踪失败：{e}")


def render_product_import():
    st.header("📥 商品效果数据导入")

    # 单个编辑
    with st.expander("单个编辑商品与视频数据"):
        db = st.session_state.bd_db
        records = db.get_all()
        names = [r["channel_name"] for r in records]
        if not names:
            st.info("底库为空")
        else:
            selected = st.selectbox("选择网红", names, key="single_edit_name")
            rec = next(r for r in records if r["channel_name"] == selected)
            with st.form("single_metric_form"):
                col1, col2 = st.columns(2)
                with col1:
                    video_link = st.text_input("视频回链", value=rec.get("video_link", ""))
                    video_views = st.number_input("播放", min_value=0, value=int(rec.get("video_views") or 0), step=1000)
                    video_likes = st.number_input("点赞", min_value=0, value=int(rec.get("video_likes") or 0), step=100)
                    video_comments = st.number_input("评论", min_value=0, value=int(rec.get("video_comments") or 0), step=100)
                with col2:
                    product_link = st.text_input("商品链接", value=rec.get("product_link", ""))
                    product_views = st.number_input("浏览", min_value=0, value=int(rec.get("product_views") or 0), step=1000)
                    product_clicks = st.number_input("点击", min_value=0, value=int(rec.get("product_clicks") or 0), step=100)
                    product_conversions = st.number_input("转化", min_value=0, value=int(rec.get("product_conversions") or 0), step=10)
                gmv = st.number_input("GMV (KRW)", min_value=0.0, value=float(rec.get("gmv") or 0), step=10000.0)
                if st.form_submit_button("保存"):
                    db.update(rec["channel_id"], {
                        "video_link": video_link,
                        "video_views": video_views,
                        "video_likes": video_likes,
                        "video_comments": video_comments,
                        "product_link": product_link,
                        "product_views": product_views,
                        "product_clicks": product_clicks,
                        "product_conversions": product_conversions,
                        "gmv": gmv,
                    })
                    st.success("已保存")
                    st.rerun()

    # 批量导入
    st.subheader("批量导入")
    uploaded = st.file_uploader("上传 CSV 或 Excel", type=["csv", "xlsx", "xls"])
    if uploaded:
        try:
            df = parse_upload_file(uploaded)
            st.write("预览：")
            st.dataframe(df.head(), use_container_width=True)

            if st.button("确认导入"):
                result = validate_and_transform(df)
                st.session_state.bd_db.bulk_update_metrics(result["valid"])
                st.success(f"成功导入 {result['success_count']} 条，失败 {result['error_count']} 条")
                if result["invalid"]:
                    with st.expander("查看失败记录"):
                        st.json(result["invalid"])
                st.rerun()
        except Exception as e:
            st.error(f"解析文件失败：{e}")

    # 下载模板
    template = generate_template_df()
    csv = template.to_csv(index=False).encode("utf-8-sig")
    st.download_button("下载导入模板", data=csv, file_name="bd_product_template.csv", mime="text/csv")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="YTS 网红管理库",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.title("🎯 YTS 网红管理库")
    st.caption("配置项默认收起，点击左上角 ☰ 可展开填写 API Key 等设置")

    # Flat Design: 大胆扁平、色块结构、无阴影、Outfit 字体
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&display=swap');

            .stApp {
                font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
                background: #FFFFFF;
                color: #111827;
            }
            .stApp * {
                box-shadow: none !important;
            }

            /* Typography */
            h1, h2, h3, h4, h5, h6, p, label, span, div, input, button, select, textarea {
                font-family: 'Outfit', sans-serif;
            }
            h1 {
                font-weight: 800;
                letter-spacing: -0.02em;
                font-size: 2.25rem;
                color: #111827;
            }
            h2, h3 {
                font-weight: 700;
                letter-spacing: -0.02em;
                color: #111827;
            }

            /* Container width */
            .block-container {
                max-width: 1400px;
                padding-left: 2rem;
                padding-right: 2rem;
            }

            /* Buttons */
            [data-testid="stButton"] button {
                font-family: 'Outfit', sans-serif;
                font-weight: 600;
                border-radius: 6px;
                border: none;
                background: #D97A8A;
                color: #FFFFFF;
                min-height: 2.25rem;
                padding: 0 1rem;
                transition: all 0.2s ease;
            }
            [data-testid="stButton"] button:hover {
                background: #C35A6E;
                transform: scale(1.05);
            }
            [data-testid="stButton"] button[kind="primary"] {
                background: #D97A8A;
                color: #FFFFFF;
            }
            [data-testid="stButton"] button[kind="secondary"] {
                background: #F9EEF1;
                color: #111827;
            }
            [data-testid="stButton"] button[kind="secondary"]:hover {
                background: #EAD0D6;
            }

            /* Inputs */
            [data-testid="stTextInput"] input,
            [data-testid="stNumberInput"] input,
            [data-testid="stTextArea"] textarea {
                font-family: 'Outfit', sans-serif;
                background: #F9EEF1;
                border: 2px solid transparent;
                border-radius: 6px;
                color: #111827;
                transition: all 0.2s ease;
            }
            [data-testid="stTextInput"] input:focus,
            [data-testid="stNumberInput"] input:focus,
            [data-testid="stTextArea"] textarea:focus {
                background: #FFFFFF;
                border: 2px solid #D97A8A;
            }

            /* Selectbox / Multiselect */
            [data-testid="stSelectbox"] > div[data-baseweb="select"] > div,
            [data-testid="stMultiselect"] > div[data-baseweb="select"] > div {
                background: #F9EEF1;
                border: 2px solid transparent;
                border-radius: 6px;
            }
            [data-testid="stSelectbox"] > div[data-baseweb="select"] > div:focus-within,
            [data-testid="stMultiselect"] > div[data-baseweb="select"] > div:focus-within {
                background: #FFFFFF;
                border: 2px solid #D97A8A;
            }

            /* Checkbox */
            [data-testid="stCheckbox"] label {
                font-family: 'Outfit', sans-serif;
                font-weight: 500;
            }
            [data-testid="stCheckbox"] input[type="checkbox"] {
                width: 18px;
                height: 18px;
                accent-color: #D97A8A;
                cursor: pointer;
            }

            /* Tabs */
            [data-testid="stTabs"] [role="tablist"] {
                display: flex;
                justify-content: space-between;
                background: #F9EEF1;
                border-radius: 8px;
                padding: 4px;
                gap: 4px;
                border-bottom: none;
            }
            [data-testid="stTabs"] [role="tablist"] button {
                flex: 1;
                text-align: center;
                font-family: 'Outfit', sans-serif;
                font-weight: 600;
                font-size: 14px;
                border-radius: 6px;
                color: #8E6B72;
                background: transparent;
                border: none;
                transition: all 0.2s ease;
            }
            [data-testid="stTabs"] [role="tablist"] button:hover {
                color: #111827;
                background: #EAD0D6;
            }
            [data-testid="stTabs"] [role="tablist"] button[aria-selected="true"] {
                background: #D97A8A;
                color: #FFFFFF;
            }

            /* Metrics / Cards */
            [data-testid="stMetric"] {
                background: #F9EEF1;
                border-radius: 8px;
                padding: 1rem;
            }
            [data-testid="stMetricLabel"] {
                font-family: 'Outfit', sans-serif;
                font-weight: 600;
                color: #8E6B72;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-size: 12px;
            }
            [data-testid="stMetricValue"] {
                font-family: 'Outfit', sans-serif;
                font-weight: 700;
                color: #111827;
            }

            /* Divider */
            hr {
                border: none;
                border-top: 2px solid #EAD0D6;
                margin: 1.5rem 0;
            }

            /* Table */
            .bd-table-wrapper {
                overflow-x: auto;
                width: 100%;
                border-radius: 8px;
                padding-bottom: 4px;
            }
            .bd-table-wrapper::-webkit-scrollbar {
                height: 8px;
            }
            .bd-table-wrapper::-webkit-scrollbar-track {
                background: #F9EEF1;
                border-radius: 4px;
            }
            .bd-table-wrapper::-webkit-scrollbar-thumb {
                background: #E8B4C0;
                border-radius: 4px;
            }
            .bd-table-wrapper::-webkit-scrollbar-thumb:hover {
                background: #B8989E;
            }
            .bd-table {
                table-layout: fixed;
                width: 1600px;
                border-collapse: collapse;
                font-family: 'Outfit', sans-serif;
            }
            .bd-table thead {
                display: table-header-group;
            }
            .bd-table th {
                font-size: 11px;
                font-weight: 800;
                color: #7A4A55;
                text-transform: uppercase;
                letter-spacing: 0.07em;
                padding: 10px 8px;
                line-height: 1.3;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                border-bottom: 3px solid #D97A8A;
                background: #FFFFFF;
                text-align: left;
                vertical-align: middle;
            }
            .bd-table th input[type="checkbox"] {
                width: 18px;
                height: 18px;
                accent-color: #D97A8A;
                cursor: pointer;
                margin: 0;
            }
            .bd-table td {
                padding: 0;
                border-bottom: 2px solid #F9EEF1;
                vertical-align: middle;
            }
            .bd-table td p {
                font-family: 'Outfit', sans-serif;
                font-size: 13px;
                font-weight: 500;
                color: #111827;
                margin: 0;
                padding: 10px 8px;
                line-height: 1.4;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .bd-table td p.bd-num {
                font-variant-numeric: tabular-nums;
                text-align: right;
                font-weight: 600;
            }
            .bd-table td p.bd-center {
                text-align: center;
            }
            .bd-table td p.bd-empty {
                color: #B8989E;
                font-weight: 400;
            }
            .bd-table td p.bd-status {
                color: #D97A8A;
                font-weight: 700;
            }
            .bd-table td a {
                color: #D97A8A;
                text-decoration: none;
                font-weight: 600;
            }
            .bd-table td a:hover {
                text-decoration: underline;
            }
            .bd-table tbody tr {
                cursor: pointer;
                transition: background 0.15s ease;
            }
            .bd-table tbody tr:hover {
                background: #FDF6F8;
            }
            .bd-table tbody tr td:first-child {
                text-align: center;
            }
            .bd-table tbody tr td:first-child input[type="checkbox"] {
                width: 18px;
                height: 18px;
                accent-color: #D97A8A;
                cursor: pointer;
                margin: 0;
            }

            /* Caption */
            .stCaption {
                font-family: 'Outfit', sans-serif;
                color: #8E6B72;
            }

            /* Alert boxes */
            .stAlert {
                border-radius: 8px;
                border: 2px solid #EAD0D6;
            }

            /* Horizontal scroll for table */
            .block-container {
                max-width: 1400px;
                padding-left: 1.5rem;
                padding-right: 1.5rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    render_sidebar()
    init_db()
    if SEED_SAMPLE_DATA:
        seed_sample_data()

    tab_base, tab_add, tab_track, tab_import = st.tabs([
        "📁 YTS 底库",
        "➕ 添加网红",
        "📹 视频追踪",
        "📥 商品导入",
    ])

    with tab_base:
        render_bd_table()
    with tab_add:
        render_add_influencer()
    with tab_track:
        render_video_tracker()
    with tab_import:
        render_product_import()


if __name__ == "__main__":
    main()
