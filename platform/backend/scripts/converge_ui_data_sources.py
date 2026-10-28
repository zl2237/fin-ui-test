# -*- coding: utf-8 -*-
"""UI 用例数据收口迁移（2026-10-28 定案）：编排内生成规则搬进数据集单元格。

背景：用例步骤 value 里散落整串 ${generate_xxx(...)}（如提单号规则），违背
「数据唯一来源 = 数据集」——本脚本把规则原样搬进绑定数据集各 sheet 的指定字段，
步骤值改为 ${字段} 引用。规则文本原封不动搬运（prefix 等参数保持不变，执行行为
等价：单元格求值见 engine/expression.evaluate_dataset_cell，双通道同值见 context）。

顺序契约：先写数据集单元格，再改步骤值（中间态步骤引用空单元格会被 fill 的
空值跳过语义吞掉；两步完成后无中间态暴露）。

幂等：步骤已是 ${字段} 且单元格已是规则 → 跳过；可重复执行。

用法（platform/backend 目录下；HTTP 走平台 API，目标由 API_BASE 决定）：
    python scripts/converge_ui_data_sources.py                       # 默认 dry-run
    python scripts/converge_ui_data_sources.py --apply               # 实际写库
    API_BASE=http://192.168.22.106:8002/api python scripts/converge_ui_data_sources.py --apply
        （线上须先部署含单元格求值的后端代码，否则规则单元格只会被当字面量填出）
"""
import argparse
import json
import os
import re
import sys
import urllib.request

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api")
WHOLE_RULE_RE = re.compile(r"^\$\{(generate_\w+)\((.*)\)\}$", re.S)

# 收口目标：case → 搬家动作列表。
# field = 规则落位的数据集字段；new_field_desc = 字段新增时补的中文描述（已存在则忽略）
TARGETS = [
    {
        "case_id": 274, "dataset_id": 150,
        "moves": [
            {"node_id": "n2", "field": "bl_no", "new_field_desc": "提单号"},
            {"node_id": "n6", "field": "customer_order_sn", "new_field_desc": "客户单号"},
        ],
    },
    {
        "case_id": 283, "dataset_id": 159,
        "moves": [
            {"node_id": "g1", "field": "bl_no", "new_field_desc": "提单号"},
        ],
    },
    {
        "case_id": 287, "dataset_id": 167,
        "moves": [
            {"node_id": "rc_n2", "field": "account_simple_name",
             "new_field_desc": "对账批次简称（应收对账-新增批次）"},
            {"node_id": "g1", "field": "bl_no", "new_field_desc": "提单号"},
        ],
    },
    {
        "case_id": 288, "dataset_id": 169,
        "moves": [
            {"node_id": "n6", "field": "customer_order_sn", "new_field_desc": "客户单号"},
        ],
    },
]


def login():
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    req = urllib.request.Request(API_BASE + "/auth/login", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    tok = json.loads(urllib.request.urlopen(req).read())["token"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def api(headers, path, data=None):
    req = urllib.request.Request(API_BASE + path, headers=headers, method="GET" if data is None else "PUT",
                                 data=json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None)
    return json.loads(urllib.request.urlopen(req).read().decode("utf-8"))


def find_rule_step(case, node_id):
    """节点内找整串生成规则步骤。
    命中 → (step, 规则原文, None)；未命中 → (None, None, 原因文案)"""
    nc = next((n for n in case.get("node_configs") or [] if n and n.get("node_id") == node_id), None)
    if not nc:
        return None, None, f"节点 {node_id} 不存在"
    steps = (nc.get("ui_params") or {}).get("steps") or []
    hits = [(st, st["value"].strip()) for st in steps
            if isinstance(st.get("value"), str) and WHOLE_RULE_RE.match(st["value"].strip())]
    if not hits:
        return None, None, f"节点 {node_id} 无整串生成规则步骤"
    if len(hits) > 1:
        return None, None, f"节点 {node_id} 有 {len(hits)} 处生成规则（预期 1），请人工确认"
    return hits[0][0], hits[0][1], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    args = ap.parse_args()
    headers = login()
    print(f"目标平台：{API_BASE}（{'APPLY' if args.apply else 'DRY-RUN'}）\n")

    for t in TARGETS:
        case = api(headers, f"/testcases/{t['case_id']}")
        bound = case.get("dataset_id")
        if bound != t["dataset_id"]:
            print(f"[abort] case {t['case_id']} 绑定数据集 {bound}，与配置 {t['dataset_id']} 不符")
            return 1
        print(f"=== case {t['case_id']} {case['name']}（ds {bound}）")

        # 1) 找出各节点的规则步骤（先全部定位成功再动笔）
        rule_steps = {}
        for mv in t["moves"]:
            st, rule, err = find_rule_step(case, mv["node_id"])
            if err:
                # 幂等态判定：步骤值已是 ${字段} 引用 → 该节点无需改写
                nc = next((n for n in case.get("node_configs") or []
                           if n and n.get("node_id") == mv["node_id"]), None)
                steps = ((nc or {}).get("ui_params") or {}).get("steps") or []
                if any(isinstance(s.get("value"), str) and s["value"] == f"${{{mv['field']}}}"
                       for s in steps):
                    print(f"  {mv['node_id']}: 已是 ${{{mv['field']}}} 引用（幂等跳过步骤改写）")
                    continue
                print(f"  [abort] {mv['node_id']}: {err}")
                return 1
            rule_steps[mv["node_id"]] = (st, rule, mv)
        if not rule_steps:
            print("  全部已收口，无需动作\n")
            continue

        # 2) 数据集单元格先落规则
        dss = api(headers, f"/testcases/{t['case_id']}/datasets")
        ds = next(d for d in dss if d["id"] == bound)
        rows_out, ds_dirty = [], False
        for r in ds.get("rows") or []:
            data = dict(r.get("data") or {})
            fdesc = dict(r.get("field_desc") or {})
            forder = list(r.get("field_order") or [])
            for mv in t["moves"]:
                entry = rule_steps.get(mv["node_id"])
                field = mv["field"]
                if entry is None:
                    # 幂等跳过改写的节点：步骤已引用，只校验单元格确有生成规则
                    if not WHOLE_RULE_RE.match(str(data.get(field) or "")):
                        print(f"  [warn] sheet「{r.get('label')}」{field} 缺生成规则"
                              f"（步骤已引用但单元格非规则，请人工补）")
                    continue
                _st, rule, _mv = entry
                if data.get(field) != rule:
                    if field not in data and field not in forder:
                        forder.append(field)  # 新字段补到列序尾
                    fdesc.setdefault(field, mv.get("new_field_desc", ""))
                    old = repr(data.get(field))[:40]
                    data[field] = rule
                    ds_dirty = True
                    print(f"  sheet「{r.get('label')}」{field}: {old} -> {rule}")
            rows_out.append({"label": r.get("label"), "data": data,
                             "field_desc": fdesc, "field_order": forder})
        if ds_dirty:
            if args.apply:
                api(headers, f"/datasets/{bound}/rows", {"rows": rows_out})
                print(f"  已写数据集 ds#{bound}（{len(rows_out)} sheet）")
        else:
            print("  数据集单元格均已就位（幂等）")

        # 3) 步骤值改引用（数据集已就位后）
        node_dirty = False
        for node_id, (st, rule, mv) in rule_steps.items():
            st["value"] = f"${{{mv['field']}}}"
            node_dirty = True
            print(f"  节点 {node_id} 步骤值 -> ${{{mv['field']}}}")
        if node_dirty and args.apply:
            api(headers, f"/testcases/{t['case_id']}", {"node_configs": case["node_configs"]})
            print("  已保存用例编排")
        print()

    if not args.apply:
        print("dry-run 结束（未写库）。确认后加 --apply 执行。")
    else:
        print("收口完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
