#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宜搭 BD 网红底库数据层（阿里钉 aliding 网关版）

- 走 aliding.aliyuncs.com 网关，阿里云 AK/SK 签名鉴权
- 与 LocalBDDB / SupabaseBDDB 同接口：add / get_all / get_by_channel_id /
  update / delete / bulk_update_metrics / sync_from_discovery
- fieldId 已按表单实际组件硬编码（2026-08-12 实测获取）

依赖：
    pip install alibabacloud_aliding20230426 alibabacloud_tea_openapi alibabacloud_tea_util
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

from alibabacloud_aliding20230426.client import Client
from alibabacloud_aliding20230426 import models as aliding_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

ENDPOINT = "aliding.aliyuncs.com"

# ---------------------------------------------------------------------------
# fieldId 映射（来自 GetFormComponentDefinitionList 实测结果）
# 代码名 -> fieldId
# ---------------------------------------------------------------------------
FIELD_IDS = {
    "channel_id": "textField_msn2qhnb",        # 频道ID（唯一）
    "channel_name": "textField_msn2qhnd",      # 昵称
    "channel_url": "textField_msn2qhnh",       # YouTube主页
    "category": "selectField_msn2qhnj",        # 垂类
    "recruiter": "textField_msn2qhnl",         # 挖掘人
    "subscribers": "numberField_msn2qhnp",     # 粉丝数
    "total_views": "numberField_msn2qhnt",     # 总播放
    "status": "selectField_msn2qhnx",          # 状态
    "video_link": "textField_msn2qhnz",        # 视频回链
    "video_views": "numberField_msn2qho1",     # 播放量
    "video_likes": "numberField_msn2qho5",     # 点赞数
    "video_comments": "numberField_msn2qho7",  # 评论数
    "product_link": "textField_msn2qho9",      # 商品链接
    "product_views": "numberField_msn2qhob",   # 浏览量
    "ctr": "numberField_mspqr44w",             # 点击率（CTR）
    "orders": "numberField_mspqr44x",          # 成交量
    "conversion_rate": "numberField_msn2qhod", # 转化率
    "gmv": "numberField_msn2qhof",             # GMV
    "price": "numberField_mspqr44z",           # 报价
    "notes": "textareaField_msn2qhoj",         # 备注
    # ---- YTS 项目流程字段（2026-08-12 第二批实测） ----
    "stage": "selectField_mspwxzct",           # 合作阶段
    "email_status": "selectField_mspwxzcv",    # 邮件状态
    "settlement": "selectField_mspwxzcx",      # 结算方式
    "group_link": "textField_mspwxzcz",        # 群链接
    "contract_status": "selectField_mspwxzd3", # 合同状态
    "order_status": "selectField_mspwxzd5",    # 下单状态
    "submit_deadline": "dateField_mspwxzd7",   # 交稿截止
    "submit_actual": "dateField_mspwxzd9",     # 实际提交时间
    "ad_auth": "selectField_mspwxzdb",         # 投放授权
    "audit_status": "selectField_mspwxzdd",    # 审核状态
    "audit_log": "tableField_mspwxzdf",        # 子表单（审核记录）
    # ---- YTS 正式版字段（2026-08-17 第三批实测） ----
    "plan_month": "textField_mswndfpl",        # 计划上线月份
    "shoot_status": "selectField_mswndfpm",    # 拍摄状态（未开始/拍摄中/已完成）
    "recheck_video_url": "textField_mswndfpn", # 复审视频链接
    "gmc_status": "selectField_mswndfpo",      # GMC校验状态（未校验/校验通过）
    "product_list": "textareaField_mswndfpp",  # 选品清单（每行一个链接）
    "guideline_status": "selectField_mswndfpr",# Guideline状态（未发送/已发送）
    "email": "textField_mswndfpt",             # 联系邮箱
    # ---- 视频明细子表（2026-08-20 第四批） ----
    "videos": "tableField_mt0hcgfr",           # 子表容器：视频明细
}

# 子表（审核记录）内部字段映射
AUDIT_SUB_FIELD_IDS = {
    "audit_date": "dateField_mspwxzdg",        # 子表单-审核日期
    "audit_result": "selectField_mspwxzdh",    # 子表单-审核结果
    "audit_opinion": "textareaField_mspwxzdi", # 子表单-审核意见
}

# 子表（视频明细）内部字段映射：代码名 -> fieldId
VIDEO_SUB_FIELD_IDS = {
    "video_type": "radioField_mt0hcgfs",       # 视频类型（长视频/Shorts）
    "video_url": "textField_mt0hcgg7",         # 视频链接
    "product_ids": "textField_mt0hcgg8",       # 关联商品（逗号分隔的商品ID）
    "views": "numberField_mt0hcgfu",           # 播放量
    "likes": "numberField_mt0hcggfw",          # 点赞
    "comments": "numberField_mt0hcggfy",       # 评论
    "clicks": "numberField_mt0hcgg0",          # 点击量
    "ctr": "numberField_mt0hcgg2",             # CTR
    "orders": "numberField_mt0hcgg4",          # 成交量
    "gmv": "numberField_mt0hcgg6",             # GMV
}

# 视频明细子表内的浮点字段（写入时保留小数）
VIDEO_FLOAT_FIELDS = {"ctr", "gmv"}

NUMBER_FIELDS = {
    "subscribers", "total_views", "video_views", "video_likes", "video_comments",
    "product_views", "ctr", "orders", "conversion_rate", "gmv", "price",
}

CODE_TO_LABEL = {
    "channel_id": "频道ID", "channel_name": "昵称", "channel_url": "YouTube主页",
    "category": "垂类", "recruiter": "挖掘人", "subscribers": "粉丝数",
    "total_views": "总播放", "status": "状态", "video_link": "视频回链",
    "video_views": "播放量", "video_likes": "点赞数", "video_comments": "评论数",
    "product_link": "商品链接", "product_views": "浏览量",
    "ctr": "点击率", "orders": "成交量",
    "conversion_rate": "转化率", "gmv": "GMV", "price": "报价", "notes": "备注",
    "stage": "合作阶段", "email_status": "邮件状态", "settlement": "结算方式",
    "group_link": "群链接", "contract_status": "合同状态", "order_status": "下单状态",
    "submit_deadline": "交稿截止", "submit_actual": "实际提交时间",
    "ad_auth": "投放授权", "audit_status": "审核状态", "audit_log": "审核记录",
    "plan_month": "计划上线月份", "shoot_status": "拍摄状态",
    "recheck_video_url": "复审视频链接", "gmc_status": "GMC校验状态",
    "product_list": "选品清单", "guideline_status": "Guideline状态",
    "email": "联系邮箱",
}

# 日期类字段（宜搭 dateField 只接受毫秒时间戳，字符串会报"日期组件值的格式错误"）
DATE_FIELDS = {"submit_deadline", "submit_actual"}

_TZ_CN = timezone(timedelta(hours=8))


def _date_to_ms(value):
    """YYYY-MM-DD（或时间戳）-> 毫秒时间戳；无法解析时返回 None（跳过该字段）"""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).replace(
                tzinfo=_TZ_CN).timestamp() * 1000)
        except ValueError:
            continue
    return None


def _ms_to_date(value):
    """毫秒时间戳 -> YYYY-MM-DD；非时间戳原样返回"""
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return value
    return datetime.fromtimestamp(ms / 1000, _TZ_CN).strftime("%Y-%m-%d")


class YidaBDDB:
    """基于阿里钉 aliding 网关的宜搭 BD 底库（团队共享数据源）"""

    def __init__(self, access_key_id: str, access_key_secret: str,
                 app_type: str, system_token: str, form_uuid: str,
                 account_id: str):
        config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        config.endpoint = ENDPOINT
        self._client = Client(config)
        self.app_type = app_type
        self.system_token = system_token
        self.form_uuid = form_uuid
        self.account_id = account_id
        # 超时保护：10人共用下，宜搭接口卡死会拖住所有用户的请求
        self._runtime = util_models.RuntimeOptions(
            connect_timeout=5000, read_timeout=20000)

    # ------------------------- 内部工具 -------------------------

    def _headers(self, api_name: str):
        """构造 XxxHeaders（account_context 填工号）"""
        headers_cls = getattr(aliding_models, f"{api_name}Headers")
        ctx_cls = getattr(aliding_models, f"{api_name}HeadersAccountContext")
        return headers_cls(account_context=ctx_cls(account_id=self.account_id))

    def _to_form_data(self, record: dict) -> dict:
        out = {}
        for code, value in record.items():
            fid = FIELD_IDS.get(code, "")
            if not fid or value is None or value == "":
                continue
            if code in NUMBER_FIELDS:
                try:
                    value = float(value)
                    if value == int(value) and code not in ("ctr", "conversion_rate"):
                        value = int(value)
                except (TypeError, ValueError):
                    continue
            elif code in DATE_FIELDS:
                value = _date_to_ms(value)
                if value is None:
                    continue
            elif code == "audit_log":
                # 子表：value 是列表，每项为 {"audit_date","audit_result","audit_opinion"}
                value = [self._to_audit_row(row) for row in (value or [])]
            elif code == "videos":
                # 子表：视频明细，每项字段见 VIDEO_SUB_FIELD_IDS
                value = [self._to_video_row(row) for row in (value or [])]
            else:
                value = str(value)
            out[fid] = value
        return out

    @staticmethod
    def _to_video_row(row: dict) -> dict:
        """视频明细行 → 宜搭子表行（fieldId: value）"""
        out = {
            VIDEO_SUB_FIELD_IDS["video_type"]: str(row.get("video_type", "")),
            VIDEO_SUB_FIELD_IDS["video_url"]: str(row.get("video_url", "")),
            VIDEO_SUB_FIELD_IDS["product_ids"]: str(row.get("product_ids", "")),
        }
        for code in ("views", "likes", "comments", "clicks", "ctr",
                     "orders", "gmv"):
            try:
                v = float(row.get(code) or 0)
            except (TypeError, ValueError):
                continue
            if code in VIDEO_FLOAT_FIELDS:
                out[VIDEO_SUB_FIELD_IDS[code]] = round(v, 2)
            else:
                out[VIDEO_SUB_FIELD_IDS[code]] = int(v)
        return out

    @staticmethod
    def _from_video_row(row: dict) -> dict:
        """宜搭子表行 → 视频明细行（代码名: value）"""
        rev = {v: k for k, v in VIDEO_SUB_FIELD_IDS.items()}
        out = {}
        for fid, value in row.items():
            code = rev.get(fid, "")
            if code:
                out[code] = value
        return out

    @staticmethod
    def _to_audit_row(row: dict) -> dict:
        out = {
            AUDIT_SUB_FIELD_IDS["audit_result"]: str(row.get("audit_result", "")),
            AUDIT_SUB_FIELD_IDS["audit_opinion"]: str(row.get("audit_opinion", "")),
        }
        ms = _date_to_ms(row.get("audit_date", ""))
        if ms is not None:
            out[AUDIT_SUB_FIELD_IDS["audit_date"]] = ms
        return out

    @staticmethod
    def _from_audit_row(row: dict) -> dict:
        rev = {v: k for k, v in AUDIT_SUB_FIELD_IDS.items()}
        out = {}
        for fid, value in row.items():
            code = rev.get(fid, fid)
            if code == "audit_date":
                value = _ms_to_date(value)
            out[code] = value
        return out

    def _from_instance(self, inst: dict) -> dict:
        id_to_code = {v: k for k, v in FIELD_IDS.items() if v}
        raw = inst.get("FormData") or inst.get("formData") or {}
        rec = {"form_instance_id": inst.get("FormInstanceId") or inst.get("formInstanceId")}
        for fid, value in raw.items():
            code = id_to_code.get(fid)
            if not code:
                continue
            if code == "audit_log":
                # 子表返回的是行列表，每行 {fieldId: value}
                rows = value if isinstance(value, list) else []
                rec["audit_log"] = [self._from_audit_row(r) for r in rows]
            elif code == "videos":
                rows = value if isinstance(value, list) else []
                rec["videos"] = [self._from_video_row(r) for r in rows]
            else:
                if code in DATE_FIELDS:
                    value = _ms_to_date(value)
                rec[code] = value
        rec.setdefault("audit_log", [])
        rec.setdefault("videos", [])
        for ts_key, ts_code in (("CreatedTimeGMT", "created_at"),
                                ("ModifiedTimeGMT", "updated_at"),
                                ("createdTimeGMT", "created_at"),
                                ("modifiedTimeGMT", "updated_at")):
            if inst.get(ts_key):
                rec[ts_code] = str(inst[ts_key])
        return rec

    # ------------------------- 查询 -------------------------

    def _search_page(self, search_field: dict, page: int = 1, size: int = 100) -> dict:
        request = aliding_models.SearchFormDatasRequest(
            app_type=self.app_type,
            system_token=self.system_token,
            form_uuid=self.form_uuid,
            language="zh_CN",
            current_page=page,
            page_size=size,
            search_field_json=json.dumps(search_field, ensure_ascii=False),
        )
        resp = self._client.search_form_datas_with_options(
            request, self._headers("SearchFormDatas"), self._runtime)
        return resp.body.to_map()

    def _find_instance(self, channel_id: str) -> Optional[dict]:
        data = self._search_page({FIELD_IDS["channel_id"]: str(channel_id)}, size=1)
        rows = data.get("Data") or data.get("data") or []
        return rows[0] if rows else None

    # ------------------------- 业务接口（与 LocalBDDB 对齐） -------------------------

    def add(self, record: dict) -> dict:
        """新增或更新（以 channel_id 为主键的 upsert）"""
        if not record.get("channel_id"):
            raise ValueError("channel_id 为必填字段")
        existing = self._find_instance(record["channel_id"])
        form_data = self._to_form_data(record)
        if existing:
            instance_id = existing.get("FormInstanceId") or existing.get("formInstanceId")
            request = aliding_models.UpdateFormDataRequest(
                app_type=self.app_type,
                system_token=self.system_token,
                form_instance_id=instance_id,
                language="zh_CN",
                use_latest_version=True,
                update_form_data_json=json.dumps(form_data, ensure_ascii=False),
            )
            self._client.update_form_data_with_options(
                request, self._headers("UpdateFormData"), self._runtime)
        else:
            request = aliding_models.SaveFormDataRequest(
                app_type=self.app_type,
                system_token=self.system_token,
                form_uuid=self.form_uuid,
                language="zh_CN",
                form_data_json=json.dumps(form_data, ensure_ascii=False),
            )
            self._client.save_form_data_with_options(
                request, self._headers("SaveFormData"), self._runtime)
        return self.get_by_channel_id(record["channel_id"]) or record

    def get_by_channel_id(self, channel_id: str) -> Optional[dict]:
        inst = self._find_instance(channel_id)
        return self._from_instance(inst) if inst else None

    def get_all(self, filters: Optional[dict] = None) -> list:
        """全量分页拉取，支持等值过滤"""
        search_field = {}
        if filters:
            for code, value in filters.items():
                fid = FIELD_IDS.get(code, "")
                if fid and value not in (None, ""):
                    search_field[fid] = str(value)
        results = []

        def fetch(page):
            data = self._search_page(search_field, page=page, size=100)
            return data.get("Data") or data.get("data") or []

        rows = fetch(1)
        results.extend(self._from_instance(r) for r in rows)
        # 注意：aliding 响应不带 TotalCount，须以「不满一页」作为结束条件；
        # 第 2 页起每 4 页一批并行拉取，减少串行等待
        next_page = 2
        while len(rows) == 100:
            with ThreadPoolExecutor(max_workers=4) as ex:
                batch = list(ex.map(fetch, range(next_page, next_page + 4)))
            for rows in batch:
                results.extend(self._from_instance(r) for r in rows)
                if len(rows) < 100:
                    break
            next_page += 4
        results.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return results

    def update(self, channel_id: str, updates: dict,
               clear_fields: Optional[list] = None) -> Optional[dict]:
        """更新字段；clear_fields 里的字段显式清空为空串（编辑能力用）"""
        inst = self._find_instance(channel_id)
        if not inst:
            return None
        instance_id = inst.get("FormInstanceId") or inst.get("formInstanceId")
        form_data = self._to_form_data(updates)
        for code in clear_fields or ():
            fid = FIELD_IDS.get(code, "")
            if fid:
                form_data[fid] = ""
        request = aliding_models.UpdateFormDataRequest(
            app_type=self.app_type,
            system_token=self.system_token,
            form_instance_id=instance_id,
            language="zh_CN",
            use_latest_version=True,
            update_form_data_json=json.dumps(form_data, ensure_ascii=False),
        )
        self._client.update_form_data_with_options(
            request, self._headers("UpdateFormData"), self._runtime)
        # 不再回读验证：调用方（store层）会就地同步缓存，省1次HTTP提速约1/3
        return None

    def update_instance(self, instance_id: str, updates: dict,
                        clear_fields: Optional[list] = None) -> bool:
        """按实例ID直更（批量同步用）：不查找、不回读，单次 HTTP。
        clear_fields 里的字段显式清空为空串（清空类编辑用）"""
        form_data = self._to_form_data(updates)
        for code in clear_fields or ():
            fid = FIELD_IDS.get(code, "")
            if fid:
                form_data[fid] = ""
        request = aliding_models.UpdateFormDataRequest(
            app_type=self.app_type,
            system_token=self.system_token,
            form_instance_id=instance_id,
            language="zh_CN",
            use_latest_version=True,
            update_form_data_json=json.dumps(form_data, ensure_ascii=False),
        )
        self._client.update_form_data_with_options(
            request, self._headers("UpdateFormData"), self._runtime)
        return True

    def delete(self, channel_id: str) -> bool:
        inst = self._find_instance(channel_id)
        if not inst:
            return False
        instance_id = inst.get("FormInstanceId") or inst.get("formInstanceId")
        request = aliding_models.DeleteFormDataRequest(
            app_type=self.app_type,
            system_token=self.system_token,
            form_instance_id=instance_id,
            language="zh_CN",
        )
        self._client.delete_form_data_with_options(
            request, self._headers("DeleteFormData"), self._runtime)
        return True

    def bulk_update_metrics(self, records: list) -> int:
        """批量更新视频/商品指标"""
        metric_fields = {
            "video_link", "video_views", "video_likes", "video_comments",
            "product_link", "product_views", "ctr", "orders",
            "conversion_rate", "gmv", "price",
        }
        count = 0
        for r in records:
            cid = r.get("channel_id")
            fields = {k: v for k, v in r.items()
                      if k in metric_fields and v not in (None, "")}
            if not cid or not fields:
                continue
            if self.update(cid, fields):
                count += 1
        return count

    def sync_from_discovery(self, records: list) -> int:
        """从挖掘库同步状态为「已引入」的网红到底库"""
        count = 0
        for rec in records:
            if rec.get("status") != "已引入":
                continue
            mapped = {
                "channel_id": rec.get("channel_id"),
                "channel_name": rec.get("channel_name"),
                "channel_url": rec.get("channel_url"),
                "category": rec.get("category", ""),
                "recruiter": rec.get("discovered_by", ""),
                "subscribers": rec.get("subscribers", 0) or 0,
                "status": "已引入",
            }
            if not mapped["channel_id"]:
                continue
            self.add(mapped)
            count += 1
        return count

    # ------------------------- YTS 流程：审核流 -------------------------

    def add_audit(self, channel_id: str, result: str, opinion: str,
                  audit_date: str = "") -> bool:
        """追加一条审核记录到子表，并同步更新「审核状态」主字段

        result: 「已通过」或「未通过」
        opinion: 审核意见
        audit_date: 审核日期（YYYY-MM-DD），默认取当天
        """
        from datetime import date
        rec = self.get_by_channel_id(channel_id)
        if not rec:
            return False
        audit_log = list(rec.get("audit_log") or [])
        audit_log.append({
            "audit_date": audit_date or date.today().isoformat(),
            "audit_result": result,
            "audit_opinion": opinion,
        })
        self.update(channel_id, {
            "audit_log": audit_log,
            "audit_status": result,
        })
        return True

    def get_audit_log(self, channel_id: str) -> list:
        """读取某网红的审核历史（按写入顺序）"""
        rec = self.get_by_channel_id(channel_id)
        if not rec:
            return []
        return rec.get("audit_log") or []

    # ------------------------- YTS 流程：批量导入 -------------------------

    def bulk_add(self, records: list) -> int:
        """一键导入：批量写入网红记录（upsert 语义，已存在则更新）"""
        count = 0
        for rec in records:
            if not rec.get("channel_id"):
                continue
            self.add(rec)
            count += 1
        return count
