#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 网站统一访问密码门（2026-08-26 修复：一次登录全站有效）

用法：在 yts_main_app.py / yts_review_app.py 的最顶部（set_page_config 之后、
加载数据之前）调用：

    from yts_auth import require_auth
    require_auth()

密码配置：Streamlit Cloud → 应用 → Settings → Secrets 加一行：

    SITE_PASSWORD = "你们团队约定的密码"

行为：
- 配置了 SITE_PASSWORD：输对一次密码后，30 天内全站免密——包括点进网红
  履约详情（整页跳转）、手动刷新、Streamlit 断连重连，都不用再输。
- 未配置 SITE_PASSWORD：允许进入，但顶部显示醒目警告。

实现（为什么以前跳到详情页要重复输密码）：
点进详情页是整页刷新（window.location.href 跳转），Streamlit 会话重建 →
session_state 清空。旧版只把登录态写进浏览器 Cookie，而 Cloud 环境下
components.html 在 sandbox iframe 里写 Cookie 经常不生效，于是整页刷新后
Cookie 读不到 → 又弹一次密码框。现在登录凭证走「双通道」并存：
  ① 浏览器 Cookie（同域刷新兜底）
  ② URL 查询参数 k=<签名凭证>（整页跳转 100% 不丢——yts_theme 的跳转脚本
     会合并保留现有 URL 参数，k 自然被带到每一页）
每次进入依次校验：session → URL 参数 k → Cookie，任一命中即免密放行；
任一命中后都会把凭证补写回 Cookie 与 URL，保证后续整页跳转都不再询问。
凭证值 = 密码的 HMAC 签名（不存明文；改密码后旧的 Cookie 与 URL 参数自动失效）。
"""
import hashlib
import hmac
import os

import streamlit as st

COOKIE_NAME = "yts_auth"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 天
AUTH_QUERY_KEY = "k"  # URL 查询参数名：整页跳转时携带登录凭证（最可靠的免密通道）


def _get_password() -> str:
    """从 Secrets / 环境变量读取访问密码"""
    pwd = os.environ.get("SITE_PASSWORD", "")
    if not pwd:
        try:
            pwd = str(st.secrets.get("SITE_PASSWORD", ""))
        except Exception:
            pwd = ""
    return pwd.strip()


def _auth_token(pwd: str) -> str:
    """密码 → 签名凭证（不存明文密码；改密码后旧凭证自动失效）"""
    return hmac.new(pwd.encode("utf-8"), b"yts-site-auth-v1",
                    hashlib.sha256).hexdigest()[:32]


def _read_cookie_token() -> str:
    """读取浏览器 Cookie 里的登录凭证（读不到返回 ''）"""
    try:
        cookies = st.context.cookies or {}
    except Exception:
        return ""
    return str(cookies.get(COOKIE_NAME) or "").strip()


def _write_cookie(token: str) -> None:
    """把登录凭证写入浏览器 Cookie。

    Streamlit 没有原生 set-cookie API，用 components.html 注入 JS 设置；
    iframe 与主页面同源，直接写主页面 document.cookie（整页刷新不丢）。"""
    import streamlit.components.v1 as components
    js = (f"<script>try{{var c='{COOKIE_NAME}={token};"
          f"path=/;max-age={COOKIE_MAX_AGE};SameSite=Lax';"
          f"document.cookie=c;"
          f"if(window.parent&&window.parent.document!==document){{"
          f"window.parent.document.cookie=c;}}}}catch(e){{}}</script>")
    components.html(js, height=0)


def _read_query_token() -> str:
    """读取 URL 查询参数里携带的登录凭证（读不到返回 ''）"""
    try:
        return str(st.query_params.get(AUTH_QUERY_KEY, "") or "").strip()
    except Exception:
        return ""


def _put_auth_in_url(token: str) -> None:
    """把登录凭证写进 URL 查询参数，整页跳转时由 yts_theme 的参数合并逻辑自动带到
    每一页；值不变时 Streamlit 不会重复触发 rerun，安全幂等。"""
    try:
        if str(st.query_params.get(AUTH_QUERY_KEY, "")) != token:
            st.query_params[AUTH_QUERY_KEY] = token
    except Exception:
        pass


def require_auth():
    """统一密码门。输对密码前不渲染任何业务内容。"""
    pwd = _get_password()

    # 未配置密码：放行但醒目警告（防止忘记配置把全员锁门外）
    if not pwd:
        st.warning("⚠️ 本站尚未配置访问密码（SITE_PASSWORD），"
                   "业务数据处于无保护状态。请尽快在 Streamlit Secrets 中配置。")
        return

    token = _auth_token(pwd)

    # ① 本会话已验证 → 直接放行（最快路径）
    if st.session_state.get("yts_authed") is True:
        return

    # ② URL 查询参数携带有效凭证（整页跳转/详情页免密的最可靠通道）
    #    → 恢复登录态，并把凭证补写回 Cookie，双通道保持一致
    if _read_query_token() == token:
        st.session_state["yts_authed"] = True
        _write_cookie(token)
        return

    # ③ 浏览器 Cookie 里有有效凭证（同域刷新/断连重连后）
    #    → 恢复登录态，并把凭证补写回 URL，后续整页跳转继续免密
    if _read_cookie_token() == token:
        st.session_state["yts_authed"] = True
        _put_auth_in_url(token)
        return

    # ④ 登录界面
    st.markdown(
        "<div style='max-width:380px;margin:80px auto 0;text-align:center'>"
        "<div style='font-size:40px'>🔒</div>"
        "<h3 style='margin:8px 0 4px'>YTS 全栈项目管理</h3>"
        "<p style='color:#86868b;font-size:13px;margin:0 0 18px'>"
        "内部业务系统，请输入访问密码（输对一次，30天内免重复输入）</p></div>",
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
                _write_cookie(token)          # Cookie：同域刷新兜底
                _put_auth_in_url(token)        # URL：整页跳转/详情页免密（关键）
                st.rerun()
            else:
                st.error("密码错误，请重试")
    st.stop()  # 未通过验证：到此为止，不渲染任何业务数据
