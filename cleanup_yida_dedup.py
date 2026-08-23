#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 宜搭底库去重清理脚本（本地运行版）

背景：同一(频道+月份)被重复导入产生 29 组重复、75 条多余记录，
导致网站出现重复卡片、看起来混乱。本脚本按(频道+月份)去重，
每个组只保留 1 条最完整的记录，删除前先合并被删条目里独有的数据。

三重保险：
  1. 执行前自动全量备份（yida_backup/yida_all_时间戳.json）
  2. 默认 dry-run 只预览不真删，加 --execute 才真正执行
  3. 保留"最全"的一条，被删条目里独有的字段/视频/商品先合并过去，不丢数据

用法（在 kol-bd-module 仓库目录下，先配好凭证）：
  python3 cleanup_yida_dedup.py              # 预览：看准备删什么
  python3 cleanup_yida_dedup.py --execute    # 确认无误后真正执行

凭证配置（二选一）：
  A. 环境变量：export YIDA_ACCESS_KEY_ID=... YIDA_ACCESS_KEY_SECRET=... YIDA_SYSTEM_TOKEN=...
  B. 仓库里有 yida_config_local.py（YIDA_CONFIG 字典）
"""
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yida_bd_database import YidaBDDB, FIELD_IDS
from yts_yida_store import _cfg
from alibabacloud_aliding20230426 import models as aliding_models


def delete_instance(db, instance_id):
    """按实例ID精确删除（不能用 db.delete——那个按频道ID删第一条，会误删）"""
    request = aliding_models.DeleteFormDataRequest(
        app_type=db.app_type,
        system_token=db.system_token,
        form_instance_id=instance_id,
        language="zh_CN",
    )
    db._client.delete_form_data_with_options(
        request, db._headers("DeleteFormData"), db._runtime)

# 合并时跳过的字段（身份/系统字段，不能从被删条目覆盖）
SKIP_MERGE = {"channel_id", "channel_name", "channel_url", "form_instance_id",
              "plan_month", "created_at", "updated_at"}
# 列表型字段单独合并（按唯一键去重合并）
LIST_FIELDS = {"videos": "video_url", "products": "pid", "audit_log": None}


def is_empty(v):
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def keeper_score(rec):
    """完整性评分：子表行数 + 有值的标量字段数"""
    score = 0
    for lf in ("videos", "products", "audit_log"):
        score += len(rec.get(lf) or []) * 3
    for code in FIELD_IDS:
        if code in SKIP_MERGE or code in LIST_FIELDS:
            continue
        if not is_empty(rec.get(code)):
            score += 1
    return score


def main():
    execute = "--execute" in sys.argv
    cfg = _cfg()
    if not cfg.get("access_key_id") or not cfg.get("system_token"):
        print("❌ 缺少宜搭凭证。请设置环境变量 YIDA_ACCESS_KEY_ID / "
              "YIDA_ACCESS_KEY_SECRET / YIDA_SYSTEM_TOKEN，或准备 yida_config_local.py")
        sys.exit(1)

    db = YidaBDDB(**cfg)
    print("== 1. 拉取全量数据 ==")
    rows = db.get_all()
    print(f"   共 {len(rows)} 条记录")

    # 分组：(频道ID, 月份)
    groups = {}
    for r in rows:
        key = (r.get("channel_id") or "", str(r.get("plan_month") or "").strip())
        groups.setdefault(key, []).append(r)
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    total_extra = sum(len(v) - 1 for v in dup_groups.values())
    print(f"   重复组 {len(dup_groups)} 个，多余记录 {total_extra} 条，"
          f"清理后应为 {len(rows) - total_extra} 条")
    if not dup_groups:
        print("✅ 没有重复，无需清理")
        return

    # 备份
    os.makedirs("yida_backup", exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M")
    bk = f"yida_backup/yida_all_{ts}_pre_dedup.json"
    with open(bk, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f"== 2. 已备份 {len(rows)} 条 → {bk} ==")

    # 计算每组的保留/删除/合并计划
    plan = []  # (keeper, [dups], merge_patch)
    for key, recs in dup_groups.items():
        recs_sorted = sorted(recs, key=keeper_score, reverse=True)
        keeper = recs_sorted[0]
        dups = recs_sorted[1:]
        # 合并：被删条目里有、保留条目里空的字段 → 补到保留条目
        patch = {}
        for d in dups:
            for code in FIELD_IDS:
                if code in SKIP_MERGE or code in LIST_FIELDS:
                    continue
                if is_empty(keeper.get(code)) and not is_empty(d.get(code)):
                    patch[code] = d[code]
            # 视频/商品/审核记录按唯一键合并
            for lf, uk in (("videos", "video_url"), ("products", "pid")):
                have = {(x.get(uk) or "") for x in (keeper.get(lf) or [])}
                extra = [x for x in (d.get(lf) or [])
                         if (x.get(uk) or "") and x.get(uk) not in have]
                if extra:
                    patch.setdefault(lf, list(keeper.get(lf) or []))
                    patch[lf].extend(extra)
            # 审核记录：保留条目没有而重复条目有 → 补齐
            if not (keeper.get("audit_log") or []) and (d.get("audit_log") or []):
                patch["audit_log"] = list(d["audit_log"])
        plan.append((keeper, dups, patch))

    # 打印预览
    print("\n== 3. 清理计划预览 ==")
    for keeper, dups, patch in sorted(plan, key=lambda p: -len(p[1])):
        name = keeper.get("channel_name") or keeper.get("channel_id")
        month = str(keeper.get("plan_month") or "").strip() or "(无月份)"
        print(f"\n  {name} | {month} | 保留{keeper_score(keeper)}分的一条，删 {len(dups)} 条")
        print(f"    保留: inst={keeper.get('form_instance_id')}")
        for d in dups:
            print(f"    删除: inst={d.get('form_instance_id')} "
                  f"(分数{keeper_score(d)})")
        if patch:
            keys = [k for k in patch if k not in LIST_FIELDS]
            lists = [k for k in patch if k in LIST_FIELDS]
            print(f"    合并进保留条目: 字段{keys or '无'} + 子表{lists or '无'}")

    if not execute:
        print(f"\n👆 以上是预览（未执行任何删除）。确认无误后运行：")
        print(f"   python3 cleanup_yida_dedup.py --execute")
        return

    # 真正执行
    print("\n== 4. 开始执行清理 ==")
    ok, fail = 0, []
    for keeper, dups, patch in plan:
        inst = keeper.get("form_instance_id")
        try:
            if patch:
                db.update_instance(inst, patch)
                time.sleep(0.3)
            for d in dups:
                delete_instance(db, d.get("form_instance_id"))
                time.sleep(0.3)
            ok += 1
            print(f"   ✅ {keeper.get('channel_name')} 清理完成（删 {len(dups)} 条）")
        except Exception as e:
            fail.append((keeper.get("channel_name"), str(e)[:100]))
            print(f"   ❌ {keeper.get('channel_name')} 失败: {str(e)[:100]}")

    # 验证
    print("\n== 5. 清理后验证 ==")
    final = db.get_all()
    groups2 = {}
    for r in final:
        key = (r.get("channel_id") or "", str(r.get("plan_month") or "").strip())
        groups2.setdefault(key, []).append(r)
    still_dup = {k: v for k, v in groups2.items() if len(v) > 1}
    print(f"   清理后记录数: {len(rows)} → {len(final)}")
    print(f"   剩余重复组: {len(still_dup)} 个")
    print(f"   成功 {ok} 组，失败 {len(fail)} 组")
    if fail:
        print("   失败明细:", fail)
    print(f"\n🎉 清理完成。如需回滚，备份在 {bk}")


if __name__ == "__main__":
    main()
