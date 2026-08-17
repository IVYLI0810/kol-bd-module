# 入口接力文件：Cloud 主站 App 的入口固定为 app_demo.py（平台不允许改），
# 真实代码在 yts_main_app.py。这里每次 rerun 用 exec 完整执行它，
# 效果等同于 Streamlit 直接运行 yts_main_app.py。
import os

_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yts_main_app.py")
exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"))
