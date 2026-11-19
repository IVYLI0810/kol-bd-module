#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 网红管理系统 - Supabase 共享存储（Phase 1 正式版）

功能与 yts_yida_store.YTSStore 完全等价，底层从钉钉宜搭改成 Supabase REST，
和挖掘站 kol-finder 用同一个 Supabase 项目、同一张共享库：
  - kol-bd 读写 public.collabs（本文件）
  - kol-finder 读写 public.influencers / members / keywords / user_settings
改一处另一端立刻看到，不再有"每 300s 抄一遍"的滞后。

Phase 1 语义 = 保持和宜搭版一致，不改任何业务规则（"负责人只填空不覆盖"等
老规矩沿用）。Phase 2 会再切规则。

配置：
  SUPABASE_URL   例 https://webjrwzorxxlqrcrrnro.supabase.co
  SUPABASE_KEY   anon/public key（与 kol-finder 同一份；yts_roster 里已带默认值）
  Streamlit Secrets 或直接环境变量；本地兜底 yida_config_local.py 里的 SUPABASE 键。
"""
import json
import os
import threading
import time
from datetime import datetime

import requests

import yts_roster as R
import yts_notify as N


# ------------------------------------------------------------------ 连接配置
def _cfg_supabase():
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
        url = R.SUPABASE_URL  # 与 kol-finder 同项目（yts_roster 里已有硬编码默认）
    if not key:
        key = R.SUPABASE_KEY
    return url.rstrip("/"), key


_BASE, _KEY = _cfg_supabase()
_HEADERS = {"apikey": _KEY, "Authorization": f"Bearer {_KEY}",
            "Content-Type": "application/json"}


# ------------------------------------------------------------------ 时间小工具
def _now_min():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _iso_to_min(s):
    """Supabase timestamptz → YYYY-MM-DD HH:MM（保留 UI 展示格式）"""
    if not s:
        return ""
    try:
        return str(s)[:16].replace("T", " ")
    except Exception:
        return str(s)


# ------------------------------------------------------------------ 身份键
def _ident(r) -> str:
    cid = r.get("channel_id") or ""
    m = str(r.get("plan_month") or "").strip()
    return f"{cid}#{m}" if m else cid


def _split(collab_id):
    s = str(collab_id or "")
    if "#" in s:
        cid, m = s.split("#", 1)
        return cid, m.strip()
    return s, ""


def _best_row(rows, collab_id):
    cid, m = _split(collab_id)
    first_cid = None
    for r in rows:
        if _ident(r) == collab_id:
            return r
        if r.get("channel_id") == cid:
            if not m and not str(r.get("plan_month") or "").strip():
                return r
            if first_cid is None:
                first_cid = r
    return first_cid if not m else None


# ------------------------------------------------------------------ 主类
class YTSStore:
    """与 yts_yida_store.YTSStore 接口一致的 Supabase 版；进程单例、短 TTL 缓存。

    和宜搭版的两个显著区别：
    1) 不再需要 form_instance_id —— 直接按 (channel_id, plan_month) 定位行。
    2) 缓存大幅简化：Supabase 单表读 <500ms，全表 2s TTL 就够，写完立即失效。"""

    _lock = threading.RLock()
    _CACHE_TTL = 2.0  # 秒；同进程 2s 内多次 _all() 只发一次 HTTP

    def __init__(self, url=None, key=None):
        self.base = (url or _BASE).rstrip("/")
        self.key = key or _KEY
        self.h = {"apikey": self.key,
                  "Authorization": f"Bearer {self.key}",
                  "Content-Type": "application/json"}
                self._all_cache = None  # (ts, rows)
        self.demo = False       # 主站用它区分提示语
        self.backend = "supabase"
        self._rev = 0           # 写代次：每次写库自增，供 app 层缓存即时失效

    # ================================================== 底层 REST 小工具
    def _req(self, method, path, *, params=None, body=None, prefer=None,
             timeout=15):
        url = f"{self.base}/rest/v1/{path}"
        h = dict(self.h)
        if prefer:
            h["Prefer"] = prefer
        r = requests.request(method, url, params=params, headers=h,
                             data=(json.dumps(body) if body is not None else None),
                             timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {method} {path} -> {r.status_code}: {r.text[:250]}")
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except Exception:
            return None

        def _invalidate(self):
        with self._lock:
            self._all_cache = None
            self._rev = getattr(self, "_rev", 0) + 1

    def _soft_invalidate(self):
        """同 _invalidate；Phase 1 保留同名方法给 apps 顶部按钮调用"""
        self._invalidate()

    def rev(self) -> int:
        """当前写代次：app 层缓存 key 用它，写完即变 → 缓存自动失效"""
        return getattr(self, "_rev", 0)

    def _all(self, force: bool = False):
        """全表读；带 2s TTL 进程缓存"""
        now = time.time()
        with self._lock:
            if not force and self._all_cache and now - self._all_cache[0] < self._CACHE_TTL:
                return self._all_cache[1]
        rows, off, limit = [], 0, 500
        while True:
            page = self._req("GET", "collabs",
                             params={"select": "*",
                                     "deleted": "eq.false",
                                     "order": "id.asc",
                                     "offset": off, "limit": limit}) or []
            rows.extend(page)
            if len(page) < limit:
                break
            off += limit
        with self._lock:
            self._all_cache = (time.time(), rows)
        return rows

    def _get(self, collab_id):
        return _best_row(self._all(), collab_id)

    # ---------------- 写：upsert / patch / delete ----------------
    def _upsert_row(self, rec: dict):
        """按 (channel_id, plan_month) merge；返回 Supabase 回读的行"""
        body = self._encode_row(rec)
        out = self._req("POST", "collabs",
                        params={"on_conflict": "channel_id,plan_month"},
                        body=body,
                        prefer="return=representation,resolution=merge-duplicates")
        self._invalidate()
        return (out or [None])[0] or body

    def _patch_row(self, channel_id, plan_month, patch: dict,
                   clear_fields=()):
        """按 (channel_id, plan_month) 精确 PATCH；clear_fields 里的列写空值"""
        if not patch and not clear_fields:
            return None
        body = self._encode_patch(patch, clear_fields)
        if not body:
            return None
        out = self._req("PATCH", "collabs",
                        params={"channel_id": f"eq.{channel_id}",
                                "plan_month": f"eq.{plan_month or ''}"},
                        body=body,
                        prefer="return=representation")
        self._invalidate()
        return (out or [None])[0]

    def _delete_row(self, channel_id, plan_month=None):
        params = {"channel_id": f"eq.{channel_id}"}
        if plan_month is not None:
            params["plan_month"] = f"eq.{plan_month or ''}"
        self._req("DELETE", "collabs", params=params)
        self._invalidate()

    _TEXT_COLS = ("channel_name", "channel_url", "category", "sales_category",
                  "email", "recruiter", "stage", "email_status",
                  "guideline_status", "contract_status", "gmc_status",
                  "product_list", "order_status", "shoot_status",
                  "submit_deadline", "submit_actual",
                  "video_link", "recheck_video_url", "audit_status",
                  "product_link", "group_link", "settlement", "settlement_note",
                  "notes")
    _INT_COLS = ("subscribers", "price", "orders", "video_views", "video_likes",
                 "video_comments", "product_views", "total_views")
    _NUM_COLS = ("gmv", "ctr", "conversion_rate")
    _BOOL_COLS = ("ad_needed", "ad_done", "deleted")
    _JSON_COLS = ("audit_log", "videos", "products")
    _ALL_COLS = (_TEXT_COLS + _INT_COLS + _NUM_COLS + _BOOL_COLS + _JSON_COLS +
                 ("channel_id", "plan_month"))

    def _encode_row(self, rec: dict):
        out = {}
        for k in self._ALL_COLS:
            if k in rec:
                out[k] = self._encode_val(k, rec[k])
        return out

    def _encode_patch(self, patch: dict, clear_fields=()):
        out = {}
        for k, v in patch.items():
            if k not in self._ALL_COLS:
                continue
            out[k] = self._encode_val(k, v)
        for k in clear_fields or ():
            if k not in self._ALL_COLS:
                continue
            out[k] = self._clear_val(k)
        return out

    def _encode_val(self, k, v):
        if k in _BOOL_COLS_SET:
            return bool(v) if v not in (None, "") else False
        if k in _INT_COLS_SET:
            try:
                return int(float(v)) if v not in (None, "") else 0
            except (TypeError, ValueError):
                return 0
        if k in _NUM_COLS_SET:
            try:
                return float(v) if v not in (None, "") else 0.0
            except (TypeError, ValueError):
                return 0.0
        if k in _JSON_COLS_SET:
            return v if isinstance(v, (list, dict)) else []
        # text
        return "" if v is None else str(v)

    def _clear_val(self, k):
        if k in _BOOL_COLS_SET:
            return False
        if k in _INT_COLS_SET or k in _NUM_COLS_SET:
            return 0
        if k in _JSON_COLS_SET:
            return []
        return ""

    # ================================================== 对外接口
    # ---- 内部记录 → UI collab 字典（与宜搭版输出 shape 保持一致）----
    def _to_collab(self, r):
        product_list_raw = r.get("product_list") or ""
        if isinstance(product_list_raw, str):
            product_list = [p.strip() for p in product_list_raw.splitlines() if p.strip()]
        else:
            product_list = list(product_list_raw or [])
        audit_log = r.get("audit_log") or []
        last_comment = audit_log[-1].get("audit_opinion", "") if audit_log else ""
        audit_status = r.get("audit_status") or ""
        recheck_url = r.get("recheck_video_url") or ""
        if audit_status == "已通过":
            review_status = "复审通过" if recheck_url else "已通过"
        elif audit_status == "未通过":
            review_status = "复审中" if recheck_url else "已驳回"
        else:
            review_status = audit_status or ""
        stage = r.get("stage") or ""
        plan_month = r.get("plan_month") or ""
        status = "履约中" if plan_month else ("洽谈中" if stage == "洽谈中" else "未回流")
        return {
            "collab_id": _ident(r),
            "channel_id": r.get("channel_id"),
            "influencer_id": r.get("channel_id"),
            "name": r.get("channel_name") or r.get("channel_id"),
            "platform": "YouTube",
            "followers": r.get("subscribers") or 0,
            "category": r.get("category") or "",
            "sales_category": r.get("sales_category") or "",
            "email": r.get("email") or "",
            "recruiter": r.get("recruiter") or "",
            "avatar": "",
            "status": status,
            "follow_time": _iso_to_min(r.get("updated_at")),
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
            "video_link": r.get("video_link") or "",
            "review_status": review_status,
            "review_comment": last_comment,
            "recheck_video_url": recheck_url,
            "uploaded_confirmed": stage == "已完成",
            "is_closed": stage == "已完成",
            "stage": stage,
            "email_status": r.get("email_status") or "",
            "audit_status": audit_status,
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
            "submit_actual": r.get("submit_actual") or "",
            "audit_time": (audit_log[-1].get("audit_date", "") if audit_log else ""),
            "settlement": r.get("settlement") or "",
            "settlement_note": r.get("settlement_note") or "",
            "notes": r.get("notes") or "",
            "audit_log": audit_log,
            "videos": r.get("videos") or [],
            "products": r.get("products") or [],
            "ad_needed": bool(r.get("ad_needed")),
            "ad_done": bool(r.get("ad_done")),
            "total_views": r.get("total_views") or 0,
            "product_link": r.get("product_link") or "",
        }

    def _upd(self, collab_id, patch, clear_fields=None):
        cid, month = _split(collab_id)
        return self._patch_row(cid, month, patch or {}, clear_fields or ())

    # ---------------- 挖掘模块 ----------------
    def list_pool(self):
        out, seen = [], {}
        for r in self._all():
            cid = r.get("channel_id")
            emailed = r.get("email_status") == "已发送"
            stage = r.get("stage") or ""
            if cid in seen:
                card = seen[cid]
                card["emailed"] = card["emailed"] or emailed
                if not card["stage"] and stage:
                    card["stage"] = stage
                continue
            card = {
                "id": cid,
                "name": r.get("channel_name") or cid,
                "url": r.get("channel_url") or "",
                "platform": "YouTube",
                "followers": r.get("subscribers") or 0,
                "category": r.get("category") or "",
                "sales_category": r.get("sales_category") or "",
                "avatar": "",
                "email": r.get("email") or "",
                "recruiter": r.get("recruiter") or "",
                "emailed": emailed,
                "stage": stage,
            }
            seen[cid] = card
            out.append(card)
        return out

    def latest_category(self, channel_id):
        """按频道ID反查历史内容垂类（供新增弹窗自动带出）：取该频道
        所有未删行里最后一条非空 category（行按 id.asc，较新优先）。无则 ''。"""
        cid = _split(channel_id)[0]
        if not cid:
            return ""
        best = ""
        for r in self._all():
            if (r.get("channel_id") or "") != cid:
                continue
            c = (r.get("category") or "").strip()
            if c:
                best = c
        return best

    def add_influencer(self, rec):
        rec = dict(rec or {})
        rec.setdefault("email_status", "")
        rec.setdefault("plan_month", "")
        return self._upsert_row(rec)

    def import_influencers(self, records):
        n = 0
        for rec in records or []:
            if not rec.get("channel_id"):
                continue
            self.add_influencer(rec)
            n += 1
        return n

    def import_flow(self, rec):
        """流程导入：按 (channel_id, plan_month) upsert。
        Phase 1 语义 = 与宜搭版一致：文档写了哪一行就改哪一行。
        跨月覆盖 recruiter 的旧 force_channel_recruiter 从未生效，此处保持不动。"""
        rec = dict(rec or {})
        rec.setdefault("plan_month", "")
        r = self._upsert_row(rec)
        return r or rec

    def mark_emailed(self, inf_id, actor: str = ""):
        cid, month = _split(inf_id)
        patch = {"email_status": "已发送", "stage": "已发邮件"}
        # Phase 2：谁发邮件，归属当场覆盖成谁（不留历史）
        a = (actor or "").strip()
        if a:
            patch["recruiter"] = a
        return self._patch_row(cid, month, patch)

    def mark_negotiating(self, inf_id, actor: str = ""):
        cid, month = _split(inf_id)
        patch = {"stage": "洽谈中"}
        # Phase 2：推进到洽谈（含拿到回复）同样覆盖归属为当前操作人
        a = (actor or "").strip()
        if a:
            patch["recruiter"] = a
        return self._patch_row(cid, month, patch)

    def unmark_emailed(self, inf_id):
        cid, month = _split(inf_id)
        return self._patch_row(cid, month, {},
                               clear_fields=["email_status", "stage"])

    def unmark_negotiating(self, inf_id):
        cid, month = _split(inf_id)
        return self._patch_row(cid, month, {"stage": "已发邮件"})

    def sync_yt_subscribers(self, ids):
        import yts_yt_stats as YT
        if not YT.get_key():
            return 0
        rows = self._all()
        n = 0
        seen = set()
        for ident in ids:
            cid = _split(ident)[0]
            if not cid or cid in seen:
                continue
            seen.add(cid)
            sub = 0
            if str(cid).startswith("UC"):
                sub = int((YT.fetch_stats(cid) or {}).get("subscribers") or 0)
            else:
                url = next((r.get("channel_url") for r in rows
                            if r.get("channel_id") == cid), "")
                handle = YT.handle_from_url(url) or YT.handle_from_url(cid)
                if handle:
                    sub = int((YT.fetch_stats_by_handle(handle) or {}).get("subscribers") or 0)
            if sub <= 0:
                continue
            for r in rows:
                if r.get("channel_id") == cid:
                    self._patch_row(cid, r.get("plan_month") or "",
                                    {"subscribers": sub})
            self._invalidate()
            n += 1
        return n

    def url_index(self):
        return {(r.get("channel_url") or "").strip(): r.get("channel_id")
                for r in self._all() if r.get("channel_url")}

    def existing_url_months(self):
        import re

        def norm_u(u):
            return re.sub(r"^https?://(www\.)?", "",
                          str(u or "").strip().rstrip("/"))
        url_pairs, cid_pairs = set(), set()
        for r in self._all():
            m = str(r.get("plan_month") or "").strip()
            u = norm_u(r.get("channel_url"))
            if u:
                url_pairs.add((u, m))
            cid = r.get("channel_id")
            if cid:
                cid_pairs.add((str(cid), m))
        return url_pairs, cid_pairs

    # ---------------- 活动模块 ----------------
    def _dedup_identity(self, collabs):
        out = {}
        for c in collabs:
            k = c["collab_id"]
            prev = out.get(k)
            if prev is None or (c.get("follow_time") or "") >= (prev.get("follow_time") or ""):
                out[k] = c
        return list(out.values())

    def list_negotiating(self):
        return self._dedup_identity(
            [c for c in (self._to_collab(r) for r in self._all())
             if c["status"] == "洽谈中"])

    def list_fulfilling(self):
        return self._dedup_identity(
            [c for c in (self._to_collab(r) for r in self._all())
             if c["status"] == "履约中"])

    _STAGE_PRIO = {"已闭环": 4, "履约中": 3, "洽谈中": 2, "已发邮件": 1}

    def count_stages(self):
        best = {}

        def consider(cid, stage):
            if not cid:
                return
            p = self._STAGE_PRIO.get(stage, 0)
            if cid not in best or self._STAGE_PRIO.get(best[cid], 0) < p:
                best[cid] = stage

        for c in self.list_fulfilling():
            consider(c.get("channel_id"),
                     "已闭环" if c.get("is_closed") else "履约中")
        for c in self.list_negotiating():
            consider(c.get("channel_id"), "洽谈中")
        for c in self.list_pool():
            if c.get("emailed"):
                consider(c.get("id"), "已发邮件")

        out = {"已发邮件": 0, "洽谈中": 0, "履约中": 0, "已闭环": 0}
        for stage in best.values():
            out[stage] = out.get(stage, 0) + 1
        return out

    def list_all(self):
        return [self._to_collab(r) for r in self._all()]

    def get_collab(self, collab_id, fresh: bool = False):
        if fresh:
            self._invalidate()
        r = self._get(collab_id)
        return self._to_collab(r) if r else None

    # ---------------- 编辑基本信息 ----------------
    EDIT_FIELDS = ("price", "plan_month", "email", "channel_url",
                   "group_link", "submit_deadline", "notes",
                   "settlement", "settlement_note")
    CLEARABLE = ("notes", "group_link", "email", "submit_deadline",
                 "settlement_note")

    def update_info(self, collab_id, fields: dict):
        patch, clear = {}, []
        for k, v in (fields or {}).items():
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

    # ---------------- 三分支 ----------------
    def set_branch(self, collab_id, branch, done):
        m = {"guideline": "guideline_status",
             "contract": "contract_status",
             "gmc": "gmc_status"}
        v = {"guideline": "已发送", "contract": "已签", "gmc": "校验通过"}
        col = m.get(branch)
        if not col:
            return
        if done:
            self._upd(collab_id, {col: v[branch]})
        else:
            self._upd(collab_id, {}, clear_fields=[col])

    def branches_all_done(self, collab_id):
        c = self.get_collab(collab_id) or {}
        return all((c.get("branches") or {}).values())

    def set_products(self, collab_id, product_list):
        joined = "\n".join([p for p in (product_list or []) if p])
        self._upd(collab_id, {"product_list": joined})

    # ---------------- 下单 / 收货 / 拍摄 ----------------
    def mark_order(self, collab_id):
        self._upd(collab_id, {"order_status": "已下单", "stage": "已下单"})

    def mark_received(self, collab_id):
        self._upd(collab_id, {"order_status": "已收货"})

    def mark_shoot(self, collab_id, status):
        self._upd(collab_id, {"shoot_status": status, "stage": "拍摄中"})

    # ---------------- 视频/商品明细（存 JSONB） ----------------
    def _row_to_ui(self, collab_id):
        return self._get(collab_id) or {}

    def save_videos(self, collab_id, videos):
        self._upd(collab_id, {"videos": list(videos or [])})

    def merge_videos(self, collab_id, rows):
        cur = list((self._get(collab_id) or {}).get("videos") or [])
        cur.extend(list(rows or []))
        self._upd(collab_id, {"videos": cur})

    def update_video_row(self, collab, index, patch):
        cid = collab.get("collab_id") or collab.get("channel_id")
        r = self._get(cid) or {}
        videos = [dict(v) for v in (r.get("videos") or [])]
        if not (0 <= index < len(videos)):
            return
        videos[index].update(patch)
        self._upd(cid, {"videos": videos})

    def update_video_metrics(self, collab, views, likes, comments):
        cid = collab.get("collab_id") or collab.get("channel_id")
        self._upd(cid, {"video_views": int(views),
                        "video_likes": int(likes),
                        "video_comments": int(comments)})
        return True

    def update_product_metrics(self, collab, clicks, ctr, orders, gmv):
        cid = collab.get("collab_id") or collab.get("channel_id")
        conv = round(orders / clicks * 100, 2) if clicks else 0.0
        self._upd(cid, {"product_views": int(clicks),
                        "ctr": float(ctr),
                        "orders": int(orders),
                        "conversion_rate": conv,
                        "gmv": float(gmv)})
        return True

    def save_products(self, collab_id, products):
        self._upd(collab_id, {"products": list(products or [])})

    def update_video_link(self, collab_id, new_url: str):
        self._upd(collab_id, {"video_link": (new_url or "").strip()})

    # ---------------- 提交审核 ----------------
    def submit_review(self, collab_id, video_url):
        self._upd(collab_id, {"video_link": video_url,
                              "audit_status": "待审核",
                              "stage": "已交视频",
                              "submit_actual": _now_min()})
        rec = self._get(collab_id) or {}
        return N.notify_review_submitted(rec.get("channel_name") or collab_id,
                                         video_url)

    def sync_review_states(self):
        """Supabase 读取近实时，同进程 2s TTL；跨进程最坏 2s 收敛，无需显式对账"""
        return []

    # ---------------- 审核网站 ----------------
    def list_pending_reviews(self):
        return [c for c in (self._to_collab(r) for r in self._all())
                if c["review_status"] == "待审核"]

    def list_review_history(self):
        return [c for c in (self._to_collab(r) for r in self._all())
                if c["review_status"] in ("已通过", "已驳回", "复审通过", "复审中")]

    def _add_audit(self, collab_id, result, opinion, date_str=None):
        r = self._get(collab_id) or {}
        log = list(r.get("audit_log") or [])
        log.append({"audit_date": date_str or _now_min(),
                    "audit_result": result, "audit_opinion": opinion})
        self._upd(collab_id, {"audit_log": log})

    def review_pass(self, collab_id, note=""):
        self._add_audit(collab_id, "已通过", note or "审核通过")
        self._upd(collab_id, {"audit_status": "已通过"})
        return self._notify_result(collab_id, "已通过", note or "审核通过")

    def review_reject(self, collab_id, reason):
        self._add_audit(collab_id, "未通过", reason)
        self._upd(collab_id, {"audit_status": "未通过", "stage": "修改中"})
        return self._notify_result(collab_id, "未通过", reason)

    def _notify_result(self, collab_id, result, opinion):
        rec = self._get(collab_id) or {}
        return N.notify_review_result(rec.get("channel_name") or collab_id,
                                      result, opinion,
                                      rec.get("recruiter") or "",
                                      detail_id=collab_id)

    # ---------------- 复审 ----------------
    def start_recheck(self, collab_id, new_video_url):
        self._upd(collab_id, {"recheck_video_url": new_video_url})

    def recheck_pass(self, collab_id):
        self._add_audit(collab_id, "已通过", "复审通过")
        self._upd(collab_id, {"audit_status": "已通过"})
        return self._notify_result(collab_id, "已通过", "复审通过")

    def recheck_reject(self, collab_id, reason):
        self._add_audit(collab_id, "未通过", f"复审驳回：{reason}")
        self._upd(collab_id, {"audit_status": "未通过", "recheck_video_url": ""})
        return self._notify_result(collab_id, "未通过", f"复审驳回：{reason}")

    # ---------------- 审核站表格 ----------------
    def list_review_table(self):
        order = {"待审核": 0, "未通过": 1, "已通过": 2}
        rows, hidden = [], 0
        for c in (self._to_collab(r) for r in self._all()):
            if not c["video_url"] and not c["recheck_video_url"]:
                continue
            rs = c["review_status"]
            if not rs:
                continue
            if not (c["plan_month"] or c["is_closed"]):
                hidden += 1
                continue
            passed = "Y" if rs in ("已通过", "复审通过") else ("N" if rs in ("已驳回", "复审中") else "")
            reason = c["review_comment"] if rs in ("已驳回", "复审中") else ""
            rows.append({
                "collab_id": c["collab_id"],
                "name": c["name"],
                "channel_url": c["channel_url"],
                "review_url": c["recheck_video_url"] or c["video_url"],
                "passed": passed,
                "reason": reason or "",
                "status": rs,
                "submit_actual": c.get("submit_actual") or "",
                "audit_time": c.get("audit_time") or "",
                "plan_month": c.get("plan_month") or "",
                "is_closed": bool(c.get("is_closed")),
            })
        self._review_hidden = hidden
        rows.sort(key=lambda x: (order.get(
            {"Y": "已通过", "N": "未通过"}.get(x["passed"], "待审核"), 3), x["name"]))
        return rows

    def apply_review_results(self, changes):
        cur = {c["collab_id"]: c for c in
               (self._to_collab(r) for r in self._all())}
        applied, failed = [], []
        now_min = _now_min()
        for ch in changes or []:
            cid = (ch.get("collab_id") or "").strip()
            passed = str(ch.get("passed") or "").strip().upper()
            if not cid or passed not in ("Y", "N") or cid not in cur:
                continue
            c = cur[cid]
            reason = str(ch.get("reason") or "").strip()
            already = ("Y" if c["review_status"] in ("已通过", "复审通过")
                       else "N" if c["review_status"] in ("已驳回", "复审中") else "")
            if passed == already and (passed == "Y" or reason == (c["review_comment"] or "").strip()):
                continue
            if passed == "Y":
                self._add_audit(cid, "已通过", reason or "审核通过", now_min)
                self._upd(cid, {"audit_status": "已通过"})
                applied.append((c["name"], "✅通过", reason or "审核通过"))
            else:
                self._add_audit(cid, "未通过", reason or "审核未通过", now_min)
                self._upd(cid, {"audit_status": "未通过", "stage": "修改中"})
                applied.append((c["name"], "❌驳回", reason or "审核未通过"))
        if not applied:
            return 0, True, "没有需要更新的审核结果"
        nok, nmsg = N.notify_review_results_batch(applied)
        if failed:
            nmsg = (nmsg + f"；⚠️ {len(failed)} 条写入失败：" + "、".join(failed[:10]))
            nok = False
        return len(applied), nok, nmsg

    def list_ad_table(self):
        rows = []
        for c in (self._to_collab(r) for r in self._all()):
            if not ((c["ad_needed"] or c["ad_done"]) and (c["plan_month"] or c["is_closed"])):
                continue
            vurls = []
            for v in (c.get("videos") or []):
                u = (v.get("video_url") or "").strip()
                if u and u not in vurls:
                    vurls.append(u)
            for u in (c.get("video_url") or "", c.get("recheck_video_url") or ""):
                u = u.strip()
                if u and u not in vurls:
                    vurls.append(u)
            rows.append({
                "collab_id": c["collab_id"], "name": c["name"],
                "channel_url": c["channel_url"],
                "video_urls": "\n".join(vurls),
                "ad_needed": "Y" if c["ad_needed"] else "",
                "ad_done": "Y" if c["ad_done"] else "",
            })
        rows.sort(key=lambda x: (0 if x["ad_needed"] and not x["ad_done"] else 1,
                                 x["name"]))
        return rows

    def apply_ad_results(self, changes):
        cur = {c["collab_id"]: c for c in
               (self._to_collab(r) for r in self._all())}
        n = 0
        for ch in changes or []:
            cid = (ch.get("collab_id") or "").strip()
            if not cid or cid not in cur:
                continue
            done = str(ch.get("ad_done") or "").strip().upper() == "Y"
            if done == cur[cid]["ad_done"]:
                continue
            self._upd(cid, {"ad_done": done})
            n += 1
        return n

    # ---------------- 上传确认 → 闭环 ----------------
    def confirm_uploaded(self, collab_id, video_url=None, ad_needed=False):
        patch = {"stage": "已完成", "ad_needed": bool(ad_needed)}
        if video_url:
            patch["video_link"] = video_url
        self._upd(collab_id, patch)

    # ---------------- 反向：取消 / 流回 / 淘汰 ----------------
    def cancel_collab(self, collab_id):
        """取消合作：退回洽谈中、清空归属月份、进度字段保留。
        主键含 plan_month，只能"删旧月份行 + 重建为裸行"。"""
        cid, month = _split(collab_id)
        if month:
            row = self._get(collab_id) or {}
            if not row:
                return
            payload = {k: v for k, v in row.items()
                       if k not in ("id", "created_at", "updated_at", "plan_month")}
            payload["plan_month"] = ""
            payload["stage"] = "洽谈中"
            self._delete_row(cid, month)
            self._upsert_row({"channel_id": cid, **payload})
        else:
            self._upd(collab_id, {"stage": "洽谈中"})

    def back_to_pool(self, collab_id):
        """流回挖掘库：删除该月份合作记录，网红留在挖掘池"""
        cid, month = _split(collab_id)
        if month:
            self._delete_row(cid, month)
            return
        # 裸行：清进度，保留 basic info
        self._upd(collab_id, {"stage": "已发邮件", "email_status": "已发送"},
                  clear_fields=["plan_month"])

    def remove_influencer(self, collab_id):
        """淘汰：清 email/stage/plan 回到未触达"""
        cid, month = _split(collab_id)
        if month:
            # 月份行直接删；频道级信息（若有裸行）另清
            self._delete_row(cid, month)
            bare = self._get(cid)
            if bare:
                self._patch_row(cid, "", {}, clear_fields=[
                    "email_status", "stage", "plan_month"])
            return
        self._patch_row(cid, "", {},
                        clear_fields=["email_status", "stage", "plan_month"])

    def remove_record(self, collab_id):
        cid, month = _split(collab_id)
        row = self._get(collab_id)
        if row is None:
            return False
        self._delete_row(cid, month)
        return True

    def delete_record(self, collab_id):
        return self.remove_record(collab_id)

    def channel_rows(self, channel_id):
        out = []
        for r in self._all():
            if (r.get("channel_id") or "") != channel_id:
                continue
            c = self._to_collab(r)
            out.append({
                "collab_id": c["collab_id"],
                "month": (str(c.get("plan_month") or "").strip() or "（无月份 · 挖掘中）"),
                "stage": (c.get("stage") or c.get("status") or "-"),
                "has_instance": True,
            })
        out.sort(key=lambda x: x["month"])
        return out

    def remove_channel(self, channel_id):
        """彻底删除某频道所有月份行 + 裸行；返回删除条数"""
        rows = [r for r in self._all() if (r.get("channel_id") or "") == channel_id]
        n = 0
        for r in rows:
            try:
                self._delete_row(channel_id, r.get("plan_month") or "")
                n += 1
            except Exception:
                continue
        return n

    # ---------------- 挖掘站同步（Phase 1 保持宜搭版语义不变） ----------------
    def sync_from_discovery(self, force: bool = False) -> dict:
        rows = R.fetch_emailed_channels(force=force)
        by_cid = {}
        for r in self._all():
            by_cid.setdefault(r.get("channel_id"), []).append(r)
        added = patched = 0
        for x in rows:
            cid = (x.get("channel_id") or "").strip()
            if not cid:
                continue
            if cid not in by_cid:
                rec = self._upsert_row({
                    "channel_id": cid,
                    "plan_month": "",
                    "channel_name": x.get("channel_name") or "",
                    "channel_url": x.get("channel_url") or "",
                    "category": (x.get("content_category") or "").strip(),
                    "sales_category": (x.get("category") or "").strip(),
                    "subscribers": int(x.get("subscribers") or 0),
                    "recruiter": x.get("discovered_by") or "",
                    "email": (x.get("emails") or "").strip(),
                    "email_status": "已发送", "stage": "已发邮件",
                })
                by_cid[cid] = [rec or {"channel_id": cid, "plan_month": ""}]
                added += 1
            else:
                did = False
                for cur in by_cid[cid]:
                    patch = {}
                    if not cur.get("email_status"):
                        patch["email_status"] = "已发送"
                        if not cur.get("stage"):
                            patch["stage"] = "已发邮件"
                    new_sub = int(x.get("subscribers") or 0)
                    cur_sub = int(cur.get("subscribers") or 0)
                    if new_sub > 0 and new_sub != cur_sub:
                        patch["subscribers"] = new_sub
                    new_content = (x.get("content_category") or "").strip()
                    if new_content and new_content != (cur.get("category") or "").strip():
                        patch["category"] = new_content
                    new_commerce = (x.get("category") or "").strip()
                    if new_commerce and new_commerce != (cur.get("sales_category") or "").strip():
                        patch["sales_category"] = new_commerce
                    if not (cur.get("email") or "").strip() and (x.get("emails") or "").strip():
                        patch["email"] = x["emails"].strip()
                    # Phase 1 保留"只填空不覆盖"（Phase 2 会切规则）
                    new_rec = (x.get("discovered_by") or "").strip()
                    cur_rec = (cur.get("recruiter") or "").strip()
                    if new_rec and not cur_rec:
                        patch["recruiter"] = new_rec
                    if not patch:
                        continue
                    try:
                        self._patch_row(cid, cur.get("plan_month") or "", patch)
                        did = True
                    except Exception:
                        continue
                patched += 1 if did else 0
        self._invalidate()
        return {"added": added, "patched": patched, "total": len(rows)}

    def sync_basic_info(self, force=False, progress=None, limit=0):
        rows = R.fetch_all_channels(force=force)
        if not rows:
            return {"matched": 0, "updated": 0, "total": 0, "emails_filled": 0}
        idx = {x.get("channel_id"): x for x in rows if x.get("channel_id")}
        url_idx = {(x.get("channel_url") or "").strip().rstrip("/"): x
                   for x in rows if x.get("channel_url")}
        recs = self._all()
        matched = updated = emails_filled = 0
        for i, rec in enumerate(recs):
            if progress:
                progress(i, len(recs))
            cid = (rec.get("channel_id") or "").strip()
            m = idx.get(cid) or url_idx.get((rec.get("channel_url") or "").strip().rstrip("/"))
            if not m:
                continue
            matched += 1
            patch = {}
            new_sub = int(m.get("subscribers") or 0)
            cur_sub = int(rec.get("subscribers") or 0)
            if new_sub > 0 and new_sub != cur_sub:
                patch["subscribers"] = new_sub
            new_content = (m.get("content_category") or "").strip()
            if new_content and new_content != (rec.get("category") or "").strip():
                patch["category"] = new_content
            new_commerce = (m.get("category") or "").strip()
            if new_commerce and new_commerce != (rec.get("sales_category") or "").strip():
                patch["sales_category"] = new_commerce
            if not (rec.get("channel_name") or "").strip() and (m.get("channel_name") or "").strip():
                patch["channel_name"] = m["channel_name"].strip()
            if not (rec.get("email") or "").strip() and (m.get("emails") or "").strip():
                patch["email"] = m["emails"].strip()
            new_rec = (m.get("discovered_by") or "").strip()
            cur_rec = (rec.get("recruiter") or "").strip()
            if new_rec and not cur_rec:
                patch["recruiter"] = new_rec
            if not patch:
                continue
            if limit and updated >= limit:
                continue
            try:
                self._patch_row(cid, rec.get("plan_month") or "", patch)
                updated += 1
                if "email" in patch:
                    emails_filled += 1
            except Exception:
                continue
        if progress:
            progress(len(recs), len(recs))
        self._invalidate()
        return {"matched": matched, "updated": updated, "total": len(rows),
                "emails_filled": emails_filled}

    def confirm_collab(self, collab_id, plan_month, price=0,
                       reusable=None, settle_note=""):
        """确认合作 = 把该行月份改写为 plan_month。因主键含 plan_month，
        正确姿势 = 复制当前行到新 (channel_id, plan_month) → 删旧行 → 写新行。"""
        cid, old_month = _split(collab_id)
        plan_month = str(plan_month or "").strip()
        if not plan_month or not plan_month.startswith("20"):
            # 允许宽松格式，非 YYYY-MM 时也照样写
            pass
        cur = self._get(collab_id) or {}
        if not cur:
            return
        patch = {"stage": "已确认", "price": int(price or 0)}
        if reusable is not None:
            patch["settlement"] = "可二次利用" if reusable else "不可二次利用"
        if settle_note:
            patch["settlement_note"] = str(settle_note).strip()
        for k, v in patch.items():
            cur[k] = v
        cur["plan_month"] = plan_month
        for k in ("id", "created_at", "updated_at", "channel_id"):
            cur.pop(k, None)
        if old_month != plan_month:
            self._delete_row(cid, old_month)
        self._upsert_row({"channel_id": cid, **cur})
        try:
            R.mark_introduced(cid)
        except Exception:
            pass

    def push_back_introduced(self, force=False) -> int:
        fuls = [r for r in self._all() if (r.get("plan_month") or "").strip()]
        if not fuls:
            return 0
        statuses = R.fetch_statuses(force=force)
        n = 0
        seen = set()
        for r in fuls:
            cid = r.get("channel_id")
            if not cid or cid in seen or cid not in statuses:
                continue
            seen.add(cid)
            if statuses[cid] != "已引入":
                try:
                    R.mark_introduced(cid)
                    n += 1
                except Exception:
                    pass
        return n

    # ---------------- 误判履约 → 洽谈退回（同 Yida 语义） ----------------
    def demote_preview(self):
        from yts_import_flow import has_fulfillment
        rows = list(self._all())
        bare_cids = {r.get("channel_id") for r in rows
                     if not str(r.get("plan_month") or "").strip()}
        safe, conflict = [], []
        for r in rows:
            pm = str(r.get("plan_month") or "").strip()
            if not pm or (r.get("stage") or "") == "已完成" \
                    or has_fulfillment(r):
                continue
            item = {"collab_id": _ident(r),
                    "channel_id": r.get("channel_id") or "",
                    "plan_month": pm,
                    "has_row": True,
                    "name": r.get("channel_name") or r.get("channel_id") or "?"}
            (conflict if r.get("channel_id") in bare_cids else safe).append(item)
        return safe, conflict

    def demote_false_fulfilling(self):
        safe, _ = self.demote_preview()
        n = 0
        for it in safe:
            cid, month = _split(it["collab_id"])
            row = self._get(it["collab_id"]) or {}
            if not row:
                continue
            new = dict(row)
            for k in ("id", "created_at", "updated_at"):
                new.pop(k, None)
            new["plan_month"] = ""
            new["stage"] = "洽谈中"
            try:
                self._delete_row(cid, month)
                self._upsert_row(new)
                n += 1
            except Exception:
                continue
        self._invalidate()
        return n, len(safe)

    # ---------------- 步骤回退 ----------------
    STEP_UNDO = {
        0: lambda: ({"plan_month": "", "stage": "洽谈中"}, ["plan_month"]),
        1: lambda: ({"guideline_status": "", "contract_status": "",
                     "gmc_status": ""},
                    ["guideline_status", "contract_status", "gmc_status"]),
        2: lambda: ({"order_status": "已下单"}, ["order_status"]),
        3: lambda: ({"order_status": "已下单"}, []),
        4: lambda: ({"shoot_status": "", "stage": "已确认"}, ["shoot_status"]),
        5: lambda: ({"video_link": "", "stage": "拍摄中"}, ["video_link", "audit_status"]),
        6: lambda: ({"audit_status": "", "recheck_video_url": "",
                     "stage": "已交视频"}, ["audit_status", "recheck_video_url"]),
        7: lambda: ({"stage": "已交视频"}, []),
    }

    def undo_step(self, collab_id, step):
        fn = self.STEP_UNDO.get(step)
        if not fn:
            return False
        patch, clear = fn()
        # step 0/1 会破坏身份（plan_month 变），走 rebuild 路径
        if step == 0:
            cid, old = _split(collab_id)
            row = self._get(collab_id) or {}
            if not row:
                return False
            new = {k: v for k, v in row.items()
                   if k not in ("id", "created_at", "updated_at", "plan_month")}
            self._delete_row(cid, old)
            new["plan_month"] = ""
            new["stage"] = "洽谈中"
            self._upsert_row({"channel_id": cid, **new})
            return True
        self._upd(collab_id, patch, clear_fields=clear)
        return True


# ---- 类型集合（供 _encode_val 用；放模块底部避免顶部引用问题） ----
_TEXT_COLS_SET = set(YTSStore._TEXT_COLS)
_INT_COLS_SET = set(YTSStore._INT_COLS)
_NUM_COLS_SET = set(YTSStore._NUM_COLS)
_BOOL_COLS_SET = set(YTSStore._BOOL_COLS)
_JSON_COLS_SET = set(YTSStore._JSON_COLS)
