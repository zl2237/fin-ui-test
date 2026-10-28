# -*- coding: utf-8 -*-
"""合并同页面域的顺序相邻 UI 节点（2026-10-28 编排改造后续整理）。

规则：DAG 中若 A→B 有边、A 出度 1、B 入度 1（严格线性相邻，不碰分支），
且 A、B 均为 UI 节点、页面域相同且非空、两侧均无 前置/提取/断言/等待 配置，
则把 B 的 steps 并入 A 尾部，B 的出边改挂 A，删除 B（画布节点 + 节点配置行）。
迭代到不动点——A 合并后若与后继 C 仍满足条件会继续并。

语义保持：线性相邻下步骤顺序不变（A 步骤后紧跟 B 步骤）；数据集 `${sheet.字段}`
引用与节点无关，不受影响。B 的语义名（data.desc）拼进 A 的 desc 防丢信息。

写路径走平台 PUT /testcases/{id}（全量覆盖 node_configs + 保存期域校验复检），
不直连库——避开 JSON 列 flag_modified 坑，且非法结构会被 400 拦下。

幂等：可重复执行（已合并的自然不满足条件）。

用法（platform/backend 目录下）：
    python scripts/merge_adjacent_scope_nodes.py                 # 默认 dry-run
    python scripts/merge_adjacent_scope_nodes.py --apply         # 实际写库
    API_BASE=http://192.168.22.106:8002/api python scripts/merge_adjacent_scope_nodes.py --apply
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api")

# 合并安全边界（依据线上数据实测：extras 的路径形如 $.steps[N]，按节点内步骤下标取值）：
# - 被并入方 B 带提取/断言/等待 → 不可并：步骤下标移位 + 提取变量挂在 {{B.var}} 会悬空
# - 保留方 A 带提取/断言但 B 干净 → 可并：A 的步骤仍在头部、下标不变、B 无变量被引用
#   （A 的断言触发点后移到 B 步骤之后，但校验的数据不变，结论不变）
# - A 带等待 → 不可并：等待时点会从 A/B 之间挪到整块之后
EXTRA_KEYS = ("pre_process", "post_extract", "assertions")


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
        except Exception:
            return e.code, {"raw": raw}


def has_extras(nc):
    return any(nc.get(k) for k in EXTRA_KEYS) or (nc.get("wait_after_ms") or 0) != 0


def merge_case(case):
    """返回 (payload, merges, skips)。merges=[(保留, 被并, 并入步数)]，无变化时 payload=None。"""
    dag = case.get("dag_config") or {}
    nodes = dag.get("nodes") or []
    edges = [e for e in (dag.get("edges") or []) if e.get("source") != e.get("target")]
    cfgs = {c["node_id"]: c for c in case.get("node_configs") or []}
    node_ids = {n["id"] for n in nodes}

    def ui_scope(nid):
        c = cfgs.get(nid)
        if not c or c.get("step_type") != "ui":
            return None
        s = ((c.get("ui_params") or {}).get("scope") or "").strip()
        return s or None

    merges, skips = [], []
    changed = False

    def snapshot():
        return json.dumps({"n": nodes, "e": edges, "c": list(cfgs.values())},
                          ensure_ascii=False, default=str)

    case_json = snapshot()
    while True:
        out_deg, in_deg = {}, {}
        for e in edges:
            out_deg[e["source"]] = out_deg.get(e["source"], 0) + 1
            in_deg[e["target"]] = in_deg.get(e["target"], 0) + 1
        hit = None
        for e in edges:
            a, b = e["source"], e["target"]
            if a not in node_ids or b not in node_ids:
                continue
            sa, sb = ui_scope(a), ui_scope(b)
            if sa is None or sb is None or sa != sb:
                continue
            ca, cb = cfgs[a], cfgs[b]
            if out_deg.get(a) != 1 or in_deg.get(b) != 1:
                skips.append((a, b, "非严格线性（A出度或B入度≠1）"))
                continue
            if has_extras(cb):
                skips.append((a, b, "被并侧带 前置/提取/断言/等待（下标/变量会悬空）"))
                continue
            if (ca.get("wait_after_ms") or 0) != 0:
                skips.append((a, b, "保留侧带等待（时点会后移）"))
                continue
            if f"{{{b}." in case_json:
                skips.append((a, b, f"存在 {{{{{b}.xxx}}}} 引用（防御性拦截）"))
                continue
            hit = (a, b)
            break
        if not hit:
            break
        a, b = hit
        pa, pb = cfgs[a]["ui_params"], cfgs[b]["ui_params"]
        steps_b = pb.get("steps") if isinstance(pb.get("steps"), list) else [pb]
        pa["steps"] = (pa.get("steps") if isinstance(pa.get("steps"), list) else [pa]) + steps_b
        # 语义名拼接防丢（desc 存原始用途名）
        na = next(n for n in nodes if n["id"] == a)
        nb = next(n for n in nodes if n["id"] == b)
        parts = [str(x) for x in (na.get("data", {}).get("desc"), nb.get("data", {}).get("desc")) if x]
        na.setdefault("data", {})["desc"] = "；".join(dict.fromkeys(parts))
        na["data"]["ui_steps_len"] = len(pa["steps"])
        # 画布：删 B、B 的出边改挂 A（严格线性下不会重边/成环）；保留边的其余字段
        nodes = [n for n in nodes if n["id"] != b]
        new_edges = []
        for e in edges:
            if e["source"] == a and e["target"] == b:
                continue  # A→B 吸收
            e2 = dict(e)
            if e2["source"] == b:
                e2["source"] = a
            new_edges.append(e2)
        edges = new_edges
        del cfgs[b]
        node_ids.discard(b)
        merges.append((a, b, len(steps_b)))
        changed = True
        case_json = snapshot()

    if not changed:
        return None, merges, skips

    # 客户端完整性自检：边端点均存在、无自环
    for e in edges:
        if e["source"] not in node_ids or e["target"] not in node_ids or e["source"] == e["target"]:
            raise ValueError(f"DAG 完整性检查失败：边 {e}")

    KEEP = ("node_id", "api_id", "step_type", "ui_params", "pre_process",
            "post_extract", "assertions", "wait_after_ms")
    payload = {k: case.get(k) for k in ("group_id", "name", "description",
                                        "case_type", "env_id", "dataset_id", "shared_vars")}
    payload["dag_config"] = {"nodes": nodes, "edges": edges}
    payload["node_configs"] = [{k: c[k] for k in KEEP if k in c} for c in cfgs.values()]
    return payload, merges, skips


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    ap.add_argument("--case", type=int, action="append", help="限定用例 id（可多次；默认全部 normal）")
    args = ap.parse_args()

    st, tok_r = call("POST", "/auth/login", {"username": "admin", "password": "admin123"})
    if st != 200:
        sys.exit(f"登录失败: {st} {tok_r}")
    tok = tok_r["token"]

    st, projects = call("GET", "/projects", token=tok)
    cases = []
    for p in projects:
        st, lst = call("GET", f"/testcases?project_id={p['id']}", token=tok)
        if st == 200:
            cases += [c for c in lst if c.get("case_type") == "normal"]
    if args.case:
        want = set(args.case)
        cases = [c for c in cases if c["id"] in want]
        missing = want - {c["id"] for c in cases}
        if missing:
            sys.exit(f"用例不存在或非 normal: {sorted(missing)}")
    print(f"扫描 {len(cases)} 个 normal 用例\n")

    n_applied = 0
    for c in cases:
        st, full = call("GET", f"/testcases/{c['id']}", token=tok)
        if st != 200:
            print(f"[{c['id']}] {c['name']}: GET {st}，跳过")
            continue
        try:
            payload, merges, skips = merge_case(full)
        except ValueError as e:
            print(f"[{full['id']}] {full['name']}: {e}，跳过（不写库）")
            continue
        if not merges:
            continue
        before = len((full.get("dag_config") or {}).get("nodes") or [])
        after = before - len(merges)
        print(f"[{full['id']}] {full['name']}: {before} → {after} 节点")
        for a, b, n in merges:
            print(f"    {a} ← 并入 {b}（+{n} 步）")
        for a, b, why in sorted(set(skips)):
            print(f"    未并 {a}→{b}: {why}")
        if not args.apply:
            continue
        st2, r2 = call("PUT", f"/testcases/{full['id']}", payload, tok)
        if st2 == 200:
            n_applied += 1
            print("    已保存（PUT 200）")
        else:
            print(f"    保存失败 PUT {st2}: {r2}")

    if args.apply:
        print(f"\n完成：{n_applied} 个用例已合并保存")
    else:
        print("\ndry-run 结束（未写库）。确认后加 --apply 执行。")


if __name__ == "__main__":
    main()
