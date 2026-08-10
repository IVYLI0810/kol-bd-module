import os

import streamlit.components.v1 as components

# 注册本地自定义组件：前端文件位于 frontend/index.html
_frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
_bd_table_component = components.declare_component("bd_table", path=_frontend_dir)


def bd_table(records, selected_ids, html, height=200, key="bd_table"):
    """渲染 BD 底库 HTML 表格组件，支持复选框、行点击和动作按钮。

    参数：
        records: 当前页展示的记录列表（用于前端键值稳定性）。
        selected_ids: 当前选中的 channel_id 列表。
        html: 组件 iframe 内要渲染的 HTML 字符串（包含 <style> 和 <table>）。
        height: iframe 高度（像素）。
        key: Streamlit 组件 key。

    返回 dict：
        {
            "selected": [...],      # 当前选中的 channel_id 列表
            "clicked": {"cid": ..., "ts": ...} | None,
            "action": {"cid": ..., "type": ..., "ts": ...} | None,
        }
    """
    return _bd_table_component(
        records=records,
        selected_ids=selected_ids,
        html=html,
        height=height,
        key=key,
        default={"selected": selected_ids, "clicked": None, "action": None},
    )
