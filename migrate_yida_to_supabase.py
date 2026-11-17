#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宜搭 → Supabase 一次性搬家脚本（Phase 1 · 换库）

用法（本机跑，不进 Streamlit Cloud；只在切换前执行一次）：
    cd kol-bd-module
    python3 migrate_yida_to_supabase.py --dry-run     # 只导出+预览不写库
    python3 migrate_yida_to_supabase.py               # 正式搬家

流程：
    1) 全表读宜搭 → 落地备份 JSON (yida_backup_YYYYMMDD_HHMM.json)
    2) 结构转换（把宜搭借用的遗留字段拆成独立列：ad_auth→ad_needed, status→ad_done）
    3) 打印行数 + 抽样 diff，等用户回车确认
    4) POST merge 到 Supabase public.collabs（on_conflict=channel_id,plan_month）
    5) 复核 Supabase 端行数 ≥ 宜搭端行数，打印成功。若失败可反复重跑（幂等）

前置：
    已在 Supabase SQL Editor 跑过 schema_supabase.sql
    Secrets/env 已配 YIDA_ACCESS_KEY_ID / YIDA_ACCESS_KEY_SECRET / YIDA_SYSTEM_TOKEN
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

import requests

# --- 让脚本无论从哪儿跑都能 import 同目录模块 ------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from yida_bd_database import YidaBDDB  # noqa: E402


def _yida_cfg():
    cfg = {
        "access_key_id":     os.environ.get("YIDA_ACCESS_KEY_ID", ""),
        "access_key_secret": os.environ.get("YIDA_ACCESS_KEY_SECRET", ""),
        "app_type":          "APP_N85O3OPKB9OO52S4KCTD",
        "system_token":      os.environ.get("YIDA_SYSTEM_TOKEN", ""),
        "form_uuid":         "FORM-2A64DBB4851A4301BAA4C0A5C39E752DHXL0",
        "account_id":        "550448",
    }
    if not cfg["access_key_id"]:
        try:
            from yida_config_local import YIDA_CONFIG as local  # type: ignore
            cfg.update(local)
        except ImportError:
            pass
    return cfg


def _supa_cfg():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        try:
            from yida_config_local import SUPABASE_CONFIG as local  # type: ignore
            url = url or local.get("url", "")
            key = key or local.get("key", "")
        except ImportError:
            pass
    if not url:
        import yts_roster as R
        url, key = R.SUPABASE_URL, R.SUPABASE_KEY
    return url.rstrip("/"), key


# 宜搭原始记录 → Supabase 行；只保留 schema 里存在的列，
# 并把借用的遗留字段（ad_auth/status）拆成真正的布尔列
_KEEP_COLS = {
    "channel_id", "plan_month", "channel_name", "channel_url",
    "category", "sales_category", "subscribers", "email", "recruiter",
    "stage", "email_status",
    "guideline_status", "contract_status", "gmc_status",
    "product_list", "order_status", "shoot_status",
    "submit_deadline", "submit_actual",
    "video_link", "recheck_video_url", "audit_status",
    "video_views", "video_likes", "video_comments", "total_views",
    "product_link", "product_views", "ctr", "orders", "conversion_rate",
    "gmv", "price",
    "group_link", "settlement", "settlement_note", "notes",
    "audit_log", "videos", "products",
}
_TEXT = {"channel_name", "channel_url", "category", "sales_category",
         "email", "recruiter", "stage", "email_status",
         "guideline_status", "contract_status", "gmc_status",
         "product_list", "order_status", "shoot_status",
         "submit_deadline", "submit_actual",
         "video_link", "recheck_video_url", "audit_status",
         "product_link", "group_link", "settlement", "settlement_note", "notes"}
_INT = {"subscribers", "price", "orders", "video_views", "video_likes",
        "video_comments", "product_views", "total_views"}
_NUM = {"gmv", "ctr", "conversion_rate"}
_JSON = {"audit_log", "videos", "products"}


def _s(v):
    return "" if v is None else str(v)


def _i(v):
    try:
        return int(float(v)) if v not in (None, "") else 0
    except Exception:
        return 0


def _f(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except Exception:
        return 0.0


def convert(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if k not in _KEEP_COLS:
            continue
        if k in _JSON:
            out[k] = v if isinstance(v, list) else []
        elif k in _INT:
            out[k] = _i(v)
        elif k in _NUM:
            out[k] = _f(v)
        else:
            out[k] = _s(v)
    # 身份必备
    out.setdefault("channel_id", _s(rec.get("channel_id")))
    out.setdefault("plan_month", _s(rec.get("plan_month")))
    # 遗留借用字段拆列
    out["ad_needed"] = (_s(rec.get("ad_auth")) == "Y")
    out["ad_done"] = (_s(rec.get("status")) == "Y")
    out.setdefault("deleted", False)
    return out


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只导出备份并预览转换结果，不写入 Supabase")
    ap.add_argument("--yes", action="store_true",
                    help="跳过回车确认（供 CI 用）")
    ap.add_argument("--batch", type=int, default=100,
                    help="每批 upsert 的行数（默认 100）")
    args = ap.parse_args()

    t0 = time.time()
    ycfg = _yida_cfg()
    if not ycfg["access_key_id"] or not ycfg["access_key_secret"]:
        sys.exit("❌ 缺 YIDA_ACCESS_KEY_ID / YIDA_ACCESS_KEY_SECRET（环境变量或 "
                 "yida_config_local.py）")
    scfg_url, scfg_key = _supa_cfg()
    if not scfg_url or not scfg_key:
        sys.exit("❌ 缺 SUPABASE_URL / SUPABASE_KEY")
    headers = {"apikey": scfg_key, "Authorization": f"Bearer {scfg_key}",
               "Content-Type": "application/json",
               "Prefer": "return=minimal,merge=duplicates"}

    print(f"[1/5] 拉宜搭全表 ...  (~10-20s，正常)")
    db = YidaBDDB(**ycfg)
    raw = db.get_all()
    print(f"      宜搭行数 = {len(raw)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               f"yida_backup_{stamp}.json")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=1)
    print(f"[2/5] 备份 → {backup_path}")

    print("[3/5] 转换 + 抽样")
    rows = [convert(r) for r in raw]
    rows = [r for r in rows if r.get("channel_id")]   # 空 cid 跳过
    print(f"      有效行数 = {len(rows)}（跳过无 channel_id 的行 {len(raw) - len(rows)}）")

    dup = {}
    for r in rows:
        k = (r["channel_id"], r["plan_month"])
        dup.setdefault(k, 0)
        dup[k] += 1
    conflicts = {k: v for k, v in dup.items() if v > 1}
    if conflicts:
        print(f"      ⚠️ 身份重复(channel_id,plan_month) {len(conflicts)} 组 → merge 会最后写入者胜")

    for sample in rows[:3]:
        print("      样例:", json.dumps(
            {k: sample[k] for k in list(sample)[:6] if k in sample},
            ensure_ascii=False))

    if args.dry_run:
        print("[dry-run] 未写入 Supabase，退出。")
        return

    if not args.yes:
        ans = input("[4/5] 确认写入 Supabase public.collabs? [y/N] ").strip().lower()
        if ans != "y":
            print("已取消。备份文件保留在磁盘上。")
            return

    print("[4/5] 分批 upsert ...")
    total = len(rows)
    for i in range(0, total, args.batch):
        batch = rows[i:i + args.batch]
        r = requests.post(f"{scfg_url}/rest/v1/collabs",
                          params={"on_conflict": "channel_id,plan_month"},
                          headers=headers,
                          data=json.dumps(batch, ensure_ascii=False),
                          timeout=30)
        if r.status_code >= 400:
            sys.exit(f"❌ 批次 {i}-{i+len(batch)} 写入失败: "
                     f"HTTP {r.status_code}: {r.text[:400]}")
        print(f"      {min(i+args.batch, total)}/{total}")

    print("[5/5] 复核 Supabase 端")
    rr = requests.get(f"{scfg_url}/rest/v1/collabs",
                      params={"select": "id"},
                      headers={"apikey": scfg_key,
                               "Authorization": f"Bearer {scfg_key}"},
                      timeout=15)
    rr.raise_for_status()
    supa_n = len(rr.json())
    print(f"      Supabase.collabs 现有行数 = {supa_n}")
    if supa_n < len(rows):
        print(f"      ⚠️ 少于本次转换 {len(rows)} 条，请回查重复身份是否被 merge 覆盖。")
    else:
        print(f"      ✅ 搬家完成，耗时 {time.time()-t0:.1f}s")
    print("下一步：给 kol-bd-module 加 Secrets USE_SUPABASE_STORE=1，"
          "重启 Streamlit Cloud；观察主站/审核站/看板 3-5 分钟；"
          "确认无问题后可删除宜搭表单归档（可选）。")


if __name__ == "__main__":
    main()
