#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网站统一访问密码门（2026-08-25 数据安全加固）

用法：在 yts_main_app.py / yts_review_app.py 的最顶部（set_page_config 之后、
加载数据之前）调用：

    from yts_auth import require_auth
    require_auth()

密码配置：Streamlit Cloud → 应用 → Settings → Secrets 加一行：

    SITE_PASSWORD = "你们团队约定的密码"

行为：
- 配置了 SITE_PASSWORD：必须先输对密码才能进入（每个浏览器会话只需输一次）
- 未配置 SITE_PASSWORD：允许进入，但顶部显示醒目警告（提醒尽快配置，
  避免忘记配置导致全员被锁在门外）
"""
import os

import streamlit as st


def _get_password() -> str:
    """从 Secrets / 环境变量读取访问密码"""
    pwd = os.environ.get("SITE_PASSWORD", "")
    if not pwd:
        try:
            pwd = str(st.secrets.get("SITE_PASSWORD", ""))
        except Exception:
            pwd = ""
    return pwd.strip()


def require_auth():
    """统一密码门。输对密码前不渲染任何业务内容。"""
    pwd = _get_password()

    # 未配置密码：放行但醒目警告（防止忘记配置把全员锁门外）
    if not pwd:
        st.warning("⚠️ 本站尚未配置访问密码（SITE_PASSWORD），"
                   "业务数据处于无保护状态。请尽快在 Streamlit Secrets 中配置。")
        return

    # 已通过验证的会话直接放行
    if st.session_state.get("yts_authed") is False:
        pass
    if st.session_state.get("yts_authed") is True:
        return

    # 登录界面
    st.markdown(
        "<div style='max-width:380px;margin:80px auto 0;text-align:center'>"
        "<div style='font-size:40px'>🔒</div>"
        "<h3 style='margin:8px 0 4px'>YTS 全栈项目管理</h3>"
        "<p style='color:#86868b;font-size:13px;margin:0 0 18px'>"
        "内部业务系统，请输入访问密码</p></div>",
        unsafe_allow_html=True,
    )
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        entered = st.text_input("访问密码", type="password",
                                key="yts_auth_input",
                                label_visibility="collapsed",
                                placeholder="请输入访问密码")
        if st.button("进入系统", type="primary",
                     use_container_width=True, key="yts_auth_btn"):
            if entered == pwd:
                st.session_state["yts_authed"] = True
                st.rerun()
            else:
                st.error("密码错误，请重试")
    st.stop()  # 未通过验证：到此为止，不渲染任何业务数据
