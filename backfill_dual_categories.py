# -*- coding: utf-8 -*-
"""
宜搭双垂类全量回填：存量记录一次性对齐挖掘站新版口径
====================================================================
背景：2026-08-24 起宜搭垂类拆成两个字段——
  · 内容垂类（拍什么）= 原「垂类」下拉 selectField_msn2qhnj ← 挖掘站 content_category
  · 带货垂类（卖什么）= 新文本字段 textField_mt6cwpmm      ← 挖掘站 category
同步函数已改为「全覆盖」，但只管以后点同步按钮；存量记录靠本脚本刷一遍。

逻辑：
1. 拉宜搭全部记录（每条月份行单独对齐）
2. 拉 kol-finder 公共库 channel_id → (内容垂类, 带货垂类)
3. 库里有值且与宜搭不同 → 覆盖；库里没这个频道 → 不动
4. 带货垂类字段若在宜搭表单里还没建好，数据层会自动降级只写内容垂类，
   等字段建好后再跑一次本脚本即可补齐（可重复执行，幂等）

用法：
  python3 backfill_dual_categories.py            # 预览
  python3 backfill_dual_categories.py --apply    # 真正执行
"""

import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yida_bd_database import YidaBDDB
from yida_config_local import YIDA_CONFIG

# kol-finder 公共库（与 yts_roster.py 相同的只读地址）
SUPABASE_URL = "https://webjrwzorxxlqrcrrnro.supabase.co"
SUPABASE_KEY = "sb_publishable_eUDicGLoUiNhPO04S6iz8g_UX_SkSCH"


def fetch_kol_finder() -> dict:
    """channel_id → {"content": 内容垂类, "commerce": 带货垂类}"""
    out = {}
    off = 0
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/influencers",
            params={"select": "channel_id,category,content_category",
                    "limit": 1000, "offset": off},
            headers=headers, timeout=30)
        r.raise_for_status()
        batch = r.json() or []
        for row in batch:
            cid = (row.get("channel_id") or "").strip()
            if cid:
                out[cid] = {
                    "content": (row.get("content_category") or "").strip(),
                    "commerce": (row.get("category") or "").strip(),
                }
        off += len(batch)
        if len(batch) < 1000:
            break
    return out


def main():
    apply_mode = "--apply" in sys.argv

    print("1/3 读取宜搭底库…")
    db = YidaBDDB(**YIDA_CONFIG)
    yida_rows = db.get_all()
    print(f"    宜搭共 {len(yida_rows)} 条记录（含多月行）")

    print("2/3 读取 kol-finder 公共库…")
    kf = fetch_kol_finder()
    print(f"    公共库共 {len(kf)} 位网红")

    plan, same, not_in_lib = [], 0, []
    dist_c, dist_m = {}, {}
    for rec in yida_rows:
        cid = (rec.get("channel_id") or "").strip()
        name = rec.get("channel_name", "") or cid[:12]
        cur_c = (rec.get("category") or "").strip()
        cur_m = (rec.get("sales_category") or "").strip()
        dist_c[cur_c or "(空)"] = dist_c.get(cur_c or "(空)", 0) + 1
        dist_m[cur_m or "(空)"] = dist_m.get(cur_m or "(空)", 0) + 1

        lib = kf.get(cid)
        if not lib:
            not_in_lib.append(f"{name}（内容={cur_c or '空'}，带货={cur_m or '空'}）")
            continue
        patch = {}
        if lib["content"] and lib["content"] != cur_c:
            patch["category"] = lib["content"]
        if lib["commerce"] and lib["commerce"] != cur_m:
            patch["sales_category"] = lib["commerce"]
        if not patch:
            same += 1
            continue
        plan.append({
            "instance_id": rec.get("form_instance_id"),
            "name": name,
            "patch": patch,
            "old": (cur_c or "空", cur_m or "空"),
        })

    print("\n宜搭当前「内容垂类」取值分布：")
    for c, n in sorted(dist_c.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {c}: {n}")
    print("宜搭当前「带货垂类」取值分布：")
    for c, n in sorted(dist_m.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {c}: {n}")

    print(f"\n回填计划：改 {len(plan)} 条、已一致 {same} 条、"
          f"库里查不到不动 {len(not_in_lib)} 条")
    for p in plan[:30]:
        new = p["patch"]
        print(f"  {p['name'][:22]:22s} | 内容 {p['old'][0]} → "
              f"{new.get('category', '不动')} | 带货 {p['old'][1]} → "
              f"{new.get('sales_category', '不动')}")
    if len(plan) > 30:
        print(f"  … 另有 {len(plan) - 30} 条")
    if not_in_lib:
        print(f"\n以下 {len(not_in_lib)} 条公共库查不到，保持原样（示例前10）：")
        for line in not_in_lib[:10]:
            print(f"  - {line}")

    if not apply_mode:
        print("\n这是预览（dry-run）。确认无误后运行："
              "python3 backfill_dual_categories.py --apply")
        return

    print("\n3/3 执行回填…")
    ok, fail = 0, 0
    for p in plan:
        try:
            db.update_instance(p["instance_id"], p["patch"])
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  ⚠️ {p['name']} 回填失败：{e}")
    print(f"\n✅ 完成：成功 {ok} 条，失败 {fail} 条")


if __name__ == "__main__":
    main()
