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
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from bd_database import get_bd_db
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
        "ctr": 0.0267,
        "orders": 180,
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
        "ctr": 0.0297,
        "orders": 140,
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
        "ctr": 0,
        "orders": 0,
        "gmv": 0,
    },
]


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

def _secret(key: str) -> str:
    """优先读 Streamlit Secrets，其次环境变量"""
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, "")


def get_yida_config() -> dict:
    """组装宜搭连接配置（AK/SK 来自 Secrets/环境变量，其余写死）"""
    return {
        "access_key_id": _secret("YIDA_ACCESS_KEY_ID"),
        "access_key_secret": _secret("YIDA_ACCESS_KEY_SECRET"),
        "app_type": "APP_N85O3OPKB9OO52S4KCTD",
        "system_token": "XE7668C13088ICWHNJPXODYLFX8Y2Y3Z02NSMBT",
        "form_uuid": "FORM-2A64DBB4851A4301BAA4C0A5C39E752DHXL0",
        "account_id": "550448",
    }


def init_db():
    """初始化数据库连接（仅宜搭）"""
    if "bd_db" not in st.session_state:
        st.session_state.bd_db = get_bd_db(
            use_yida=True,
            yida_config=get_yida_config(),
        )


# ---------------------------------------------------------------------------
# UI 组件
# ---------------------------------------------------------------------------

def _key_hint(value: str) -> None:
    """在输入框下方实时提示是否已填写"""
    if value:
        st.caption("✅ 已填写")
    else:
        st.caption("⬜ 未填写")


def _test_connection() -> None:
    """验证宜搭连通性，结果存入 session_state 供侧边栏展示"""
    try:
        records = st.session_state.bd_db.get_all()
        st.session_state.conn_ok = True
        st.session_state.conn_msg = f"宜搭连接成功，当前共 {len(records)} 条记录"
    except Exception as e:
        st.session_state.conn_ok = False
        st.session_state.conn_msg = f"连接失败：{e}"


def render_sidebar():
    with st.sidebar:
        st.title("⚙️ 配置")
        st.caption("数据源：钉钉宜搭（团队共享一份数据）")

        st.divider()
        st.session_state.youtube_api_key = st.text_input(
            "YouTube Data API Key",
            value=_secret("YOUTUBE_API_KEY"),
            type="password",
        )
        _key_hint(st.session_state.youtube_api_key)

        st.divider()
        st.subheader("AI 邮件生成")
        st.session_state.ai_api_key = st.text_input(
            "AI API Key",
            value=_secret("DASHSCOPE_API_KEY") or _secret("AI_API_KEY"),
            type="password",
        )
        _key_hint(st.session_state.ai_api_key)
        with st.expander("高级选项"):
            st.session_state.sender_name = st.text_input("发件人姓名", value="아이비")

        st.divider()
        if st.button("💾 保存并测试连接", use_container_width=True):
            _test_connection()
            st.rerun()

        if "conn_msg" in st.session_state:
            if st.session_state.get("conn_ok"):
                st.success(st.session_state.conn_msg)
            else:
                st.error(st.session_state.conn_msg)


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


def fmt_percent(v):
    """把小数比例格式化成百分比（如 0.035 -> 3.5%）"""
    if v is None or v == "":
        return "-"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{n * 100:.2f}%"


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


@st.dialog("视频回链")
def video_edit_dialog(record: dict):
    """弹窗内直接增加/修改/删除视频回链及数据"""
    cid = record["channel_id"]
    db = st.session_state.bd_db
    rec = db.get_by_channel_id(cid) or record

    vlink = st.text_input(
        "视频回链",
        value=rec.get("video_link", ""),
        placeholder="https://www.youtube.com/watch?v=... 或 /shorts/...",
    )
    if st.button("⚡ 一键导入视频数据", use_container_width=True):
        _import_video_stats(cid, vlink)

    c1, c2, c3 = st.columns(3)
    with c1:
        views = st.number_input("播放", min_value=0, value=int(rec.get("video_views") or 0), step=1000)
    with c2:
        likes = st.number_input("点赞", min_value=0, value=int(rec.get("video_likes") or 0), step=100)
    with c3:
        comments = st.number_input("评论", min_value=0, value=int(rec.get("video_comments") or 0), step=100)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 保存", use_container_width=True):
            db.update(cid, {
                "video_link": vlink,
                "video_views": views,
                "video_likes": likes,
                "video_comments": comments,
            })
            st.success("已保存")
            st.rerun()
    with c2:
        if st.button("🗑 删除视频回链", use_container_width=True):
            db.update(cid, {"video_link": "", "video_views": 0, "video_likes": 0, "video_comments": 0})
            st.rerun()


def _import_video_stats(cid: str, vlink: str):
    """根据视频链接一键抓取播放/点赞/评论并回写"""
    api_key = st.session_state.get("youtube_api_key", "")
    if not api_key:
        st.error("请先在侧边栏填写 YouTube API Key")
        return
    if not vlink:
        st.error("请先填写视频回链")
        return
    vid = extract_video_id(vlink)
    if not vid:
        st.error("无法识别视频链接")
        return
    with st.spinner("抓取中..."):
        try:
            stats = YouTubeAnalyzer(api_key).get_video_stats(vid)
            st.session_state.bd_db.update(cid, {
                "video_link": stats["url"],
                "video_views": stats["view_count"],
                "video_likes": stats["like_count"],
                "video_comments": stats["comment_count"],
            })
            st.success("视频数据已导入")
            st.rerun()
        except Exception as e:
            st.error(f"导入失败：{e}")


@st.dialog("商品链接")
def product_edit_dialog(record: dict):
    """弹窗内直接增加/修改/删除商品链接及效果数据"""
    cid = record["channel_id"]
    db = st.session_state.bd_db
    rec = db.get_by_channel_id(cid) or record

    plink = st.text_input(
        "商品链接",
        value=rec.get("product_link", ""),
        placeholder="https://ko.aliexpress.com/item/...",
    )
    c1, c2 = st.columns(2)
    with c1:
        pviews = st.number_input("浏览", min_value=0, value=int(rec.get("product_views") or 0), step=1000)
        ctr = st.number_input("点击率（小数）", min_value=0.0, value=float(rec.get("ctr") or 0.0), step=0.0001, format="%.4f")
    with c2:
        orders = st.number_input("成交量", min_value=0, value=int(rec.get("orders") or 0), step=10)
        gmv = st.number_input("GMV (KRW)", min_value=0.0, value=float(rec.get("gmv") or 0), step=10000.0)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 保存", use_container_width=True):
            db.update(cid, {
                "product_link": plink,
                "product_views": pviews,
                "ctr": ctr,
                "orders": orders,
                "gmv": gmv,
            })
            st.success("已保存")
            st.rerun()
    with c2:
        if st.button("🗑 删除商品链接", use_container_width=True):
            db.update(cid, {"product_link": "", "product_views": 0, "ctr": 0, "orders": 0, "gmv": 0})
            st.rerun()


@st.dialog("爆款分析")
def viral_dialog(record: dict):
    """弹窗展示爆款分析结果"""
    run_viral_analysis(record)


@st.dialog("脚本 + 邮件")
def script_email_dialog(record: dict):
    """弹窗展示拍摄框架与邀请邮件"""
    run_script_email(record)


def render_bd_table():
    st.header("BD 网红底库")

    db = st.session_state.bd_db
    try:
        records = db.get_all()
    except Exception as e:
        st.error(f"无法连接宜搭：{e}\n\n请在左侧填写密钥后点「保存并测试连接」。")
        return

    if not records:
        st.info("底库为空，先去「添加网红」页添加，或点击上方「同步挖掘库」。")
        return

    # 顶部操作：同步挖掘库 + 一键导入
    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        if st.button("同步 kol-finder 挖掘库", use_container_width=True):
            _sync_discovery_demo(db)
    with c2:
        if st.button("📥 一键导入", use_container_width=True):
            st.session_state.show_import = not st.session_state.get("show_import", False)
            st.rerun()
    with c3:
        st.caption("同步只拉「已引入」网红；一键导入用于批量更新商品/视频数据。")

    if st.session_state.get("show_import"):
        render_bulk_import()

    st.divider()

    # 搜索筛选
    search = st.text_input(
        "搜索昵称 / 垂类 / 挖掘人",
        placeholder="输入关键词筛选...",
        key="bd_search",
    )
    if search:
        query = search.lower()
        records = [
            r for r in records
            if any(query in str(r.get(k, "")).lower() for k in ("channel_name", "category", "recruiter"))
        ]

    st.caption(f"共 {len(records)} 条")

    # 表头：16 列扁平布局
    cols = st.columns([1.4, 0.65, 0.65, 1.2, 0.7, 0.75, 0.75, 0.8, 0.6, 0.6, 0.6, 0.8, 0.6, 0.6, 0.6, 0.8])
    headers = [
        "昵称", "状态", "粉丝", "垂类", "主页", "分析", "邮件",
        "视频回链", "播放", "点赞", "评论", "商品链接", "浏览", "点击率", "成交量", "GMV",
    ]
    for col, header in zip(cols, headers):
        with col:
            st.markdown(f"<p style='font-size:11px; color:#6e6e73; margin:0'>{header}</p>", unsafe_allow_html=True)

    # 数据行：一个网红一行
    for i, r in enumerate(records):
        cols = st.columns([1.4, 0.65, 0.65, 1.2, 0.7, 0.75, 0.75, 0.8, 0.6, 0.6, 0.6, 0.8, 0.6, 0.6, 0.6, 0.8])

        with cols[0]:
            st.markdown(f"<p style='font-size:12px; margin:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis'>{r.get('channel_name', '-')}</p>", unsafe_allow_html=True)

        with cols[1]:
            status = r.get("status", "-")
            if status == "已引入":
                st.markdown("<p style='font-size:11px; color:#34c759; margin:0'>已引入</p>", unsafe_allow_html=True)
            else:
                st.markdown(f"<p style='font-size:11px; color:#6e6e73; margin:0'>{status}</p>", unsafe_allow_html=True)

        with cols[2]:
            st.markdown(f"<p style='font-size:12px; margin:0'>{fmt_num(r.get('subscribers'))}</p>", unsafe_allow_html=True)

        with cols[3]:
            cat = r.get("category", "-")
            st.markdown(f"<p style='font-size:11px; margin:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis' title='{cat}'>{cat}</p>", unsafe_allow_html=True)

        with cols[4]:
            url = r.get("channel_url", "")
            if url:
                st.markdown(f"<p style='font-size:11px; margin:0'><a href='{url}' target='_blank'>主页</a></p>", unsafe_allow_html=True)
            else:
                st.markdown("<p style='font-size:11px; color:#6e6e73; margin:0'>-</p>", unsafe_allow_html=True)

        with cols[5]:
            if st.button("分析", key=f"viral_{r['channel_id']}", help="爆款分析"):
                viral_dialog(r)

        with cols[6]:
            if st.button("邮件", key=f"script_{r['channel_id']}", help="脚本/邮件"):
                script_email_dialog(r)

        with cols[7]:
            if st.button("视频", key=f"video_{r['channel_id']}", help="视频回链：增加/修改/删除"):
                video_edit_dialog(r)

        with cols[8]:
            st.markdown(f"<p style='font-size:12px; margin:0'>{fmt_num(r.get('video_views'))}</p>", unsafe_allow_html=True)

        with cols[9]:
            st.markdown(f"<p style='font-size:12px; margin:0'>{fmt_num(r.get('video_likes'))}</p>", unsafe_allow_html=True)

        with cols[10]:
            st.markdown(f"<p style='font-size:12px; margin:0'>{fmt_num(r.get('video_comments'))}</p>", unsafe_allow_html=True)

        with cols[11]:
            if st.button("商品", key=f"product_{r['channel_id']}", help="商品链接：增加/修改/删除"):
                product_edit_dialog(r)

        with cols[12]:
            st.markdown(f"<p style='font-size:12px; margin:0'>{fmt_num(r.get('product_views'))}</p>", unsafe_allow_html=True)

        with cols[13]:
            st.markdown(f"<p style='font-size:12px; margin:0'>{fmt_percent(r.get('ctr'))}</p>", unsafe_allow_html=True)

        with cols[14]:
            st.markdown(f"<p style='font-size:12px; margin:0'>{fmt_num(r.get('orders'))}</p>", unsafe_allow_html=True)

        with cols[15]:
            st.markdown(f"<p style='font-size:12px; margin:0'>{fmt_money(r.get('gmv'))}</p>", unsafe_allow_html=True)

        if i < len(records) - 1:
            st.divider()


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


def run_viral_analysis(record: dict):
    """爆款分析：曝光 + 互动维度"""
    api_key = st.session_state.get("youtube_api_key", "")
    if not api_key:
        st.error("请先配置 YouTube API Key")
        return

    with st.spinner("正在分析爆款视频..."):
        try:
            analyzer = YouTubeAnalyzer(api_key)
            result = analyzer.analyze_channel(record["channel_url"], max_videos=30, max_comments=0)

            st.subheader(f"🔥 {record['channel_name']} 爆款分析")
            st.caption(f"本次消耗配额：{result['quota_used']} units")

            tab1, tab2 = st.tabs(["曝光最高", "互动最高"])
            with tab1:
                for i, v in enumerate(result["top_exposure"], 1):
                    st.markdown(f"{i}. [{v['title']}]({v['url']})")
                    st.caption(f"播放量 {v['view_count']:,} ｜ 点赞 {v['like_count']:,} ｜ {'Shorts' if v['is_shorts'] else '长视频'}")
            with tab2:
                for i, v in enumerate(result["top_engagement"], 1):
                    st.markdown(f"{i}. [{v['title']}]({v['url']})")
                    st.caption(f"点赞 {v['like_count']:,} ｜ 评论 {v['comment_count']:,} ｜ {'Shorts' if v['is_shorts'] else '长视频'}")
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
    provider = "dashscope"
    model = None
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


def _fetch_subscribers(channel_url: str):
    """根据主页链接抓取频道粉丝数，回填到添加表单"""
    api_key = st.session_state.get("youtube_api_key", "")
    if not api_key:
        st.error("请先在左侧填写 YouTube Data API Key")
        return
    if not channel_url:
        st.error("请先填写 YouTube 主页链接")
        return
    with st.spinner("正在抓取粉丝数..."):
        try:
            analyzer = YouTubeAnalyzer(api_key)
            cid = extract_channel_id(channel_url)
            if not cid:
                st.error("无法识别主页链接，请检查格式（如 https://www.youtube.com/@xxx）")
                return
            if not cid.startswith("UC"):
                cid = analyzer.get_channel_id_by_handle(cid)
            if not cid:
                st.error("找不到该频道，请检查主页链接")
                return
            stats = analyzer.get_channel_stats(cid)
            st.session_state["pending_fetch"] = {
                "subs": stats["subscriber_count"],
                "name": stats["title"],
                "msg": f"抓取成功：{stats['title']} · 粉丝 {stats['subscriber_count']:,}",
            }
            st.rerun()
        except Exception as e:
            st.error(f"抓取失败：{e}")


def _parse_bulk_add(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """解析批量导入网红的表格，返回 (有效记录, 失败行)"""
    col_map = {
        "昵称": "channel_name", "channel_name": "channel_name",
        "YouTube主页链接": "channel_url", "YouTube 主页链接": "channel_url",
        "主页链接": "channel_url", "channel_url": "channel_url",
        "垂类": "category", "category": "category",
        "挖掘人": "recruiter", "recruiter": "recruiter",
        "粉丝数": "subscribers", "粉丝": "subscribers", "subscribers": "subscribers",
    }
    df = df.rename(columns=col_map)
    valid, invalid = [], []
    for i, row in df.iterrows():
        name = str(row.get("channel_name", "") or "").strip()
        url = str(row.get("channel_url", "") or "").strip()
        if not name or not url or name == "nan" or url == "nan":
            invalid.append({"行号": i + 2, "原因": "昵称或主页链接为空", "内容": str(row.to_dict())})
            continue
        try:
            subs = int(float(row.get("subscribers", 0) or 0))
        except (TypeError, ValueError):
            subs = 0
        valid.append({
            "channel_id": extract_channel_id(url) or url,
            "channel_name": name,
            "channel_url": url,
            "category": str(row.get("category", "") or "").strip(),
            "recruiter": str(row.get("recruiter", "") or "").strip(),
            "subscribers": subs,
            "status": "已引入",
        })
    return valid, invalid


def render_add_influencer():
    st.header("➕ 添加网红到 BD 底库")

    # 必须在控件实例化之前修改带 key 的 session_state
    pf = st.session_state.pop("pending_fetch", None)
    if pf:
        st.session_state["add_subscribers"] = pf["subs"]
        if not st.session_state.get("add_name"):
            st.session_state["add_name"] = pf["name"]
        st.success(pf["msg"])
    if st.session_state.pop("pending_clear", False):
        st.session_state["add_name"] = ""
        st.session_state["add_url"] = ""
        st.session_state["add_subscribers"] = 0

    if st.session_state.get("add_success_msg"):
        st.success(st.session_state.pop("add_success_msg"))

    channel_name = st.text_input("昵称", key="add_name")
    channel_url = st.text_input(
        "YouTube 主页链接", key="add_url",
        placeholder="https://www.youtube.com/@xxx",
    )

    c1, c2 = st.columns([1, 3])
    with c1:
        fetch_clicked = st.button("⚡ 自动抓取粉丝数", use_container_width=True)
    with c2:
        st.caption("填好主页链接后点一下，自动填粉丝数和昵称（需左侧填 YouTube API Key）。")

    if fetch_clicked:
        _fetch_subscribers(channel_url)

    c1, c2, c3 = st.columns(3)
    with c1:
        category = st.text_input("垂类", value="뷰티 & 헬스", key="add_cat")
    with c2:
        recruiter = st.text_input("挖掘人", value=st.session_state.get("sender_name", "아이비"), key="add_rec")
    with c3:
        subscribers = st.number_input(
            "粉丝数", min_value=0,
            value=int(st.session_state.get("add_subscribers", 0) or 0),
        )

    if st.button("➕ 添加", key="add_submit"):
        if not channel_name or not channel_url:
            st.error("昵称和主页链接必填")
        else:
            channel_id = extract_channel_id(channel_url) or channel_url
            st.session_state.bd_db.add({
                "channel_id": channel_id,
                "channel_name": channel_name,
                "channel_url": channel_url,
                "category": category,
                "recruiter": recruiter,
                "subscribers": int(subscribers),
                "status": "已引入",
            })
            st.session_state["add_success_msg"] = f"✅ {channel_name} 已成功加入 BD 底库，切到「BD 底库」即可查看。"
            st.session_state["pending_clear"] = True
            st.rerun()

    st.divider()

    # 批量导入网红
    st.subheader("📥 批量导入网红（上传表格）")
    template = pd.DataFrame([{
        "昵称": "꿈아",
        "YouTube主页链接": "https://www.youtube.com/@kkom_aah",
        "垂类": "여성의류",
        "挖掘人": "王修源",
        "粉丝数": 12000,
    }])
    tpl_csv = template.to_csv(index=False).encode("utf-8-sig")
    st.download_button("下载导入模板", data=tpl_csv, file_name="bd_influencer_template.csv", mime="text/csv")

    uploaded = st.file_uploader("上传 CSV 或 Excel", type=["csv", "xlsx", "xls"], key="bulk_add_upload")
    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                df = pd.read_csv(uploaded)
            else:
                df = pd.read_excel(uploaded)
            st.write("预览：")
            st.dataframe(df.head(10), use_container_width=True)
            if st.button("确认导入", key="bulk_add_confirm"):
                valid, invalid = _parse_bulk_add(df)
                ok = 0
                for rec in valid:
                    st.session_state.bd_db.add(rec)
                    ok += 1
                st.success(f"成功导入 {ok} 个网红")
                if invalid:
                    with st.expander("查看失败记录"):
                        st.json(invalid)
                st.session_state["add_success_msg"] = f"✅ 批量导入完成：成功 {ok} 个，失败 {len(invalid)} 行。"
                st.rerun()
        except Exception as e:
            st.error(f"解析文件失败：{e}")


def render_bulk_import():
    st.subheader("📥 批量导入商品/视频数据")
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
# 数据分析模块
# ---------------------------------------------------------------------------

def _df_to_xlsx(dfs: dict) -> bytes:
    """把多个 DataFrame 写成一个 Excel 的多个 sheet"""
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        for name, df in dfs.items():
            df.to_excel(w, sheet_name=name, index=False)
    return bio.getvalue()


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render_data_analysis():
    st.header("📊 数据分析")

    db = st.session_state.bd_db
    try:
        records = db.get_all()
    except Exception as e:
        st.error(f"无法连接宜搭：{e}")
        return
    if not records:
        st.info("底库为空，先添加网红再来看分析。")
        return

    def num(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    # ---- 总体数据 ----
    total_subs = sum(num(r.get("subscribers")) for r in records)
    total_views = sum(num(r.get("video_views")) for r in records)
    total_likes = sum(num(r.get("video_likes")) for r in records)
    total_comments = sum(num(r.get("video_comments")) for r in records)
    total_pviews = sum(num(r.get("product_views")) for r in records)
    total_orders = sum(num(r.get("orders")) for r in records)
    total_gmv = sum(num(r.get("gmv")) for r in records)

    st.subheader("总体数据")
    m = st.columns(7)
    m[0].metric("网红数", len(records))
    m[1].metric("总粉丝", fmt_num(total_subs))
    m[2].metric("总播放", fmt_num(total_views))
    m[3].metric("总点赞", fmt_num(total_likes))
    m[4].metric("总评论", fmt_num(total_comments))
    m[5].metric("总成交量", fmt_num(total_orders))
    m[6].metric("总 GMV", fmt_money(total_gmv))

    # ---- 分网红数据 ----
    st.subheader("分网红数据")
    rows = []
    for r in records:
        rows.append({
            "昵称": r.get("channel_name", ""),
            "垂类": r.get("category", ""),
            "挖掘人": r.get("recruiter", ""),
            "粉丝": int(num(r.get("subscribers"))),
            "播放": int(num(r.get("video_views"))),
            "点赞": int(num(r.get("video_likes"))),
            "评论": int(num(r.get("video_comments"))),
            "商品浏览": int(num(r.get("product_views"))),
            "点击率": fmt_percent(r.get("ctr")),
            "成交量": int(num(r.get("orders"))),
            "GMV": num(r.get("gmv")),
        })
    df_kol = pd.DataFrame(rows)
    st.dataframe(df_kol, use_container_width=True, hide_index=True)
    st.download_button(
        "导出分网红数据（Excel）",
        data=_df_to_xlsx({"分网红数据": df_kol}),
        file_name="yts_分网红数据.xlsx", mime=XLSX_MIME, key="dl_kol",
    )

    # ---- 分商品数据 ----
    st.subheader("分商品数据")
    prod = {}
    for r in records:
        link = str(r.get("product_link") or "").strip()
        if not link:
            continue
        p = prod.setdefault(link, {
            "商品链接": link, "关联网红": [], "浏览": 0, "成交量": 0, "GMV": 0.0, "点击率": "-",
        })
        p["关联网红"].append(str(r.get("channel_name", "")))
        p["浏览"] += int(num(r.get("product_views")))
        p["成交量"] += int(num(r.get("orders")))
        p["GMV"] += num(r.get("gmv"))
        if r.get("ctr"):
            p["点击率"] = fmt_percent(r.get("ctr"))
    if not prod:
        st.info("暂无商品链接数据，去「BD 底库」行内「商品」按钮里补充。")
        df_prod = None
    else:
        df_prod = pd.DataFrame([
            {**v, "关联网红": "、".join(v["关联网红"])} for v in prod.values()
        ])
        st.dataframe(df_prod, use_container_width=True, hide_index=True)
        st.download_button(
            "导出分商品数据（Excel）",
            data=_df_to_xlsx({"分商品数据": df_prod}),
            file_name="yts_分商品数据.xlsx", mime=XLSX_MIME, key="dl_prod",
        )

    # ---- 一键导出全部 ----
    df_total = pd.DataFrame([{
        "指标": k, "数值": v
    } for k, v in {
        "网红数": len(records),
        "总粉丝": total_subs,
        "总播放": total_views,
        "总点赞": total_likes,
        "总评论": total_comments,
        "总商品浏览": total_pviews,
        "总成交量": total_orders,
        "总GMV": total_gmv,
    }.items()])
    sheets = {"总体数据": df_total, "分网红数据": df_kol}
    if df_prod is not None:
        sheets["分商品数据"] = df_prod
    st.download_button(
        "📤 一键导出全部数据（Excel）",
        data=_df_to_xlsx(sheets),
        file_name="yts_数据分析.xlsx", mime=XLSX_MIME, key="dl_all",
    )

    # ---- AI 分析（可选） ----
    st.divider()
    st.subheader("🤖 AI 智能分析（可选）")
    ai_key = st.session_state.get("ai_api_key", "")
    if not ai_key:
        st.caption("想用 AI 分析的话，先在左侧填写 AI API Key。")
    else:
        if st.button("🤖 生成 AI 分析报告", use_container_width=True):
            with st.spinner("AI 正在分析数据..."):
                try:
                    summary_lines = [
                        f"总体：网红{len(records)}个，总播放{total_views:.0f}，总点赞{total_likes:.0f}，"
                        f"总评论{total_comments:.0f}，总成交量{total_orders:.0f}，总GMV {total_gmv:.0f}。",
                        "分网红：",
                        df_kol.to_string(index=False),
                    ]
                    if df_prod is not None:
                        summary_lines += ["分商品：", df_prod.to_string(index=False)]
                    prompt = (
                        "你是韩国网红营销团队的数据分析师。请根据以下 BD 底库数据输出：\n"
                        "1) 总体表现结论\n2) 每个网红的亮点与问题\n"
                        "3) 下一步动作建议（复投/换内容/加折扣/加曝光）。\n"
                        "用简洁中文，Markdown 格式。\n\n数据：\n" + "\n".join(summary_lines)
                    )
                    gen = AIEmailGenerator(provider="dashscope", api_key=ai_key, model=None)
                    st.session_state["analysis_report"] = gen.generate(prompt)
                except Exception as e:
                    st.error(f"分析失败：{e}")
    if st.session_state.get("analysis_report"):
        st.markdown(st.session_state["analysis_report"])


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="YTS网红管理库",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("🎯 YTS网红管理库")
    st.caption("数据存储在钉钉宜搭，团队共享一份数据")

    # 让顶部 Tab 均匀分布，避免堆在左侧
    # 表格整体压缩：按钮高度降低、行间距收紧、分隔线变细
    st.markdown(
        """
        <style>
            [data-testid="stTabs"] [role="tablist"] {
                display: flex;
                justify-content: space-between;
            }
            [data-testid="stTabs"] [role="tablist"] button {
                flex: 1;
                text-align: center;
            }
            [data-testid="stButton"] button {
                white-space: nowrap;
                padding: 0.05rem 0.3rem;
                min-width: auto;
                min-height: 1.2rem;
                font-size: 0.7rem;
                line-height: 1.1;
            }
            div[data-testid="stNumberInput"] button {
                display: none !important;
            }
            [data-testid="stHorizontalBlock"] {
                margin-bottom: -0.4rem !important;
            }
            hr {
                margin: 0.15rem 0 !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    render_sidebar()
    init_db()

    # 模块切换：按钮形式
    if "module" not in st.session_state:
        st.session_state.module = "base"

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("📁 BD 底库", use_container_width=True,
                     type="primary" if st.session_state.module == "base" else "secondary"):
            st.session_state.module = "base"
            st.rerun()
    with b2:
        if st.button("➕ 添加网红", use_container_width=True,
                     type="primary" if st.session_state.module == "add" else "secondary"):
            st.session_state.module = "add"
            st.rerun()
    with b3:
        if st.button("📊 数据分析", use_container_width=True,
                     type="primary" if st.session_state.module == "analysis" else "secondary"):
            st.session_state.module = "analysis"
            st.rerun()

    st.divider()

    if st.session_state.module == "base":
        render_bd_table()
    elif st.session_state.module == "add":
        render_add_influencer()
    else:
        render_data_analysis()


if __name__ == "__main__":
    main()
