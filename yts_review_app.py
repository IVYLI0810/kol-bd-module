#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网红管理系统 - 独立审核站（裸粉 · Apple 极简版）"""
import html

import streamlit as st

from yts_yida_store import get_yts_store
import yts_theme as T

st.set_page_config(page_title="YTS 审核站", page_icon="🎬", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(T.THEME_CSS, unsafe_allow_html=True)

store = get_yts_store()
esc = html.escape

st.markdown(T.header("YTS 视频审核站", "审核同学专用 · 操作结果自动回传主管理后台"),
            unsafe_allow_html=True)

pending = store.list_pending_reviews()
history = store.list_review_history()
st.markdown(T.stats_row([
    ("⏳ 待审核", len(pending), "c-amber"),
    ("📜 已处理", len(history), "c-green"),
]), unsafe_allow_html=True)

tab1, tab2 = st.tabs(["⏳ 待审核", "📜 已处理"])

with tab1:
    if not pending:
        st.markdown(T.empty_hint("暂无待审核视频，主站提交审核后会自动出现在这里"),
                    unsafe_allow_html=True)
    for c in pending:
        key = c["collab_id"]
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(
                f'<div class="nm" style="font-size:14px;font-weight:600">'
                f'{esc(c["name"])}　{T.badge(c.get("plan_month") or "-")}'
                f'　{T.badge("待审核")}</div>'
                f'<div class="mt" style="font-size:12px;color:#86868b;margin-top:3px">'
                f'挖掘人 {esc(c.get("recruiter") or "-")} · '
                f'视频：<a class="yts-link" href="{esc(c["video_url"])}" '
                f'target="_blank">{esc(c["video_url"])}</a></div>',
                unsafe_allow_html=True)
            note = st.text_input("审核备注（选填）", key=f"note_{key}")
            reason = st.text_area("驳回原因 / 修改意见（驳回时必填）",
                                  key=f"reason_{key}", height=70)
            c1, c2 = st.columns(2)
            if c1.button("✅ 通过", key=f"pass_{key}", type="primary",
                         use_container_width=True):
                store.review_pass(key, note)
                st.toast(f"{c['name']}：已通过，结果已回传主站")
                st.rerun()
            if c2.button("❌ 驳回", key=f"rej_{key}", use_container_width=True):
                if not reason.strip():
                    st.error("驳回必须填写原因/修改意见")
                else:
                    store.review_reject(key, reason.strip())
                    st.toast(f"{c['name']}：已驳回，主站将进入复审环节")
                    st.rerun()

with tab2:
    if not history:
        st.markdown(T.empty_hint("暂无已处理记录"), unsafe_allow_html=True)
    for c in history:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            extra = ""
            if c["review_comment"]:
                extra += (f'<div class="mt" style="font-size:12px;color:#86868b;'
                          f'margin-top:3px">备注/原因：{esc(c["review_comment"])}'
                          f'</div>')
            if c.get("recheck_video_url"):
                extra += (f'<div class="mt" style="font-size:12px;color:#86868b;'
                          f'margin-top:3px">复审链接：'
                          f'<a class="yts-link" href="{esc(c["recheck_video_url"])}" '
                          f'target="_blank">{esc(c["recheck_video_url"])}</a></div>')
            st.markdown(
                f'<div class="nm" style="font-size:14px;font-weight:600">'
                f'{esc(c["name"])}　{T.badge(c["review_status"])}</div>{extra}',
                unsafe_allow_html=True)

st.markdown(T.foot("数据与主管理后台共享同一宜搭存储，操作即回传"),
            unsafe_allow_html=True)
