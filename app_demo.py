#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 网红管理库 - Streamlit 站（数据存钉钉宜搭，团队共享）

模块：
- 活动履约：仅引入在 kol 挖掘网站标记「已发邮件」的网红；
  左栏洽谈中固定，右栏按视频上传月份两列展示；
  确认合作（报价必填）→ 三分支（指南/合同/选品）→ 下单 → 提交审核 → 闭环
- 审核站：通过意见选填、驳回意见必填，审核记录只增不减
- 添加网红 / 数据分析
"""

import os
import re
import smtplib
import ssl
from datetime import datetime, date, timedelta
from email.header import Header
from email.mime.text import MIMEText
from io import BytesIO

import pandas as pd
import streamlit as st

from bd_database import get_bd_db
from youtube_analyzer import YouTubeAnalyzer, extract_channel_id
from ai_email_generator import AIEmailGenerator


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
        st.subheader("📨 发件邮箱（SMTP）")
        st.caption("用于站内直接给网红发邮件。Gmail 需使用「应用专用密码」。")
        SMTP_PRESETS = {
            "Gmail": ("smtp.gmail.com", 587),
            "Naver": ("smtp.naver.com", 587),
            "QQ 邮箱": ("smtp.qq.com", 465),
            "Outlook": ("smtp.office365.com", 587),
        }
        prov = st.selectbox(
            "邮箱类型", list(SMTP_PRESETS.keys()) + ["自定义"],
            key="smtp_prov",
        )
        if st.session_state.get("smtp_prov_prev") != prov:
            if prov in SMTP_PRESETS:
                st.session_state["smtp_host"] = SMTP_PRESETS[prov][0]
                st.session_state["smtp_port"] = SMTP_PRESETS[prov][1]
            st.session_state["smtp_prov_prev"] = prov
        c1, c2 = st.columns([3, 1])
        with c1:
            st.text_input("SMTP 服务器", key="smtp_host", value="smtp.gmail.com")
        with c2:
            st.number_input("端口", min_value=1, max_value=65535, key="smtp_port", value=587)
        st.text_input("发件账号", key="smtp_user", value=_secret("SMTP_USER"))
        st.text_input("密码 / 应用专用密码", key="smtp_pass", type="password",
                      value=_secret("SMTP_PASS"))

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
            st.session_state["add_success_msg"] = f"✅ {channel_name} 已成功加入底库。在 kol 挖掘网站标记「已发邮件」后，会自动进入「活动履约」看板。"
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
# 站内直发网红邮件（AI 基于数据分析生成内容 + SMTP 发送）
# ---------------------------------------------------------------------------

def _get_contact_email(rec: dict) -> str:
    m = re.search(r"CONTACT_EMAIL:\s*(\S+)", str(rec.get("notes") or ""))
    return m.group(1) if m else ""


def _set_contact_email(db, rec: dict, email: str) -> None:
    notes = str(rec.get("notes") or "")
    if "CONTACT_EMAIL:" in notes:
        notes = re.sub(r"CONTACT_EMAIL:\s*\S+", f"CONTACT_EMAIL: {email}", notes)
    else:
        notes = (notes.rstrip() + "\n" if notes.strip() else "") + f"CONTACT_EMAIL: {email}"
    db.update(rec["channel_id"], {"notes": notes})


def _ensure_dna(rec: dict) -> dict:
    """拿该网红的内容 DNA：优先缓存 → 真实抓取 → 模板模拟"""
    cid = rec["channel_id"]
    dna = st.session_state.get(f"dna_{cid}")
    if dna:
        return dna
    api_key = st.session_state.get("youtube_api_key", "")
    if api_key and rec.get("channel_url"):
        try:
            dna = _real_dna(rec, api_key)
        except Exception:
            dna = _tpl_dna(rec)
    else:
        dna = _tpl_dna(rec)
    st.session_state[f"dna_{cid}"] = dna
    return dna


# 韩文版内容 DNA（发给韩国网红的邮件用韩文表述，避免中文混入）
DNA_KO = {
    "뷰티": {
        "style": "실사용 전후 비교 + 부드러운 내레이션, 신뢰감 높은 추천",
        "tags": ["실측 비교", "몰입형 스킨케어", "성분 분석", "꿀템 모음"],
        "hook": "첫 15초 '사용 전후 비교'로 완주율 확보",
    },
    "여성의류": {
        "style": "착장 쇼케이스 + 실착 리뷰, 상황 몰입감이 뛰어난 콘텐츠",
        "tags": ["OOTD", "실착 리뷰", "출근룩", "작은 키 추천"],
        "hook": "'한 벌로 여러 코디' 빠른 전환 오프닝",
    },
    "라이프스타일": {
        "style": "브이로그 내러티브 + 감성 화면, 자연스러운 협찬 녹여내기",
        "tags": ["room tour", "힐링 브이로그", "자취 생활", "수납 정리"],
        "hook": "'ASMR 정리' 클립으로 몰입감 조성",
    },
    "요리": {
        "style": "단계별 레시피 + 집밥 재료, 실용성 높아 저장률이 우수한 콘텐츠",
        "tags": ["10분 요리", "초보 레시피", "도시락 밀프렙", "한 냄비 요리"],
        "hook": "완성품 클로즈업 + ASMR 사운드로 식욕 자극",
    },
    "패션": {
        "style": "트렌드 해석 + 코디 팁, 전문성 높은 인사이트 콘텐츠",
        "tags": ["트렌드 해석", "코디 공식", "시즌 코디", "액세서리 디테일"],
        "hook": "'유행 아이템 스트릿 스냅'으로 전문 이미지 구축",
    },
}


def _tpl_email_ko(rec: dict, dna: "dict | None") -> str:
    """无 AI Key 时的韩文模板邮件（仍基于数据分析填充）"""
    name = rec.get("channel_name", "-")
    sender = st.session_state.get("sender_name", "아이비")
    deadline = rec.get("deadline") or ""
    price = rec.get("price")
    product_link = str(rec.get("product_link") or "").strip()
    try:
        price_txt = f"₩{int(float(price)):,}" if price not in (None, "") else "계약서 협의 시 안내드릴게요"
    except (TypeError, ValueError):
        price_txt = "계약서 협의 시 안내드릴게요"
    ko = DNA_KO.get(str(rec.get("category") or "")) or {}
    style = ko.get("style", "크리에이터님의 고유한 스타일")
    hook = ko.get("hook", "")
    tags = ", ".join(ko.get("tags", []))
    L = [
        f"{name} 크리에이터님, 안녕하세요!",
        "",
        f"YTS 에서 콜라보레이션을 담당하고 있는 {sender} 입니다. "
        f"평소 채널을 눈여겨 봐왔는데, 「{style}」의 진정성 있는 매력이 정말 인상적이었어요. "
        "이번에 준비 중인 협업과 크리에이터님의 영향력이 멋진 시너지를 낼 수 있다고 확신합니다.",
        "",
        "간단한 협업 안내 드립니다.",
        "",
        f"1. 협업 상품: {product_link or '선정 완료 후 별도 안내'}",
        f"2. 콘텐츠 방향: 크리에이터님의 대표 스타일({tags or '기존 스타일'})을 자연스럽게 살려주시면 좋겠습니다."
        + (f" 오프닝은 「{hook}」 방식도 참고해 주세요." if hook else ""),
        f"3. 업로드 일정: {deadline or '협의 후 결정'}",
        f"4. 보상: {price_txt}",
        "",
        "관심이 있으시다면 회신 가능한 일정을 알려주세요. 상세 가이드를 보내드리겠습니다. "
        "크리에이터님의 창작을 최대한 지원해 드리겠습니다.",
        "",
        "감사합니다!",
        f"{sender} 드림",
    ]
    return "\n".join(L)


def _build_email_prompt(rec: dict, dna: dict) -> str:
    """把网红数据分析结果喂给 AI，生成韩文邀请邮件"""
    name = rec.get("channel_name", "-")
    sender = st.session_state.get("sender_name", "아이비")
    t = dna.get("tpl", {})
    vids = dna.get("vids", [])
    vid_txt = "、".join(v.get("title", "") for v in vids[:3]) or "无"
    product_link = str(rec.get("product_link") or "").strip()
    price = rec.get("price")
    try:
        price_txt = f"₩{int(float(price)):,}" if price not in (None, "") else "待定（以合同为准）"
    except (TypeError, ValueError):
        price_txt = "待定（以合同为准）"
    return f"""你是韩国 MCN 的资深 BD。请根据以下网红的真实数据分析（内容 DNA），
写一封韩语合作邀请邮件，直接输出邮件正文（含问候、正文、结尾署名 {sender}），不要任何解释。

要求：
- 语气礼貌真诚、简洁，不夸张；
- 结合内容 DNA 具体夸赞其内容特点（不要空泛套话）；
- 包含：合作来意、本期选品、内容方向建议、上传时间、报酬、邀请回复。

网红数据分析：
- 频道名：{name}
- 垂类：{rec.get('category') or '未分类'}；粉丝：{fmt_num(rec.get('subscribers'))}
- 内容风格：{t.get('style', '-')}
- 受众画像：{t.get('audience', '-')}
- 高频标签：{'、'.join(t.get('tags', []))}
- 开场钩子：{t.get('hook', '-')}
- 爆款视频主题：{vid_txt}

本期合作信息：
- 选品：{product_link or '选品完成后另行补充'}
- 报酬：{price_txt}
- 约定上传日期：{rec.get('deadline') or '另行协商'}
"""


def _send_smtp(to_addr: str, subject: str, body: str) -> None:
    """用侧边栏配置的 SMTP 发送邮件"""
    host = str(st.session_state.get("smtp_host") or "").strip()
    port = int(st.session_state.get("smtp_port") or 0)
    user = str(st.session_state.get("smtp_user") or "").strip()
    pwd = str(st.session_state.get("smtp_pass") or "")
    sender_name = st.session_state.get("sender_name", "아이비")
    if not (host and port and user and pwd):
        raise RuntimeError("请先在左侧「发件邮箱（SMTP）」配置发件账号和密码")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = f"{Header(sender_name, 'utf-8')} <{user}>"
    msg["To"] = to_addr
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, pwd)
            s.sendmail(user, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.sendmail(user, [to_addr], msg.as_string())


@st.dialog("AI 邮件")
def email_dialog(rec: dict, preset_body: str = "", mark_status: str = ""):
    """站内直发网红邮件：AI 基于数据分析生成 → 可编辑 → SMTP 发送"""
    cid = rec["channel_id"]
    db = st.session_state.bd_db
    name = rec.get("channel_name", "-")
    st.caption(f"网红：{name}。邮件内容由 AI 结合该网红的内容 DNA / 爆款数据 / 报价等分析生成，可修改后发送。")

    email = st.text_input(
        "网红邮箱", value=_get_contact_email(rec), key=f"mail_to_{cid}",
        placeholder="creator@gmail.com",
    )

    if st.button("✨ 生成 / 刷新 AI 邮件", use_container_width=True, key=f"mail_gen_{cid}"):
        with st.spinner("正在分析网红数据并生成邮件..."):
            dna = _ensure_dna(rec)
            ai_key = st.session_state.get("ai_api_key", "")
            if ai_key:
                try:
                    gen = AIEmailGenerator(provider="dashscope", api_key=ai_key, model=None)
                    st.session_state[f"mail_body_{cid}"] = gen.generate(_build_email_prompt(rec, dna))
                    st.session_state[f"mail_src_{cid}"] = "✅ 已基于内容 DNA 等数据分析，由 AI 生成韩文邮件"
                except Exception as e:
                    st.session_state[f"mail_body_{cid}"] = _tpl_email_ko(rec, dna)
                    st.session_state[f"mail_src_{cid}"] = f"AI 生成失败，已改用数据模板：{e}"
            else:
                st.session_state[f"mail_body_{cid}"] = _tpl_email_ko(rec, dna)
                st.session_state[f"mail_src_{cid}"] = "未配置 AI API Key，本次使用基于数据分析的模板邮件"
            if not st.session_state.get(f"mail_subject_{cid}"):
                st.session_state[f"mail_subject_{cid}"] = f"[협력 제안] {name}님, YTS 콜라보레이션 초청"
        # 注意：不要 st.rerun()，否则弹窗会关闭；
        # 下方主题/正文 widget 在同一次运行中实例化，会自动读取刚写入的 session_state。

    if preset_body and not st.session_state.get(f"mail_body_{cid}"):
        st.session_state[f"mail_body_{cid}"] = preset_body
        st.session_state[f"mail_src_{cid}"] = "正文为创作指南，可直接发送或修改"

    if st.session_state.get(f"mail_src_{cid}"):
        st.caption(st.session_state[f"mail_src_{cid}"])

    subject = st.text_input(
        "邮件主题", key=f"mail_subject_{cid}",
        value=f"[협력 제안] {name}님, YTS 콜라보레이션 초청",
    )
    body = st.text_area("邮件正文", key=f"mail_body_{cid}", height=320, value="")

    if st.button("📨 发送邮箱", use_container_width=True, type="primary", key=f"mail_send_{cid}"):
        addr = email.strip()
        if not re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", addr):
            st.error("请先填写有效的网红邮箱")
            return
        if not body.strip():
            st.error("正文为空，请先点「生成 / 刷新 AI 邮件」")
            return
        _set_contact_email(db, rec, addr)
        try:
            _send_smtp(addr, subject, body)
        except Exception as e:
            st.error(f"发送失败：{e}")
            return
        cur = str(rec.get("email_status") or "").strip()
        new_status = mark_status or (cur if cur in MAILED_STATUSES else "已发送")
        db.update(cid, {"email_status": new_status})
        st.session_state["pending_mail_sent"] = (
            f"✅ 邮件已发送给 {name}（{addr}），该网红已进入「活动履约」洽谈中栏。"
        )
        st.rerun()


# ---------------------------------------------------------------------------
# 活动履约模块（移植自 yts_demo.html 定稿流程）
# ---------------------------------------------------------------------------

DNA_TPL = {
    "뷰티": {
        "style": "真实测评对比 + 温柔口播，信任感种草",
        "tags": ["实测对比", "沉浸式护肤", "成分解析", "好物合集"],
        "len": "8-12 分钟", "time": "周四/周日 19:00-21:00",
        "audience": "女性 25-34 为主（约 72%）",
        "hook": "开头 15 秒「使用前后对比」锁定完播",
        "titles": ["爆火新品实测 30 天，真相是…", "沉浸式晚间护肤｜跟我一起用", "平价宝藏合集，学生党闭眼入"],
    },
    "여성의류": {
        "style": "穿搭展示 + 实穿测评，场景代入感强",
        "tags": ["OOTD", "实穿测评", "通勤穿搭", "小个子友好"],
        "len": "6-10 分钟", "time": "周五/周六 12:00-14:00",
        "audience": "女性 20-30 为主（约 68%）",
        "hook": "「一衣多穿」快切开场提升留存",
        "titles": ["一周通勤穿搭不重样，全平价", "155cm 小个子实穿｜春天这样穿", "一条连衣裙的 5 种搭法"],
    },
    "라이프스타일": {
        "style": "vlog 叙事 + 治愈画面，软性植入自然",
        "tags": ["room tour", "治愈 vlog", "独居生活", "收纳整理"],
        "len": "10-15 分钟", "time": "周末 20:00-22:00",
        "audience": "女性 18-29 为主（约 64%）",
        "hook": "「ASMR 整理」片段开场营造沉浸感",
        "titles": ["独居周末｜做饭、收纳、好好生活", "房间改造计划，预算 3 万韩元挑战", "我的晨间 routine"],
    },
    "요리": {
        "style": "步骤化教学 + 家常食材，实用收藏率高",
        "tags": ["10分钟料理", "新手食谱", "便当备餐", "一锅端"],
        "len": "8-12 分钟", "time": "周三/周日 17:00-19:00",
        "audience": "女性 25-44 为主（约 61%）",
        "hook": "成品特写 + ASMR 收音开场刺激食欲",
        "titles": ["10 分钟料理｜懒人奶油意面", "一周便当备餐，预算 2 万韩元", "一锅端料理，洗碗不烦恼"],
    },
    "패션": {
        "style": "趋势解读 + 搭配技巧，专业度输出强",
        "tags": ["趋势解读", "搭配公式", "季节穿搭", "配饰细节"],
        "len": "6-9 分钟", "time": "周六 11:00-13:00",
        "audience": "女性 18-27 为主（约 70%）",
        "hook": "「流行单品街拍」开场立专业人设",
        "titles": ["今年秋天流行色，一条视频讲清", "显贵搭配公式 5 条", "配饰细节决定完成度"],
    },
}

CAMP_CSS = """
<style>
.yts-card{background:#fff7f8;border:1px solid #ffdfe4;border-radius:12px;
 padding:14px 16px;margin-bottom:12px;}
.yts-card h4{margin:0 0 6px 0;font-size:16px;font-weight:600;color:#1d1d1f;}
.yts-sub{font-size:13px;color:#6e6e73;margin:0 0 8px 0;}
.yts-pill{display:inline-block;font-size:12px;border-radius:999px;
 padding:2px 10px;margin:2px 5px 2px 0;font-weight:600;}
.pill-pink{background:#ffe3e8;color:#c2185b;}
.pill-green{background:#e3f6e8;color:#1b7f3b;}
.pill-gray{background:#f0f0f2;color:#6e6e73;}
.pill-blue{background:#e5f0ff;color:#1a5fc9;}
.pill-orange{background:#fff1dc;color:#b26a00;}
.pill-red{background:#ffe5e5;color:#c62828;}
.yts-month-h{font-size:15px;font-weight:600;color:#1d1d1f;margin:4px 0 10px 0;}
</style>
"""


def _pill(text: str, color: str = "gray") -> str:
    return f"<span class='yts-pill pill-{color}'>{text}</span>"


def _d(s) -> "date | None":
    """'YYYY-MM-DD' -> datetime.date"""
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _stage_of(rec: dict) -> str:
    return str(rec.get("stage") or "").strip() or "洽谈中"


# 挖掘库标记「已发邮件」后才会进入活动履约看板
MAILED_STATUSES = ("已发送", "已发邮件", "指南已发送")


def _is_mailed(rec: dict) -> bool:
    return (str(rec.get("email_status") or "").strip()) in MAILED_STATUSES


def _camp_summary_pills(rec: dict) -> str:
    """卡片上的状态小标签"""
    out = []
    if rec.get("price"):
        out.append(_pill(f"报价 ₩{fmt_money(rec['price'])}", "pink"))
    if rec.get("deadline"):
        out.append(_pill(f"上传 {rec['deadline']}", "blue"))
    es = str(rec.get("email_status") or "").strip()
    if es == "指南已发送":
        out.append(_pill("指南已发送", "green"))
    elif es in MAILED_STATUSES:
        out.append(_pill("邮件已发送", "blue"))
    if rec.get("contract") == "已签署":
        out.append(_pill("合同已签署", "green"))
    if rec.get("order_status") == "已下单":
        out.append(_pill("已下单", "green"))
    rs = rec.get("review_status") or ""
    if rs == "待审核":
        out.append(_pill("待审核", "orange"))
    elif rs == "已通过":
        out.append(_pill("审核通过", "green"))
    elif rs == "已驳回":
        out.append(_pill("审核驳回", "red"))
    return "".join(out) or _pill("未开始", "gray")


def _inf_card(rec: dict, extra_buttons=None):
    """看板卡片（纯 HTML 部分）"""
    name = rec.get("channel_name", "-")
    cat = rec.get("category") or "未分类"
    subs = fmt_num(rec.get("subscribers"))
    return (
        f"<div class='yts-card'><h4>{name}</h4>"
        f"<p class='yts-sub'>{cat} · 粉丝 {subs}</p>"
        f"<p style='margin:2px 0 0 0'>{_camp_summary_pills(rec)}</p></div>"
    )


@st.dialog("确认合作")
def confirm_collab_dialog(rec: dict):
    """报价必填；同时可登记视频上传日期（=交稿截止）"""
    db = st.session_state.bd_db
    st.caption(f"网红：{rec.get('channel_name', '-')}")
    price = st.text_input(
        "网红报价（KRW）·必填", key=f"cf_price_{rec['channel_id']}",
        placeholder="如 900000",
    )
    deadline = st.date_input(
        "视频上传日期（可选）",
        value=_d(rec.get("deadline")) or (date.today() + timedelta(days=14)),
        key=f"cf_date_{rec['channel_id']}",
    )
    if st.button("✅ 确认合作", use_container_width=True, type="primary"):
        try:
            p = float(str(price).replace(",", "").strip())
        except (TypeError, ValueError):
            p = 0
        if p <= 0:
            st.error("请先填写网红报价（必填，且大于 0）")
            return
        updates = {"price": int(p), "stage": "履约中"}
        if deadline:
            updates["deadline"] = deadline.strftime("%Y-%m-%d")
        try:
            db.update(rec["channel_id"], updates)
            st.success(f"已确认合作，报价 ₩{int(p):,}")
            st.session_state.campaign_view = rec["channel_id"]
            st.rerun()
        except Exception as e:
            st.error(f"保存失败：{e}")


@st.dialog("审核通过")
def review_pass_dialog(rec: dict):
    comment = st.text_area("审核意见（选填）", key=f"rp_c_{rec['channel_id']}")
    if st.button("✅ 确认通过", use_container_width=True, type="primary"):
        try:
            db = st.session_state.bd_db
            db.update(rec["channel_id"], {"review_status": "已通过"})
            db.append_review_log(rec["channel_id"], "已通过", comment.strip())
            st.success("已通过审核，记录已写入审核日志")
            st.rerun()
        except Exception as e:
            st.error(f"保存失败：{e}")


@st.dialog("审核驳回")
def review_reject_dialog(rec: dict):
    comment = st.text_area("驳回原因（必填）", key=f"rj_c_{rec['channel_id']}")
    if st.button("🚫 确认驳回", use_container_width=True):
        if not comment.strip():
            st.error("驳回必须填写审核意见")
            return
        try:
            db = st.session_state.bd_db
            db.update(rec["channel_id"], {"review_status": "已驳回"})
            db.append_review_log(rec["channel_id"], "已驳回", comment.strip())
            st.success("已驳回，意见已写入审核日志")
            st.rerun()
        except Exception as e:
            st.error(f"保存失败：{e}")


def _tpl_dna(rec: dict) -> dict:
    """无 API Key / 抓取失败时的模板模拟 DNA"""
    cat = str(rec.get("category") or "")
    t = DNA_TPL.get(cat) or DNA_TPL["뷰티"]
    base = float(rec.get("total_views") or rec.get("video_views") or 3000000)
    dates = ["2026-05-14", "2026-03-02", "2026-01-21"]
    vids = []
    for k, tt in enumerate(t["titles"]):
        v = int(base * (0.085 - k * 0.022))
        vids.append({"title": tt, "views": v, "likes": int(v * 0.055),
                     "comments": int(v * 0.004), "date": dates[k], "url": ""})
    return {"tpl": t, "vids": vids, "src": "tpl",
            "gen_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _real_dna(rec: dict, api_key: str) -> dict:
    """用 YouTube API 抓真实爆款 TOP3，画像部分仍用垂类模板"""
    analyzer = YouTubeAnalyzer(api_key)
    result = analyzer.analyze_channel(rec["channel_url"], max_videos=30, max_comments=0)
    cat = str(rec.get("category") or "")
    t = DNA_TPL.get(cat) or DNA_TPL["뷰티"]
    vids = [
        {"title": v["title"], "views": v["view_count"], "likes": v["like_count"],
         "comments": v["comment_count"], "date": v.get("published_at", "")[:10],
         "url": v["url"]}
        for v in result["top_exposure"][:3]
    ]
    return {"tpl": t, "vids": vids, "src": "real",
            "gen_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _build_guide(rec: dict, dna: "dict | None") -> str:
    """生成可发给网红的创作指南（Markdown 文本）"""
    name = rec.get("channel_name", "-")
    deadline = rec.get("deadline") or ""
    plan_month = deadline[:7] if deadline else ""
    price = rec.get("price")
    product_link = str(rec.get("product_link") or "").strip()
    L = []
    L.append(f"【{name}】本期合作视频创作指南")
    L.append("")
    L.append(f"{name} 您好！感谢参与本期合作。为帮助您更高效地创作，我们整理了以下指南，供创作时参考。")
    L.append("")
    L.append("一、合作背景与流程")
    L.append(f"1. 计划上线月份：{plan_month or '待定'}；约定视频上传日期：{deadline or '另行确认'}。")
    L.append("2. 流程：提交未公开视频链接 → 我方审核通过 → 正式发布并回传公开链接。")
    L.append("")
    L.append("二、本期合作选品")
    if product_link:
        L.append(f"1. 合作商品链接：{product_link}")
        L.append("2. 卖点以商品详情页为准，请真实体验后口播 2-3 个核心卖点。")
    else:
        L.append("（尚未选品，待选品完成后另行补充。）")
    L.append("")
    L.append("三、内容方向建议")
    if dna:
        t = dna["tpl"]
        L.append(f"1. 建议延续您一贯的「{t['style']}」风格，保持人设真实感。")
        L.append(f"2. 视频时长建议 {t['len']}；发布于高互动时段 {t['time']}。")
        L.append(f"3. 开场可参考：{t['hook']}。")
        L.append(f"4. 可融入您的高频标签：{'、'.join(t['tags'])}。")
    else:
        L.append("1. 建议以您一贯的风格呈现，保证真实体验感。")
        L.append("2. 视频时长与发布时段参考您过往爆款数据。")
    L.append("")
    L.append("四、必须包含的信息（必填）")
    L.append("1. 口播专属折扣码，并引导观众查看描述区/评论区链接。")
    L.append("2. 每个选品需有真实使用画面与卖点口播。")
    L.append("3. 片尾加入购买链接引导画面（不少于 3 秒）。")
    L.append("")
    L.append("五、拍摄与合规要求")
    L.append("1. 画质不低于 1080p，收音清晰，无其他平台水印。")
    L.append("2. 不使用「第一」「最」等绝对化用语，功效表述以商品页为准。")
    L.append("3. 请在视频或描述中明确标注合作关系（遵循平台规范）。")
    L.append("")
    L.append("六、报酬与联系")
    try:
        price_txt = f"₩{int(float(price)):,}" if price not in (None, "") else "以合同为准"
    except (TypeError, ValueError):
        price_txt = "以合同为准"
    L.append(f"1. 本期合作报价：{price_txt}。")
    L.append("2. 有任何疑问请随时联系对接 BD，期待您的大作！")
    return "\n".join(L)


def render_analysis_guide(rec: dict):
    """分析与指南：内容 DNA（左）+ 创作指南（右）"""
    cid = rec["channel_id"]
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.markdown("##### 🧬 内容 DNA")
        dna = st.session_state.get(f"dna_{cid}")
        if st.button("生成 / 刷新内容 DNA", key=f"btn_dna_{cid}", use_container_width=True):
            api_key = st.session_state.get("youtube_api_key", "")
            if api_key and rec.get("channel_url"):
                with st.spinner("正在抓取该网红爆款视频与数据..."):
                    try:
                        st.session_state[f"dna_{cid}"] = _real_dna(rec, api_key)
                    except Exception as e:
                        st.session_state[f"dna_{cid}"] = _tpl_dna(rec)
                        st.warning(f"真实数据抓取失败，已改用模板模拟：{e}")
            else:
                st.session_state[f"dna_{cid}"] = _tpl_dna(rec)
                st.caption("未配置 YouTube API Key，本次为模板模拟画像。")
            st.rerun()
        if dna:
            t = dna["tpl"]
            src = "真实爆款数据" if dna["src"] == "real" else "模板模拟"
            st.caption(f"生成时间 {dna['gen_at']} · 来源：{src}")
            st.markdown(
                f"**风格定位**：{t['style']}  \n"
                f"**受众画像**：{t['audience']}  \n"
                f"**建议时长**：{t['len']} · **高互动时段**：{t['time']}  \n"
                f"**开场钩子**：{t['hook']}  \n"
                f"**高频标签**：{'、'.join(t['tags'])}"
            )
            st.markdown("**爆款 TOP3**")
            for i, v in enumerate(dna["vids"], 1):
                title = v["title"]
                if v.get("url"):
                    st.markdown(f"{i}. [{title}]({v['url']})")
                else:
                    st.markdown(f"{i}. {title}")
                st.caption(f"播放 {fmt_num(v['views'])} ｜ 点赞 {fmt_num(v['likes'])} ｜ 评论 {fmt_num(v['comments'])}")
        else:
            st.caption("点击上方按钮，抓取爆款视频并生成内容 DNA 画像。")

    with c2:
        st.markdown("##### 📝 创作指南")
        guide = st.session_state.get(f"guide_{cid}")
        if st.button("生成 / 刷新创作指南", key=f"btn_guide_{cid}", use_container_width=True):
            dna_now = st.session_state.get(f"dna_{cid}")
            st.session_state[f"guide_{cid}"] = _build_guide(rec, dna_now)
            st.rerun()
        if guide:
            st.code(guide, language="markdown")
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                st.download_button(
                    "⬇️ 下载 .md", data=guide.encode("utf-8"),
                    file_name=f"{rec.get('channel_name', 'kol')}_创作指南.md",
                    mime="text/markdown", key=f"dl_guide_{cid}", use_container_width=True,
                )
            with cc2:
                st.caption("💡 代码块右上角可一键复制")
            with cc3:
                sent = (rec.get("email_status") == "指南已发送")
                if sent:
                    st.markdown(_pill("指南已发送", "green"), unsafe_allow_html=True)
                elif st.button("✉️ 发送网红", key=f"btn_send_{cid}", use_container_width=True, type="primary"):
                    email_dialog(rec, preset_body=guide, mark_status="指南已发送")
        else:
            st.caption("结合内容 DNA 与本期选品，生成可直接发给网红的完整指南文档。")


def render_campaign_detail(rec: dict):
    """履约详情页：基本信息卡 + 流程进度 + 三分支 + 下单/提交审核/闭环"""
    cid = rec["channel_id"]
    db = st.session_state.bd_db

    if st.button("← 返回活动模块", key="camp_back"):
        st.session_state.pop("campaign_view", None)
        st.rerun()

    st.subheader(f"{rec.get('channel_name', '-')} · 履约详情")
    st.markdown(_camp_summary_pills(rec) + _pill(_stage_of(rec), "pink"), unsafe_allow_html=True)

    # ---- 基本信息卡 ----
    st.markdown("#### 基本信息")
    m = st.columns(5)
    m[0].metric("粉丝", fmt_num(rec.get("subscribers")))
    m[1].metric("垂类", rec.get("category") or "-")
    m[2].metric("频道总播放", fmt_num(rec.get("total_views")))
    m[3].metric("挖掘人", rec.get("recruiter") or "-")
    m[4].metric("网红报价", f"₩{fmt_money(rec.get('price'))}" if rec.get("price") else "-")

    ic1, ic2, ic3 = st.columns([1.2, 1.2, 1.6])
    with ic1:
        new_price = st.number_input(
            "修改报价（KRW）", min_value=0, step=10000,
            value=int(float(rec.get("price") or 0)), key=f"det_price_{cid}",
        )
        if st.button("保存报价", key=f"det_price_save_{cid}", use_container_width=True):
            if new_price <= 0:
                st.error("报价必须大于 0")
            else:
                db.update(cid, {"price": int(new_price)})
                st.success(f"报价已更新：₩{int(new_price):,}")
                st.rerun()
    with ic2:
        new_deadline = st.date_input(
            "视频上传日期", value=_d(rec.get("deadline")) or date.today(),
            key=f"det_date_{cid}",
        )
        if st.button("保存上传日期", key=f"det_date_save_{cid}", use_container_width=True):
            db.update(cid, {"deadline": new_deadline.strftime("%Y-%m-%d")})
            st.success(f"上传日期已登记：{new_deadline}")
            st.rerun()
    with ic3:
        st.caption("「视频上传日期」即交稿截止，活动看板按此日期分月份展示。")

    # ---- 流程进度 chips ----
    st.markdown("#### 流程进度")
    done_quote = bool(rec.get("price"))
    done_guide = (rec.get("email_status") == "指南已发送")
    done_contract = (rec.get("contract") == "已签署")
    done_product = bool(str(rec.get("product_link") or "").strip())
    done_order = (rec.get("order_status") == "已下单")
    done_submit = bool(rec.get("review_status"))
    passed = (rec.get("review_status") == "已通过")
    closed = (_stage_of(rec) == "已闭环")

    def step(name, ok, active_color="green"):
        return _pill(("✅ " if ok else "○ ") + name, active_color if ok else "gray")

    flow = (
        step("确认合作", done_quote)
        + step("指南已发送", done_guide)
        + step("合同签署", done_contract)
        + step("选品完成", done_product)
        + step("已下单", done_order)
        + step("提交审核", done_submit)
        + step("审核通过", passed)
        + step("已闭环", closed)
    )
    st.markdown(flow, unsafe_allow_html=True)

    st.divider()

    # ---- 并行准备：分析与指南（分支A） ----
    with st.expander("🧬 分析与指南（分支A：发送创作指南）", expanded=True):
        render_analysis_guide(rec)

    # ---- 分支B / 分支C / 下单 ----
    st.markdown("#### 并行准备（分支 B / C）与下单")
    b1, b2, b3 = st.columns(3, gap="large")
    with b1:
        st.markdown("**分支 B · 合同**")
        if done_contract:
            st.markdown(_pill("合同已签署", "green"), unsafe_allow_html=True)
        elif st.button("✍️ 标记合同已签署", key=f"btn_contract_{cid}", use_container_width=True):
            db.update(cid, {"contract": "已签署"})
            st.rerun()
    with b2:
        st.markdown("**分支 C · 选品（商品链接）**")
        plink = st.text_input(
            "商品链接", value=rec.get("product_link", ""),
            placeholder="https://ko.aliexpress.com/item/...",
            key=f"camp_plink_{cid}", label_visibility="collapsed",
        )
        if st.button("💾 保存选品链接", key=f"btn_plink_{cid}", use_container_width=True):
            db.update(cid, {"product_link": plink.strip()})
            st.rerun()
        if st.session_state.get(f"gmc_{cid}"):
            st.markdown(_pill("GMC 已登记（模拟）", "green"), unsafe_allow_html=True)
        elif st.button("🛒 提交 GMC 登记（模拟）", key=f"btn_gmc_{cid}", use_container_width=True):
            if not plink.strip() and not done_product:
                st.error("请先保存商品链接，再提交 GMC 登记")
            else:
                st.session_state[f"gmc_{cid}"] = True
                st.success("已模拟提交 GMC 登记（真实 GMC 接口后续接入），预计 1-2 个工作日审核。")
    with b3:
        st.markdown("**下单**")
        if done_order:
            st.markdown(_pill("已下单", "green"), unsafe_allow_html=True)
        elif st.button("📦 标记已下单", key=f"btn_order_{cid}", use_container_width=True):
            db.update(cid, {"order_status": "已下单"})
            st.rerun()
        st.caption("建议分支 A/B/C 至少完成一项后再下单。")

    st.divider()

    # ---- 提交审核 ----
    st.markdown("#### 提交审核")
    s1, s2, s3 = st.columns([2, 1, 1])
    with s1:
        vlink = st.text_input(
            "视频回链", value=rec.get("video_link", ""),
            placeholder="网红提交的未公开视频链接", key=f"camp_vlink_{cid}",
        )
    with s2:
        sub_date = st.date_input("提交日期", value=_d(rec.get("submitted_at")) or date.today(),
                                 key=f"camp_subdate_{cid}")
    with s3:
        st.write("")
        if st.button("📤 提交审核", key=f"btn_submit_{cid}", use_container_width=True, type="primary"):
            if not vlink.strip():
                st.error("请先填写视频回链")
            else:
                db.update(cid, {
                    "video_link": vlink.strip(),
                    "submitted_at": sub_date.strftime("%Y-%m-%d"),
                    "review_status": "待审核",
                })
                st.success("已提交审核，请前往「审核站」处理。")
                st.rerun()
    rs = rec.get("review_status") or ""
    if rs == "待审核":
        st.markdown(_pill("当前状态：待审核", "orange"), unsafe_allow_html=True)
    elif rs == "已通过":
        st.markdown(_pill("当前状态：审核已通过", "green"), unsafe_allow_html=True)
    elif rs == "已驳回":
        st.markdown(_pill("当前状态：审核已驳回（请修改后重新提交）", "red"), unsafe_allow_html=True)

    # ---- 闭环 ----
    st.divider()
    if closed:
        st.markdown(_pill("本单合作已闭环 🎉", "green"), unsafe_allow_html=True)
    elif st.button("🏁 标记已闭环", key=f"btn_close_{cid}", use_container_width=True,
                   disabled=(not passed)):
        db.update(cid, {"stage": "已闭环"})
        st.rerun()
    if not passed and not closed:
        st.caption("审核通过后即可闭环。")


def render_campaign():
    """活动履约看板：左栏洽谈中固定，右栏按上传月份两列展示"""
    st.markdown(CAMP_CSS, unsafe_allow_html=True)
    st.header("🗓 活动履约")
    st.caption("仅引入在 kol 挖掘网站标记「已发邮件」的网红；左栏洽谈中固定，右栏按视频上传月份分列（两列宽）。点击卡片进入履约详情。")

    if st.session_state.get("pending_mail_sent"):
        st.success(st.session_state.pop("pending_mail_sent"))

    db = st.session_state.bd_db
    try:
        records = db.get_all()
    except Exception as e:
        st.error(f"无法连接宜搭：{e}")
        return

    # 详情路由
    view_id = st.session_state.get("campaign_view")
    if view_id:
        rec = next((r for r in records if r.get("channel_id") == view_id), None)
        if rec:
            render_campaign_detail(rec)
            return
        st.session_state.pop("campaign_view", None)

    negotiating, fulfilling, closed, unmailed = [], [], [], []
    for r in records:
        s = _stage_of(r)
        if s == "履约中":
            fulfilling.append(r)
        elif s == "已闭环":
            closed.append(r)
        elif _is_mailed(r):
            negotiating.append(r)
        else:
            unmailed.append(r)

    left, right = st.columns([1, 2.3], gap="large")

    # ---- 左栏：洽谈中 ----
    with left:
        st.markdown(f"##### 💬 洽谈中（{len(negotiating)}）")
        if not negotiating:
            st.caption("暂无。在 kol 挖掘网站标记「已发邮件」后，网红会自动进入这里。")
        for r in negotiating:
            st.markdown(_inf_card(r), unsafe_allow_html=True)
            if st.button("确认合作", key=f"camp_confirm_{r['channel_id']}",
                         use_container_width=True, type="primary"):
                confirm_collab_dialog(r)

        st.divider()
        st.markdown(f"##### 📮 待联系（{len(unmailed)}）")
        if not unmailed:
            st.caption("所有网红都已发邮件。")
        st.caption("未发邮件的网红。可在站内直发 AI 邀请邮件，或在你自己邮箱发过后点「标记已发邮件」。")
        for r in unmailed:
            st.markdown(_inf_card(r), unsafe_allow_html=True)
            e1, e2 = st.columns(2)
            with e1:
                if st.button("AI 邮件", key=f"camp_email_{r['channel_id']}",
                             use_container_width=True, type="primary"):
                    email_dialog(r)
            with e2:
                if st.button("标记已发邮件", key=f"camp_mailed_{r['channel_id']}",
                             use_container_width=True,
                             help="已在站外自己邮箱发过邮件时用"):
                    db.update(r["channel_id"], {"email_status": "已发送"})
                    st.rerun()

    # ---- 右栏：履约中（按上传月份分组，两列宽） ----
    with right:
        st.markdown(f"##### 🚚 履约中（{len(fulfilling)}）")
        months: dict = {}
        for r in fulfilling:
            dl = str(r.get("deadline") or "")[:7]
            months.setdefault(dl or "未排期", []).append(r)
        order = sorted(k for k in months if k != "未排期")
        if "未排期" in months:
            order.append("未排期")
        if not order:
            st.caption("右栏暂无履约中的网红。在左栏点「确认合作」后自动进入本月看板。")
        for i in range(0, len(order), 2):
            pair = order[i:i + 2]
            cols = st.columns(2, gap="large")
            for col, month in zip(cols, pair):
                with col:
                    label = month if month != "未排期" else "未排期（未登记上传日期）"
                    st.markdown(f"<p class='yts-month-h'>📅 {label}（{len(months[month])}）</p>",
                                unsafe_allow_html=True)
                    for r in months[month]:
                        st.markdown(_inf_card(r), unsafe_allow_html=True)
                        if st.button("查看履约详情 →", key=f"camp_open_{r['channel_id']}",
                                     use_container_width=True):
                            st.session_state.campaign_view = r["channel_id"]
                            st.rerun()

    # ---- 已闭环归档 ----
    if closed:
        st.divider()
        with st.expander(f"🗂 已闭环（{len(closed)}）"):
            for r in closed:
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(
                        f"**{r.get('channel_name', '-')}** · {r.get('category') or '-'} · "
                        f"报价 ₩{fmt_money(r.get('price'))}"
                    )
                with c2:
                    if st.button("查看", key=f"camp_closed_{r['channel_id']}", use_container_width=True):
                        st.session_state.campaign_view = r["channel_id"]
                        st.rerun()


def render_review():
    """审核站：待审核列表 + 通过/驳回（驳回必填意见）+ 审核日志"""
    st.markdown(CAMP_CSS, unsafe_allow_html=True)
    st.header("✅ 审核站")
    st.caption("网红提交视频后在此审核。通过意见选填，驳回意见必填；每次审核自动追加审核记录（只增不减）。")

    db = st.session_state.bd_db
    try:
        records = db.get_all()
    except Exception as e:
        st.error(f"无法连接宜搭：{e}")
        return

    pending = [r for r in records if r.get("review_status") == "待审核"]
    st.markdown(f"##### ⏳ 待审核（{len(pending)}）")
    if not pending:
        st.info("暂无待审核视频。网红在「活动履约」里提交审核后，会出现在这里。")
    for r in pending:
        st.markdown(_inf_card(r), unsafe_allow_html=True)
        vlink = str(r.get("video_link") or "").strip()
        if vlink:
            st.markdown(f"视频回链：[{vlink}]({vlink})")
        else:
            st.caption("视频回链：未填写")
        if r.get("submitted_at"):
            st.caption(f"提交日期：{r['submitted_at']}")
        bc1, bc2, bc3 = st.columns([1, 1, 3])
        with bc1:
            if st.button("✅ 通过", key=f"rv_pass_{r['channel_id']}", use_container_width=True, type="primary"):
                review_pass_dialog(r)
        with bc2:
            if st.button("🚫 驳回", key=f"rv_reject_{r['channel_id']}", use_container_width=True):
                review_reject_dialog(r)
        st.divider()

    # ---- 审核日志 ----
    st.markdown("##### 📒 审核记录")
    logs = []
    for r in records:
        for row in (r.get("review_log") or []):
            logs.append({
                "网红": r.get("channel_name", "-"),
                "审核日期": row.get("date", ""),
                "审核结果": row.get("result", ""),
                "审核意见": row.get("comment", ""),
            })
    if not logs:
        st.caption("暂无审核记录。")
    else:
        logs.sort(key=lambda x: x["审核日期"], reverse=True)
        st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)


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

    # 全局样式：保持默认字号（清晰易读），仅隐藏数字输入框的加减按钮、
    # 让 Tabs 均匀分布
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
            div[data-testid="stNumberInput"] button {
                display: none !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    render_sidebar()
    init_db()

    # 模块切换：按钮形式
    if "module" not in st.session_state:
        st.session_state.module = "campaign"

    modules = [
        ("campaign", "🗓 活动履约"),
        ("review", "✅ 审核站"),
        ("add", "➕ 添加网红"),
        ("analysis", "📊 数据分析"),
    ]
    cols = st.columns(len(modules))
    for col, (key, label) in zip(cols, modules):
        with col:
            if st.button(label, use_container_width=True,
                         type="primary" if st.session_state.module == key else "secondary",
                         key=f"mod_{key}"):
                st.session_state.module = key
                st.rerun()

    st.divider()

    if st.session_state.module == "campaign":
        render_campaign()
    elif st.session_state.module == "review":
        render_review()
    elif st.session_state.module == "add":
        render_add_influencer()
    else:
        render_data_analysis()


if __name__ == "__main__":
    main()
