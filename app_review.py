# 入口接力文件：审核站真实代码在 yts_review_app.py。
# 新建 Cloud App 时可直接选 yts_review_app.py 作入口；
# 若沿用旧入口 app_review.py，则由本文件接力执行。
import os

_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yts_review_app.py")
exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"))
