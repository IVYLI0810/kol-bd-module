#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 网红管理系统 - 宜搭真实数据存储（正式版）

实现与 yts_store.YTSStore 相同的接口，底层改为读写钉钉宜搭，
主站与审核网站共享同一张表，天然"实时同步"。

状态语义（全部由已有字段推导，不新增字段）：
- 洽谈中 = email_status=="已发送" 且 plan_month 为空
- 履约中 = plan_month 非空 且 stage!="已完成"
- 闭环   = stage=="已完成"
- 复审中 = audit_status=="未通过" 且 recheck_video_url 非空
- 复审通过 = audit_status=="已通过" 且 recheck_video_url 非空
"""
import os
import time
from datetime import datetime

import streamlit as st

from yida_bd_database import YidaBDDB


def _cfg():
    """从环境变量（Streamlit Secrets）读取宜搭配置，允许本地 yida_config_local.py 兜底"""
    cfg = {
        "access_key_id": os.environ.get("YIDA_ACCESS_KEY_ID", ""),
        "access_key_secret": os.environ.get("YIDA_ACCESS_KEY_SECRET", ""),
        "app_type": "APP_N85O3OPKB9OO52S4KCTD",
        "system_token": "XE7668C13088ICWHNJPXODYLFX8Y2Y3Z02NSMBT",
        "form_uuid": "FORM-2A64DBB4851A4301BAA4C0A5C39E752DHXL0",
        "account_id": "550448",
    }
    if not cfg["access_key_id"]:
        try:
            from yida_config_local import YIDA_CONFIG as local
            cfg.update(local)
        except ImportError:
            pass
    return cfg


def _today():
    return datetime.now().strftime("%Y-%m-%d")


class YTSStore:
    """与 demo 版 YTSStore 同接口，底层为宜搭（带 60 秒缓存，避免页面卡顿）"""

    CACHE_TTL = 60  # 秒；写操作会 _invalidate 强制刷新

    def __init__(self, db=None):
        self.db = db or YidaBDDB(**_cfg())
        self._cache = {}

    def _all(self):
        now = time.time()
        if "all" not in self._cache or now - self._cache["all"][0] > self.CACHE_TTL:
            with st.spinner("正在同步宜搭数据…"):
                self._cache["all"] = (now, self.db.get_all())
        return self._cache["all"][1]

    def _get(self, channel_id):
        now = time.time()
        key = "one:" + channel_id
        if key not in self._cache or now - self._cache[key][0] > self.CACHE_TTL:
            with st.spinner("正在同步宜搭数据…"):
                self._cache[key] = (now, self.db.get_by_channel_id(channel_id))
        return self._cache[key][1]

    def _invalidate(self):
        self._cache.clear()

    # ---------------- 宜搭记录 -> UI collab 字典 ----------------
    def _to_collab(self, r):
        product_list = r.get("product_list") or ""
        if isinstance(product_list, str):
            product_list = [p.strip() for p in product_list.splitlines() if p.strip()]
        audit_log = r.get("audit_log") or []
        last_comment = audit_log[-1].get("audit_opinion", "") if audit_log else ""
        audit_status = r.get("audit_status") or ""
        recheck_url = r.get("recheck_video_url") or ""
        # 审核状态推导
        if audit_status == "已通过":
            review_status = "复审通过" if recheck_url else "已通过"
        elif audit_status == "未通过":
            review_status = "复审中" if recheck_url else "已驳回"
        else:
            review_status = audit_status or ""
        stage = r.get("stage") or ""
        plan_month = r.get("plan_month") or ""
        status = "履约中" if plan_month else ("洽谈中" if r.get("email_status") == "已发送" else "未回流")
        return {
            "collab_id": r.get("channel_id"),
            "influencer_id": r.get("channel_id"),
            "name": r.get("channel_name") or r.get("channel_id"),
            "platform": "YouTube",
            "followers": r.get("subscribers") or 0,
            "category": r.get("category") or "",
            "email": r.get("email") or "",
            "recruiter": r.get("recruiter") or "",
            "avatar": "",
            "status": status,
            "follow_time": r.get("updated_at") or "",
            "plan_month": plan_month,
            "branches": {
                "guideline": r.get("guideline_status") == "已发送",
                "contract": r.get("contract_status") == "已签",
                "gmc": r.get("gmc_status") == "校验通过",
            },
            "product_list": product_list,
            "order_done": r.get("order_status") in ("已下单", "已收货"),
            "received": r.get("order_status") == "已收货",
            "shoot_status": r.get("shoot_status") or "",
            "video_url": r.get("video_link") or "",
            "review_status": review_status,
            "review_comment": last_comment,
            "recheck_video_url": recheck_url,
            "uploaded_confirmed": stage == "已完成",
            "is_closed": stage == "已完成",
            "stage": stage,
            "email_status": r.get("email_status") or "",
            # ---- 分析看板指标（只读展示） ----
            "video_views": r.get("video_views") or 0,
            "video_likes": r.get("video_likes") or 0,
            "video_comments": r.get("video_comments") or 0,
            "product_views": r.get("product_views") or 0,
            "ctr": r.get("ctr") or 0,
            "orders": r.get("orders") or 0,
            "conversion_rate": r.get("conversion_rate") or 0,
            "gmv": r.get("gmv") or 0,
            "price": r.get("price") or 0,
            "channel_url": r.get("channel_url") or "",
            "group_link": r.get("group_link") or "",
            "submit_deadline": r.get("submit_deadline") or "",
            "audit_log": audit_log,
        }

    def _upd(self, channel_id, patch):
        r = self.db.update(channel_id, patch)
        self._invalidate()
        return r

    # ---------------- 挖掘模块 ----------------
    def list_pool(self):
        """挖掘池 = 所有网红；已回流(已发邮件)的做标记"""
        out = []
        for r in self._all():
            emailed = r.get("email_status") == "已发送"
            out.append({
                "id": r.get("channel_id"),
                "name": r.get("channel_name") or r.get("channel_id"),
                "platform": "YouTube",
                "followers": r.get("subscribers") or 0,
                "category": r.get("category") or "",
                "avatar": "",
                "email": r.get("email") or "",
                "recruiter": r.get("recruiter") or "",
                "emailed": emailed,
            })
        return out

    def add_influencer(self, rec):
        """新增网红（写入宜搭），rec 用代码名字段"""
        rec.setdefault("email_status", "")
        self.db.add(rec)
        self._invalidate()

    def mark_emailed(self, inf_id):
        """标记已发邮件 → 自动进入活动模块左栏（宜搭即单一数据源，天然去重）"""
        self._upd(inf_id, {"email_status": "已发送", "stage": "已发邮件"})

    # ---------------- 活动模块 ----------------
    def list_negotiating(self):
        return [c for c in (self._to_collab(r) for r in self._all())
                if c["status"] == "洽谈中"]

    def list_fulfilling(self):
        return [c for c in (self._to_collab(r) for r in self._all())
                if c["status"] == "履约中"]

    def list_all(self):
        """全部记录（含指标字段），分析看板用"""
        return [self._to_collab(r) for r in self._all()]

    def import_influencers(self, records: list) -> int:
        """批量导入网红（upsert），records 用代码名字段"""
        count = 0
        for rec in records:
            if not rec.get("channel_id"):
                continue
            self.db.add(rec)
            count += 1
        self._invalidate()
        return count

    def confirm_collab(self, collab_id, plan_month):
        self._upd(collab_id, {"plan_month": plan_month, "stage": "已确认"})

    def get_collab(self, collab_id):
        r = self._get(collab_id)
        return self._to_collab(r) if r else None

    # ---------------- 履约：三分支 ----------------
    def set_branch(self, collab_id, branch, done):
        mapping = {
            "guideline": ("guideline_status", "已发送"),
            "contract": ("contract_status", "已签"),
            "gmc": ("gmc_status", "校验通过"),
        }
        field, on = mapping[branch]
        self._upd(collab_id, {field: on if done else ""})

    def branches_all_done(self, collab_id):
        c = self.get_collab(collab_id)
        return c and all(c["branches"].values())

    def set_products(self, collab_id, product_list):
        self._upd(collab_id, {"product_list": "\n".join(product_list)})

    # ---------------- 下单 → 收货 → 拍摄 ----------------
    def mark_order(self, collab_id):
        self._upd(collab_id, {"order_status": "已下单", "stage": "已下单"})

    def mark_received(self, collab_id):
        self._upd(collab_id, {"order_status": "已收货"})

    def mark_shoot(self, collab_id, status):
        self._upd(collab_id, {"shoot_status": status, "stage": "拍摄中"})

    # ---------------- 提交审核 ----------------
    def submit_review(self, collab_id, video_url):
        self._upd(collab_id, {"video_link": video_url, "audit_status": "待审核",
                              "stage": "已交视频", "submit_actual": _today()})

    # ---------------- 审核网站 ----------------
    def list_pending_reviews(self):
        # 复审由运营操作，不出现在审核同学的待审列表
        return [c for c in (self._to_collab(r) for r in self._all())
                if c["review_status"] == "待审核"]

    def list_review_history(self):
        return [c for c in (self._to_collab(r) for r in self._all())
                if c["review_status"] in ("已通过", "已驳回", "复审通过")]

    def review_pass(self, collab_id, note=""):
        self.db.add_audit(collab_id, result="已通过", opinion=note or "审核通过")
        self._upd(collab_id, {"audit_status": "已通过"})

    def review_reject(self, collab_id, reason):
        self.db.add_audit(collab_id, result="未通过", opinion=reason)
        self._upd(collab_id, {"audit_status": "未通过", "stage": "修改中"})

    # ---------------- 复审（运营操作，可循环） ----------------
    def start_recheck(self, collab_id, new_video_url):
        self._upd(collab_id, {"recheck_video_url": new_video_url})

    def recheck_pass(self, collab_id):
        self.db.add_audit(collab_id, result="已通过", opinion="复审通过")
        self._upd(collab_id, {"audit_status": "已通过"})

    def recheck_reject(self, collab_id, reason):
        self.db.add_audit(collab_id, result="未通过", opinion=f"复审驳回：{reason}")
        self._upd(collab_id, {"audit_status": "未通过", "recheck_video_url": ""})

    # ---------------- 上传确认 → 闭环（绿光） ----------------
    def confirm_uploaded(self, collab_id):
        self._upd(collab_id, {"stage": "已完成"})


def get_yts_store():
    """工厂函数：配置了 AK（环境变量或本地配置文件）→ 宜搭真实数据；否则回退本地 demo 数据"""
    cfg = _cfg()
    if cfg.get("access_key_id") and cfg.get("access_key_secret"):
        try:
            return YTSStore(YidaBDDB(**cfg))
        except Exception:
            pass
    from yts_store import YTSStore as DemoStore
    return DemoStore()
