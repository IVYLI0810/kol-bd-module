# -*- coding: utf-8 -*-
"""
带货垂类存量迁移：老记录「重建式」补写
====================================================================
背景：宜搭对「字段加上表单之前就已存在的老记录」，API 更新通道写不进
新字段（静默丢弃）；但新建记录（SaveFormData）一切正常。
所以把需要补带货垂类的老记录整条重建：
    原样读出全部数据 → 新建一条一模一样的记录并带上带货垂类
    → 逐字段比对无误后 → 删除旧记录
安全：
  · 执行前先全量备份到 backups/ 目录（含旧字段 mt6cwpmm 里的存量值）
  · 每条记录「新建成功 + 比对通过」才会删旧；任何一步失败都保留旧记录
  · 带货垂类取值优先级：kol-finder 公共库 > 旧字段 mt6cwpmm 存量值

用法：
  python3 migrate_rebuild_sales_category.py            # 预览
  python3 migrate_rebuild_sales_category.py --apply    # 真正执行
"""

import json
import os
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yida_bd_database import YidaBDDB, FIELD_IDS
from yida_config_local import YIDA_CONFIG

OLD_COMMERCE_FID = "textField_mt6cwpmm"   # 旧带货垂类字段（已弃用，仅读存量值）

SUPABASE_URL = "https://webjrwzorxxlqrcrrnro.supabase.co"
SUPABASE_KEY = "sb_publishable_eUDicGLoUiNhPO04S6iz8g_UX_SkSCH"


def fetch_kol_finder() -> dict:
    out = {}
    off = 0
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/influencers",
            params={"select": "channel_id,category", "limit": 1000, "offset": off},
            headers=headers, timeout=30)
        r.raise_for_status()
        batch = r.json() or []
        for row in batch:
            cid = (row.get("channel_id") or "").strip()
            if cid:
                out[cid] = (row.get("category") or "").strip()
        off += len(batch)
        if len(batch) < 1000:
            break
    return out


def raw_all_instances(db):
    """分页拉全部原始实例（未解析，含所有字段原始值）"""
    items, page = [], 1
    while True:
        data = db._search_page({}, page=page, size=100)
        rows = data.get("Data") or data.get("data") or []
        items.extend(rows)
        if len(rows) < 100:
            break
        page += 1
    return items


def norm(v):
    """数值宽松比较；None 与空串视为相同"""
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 4)
    return v


def scalar_eq(a, b) -> bool:
    """标量宽松相等：数值按浮点比；空/None 与 0 视为等价
    （宜搭子表数字字段读回时会把 0 吞成空）"""
    na, nb = norm(a), norm(b)
    if na == nb:
        return True
    emptyish = {"", 0.0}
    return na in emptyish and nb in emptyish


def rec_equal(a: dict, b: dict) -> list:
    """比较两条解析后记录，返回差异描述列表（空=一致）"""
    diffs = []
    keys = set(a) | set(b)
    for k in keys:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, list) or isinstance(vb, list):
            la, lb = va if isinstance(va, list) else [], vb if isinstance(vb, list) else []
            if len(la) != len(lb):
                diffs.append(f"{k}: 子表行数 {len(la)} != {len(lb)}")
                continue
            for i, (ra, rb) in enumerate(zip(la, lb)):
                for kk in set(ra) | set(rb):
                    if kk.endswith("_id"):
                        continue  # 宜搭读回时给下拉/单选自动附的选项镜像键
                    if not scalar_eq(ra.get(kk), rb.get(kk)):
                        diffs.append(f"{k}[{i}].{kk}: {ra.get(kk)!r} != {rb.get(kk)!r}")
        elif not scalar_eq(va, vb):
            diffs.append(f"{k}: {va!r} != {vb!r}")
    return diffs


def main():
    apply_mode = "--apply" in sys.argv
    db = YidaBDDB(**YIDA_CONFIG)

    print("1/4 拉取全部原始实例…")
    raws = raw_all_instances(db)
    print(f"    共 {len(raws)} 条")

    # ---- 备份 ----
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups"),
                exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "backups", f"yida_full_backup_{stamp}.json")
    with open(bak_path, "w", encoding="utf-8") as f:
        json.dump(raws, f, ensure_ascii=False, indent=1)
    print(f"    已备份 → {bak_path}")

    # 解析 + 旧字段存量值
    recs = [db._from_instance(r) for r in raws]
    old_val_by_inst = {}
    for r in raws:
        fid = r.get("FormInstanceId") or r.get("formInstanceId")
        old_val_by_inst[fid] = ((r.get("FormData") or {}).get(OLD_COMMERCE_FID) or "").strip()

    print("2/4 拉取 kol-finder 公共库…")
    lib = fetch_kol_finder()
    print(f"    公共库 {len(lib)} 位网红")

    print("3/4 生成迁移计划…")
    plan, skip_ok, skip_none = [], 0, 0
    for rec in recs:
        iid = rec.get("form_instance_id")
        cid = (rec.get("channel_id") or "").strip()
        cur = (rec.get("sales_category") or "").strip()
        target = lib.get(cid, "") or old_val_by_inst.get(iid, "")
        if not target:
            skip_none += 1
            continue
        if target == cur:
            skip_ok += 1
            continue
        plan.append({"rec": rec, "iid": iid, "cid": cid,
                     "name": rec.get("channel_name") or cid[:12],
                     "month": rec.get("plan_month") or "",
                     "cur": cur, "target": target,
                     "src": "公共库" if lib.get(cid) else "旧字段存量"})

    print(f"    需迁移 {len(plan)} 条 | 已一致 {skip_ok} | 无值不动 {skip_none}")
    for p in plan[:25]:
        print(f"      {p['name'][:20]:20s} {p['month']:7s} | "
              f"{p['cur'] or '空'} → {p['target']}（{p['src']}）")
    if len(plan) > 25:
        print(f"      … 另有 {len(plan) - 25} 条")

    if not apply_mode:
        print("\n这是预览。确认后运行：python3 migrate_rebuild_sales_category.py --apply")
        return

    print("4/4 执行迁移（建新 → 比对 → 删旧）…")
    pilot = "--pilot" in sys.argv
    only = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")), "")
    if only:
        plan = [p for p in plan if p["cid"] == only]
        print(f"    【指定模式】只迁移 channel_id={only}")
    elif pilot:
        plan = plan[:1]
        print("    【试点模式】只迁移第 1 条")
    ok, fail = 0, []
    for idx, p in enumerate(plan, 1):
        rec, target = p["rec"], p["target"]
        name = p["name"]
        try:
            # a) 组装新记录数据（去掉实例元信息）
            new_rec = {k: v for k, v in rec.items()
                       if k not in ("form_instance_id", "created_at", "updated_at")}
            new_rec["sales_category"] = target
            form_data = db._to_form_data(new_rec)
            # b) 新建
            db._send_save(form_data)
            # c) 找到新实例（同 channel_id + 同月份下非旧 id 的那条；
            #    搜索索引有延迟，重试几次）
            fresh = []
            for _ in range(5):
                time.sleep(1.2)
                data = db._search_page({FIELD_IDS["channel_id"]: p["cid"]}, size=20)
                rows = data.get("Data") or data.get("data") or []
                fresh = []
                for r in rows:
                    rid = r.get("FormInstanceId") or r.get("formInstanceId")
                    if rid == p["iid"]:
                        continue
                    if (db._from_instance(r).get("plan_month") or "") != p["month"]:
                        continue
                    fresh.append(r)
                if fresh:
                    break
            if len(fresh) != 1:
                fail.append(f"{name}: 新建后找到 {len(fresh)} 条新实例（预期1），保留旧记录")
                continue
            new_inst = fresh[0]
            new_parsed = db._from_instance(new_inst)
            # d) 比对：新实例 vs 「写入内容」的解析结果（天然含截断/类型归一；
            #    实例元信息/时间戳不参与比较）
            _meta = ("form_instance_id", "created_at", "updated_at")
            expect = db._from_instance({"FormData": form_data})
            d1 = rec_equal({k: v for k, v in new_parsed.items() if k not in _meta},
                           {k: v for k, v in expect.items() if k not in _meta})
            if d1:
                fail.append(f"{name}: 新实例与写入内容不符 {d1[:3]}，删除新实例保留旧记录")
                db.delete_instance(new_parsed["form_instance_id"])
                continue
            if (new_parsed.get("sales_category") or "").strip() != target:
                fail.append(f"{name}: 新实例带货垂类读回不符，删除新实例保留旧记录")
                db.delete_instance(new_parsed["form_instance_id"])
                continue
            # e) 删旧
            db.delete_instance(p["iid"])
            time.sleep(0.4)
            data2 = db._search_page({FIELD_IDS["channel_id"]: p["cid"]}, size=20)
            rows2 = data2.get("Data") or data2.get("data") or []
            months = [db._from_instance(r).get("plan_month") or "" for r in rows2]
            if months.count(p["month"]) != 1:
                fail.append(f"{name}: 删旧后月份行数量异常 {months}，请人工检查")
                continue
            ok += 1
            print(f"    [{idx}/{len(plan)}] ✓ {name} {p['month']} → {target}")
        except Exception as e:
            fail.append(f"{name}: 异常 {type(e).__name__}: {str(e)[:120]}（旧记录保留）")

    print(f"\n✅ 迁移完成：成功 {ok} / {len(plan)}")
    if fail:
        print(f"⚠️ 失败 {len(fail)} 条（旧记录均未动）：")
        for line in fail:
            print("  -", line)


if __name__ == "__main__":
    main()
