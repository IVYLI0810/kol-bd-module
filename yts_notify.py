# -*- coding: utf-8 -*-
"""
YTS 审核提醒模块（钉钉双通道版：群机器人 + 个人待办）
================
- 提交审核 → ① 群里发一条 markdown 通知并 @审核同学（群自定义机器人）
             ② 给审核同学建一条钉钉个人待办（带视频链接按钮）
- 审核/复审出结果 → 给负责运营建一条钉钉个人待办，提醒 check

两个通道互相独立：哪个配置好就发哪个，都发时结果合并展示；
任何一个失败都会把原因写进返回消息，UI 直接展示，绝不静默吞掉。

所有发送函数返回 (ok: bool, msg: str)：
  ok=True  → 至少一个通道发送成功
  ok=False → 全部通道失败/未配置，msg 是具体原因

部署配置（Streamlit Secrets 环境变量，或本地 yida_config_local.py）：
  【个人待办】
  DINGTALK_APP_KEY / DINGTALK_APP_SECRET  钉钉应用凭证
  DINGTALK_REVIEW_USERIDS  名字→userid 的 JSON，如
      {"Minjeong": "550448", "艾薇李": "550448"}
  应用需在钉钉开放平台开通权限 Todo.Todo.Write（一次性操作）。
  【群机器人】（群设置→机器人→添加自定义机器人，安全设置选「加签」）
  DINGTALK_WEBHOOK          机器人的 webhook 完整地址（含 access_token）
  DINGTALK_WEBHOOK_SECRET   加签密钥（SEC 开头）
  DINGTALK_REVIEW_MOBILES   名字→手机号 JSON（可选，填了才能 @ 出红点），如
      {"Minjeong": "01012345678"}
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse

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


def _cfg(name):
    """通用配置读取：环境变量优先，yida_config_local.py 兜底"""
    v = os.environ.get(name, "")
    if not v:
        try:
            import yida_config_local as _c
            v = getattr(_c, name, "") or ""
        except ImportError:
            pass
    return v


def _mobiles() -> dict:
    """名字→手机号映射（可选）。配了才能在群里 @ 出红点提醒。"""
    raw = _cfg("DINGTALK_REVIEW_MOBILES")
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 群自定义机器人（webhook + 加签，不需要任何权限审批）
# ---------------------------------------------------------------------------
def _sign_webhook_url(webhook, secret):
    """钉钉自定义机器人「加签」：timestamp + HMAC-SHA256 签名拼到 URL 上"""
    if not secret:
        return webhook
    ts = str(round(time.time() * 1000))
    string_to_sign = f"{ts}\n{secret}"
    h = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                 hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(h))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={ts}&sign={sign}"


def _send_group(title, md_text, reviewer=""):
    """往群里发一条 markdown 通知；配了手机号/userid 就 @ 审核同学。返回 (ok, msg)"""
    webhook = _cfg("DINGTALK_WEBHOOK")
    if not webhook:
        return False, "群机器人未配置（DINGTALK_WEBHOOK）"
    at_uids, at_mobiles = [], []
    if reviewer:
        uid = _userids().get(reviewer)
        mob = _mobiles().get(reviewer)
        if uid:
            at_uids.append(str(uid))
        if mob:
            at_mobiles.append(str(mob))
            md_text += f"\n\n@{mob}"  # markdown 里必须写上 @手机号 才会显示
    body = {"msgtype": "markdown",
            "markdown": {"title": title, "text": md_text},
            "at": {"atUserIds": at_uids, "atMobiles": at_mobiles,
                   "isAtAll": False}}
    try:
        r = requests.post(_sign_webhook_url(webhook, _cfg("DINGTALK_WEBHOOK_SECRET")),
                          json=body, timeout=8)
        data = r.json() or {}
        if data.get("errcode") == 0:
            who = f"并@{reviewer}" if (at_uids or at_mobiles) else ""
            return True, f"群通知已发送{who}"
        em = str(data.get("errmsg") or r.text or "")[:120]
        if "keywords" in em:
            return False, "群机器人安全设置是「自定义关键词」且没匹配上——请把机器人安全设置改为「加签」"
        if "sign not match" in em or "sign" in em:
            return False, "加签密钥不对，请核对 DINGTALK_WEBHOOK_SECRET（SEC 开头那串）"
        if "robot not exists" in em or "token" in em:
            return False, "webhook 地址不对，请重新复制机器人的完整 webhook"
        return False, f"群通知发送失败：{em}"
    except Exception as e:
        return False, f"群通知发送失败：{e}"


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
    """提交审核成功时调用：群机器人@审核同学 + 审核同学个人待办，双通道"""
    name = channel_name or "（이름 없음）"
    parts = []

    # 通道一：群机器人（配了 webhook 就发）
    md = (f"### 🎬 새 영상 검토 요청\n\n"
          f"- 크리에이터: **{name}**\n"
          f"- 검토 담당: {reviewer}\n"
          f"- 영상 링크: [바로가기]({video_url})\n\n"
          f"확인 부탁드립니다 🙏")
    gok, gmsg = _send_group(f"영상 검토 요청 · {name}", md, reviewer)
    parts.append(gmsg)

    # 通道二：个人待办（配了 userid 就发）
    uid = _userids().get(reviewer)
    todo_ok = False
    if not uid:
        parts.append(f"待办未发送：{reviewer} 的钉钉 userid 未配置")
    else:
        todo_ok, tok_msg = _send_todo(
            f"🎬 영상 검토 요청 · {name}",
            f"{name} 님의 영상이 검토 대기 중입니다.\n영상 링크: {video_url}",
            video_url, uid)
        parts.append(f"已向 {reviewer} 发送钉钉待办" if todo_ok else f"待办：{tok_msg}")

    return gok or todo_ok, "；".join(parts)


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
