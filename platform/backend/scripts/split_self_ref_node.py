# -*- coding: utf-8 -*-
"""拆分组内自引用节点（merge_adjacent_scope_nodes 的修复手术，2026-10-28）。

背景：同域相邻节点合并把「消费 A 提取变量」的 B 步骤并进 A 后，B 侧的
`${A.var}` 变成组内自引用——post_extract 要等整组跑完才落注册表，组内
消费时序必失败（线上 case 287 rc_n5 pick `${rc_n5.create_by}` 实证）。

修复：把命中节点从首个自引用步骤处一分为二——
  A（原 id）保留前段步骤 + 下标未移位的提取/断言；B（新 id，同域同 label）
  接走后段步骤 + `$.steps[N>=切点]` 的提取/断言，下游出边改挂 B。
拆完 `${A.var}` 恢复为跨节点引用（A 的 post_extract 先落库，B 后执行）。

写路径走平台 PUT /testcases/{id}（保存期域校验复检）。幂等：目标新节点已
存在则跳过。dry-run 默认，APPLY=1 落库。

用法（platform/backend 目录下）：
    API_BASE=http://192.168.22.106:8002/api APPLY=1 \
        python scripts/split_self_ref_node.py 287 rc_n5 rc_n5b
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api")
APPLY = os.environ.get("APPLY") == "1"
SELF_REF = re.compile(r"\$\{([a-zA-Z_][\w]*)\.(\w+)\}")
STEP_IDX = re.compile(r"\$\.steps\[(\d+)\]")
KEEP = ("node_id", "api_id", "step_type", "ui_params", "pre_process",
        "post_extract", "assertions", "wait_after_ms")


def call(method, path, body=None, token=None):
    req = urllib.request.Request(API_BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw}


def split_step_index(steps, node_id, own_vars):
    """首个自引用步骤下标：步骤文本引用 ${本节点.own_vars 中的变量}。"""
    for i, st in enumerate(steps):
        text = json.dumps(st, ensure_ascii=False)
        if any(m.group(1) == node_id and m.group(2) in own_vars
               for m in SELF_REF.finditer(text)):
            return i
    return -1


def main():
    case_id, host_id, new_id = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    _, tok = call("POST", "/auth/login",
                  {"username": "admin", "password": "admin123"})
    token = tok.get("token") or tok.get("access_token")
    _, case = call("GET", f"/testcases/{case_id}", token=token)

    dag = case.get("dag_config") or {}
    nodes = dag.get("nodes") or []
    edges = [e for e in (dag.get("edges") or []) if e.get("source") != e.get("target")]
    cfgs = {c["node_id"]: c for c in case.get("node_configs") or []}
    if new_id in cfgs:
        print(f"节点 {new_id} 已存在，幂等跳过")
        return
    if host_id not in cfgs:
        raise SystemExit(f"节点 {host_id} 不存在")

    cfg = cfgs[host_id]
    steps = (cfg.get("ui_params") or {}).get("steps")
    if not isinstance(steps, list) or not steps:
        raise SystemExit(f"{host_id} 无步骤组")
    pe = cfg.get("post_extract") or []
    own = {x.get("name") for x in pe if x.get("name")}
    cut = split_step_index(steps, host_id, own)
    if cut <= 0:
        raise SystemExit(f"{host_id} 未检出组内自引用（或切点在首位，无可保留前段）")
    print(f"{host_id} 共 {len(steps)} 步，切点=步骤[{cut}]"
          f"（前 {cut} 步留 A，后 {len(steps) - cut} 步归 {new_id}）")

    # 提取/断言按 $.steps[N] 下标分流：<切点留 A，>=切点随步骤走 B
    def move_extras(rows):
        stay, moved = [], []
        for x in rows or []:
            m = STEP_IDX.search(json.dumps(x, ensure_ascii=False))
            (moved if m and int(m.group(1)) >= cut else stay).append(x)
        return stay, moved

    pe_a, pe_b = move_extras(pe)
    as_a, as_b = move_extras(cfg.get("assertions"))

    # B：新节点（同域同 label；desc 取 A desc 的后半段或标注续段）
    host_node = next(n for n in nodes if n["id"] == host_id)
    data = dict(host_node.get("data") or {})
    desc = str(data.get("desc") or "")
    data["desc"] = desc.split("；")[-1] if "；" in desc else desc + "·续"
    b_steps = steps[cut:]
    data["ui_steps_len"] = len(b_steps)
    pos = dict(host_node.get("position") or {"x": 0, "y": 0})
    pos["x"] = pos.get("x", 0) + 220
    b_node = {"id": new_id, "type": host_node.get("type"),
              "label": host_node.get("label"), "data": data, "position": pos}
    b_cfg = {"node_id": new_id, "step_type": cfg.get("step_type"),
             "ui_params": {"scope": (cfg.get("ui_params") or {}).get("scope"),
                           "steps": b_steps},
             "wait_after_ms": 0}
    if pe_b:
        b_cfg["post_extract"] = pe_b
    if as_b:
        b_cfg["assertions"] = as_b

    # A：留前段；下标未移位（前段位置不变），提取/断言留 <切点 部分
    # （schema 要求列表：空则整键省略，不传 null）
    cfg["ui_params"]["steps"] = steps[:cut]
    if pe_a:
        cfg["post_extract"] = pe_a
    else:
        cfg.pop("post_extract", None)
    if as_a:
        cfg["assertions"] = as_a
    else:
        cfg.pop("assertions", None)
    host_node["data"]["ui_steps_len"] = cut
    nodes.append(b_node)
    edges.append({"source": host_id, "target": new_id})
    edges = [{**e, "source": new_id if e["source"] == host_id and e["target"] != new_id else e["source"]}
             for e in edges]

    payload = {k: case.get(k) for k in ("group_id", "name", "description",
                                        "case_type", "env_id", "dataset_id", "shared_vars")}
    payload["dag_config"] = {"nodes": nodes, "edges": edges}
    payload["node_configs"] = [{k: c[k] for k in KEEP if k in c} for c in cfgs.values()] + [b_cfg]
    print(f"节点 {len(nodes)} 个 / 边 {len(edges)} 条；A 提取 {len(pe_a)} 条留原位，"
          f"B 带走提取 {len(pe_b)} 条、断言 {len(as_b)} 条")

    if not APPLY:
        print("DRY-RUN（APPLY=1 落库）")
        return
    st, r = call("PUT", f"/testcases/{case_id}", payload, token)
    print(f"PUT {st}: {json.dumps(r, ensure_ascii=False)[:200] if st != 200 else '已保存'}")
    if st != 200:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
