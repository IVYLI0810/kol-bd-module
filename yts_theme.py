#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 网红管理系统 - 视觉主题（裸粉 · Apple 极简）

设计语言：近白粉底 + 白卡片 + 发丝分割线 + 小圆角 + 轻阴影
字号 13px 起步、字重 500-600、主色 #1d1d1f、点缀粉 #c2507a
"""

THEME_CSS = """
<style>
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC',
                 'Microsoft YaHei', sans-serif;
}
html {font-size: 14px;}
.stApp {background: #faf4f6 !important;}
section.main .block-container {max-width: 1180px; padding-top: 1.6rem;}
#MainMenu, footer {visibility: hidden;}
body, p, span, div, label {color: #1d1d1f;}

/* ---------- 头部 ---------- */
.yheader {margin: 2px 0 14px 0;}
.yheader h1 {font-size: 21px; font-weight: 700; color: #1d1d1f; margin: 0;
    letter-spacing: -.2px;}
.yheader h1::before {content: ""; display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; background: #e39ab1; margin-right: 9px; vertical-align: 2px;}
.yheader p {font-size: 12.5px; font-weight: 500; color: #86868b; margin: 5px 0 0 17px;}

/* ---------- 统计卡 ---------- */
.ystats {display: flex; gap: 10px; margin: 4px 0 16px 0;}
.ystat {flex: 1; background: #fff; border: 1px solid #f1e4e8; border-radius: 14px;
    padding: 12px 16px; box-shadow: 0 1px 2px rgba(29,29,31,.03);}
.ystat .n {font-size: 22px; font-weight: 700; letter-spacing: -.3px;}
.ystat .l {font-size: 12px; font-weight: 600; color: #86868b; margin-top: 1px;}
.c-pink .n {color: #c2507a;} .c-purple .n {color: #7a5fd0;}
.c-green .n {color: #1a7f4b;} .c-amber .n {color: #b26a09;}

/* ---------- 徽章 ---------- */
.ybadge {display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 11px; font-weight: 600; white-space: nowrap;}
.b-gray {background: #f2f2f4; color: #6e6e73;}
.b-pink {background: #fdeef3; color: #c2507a;}
.b-green {background: #e5f6ec; color: #1a7f4b;}
.b-amber {background: #fdf4e0; color: #b26a09;}
.b-red {background: #fdecec; color: #c0392b;}
.b-purple {background: #f1edfb; color: #7a5fd0;}

/* ---------- 卡片 ---------- */
.ycard {background: #fff; border: 1px solid #f1e4e8; border-radius: 14px;
    padding: 12px 16px; margin: 8px 0; box-shadow: 0 1px 2px rgba(29,29,31,.03);}
.ycard .nm {display: block; font-size: 14px; font-weight: 600; color: #1d1d1f;}
.ycard .mt {display: block; font-size: 12px; font-weight: 500; color: #86868b;
    margin-top: 3px;}
a.ycard {display: block; text-decoration: none; color: inherit;
    transition: box-shadow .15s ease, transform .15s ease;}
a.ycard, a.ycard * {text-decoration: none !important; color: inherit;}
a.ycard .mt {color: #86868b;}
a.ycard:hover {box-shadow: 0 5px 16px rgba(190,120,145,.14); transform: translateY(-1px);}
a.ycard.closed {border-color: #cdead8;
    box-shadow: 0 0 0 1px #ddf2e5, 0 4px 16px rgba(52,199,123,.16);}
.closed-tag {font-size: 11px; font-weight: 600; color: #1a7f4b;}

/* 三分支进度点 */
.bdots {display: inline-flex; gap: 4px; vertical-align: 1px;}
.bdot {width: 7px; height: 7px; border-radius: 50%; background: #eadfe3;}
.bdot.on {background: #3fbf7f;}

/* 原生容器 → 白卡片：容器内首元素放 .ycard-box 标记，:has() 命中外层 */
.ycard-box {display: none;}
div[data-testid="stVerticalBlock"]:has(> div.element-container .ycard-box) {
    border: 1px solid #f1e4e8 !important; border-radius: 14px !important;
    background: #fff !important; padding: 12px 14px !important;
    margin: 8px 0 !important; box-shadow: 0 1px 2px rgba(29,29,31,.03) !important;
}

/* ---------- 真实表格 ---------- */
.yts-tablewrap {background: #fff; border: 1px solid #f1e4e8; border-radius: 14px;
    padding: 4px 8px; box-shadow: 0 1px 2px rgba(29,29,31,.03); overflow-x: auto;}
table.yts-table {width: 100%; border-collapse: collapse; font-size: 13px;}
.yts-table th {text-align: left; font-size: 12px; color: #86868b; font-weight: 600;
    padding: 9px 10px; border-bottom: 1px solid #f0e4e8; white-space: nowrap;}
.yts-table td {padding: 9px 10px; border-bottom: 1px solid #f6eef1; font-weight: 500;
    color: #1d1d1f; vertical-align: middle;}
.yts-table tr:last-child td {border-bottom: none;}
.yts-table tr:hover td {background: #fdf9fa;}
.yts-table .num {font-variant-numeric: tabular-nums;}
.yts-link {color: #c2688a; font-weight: 600; text-decoration: none;}
.yts-link:hover {text-decoration: underline;}
a.act, .act {display: inline-block; padding: 3px 12px; border-radius: 999px;
    background: #fdeef3; color: #c2507a; font-size: 12px; font-weight: 600;
    text-decoration: none !important; white-space: nowrap;}
a.act:hover, .act:hover {background: #fbdce7; text-decoration: none !important;}

/* ---------- 流程图（单块渲染，横向） ---------- */
.yts-steps {display: flex; margin: 10px 0 20px 0;}
.ystep {flex: 1; display: flex; flex-direction: column; align-items: center;
    position: relative; min-width: 0;}
.ystep .dot {width: 28px; height: 28px; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
    background: #f3ecef; color: #a89aa1; border: 1px solid #ecdfe4; z-index: 1;}
.ystep.done .dot {background: #e5f6ec; color: #1a7f4b; border-color: #bfe6cf;}
.ystep.doing .dot {background: #fdeef3; color: #c2507a; border-color: #f0c3d4;}
.ystep .lbl {margin-top: 6px; font-size: 11.5px; font-weight: 600; color: #86868b;
    text-align: center; line-height: 1.35;}
.ystep.done .lbl {color: #1a7f4b;}
.ystep.doing .lbl {color: #c2507a;}
.ystep:not(:last-child)::after {content: ""; position: absolute; top: 14px;
    left: calc(50% + 18px); width: calc(100% - 36px); height: 2px; background: #efe3e8;}
.ystep.done:not(:last-child)::after {background: #cdead8;}

/* ---------- 原生可点流程条（隐形按钮覆盖，点击=轻量刷新） ---------- */
.stepnode {display: flex; flex-direction: column; align-items: center;
    min-width: 0; padding: 4px 0 2px 0;}
.stepnode .dot {width: 28px; height: 28px; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
    background: #f3ecef; color: #a89aa1; border: 1px solid #ecdfe4;
    position: relative; z-index: 1; transition: box-shadow .12s ease;}
.stepnode.done .dot {background: #e5f6ec; color: #1a7f4b; border-color: #bfe6cf;}
.stepnode.doing .dot {background: #fdeef3; color: #c2507a; border-color: #f0c3d4;}
.stepnode .lbl {margin-top: 6px; font-size: 11.5px; font-weight: 600; color: #86868b;
    text-align: center; line-height: 1.35; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; max-width: 100%;}
.stepnode.done .lbl {color: #1a7f4b;}
.stepnode.doing .lbl {color: #c2507a;}
div[data-testid="stColumn"]:has(.stepnode) {position: relative;}
div[data-testid="stColumn"]:has(.stepnode):not(:last-child)::after {content: "";
    position: absolute; top: 18px; left: calc(50% + 18px); right: calc(-50% + 18px);
    height: 2px; background: #efe3e8;}
div[data-testid="stColumn"]:has(.stepnode.done):not(:last-child)::after {background: #cdead8;}
div[data-testid="stColumn"]:has(.stepnode):hover .dot {box-shadow: 0 2px 8px rgba(190,120,145,.25);}
.stepnode.sel .dot {box-shadow: 0 0 0 3px #fff, 0 0 0 5px #dd8fa8;}
.stepnode.sel .lbl {color: #1d1d1f;}
div[data-testid="stColumn"]:has(.stepnode) button {position: absolute !important;
    inset: 0 !important; width: 100% !important; height: 100% !important;
    opacity: 0 !important; cursor: pointer; z-index: 6; margin: 0 !important;
    padding: 0 !important; box-shadow: none !important;}
div[data-testid="stColumn"]:has(.stepnode) button:focus,
div[data-testid="stColumn"]:has(.stepnode) button:active {outline: none !important;
    box-shadow: none !important;}

/* 分支小卡 */
.ybranch {border: 1px solid #f1e4e8; border-radius: 12px; background: #fff;
    padding: 10px 12px; height: 100%;}
.ybranch.done {background: #f2fbf6; border-color: #cdead8;}
.ybranch .bt {font-size: 12.5px; font-weight: 600; color: #1d1d1f;}
.ybranch .bd {font-size: 11.5px; font-weight: 500; color: #86868b; margin-top: 2px;}

/* ---------- 杂项 ---------- */
.ymonth {display: inline-block; font-size: 12px; font-weight: 700; color: #c2507a;
    background: #fdeef3; padding: 3px 14px; border-radius: 999px; margin: 12px 0 2px 0;}
.yempty {border: 1px dashed #e5cdd6; border-radius: 14px; padding: 20px;
    text-align: center; color: #9a8b91; font-size: 12.5px; font-weight: 500;
    background: #fffdfe; margin: 8px 0;}
.ysub {font-size: 15px; font-weight: 700; color: #1d1d1f; margin: 14px 0 6px 0;}
.yfoot {margin-top: 26px; color: #a89aa1; font-size: 11.5px; font-weight: 500;
    text-align: center;}

/* ---------- 原生控件微调 ---------- */
.stButton > button {
    border-radius: 10px !important; border: 1px solid #e8d8dd !important;
    background: #fff !important; color: #1d1d1f !important;
    font-weight: 600 !important; font-size: 12.5px !important;
    height: 34px !important; padding: 0 14px !important;
    box-shadow: none !important; transition: background .12s ease !important;
}
.stButton > button:hover {background: #fdf3f6 !important; border-color: #e3c4cf !important;}
.stButton > button[kind="primary"] {
    background: #dd8fa8 !important; border-color: #dd8fa8 !important;
    color: #fff !important;
}
.stButton > button[kind="primary"]:hover {background: #d57f99 !important;}
.stFormSubmitButton > button {
    border-radius: 10px !important; border: 1px solid #e8d8dd !important;
    background: #fff !important; color: #1d1d1f !important;
    font-weight: 600 !important; font-size: 12.5px !important;
    height: 34px !important; padding: 0 14px !important;
}
.stFormSubmitButton > button[kind="primaryFormSubmit"] {
    background: #dd8fa8 !important; border-color: #dd8fa8 !important;
    color: #fff !important;
}
.stFormSubmitButton > button[kind="primaryFormSubmit"]:hover {background: #d57f99 !important;}
button[data-testid="stNumberInputStepDown"],
button[data-testid="stNumberInputStepUp"] {display: none !important;}
.stTextInput input, .stNumberInput input, .stTextArea textarea,
div[data-baseweb="select"] > div {
    border-radius: 10px !important; border: 1px solid #e8d8dd !important;
    background: #fff !important; font-weight: 500 !important; font-size: 13px !important;
}
.stNumberInput input::-webkit-outer-spin-button,
.stNumberInput input::-webkit-inner-spin-button {-webkit-appearance: none;}
label, .stTextInput label, .stNumberInput label, .stSelectbox label {
    font-size: 12.5px !important; font-weight: 600 !important; color: #6e6e73 !important;
}
div[data-testid="stModal"] > div {border-radius: 18px !important; border: 1px solid #f1e4e8;}
div[data-testid="stExpander"] {border: 1px solid #f1e4e8; border-radius: 14px;
    background: #fff;}
div[data-testid="stTabs"] ul[role="tablist"] {gap: 4px;}
div[data-testid="stTabs"] button[role="tab"] {font-size: 13px; font-weight: 600;
    color: #86868b;}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {color: #c2507a;}
.stToast {border-radius: 12px !important;}
</style>
"""

# ------------------------- 生成器 -------------------------

BADGE_MAP = {
    "未发邮件": "b-gray", "已回流活动": "b-green", "已发邮件": "b-amber",
    "洽谈中": "b-amber", "履约中": "b-purple", "已闭环": "b-green",
    "待审核": "b-amber", "已通过": "b-green", "复审通过": "b-green",
    "已驳回": "b-red", "复审中": "b-purple", "修改中": "b-red",
    "未发送": "b-gray", "已发送": "b-green", "未签署": "b-gray", "已签署": "b-green",
    "待校验": "b-gray", "校验通过": "b-green", "拍摄中": "b-amber", "已完成": "b-green",
    "未下单": "b-gray", "已下单": "b-purple", "已收货": "b-green",
}


def badge(text: str) -> str:
    cls = BADGE_MAP.get(text, "b-gray")
    return f'<span class="ybadge {cls}">{text}</span>'


def header(title: str, sub: str) -> str:
    return f'<div class="yheader"><h1>{title}</h1><p>{sub}</p></div>'


def stats_row(items: list) -> str:
    """items: [(标签, 数量, 颜色类 c-pink/c-purple/c-green/c-amber)]"""
    html = '<div class="ystats">'
    for label, n, cls in items:
        html += (f'<div class="ystat {cls}"><div class="n">{n}</div>'
                 f'<div class="l">{label}</div></div>')
    return html + "</div>"


def sub(text: str) -> str:
    return f'<div class="ysub">{text}</div>'


def empty_hint(text: str) -> str:
    return f'<div class="yempty">{text}</div>'


def month_tag(m: str) -> str:
    return f'<div class="ymonth">{m}</div>'


def foot(text: str) -> str:
    return f'<div class="yfoot">{text}</div>'


def ycard_open() -> str:
    """放在 st.container() 内第一行，把整个容器变成白卡片"""
    return '<div class="ycard-box"></div>'


def branch_dots(branches: dict) -> str:
    html = '<span class="bdots">'
    for k in ("guideline", "contract", "gmc"):
        html += f'<span class="bdot{" on" if branches.get(k) else ""}"></span>'
    return html + "</span>"


def table(headers: list, rows: list, wrap: bool = True) -> str:
    """rows: 二维列表，单元格为安全 HTML 字符串；wrap=False 时不包外框（组件内用）"""
    th = "".join(f"<th>{h}</th>" for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
    inner = (f'<table class="yts-table"><thead><tr>{th}</tr></thead>'
             f'<tbody>{body}</tbody></table>')
    return f'<div class="yts-tablewrap">{inner}</div>' if wrap else inner


def steps_bar(steps: list, selected: int = None, nav_id: str = None) -> str:
    """steps: [(标签, 状态 done/doing/todo)]，横向流程条。
    nav_id 给定时节点可点（iframe 内 data-nav 跳转 ?detail&step），
    selected 为当前展开的节点索引（高亮圈）。"""
    html = '<div class="yts-steps">'
    for i, (label, state) in enumerate(steps):
        icon = "✓" if state == "done" else str(i + 1)
        sel = " sel" if i == selected else ""
        inner = (f'<div class="dot">{icon}</div><div class="lbl">{label}</div>')
        if nav_id:
            html += (f'<a class="ystep {state}{sel}" '
                     f'data-nav="#step={i}">{inner}</a>')
        else:
            html += f'<div class="ystep {state}{sel}">{inner}</div>'
    return html + "</div>"


def name_card(c: dict, node: str) -> str:
    """履约右栏卡片：整卡可点 → ?detail="""
    closed = c.get("is_closed")
    cls = "ycard closed" if closed else "ycard"
    tag = ' <span class="closed-tag">已闭环</span>' if closed else ""
    return (f'<a class="{cls}" data-nav="?detail={c["collab_id"]}">'
            f'<span class="nm">{c["name"]}{tag}</span>'
            f'<span class="mt">{c.get("category") or "-"} · '
            f'{c.get("followers", 0):,} 粉丝 · {badge(node)} '
            f'{branch_dots(c.get("branches", {}))}</span></a>')


def branch_card(t: str, done: bool, desc: str) -> str:
    cls = "ybranch done" if done else "ybranch"
    return (f'<div class="{cls}"><div class="bt">{t}</div>'
            f'<div class="bd">{desc}</div></div>')


# ------------------------- 可点击组件（iframe 内跳转） -------------------------
# Streamlit 前端会吞掉 st.markdown 里同源 <a> 的点击，故表格行操作 / 整卡点击
# 改走 components.v1.html：同域 iframe 内用 JS 驱动父窗口跳转（?xxx=yyy）。

COMP_CSS = """
* {box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont,
   'SF Pro Text', 'PingFang SC', 'Microsoft YaHei', sans-serif;}
body {margin: 0; background: transparent;}
table.yts-table {width: 100%; border-collapse: collapse; font-size: 13px;
    background: #fff; border: 1px solid #f1e4e8; border-radius: 14px;}
.yts-table th {text-align: left; font-size: 12px; color: #86868b; font-weight: 600;
    padding: 9px 10px; border-bottom: 1px solid #f0e4e8; white-space: nowrap;}
.yts-table td {padding: 9px 10px; border-bottom: 1px solid #f6eef1; font-weight: 500;
    color: #1d1d1f; vertical-align: middle;}
.yts-table tr:last-child td {border-bottom: none;}
.yts-table tr:hover td {background: #fdf9fa;}
.yts-table .num {font-variant-numeric: tabular-nums;}
a.act {display: inline-block; padding: 3px 12px; border-radius: 999px;
    background: #fdeef3; color: #c2507a; font-size: 12px; font-weight: 600;
    text-decoration: none; white-space: nowrap; cursor: pointer;}
a.act:hover {background: #fbdce7;}
.yts-steps {display: flex; margin: 6px 4px 4px 4px;}
a.ystep {flex: 1; display: flex; flex-direction: column; align-items: center;
    position: relative; min-width: 0; text-decoration: none; cursor: pointer;}
.ystep .dot {width: 28px; height: 28px; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
    background: #f3ecef; color: #a89aa1; border: 1px solid #ecdfe4; z-index: 1;
    transition: box-shadow .12s ease;}
a.ystep:hover .dot {box-shadow: 0 2px 8px rgba(190,120,145,.25);}
.ystep.sel .dot {box-shadow: 0 0 0 3px #fff, 0 0 0 5px #dd8fa8;}
.ystep.done .dot {background: #e5f6ec; color: #1a7f4b; border-color: #bfe6cf;}
.ystep.doing .dot {background: #fdeef3; color: #c2507a; border-color: #f0c3d4;}
.ystep .lbl {margin-top: 6px; font-size: 11.5px; font-weight: 600; color: #86868b;
    text-align: center; line-height: 1.35;}
.ystep.done .lbl {color: #1a7f4b;}
.ystep.doing .lbl {color: #c2507a;}
.ystep.sel .lbl {color: #1d1d1f;}
.ystep:not(:last-child)::after {content: ""; position: absolute; top: 14px;
    left: calc(50% + 18px); width: calc(100% - 36px); height: 2px; background: #efe3e8;}
.ystep.done:not(:last-child)::after {background: #cdead8;}
.ybadge {display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 11px; font-weight: 600; white-space: nowrap;}
.b-gray {background: #f2f2f4; color: #6e6e73;} .b-pink {background: #fdeef3; color: #c2507a;}
.b-green {background: #e5f6ec; color: #1a7f4b;} .b-amber {background: #fdf4e0; color: #b26a09;}
.b-red {background: #fdecec; color: #c0392b;} .b-purple {background: #f1edfb; color: #7a5fd0;}
.ymonth {display: inline-block; font-size: 12px; font-weight: 700; color: #c2507a;
    background: #fdeef3; padding: 3px 14px; border-radius: 999px; margin: 10px 0 2px 0;}
.ycard {display: block; background: #fff; border: 1px solid #f1e4e8; border-radius: 14px;
    padding: 12px 16px; margin: 8px 0; cursor: pointer;
    box-shadow: 0 1px 2px rgba(29,29,31,.03); transition: box-shadow .15s ease;}
.ycard:hover {box-shadow: 0 5px 16px rgba(190,120,145,.14);}
.ycard.closed {border-color: #cdead8;
    box-shadow: 0 0 0 1px #ddf2e5, 0 4px 16px rgba(52,199,123,.16);}
.ycard .nm {display: block; font-size: 14px; font-weight: 600; color: #1d1d1f;}
.ycard .mt {display: block; font-size: 12px; font-weight: 500; color: #86868b;
    margin-top: 3px;}
.closed-tag {font-size: 11px; font-weight: 600; color: #1a7f4b;}
.bdots {display: inline-flex; gap: 4px; vertical-align: 1px;}
.bdot {width: 7px; height: 7px; border-radius: 50%; background: #eadfe3;}
.bdot.on {background: #3fbf7f;}
"""

COMP_JS = r"""
<script>
// 父页面里紧跟在流程条 iframe 之后的 8 个原生按钮（点击靶子，加载后隐藏）
function stepButtons() {
    var fe = window.frameElement;
    if (!fe) return [];
    var all = window.parent.document.querySelectorAll('button');
    var out = [];
    for (var i = 0; i < all.length; i++) {
        if (fe.compareDocumentPosition(all[i]) & 4 /* FOLLOWING */) out.push(all[i]);
        if (out.length === 8) break;
    }
    return out;
}
document.addEventListener('click', function (e) {
    var a = e.target.closest('[data-nav]');
    if (!a) return;
    e.preventDefault();
    var nav = a.getAttribute('data-nav') || '';
    if (nav.indexOf('#step=') === 0) {
        // 流程节点：不整页刷新，"按下"父页面对应的隐藏原生按钮 → 轻量 rerun
        var i = parseInt(nav.slice(6), 10);
        var b = stepButtons()[i];
        if (b) b.click();
        return;
    }
    // 普通跳转（卡片等）：sandbox iframe 无 allow-top-navigation，
    // 利用 allow-same-origin 向父页面注入脚本，由顶层上下文自己跳转；
    // 合并现有 URL 参数（如 rec），不丢上下文。
    var p = window.parent.location;
    var params = new URLSearchParams(p.search);
    new URLSearchParams(nav.replace(/^\?/, ''))
        .forEach(function (v, k) { params.set(k, v); });
    var url = p.pathname + '?' + params.toString();
    var d = window.parent.document;
    var s = d.createElement('script');
    s.textContent = 'window.location.href = ' + JSON.stringify(url) + ';';
    d.body.appendChild(s);
});
(function () {
    if (!document.querySelector('.ystep')) return;
    var tries = 0;
    function hide() {
        var bs = stepButtons();
        if (bs.length === 8) {
            bs.forEach(function (b) {
                var el = b;
                while (el && el !== window.parent.document.body) {
                    el = el.parentElement;
                    if (el && el.getAttribute
                            && el.getAttribute('data-testid') === 'stElementContainer') break;
                }
                var target = (el && el !== window.parent.document.body) ? el : b;
                target.style.setProperty('display', 'none', 'important');
            });
        } else if (tries++ < 50) {
            // 云端流式渲染：按钮可能晚于流程条到达父页面，轮询等待
            setTimeout(hide, 200);
        }
    }
    hide();
})();
</script>
"""


def component_html(body: str, height: int) -> None:
    import streamlit.components.v1 as components
    components.html(f"<style>{COMP_CSS}</style>{body}{COMP_JS}", height=height)
