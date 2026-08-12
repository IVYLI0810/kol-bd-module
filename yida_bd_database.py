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
    "conversion_rate": "numberField_msn2qhod", # 转化率
    "gmv": "numberField_msn2qhof",             # GMV
    "notes": "textareaField_msn2qhoj",         # 备注
    # ↓ 表单中尚未创建，建好后把 fieldId 填上即可（代码自动跳过空值）
    "product_clicks": "",      # 点击（缺）
    "product_conversions": "", # 转化（缺）
    "ctr": "",                 # CTR（缺）
}

NUMBER_FIELDS = {
    "subscribers", "total_views", "video_views", "video_likes", "video_comments",
    "product_views", "product_clicks", "product_conversions",
    "ctr", "conversion_rate", "gmv",
}

CODE_TO_LABEL = {
    "channel_id": "频道ID", "channel_name": "昵称", "channel_url": "YouTube主页",
    "category": "垂类", "recruiter": "挖掘人", "subscribers": "粉丝数",
    "total_views": "总播放", "status": "状态", "video_link": "视频回链",
    "video_views": "播放量", "video_likes": "点赞数", "video_comments": "评论数",
    "product_link": "商品链接", "product_views": "浏览量",
    "product_clicks": "点击", "product_conversions": "转化",
    "ctr": "CTR", "conversion_rate": "转化率", "gmv": "GMV", "notes": "备注",
}


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
            else:
                value = str(value)
            out[fid] = value
        return out

    def _from_instance(self, inst: dict) -> dict:
        id_to_code = {v: k for k, v in FIELD_IDS.items() if v}
        raw = inst.get("FormData") or inst.get("formData") or {}
        rec = {"form_instance_id": inst.get("FormInstanceId") or inst.get("formInstanceId")}
        for fid, value in raw.items():
            code = id_to_code.get(fid)
            if code:
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

    def update(self, channel_id: str, updates: dict) -> Optional[dict]:
        inst = self._find_instance(channel_id)
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
        return self.get_by_channel_id(channel_id)

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
            "product_link", "product_views", "product_clicks",
            "product_conversions", "ctr", "conversion_rate", "gmv",
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
