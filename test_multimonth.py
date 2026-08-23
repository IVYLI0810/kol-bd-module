#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多月多行改造本地模拟测试：
A. 真实模板42行导入 → 42条记录（하봄 7/8/9 三行并存）
B. 重复导入同表 → 仍42条（upsert不重复建）
C. 无月份行导入 → 不误伤月份记录，独立成行
D. 审核写入按月份精确定位
E. 改月份后旧身份仍可定位（兜底）
F. 选品导入按月份挑目标行
"""
import hashlib
import sys

sys.path.insert(0, ".")

import yts_import_flow as FI
from yts_yida_store import YTSStore, _ident, _split, _best_row


class MockDB:
    """按 yida_bd_database 的三态定位语义实现的内存版"""

    def __init__(self):
        self.rows = []
        self._n = 0

    def _find(self, channel_id, plan_month=None):
        hits = [r for r in self.rows if r.get("channel_id") == str(channel_id)]
        if not hits:
            return None
        if plan_month is None:
            return hits[0]
        for r in hits:
            if (r.get("plan_month") or "") == plan_month:
                return r
        return None

    def add(self, record):
        if not record.get("channel_id"):
            raise ValueError("channel_id 为必填字段")
        month = str(record.get("plan_month") or "").strip()
        ex = self._find(record["channel_id"], month)
        data = {k: v for k, v in record.items() if v not in (None, "")}
        if ex:
            for k, v in data.items():
                ex[k] = v
            return dict(ex)
        self._n += 1
        rec = dict(data)
        rec["form_instance_id"] = f"FINST-{self._n:04d}"
        rec.setdefault("audit_log", [])
        rec.setdefault("videos", [])
        rec.setdefault("products", [])
        self.rows.append(rec)
        return dict(rec)

    def get_by_channel_id(self, channel_id, plan_month=None):
        r = self._find(channel_id, plan_month)
        return dict(r) if r else None

    def get_all(self, filters=None):
        return [dict(r) for r in self.rows]

    def update(self, channel_id, updates, clear_fields=None, plan_month=None):
        r = self._find(channel_id, plan_month)
        if not r:
            return None
        for k, v in updates.items():
            if v not in (None, ""):
                r[k] = v
        for c in clear_fields or ():
            r[c] = ""
        return None

    def update_instance(self, instance_id, updates, clear_fields=None):
        r = next((x for x in self.rows
                  if x.get("form_instance_id") == instance_id), None)
        if not r:
            return False
        for k, v in updates.items():
            if v not in (None, ""):
                r[k] = v
        for c in clear_fields or ():
            r[c] = ""
        return True

    def add_audit(self, channel_id, result, opinion, audit_date="",
                  extra_fields=None, plan_month=None):
        r = self._find(channel_id, plan_month)
        if not r:
            return False
        log = list(r.get("audit_log") or [])
        log.append({"audit_date": audit_date or "2026-08-24 10:00",
                    "audit_result": result, "audit_opinion": opinion})
        r["audit_log"] = log
        r["audit_status"] = result
        for k, v in (extra_fields or {}).items():
            r[k] = v
        return True

    def get_audit_log(self, channel_id, plan_month=None):
        r = self._find(channel_id, plan_month)
        return list((r or {}).get("audit_log") or [])


def fake_cid(url: str) -> str:
    if "youtu" in url and "/channel/UC" in url:
        return url.split("/channel/UC", 1)[1].split("/")[0] and \
            "UC" + url.split("/channel/UC", 1)[1].split("/")[0]
    return "UC" + hashlib.md5(url.encode()).hexdigest()[:22]


PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


TPL = "/Users/iivyli/Downloads/YTS流程导入模版-2.xlsx"
HABOM_URL_KEY = "하봄"
HABOM_CID = "UCpMTiotH-azWcWrIGeiBZbw"

with open(TPL, "rb") as f:
    rows, issues = FI.parse_workbook(f.read())
print(f"模板解析：{len(rows)} 行；问题提示 {len(issues)} 条")

# 给每行一个稳定的频道ID：하봄 用真实ID，其余按链接生成
url_cid = {}
for raw in rows:
    u = str(raw["channel_url"]).strip()
    nm = str(raw.get("channel_name") or "")
    if HABOM_URL_KEY in nm:
        url_cid[u] = HABOM_CID
    else:
        url_cid[u] = url_cid.get(u) or fake_cid(u)

store = YTSStore(MockDB())

print("\n== A. 首次导入 42 行 ==")
for raw in rows:
    rec = FI.derive_record(raw, url_cid[str(raw["channel_url"]).strip()])
    rec.pop("_shoot_raw", None); rec.pop("_plan_auto", None)
    rec.pop("_split_n", None); rec.pop("_closed_no_link", None)
    store.import_flow(rec)
all_rows = store.list_all()
check("记录数=42", len(all_rows) == 42, f"实际 {len(all_rows)}")

habom = [c for c in all_rows if (c.get("channel_id") or "") == HABOM_CID]
months = sorted(c["plan_month"] for c in habom)
check("하봄 三行并存 07/08/09", months == ["2026-07", "2026-08", "2026-09"],
      f"实际 {months}")
h7 = next(c for c in habom if c["plan_month"] == "2026-07")
check("하봄7月 已闭环", bool(h7["is_closed"]), f"stage={h7['stage']}")
check("하봄7月 3条视频", len(h7["videos"]) == 3,
      f"实际 {len(h7['videos'])}: {[v.get('video_url','')[:30] for v in h7['videos']]}")
check("하봄7月 报价50万", int(h7["price"]) == 500000, f"实际 {h7['price']}")

print("\n== B. 同表重导（upsert） ==")
for raw in rows:
    rec = FI.derive_record(raw, url_cid[str(raw["channel_url"]).strip()])
    rec.pop("_shoot_raw", None); rec.pop("_plan_auto", None)
    rec.pop("_split_n", None); rec.pop("_closed_no_link", None)
    store.import_flow(rec)
check("重导后仍42条", len(store.list_all()) == 42,
      f"实际 {len(store.list_all())}")

print("\n== C. 无月份行不误伤月份记录 ==")
raw0 = {"channel_url": rows[0]["channel_url"],
        "channel_name": str(rows[0].get("channel_name") or ""),
        "recruiter": "测试", "plan_month": ""}
cid0 = url_cid[str(rows[0]["channel_url"]).strip()]
store.import_flow(FI.derive_record(raw0, cid0))
rows0 = [c for c in store.list_all() if c.get("channel_id") == cid0]
check("该频道多了一条无月份行",
      len(rows0) == 2 and "" in (c["plan_month"] for c in rows0),
      f"实际 {[c['plan_month'] for c in rows0]}")
check("总数=43", len(store.list_all()) == 43, f"实际 {len(store.list_all())}")

print("\n== D. 审核按月份精确定位 ==")
h8 = next(c for c in habom if c["plan_month"] == "2026-08")
store._upd(h8["collab_id"], {"video_link": "https://youtu.be/test8",
                               "audit_status": "待审核"})
ok = store.db.add_audit(HABOM_CID, result="已通过", opinion="审了8月这条",
                        plan_month="2026-08")
check("add_audit(8月) 成功", ok)
fresh7 = store.db.get_by_channel_id(HABOM_CID, "2026-07")
fresh8 = store.db.get_by_channel_id(HABOM_CID, "2026-08")
check("8月记录有审核日志", len(fresh8["audit_log"]) == 1)
check("7月记录不受影响", len(fresh7["audit_log"]) == 0)

print("\n== E. 改月份后旧身份兜底 ==")
# 单条记录的频道：旧身份宽松兜底仍能找到
solo_raw = {"channel_url": "https://www.youtube.com/@solotest",
            "channel_name": "单独测试", "recruiter": "测试",
            "plan_month": "2026-08"}
store.import_flow(FI.derive_record(solo_raw, "UCSOLOTEST0001"))
store.update_info("UCSOLOTEST0001#2026-08", {"plan_month": "2026-11"})
c_old = store.get_collab("UCSOLOTEST0001#2026-08")
check("单条频道：旧身份仍可定位",
      c_old is not None and c_old["plan_month"] == "2026-11",
      f"{c_old and c_old['plan_month']}")
check("单条频道：新身份定位",
      store.get_collab("UCSOLOTEST0001#2026-11") is not None)
# 多月频道：旧月份身份天然歧义 → None（UI 侧保存时已把会话ID换成新身份）
store.update_info(h8["collab_id"], {"plan_month": "2026-10",
                                      "price": "600000"})
check("多月频道：旧身份返回None（由UI更新会话ID兜底）",
      store.get_collab(f"{HABOM_CID}#2026-08") is None)
check("多月频道：新身份定位",
      store.get_collab(f"{HABOM_CID}#2026-10") is not None)

print("\n== F. 选品导入按月份挑行 ==")
import yts_product_import as PI
recs = store.list_all()
g7 = {"name": "하봄", "recruiter": "x", "channel_url": h7["channel_url"],
      "month": "7月", "products": [{"id": "100500123456", "name": "p",
                                     "url": "https://ko.aliexpress.com/item/100500123456.html"}]}
g8 = dict(g7, month="8月")
m = PI.match_groups([g7, g8], recs)
t7 = m[0]["matched"]["plan_month"] if m[0]["matched"] else None
t8 = m[1]["matched"]["plan_month"] if m[1]["matched"] else None
check("7月表 → 2026-07 行", t7 == "2026-07", f"实际 {t7} / {m[0]['match_by']}")
check("8月表 → 2026-10 行（同月份数字兜底）", t8 == "2026-10",
      f"实际 {t8} / {m[1]['match_by']}")

print("\n== G. 身份工具 ==")
check("_split 复合", _split("UCabc#2026-07") == ("UCabc", "2026-07"))
check("_split 裸ID", _split("UCabc") == ("UCabc", ""))
check("_ident 有月", _ident({"channel_id": "UCabc", "plan_month": "2026-07"})
      == "UCabc#2026-07")
check("_ident 无月", _ident({"channel_id": "UCabc", "plan_month": ""}) == "UCabc")
rows_g = [{"channel_id": "UCabc", "plan_month": "2026-07"},
          {"channel_id": "UCabc", "plan_month": ""}]
check("_best_row 裸ID优先无月行",
      _best_row(rows_g, "UCabc") is rows_g[1])
check("_best_row 月份精确",
      _best_row(rows_g, "UCabc#2026-07") is rows_g[0])
check("_best_row 月份不存在返回None",
      _best_row(rows_g, "UCabc#2026-12") is None)

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
