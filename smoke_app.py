#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""迁移后冒烟测试：AppTest 真实渲染主站各页 + 复合ID详情页 + 审核站"""
import sys

sys.path.insert(0, ".")
from streamlit.testing.v1 import AppTest

OK = True


def check(name, at):
    global OK
    if at.exception:
        OK = False
        print(f"✘ {name}: 异常")
        for e in at.exception:
            print("   ", str(e)[:300].replace("\n", " | "))
    else:
        print(f"✔ {name}: 渲染正常")
    return at


# 主站：首页 → 逐页点「进入」
at = AppTest.from_file("app_demo.py", default_timeout=120)
at.run()
check("主站-首页", at)
for pg, label in (("dig", "挖掘站"), ("activity", "活动"), ("analysis", "分析")):
    at2 = AppTest.from_file("app_demo.py", default_timeout=120)
    at2.run()
    btn = next((b for b in at2.button if b.key == f"hb_{pg}"), None)
    if btn is None:
        OK = False
        print(f"✘ 主站-{label}: 找不到入口按钮")
        continue
    btn.click().run()
    check(f"主站-{label}", at2)

# 复合ID详情页：하봄 7月
atd = AppTest.from_file("app_demo.py", default_timeout=120)
atd.query_params["detail"] = "UCpMTiotH-azWcWrIGeiBZbw#2026-07"
atd.run()
check("主站-详情(하봄7月复合ID)", atd)
txt = " ".join(m.value for m in atd.markdown if isinstance(m.value, str))
if "하봄" in txt:
    print("   ✔ 详情页含 하봄")
else:
    OK = False
    print("   ✘ 详情页缺 하봄")

# 审核站
atr = AppTest.from_file("app_review.py", default_timeout=120)
atr.run()
check("审核站", atr)

print("\n冒烟测试:", "全部通过 ✅" if OK else "有失败 ✘")
sys.exit(0 if OK else 1)
