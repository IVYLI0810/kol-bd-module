#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性搬家向导（Phase 1 · 钉钉宜搭 → Supabase）
================================================

设计目的：搬家脚本原本要"在本地跑 python"，但宜搭密钥只在 Streamlit Cloud
的 Secrets 里、本机也没有阿里云宜搭 SDK，对非技术同学不友好。于是把搬家做成
挂在主管理站里的一个临时页面：浏览器打开 `.../app_demo.py?migrate=1`
就能看到，仍然在原有访问密码门之后。

它复用：
  - get_yts_store()  → 现成的宜搭数据层（密钥来自应用 Secrets）
  - yts_roster.SUPABASE_URL / SUPABASE_KEY  → 挖掘站一直在用的 Supabase
  - migrate_yida_to_supabase.convert()      → 同一套字段拆分逻辑（DRY）

两步走：
  ① 演练预览（只读，绝不写库）：拉宜搭全表→转换→显示行数/重复/样例，结果缓存
     到 session_state，避免下一步再拉一次。
  ② 正式搬家（写入 Supabase public.collabs）：分批 POST merge，幂等可重跑。

搬家完成后本页面可整体删除（连同主程序里那 4 行入口）。
"""
import json
import time

import requests
import streamlit as st

NOW = time.strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ 配置
def _supa():
    import yts_roster as R
    return R.SUPABASE_URL.rstrip("/"), R.SUPABASE_KEY


def _load_raw():
    """从宜搭拉全表原始记录（复用主站已建好的 store 单例）。"""
    from yts_yida_store import get_yts_store
    store = get_yts_store()
    if getattr(store, "demo", False):
        st.error("当前应用没有连到宜搭真实数据（演示模式），无法搬家。"
                 "请确认 Secrets 里 YIDA_ACCESS_KEY_ID / YIDA_ACCESS_KEY_SECRET / "
                 "YIDA_SYSTEM_TOKEN 都在，重启后再试。")
        return None
    try:
        return store.db.get_all()
    except Exception as e:  # noqa: BLE001
        st.error(f"读取宜搭失败：{e}")
        return None


def _do_preview():
    from migrate_yida_to_supabase import convert
    raw = _load_raw()
    if raw is None:
        return
    rows = [convert(r) for r in raw]
    skipped = len(raw) - sum(1 for r in rows if r.get("channel_id"))
    rows = [r for r in rows if r.get("channel_id")]

    dup = {}
    for r in rows:
        k = (r["channel_id"], r["plan_month"])
        dup[k] = dup.get(k, 0) + 1
    conflicts = {k: v for k, v in dup.items() if v > 1}

    st.session_state["_mig_rows"] = rows
    st.session_state["_mig_meta"] = {
        "yida_total": len(raw),
        "valid": len(rows),
        "skipped": skipped,
        "conflicts": conflicts,
        "ts": NOW,
    }


def _do_apply(batch: int = 100):
    rows = st.session_state.get("_mig_rows")
    if not rows:
        st.warning("请先做第①步演练预览。")
        return
    url, key = _supa()
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,merge=duplicates",
    }
    bar = st.progress(0.0)
    status = st.empty()
    total = len(rows)
    for i in range(0, total, batch):
        chunk = rows[i:i + batch]
        r = requests.post(f"{url}/rest/v1/collabs",
                          params={"on_conflict": "channel_id,plan_month"},
                          headers=headers,
                          data=json.dumps(chunk, ensure_ascii=False),
                          timeout=60)
        if r.status_code >= 400:
            bar.empty(); status.empty()
            st.error(f"批次 {i}-{i+len(chunk)} 写入失败：HTTP {r.status_code}\n{r.text[:500]}")
            return
        done = min(i + batch, total)
        bar.progress(done / total)
        status.caption(f"已写入 {done}/{total}")

    # 复核
    rr = requests.get(f"{url}/rest/v1/collabs", params={"select": "id"},
                      headers={"apikey": key, "Authorization": f"Bearer {key}"},
                      timeout=30)
    if rr.status_code >= 400:
        st.error(f"复核失败：HTTP {rr.status_code} {rr.text[:300]}")
        return
    supa_n = len(rr.json())
    bar.empty(); status.empty()
    st.session_state["_mig_done"] = {"supa_n": supa_n, "expect": total, "ts": NOW}


# ------------------------------------------------------------------ 渲染
def render():
    st.title("🚚 一次性搬家：钉钉宜搭 → Supabase")
    st.caption("把 kol-bd 管理站现有的宜搭数据整表迁进共享 Supabase 库 `public.collabs`。"
               "搬家幂等，可反复重跑；只写 collabs，不动挖掘站 influencers。")

    # 可选二次口令：Secrets 里若设了 MIGRATE_TOKEN，则 URL 需再带 &tok=xxx
    tok_required = st.secrets.get("MIGRATE_TOKEN") if "MIGRATE_TOKEN" in st.secrets else None
    if tok_required:
        given = st.query_params.get("tok", "")
        if given != tok_required:
            st.error("此搬家入口已启用二次口令，请在链接末尾加 `&tok=<MIGRATE_TOKEN>` 后重开。")
            return

    # ---- 第①步：演练预览 ----
    st.subheader("第①步 · 演练预览（只读，不写库）")
    if st.button("拉宜搭全表并预览转换结果", type="primary"):
        with st.spinner("正在读取宜搭（约 10-20 秒）……"):
            _do_preview()
    meta = st.session_state.get("_mig_meta")
    if meta:
        st.success(
            f"宜搭总行数 {meta['yida_total']} → 有效行数 {meta['valid']}"
            f"（跳过无 channel_id 的 {meta['skipped']} 行）。预览时间 {meta['ts']}"
        )
        if meta["conflicts"]:
            st.warning(f"⚠️ 身份重复 (channel_id, plan_month) 共 {len(meta['conflicts'])} 组，"
                       "写入时后一条会覆盖前一条。可下载下方样例核对。")
        rows = st.session_state["_mig_rows"]
        st.write("转换后前 3 条样例：")
        st.dataframe(rows[:3], use_container_width=True)
        st.download_button(
            "⬇️ 下载本次转换的完整 JSON（留档/核对）",
            data=json.dumps(rows, ensure_ascii=False, indent=1),
            file_name=f"collabs_preview_{time.strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
        )

    # ---- 第②步：正式搬家 ----
    st.divider()
    st.subheader("第②步 · 正式搬家（写入 Supabase）")
    if not meta:
        st.info("请先完成第①步预览，再执行搬家。")
    else:
        if st.session_state.get("_mig_done"):
            d = st.session_state["_mig_done"]
            ok = d["supa_n"] >= d["expect"]
            (st.success if ok else st.error)(
                f"上次搬家 {d['ts']}：Supabase.collabs 现有 {d['supa_n']} 行，"
                f"本次转换 {d['expect']} 行。{'✅ 看起来没问题。' if ok else '⚠️ 少于预期，请回查。'}"
            )
        if st.button(f"确认写入 {meta['valid']} 行到 Supabase（可重跑）",
                     disabled=bool(st.session_state.get("_mig_done"))):
            with st.spinner("分批写入中……"):
                _do_apply()
        st.caption("写完后：给 kol-bd 加 Secrets `USE_SUPABASE_STORE=1` → Reboot，"
                   "界面就会切到新库。观察无问题后，本页面和主程序里 `?migrate=1` 那 4 行可删除。")
