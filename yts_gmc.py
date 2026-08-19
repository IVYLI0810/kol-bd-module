# -*- coding: utf-8 -*-
"""GMC（Merchant Center）自动化：商品ID提取 / 池校验 / 效果数据拉取。

数据来源：Google Merchant API（Content API for Shopping），
与 merchants.google.com 后台同源，需一次性配置服务账号（见 README/配置指引）。

凭证从 Streamlit Secrets 读取：
    [gmc]
    client_email = "xxx@yyy.iam.gserviceaccount.com"
    private_key  = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    merchant_id  = "5625230615"
    feed_label   = "KR-YOUTUBE"

未配置时所有函数返回友好错误信息，不影响其他功能。
"""
import json
import os
import re
import time

import requests

FEED_LABEL_DEFAULT = "KR-YOUTUBE"
_TOKEN_CACHE = {"token": "", "exp": 0.0}


# ---------------------------------------------------------------------------
# 配置与凭证
# ---------------------------------------------------------------------------
def get_cfg() -> dict:
    """从环境变量或 Streamlit Secrets 读取 GMC 配置"""
    cfg = {
        "client_email": os.environ.get("GMC_CLIENT_EMAIL", ""),
        "private_key": os.environ.get("GMC_PRIVATE_KEY", ""),
        "merchant_id": os.environ.get("GMC_MERCHANT_ID", ""),
        "feed_label": os.environ.get("GMC_FEED_LABEL", FEED_LABEL_DEFAULT),
    }
    try:  # Streamlit Cloud Secrets：[gmc] 段
        import streamlit as st
        g = st.secrets.get("gmc", None) if hasattr(st, "secrets") else None
        if g:
            for k in cfg:
                if g.get(k):
                    cfg[k] = g[k]
    except Exception:
        pass
    return cfg


def configured() -> bool:
    c = get_cfg()
    return bool(c["client_email"] and c["private_key"] and c["merchant_id"])


def _access_token() -> str:
    """服务账号 JWT → OAuth2 access_token（缓存至过期前60秒）"""
    cfg = get_cfg()
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["exp"]:
        return _TOKEN_CACHE["token"]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    import base64

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    iat = int(now)
    claim = b64url(json.dumps({
        "iss": cfg["client_email"],
        "scope": "https://www.googleapis.com/auth/content",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": iat, "exp": iat + 3600,
    }).encode())
    signing_input = f"{header}.{claim}".encode()
    key = serialization.load_pem_private_key(cfg["private_key"].encode(), None)
    sig = key.sign(signing_input, asym_padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{header}.{claim}.{b64url(sig)}"
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
    }, timeout=15)
    r.raise_for_status()
    data = r.json()
    _TOKEN_CACHE["token"] = data["access_token"]
    _TOKEN_CACHE["exp"] = now + int(data.get("expires_in", 3600)) - 60
    return _TOKEN_CACHE["token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_access_token()}"}


# ---------------------------------------------------------------------------
# 商品ID提取
# ---------------------------------------------------------------------------
def extract_offer_id(url_or_id: str) -> str:
    """从商品链接/offerId参数/裸ID中提取商品ID；无法提取返回空串。

    支持：aliexpress 商品链接（取 /item/xxx.html 的数字）、
    merchants.google.com 链接（取 offerId 参数）、裸数字ID。
    """
    s = str(url_or_id or "").strip()
    if not s:
        return ""
    m = re.search(r"offerId=([\w-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"/item/(\d+)", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{4,}", s):
        return s
    return ""


# ---------------------------------------------------------------------------
# GMC 校验：商品是否在 KR-YOUTUBE 池
# ---------------------------------------------------------------------------
def check_product(offer_id: str) -> dict:
    """返回 {"ok": bool, "msg": str}：在池=通过，不在=不通过"""
    if not configured():
        return {"ok": False, "msg": "未配置 GMC 凭证（Secrets [gmc] 段）"}
    cfg = get_cfg()
    oid = extract_offer_id(offer_id)
    if not oid:
        return {"ok": False, "msg": "无法从输入提取商品ID"}
    # REST 路径：products/{merchant_id}~{channel}~{feed_label}~{offer_id}
    rest_id = f"{cfg['merchant_id']}~online~{cfg['feed_label']}~{oid}"
    try:
        r = requests.get(
            f"https://shoppingcontent.googleapis.com/content/v2.1/products/{rest_id}",
            headers=_headers(), timeout=15)
        if r.status_code == 200:
            return {"ok": True, "msg": f"商品 {oid} 在 {cfg['feed_label']} 池内"}
        if r.status_code == 404:
            return {"ok": False, "msg": f"商品 {oid} 不在 {cfg['feed_label']} 池内"}
        return {"ok": False, "msg": f"GMC 返回 {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "msg": f"GMC 请求失败：{e}"}


def check_products(urls: list) -> dict:
    """批量校验选品清单，返回 {offer_id: {"ok","msg"}}"""
    return {extract_offer_id(u): check_product(u) for u in urls
            if extract_offer_id(u)}


# ---------------------------------------------------------------------------
# 效果数据：SHOPPING_PERFORMANCE_VIEW 报表（点击/CTR/转化/GMV）
# ---------------------------------------------------------------------------
def fetch_performance(offer_ids: list, start_date: str, end_date: str) -> dict:
    """按商品ID聚合效果数据。start/end 形如 2026-08-01。

    返回 {offer_id: {"clicks","impressions","ctr","orders","gmv"}}；
    未配置/失败返回 {}。
    """
    if not configured() or not offer_ids:
        return {}
    cfg = get_cfg()
    oids = [extract_offer_id(x) for x in offer_ids]
    oids = [o for o in oids if o]
    if not oids:
        return {}
    body = {
        "reportId": "SHOPPING_PERFORMANCE_VIEW",
        "dimensions": ["OFFER_ID"],
        "metrics": ["CLICKS", "IMPRESSIONS", "CTR", "ORDER_LINES",
                    "ORDER_REVENUE_VALUE"],
        "filters": [{
            "fieldName": "OFFER_ID",
            "predicate": {"operator": "IN", "value": oids},
        }, {
            "fieldName": "FEED_LABEL",
            "predicate": {"operator": "EQUALS", "value": [cfg["feed_label"]]},
        }],
        "dateRange": {"startDate": start_date, "endDate": end_date},
    }
    try:
        r = requests.post(
            f"https://shoppingcontent.googleapis.com/reports/v2/merchantId="
            f"{cfg['merchant_id']}/reports/search",
            headers=_headers(), json=body, timeout=30)
        r.raise_for_status()
        out = {}
        for row in r.json().get("results", []):
            oid = row.get("dimensions", {}).get("OFFER_ID", "")
            m = row.get("metrics", {})
            ctr = m.get("CTR", 0) or 0
            if isinstance(ctr, str):
                ctr = float(ctr.rstrip("%")) if ctr else 0.0
            out[oid] = {
                "clicks": int(m.get("CLICKS", 0) or 0),
                "impressions": int(m.get("IMPRESSIONS", 0) or 0),
                "ctr": round(ctr * 100, 2) if ctr <= 1 else round(ctr, 2),
                "orders": int(m.get("ORDER_LINES", 0) or 0),
                "gmv": float(m.get("ORDER_REVENUE_VALUE", 0) or 0),
            }
        return out
    except Exception:
        return {}
