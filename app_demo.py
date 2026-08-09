#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BD 网红底库 - 独立 Streamlit Demo

大表单目标：
- 与 kol-finder 挖掘库联动，状态为「已引入」的网红自动进入 BD 底库
- 一页展示所有关键字段：
  昵称 / 状态 / 粉丝 / 垂类 / 主页链接 / 分析 / 邮件 / 视频回链 / 播放 / 点赞 / 评论 / 商品链接 / 浏览 / 点击 / 转化 / GMV
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
            for r in selected:
                st.session_state.pop(f"sel_{r['channel_id']}", None)
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
                "播放量 从高到低",
                "点赞数 从高到低",
                "评论数 从高到低",
            ],
            index=[
                "默认",
                "GMV 从高到低",
                "GMV 从低到高",
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


def render_bd_table():
    st.header("YTS 网红管理库")

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
    elif sort_by == "播放量 从高到低":
        records = sorted(records, key=lambda x: int(x.get("video_views") or 0), reverse=True)
    elif sort_by == "点赞数 从高到低":
        records = sorted(records, key=lambda x: int(x.get("video_likes") or 0), reverse=True)
    elif sort_by == "评论数 从高到低":
        records = sorted(records, key=lambda x: int(x.get("video_comments") or 0), reverse=True)

    st.caption(f"共 {len(records)} 条")

    # 批量操作栏
    def _get_selected_records():
        return [r for r in records if st.session_state.get(f"sel_{r['channel_id']}", False)]

    bulk_cols = st.columns([0.12, 0.88])
    with bulk_cols[0]:
        if st.button("删除选中", key="bulk_delete_btn", type="primary"):
            selected = _get_selected_records()
            bulk_delete_dialog(selected)
    with bulk_cols[1]:
        selected_count = len(_get_selected_records())
        if selected_count:
            st.caption(f"已选中 {selected_count} 位网红")

    # 表头：17 + 1 列 Apple 风表格（增加选择列）
    COL_WIDTHS = [0.6, 1.35, 0.65, 0.65, 1.15, 0.7, 0.75, 0.75, 0.8, 0.6, 0.6, 0.6, 0.8, 0.6, 0.6, 0.6, 0.75, 0.45]
    headers = [
        "", "昵称", "状态", "粉丝", "垂类", "主页", "分析", "邮件",
        "视频回链", "播放", "点赞", "评论", "商品链接", "浏览", "点击", "转化", "GMV", "",
    ]
    cols = st.columns(COL_WIDTHS)
    for col, header in zip(cols, headers):
        with col:
            st.markdown(f"<p class='bd-th'>{header}</p>", unsafe_allow_html=True)
    st.markdown("<div class='bd-head-line'></div>", unsafe_allow_html=True)

    # 数据行：一个网红一行
    for i, r in enumerate(records):
        cols = st.columns(COL_WIDTHS)

        with cols[0]:
            st.checkbox(
                "",
                key=f"sel_{r['channel_id']}",
                label_visibility="collapsed",
            )

        with cols[1]:
            st.markdown(f"<p class='bd-td'>{r.get('channel_name', '-')}</p>", unsafe_allow_html=True)

        with cols[2]:
            status = r.get("status", "-")
            if status == "已引入":
                st.markdown("<p class='bd-td bd-status'>已引入</p>", unsafe_allow_html=True)
            else:
                st.markdown(f"<p class='bd-td bd-empty'>{status}</p>", unsafe_allow_html=True)

        with cols[3]:
            st.markdown(f"<p class='bd-td'>{fmt_num(r.get('subscribers'))}</p>", unsafe_allow_html=True)

        with cols[4]:
            cat = r.get("category", "-")
            st.markdown(f"<p class='bd-td' title='{cat}'>{cat}</p>", unsafe_allow_html=True)

        with cols[5]:
            url = r.get("channel_url", "")
            if url:
                st.markdown(f"<p class='bd-td'><a href='{url}' target='_blank'>主页</a></p>", unsafe_allow_html=True)
            else:
                st.markdown("<p class='bd-td bd-empty'>-</p>", unsafe_allow_html=True)

        with cols[6]:
            if st.button("分析", key=f"viral_{r['channel_id']}", help="爆款分析"):
                viral_dialog(r)

        with cols[7]:
            if st.button("邮件", key=f"script_{r['channel_id']}", help="脚本/邮件"):
                script_email_dialog(r)

        with cols[8]:
            vlink = r.get("video_link", "")
            if vlink:
                if st.button("视频", key=f"video_{r['channel_id']}", help="查看视频详情"):
                    video_detail_dialog(r)
            else:
                if st.button("添加", key=f"add_video_{r['channel_id']}", help="添加视频回链"):
                    add_video_dialog(r)

        with cols[9]:
            st.markdown(f"<p class='bd-td'>{fmt_num(r.get('video_views'))}</p>", unsafe_allow_html=True)

        with cols[10]:
            st.markdown(f"<p class='bd-td'>{fmt_num(r.get('video_likes'))}</p>", unsafe_allow_html=True)

        with cols[11]:
            st.markdown(f"<p class='bd-td'>{fmt_num(r.get('video_comments'))}</p>", unsafe_allow_html=True)

        with cols[12]:
            plink = r.get("product_link", "")
            if plink:
                if st.button("商品", key=f"product_{r['channel_id']}", help="查看转化详情"):
                    conversion_detail_dialog(r)
            else:
                st.markdown("<p class='bd-td bd-empty'>-</p>", unsafe_allow_html=True)

        with cols[13]:
            st.markdown(f"<p class='bd-td'>{fmt_num(r.get('product_views'))}</p>", unsafe_allow_html=True)

        with cols[14]:
            st.markdown(f"<p class='bd-td'>{fmt_num(r.get('product_clicks'))}</p>", unsafe_allow_html=True)

        with cols[15]:
            st.markdown(f"<p class='bd-td'>{fmt_num(r.get('product_conversions'))}</p>", unsafe_allow_html=True)

        with cols[16]:
            st.markdown(f"<p class='bd-td'>{fmt_money(r.get('gmv'))}</p>", unsafe_allow_html=True)

        with cols[17]:
            if st.button("编辑", key=f"edit_{r['channel_id']}", help="编辑数据"):
                edit_metrics_dialog(r)

        st.markdown("<div class='bd-row-line'></div>", unsafe_allow_html=True)


def _sync_discovery_demo(db):
    """演示：模拟从 kol-finder 挖掘库同步「已引入」网红"""
    demo_discovery = [
        {
            "channel_id": "UC_demo_sync_1",
            "channel_name": "同步示例网红",
            "channel_url": "https://www.youtube.com/@sync_example",
            "category": "뷰티",
            "subscribers": 30000,
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
        submitted = st.form_submit_button("添加")

    if submitted:
        if not channel_name or not channel_url:
            st.error("昵称和主页链接必填")
            return

        channel_id = extract_channel_id(channel_url) or channel_url
        db = st.session_state.bd_db
        db.add({
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_url": channel_url,
            "category": category,
            "recruiter": recruiter,
            "subscribers": int(subscribers),
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

    # Apple 官网极简高级风：真实表格感、垂直居中、中等字重
    st.markdown(
        """
        <style>
            .stApp {
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
            }
            [data-testid="stTabs"] [role="tablist"] {
                display: flex;
                justify-content: space-between;
            }
            [data-testid="stTabs"] [role="tablist"] button {
                flex: 1;
                text-align: center;
            }
            .bd-th p {
                font-size: 13px;
                font-weight: 600;
                color: #86868b;
                margin: 0;
                letter-spacing: -0.01em;
            }
            .bd-td p {
                font-size: 13px;
                font-weight: 500;
                color: #1d1d1f;
                margin: 0;
                line-height: 1.4;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .bd-td a {
                color: #0071e3;
                text-decoration: none;
                font-weight: 500;
            }
            .bd-empty p {
                color: #86868b;
                font-weight: 400;
            }
            .bd-status p {
                color: #34c759;
                font-weight: 600;
            }
            [data-testid="stHorizontalBlock"] {
                align-items: center !important;
                margin-bottom: 0 !important;
                padding: 0.05rem 0 !important;
                min-height: auto !important;
            }
            [data-testid="stHorizontalBlock"] [data-testid="stButton"] button {
                white-space: nowrap;
                padding: 0.05rem 0.35rem;
                min-width: auto;
                min-height: 1.1rem;
                font-size: 11px;
                font-weight: 500;
                line-height: 1.1;
                color: #1d1d1f;
                background-color: #ffffff;
                border: 1px solid #d2d2d7;
                border-radius: 9999px;
                box-shadow: none;
            }
            [data-testid="stHorizontalBlock"] [data-testid="stCheckbox"] {
                margin: 0 !important;
                padding: 0 !important;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            [data-testid="stHorizontalBlock"] [data-testid="stCheckbox"] > div {
                margin: 0 !important;
                padding: 0 !important;
                min-height: auto !important;
                width: auto !important;
            }
            [data-testid="stHorizontalBlock"] [data-testid="stCheckbox"] label {
                font-size: 0 !important;
                padding: 0 !important;
                margin: 0 !important;
                min-height: auto !important;
            }
            [data-testid="stHorizontalBlock"] [data-testid="stCheckbox"] label p {
                display: none !important;
            }
            [data-testid="stHorizontalBlock"] [data-testid="stButton"] button:hover {
                background-color: #f5f5f7;
                border-color: #86868b;
            }
            .bd-row-line {
                border-bottom: 1px solid #f0f0f0;
                margin: 0;
                height: 0;
            }
            .bd-head-line {
                border-bottom: 1px solid #d2d2d7;
                margin: 0;
                height: 0;
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
