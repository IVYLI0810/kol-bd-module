# -*- coding: utf-8 -*-
"""
宜搭底库垂类一键更新：把宜搭表单里的「垂类」换成新版官方26类
====================================================================
背景：YTS 同步宜搭时「垂类」只空缺时补、已有值不覆盖，所以库里改成新版后
宜搭里的旧垂类不会自己变，需要这个脚本单独刷一遍。

逻辑：
1. 拉宜搭全部记录（按频道ID对齐）
2. 拉 kol-finder 公共库（Supabase）里每个频道的新版带货垂类
3. 库里有的 → 用库里的新值覆盖宜搭垂类（库值必须非空，且与宜搭现值不同才动）
4. 库里没有的 → 宜搭垂类若是已知旧值，按对照表机械映射；否则不动
   （宜搭只存货运垂类一个标签；内容垂类在 kol-finder 库里维护）

凭证：读 ~/Desktop/yts_demo/yida_config_local.py（本机已有）

用法：
  python3 migrate_yida_categories.py            # 预览：将改哪些、改成什么
  python3 migrate_yida_categories.py --apply    # 真正执行
"""

import sys
import os
import requests

# 宜搭配置：本机 yts_demo 目录下的本地配置文件
sys.path.insert(0, os.path.expanduser("~/Desktop/yts_demo"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yida_bd_database import YidaBDDB
from yida_config_local import YIDA_CONFIG

# kol-finder 公共库（与 yts_roster.py 相同的只读地址）
SUPABASE_URL = "https://webjrwzorxxlqrcrrnro.supabase.co"
SUPABASE_KEY = "sb_publishable_eUDicGLoUiNhPO04S6iz8g_UX_SkSCH"

# 新版官方26类（安全锁：只有属于这张表的值才允许写进宜搭，
# 防止公共库还没迁完时把旧值复制过去、甚至把宜搭的新值改回旧值）
NEW_COMMERCE_TABLE = {
    "여성 의류", "남성 의류", "뷰티 & 헬스", "홈 & 가든", "반려동물 용품",
    "완구 & 게임", "식품 & 장보기", "스포츠 & 아웃도어", "휴대폰 & 액세서리",
    "전자제품", "가전제품", "주얼리 & 액세서리", "가방 & 캐리어", "신발",
    "유아 & 출산", "가구", "공구 & 홈인테리어", "자동차 부품",
    "오토바이 & 파워스포츠", "사무 & 학용품", "공예 & 재봉",
    "헤어 익스텐션 & 가발", "서적 & 미디어", "특수 의류 & 코스프레",
    "산업 & 과학", "기타",
}

# 宜搭旧垂类值 → 新版带货垂类（库里查不到该频道时的机械兜底，
# 与 kol-finder migrate_categories.py 的阶段A对照表一致）
OLD_VALUE_MAP = {
    "平价美妆": "뷰티 & 헬스",
    "家居收纳": "홈 & 가든",
    "宿舍好物": "홈 & 가든",
    "通勤配件": "주얼리 & 액세서리",
    "宠物用品": "반려동물 용품",
    "学生用品": "사무 & 학용품",
    "네일": "뷰티 & 헬스",
    "생활용품": "홈 & 가든",
    "의복 & 부속품": "주얼리 & 액세서리",
    "의복&부속품": "주얼리 & 액세서리",
    "컴퓨터 및 오피스": "사무 & 학용품",
    "전화 및 통신 액세서리": "휴대폰 & 액세서리",
    "애완동물": "반려동물 용품",
    "완구 및 취미": "완구 & 게임",
    "도구": "공구 & 홈인테리어",
    "음식": "식품 & 장보기",
    "오토바이 장비 및 부품": "오토바이 & 파워스포츠",
    "오토바이": "오토바이 & 파워스포츠",
    "학생용품": "사무 & 학용품",
    "문구 및 학용품": "사무 & 학용품",
}


def fetch_kol_finder() -> dict:
    """从 kol-finder 库分页拉 channel_id → 带货垂类"""
    out = {}
    off = 0
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/influencers",
            params={"select": "channel_id,category", "limit": 1000, "offset": off},
            headers=headers, timeout=30)
        r.raise_for_status()
        batch = r.json() or []
        for row in batch:
            cid = (row.get("channel_id") or "").strip()
            cat = (row.get("category") or "").strip()
            if cid:
                out[cid] = cat
        off += len(batch)
        if len(batch) < 1000:
            break
    return out


def main():
    apply_mode = "--apply" in sys.argv

    print("1/3 读取宜搭底库…")
    db = YidaBDDB(**YIDA_CONFIG)
    yida_rows = db.get_all()
    print(f"    宜搭共 {len(yida_rows)} 条记录")

    print("2/3 读取 kol-finder 公共库…")
    kf = fetch_kol_finder()
    print(f"    公共库共 {len(kf)} 条记录")

    # 3) 比对生成计划
    plan, skipped_same, waiting_lib, no_match_keep = [], 0, [], []
    dist: dict = {}
    for rec in yida_rows:
        cid = (rec.get("channel_id") or "").strip()
        cur = (rec.get("category") or "").strip()
        name = rec.get("channel_name", "") or cid[:12]
        dist[cur or "(空)"] = dist.get(cur or "(空)", 0) + 1

        new, reason = "", ""
        if cid in kf:
            lib_val = kf[cid]
            if lib_val in NEW_COMMERCE_TABLE:
                # 公共库已是新版值 → 直接对齐
                if lib_val != cur:
                    new, reason = lib_val, "按公共库新值"
            else:
                # 公共库自己还是旧值 → 等公共库迁移完再同步，现在不动
                waiting_lib.append(f"{name}（宜搭={cur or '空'}，库={lib_val or '空'}）")
                continue
        elif cur in OLD_VALUE_MAP:
            # 公共库里查不到：宜搭旧值按对照表机械映射
            new, reason = OLD_VALUE_MAP[cur], "库里无此频道，按对照表"
        else:
            no_match_keep.append(f"{name}（垂类={cur or '空'}）")
            continue

        if not new or new == cur:
            skipped_same += 1
            continue
        plan.append({
            "instance_id": rec.get("form_instance_id"),
            "name": name,
            "old": cur or "(空)",
            "new": new,
            "reason": reason,
        })

    print("\n宜搭当前垂类取值分布：")
    for c, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {c}: {n}")

    print(f"\n更新计划：改 {len(plan)} 条，已一致 {skipped_same} 条，"
          f"等公共库先迁移 {len(waiting_lib)} 条，不认识不动 {len(no_match_keep)} 条")
    for p in plan[:40]:
        print(f"  {p['name'][:24]:24s} | {p['old']} → {p['new']}（{p['reason']}）")
    if len(plan) > 40:
        print(f"  … 另有 {len(plan) - 40} 条")
    if waiting_lib:
        print(f"\n以下 {len(waiting_lib)} 条要等公共库迁移完再跑本脚本才会同步（示例前10）：")
        for line in waiting_lib[:10]:
            print(f"  - {line}")
    if no_match_keep:
        print(f"\n以下 {len(no_match_keep)} 条公共库里查不到且不是已知旧值，保持原样：")
        for line in no_match_keep[:10]:
            print(f"  - {line}")

    if not apply_mode:
        print("\n这是预览（dry-run）。确认无误后运行：python3 migrate_yida_categories.py --apply")
        return

    print("\n3/3 执行更新…")
    ok, fail = 0, 0
    for p in plan:
        try:
            db.update_instance(p["instance_id"], {"category": p["new"]})
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  ⚠️ {p['name']} 更新失败：{e}")
    print(f"\n✅ 完成：成功 {ok} 条，失败 {fail} 条")


if __name__ == "__main__":
    main()
