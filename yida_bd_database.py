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
from datetime import datetime
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
    "channel_id": "textField_msn2qhnb",        # 频道ID（与活动名称组合唯一）
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
    "activity_name": "textField_msrcwjcr",     # 活动名称（如 2608活动；同一网红每活动一行）
    # ---- 活动履约流程字段（2026-08-12 组件定义实测） ----
    "stage": "selectField_mspwxzct",           # 合作阶段：洽谈中/履约中/已闭环
    "email_status": "selectField_mspwxzcv",    # 邮件状态：已发送/指南已发送
    "contract": "selectField_mspwxzd3",        # 合同状态：已签署/…
    "order_status": "selectField_mspwxzd5",    # 下单状态：已下单/…
    "deadline": "dateField_mspwxzd7",          # 交稿截止（=计划上传日期）
    "submitted_at": "dateField_mspwxzd9",      # 实际提交时间
    "review_status": "selectField_mspwxzdd",   # 审核状态：待审核/已通过/已驳回
    "auth": "selectField_mspwxzdb",            # 投放授权
    "group_link": "textField_mspwxzcz",        # 群链接
    "settle": "selectField_mspwxzcx",          # 结算方式
    "review_log": "tableField_mspwxzdf",       # 审核记录子表单
}

# 日期字段：写入须转毫秒时间戳，读取转回 YYYY-MM-DD
DATE_FIELDS = {"deadline", "submitted_at"}

# 子表单字段：值为对象数组，直接透传（内部日期同样转毫秒）
TABLE_FIELDS = {"review_log"}

# 审核子表单的列 fieldId（代码名 -> fieldId）
REVIEW_LOG_CHILD = {
    "date": "dateField_mspwxzdg",       # 审核日期
    "result": "selectField_mspwxzdh",   # 审核结果：已通过/已驳回
    "comment": "textareaField_mspwxzdi",  # 审核意见（驳回必填）
}

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
    "activity_name": "活动名称",
    "stage": "合作阶段", "email_status": "邮件状态", "contract": "合同状态",
    "order_status": "下单状态", "deadline": "交稿截止", "submitted_at": "实际提交时间",
    "review_status": "审核状态", "auth": "投放授权", "group_link": "群链接",
    "settle": "结算方式", "review_log": "审核记录",
}


def _date_to_ms(value) -> Optional[int]:
    """YYYY-MM-DD / YYYY-MM-DD HH:MM:SS / datetime -> 毫秒时间戳"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(s, fmt).timestamp() * 1000)
        except ValueError:
            continue
    return None


def _ms_to_date(value) -> str:
    """毫秒时间戳 -> YYYY-MM-DD（非法值原样转字符串）"""
    try:
        return datetime.fromtimestamp(float(value) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return str(value)


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
        self._runtime = util_models.RuntimeOptions()

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
                ms = _date_to_ms(value)
                if ms is None:
                    continue
                value = ms
            elif code in TABLE_FIELDS and code == "review_log":
                rows = []
                for row in (value or []):
                    item = {}
                    for child_code, child_fid in REVIEW_LOG_CHILD.items():
                        v = row.get(child_code)
                        if v in (None, ""):
                            continue
                        if child_code == "date":
                            ms = _date_to_ms(v)
                            if ms is None:
                                continue
                            v = ms
                        else:
                            v = str(v)
                        item[child_fid] = v
                    if item:
                        rows.append(item)
                if not rows:
                    continue
                value = rows
            else:
                value = str(value)
            out[fid] = value
        return out

    def _from_instance(self, inst: dict) -> dict:
        id_to_code = {v: k for k, v in FIELD_IDS.items() if v}
        child_id_to_code = {v: k for k, v in REVIEW_LOG_CHILD.items()}
        raw = inst.get("FormData") or inst.get("formData") or {}
        rec = {"form_instance_id": inst.get("FormInstanceId") or inst.get("formInstanceId")}
        for fid, value in raw.items():
            code = id_to_code.get(fid)
            if not code:
                continue
            if code in DATE_FIELDS and value not in (None, ""):
                rec[code] = _ms_to_date(value)
            elif code == "review_log" and isinstance(value, list):
                rows = []
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    row = {}
                    for k, v in item.items():
                        ccode = child_id_to_code.get(k)
                        if not ccode:
                            continue
                        row[ccode] = _ms_to_date(v) if ccode == "date" else v
                    if row:
                        rows.append(row)
                rec[code] = rows
            else:
                rec[code] = value
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

    def _find_instances(self, channel_id: str) -> list:
        """同一频道可能有多行（每个活动一行），全部取回"""
        data = self._search_page({FIELD_IDS["channel_id"]: str(channel_id)}, size=100)
        return data.get("Data") or data.get("data") or []

    def _find_instance(self, channel_id: str, activity: Optional[str] = None) -> Optional[dict]:
        rows = self._find_instances(channel_id)
        if not rows:
            return None
        if activity is not None:
            fid = FIELD_IDS["activity_name"]
            for row in rows:
                raw = row.get("FormData") or row.get("formData") or {}
                if str(raw.get(fid) or "").strip() == str(activity).strip():
                    return row
            return None
        if len(rows) == 1:
            return rows[0]
        # 多行且未指定活动：优先返回未填活动名称的行（兼容旧调用）
        fid = FIELD_IDS["activity_name"]
        for row in rows:
            raw = row.get("FormData") or row.get("formData") or {}
            if not str(raw.get(fid) or "").strip():
                return row
        return rows[0]

    # ------------------------- 业务接口（与 LocalBDDB 对齐） -------------------------

    def add(self, record: dict) -> dict:
        """新增或更新（以 channel_id × 活动名称 为复合主键的 upsert）"""
        if not record.get("channel_id"):
            raise ValueError("channel_id 为必填字段")
        activity = record.get("activity_name")
        existing = self._find_instance(record["channel_id"], activity)
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
        return self.get_by_channel_id(record["channel_id"], activity) or record

    def get_by_channel_id(self, channel_id: str, activity: Optional[str] = None) -> Optional[dict]:
        inst = self._find_instance(channel_id, activity)
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
        page = 1
        while True:
            data = self._search_page(search_field, page=page, size=100)
            rows = data.get("Data") or data.get("data") or []
            results.extend(self._from_instance(r) for r in rows)
            total = data.get("TotalCount") or data.get("totalCount") or len(results)
            if len(results) >= total or not rows:
                break
            page += 1
        results.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return results

    def update(self, channel_id: str, updates: dict, activity: Optional[str] = None) -> Optional[dict]:
        inst = self._find_instance(channel_id, activity)
        if not inst:
            return None
        instance_id = inst.get("FormInstanceId") or inst.get("formInstanceId")
        request = aliding_models.UpdateFormDataRequest(
            app_type=self.app_type,
            system_token=self.system_token,
            form_instance_id=instance_id,
            language="zh_CN",
            use_latest_version=True,
            update_form_data_json=json.dumps(self._to_form_data(updates), ensure_ascii=False),
        )
        self._client.update_form_data_with_options(
            request, self._headers("UpdateFormData"), self._runtime)
        return self.get_by_channel_id(channel_id, activity)

    def delete(self, channel_id: str, activity: Optional[str] = None) -> bool:
        rows = self._find_instances(channel_id)
        if activity is not None:
            fid = FIELD_IDS["activity_name"]
            rows = [r for r in rows
                    if str((r.get("FormData") or r.get("formData") or {}).get(fid) or "").strip()
                    == str(activity).strip()]
        if not rows:
            return False
        for inst in rows:
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

    def append_review_log(self, channel_id: str, result: str,
                          comment: str = "", date: str = "",
                          activity: Optional[str] = None) -> Optional[dict]:
        """追加一条审核记录（只增不减），并返回更新后的记录"""
        rec = self.get_by_channel_id(channel_id, activity)
        if not rec:
            return None
        rows = list(rec.get("review_log") or [])
        rows.append({
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "result": result,
            "comment": comment or "",
        })
        return self.update(channel_id, {"review_log": rows}, activity)
