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
import yts_roster as R


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

    CACHE_TTL = 300  # 秒；写操作就地补丁缓存，不再全量重拉

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

    def url_index(self):
        """频道链接 -> channel_id，流程导入判断新增/更新用"""
        return {(r.get("channel_url") or "").strip(): r.get("channel_id")
                for r in self._all() if r.get("channel_url")}

    def import_flow(self, rec: dict):
        """流程导入：按 channel_id upsert，写完失效缓存"""
        r = self.db.add(rec)
        self._invalidate()
        return r

    def _patch(self, channel_id, patch):
        """写成功后就地更新缓存，避免每次操作都全量重拉（4-5 秒）"""
        p = dict(patch)
        p.setdefault("updated_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
        for r in self._cache.get("all", (0, []))[1]:
            if r.get("channel_id") == channel_id:
                r.update(p)
        one = self._cache.get("one:" + channel_id)
        if one and isinstance(one[1], dict):
            one[1].update(p)

    def _audit_patch(self, channel_id, result, opinion):
        """与 db.add_audit 同步：向缓存里的 audit_log 追加同一条记录"""
        entry = {"audit_date": datetime.now().strftime("%Y-%m-%d"),
                 "audit_result": result, "audit_opinion": opinion}
        rows = list(self._cache.get("all", (0, []))[1])
        one = self._cache.get("one:" + channel_id)
        if one and isinstance(one[1], dict):
            rows.append(one[1])
        for r in rows:
            if r.get("channel_id") == channel_id:
                log = list(r.get("audit_log") or [])
                log.append(entry)
                r["audit_log"] = log

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
        # 洽谈中闸门：挖掘页标记「洽谈中」后才流入活动模块（仅已发邮件不够）
        status = "履约中" if plan_month else ("洽谈中" if stage == "洽谈中" else "未回流")
        return {
            "collab_id": r.get("channel_id"),
            "form_instance_id": r.get("form_instance_id") or "",
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
            "notes": r.get("notes") or "",
            "audit_log": audit_log,
        }

    def _upd(self, channel_id, patch, clear_fields=None):
        r = self.db.update(channel_id, patch, clear_fields=clear_fields)
        self._patch(channel_id, patch)
        # 被清空的字段缓存里也同步清掉
        for code in clear_fields or ():
            for r0 in self._cache.get("all", (0, []))[1]:
                if r0.get("channel_id") == channel_id:
                    r0[code] = ""
            one = self._cache.get("one:" + channel_id)
            if one and isinstance(one[1], dict):
                one[1][code] = ""
        return r

    # ---------------- 编辑基本信息 ----------------
    EDIT_FIELDS = ("price", "plan_month", "email", "channel_url",
                   "group_link", "submit_deadline", "notes")
    # 允许清空的文本字段（plan_month/channel_url 清空会破坏流程状态，不允许）
    CLEARABLE = ("notes", "group_link", "email", "submit_deadline")

    def update_info(self, collab_id, fields: dict) -> None:
        """编辑基本信息（报价/月份/邮箱/链接/交稿截止/备注）。
        fields 只取白名单字段；值为空串的文本字段按"清空"处理"""
        patch, clear = {}, []
        for k, v in fields.items():
            if k not in self.EDIT_FIELDS:
                continue
            v = "" if v is None else str(v).strip()
            if k == "price":
                try:
                    patch["price"] = int(float(v)) if v else 0
                except ValueError:
                    continue
            elif not v:
                if k in self.CLEARABLE:
                    clear.append(k)
            else:
                patch[k] = v
        if patch or clear:
            self._upd(collab_id, patch, clear_fields=clear)

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
                "stage": r.get("stage") or "",
            })
        return out

    def add_influencer(self, rec):
        """新增网红（写入宜搭），rec 用代码名字段"""
        rec.setdefault("email_status", "")
        self.db.add(rec)
        self._invalidate()

    def mark_emailed(self, inf_id):
        """标记已发邮件 → 留在挖掘池（待「标记洽谈中」后才流入活动）"""
        self._upd(inf_id, {"email_status": "已发送", "stage": "已发邮件"})

    def mark_negotiating(self, inf_id):
        """标记洽谈中 → 流入活动模块洽谈栏"""
        self._upd(inf_id, {"stage": "洽谈中"})

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

    def sync_from_discovery(self, force: bool = False) -> dict:
        """挖掘站「已发邮件」自动同步进挖掘池。

        新增：补基础信息并标记已发邮件；
        已存在：补空标记 + 补空基础信息（粉丝数/垂类），已有进度一律不动。
        """
        rows = R.fetch_emailed_channels(force=force)
        existing = {r.get("channel_id"): r for r in self._all()}
        added = patched = 0
        for x in rows:
            cid = (x.get("channel_id") or "").strip()
            if not cid:
                continue
            if cid not in existing:
                self.db.add({
                    "channel_id": cid,
                    "channel_name": x.get("channel_name") or "",
                    "channel_url": x.get("channel_url") or "",
                    "category": x.get("category") or "",
                    "subscribers": int(x.get("subscribers") or 0),
                    "recruiter": x.get("discovered_by") or "",
                    "email_status": "已发送", "stage": "已发邮件",
                })
                added += 1
            else:
                cur = existing[cid]
                patch = {}
                if not cur.get("email_status"):
                    patch["email_status"] = "已发送"
                    if not cur.get("stage"):
                        patch["stage"] = "已发邮件"
                # 旧记录基础信息空缺时，用挖掘站数据补（已有值一律不动）
                cur_sub = int(cur.get("subscribers") or 0)
                new_sub = int(x.get("subscribers") or 0)
                if cur_sub <= 0 < new_sub:
                    patch["subscribers"] = new_sub
                if not (cur.get("category") or "").strip() \
                        and (x.get("category") or "").strip():
                    patch["category"] = x.get("category")
                if patch:
                    self._upd(cid, patch)
                    patched += 1
        if added or patched:
            self._invalidate()
        return {"added": added, "patched": patched, "total": len(rows)}

    def sync_basic_info(self, force: bool = False, progress=None) -> dict:
        """全量同步挖掘站基础信息：粉丝量刷新为挖掘站最新值（YouTube API 抓的），
        垂类/频道名仅空缺时补；进度类字段一律不动。"""
        rows = R.fetch_all_channels(force=force)
        if not rows:
            return {"matched": 0, "updated": 0, "total": 0}
        idx = {x.get("channel_id"): x for x in rows if x.get("channel_id")}
        url_idx = {(x.get("channel_url") or "").strip().rstrip("/"): x
                   for x in rows if x.get("channel_url")}
        recs = self._all()
        matched = updated = 0
        for i, rec in enumerate(recs):
            if progress:
                progress(i, len(recs))
            cid = (rec.get("channel_id") or "").strip()
            m = idx.get(cid) or url_idx.get(
                (rec.get("channel_url") or "").strip().rstrip("/"))
            if not m:
                continue
            matched += 1
            patch = {}
            new_sub = int(m.get("subscribers") or 0)
            cur_sub = int(rec.get("subscribers") or 0)
            if new_sub > 0 and new_sub != cur_sub:
                patch["subscribers"] = new_sub
            if not (rec.get("category") or "").strip() \
                    and (m.get("category") or "").strip():
                patch["category"] = m["category"].strip()
            if not (rec.get("channel_name") or "").strip() \
                    and (m.get("channel_name") or "").strip():
                patch["channel_name"] = m["channel_name"].strip()
            if not patch:
                continue
            inst = rec.get("form_instance_id")
            try:
                if inst and getattr(self.db, "update_instance", None):
                    self.db.update_instance(inst, patch)
                else:
                    self._upd(cid, patch)
                self._patch(cid, patch)
                updated += 1
            except Exception:
                continue
        if progress:
            progress(len(recs), len(recs))
        if updated:
            self._invalidate()
        return {"matched": matched, "updated": updated, "total": len(rows)}

    def confirm_collab(self, collab_id, plan_month, price=0):
        self._upd(collab_id, {"plan_month": plan_month, "stage": "已确认",
                              "price": int(price or 0)})
        try:  # 即时回流挖掘站标「已引入」；失败则由对账兜底
            R.mark_introduced(collab_id)
        except Exception:
            pass

    def push_back_introduced(self, force: bool = False) -> int:
        """回流对账：YTS 履约中（含已闭环）的网红，挖掘站状态补标「已引入」。
        只补不反向改，挖掘站不存在的记录跳过。"""
        fuls = [r for r in self._all() if (r.get("plan_month") or "").strip()]
        if not fuls:
            return 0
        statuses = R.fetch_statuses(force=force)
        n = 0
        for r in fuls:
            cid = r.get("channel_id")
            if cid and cid in statuses and statuses[cid] != "已引入":
                try:
                    R.mark_introduced(cid)
                    n += 1
                except Exception:
                    pass
        return n

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

    def update_video_link(self, collab_id, new_url: str):
        """待审核状态下更换初审视频链接（不重推审核流，只换链接）"""
        self._upd(collab_id, {"video_link": new_url.strip()})

    def update_video_metrics(self, collab: dict, views: int, likes: int,
                             comments: int) -> bool:
        """回写视频互动数据（分析模块自动抓取用）：播放/点赞/评论。
        优先按 form_instance_id 直更（单次HTTP，跳过搜索），失败回退按ID更新"""
        cid = collab.get("collab_id")
        patch = {"video_views": int(views), "video_likes": int(likes),
                 "video_comments": int(comments)}
        inst = collab.get("form_instance_id") or ""
        if inst:
            try:
                self.db.update_instance(inst, patch)
                self._patch(cid, patch)
                return True
            except Exception:
                pass
        self._upd(cid, patch)
        return True

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
        self._audit_patch(collab_id, "已通过", note or "审核通过")
        self._upd(collab_id, {"audit_status": "已通过"})

    def review_reject(self, collab_id, reason):
        self.db.add_audit(collab_id, result="未通过", opinion=reason)
        self._audit_patch(collab_id, "未通过", reason)
        self._upd(collab_id, {"audit_status": "未通过", "stage": "修改中"})

    # ---------------- 复审（运营操作，可循环） ----------------
    def start_recheck(self, collab_id, new_video_url):
        self._upd(collab_id, {"recheck_video_url": new_video_url})

    def recheck_pass(self, collab_id):
        self.db.add_audit(collab_id, result="已通过", opinion="复审通过")
        self._audit_patch(collab_id, "已通过", "复审通过")
        self._upd(collab_id, {"audit_status": "已通过"})

    def recheck_reject(self, collab_id, reason):
        self.db.add_audit(collab_id, result="未通过", opinion=f"复审驳回：{reason}")
        self._audit_patch(collab_id, "未通过", f"复审驳回：{reason}")
        self._upd(collab_id, {"audit_status": "未通过", "recheck_video_url": ""})

    # ---------------- 上传确认 → 闭环（绿光） ----------------
    def confirm_uploaded(self, collab_id, video_url=None):
        patch = {"stage": "已完成"}
        if video_url:
            patch["video_link"] = video_url
        self._upd(collab_id, patch)


_STORE = None


def get_yts_store():
    """进程级单例：缓存跨 rerun 存活，避免每次刷新整页重拉宜搭（~10s）；
    配置了 AK（环境变量或本地配置文件）→ 宜搭真实数据；否则回退本地 demo 数据"""
    global _STORE
    if _STORE is not None:
        return _STORE
    cfg = _cfg()
    if cfg.get("access_key_id") and cfg.get("access_key_secret"):
        try:
            _STORE = YTSStore(YidaBDDB(**cfg))
            return _STORE
        except Exception:
            pass
    from yts_store import YTSStore as DemoStore
    d = DemoStore()
    d.demo = True
    _STORE = d
    return d
