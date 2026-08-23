#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多月多行线上迁移（模板=YTS流程导入模版-2.xlsx，42行， ground truth）：

两个多月频道：
  하봄   线上1条(标2026-09，实为7月执行数据+9月外壳) → 新建7月/8月，9月清残留
  이노   线上1条(标2026-08，基础字段=8月新合作，视频链接=7月的) →
         新建7月记录(릴리 LILYNAIL, 闭环视频L1cS0H2uyDg)；8月记录清掉串门的7月视频链接
         （视频上传于2026-07-29、标题/作者均为릴리，确认属7月合作；8月选品=家居类留在8月）

其余37行同月 upsert，保护规则：
  - 线上已有视频链接 → 不覆盖（模板里的旧链接可能是发稿前的网盘稿）
  - 指标类标量(播放/点赞/成交等)一律不写（以线上累计值为准）
  - videos 子表不动（派生记录本就不带，双保险）
"""
import json
import re
import sys
import time

sys.path.insert(0, ".")

import yts_import_flow as FI
from yida_bd_database import YidaBDDB
from yts_yida_store import _cfg

TPL = "/Users/iivyli/Downloads/YTS流程导入模版-2.xlsx"
METRIC_KEYS = ("video_views", "video_likes", "video_comments",
               "product_views", "orders", "gmv")


def norm_u(u):
    return re.sub(r"^https?://(www\.)?", "", str(u or "").strip().rstrip("/"))


db = YidaBDDB(**_cfg())

print("== 0. fresh 备份 ==")
all_rows = db.get_all()
ts = time.strftime("%Y%m%d_%H%M")
bk = f"../yida_backup/yida_all_{ts}_pre_migrate.json"
with open(bk, "w") as f:
    json.dump(all_rows, f, ensure_ascii=False, indent=1)
print(f"   已备份 {len(all_rows)} 条 → {bk}")

url_idx = {}
for r in all_rows:
    u = norm_u(r.get("channel_url"))
    if u:
        url_idx.setdefault(u, r)

rows, issues = FI.parse_workbook(open(TPL, "rb").read())
assert len(rows) == 42, f"模板行数异常: {len(rows)}"
assert not issues, f"模板解析问题: {issues}"

plan = []
for raw in rows:
    live = url_idx.get(norm_u(raw["channel_url"]))
    assert live, f"线上找不到频道: {raw['channel_url']}"
    plan.append((raw, live.get("channel_id")))

habom_cid = next(cid for raw, cid in plan if "하봄" in str(raw.get("channel_name")))
ino_cid = next(cid for raw, cid in plan if "ino_in2" in norm_u(raw["channel_url"]))
print(f"   하봄={habom_cid}  이노={ino_cid}")


def derive(raw, cid):
    rec = FI.derive_record(raw, cid)
    return {k: v for k, v in rec.items() if not k.startswith("_")}


print("\n== 1. 新建 하봄 7月/8月 ==")
created = []
for raw, cid in plan:
    if cid == habom_cid and raw.get("plan_month") in ("2026-07", "2026-08"):
        r = db.add(derive(raw, cid))  # 7月行含3条视频链接→自动拆3行视频子表
        created.append(raw.get("plan_month"))
        print(f"   ✔ 新建 하봄 {raw.get('plan_month')}  inst={r.get('form_instance_id')}")
assert sorted(created) == ["2026-07", "2026-08"], created

print("\n== 2. 新建 이노 7月记录（릴리 LILYNAIL，闭环） ==")
lily_raw = next(raw for raw, cid in plan
                if cid == ino_cid and raw.get("plan_month") == "2026-07")
assert "L1cS0H2uyDg" in str(lily_raw.get("video_link"))
rec = derive(lily_raw, ino_cid)
rec["videos"] = [{"video_url": str(lily_raw["video_link"]).strip(),
                  "video_type": "Shorts", "product_ids": "",
                  "views": 0, "likes": 0, "comments": 0,
                  "clicks": 0, "ctr": 0, "orders": 0, "gmv": 0}]
r = db.add(rec)
print(f"   ✔ 新建 릴리 2026-07  inst={r.get('form_instance_id')}")

print("\n== 3. 이노 8月记录清掉串门的7月视频链接 ==")
ino_live = next(r for r in all_rows if r.get("channel_id") == ino_cid)
assert ino_live.get("plan_month") == "2026-08"
assert "L1cS0H2uyDg" in str(ino_live.get("video_link") or "")
db.update(ino_cid, {}, clear_fields=["video_link"], plan_month="2026-08")
chk = db.get_by_channel_id(ino_cid, "2026-08")
assert not (chk.get("video_link") or ""), chk.get("video_link")
assert int(chk.get("price") or 0) == 400000
assert len(chk.get("products") or []) == 7, "8月选品(GMC)应留在8月记录"
print("   ✔ 8月记录视频链接已清，基础字段/选品不动")

print("\n== 4. 其余37行 upsert（保护已有视频链接与指标） ==")
SKIP = {habom_cid, ino_cid}
n_upd, n_prot = 0, 0
for raw, cid in plan:
    if cid in SKIP:
        continue
    rec = derive(raw, cid)
    live = url_idx[norm_u(raw["channel_url"])]
    protected = False
    for k in METRIC_KEYS:  # 指标以线上累计为准，模板不覆盖
        rec.pop(k, None)
    if live.get("video_link"):  # 线上已有发稿链接 → 不用模板旧链接覆盖
        if rec.pop("video_link", None) or rec.pop("recheck_video_url", None):
            protected = True
    if live.get("videos") and rec.get("videos"):  # 双保险：不动已有视频子表
        rec.pop("videos")
        protected = True
    db.add(rec)
    n_upd += 1
    n_prot += 1 if protected else 0
print(f"   ✔ upsert {n_upd} 行（其中 {n_prot} 行保护了已有视频链接）")

print("\n== 5. 하봄 9月记录清残留 ==")
db.update(habom_cid, {"stage": "已确认"},
          clear_fields=["guideline_status", "contract_status", "gmc_status",
                        "order_status", "shoot_status", "video_link",
                        "audit_status", "recheck_video_url"],
          plan_month="2026-09")
sep = db.get_by_channel_id(habom_cid, "2026-09")
leftover = [k for k in ("guideline_status", "contract_status", "gmc_status",
                        "order_status", "shoot_status", "video_link",
                        "audit_status")
            if (sep.get(k) or "")]
assert not leftover, f"9月残留未清: {leftover}"
assert (sep.get("email_status") or "") == "已发送"
assert int(sep.get("price") or 0) == 500000
assert len(sep.get("product_list") or "") > 0, "选品清单应保留"
print("   ✔ 9月记录只剩 已发邮件+报价+选品清单")

print("\n== 6. 校验 ==")
final = db.get_all()
by_ident = {}
for r in final:
    m = str(r.get("plan_month") or "").strip()
    by_ident[(r.get("channel_id"), m)] = r
tpl_pairs = {(cid, str(raw.get("plan_month") or "").strip())
             for raw, cid in plan}
missing = tpl_pairs - set(by_ident)
assert not missing, f"缺失: {missing}"
print(f"   ✔ 模板 42 个(频道,月份)全部就位")

h7 = by_ident[(habom_cid, "2026-07")]
assert h7.get("stage") == "已完成" and len(h7.get("videos") or []) == 3
assert int(h7.get("price") or 0) == 500000
h8 = by_ident[(habom_cid, "2026-08")]
assert (h8.get("audit_status") or "") == "已通过"
l7 = by_ident[(ino_cid, "2026-07")]
assert l7.get("stage") == "已完成" and int(l7.get("price") or 0) == 300000
assert len(l7.get("videos") or []) == 1
assert (l7.get("category") or "") == "네일"
l8 = by_ident[(ino_cid, "2026-08")]
assert not (l8.get("video_link") or "") and int(l8.get("price") or 0) == 400000
print("   ✔ 하봄 7月闭环(3视频)/8月审核通过/9月干净；릴리 7月闭环、이노 8月在途")
print(f"   总记录数: {len(all_rows)} → {len(final)}")
print("\n迁移完成 ✅")
