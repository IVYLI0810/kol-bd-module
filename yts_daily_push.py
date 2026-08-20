#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTS 每日定时推送（由 GitHub Actions 定时运行，见 .github/workflows/daily-push.yml）

每天 10:00 / 16:00（北京时间）：
  1) 待审核清单 → 群机器人发到审核群 @对接同学
  2) 待投放清单 → 钉钉个人待办直发给投放负责人

手动运行：python3 yts_daily_push.py            （真实发送）
          python3 yts_daily_push.py --dry-run  （只打印清单不发送）
"""
import os
import sys

from yida_bd_database import YidaBDDB
import yts_notify as N

# 宜搭应用常量（与 yts_yida_store._cfg 保持一致）
APP_TYPE = "APP_N85O3OPKB9OO52S4KCTD"
# system_token 从 Secrets 读取，不再硬编码在代码里（安全整改 2026-08-21）
SYSTEM_TOKEN = os.environ.get("YIDA_SYSTEM_TOKEN", "")
FORM_UUID = "FORM-2A64DBB4851A4301BAA4C0A5C39E752DHXL0"
ACCOUNT_ID = "550448"


def _cfg():
    cfg = {
        "access_key_id": os.environ.get("YIDA_ACCESS_KEY_ID", ""),
        "access_key_secret": os.environ.get("YIDA_ACCESS_KEY_SECRET", ""),
        "app_type": APP_TYPE,
        "system_token": SYSTEM_TOKEN,
        "form_uuid": FORM_UUID,
        "account_id": ACCOUNT_ID,
    }
    if not cfg["access_key_id"]:
        try:
            from yida_config_local import YIDA_CONFIG as local
            cfg.update(local)
        except ImportError:
            pass
    return cfg


def collect(db):
    """拉全量数据，拆出待审核 / 待投放两份清单"""
    rows = db.get_all()
    pending_review = [(r.get("channel_name") or r.get("channel_id") or "?",
                       r.get("video_link") or "")
                      for r in rows
                      if (r.get("audit_status") or "") == "待审核"]
    pending_ad = [(r.get("channel_name") or r.get("channel_id") or "?",
                   r.get("channel_url") or "")
                  for r in rows
                  if (r.get("ad_auth") or "") == "Y"
                  and (r.get("status") or "") != "Y"]
    return pending_review, pending_ad


def main():
    dry = "--dry-run" in sys.argv
    db = YidaBDDB(**_cfg())
    pending_review, pending_ad = collect(db)
    print(f"待审核 {len(pending_review)} 条 / 待投放 {len(pending_ad)} 条")

    if dry:
        print("--- 待审核 ---")
        for nm, url in pending_review:
            print(f"  {nm} | {url}")
        print("--- 待投放 ---")
        for nm, url in pending_ad:
            print(f"  {nm} | {url}")
        return

    liaison = os.environ.get("DINGTALK_LIAISON", "") or "Minjeong"
    ok1, m1 = N.notify_daily_review(pending_review, reviewer=liaison)
    print(f"[待审核推送] ok={ok1} | {m1}")
    ok2, m2 = N.notify_daily_ad(pending_ad)
    print(f"[待投放推送] ok={ok2} | {m2}")
    if not (ok1 and ok2):
        sys.exit(1)


if __name__ == "__main__":
    main()
