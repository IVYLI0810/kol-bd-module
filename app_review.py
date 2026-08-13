#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 审核站 - 独立站点（给审核同学专用）

与管理站（app_demo.py）共享同一份钉钉宜搭数据：
- 待审核列表：通过（意见选填）/ 驳回（意见必填）
- 审核记录只增不减

部署：Streamlit Cloud → New app → 同一仓库（kol-bd-module），
Main file path 填 app_review.py；Secrets 同样配置
YIDA_ACCESS_KEY_ID / YIDA_ACCESS_KEY_SECRET。
"""

import pandas as pd
import streamlit as st

from app_demo import CAMP_CSS, _inf_card, init_db


@st.dialog("审核通过")
def review_pass_dialog(rec: dict):
    act = str(rec.get("activity_name") or "").strip()
    rk = f"{rec['channel_id']}::{act}"
    comment = st.text_area("审核意见（选填）", key=f"rp_c_{rk}")
    if st.button("✅ 确认通过", use_container_width=True, type="primary"):
        try:
            db = st.session_state.bd_db
            db.update(rec["channel_id"], {"review_status": "已通过"}, rec.get("activity_name"))
            db.append_review_log(rec["channel_id"], "已通过", comment.strip(),
                                 activity=rec.get("activity_name"))
            st.success("已通过审核，记录已写入审核日志")
            st.rerun()
        except Exception as e:
            st.error(f"保存失败：{e}")


@st.dialog("审核驳回")
def review_reject_dialog(rec: dict):
    act = str(rec.get("activity_name") or "").strip()
    rk = f"{rec['channel_id']}::{act}"
    comment = st.text_area("驳回原因（必填）", key=f"rj_c_{rk}")
    if st.button("🚫 确认驳回", use_container_width=True):
        if not comment.strip():
            st.error("驳回必须填写审核意见")
            return
        try:
            db = st.session_state.bd_db
            db.update(rec["channel_id"], {"review_status": "已驳回"}, rec.get("activity_name"))
            db.append_review_log(rec["channel_id"], "已驳回", comment.strip(),
                                 activity=rec.get("activity_name"))
            st.success("已驳回，意见已写入审核日志")
            st.rerun()
        except Exception as e:
            st.error(f"保存失败：{e}")


def render_review():
    """待审核列表 + 通过/驳回（驳回必填意见）+ 审核日志"""
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
        act = str(r.get("activity_name") or "").strip()
        rk = f"{r['channel_id']}::{act}"
        st.markdown(_inf_card(r), unsafe_allow_html=True)
        caps = []
        if act:
            caps.append(f"活动：{act}")
        if r.get("recruiter"):
            caps.append(f"挖掘人：{r['recruiter']}")
        if caps:
            st.caption(" ｜ ".join(caps))
        vlink = str(r.get("video_link") or "").strip()
        if vlink:
            st.markdown(f"视频回链：[{vlink}]({vlink})")
        else:
            st.caption("视频回链：未填写")
        if r.get("submitted_at"):
            st.caption(f"提交日期：{r['submitted_at']}")
        bc1, bc2, bc3 = st.columns([1, 1, 3])
        with bc1:
            if st.button("✅ 通过", key=f"rv_pass_{rk}", use_container_width=True, type="primary"):
                review_pass_dialog(r)
        with bc2:
            if st.button("🚫 驳回", key=f"rv_reject_{rk}", use_container_width=True):
                review_reject_dialog(r)
        st.divider()

    # ---- 审核日志 ----
    st.markdown("##### 📒 审核记录")
    logs = []
    for r in records:
        for row in (r.get("review_log") or []):
            logs.append({
                "网红": r.get("channel_name", "-"),
                "活动": str(r.get("activity_name") or "").strip() or "-",
                "审核日期": row.get("date", ""),
                "审核结果": row.get("result", ""),
                "审核意见": row.get("comment", ""),
            })
    if not logs:
        st.caption("暂无审核记录。")
    else:
        logs.sort(key=lambda x: x["审核日期"], reverse=True)
        st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)


def main():
    st.set_page_config(
        page_title="YTS审核站",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.title("✅ YTS审核站")
    st.caption("数据存储在钉钉宜搭，与管理站共享。通过意见选填，驳回意见必填；审核记录只增不减。")
    st.markdown(CAMP_CSS, unsafe_allow_html=True)
    init_db()
    render_review()


if __name__ == "__main__":
    main()
