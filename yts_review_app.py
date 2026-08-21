#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网红管理系统 - 审核协作站（表格版 · 中韩双语）
工作流：主站提交视频 → 对接同学把链接打包转审核侧 → 审核侧出意见 →
对接同学在本表回填结果（直接编辑或上传 Excel），保存即回传主站。
两个模块：审核模块（是否通过/驳回原因）+ 投放模块（是否需要投放/是否投放）"""
import html
import io
import time
from datetime import datetime

import pandas as pd
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


# ---------- 表格列名（中韩双语，Excel 上传下载同一套） ----------
C_NAME = "크리에이터 网红"
C_HOME = "홈페이지 링크 主页链接"
C_VIDEO = "검토 링크 审核链接"
C_STATUS = "상태 状态"
C_SUBMIT = "제출 시각 提交时间"
C_AUDIT = "심사 시각 审核时间"
C_PASS = "통과 여부 是否通过"
C_REASON = "반려 사유 驳回原因"
C_AD_NEED = "광고 필요 여부 是否需要投放"
C_AD_DONE = "광고 완료 여부 是否投放"

# 状态 → 带 emoji 的显示文案（让待审核/已审核一眼可辨）
_STATUS_EMOJI = {
    "待审核": "⏳ 待审核",
    "已通过": "✅ 已通过",
    "已驳回": "❌ 已驳回",
    "复审中": "🔄 复审中",
    "复审通过": "✅ 复审通过",
}


def _norm(v):
    """单元格清洗：None/nan→空串，去空格"""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def _match_col(df, keywords):
    """按关键字模糊找列名（兼容只填了韩文或中文的表头）"""
    for col in df.columns:
        lc = str(col).lower()
        if any(k.lower() in lc for k in keywords):
            return col
    return None


def _df_to_bytes(df):
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


st.markdown(T.header(bih("YTS 영상 심사 · 광고 협업", "YTS 审核协作站"),
                     bih("표에 결과 입력 또는 Excel 업로드, 저장 즉시 메인 시스템에 반영",
                         "表格内填写结果或上传 Excel，保存即回传主管理后台")),
            unsafe_allow_html=True)

# 上一步操作提示（保存/上传的结果、钉钉通知发送成功与否，明明白白显示）
_f = st.session_state.pop("rev_flash", None)
if _f:
    (st.success if _f[0] == "ok" else st.warning)(_f[1])

# 审核站与主站是两个独立进程（缓存互不相通）。每 60 秒软失效一次：
# 保留旧数据立即返回（不阻塞），同时后台刷新，主站刚提交的审核最多 1 分钟可见。
# 用 _soft_invalidate 而非 _invalidate，避免清空缓存后下一个访问者被全表重拉卡住。
if time.time() - st.session_state.get("rev_sync_ts", 0) > 60:
    st.session_state["rev_sync_ts"] = time.time()
    store._soft_invalidate()

hb, _ = st.columns([1, 4])
if hb.button("🔄 목록 새로고침 · 刷新列表",
             help="主站刚提交的内容若未显示，点此立即刷新（平时每 60 秒也会自动刷新）"):
    store._soft_invalidate()
    st.session_state["rev_sync_ts"] = time.time()
    st.rerun()

review_rows = store.list_review_table()
ad_rows = store.list_ad_table()
n_pending = sum(1 for r in review_rows if not r["passed"])
n_ad_wait = sum(1 for r in ad_rows if r["ad_needed"] and not r["ad_done"])
n_done = sum(1 for r in review_rows if r["passed"])
st.markdown(T.stats_row([
    ("⏳ 심사 대기 (待审核)", n_pending, "c-amber"),
    ("📣 광고 대기 (待投放)", n_ad_wait, "c-pink"),
    ("📜 처리 완료 (已出结果)", n_done, "c-green"),
], narrow=True), unsafe_allow_html=True)

tab_rev, tab_ad = st.tabs(["🎬 검토 모듈 (审核模块)", "📣 광고 모듈 (投放模块)"])

# ============================ 审核模块 ============================
with tab_rev:
    st.caption("통과=Y / 반려=N / 대기 중=空白 · 통과 시에는 사유 비워둬도 되지만, "
               "반려 시에는 반드시 사유를 입력하세요")
    st.caption("通过填 Y、驳回填 N、还没出结果留空。驳回必须填写原因。"
               "可以直接在表格里填，也可以下载 Excel 拿给审核侧离线填写后上传回来。")

    orig_df = pd.DataFrame([{
        C_STATUS: _STATUS_EMOJI.get(r["status"], r["status"]),
        C_NAME: r["name"], C_HOME: r["channel_url"], C_VIDEO: r["review_url"],
        C_SUBMIT: r["submit_actual"], C_AUDIT: r["audit_time"],
        C_PASS: r["passed"], C_REASON: r["reason"],
    } for r in review_rows])
    # 行位置 -> collab_id（与 orig_df 行序一致，比按名字匹配更稳，避免重名/空格问题）
    id_by_pos = [r["collab_id"] for r in review_rows]
    id_by_name = {r["name"]: r["collab_id"] for r in review_rows}
    id_by_url = {r["channel_url"]: r["collab_id"] for r in review_rows
                 if r["channel_url"]}

    edited = st.data_editor(
        orig_df, key="rev_grid", hide_index=True, use_container_width=True,
        height=min(560, 80 + 38 * (len(orig_df) + 1)),
        column_config={
            C_STATUS: st.column_config.TextColumn("상태 状态", disabled=True, width="small"),
            C_NAME: st.column_config.TextColumn("크리에이터 网红", disabled=True, width="medium"),
            C_HOME: st.column_config.LinkColumn("홈페이지 主页", disabled=True, width="medium"),
            C_VIDEO: st.column_config.LinkColumn("검토 영상 审核视频", disabled=True, width="medium"),
            C_SUBMIT: st.column_config.TextColumn("제출 시각 提交时间", disabled=True, width="medium"),
            C_AUDIT: st.column_config.TextColumn("심사 시각 审核时间", disabled=True, width="medium"),
            C_PASS: st.column_config.TextColumn("통과? 通过? (Y/N)", width="small"),
            C_REASON: st.column_config.TextColumn("반려 사유 驳回原因", width="large"),
        })

    b1, b2, b3 = st.columns(3)
    if b1.button("💾 변경 사항 저장 · 保存修改", type="primary",
                 use_container_width=True, disabled=orig_df.empty):
        changes, missing_reason = [], []
        for i in range(len(edited)):
            row = edited.iloc[i]
            o = orig_df.iloc[i] if i < len(orig_df) else None
            passed, reason = _norm(row[C_PASS]).upper(), _norm(row[C_REASON])
            opass = _norm(o[C_PASS]).upper() if o is not None else ""
            if passed == opass and (passed != "N" or reason == _norm(o[C_REASON])):
                continue
            if passed not in ("Y", "N", ""):
                st.error(f"「{row[C_NAME]}」통과 여부只能是 Y 或 N（当前：{passed}）")
                st.stop()
            if not passed:
                continue
            if passed == "N" and not reason:
                missing_reason.append(str(row[C_NAME]))
                continue
            # 优先按行位置取 collab_id（与表格行序一一对应），名字匹配作兜底
            cid = id_by_pos[i] if i < len(id_by_pos) else id_by_name.get(str(row[C_NAME]), "")
            changes.append({"collab_id": cid,
                            "passed": passed, "reason": reason})
        if missing_reason:
            st.error("반려 시 사유 필수 · 以下驳回行未填原因，请补上再保存："
                     + "、".join(missing_reason))
        elif not changes:
            st.info("변경 사항이 없습니다 · 没有检测到修改")
        else:
            n, nok, nmsg = store.apply_review_results(changes)
            st.session_state["rev_flash"] = (
                "ok" if nok else "warn",
                f"✅ {n}건의 결과가 메인 시스템에 반영됨 · 已回传 {n} 条审核结果 · {nmsg}")
            st.rerun()

    if b2.download_button("⬇ Excel 다운로드 · 下载Excel",
                          data=_df_to_bytes(orig_df),
                          file_name=f"검토현황_{datetime.now():%Y%m%d}.xlsx",
                          use_container_width=True):
        pass

    up = b3.file_uploader("⬆ Excel 업로드 · 上传Excel", type=["xlsx", "xls"],
                          key="rev_upload",
                          help="上传从本站下载的表格（审核侧填好后），自动匹配网红并回写结果")
    if up is not None:
        try:
            up_df = pd.read_excel(up)
        except Exception as e:
            st.error(f"Excel 파일을 읽지 못했습니다 · 读取失败：{e}")
            st.stop()
        col_name = _match_col(up_df, ["크리에이터", "网红", "name"])
        col_home = _match_col(up_df, ["홈페이지", "主页", "channel"])
        col_pass = _match_col(up_df, ["통과", "是否通过", "pass"])
        col_reason = _match_col(up_df, ["반려", "驳回", "reason", "사유", "原因"])
        if not col_name or not col_pass:
            st.error("表头不对：请上传从本站「下载Excel」得到的表格（含 网红/是否通过 列）")
            st.stop()
        changes, skipped, bad = [], 0, []
        for _, row in up_df.iterrows():
            nm, home = _norm(row[col_name]), (_norm(row[col_home]) if col_home else "")
            cid = id_by_url.get(home) or id_by_name.get(nm)
            if not cid:
                if nm:
                    skipped += 1
                continue
            passed = _norm(row[col_pass]).upper()
            if passed not in ("Y", "N"):
                continue
            reason = _norm(row[col_reason]) if col_reason else ""
            if passed == "N" and not reason:
                bad.append(nm or cid)
                continue
            changes.append({"collab_id": cid, "passed": passed, "reason": reason})
        if bad:
            st.error("반려 시 사유 필수 · 以下驳回行未填原因，未写入：" + "、".join(bad[:10]))
        if not changes:
            st.info("쓸 내용이 없습니다 · 没有可写入的结果（空白/未变化的行会自动跳过）")
        else:
            n, nok, nmsg = store.apply_review_results(changes)
            extra = f"（{skipped} 行未匹配到网红被跳过）" if skipped else ""
            st.session_state["rev_flash"] = (
                "ok" if nok else "warn",
                f"✅ Excel 업로드 완료 · 上传成功，回传 {n} 条审核结果{extra} · {nmsg}")
            st.rerun()

# ============================ 投放模块 ============================
with tab_ad:
    st.caption("「광고 필요 여부 是否需要投放」는 메인 사이트에서 클로즈 시 운영이 선택합니다(읽기 전용). "
               "단편 영상=광고, 장편 영상=비광고")
    st.caption("「是否需要投放」由运营在主站闭环时选择（只读，短视频投/长视频不投）。"
               "投放完成后在「是否投放」列填 Y，或直接上传 Excel。")

    ad_df = pd.DataFrame([{
        C_NAME: r["name"], C_HOME: r["channel_url"],
        C_AD_NEED: r["ad_needed"], C_AD_DONE: r["ad_done"],
    } for r in ad_rows])
    ad_id_by_name = {r["name"]: r["collab_id"] for r in ad_rows}
    ad_id_by_url = {r["channel_url"]: r["collab_id"] for r in ad_rows
                    if r["channel_url"]}

    if ad_df.empty:
        st.markdown(T.empty_hint(bih(
            "광고 대기 항목이 없습니다. 메인 사이트에서 클로즈 시 「광고 필요」를 선택하면 여기에 표시됩니다",
            "暂无投放项。主站闭环时勾选「需要投放」后会自动出现在这里")),
            unsafe_allow_html=True)
    else:
        ad_edited = st.data_editor(
            ad_df, key="ad_grid", hide_index=True, use_container_width=True,
            height=min(560, 80 + 38 * (len(ad_df) + 1)),
            column_config={
                C_NAME: st.column_config.TextColumn("크리에이터 网红", disabled=True, width="medium"),
                C_HOME: st.column_config.LinkColumn("홈페이지 主页", disabled=True, width="medium"),
                C_AD_NEED: st.column_config.TextColumn("광고 필요? 需要投放?", disabled=True, width="small"),
                C_AD_DONE: st.column_config.TextColumn("광고 완료? 已投放? (Y)", width="small"),
            })
        c1, c2, c3 = st.columns(3)
        if c1.button("💾 변경 사항 저장 · 保存修改", type="primary",
                     use_container_width=True):
            changes = []
            for i in range(len(ad_edited)):
                done = _norm(ad_edited.iloc[i][C_AD_DONE]).upper() == "Y"
                was = _norm(ad_df.iloc[i][C_AD_DONE]).upper() == "Y"
                if done != was:
                    changes.append({"collab_id": ad_id_by_name.get(
                        str(ad_edited.iloc[i][C_NAME]), ""), "ad_done": "Y" if done else ""})
            if not changes:
                st.info("변경 사항이 없습니다 · 没有检测到修改")
            else:
                n = store.apply_ad_results(changes)
                st.session_state["rev_flash"] = (
                    "ok", f"✅ {n}건의 광고 상태가 반영됨 · 已更新 {n} 条投放状态")
                st.rerun()

        if c2.download_button("⬇ Excel 다운로드 · 下载Excel",
                              data=_df_to_bytes(ad_df),
                              file_name=f"광고현황_{datetime.now():%Y%m%d}.xlsx",
                              use_container_width=True):
            pass

        ad_up = c3.file_uploader("⬆ Excel 업로드 · 上传Excel", type=["xlsx", "xls"],
                                 key="ad_upload")
        if ad_up is not None:
            try:
                up_df = pd.read_excel(ad_up)
            except Exception as e:
                st.error(f"Excel 파일을 읽지 못했습니다 · 读取失败：{e}")
                st.stop()
            col_name = _match_col(up_df, ["크리에이터", "网红", "name"])
            col_home = _match_col(up_df, ["홈페이지", "主页", "channel"])
            col_done = _match_col(up_df, ["완료", "是否投放", "已投放", "done"])
            if not col_name or not col_done:
                st.error("表头不对：请上传从本站「下载Excel」得到的表格（含 网红/是否投放 列）")
                st.stop()
            changes, skipped = [], 0
            for _, row in up_df.iterrows():
                nm, home = _norm(row[col_name]), (_norm(row[col_home]) if col_home else "")
                cid = ad_id_by_url.get(home) or ad_id_by_name.get(nm)
                if not cid:
                    if nm:
                        skipped += 1
                    continue
                changes.append({"collab_id": cid,
                                "ad_done": "Y" if _norm(row[col_done]).upper() == "Y" else ""})
            n = store.apply_ad_results(changes)
            extra = f"（{skipped} 行未匹配到网红被跳过）" if skipped else ""
            st.session_state["rev_flash"] = (
                "ok", f"✅ Excel 업로드 완료 · 上传成功，更新 {n} 条投放状态{extra}")
            st.rerun()

st.markdown(T.foot(bih("데이터는 메인 관리 시스템과 동일한 Yida 저장소를 공유하며, 저장 즉시 회신됩니다",
                       "数据与主管理后台共享同一宜搭存储，保存即回传")),
            unsafe_allow_html=True)
