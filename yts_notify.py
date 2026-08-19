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


def _send_markdown(title, text):
    """发送 markdown 消息到钉钉群；未配置或失败都静默返回 False"""
    try:
        webhook, secret = _creds()
        if not webhook or not secret:
            return False
        url = _signed_url(webhook, secret)
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
        r = requests.post(url, json=payload, timeout=8)
        return r.json().get("errcode") == 0
    except Exception:
        return False


def notify_review_submitted(channel_name, video_url):
    """提交审核成功时调用：往群里发韩文提醒"""
    name = channel_name or "（이름 없음）"
    text = (
        f"### 🎬 영상 검토 요청\n\n"
        f"**{name}** 님의 영상이 검토 대기 상태로 등록되었습니다.\n\n"
        f"🔗 [영상 링크]({video_url})\n\n"
        f"Minjeong 님, 검토 부탁드립니다! 🙏"
    )
    return _send_markdown("영상 검토 요청", text)
