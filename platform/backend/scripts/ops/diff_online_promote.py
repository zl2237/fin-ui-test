# -*- coding: utf-8 -*-
"""本地 vs 线上 修复晋升前全量 diff（只读，不写任何库）。
覆盖：六用例 case_node_configs / ui_elements 全表 / 相关数据集行 / test_files 名单。
输出落盘 UTF-8：Temp/online_promote_diff.txt
"""
import io
import json

import pymysql

CASES = [274, 277, 278, 283, 287, 288]
OUT = io.open(r"Temp/online_promote_diff.txt", "w", encoding="utf-8")


def L(*a):
    print(*a, file=OUT)


def conn(local_):
    if local_:
        return pymysql.connect(host="127.0.0.1", port=3306, user="root",
                               password="123456", database="fin_ui_test", charset="utf8mb4")
    return pymysql.connect(host="192.168.2.51", port=20001, user="dev-wifi",
                           password="Dev%%0532", database="fin_ui_test", charset="utf8mb4")


def rows(cur, sql, args=None):
    cur.execute(sql, args or ())
    return cur.fetchall()


def jload(x):
    return json.loads(x) if isinstance(x, str) else x


lc, oc = conn(True), conn(False)
lcur, ocur = lc.cursor(), oc.cursor()

# ---------- 1) 六用例节点配置 ----------
L("=" * 70)
L("### 1) case_node_configs (cases %s)" % CASES)
for cid in CASES:
    lmap = {nid: (jload(p), jload(a), st) for nid, p, a, st in rows(
        lcur, "SELECT node_id, ui_params, assertions, step_type FROM case_node_configs WHERE case_id=%s", (cid,))}
    omap = {nid: (jload(p), jload(a), st) for nid, p, a, st in rows(
        ocur, "SELECT node_id, ui_params, assertions, step_type FROM case_node_configs WHERE case_id=%s", (cid,))}
    if lmap == omap:
        L(f"case{cid}: 节点配置与线上一致 ({len(lmap)} nodes)")
        continue
    L(f"case{cid}: 有差异 nodes local={len(lmap)} online={len(omap)}")
    for nid in sorted(set(lmap) | set(omap)):
        lv, ov = lmap.get(nid), omap.get(nid)
        if lv == ov:
            continue
        if lv is None:
            L(f"  {nid}: 仅线上存在")
            continue
        if ov is None:
            L(f"  {nid}: 仅本地存在")
            continue
        lp_, la_, lst = lv
        op_, oa_, ost = ov
        if lp_ != op_:
            ls = lp_.get("steps") if isinstance(lp_, dict) else None
            os_ = op_.get("steps") if isinstance(op_, dict) else None
            if ls is not None and os_ is not None:
                L(f"  {nid}: steps local={len(ls)} online={len(os_)}")
                for i in range(max(len(ls), len(os_))):
                    a = ls[i] if i < len(ls) else None
                    b = os_[i] if i < len(os_) else None
                    if a != b:
                        L(f"    [{i}] L={json.dumps(a, ensure_ascii=False)[:160]}")
                        L(f"    [{i}] O={json.dumps(b, ensure_ascii=False)[:160]}")
            else:
                L(f"  {nid}: ui_params 整体不同 L={json.dumps(lp_, ensure_ascii=False)[:120]}")
                L(f"  {nid}: ui_params 整体不同 O={json.dumps(op_, ensure_ascii=False)[:120]}")
        if la_ != oa_:
            L(f"  {nid}: assertions local={len(la_ or [])} online={len(oa_ or [])} 不一致!")

# ---------- 2) ui_elements ----------
L("=" * 70)
L("### 2) ui_elements 全表（strategies 差异）")
lel = {i: jload(s) for i, s in rows(lcur, "SELECT id, strategies FROM ui_elements")}
oel = {i: jload(s) for i, s in rows(ocur, "SELECT id, strategies FROM ui_elements")}
for eid in sorted(set(lel) | set(oel)):
    if lel.get(eid) != oel.get(eid):
        L(f"  el{eid}: L={json.dumps(lel.get(eid), ensure_ascii=False)[:140]}")
        L(f"  el{eid}: O={json.dumps(oel.get(eid), ensure_ascii=False)[:140]}")
L(f"  (本地 {len(lel)} / 线上 {len(oel)} 个元素)")

# ---------- 3) 数据集 ----------
L("=" * 70)
L("### 3) 数据集（六用例绑定 + case 私有池）")
dsids = set()
for cid in CASES:
    for (ds,) in rows(lcur, "SELECT dataset_id FROM test_cases WHERE id=%s", (cid,)):
        if ds:
            dsids.add(ds)
    for (ds,) in rows(lcur, "SELECT id FROM data_sets WHERE case_id=%s", (cid,)):
        dsids.add(ds)
L(f"  检查 dataset ids: {sorted(dsids)}")
for ds in sorted(dsids):
    lrow = {rid: jload(d) for rid, d in rows(
        lcur, "SELECT id, data FROM data_set_rows WHERE dataset_id=%s", (ds,))}
    orow = {rid: jload(d) for rid, d in rows(
        ocur, "SELECT id, data FROM data_set_rows WHERE dataset_id=%s", (ds,))}
    # 行 id 可能两库不同步：按 row_index 对齐更稳
    lby = {i: jload(d) for i, d in rows(
        lcur, "SELECT row_index, data FROM data_set_rows WHERE dataset_id=%s ORDER BY row_index", (ds,))}
    oby = {i: jload(d) for i, d in rows(
        ocur, "SELECT row_index, data FROM data_set_rows WHERE dataset_id=%s ORDER BY row_index", (ds,))}
    if lby == oby:
        L(f"  ds{ds}: 一致 ({len(lby)} 行)")
        continue
    L(f"  ds{ds}: 差异（本地 {len(lby)} 行 / 线上 {len(oby)} 行）")
    for ri in sorted(set(lby) | set(oby)):
        a, b = lby.get(ri), oby.get(ri)
        if a == b:
            continue
        if a is None or b is None:
            L(f"    row{ri}: 仅{'线上' if a is None else '本地'}存在")
            continue
        keys = sorted(set(a) | set(b))
        diffs = [(k, a.get(k), b.get(k)) for k in keys if a.get(k) != b.get(k)]
        for k, lv, ov in diffs:
            L(f"    row{ri}.{k}: L={json.dumps(lv, ensure_ascii=False)[:80]} O={json.dumps(ov, ensure_ascii=False)[:80]}")

# ---------- 4) test_files ----------
L("=" * 70)
L("### 4) test_files（本地 3107/3108 名+sha 在线上是否存在）")
lf = rows(lcur, "SELECT id, name, sha256 FROM test_files WHERE id IN (3107,3108)")
for fid, name, sha in lf:
    hit = rows(ocur, "SELECT id, name FROM test_files WHERE sha256=%s", (sha,))
    name_hit = rows(ocur, "SELECT id, name FROM test_files WHERE name=%s AND project_id=1", (name,))
    L(f"  本地 {fid} {name}: sha命中线上={hit} 同名命中={name_hit}")

lc.close()
oc.close()
OUT.close()
print("diff written")
