#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 网红管理系统 - 共享数据存储（demo 用本地 JSON 版）

主站与审核网站共用本模块，数据写入同一个 JSON 文件，模拟"两站共享宜搭表"。
接口与 yts_yida_store.YTSStore 完全一致（含分析看板指标字段）。
"""
import json
import os
import uuid
from datetime import datetime

STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yts_demo_data.json")

SEED_POOL = [
    {"id": "UC_demo_001", "name": "뷰티써니", "platform": "YouTube", "followers": 52000,
     "category": "뷰티", "avatar": "", "email": "sunny@example.com", "emailed": True,
     "recruiter": "艾薇李"},
    {"id": "UC_demo_002", "name": "패션왕민준", "platform": "YouTube", "followers": 128000,
     "category": "패션", "avatar": "", "email": "minjun@example.com", "emailed": True,
     "recruiter": "艾薇李"},
    {"id": "UC_demo_003", "name": "홈스토랑", "platform": "YouTube", "followers": 34000,
     "category": "홈", "avatar": "", "email": "home@example.com", "emailed": True,
     "recruiter": "艾薇李"},
    {"id": "UC_demo_004", "name": "펫로그댕이", "platform": "YouTube", "followers": 210000,
     "category": "pet", "avatar": "", "email": "pet@example.com", "emailed": True,
     "recruiter": "运营A"},
    {"id": "UC_demo_005", "name": "슬기로운자취", "platform": "YouTube", "followers": 18000,
     "category": "홈", "avatar": "", "email": "slg@example.com", "emailed": True,
     "recruiter": "艾薇李"},
    {"id": "UC_demo_006", "name": "데일리메이크업", "platform": "YouTube", "followers": 46000,
     "category": "뷰티", "avatar": "", "email": "daily@example.com", "emailed": True,
     "recruiter": "运营A"},
    {"id": "UC_demo_007", "name": "캠퍼스라이프", "platform": "YouTube", "followers": 9800,
     "category": "학생", "avatar": "", "email": "campus@example.com", "emailed": False,
     "recruiter": "艾薇李"},
    {"id": "UC_demo_008", "name": "멍냥일기", "platform": "YouTube", "followers": 27000,
     "category": "pet", "avatar": "", "email": "mny@example.com", "emailed": False,
     "recruiter": ""},
]


def _base_collab(inf, **over):
    c = {
        "collab_id": inf["id"], "influencer_id": inf["id"], "name": inf["name"],
        "platform": "YouTube", "followers": inf["followers"], "category": inf["category"],
        "email": inf.get("email", ""), "recruiter": inf.get("recruiter", ""),
        "avatar": "", "status": "洽谈中", "follow_time": "2026-08-01 10:00",
        "plan_month": "", "branches": {"guideline": False, "contract": False, "gmc": False},
        "product_list": [], "order_done": False, "received": False,
        "shoot_status": "", "video_url": "", "review_status": "", "review_comment": "",
        "recheck_video_url": "", "uploaded_confirmed": False, "is_closed": False,
        "video_views": 0, "video_likes": 0, "video_comments": 0, "product_views": 0,
        "ctr": 0, "orders": 0, "conversion_rate": 0, "gmv": 0, "price": 0,
        "channel_url": f'https://youtube.com/channel/{inf["id"]}',
        "group_link": "", "submit_deadline": "", "audit_log": [],
    }
    c.update(over)
    return c


def _seed_collabs():
    p = {x["id"]: x for x in SEED_POOL}
    return [
        # 洽谈中
        _base_collab(p["UC_demo_001"], status="洽谈中"),
        _base_collab(p["UC_demo_005"], status="洽谈中"),
        # 履约中 · 三分支进行中
        _base_collab(p["UC_demo_002"], status="履约中", plan_month="2026-08",
                     branches={"guideline": True, "contract": True, "gmc": False},
                     product_list=["https://aliexpress.com/item/1001.html",
                                   "https://aliexpress.com/item/1002.html"]),
        # 履约中 · 拍摄中
        _base_collab(p["UC_demo_003"], status="履约中", plan_month="2026-08",
                     branches={"guideline": True, "contract": True, "gmc": True},
                     order_done=True, received=True, shoot_status="拍摄中"),
        # 待审核
        _base_collab(p["UC_demo_004"], status="履约中", plan_month="2026-08",
                     branches={"guideline": True, "contract": True, "gmc": True},
                     order_done=True, received=True, shoot_status="已完成",
                     video_url="https://youtube.com/watch?v=demo004",
                     review_status="待审核"),
        # 已驳回（待运营复审）
        _base_collab(p["UC_demo_006"], status="履约中", plan_month="2026-07",
                     branches={"guideline": True, "contract": True, "gmc": True},
                     order_done=True, received=True, shoot_status="已完成",
                     video_url="https://youtube.com/watch?v=demo006",
                     review_status="已驳回", review_comment="口播未提及折扣码，请补拍结尾",
                     audit_log=[{"audit_date": "2026-07-28", "audit_result": "未通过",
                                 "audit_opinion": "口播未提及折扣码，请补拍结尾"}]),
        # 已闭环（带指标）
        _base_collab({**p["UC_demo_004"], "id": "UC_demo_009", "name": "소확행다이소"},
                     status="履约中", plan_month="2026-07",
                     branches={"guideline": True, "contract": True, "gmc": True},
                     order_done=True, received=True, shoot_status="已完成",
                     video_url="https://youtube.com/watch?v=demo009",
                     review_status="已通过", uploaded_confirmed=True, is_closed=True,
                     video_views=182000, video_likes=9400, video_comments=312,
                     product_views=26000, ctr=4.2, orders=356,
                     conversion_rate=1.4, gmv=4820, price=300,
                     audit_log=[{"audit_date": "2026-07-20", "audit_result": "已通过",
                                 "audit_opinion": "审核通过"}]),
    ]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class YTSStore:
    def __init__(self, path=STORE_FILE):
        self.path = path
        if not os.path.exists(path):
            self._save({"pool": SEED_POOL, "collabs": _seed_collabs()})

    def _load(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, ensure_ascii=False, indent=1, fp=f)

    # ---------------- 挖掘模块 ----------------
    def list_pool(self):
        return self._load()["pool"]

    def add_influencer(self, rec):
        """新增网红到挖掘池（demo 本地版）"""
        data = self._load()
        rec = dict(rec)
        rec["id"] = rec.get("channel_id") or ("UC_" + uuid.uuid4().hex[:8])
        rec["name"] = rec.get("channel_name", "")
        rec["platform"] = "YouTube"
        rec["followers"] = rec.get("subscribers", 0)
        rec["category"] = rec.get("category", "")
        rec["avatar"] = ""
        rec["email"] = rec.get("email", "")
        rec["recruiter"] = rec.get("recruiter", "")
        rec["emailed"] = False
        if not any(p["id"] == rec["id"] for p in data["pool"]):
            data["pool"].append(rec)
        self._save(data)

    def import_influencers(self, records: list) -> int:
        count = 0
        for rec in records:
            if rec.get("channel_id"):
                self.add_influencer(rec)
                count += 1
        return count

    def mark_emailed(self, inf_id):
        """标记已发邮件 → 自动回流到活动模块左栏（洽谈中），按 id 去重"""
        data = self._load()
        for inf in data["pool"]:
            if inf["id"] == inf_id:
                inf["emailed"] = True
        exists = any(c["influencer_id"] == inf_id for c in data["collabs"])
        if not exists:
            inf = next(i for i in data["pool"] if i["id"] == inf_id)
            data["collabs"].append(_base_collab(inf, status="洽谈中",
                                                follow_time=_now()))
        self._save(data)

    # ---------------- 活动模块 ----------------
    def list_negotiating(self):
        return [c for c in self._load()["collabs"] if c["status"] == "洽谈中"]

    def list_fulfilling(self):
        return [c for c in self._load()["collabs"] if c["status"] == "履约中"]

    def list_all(self):
        return self._load()["collabs"]

    def confirm_collab(self, collab_id, plan_month):
        data = self._load()
        for c in data["collabs"]:
            if c["collab_id"] == collab_id:
                c["status"] = "履约中"
                c["plan_month"] = plan_month
        self._save(data)

    def get_collab(self, collab_id):
        for c in self._load()["collabs"]:
            if c["collab_id"] == collab_id:
                return c
        return None

    def _update(self, collab_id, patch):
        data = self._load()
        for c in data["collabs"]:
            if c["collab_id"] == collab_id:
                c.update(patch)
        self._save(data)

    # ---------------- 履约：三分支 ----------------
    def set_branch(self, collab_id, branch, done):
        c = self.get_collab(collab_id)
        branches = dict(c["branches"])
        branches[branch] = done
        self._update(collab_id, {"branches": branches})

    def branches_all_done(self, collab_id):
        c = self.get_collab(collab_id)
        return all(c["branches"].values())

    def set_products(self, collab_id, product_list):
        self._update(collab_id, {"product_list": product_list})

    # ---------------- 下单→收货→拍摄 ----------------
    def mark_order(self, collab_id):
        self._update(collab_id, {"order_done": True})

    def mark_received(self, collab_id):
        self._update(collab_id, {"received": True})

    def mark_shoot(self, collab_id, status):
        self._update(collab_id, {"shoot_status": status})

    # ---------------- 提交审核（推审核网站） ----------------
    def submit_review(self, collab_id, video_url):
        self._update(collab_id, {"video_url": video_url, "review_status": "待审核",
                                 "review_comment": ""})

    # ---------------- 审核网站 ----------------
    def list_pending_reviews(self):
        return [c for c in self._load()["collabs"] if c["review_status"] == "待审核"]

    def list_review_history(self):
        return [c for c in self._load()["collabs"]
                if c["review_status"] in ("已通过", "已驳回", "复审中", "复审通过")]

    def review_pass(self, collab_id, note=""):
        c = self.get_collab(collab_id)
        log = list(c.get("audit_log") or [])
        log.append({"audit_date": datetime.now().strftime("%Y-%m-%d"),
                    "audit_result": "已通过", "audit_opinion": note or "审核通过"})
        self._update(collab_id, {"review_status": "已通过", "review_comment": note,
                                 "audit_log": log})

    def review_reject(self, collab_id, reason):
        c = self.get_collab(collab_id)
        log = list(c.get("audit_log") or [])
        log.append({"audit_date": datetime.now().strftime("%Y-%m-%d"),
                    "audit_result": "未通过", "audit_opinion": reason})
        self._update(collab_id, {"review_status": "已驳回", "review_comment": reason,
                                 "audit_log": log})

    # ---------------- 复审（运营操作，可循环） ----------------
    def start_recheck(self, collab_id, new_video_url):
        self._update(collab_id, {"review_status": "复审中",
                                 "recheck_video_url": new_video_url})

    def recheck_pass(self, collab_id):
        c = self.get_collab(collab_id)
        log = list(c.get("audit_log") or [])
        log.append({"audit_date": datetime.now().strftime("%Y-%m-%d"),
                    "audit_result": "已通过", "audit_opinion": "复审通过"})
        self._update(collab_id, {"review_status": "复审通过", "audit_log": log})

    def recheck_reject(self, collab_id, reason):
        """复审仍不合格 → 回到已驳回，要求网红继续改"""
        c = self.get_collab(collab_id)
        log = list(c.get("audit_log") or [])
        log.append({"audit_date": datetime.now().strftime("%Y-%m-%d"),
                    "audit_result": "未通过", "audit_opinion": f"复审驳回：{reason}"})
        self._update(collab_id, {"review_status": "已驳回", "review_comment": reason,
                                 "recheck_video_url": "", "audit_log": log})

    # ---------------- 上传确认 → 闭环（绿光） ----------------
    def confirm_uploaded(self, collab_id):
        self._update(collab_id, {"uploaded_confirmed": True, "is_closed": True})
