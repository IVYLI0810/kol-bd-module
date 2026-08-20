# -*- coding: utf-8 -*-
"""
YTS 审核提醒模块
================
提交审核时，通过钉钉群机器人（加签模式）发送韩文提醒给审核同学。

设计原则：所有提醒逻辑失败都静默吞掉，绝不影响主流程。

部署注意：webhook 和加签密钥放在 Streamlit Secrets 里
（DINGTALK_REVIEW_WEBHOOK / DINGTALK_REVIEW_SECRET），不要写死在代码里。
"""
import base64
import hashlib
import hmac
import os
import time
import urllib.parse

import requests


# ---------------------------------------------------------------------------
# 凭证读取：环境变量（Streamlit Secrets）优先，本地配置文件兜底
# ---------------------------------------------------------------------------
def _creds():
    webhook = os.environ.get("DINGTALK_REVIEW_WEBHOOK", "")
    secret = os.environ.get("DINGTALK_REVIEW_SECRET", "")
    if not webhook:
        try:
            from yida_config_local import (DINGTALK_REVIEW_WEBHOOK as w,
                                           DINGTALK_REVIEW_SECRET as s)
            webhook, secret = webhook or w, secret or s
        except ImportError:
            pass
    return webhook, secret


def _mobiles() -> dict:
    """名字→手机号映射（用于真@）。Secrets 里配 DINGTALK_REVIEW_MOBILES，
    格式 JSON：{"Minjeong": "138xxxx", "艾薇李": "139xxxx"}。未配置返回 {}"""
    import json
    raw = os.environ.get("DINGTALK_REVIEW_MOBILES", "")
    if not raw:
        try:
            from yida_config_local import DINGTALK_REVIEW_MOBILES as raw
        except ImportError:
            return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 钉钉发送（加签模式）
# ---------------------------------------------------------------------------
def _signed_url(webhook, secret):
    """给 webhook 拼上时间戳和签名（钉钉自定义机器人·加签安全设置）"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"),
                         string_to_sign.encode("utf-8"),
                         digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{webhook}&timestamp={timestamp}&sign={sign}"


def _send_markdown(title, text, at_names=()):
    """发送 markdown 消息到钉钉群；未配置或失败都静默返回 False。
    @策略：at_names 按 _mobiles() 映射手机号精准@；
    未配置手机号时默认 @所有人（isAtAll）保证响铃提醒，
    可用 Secrets 的 DINGTALK_REVIEW_AT_ALL = "false" 关闭。
    映射不到的名字以文本形式附在消息末尾（兜底提醒）"""
    try:
        webhook, secret = _creds()
        if not webhook or not secret:
            return False
        mobiles_map = _mobiles()
        at_mobiles, missed = [], []
        for n in at_names or ():
            m = (mobiles_map.get(n) or "").strip()
            if m:
                at_mobiles.append(m)
            else:
                missed.append(n)
        if missed:
            text += "\n\n" + " ".join(f"@{n}" for n in missed)
        # 默认不@所有人（避免打扰领导）；仅当显式配置
        # DINGTALK_REVIEW_AT_ALL = "true" 时才@所有人
        at_all = (not at_mobiles) and os.environ.get(
            "DINGTALK_REVIEW_AT_ALL", "false").strip().lower() == "true"
        url = _signed_url(webhook, secret)
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text},
                   "at": {"atMobiles": at_mobiles, "isAtAll": at_all}}
        r = requests.post(url, json=payload, timeout=8)
        return r.json().get("errcode") == 0
    except Exception:
        return False


def notify_review_submitted(channel_name, video_url, reviewer="Minjeong"):
    """提交审核成功时调用：优先发个人待办（不进群、不打扰领导）；
    未配该人 userid 时退回群机器人提醒"""
    name = channel_name or "（이름 없음）"
    if notify_todo_review(name, video_url, reviewer):
        return True
    text = (
        f"### 🎬 영상 검토 요청\n\n"
        f"**{name}** 님의 영상이 검토 대기 상태로 등록되었습니다.\n\n"
        f"🔗 [영상 링크]({video_url})\n\n"
        f"{reviewer} 님, 검토 부탁드립니다! 🙏"
    )
    return _send_markdown("영상 검토 요청", text, at_names=[reviewer])


def notify_review_result(channel_name, result, opinion, owner):
    """审核/复审出结果时调用：优先个人待办提醒运营 check；
    未配 userid 时退回群机器人"""
    name = channel_name or "（이름 없음）"
    if owner and notify_todo_result(name, result, opinion, owner):
        return True
    icon = "✅" if result == "已通过" else "❌"
    text = (
        f"### {icon} 검토 결과 알림\n\n"
        f"**{name}** 님의 영상 검토 결과：**{result}**\n\n"
        f"💬 의견：{opinion or '-'}\n\n"
        f"{owner or '담당자'} 님, 확인 부탁드립니다!"
    )
    return _send_markdown("검토 결과 알림", text, at_names=[owner] if owner else [])


# ---------------------------------------------------------------------------
# 个人待办（不进群、不打扰领导）：复用宜搭同款 AK/SK 网关
# ---------------------------------------------------------------------------
def _yida_creds():
    ak = os.environ.get("YIDA_ACCESS_KEY_ID", "")
    sk = os.environ.get("YIDA_ACCESS_KEY_SECRET", "")
    if not ak:
        try:
            from yida_config_local import YIDA_CONFIG as c
            ak, sk = c.get("access_key_id", ""), c.get("access_key_secret", "")
        except ImportError:
            pass
    return ak, sk


def _userids() -> dict:
    """名字→钉钉userid/工号映射。Secrets 配 DINGTALK_REVIEW_USERIDS，
    格式 JSON：{"Minjeong": "550448", "艾薇李": "550448"}。未配置返回 {}"""
    import json
    raw = os.environ.get("DINGTALK_REVIEW_USERIDS", "")
    if not raw:
        try:
            from yida_config_local import DINGTALK_REVIEW_USERIDS as raw
        except ImportError:
            return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


def _send_todo(subject, description, url, user_id):
    """给指定人创建一条钉钉个人待办（带跳转按钮）。失败静默返回 False"""
    try:
        ak, sk = _yida_creds()
        if not ak or not sk or not user_id:
            return False
        from alibabacloud_aliding20230426.client import Client
        from alibabacloud_aliding20230426 import models as m
        from alibabacloud_tea_openapi import models as om
        from alibabacloud_tea_util import models as um
        client = Client(om.Config(access_key_id=ak, access_key_secret=sk,
                                  endpoint="aliding.aliyuncs.com"))
        req = m.CreateTodoTaskRequest(
            subject=subject, description=description,
            executor_ids=[str(user_id)], operator_id=str(user_id),
            detail_url=m.CreateTodoTaskRequestDetailUrl(
                app_url=url, pc_url=url),
            notify_configs=m.CreateTodoTaskRequestNotifyConfigs(
                send_assistant_chat="true", send_todo_apn="true"),
        )
        client.create_todo_task_with_options(
            req, m.CreateTodoTaskHeaders(), um.RuntimeOptions(
                connect_timeout=5000, read_timeout=10000))
        return True
    except Exception:
        return False


def notify_todo_review(channel_name, video_url, reviewer="Minjeong"):
    """提交审核 → 给审核同学发个人待办（不进群）。无 userid 静默返回 False"""
    uid = _userids().get(reviewer)
    return _send_todo(f"🎬 영상 검토 요청 · {channel_name}",
                      f"{channel_name} 님의 영상이 검토 대기 중입니다.\n"
                      f"영상 링크: {video_url}", video_url, uid)


def notify_todo_result(channel_name, result, opinion, owner):
    """审核出结果 → 给运营发个人待办（不进群）。无 userid 静默返回 False"""
    uid = _userids().get(owner)
    icon = "✅" if result == "已通过" else "❌"
    return _send_todo(f"{icon} 검토 결과 · {channel_name}",
                      f"검토 결과: {result}\n의견: {opinion or '-'}\n"
                      f"확인 부탁드립니다!", "", uid)
