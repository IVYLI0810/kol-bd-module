#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 网红管理系统 - 共享数据存储（demo 用本地 JSON 版）

主站与审核网站共用本模块，数据写入同一个 JSON 文件，模拟"两站共享宜搭表"。
接口与 yts_yida_store.YTSStore 完全一致（含分析看板指标字段）。
"""
import json
import os
import threading
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
    # 多人共用时（Streamlit 单进程多会话）所有实例共享一把可重入锁，
    # 「读-改-写」全程持锁，防止并发操作互相覆盖丢失
    _lock = threading.RLock()

    def __init__(self, path=STORE_FILE):
        self.path = path
        if not os.path.exists(path):
            self._save({"pool": SEED_POOL, "collabs": _seed_collabs()})

    def _load(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data):
        # 原子写：临时文件名带随机后缀再 rename，
        # 防止并发会话写同一固定 .tmp 名互相截断产生半截 JSON
        tmp = f"{self.path}.{uuid.uuid4().hex}.tmp"
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, ensure_ascii=False, indent=1, fp=f)
            os.replace(tmp, self.path)

    def _modify(self, fn):
        """读-改-写原子操作：fn(data) 原地修改数据后落盘。
        全程持锁，10人并发操作不会互相覆盖"""
        with self._lock:
            data = self._load()
            fn(data)
            self._save(data)

    # ---------------- 挖掘模块 ----------------
    def list_pool(self):
        data = self._load()
        stages = {}
        for c in data["collabs"]:
            stages[c["influencer_id"]] = "洽谈中" if c["status"] == "洽谈中" else "已确认"
        out = []
        for inf in data["pool"]:
            out.append({**inf, "stage": stages.get(
                inf["id"], "已发邮件" if inf.get("emailed") else "")})
        return out

    def add_influencer(self, rec, overwrite: bool = False):
        """新增网红到挖掘池（demo 本地版）；已存在的频道ID默认跳过，
        overwrite=True 时按新值更新非空字段（批量导入用）"""
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

        def fn(data):
            existing = next((p for p in data["pool"] if p["id"] == rec["id"]), None)
            if existing is None:
                data["pool"].append(rec)
            elif overwrite:
                for k in ("name", "followers", "category", "email", "recruiter"):
                    if rec.get(k) not in (None, "", 0):
                        existing[k] = rec[k]

        self._modify(fn)

    def import_influencers(self, records: list) -> int:
        """批量导入：upsert 语义（已存在的频道ID按新值更新），计数=实际处理行数"""
        count = 0
        for rec in records:
            if rec.get("channel_id"):
                self.add_influencer(rec, overwrite=True)
                count += 1
        return count

    def import_flow(self, rec: dict) -> dict:
        """流程导入（demo 本地版）：按 channel_id upsert，
        根据进度字段自动落到挖掘池 / 洽谈 / 履约 / 闭环"""
        cid = rec.get("channel_id")

        def fn(data):
            inf = next((p for p in data["pool"] if p["id"] == cid), None)
            if inf is None:
                inf = {"id": cid, "name": rec.get("channel_name") or cid,
                       "platform": "YouTube",
                       "followers": int(rec.get("subscribers") or 0),
                       "category": rec.get("category") or "", "avatar": "",
                       "email": rec.get("email") or "",
                       "recruiter": rec.get("recruiter") or "",
                       "emailed": bool(rec.get("email_status")),
                       "channel_url": rec.get("channel_url") or ""}
                data["pool"].append(inf)
            else:
                for k, v in (("name", rec.get("channel_name")),
                             ("followers", rec.get("subscribers")),
                             ("category", rec.get("category")),
                             ("email", rec.get("email")),
                             ("recruiter", rec.get("recruiter"))):
                    if v not in (None, "", 0):
                        inf[k] = int(v) if k == "followers" else v
                if rec.get("email_status"):
                    inf["emailed"] = True

            stage = rec.get("stage") or ""
            need_collab = stage in ("洽谈中", "已确认", "已完成") \
                or rec.get("plan_month")
            if need_collab:
                collab = next((c for c in data["collabs"]
                               if c["collab_id"] == cid), None)
                if collab is None:
                    collab = _base_collab(inf)
                    if rec.get("channel_url"):
                        collab["channel_url"] = rec["channel_url"]
                    data["collabs"].append(collab)
                if rec.get("plan_month"):
                    collab["plan_month"] = rec["plan_month"]
                if rec.get("price"):
                    collab["price"] = int(rec["price"])
                if stage == "洽谈中":
                    collab["status"] = "洽谈中"
                elif collab["status"] == "洽谈中":
                    collab["status"] = "履约中"
                for bkey, fld in (("guideline", "guideline_status"),
                                  ("contract", "contract_status"),
                                  ("gmc", "gmc_status")):
                    if rec.get(fld):
                        collab["branches"][bkey] = True
                if rec.get("order_status") in ("已下单", "已收货"):
                    collab["order_done"] = True
                if rec.get("order_status") == "已收货":
                    collab["received"] = True
                if rec.get("shoot_status"):
                    collab["shoot_status"] = rec["shoot_status"]
                if rec.get("video_link"):
                    collab["video_url"] = rec["video_link"]
                amap = {"待审核": "待审核", "已通过": "已通过", "未通过": "已驳回"}
                if rec.get("audit_status") in amap:
                    collab["review_status"] = amap[rec["audit_status"]]
                if rec.get("recheck_video_url"):
                    collab["recheck_video_url"] = rec["recheck_video_url"]
                if rec.get("submit_deadline"):
                    collab["submit_deadline"] = rec["submit_deadline"]
                if rec.get("notes"):
                    collab["notes"] = rec["notes"]
                for mk in ("video_views", "video_likes", "video_comments",
                           "product_views", "orders", "gmv"):
                    if rec.get(mk):
                        collab[mk] = rec[mk]
                if stage == "已完成":
                    collab["uploaded_confirmed"] = True
                    collab["is_closed"] = True

        self._modify(fn)
        return rec

    def mark_emailed(self, inf_id):
        """标记已发邮件 → 留在挖掘池（待「标记洽谈中」后才流入活动）"""
        def fn(data):
            for inf in data["pool"]:
                if inf["id"] == inf_id:
                    inf["emailed"] = True
        self._modify(fn)

    def mark_negotiating(self, inf_id):
        """标记洽谈中 → 流入活动模块洽谈栏，按 id 去重"""
        def fn(data):
            exists = any(c["influencer_id"] == inf_id for c in data["collabs"])
            if not exists:
                inf = next(i for i in data["pool"] if i["id"] == inf_id)
                data["collabs"].append(_base_collab(inf, status="洽谈中",
                                                    follow_time=_now()))
        self._modify(fn)

    # ---------------- 活动模块 ----------------
    def list_negotiating(self):
        return [c for c in self._load()["collabs"] if c["status"] == "洽谈中"]

    def list_fulfilling(self):
        return [c for c in self._load()["collabs"] if c["status"] == "履约中"]

    def list_all(self):
        return self._load()["collabs"]

    def confirm_collab(self, collab_id, plan_month, price=0):
        def fn(data):
            for c in data["collabs"]:
                if c["collab_id"] == collab_id:
                    c["status"] = "履约中"
                    c["plan_month"] = plan_month
                    c["price"] = int(price or 0)
        self._modify(fn)

    def get_collab(self, collab_id):
        for c in self._load()["collabs"]:
            if c["collab_id"] == collab_id:
                return c
        return None

    def _update(self, collab_id, patch):
        def fn(data):
            for c in data["collabs"]:
                if c["collab_id"] == collab_id:
                    c.update(patch)
        self._modify(fn)

    # ---------------- 编辑基本信息（demo 本地版） ----------------
    EDIT_FIELDS = ("price", "plan_month", "email", "channel_url",
                   "group_link", "submit_deadline", "notes")

    def update_info(self, collab_id, fields: dict):
        patch = {}
        for k, v in fields.items():
            if k not in self.EDIT_FIELDS:
                continue
            v = "" if v is None else str(v).strip()
            if k == "price":
                try:
                    patch["price"] = int(float(v)) if v else 0
                except ValueError:
                    continue
            else:
                patch[k] = v
        if patch:
            self._update(collab_id, patch)

    def update_video_link(self, collab_id, new_url: str):
        """待审核状态下更换初审视频链接"""
        self._update(collab_id, {"video_url": new_url.strip()})

    def update_video_metrics(self, collab: dict, views: int, likes: int,
                             comments: int) -> bool:
        """回写视频互动数据：播放/点赞/评论"""
        self._update(collab["collab_id"], {
            "video_views": int(views), "video_likes": int(likes),
            "video_comments": int(comments),
        })
        return True

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
    def confirm_uploaded(self, collab_id, video_url=None):
        patch = {"uploaded_confirmed": True, "is_closed": True}
        if video_url:
            patch["video_url"] = video_url
        self._update(collab_id, patch)
