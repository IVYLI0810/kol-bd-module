# -*- coding: utf-8 -*-
"""
YTS 审核提醒模块（钉钉个人待办版）
================
- 提交审核 → 给审核同学建一条钉钉个人待办（带视频链接按钮）
- 审核/复审出结果 → 给负责运营建一条钉钉个人待办，提醒 check
- 群机器人已停用（2026-08-20 产品决定），本文件不再有任何群消息逻辑

所有发送函数返回 (ok: bool, msg: str)：
  ok=True  → msg 形如「已发送钉钉待办给 Minjeong」
  ok=False → msg 是具体原因（未配置 userid / 无权限 / 网络失败），
             UI 层直接把它显示出来，绝不静默吞掉。

部署配置（Streamlit Secrets 环境变量，或本地 yida_config_local.py）：
  DINGTALK_APP_KEY / DINGTALK_APP_SECRET  钉钉应用凭证
  DINGTALK_REVIEW_USERIDS  名字→userid 的 JSON，如
      {"Minjeong": "550448", "艾薇李": "550448"}
应用需在钉钉开放平台开通权限 Todo.Todo.Write（一次性操作）。
"""
import json
import os
import time

import requests


# ---------------------------------------------------------------------------
# 配置读取：环境变量（Streamlit Secrets）优先，本地配置文件兜底
# ---------------------------------------------------------------------------
def _app_creds():
    key = os.environ.get("DINGTALK_APP_KEY", "")
    sec = os.environ.get("DINGTALK_APP_SECRET", "")
    if not key:
        try:
            from yida_config_local import DINGTALK_APP_KEY as k2
            from yida_config_local import DINGTALK_APP_SECRET as s2
            key, sec = key or k2, sec or s2
        except ImportError:
            pass
    return key, sec


def _userids() -> dict:
    """名字→钉钉userid映射。Secrets 配 DINGTALK_REVIEW_USERIDS（JSON）。"""
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


# ---------------------------------------------------------------------------
# accessToken（进程内缓存 ~100 分钟，钉钉 token 有效期 2 小时）
# ---------------------------------------------------------------------------
_TOKEN_CACHE = {"t": 0.0, "tok": ""}


def _access_token():
    key, sec = _app_creds()
    if not key or not sec:
        return "", "未配置钉钉应用凭证（DINGTALK_APP_KEY / DINGTALK_APP_SECRET）"
    if _TOKEN_CACHE["tok"] and time.time() - _TOKEN_CACHE["t"] < 6000:
        return _TOKEN_CACHE["tok"], ""
    try:
        r = requests.post("https://api.dingtalk.com/v1.0/oauth2/accessToken",
                          json={"appKey": key, "appSecret": sec}, timeout=8)
        tok = (r.json() or {}).get("accessToken", "")
        if tok:
            _TOKEN_CACHE["t"], _TOKEN_CACHE["tok"] = time.time(), tok
            return tok, ""
        return "", f"获取钉钉 accessToken 失败：{r.text[:120]}"
    except Exception as e:
        return "", f"获取钉钉 accessToken 失败：{e}"


# ---------------------------------------------------------------------------
# 创建个人待办（钉钉新版待办 OpenAPI，纯 HTTP 不依赖 SDK）
# ---------------------------------------------------------------------------
def _send_todo(subject, description, url, user_id):
    """给 user_id 创建一条个人待办。返回 (ok, msg)"""
    if not user_id:
        return False, "该同学的钉钉 userid 未配置（DINGTALK_REVIEW_USERIDS）"
    tok, err = _access_token()
    if not tok:
        return False, err
    body = {
        "subject": subject[:120],
        "description": description[:400],
        "executorIds": [str(user_id)],
        "operatorId": str(user_id),
        "notifyConfigs": {"dingNotify": "1"},
    }
    if url:
        body["detailUrl"] = {"pcUrl": url, "appUrl": url}
    try:
        r = requests.post(
            f"https://api.dingtalk.com/v1.0/todo/users/{user_id}/tasks",
            headers={"x-acs-dingtalk-access-token": tok},
            json=body, timeout=10)
        if r.status_code == 200:
            return True, "钉钉待办已发送"
        txt = r.text or ""
        if "Todo.Todo.Write" in txt:
            return False, ("应用未开通「钉钉待办」权限（Todo.Todo.Write），"
                           "请到钉钉开放平台为该应用申请开通")
        msg = txt[:150]
        try:
            msg = (r.json() or {}).get("message", msg)
        except Exception:
            pass
        return False, f"钉钉待办发送失败：{msg}"
    except Exception as e:
        return False, f"钉钉待办发送失败：{e}"


# ---------------------------------------------------------------------------
# 对外入口：均返回 (ok, msg)，UI 直接展示
# ---------------------------------------------------------------------------
def notify_review_submitted(channel_name, video_url, reviewer="Minjeong"):
    """提交审核成功时调用：给审核同学发个人待办"""
    name = channel_name or "（이름 없음）"
    uid = _userids().get(reviewer)
    if not uid:
        return False, f"审核同学 {reviewer} 的钉钉 userid 未配置，待办未发送"
    ok, msg = _send_todo(
        f"🎬 영상 검토 요청 · {name}",
        f"{name} 님의 영상이 검토 대기 중입니다.\n영상 링크: {video_url}",
        video_url, uid)
    return ok, (f"已向审核同学 {reviewer} 发送钉钉待办" if ok else msg)


def notify_review_result(channel_name, result, opinion, owner):
    """审核/复审出结果时调用：给负责运营发个人待办提醒 check"""
    name = channel_name or "（이름 없음）"
    if not owner:
        return False, "该记录没有挖掘人/负责人，待办未发送"
    uid = _userids().get(owner)
    if not uid:
        return False, f"运营同学 {owner} 的钉钉 userid 未配置，待办未发送"
    icon = "✅" if result == "已通过" else "❌"
    ok, msg = _send_todo(
        f"{icon} 검토 결과 · {name}",
        f"검토 결과: {result}\n의견: {opinion or '-'}\n확인 부탁드립니다!",
        "", uid)
    return ok, (f"已向运营同学 {owner} 发送钉钉待办" if ok else msg)
