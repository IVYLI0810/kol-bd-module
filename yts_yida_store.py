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
import threading
import time
from datetime import datetime

import streamlit as st

from yida_bd_database import YidaBDDB
import yts_roster as R
import yts_notify as N


def _cfg():
    """从环境变量（Streamlit Secrets）读取宜搭配置，允许本地 yida_config_local.py 兜底"""
    cfg = {
        "access_key_id": os.environ.get("YIDA_ACCESS_KEY_ID", ""),
        "access_key_secret": os.environ.get("YIDA_ACCESS_KEY_SECRET", ""),
        "app_type": "APP_N85O3OPKB9OO52S4KCTD",
        # system_token 从 Secrets 读取，不再硬编码在代码里（安全整改 2026-08-21）
        "system_token": os.environ.get("YIDA_SYSTEM_TOKEN", ""),
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


def _now_min():
    """当前时间，精确到分钟（提交/审核时间戳用）"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# 防缓存击穿：进程级单例被10个会话共享，缓存过期瞬间只让1个会话
# 真正回源宜搭，其他会话等待结果，避免并发全表拉取风暴
_FETCH_LOCK = threading.Lock()


class YidaFetchError(RuntimeError):
    """宜搭数据加载失败（已重试仍失败）。页面层捕获后显示友好提示+重试按钮，
    避免整页崩溃成英文 traceback"""


class YTSStore:
    """与 demo 版 YTSStore 同接口，底层为宜搭（带缓存 + 后台刷新，避免页面卡顿）"""

    CACHE_TTL = 300  # 秒；写操作就地补丁缓存，不再全量重拉

    def __init__(self, db=None):
        self.db = db or YidaBDDB(**_cfg())
        self._cache = {}
        self._refreshing = set()  # 正在后台刷新的 cache_key 集合

    def _bg_refresh(self, cache_key, fetch_fn):
        """后台线程回源：刷新完成写回缓存。失败则保留旧数据。"""
        try:
            value = fetch_fn()
            self._cache[cache_key] = (time.time(), value)
        except Exception:
            pass  # 回源失败：旧缓存继续可用，下次访问再试
        finally:
            self._refreshing.discard(cache_key)

    def _fetch_with_lock(self, cache_key, fetch_fn):
        """stale-while-revalidate 取数：核心是「任何人都不阻塞」。

        10 人共用同一进程缓存，宜搭回源慢时可达 10-20s。策略：
        - 缓存有效（TTL 内）：直接返回（快路径）。
        - 缓存过期但有旧数据：**立即返回旧数据**，同时起后台线程刷新；
          同一 key 只允许一个后台刷新在跑（_refreshing 去重）。
        - 完全无缓存（首次加载）：只能同步等待并显示 spinner（不可避免）。
        """
        hit = self._cache.get(cache_key)
        if hit is not None and time.time() - hit[0] <= self.CACHE_TTL:
            return hit[1]  # 快路径：缓存新鲜

        if hit is not None:
            # 有过期数据：先返回旧的，后台刷新（用户零等待）
            if cache_key not in self._refreshing:
                self._refreshing.add(cache_key)
                threading.Thread(target=self._bg_refresh,
                                 args=(cache_key, fetch_fn), daemon=True).start()
            return hit[1]

        # 完全无缓存（首次加载 / 部署后第一次打开）：同步拉取，带重试保护。
        # 宜搭 API 偶发超时/抖动，重试 2 次；仍失败则抛出自定义异常，
        # 由页面层捕获并显示友好提示，而非整页崩溃。
        last_err = None
        with _FETCH_LOCK:
            hit = self._cache.get(cache_key)
            if hit is not None:
                return hit[1]
            for attempt in range(3):
                try:
                    with st.spinner("正在同步宜搭数据…" if attempt == 0
                                    else f"宜搭连接失败，第 {attempt + 1} 次重试…"):
                        value = fetch_fn()
                    self._cache[cache_key] = (time.time(), value)
                    return value
                except Exception as e:
                    last_err = e
                    if attempt < 2:
                        time.sleep(1.5)  # 短暂等待再重试
        # 3 次都失败：抛出带中文说明的异常，页面层可捕获展示
        raise YidaFetchError(f"宜搭数据加载失败（已重试 3 次）：{last_err}") from last_err

    def _all(self):
        return self._fetch_with_lock("all", self.db.get_all)

    def _get(self, channel_id):
        key = "one:" + channel_id
        hit = self._cache.get(key)
        if hit is not None and time.time() - hit[0] <= self.CACHE_TTL:
            return hit[1]
        # 优先从全量缓存取（避免为单条记录再发一次搜索请求）
        for r in self._cache.get("all", (0, []))[1]:
            if r.get("channel_id") == channel_id:
                self._cache[key] = (time.time(), r)
                return r
        return self._fetch_with_lock(
            key, lambda: self.db.get_by_channel_id(channel_id))

    def _invalidate(self):
        self._cache.clear()

    def _soft_invalidate(self):
        """让缓存过期但保留旧数据：下次读取立即返回旧值，同时触发回源刷新。

        与 _invalidate()（清空）的区别：清空后缓存为空，下一个访问者必须
        阻塞等待全表重拉（宜搭慢时 10-20s，期间页面卡死）。软失效保留旧数据，
        _fetch_with_lock 会「先返回旧值、后台刷新」，任何人都不阻塞。
        审核站定时同步用这个，避免周期性卡顿。"""
        for key in list(self._cache.keys()):
            _ts, val = self._cache[key]
            self._cache[key] = (0.0, val)  # 时间戳置0=视为过期，但数据仍在

    def url_index(self):
        """频道链接 -> channel_id，流程导入判断新增/更新用"""
        return {(r.get("channel_url") or "").strip(): r.get("channel_id")
                for r in self._all() if r.get("channel_url")}

    def import_flow(self, rec: dict):
        """流程导入：按 channel_id upsert，写完就地更新缓存（不整表失效，
        避免一人导入触发全员重拉）"""
        r = self.db.add(rec)
        self._upsert_cached(r or rec)
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

    def _upsert_cached(self, rec):
        """新增记录就地追加进全量缓存（按 channel_id 替换或追加）。

        10人共用关键点：新增/导入后不再整表失效缓存——否则一人导入，
        其他所有人下次操作都被迫重拉全表（4-5秒卡顿）。"""
        if not rec or not rec.get("channel_id"):
            return
        hit = self._cache.get("all")
        if hit is None:
            return  # 无缓存时无需维护，下次全量拉取自然带上
        cid = rec["channel_id"]
        rec = dict(rec)
        rec.setdefault("updated_at",
                       datetime.now().strftime("%Y-%m-%d %H:%M"))
        rows = hit[1]
        for i, r in enumerate(rows):
            if r.get("channel_id") == cid:
                rows[i] = rec
                break
        else:
            rows.append(rec)

    def _audit_patch(self, channel_id, result, opinion):
        """与 db.add_audit 同步：向缓存里的 audit_log 追加同一条记录（精确到分钟）"""
        entry = {"audit_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
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
            # 提交审核时间（精确到分钟，宜搭读回已是 YYYY-MM-DD HH:MM）
            "submit_actual": r.get("submit_actual") or "",
            # 最近一次审核时间（取审核记录最后一条的日期，精确到分钟）
            "audit_time": (audit_log[-1].get("audit_date", "") if audit_log else ""),
            "notes": r.get("notes") or "",
            "audit_log": audit_log,
            # ---- 视频明细子表（一行一条视频，闭环时登记） ----
            "videos": r.get("videos") or [],
            # ---- 投放标记（复用宜搭遗留空字段：ad_auth=是否需要投放，status=是否投放） ----
            "ad_needed": (r.get("ad_auth") or "") == "Y",
            "ad_done": (r.get("status") or "") == "Y",
        }

    def _upd(self, channel_id, patch, clear_fields=None):
        # 快路径：从缓存拿 form_instance_id 直更（1次HTTP，省掉查找+回读）。
        # 缓存里取不到或直更失败时回退 db.update（搜索→更新，2次HTTP）。
        inst = ""
        for r in self._cache.get("all", (0, []))[1]:
            if r.get("channel_id") == channel_id:
                inst = r.get("form_instance_id") or ""
                break
        if not inst:
            one = self._cache.get("one:" + channel_id)
            if one and isinstance(one[1], dict):
                inst = one[1].get("form_instance_id") or ""
        if inst:
            try:
                self.db.update_instance(inst, patch,
                                         clear_fields=clear_fields)
            except Exception:
                self.db.update(channel_id, patch, clear_fields=clear_fields)
        else:
            self.db.update(channel_id, patch, clear_fields=clear_fields)
        self._patch(channel_id, patch)
        # 被清空的字段缓存里也同步清掉
        for code in clear_fields or ():
            for r0 in self._cache.get("all", (0, []))[1]:
                if r0.get("channel_id") == channel_id:
                    r0[code] = ""
            one = self._cache.get("one:" + channel_id)
            if one and isinstance(one[1], dict):
                one[1][code] = ""

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
                "url": r.get("channel_url") or "",
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
        """新增网红（写入宜搭），rec 用代码名字段。
        就地更新缓存，不整表失效（避免一人新增触发全员重拉）"""
        rec.setdefault("email_status", "")
        r = self.db.add(rec)
        self._upsert_cached(r or rec)

    def mark_emailed(self, inf_id):
        """标记已发邮件 → 留在挖掘池（待「标记洽谈中」后才流入活动）。
        _upd 自带快路径：缓存命中实例ID时单次HTTP直更"""
        self._upd(inf_id, {"email_status": "已发送", "stage": "已发邮件"})

    def mark_negotiating(self, inf_id):
        """标记洽谈中 → 流入活动模块洽谈栏（_upd 快路径）"""
        self._upd(inf_id, {"stage": "洽谈中"})

    def unmark_emailed(self, inf_id):
        """取消「已发邮件」标记 → 回到未触达状态。
        注意：_to_form_data 跳过空值，清空必须走 clear_fields。"""
        self._upd(inf_id, {}, clear_fields=["email_status", "stage"])

    def unmark_negotiating(self, inf_id):
        """取消「洽谈中」→ 退回已发邮件状态（保留已发邮件标记，
        仅当还未流入活动月份时允许，UI 侧控制）"""
        self._upd(inf_id, {"stage": "已发邮件"})

    def sync_yt_subscribers(self, ids: list) -> int:
        """补频道粉丝数：对给定记录逐个抓 YouTube 主页数据（缓存7天），
        粉丝数>0 时写回宜搭。返回成功条数。未配 key/抓取失败跳过。"""
        import yts_yt_stats as YT
        if not YT.get_key():
            return 0
        n = 0
        for cid in ids:
            if not str(cid).startswith("UC"):
                continue
            stats = YT.fetch_stats(cid)
            if not stats:
                continue
            sub = int(stats.get("subscribers") or 0)
            if sub > 0:
                self._upd(cid, {"subscribers": sub})
                n += 1
        return n

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
        """批量导入网红（upsert），records 用代码名字段。
        逐条就地更新缓存，不整表失效（避免一人导入触发全员重拉）"""
        count = 0
        for rec in records:
            if not rec.get("channel_id"):
                continue
            r = self.db.add(rec)
            self._upsert_cached(r or rec)
            count += 1
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
                r = self.db.add({
                    "channel_id": cid,
                    "channel_name": x.get("channel_name") or "",
                    "channel_url": x.get("channel_url") or "",
                    "category": x.get("category") or "",
                    "subscribers": int(x.get("subscribers") or 0),
                    "recruiter": x.get("discovered_by") or "",
                    "email_status": "已发送", "stage": "已发邮件",
                })
                self._upsert_cached(r)
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
        # 新增/补丁均已就地维护缓存，无需整表失效（避免触发全员重拉）
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
        # 每条更新均已通过 _patch 就地维护缓存，无需整表失效
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

    def get_collab(self, collab_id, fresh: bool = False):
        """读取单条合作记录。fresh=True 时绕过缓存直查宜搭（约1-2秒），
        用于详情页打开时拿最新审核状态，避免双站缓存不同步"""
        if fresh:
            try:
                r = self.db.get_by_channel_id(collab_id)
                if r:
                    self._cache["one:" + collab_id] = (time.time(), r)
                    return self._to_collab(r)
            except Exception:
                pass  # 直查失败降级走缓存
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

    # ---------------- 视频明细子表（闭环时登记，一条视频一行） ----------------
    def save_videos(self, collab_id, videos: list) -> None:
        """全量覆写视频明细子表。videos 每项：
        {"video_type","video_url","product_ids","views","likes","comments",
         "clicks","ctr","orders","gmv"}
        ⚠ 宜搭子表是整表覆写：必须传完整列表，不能只传增量行"""
        self._upd(collab_id, {"videos": videos})

    def update_video_row(self, collab: dict, index: int, patch: dict) -> None:
        """更新视频明细第 index 行的指标字段（分析模块一键刷新用）。
        先读当前全量 → 改对应行 → 整表覆写回"""
        videos = [dict(v) for v in (collab.get("videos") or [])]
        if not (0 <= index < len(videos)):
            return
        videos[index].update(patch)
        self._upd(collab["collab_id"], {"videos": videos})

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

    def update_product_metrics(self, collab: dict, clicks: int, ctr: float,
                               orders: int, gmv: float) -> bool:
        """回写商品效果数据（GMC 报表自动拉取用）：点击/CTR/成交/GMV。
        转化率 = 成交/点击（点击为0时记0）"""
        cid = collab.get("collab_id")
        conv = round(orders / clicks * 100, 2) if clicks else 0.0
        patch = {"product_views": int(clicks), "ctr": float(ctr),
                 "orders": int(orders), "conversion_rate": conv,
                 "gmv": float(gmv)}
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
        # 提交时间精确到分钟（YYYY-MM-DD HH:MM），宜搭 dateField 存毫秒时间戳
        self._upd(collab_id, {"video_link": video_url, "audit_status": "待审核",
                              "stage": "已交视频", "submit_actual": _now_min()})
        # 个人待办：提醒审核同学。返回 (ok, msg) 供页面展示发送结果
        rec = self._get(collab_id) or {}
        return N.notify_review_submitted(rec.get("channel_name") or collab_id,
                                         video_url)

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
        return self._notify_result(collab_id, "已通过", note or "审核通过")

    def review_reject(self, collab_id, reason):
        self.db.add_audit(collab_id, result="未通过", opinion=reason)
        self._audit_patch(collab_id, "未通过", reason)
        self._upd(collab_id, {"audit_status": "未通过", "stage": "修改中"})
        return self._notify_result(collab_id, "未通过", reason)

    def _notify_result(self, collab_id, result, opinion):
        """审核出结果 → 群里@运营 + 给负责运营发待办提醒 check，返回 (ok, msg)"""
        rec = self._get(collab_id) or {}
        return N.notify_review_result(rec.get("channel_name") or collab_id,
                                      result, opinion, rec.get("recruiter") or "",
                                      detail_id=collab_id)

    # ---------------- 复审（运营操作，可循环） ----------------
    def start_recheck(self, collab_id, new_video_url):
        self._upd(collab_id, {"recheck_video_url": new_video_url})

    def recheck_pass(self, collab_id):
        self.db.add_audit(collab_id, result="已通过", opinion="复审通过")
        self._audit_patch(collab_id, "已通过", "复审通过")
        self._upd(collab_id, {"audit_status": "已通过"})
        return self._notify_result(collab_id, "已通过", "复审通过")

    def recheck_reject(self, collab_id, reason):
        self.db.add_audit(collab_id, result="未通过", opinion=f"复审驳回：{reason}")
        self._audit_patch(collab_id, "未通过", f"复审驳回：{reason}")
        self._upd(collab_id, {"audit_status": "未通过", "recheck_video_url": ""})
        return self._notify_result(collab_id, "未通过", f"复审驳回：{reason}")

    # ---------------- 审核站表格模式（审核模块 / 投放模块） ----------------
    def list_review_table(self):
        """审核模块表格行：所有已提交视频的网红。
        是否通过：已通过/复审通过=Y，已驳回=N，待审核/复审中=空白
        附带：提交时间(submit_actual)、审核时间(audit_time)、状态(review_status) 用于展示区分"""
        order = {"待审核": 0, "未通过": 1, "已通过": 2}
        rows = []
        for c in (self._to_collab(r) for r in self._all()):
            if not c["video_url"] and not c["recheck_video_url"]:
                continue
            rs = c["review_status"]
            if not rs:
                continue  # 从没提交过审核的（如直接闭环）不进审核表
            passed = "Y" if rs in ("已通过", "复审通过") else ("N" if rs == "已驳回" else "")
            reason = c["review_comment"] if rs == "已驳回" else ""
            rows.append({
                "collab_id": c["collab_id"],
                "name": c["name"],
                "channel_url": c["channel_url"],
                # 复审过就用复审链接，否则用首次提交的视频链接
                "review_url": c["recheck_video_url"] or c["video_url"],
                "passed": passed,
                "reason": reason,
                # ---- 新增：用于展示与区分 ----
                "status": rs,                       # 待审核/已通过/已驳回/复审中/复审通过
                "submit_actual": c.get("submit_actual") or "",  # 提交时间（精确到分钟）
                "audit_time": c.get("audit_time") or "",        # 审核时间（精确到分钟）
            })
        rows.sort(key=lambda x: (order.get(
            {"Y": "已通过", "N": "未通过"}.get(x["passed"], "待审核"), 3), x["name"]))
        return rows

    def apply_review_results(self, changes):
        """批量回填审核结果（表格保存/Excel上传共用）。
        changes: [{"collab_id","passed"("Y"/"N"),"reason"}]，只处理与现状不同的行。
        写完统一发一条群通知@运营（不逐条发待办，避免刷屏）。返回 (条数, 通知ok, 通知msg)

        修复要点（2026-08-21）：
        - 每条审核合并为 1 次宜搭写入（add_audit 内部已含 audit_status，
          stage 通过 extra_fields 一并写入），原先 3 次 HTTP 减到 2 次，提速且降低超时风险。
        - add_audit 返回 False（记录未找到/写入失败）时不再静默，
          计入失败并在通知消息里如实提示，避免"显示已保存实际没保存"。
        """
        cur = {c["collab_id"]: c for c in
               (self._to_collab(r) for r in self._all())}
        done, applied, failed = [], [], []
        now_min = _now_min()  # 审核时间精确到分钟
        for ch in changes:
            cid = (ch.get("collab_id") or "").strip()
            passed = str(ch.get("passed") or "").strip().upper()
            if not cid or passed not in ("Y", "N") or cid not in cur:
                continue
            c = cur[cid]
            reason = str(ch.get("reason") or "").strip()
            already = ("Y" if c["review_status"] in ("已通过", "复审通过")
                       else "N" if c["review_status"] == "已驳回" else "")
            if passed == already and (passed == "Y" or reason == (c["review_comment"] or "").strip()):
                continue  # 没变化就不重复写
            if passed == "Y":
                ok = self.db.add_audit(cid, result="已通过",
                                       opinion=reason or "审核通过",
                                       audit_date=now_min)
                if ok:
                    self._audit_patch(cid, "已通过", reason or "审核通过")
                    self._patch(cid, {"audit_status": "已通过"})
                    applied.append((c["name"], "✅通过", reason or "审核通过"))
                else:
                    failed.append(c["name"])
            else:
                # 驳回：stage=修改中 通过 extra_fields 一并写入，省一次 HTTP
                ok = self.db.add_audit(cid, result="未通过",
                                       opinion=reason or "审核未通过",
                                       audit_date=now_min,
                                       extra_fields={"stage": "修改中"})
                if ok:
                    self._audit_patch(cid, "未通过", reason or "审核未通过")
                    self._patch(cid, {"audit_status": "未通过", "stage": "修改中"})
                    applied.append((c["name"], "❌驳回", reason or "审核未通过"))
                else:
                    failed.append(c["name"])
            done.append(cid)
        if not applied and not failed:
            return 0, True, "没有需要更新的审核结果"
        # 一条汇总群通知@运营，代替逐条待办
        nok, nmsg = N.notify_review_results_batch(applied)
        if failed:
            nmsg = (nmsg + f"；⚠️ {len(failed)} 条写入失败（未找到记录）："
                    + "、".join(failed[:10]))
            nok = False
        return len(applied), nok, nmsg

    def list_ad_table(self):
        """投放模块表格行：标记了「需要投放」或「已投放」的网红。
        是否需要投放由主站闭环时选择；是否投放在本表格回填"""
        rows = [{
            "collab_id": c["collab_id"],
            "name": c["name"],
            "channel_url": c["channel_url"],
            "ad_needed": "Y" if c["ad_needed"] else "",
            "ad_done": "Y" if c["ad_done"] else "",
        } for c in (self._to_collab(r) for r in self._all())
            if c["ad_needed"] or c["ad_done"]]
        # 待投放（需投但未投）排最前
        rows.sort(key=lambda x: (0 if x["ad_needed"] and not x["ad_done"] else 1,
                                 x["name"]))
        return rows

    def apply_ad_results(self, changes):
        """批量回填「是否投放」。changes: [{"collab_id","ad_done"("Y"/"")}]
        复用遗留字段 status 存储。返回更新条数"""
        n = 0
        cur = {c["collab_id"]: c for c in
               (self._to_collab(r) for r in self._all())}
        for ch in changes:
            cid = (ch.get("collab_id") or "").strip()
            if not cid or cid not in cur:
                continue
            done = str(ch.get("ad_done") or "").strip().upper() == "Y"
            if done == cur[cid]["ad_done"]:
                continue
            if done:
                self._upd(cid, {"status": "Y"})
            else:
                self._upd(cid, {"status": ""}, clear_fields=["status"])
            n += 1
        return n

    # ---------------- 审核状态快速同步（写入就反馈） ----------------
    def sync_review_states(self):
        """审核站和主站是两个进程，缓存互不相通。本方法只挑缓存里
        处于「待审核 / 复审中」的记录逐条直查宜搭（通常只有几条，1-2秒），
        有变化就地补丁缓存。返回状态发生变化的网红名列表，供页面提示。
        活动模块每次打开自动调用 → 审核站一驳回，回到主站几秒内可见。"""
        rows = self._cache.get("all", (0, []))[1]
        changed = []
        for r in rows:
            cid = r.get("channel_id")
            if not cid:
                continue
            if (r.get("audit_status") or "") not in ("待审核", "未通过"):
                continue
            try:
                fresh = self.db.get_by_channel_id(cid)
            except Exception:
                continue
            if not fresh:
                continue
            diff = ((fresh.get("audit_status") or "") != (r.get("audit_status") or "")) \
                or len(fresh.get("audit_log") or []) != len(r.get("audit_log") or []) \
                or ((fresh.get("recheck_video_url") or "") != (r.get("recheck_video_url") or ""))
            if not diff:
                continue
            r.clear()
            r.update(fresh)  # 就地补丁，列表里其他引用同步生效
            one = self._cache.get("one:" + cid)
            if one and isinstance(one[1], dict):
                one[1].clear()
                one[1].update(fresh)
            changed.append(fresh.get("channel_name") or cid)
        return changed

    # ---------------- 上传确认 → 闭环（绿光） ----------------
    def confirm_uploaded(self, collab_id, video_url=None, ad_needed=False):
        patch = {"stage": "已完成"}
        if video_url:
            patch["video_link"] = video_url
        # 是否需要投放：运营在闭环时勾选 → 进审核站投放模块待办
        if ad_needed:
            patch["ad_auth"] = "Y"
            self._upd(collab_id, patch)
        else:
            patch["ad_auth"] = ""
            self._upd(collab_id, patch, clear_fields=["ad_auth"])

    # ---------------- 反向操作：回退 / 取消 / 流回 / 淘汰 ----------------
    def cancel_collab(self, collab_id):
        """取消合作：退回洽谈中（清空上线月份，进度保留）"""
        self._upd(collab_id, {"plan_month": ""}, clear_fields=["plan_month"])

    def back_to_pool(self, collab_id):
        """流回挖掘库：退回挖掘池（清空月份+洽谈标记，保留已发邮件标记）"""
        self._upd(collab_id, {"plan_month": "", "stage": ""},
                  clear_fields=["plan_month", "stage"])

    def remove_influencer(self, collab_id):
        """淘汰：从挖掘池移除（清空已发邮件/洽谈标记，回到未触达状态）"""
        self._upd(collab_id, {"email_status": "", "stage": "", "plan_month": ""},
                  clear_fields=["email_status", "stage", "plan_month"])

    # 步骤回退：把对应字段写回"未完成"值（均为宜搭表单已有选项或清空）
    STEP_UNDO = {
        0: lambda: ({"plan_month": ""}, ["plan_month"]),          # 确认合作
        1: lambda: ({"guideline_status": "", "contract_status": "",
                     "gmc_status": ""},
                    ["guideline_status", "contract_status", "gmc_status"]),
        2: lambda: ({"order_status": ""}, ["order_status"]),      # 下单
        3: lambda: ({"order_status": "已下单"}, []),              # 收货→退回已下单
        4: lambda: ({"shoot_status": ""}, ["shoot_status"]),      # 拍摄
        5: lambda: ({"video_link": ""}, ["video_link"]),          # 提交审核
        6: lambda: ({"audit_status": "", "recheck_video_url": ""},
                    ["audit_status", "recheck_video_url"]),       # 审核
        7: lambda: ({"stage": ""}, ["stage"]),                    # 闭环→退回履约
    }

    def undo_step(self, collab_id, step: int) -> bool:
        """回退指定步骤（0-7）；回退后该步骤及之后的状态回到未完成"""
        fn = self.STEP_UNDO.get(step)
        if not fn:
            return False
        patch, clear = fn()
        self._upd(collab_id, patch, clear_fields=clear)
        return True


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
