#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网红管理系统 - 独立审核站（中韩双语 · 韩国审核同学为主、中文对照）"""
import html

import streamlit as st

from yts_yida_store import get_yts_store
import yts_theme as T

st.set_page_config(page_title="YTS 심사 스테이션 · YTS 审核站", page_icon="🎬",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown(T.THEME_CSS, unsafe_allow_html=True)
st.markdown('<style>.bi-zh{color:#9a9aa0;font-size:12px;font-weight:500;}'
            '.bi-zh::before{content:" · ";}</style>',
            unsafe_allow_html=True)

store = get_yts_store()
esc = html.escape


def bih(ko, zh):
    """HTML 文案：韩主中辅（中文灰小）"""
    return f'{ko}<span class="bi-zh">{zh}</span>'


STATUS_KO = {"待审核": "심사 대기", "已通过": "승인", "已驳回": "반려",
             "复审中": "재심사 중", "复审通过": "재심사 승인"}


def badge_bi(s):
    return T.badge(f"{STATUS_KO.get(s, s)} {s}")


st.markdown(T.header(bih("YTS 영상 심사", "YTS 视频审核站"),
                     bih("심사 담당자 전용, 처리 결과는 메인 관리 시스템에 자동 반영됩니다",
                         "审核同学专用 · 操作结果自动回传主管理后台")),
            unsafe_allow_html=True)

# 审核站与主站是两个独立进程（缓存互不相通）：主站刚提交的审核，
# 这里要等缓存过期才可见。提供手动刷新，清空本站缓存立即重拉。
hb, _ = st.columns([1, 4])
if hb.button("🔄 목록 새로고침 · 刷新列表",
             help="主站刚提交的审核若未显示，点此立即刷新"):
    store._invalidate()
    st.rerun()

pending = store.list_pending_reviews()
history = store.list_review_history()
st.markdown(T.stats_row([
    ("⏳ 심사 대기 (待审核)", len(pending), "c-amber"),
    ("📜 처리 완료 (已处理)", len(history), "c-green"),
], narrow=True), unsafe_allow_html=True)

tab1, tab2 = st.tabs(["⏳ 심사 대기 (待审核)", "📜 처리 완료 (已处理)"])

with tab1:
    if not pending:
        st.markdown(T.empty_hint(bih("심사 대기 영상이 없습니다. 메인 사이트에서 심사 제출 시 여기에 자동 표시됩니다",
                                     "暂无待审核视频，主站提交审核后会自动出现在这里")),
                    unsafe_allow_html=True)
    for c in pending:
        key = c["collab_id"]
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            st.markdown(
                f'<div class="nm" style="font-size:14px;font-weight:600">'
                f'{esc(c["name"])}　{T.badge(c.get("plan_month") or "-")}'
                f'　{badge_bi("待审核")}</div>'
                f'<div class="mt" style="font-size:12px;color:#86868b;margin-top:3px">'
                f'발굴 담당 (挖掘人) {esc(c.get("recruiter") or "-")} · '
                f'영상 (视频)：<a class="yts-link" href="{esc(c["video_url"])}" '
                f'target="_blank">{esc(c["video_url"])}</a></div>',
                unsafe_allow_html=True)
            if st.session_state.get(f"rej_{key}"):
                # 驳回态：强制填写原因
                st.text_area("반려 사유 / 수정 의견 (필수) · 驳回原因 / 修改意见（必填）",
                             key=f"reason_{key}", height=70)
                c1, c2 = st.columns([3, 1])
                if c1.button("❌ 반려 확인 · 确认驳回", key=f"rejok_{key}",
                             use_container_width=True):
                    reason = st.session_state.get(f"reason_{key}", "")
                    if not reason.strip():
                        st.error("반려 시 사유/수정 의견을 반드시 입력하세요 · 驳回必须填写原因/修改意见")
                    else:
                        st.session_state.pop(f"rej_{key}", None)
                        store.review_reject(key, reason.strip())
                        st.toast(f"{c['name']}：반려 · 已驳回，메인 사이트 재심사 절차로 · 主站将进入复审")
                        st.rerun()
                if c2.button("↩ 취소 · 取消", key=f"rejno_{key}"):
                    st.session_state.pop(f"rej_{key}", None)
                    st.rerun()
            else:
                # 默认态：只需选择 通过 / 驳回
                c1, c2 = st.columns(2)
                if c1.button("✅ 승인 · 通过", key=f"pass_{key}", type="primary",
                             use_container_width=True):
                    store.review_pass(key, "")
                    st.toast(f"{c['name']}：승인 · 已通过，결과 회신 완료 · 已回传主站")
                    st.rerun()
                if c2.button("❌ 반려 · 驳回", key=f"rejbtn_{key}",
                             use_container_width=True):
                    st.session_state[f"rej_{key}"] = True
                    st.rerun()

with tab2:
    if not history:
        st.markdown(T.empty_hint(bih("처리 기록이 없습니다", "暂无已处理记录")),
                    unsafe_allow_html=True)
    for c in history:
        with st.container():
            st.markdown(T.ycard_open(), unsafe_allow_html=True)
            extra = ""
            if c["review_comment"]:
                extra += (f'<div class="mt" style="font-size:12px;color:#86868b;'
                          f'margin-top:3px">메모/사유 (备注/原因)：{esc(c["review_comment"])}'
                          f'</div>')
            if c.get("recheck_video_url"):
                extra += (f'<div class="mt" style="font-size:12px;color:#86868b;'
                          f'margin-top:3px">재심사 링크 (复审链接)：'
                          f'<a class="yts-link" href="{esc(c["recheck_video_url"])}" '
                          f'target="_blank">{esc(c["recheck_video_url"])}</a></div>')
            st.markdown(
                f'<div class="nm" style="font-size:14px;font-weight:600">'
                f'{esc(c["name"])}　{badge_bi(c["review_status"])}</div>{extra}',
                unsafe_allow_html=True)

st.markdown(T.foot(bih("데이터는 메인 관리 시스템과 동일한 Yida 저장소를 공유하며, 처리 즉시 회신됩니다",
                       "数据与主管理后台共享同一宜搭存储，操作即回传")),
            unsafe_allow_html=True)
