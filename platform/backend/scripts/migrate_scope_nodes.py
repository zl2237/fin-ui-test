# -*- coding: utf-8 -*-
"""编排模型迁移：UI 节点补页面域（2026-10-28 编排改造「节点=页面域」）。

背景：编排改造后每个画布节点代表一个页面域——ui_params 增加 scope 字段、
dag_config 节点 data 增加 scope + 域中文名 label。存量节点无 scope，
直接保存会被新校验拦截（「未设置页面域」），本脚本为存量节点推导并回填。

推导链（对每个 UI 节点）：
    1. 步骤元素引用 → 元素所属 page_scope（多域节点不自动拆分：报告 + 跳过，
       两库实测均为 0 个，拆分逻辑不值得引入未经实测的边改写）；
    2. goto URL 字面量内嵌 page_scope（如 #/development/orderManage/businessOrder）；
    3. goto URL 为 ${var} → 从用例绑定数据集行解析字段值后再按 2 匹配；
    4. 前驱继承：同用例拓扑序上最近一个已定域节点（动作停留在上一 goto 页面）；
    5. 后继继承（首节点未定域时）；
    6. 仍无法推导 → 不写 scope，报告人工指派（UI 上节点抽屉可选域补设）。

写库内容：
    - CaseNodeConfig.ui_params["scope"]（其余键原样保留，含单动作历史形态）
    - dag_config 节点 data：label=域中文名（page_scope_labels，缺省用 scope 原串）、
      scope、ui_action="steps"、ui_steps_len=步骤数；原 label 存入 data.desc 备查。

用法（platform/backend 目录下，目标库由 backend/.env 或环境变量决定）：
    python scripts/migrate_scope_nodes.py                # dry-run：只报告
    python scripts/migrate_scope_nodes.py --apply        # 实际写库
    DB_HOST=192.168.2.51 DB_PORT=20001 DB_USER=dev-wifi DB_PASSWORD=*** \\
        python scripts/migrate_scope_nodes.py --apply    # 指向线上库

幂等：已带 scope 的节点跳过；重复执行无副作用。
时序：必须在部署含 validate_ui_scope_bindings 的后端【之后】、用户手工保存
受影响用例【之前】执行（部署前的旧代码忽略 scope，先后皆不破坏数据）。
"""
import argparse
import json
import re
import sys
from collections import Counter, deque
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

import os

os.environ.setdefault("DB_PASSWORD", "x")

from app.database import SessionLocal
from app import models

VAR_RE = re.compile(r"^\$\{([A-Za-z_][\w]*)\}$")  # 纯字段引用（无 sheet 命名空间）


def topo_order(dag: dict) -> list[str]:
    """Kahn 拓扑序（节点数组序为稳定破平局）；孤儿节点按数组序附后。"""
    nodes = [n.get("id") for n in (dag or {}).get("nodes", []) if n.get("id")]
    idx = {nid: i for i, nid in enumerate(nodes)}
    edges = [(e.get("source"), e.get("target"))
             for e in (dag or {}).get("edges", []) if e.get("source") and e.get("target")]
    indeg = {nid: 0 for nid in nodes}
    out = {nid: [] for nid in nodes}
    for s, t in edges:
        if s in out and t in indeg:
            out[s].append(t)
            indeg[t] += 1
    q = sorted([n for n in nodes if indeg[n] == 0], key=idx.get)
    order, heap = [], deque(q)
    seen = set()
    while heap:
        n = heap.popleft()
        if n in seen:
            continue
        seen.add(n)
        order.append(n)
        for m in sorted(out[n], key=idx.get):
            indeg[m] -= 1
            if indeg[m] == 0:
                heap.append(m)
    return order + [n for n in nodes if n not in seen]  # 环上残余按数组序兜底


def url_scope(url: str, scopes: list[str]) -> str | None:
    """URL 字面量内嵌的 page_scope（最长匹配，大小写不敏感）。"""
    u = str(url or "").lower()
    hit = [s for s in scopes if s.lower() in u]
    return max(hit, key=len) if hit else None


def dataset_var_value(db: SessionLocal, dataset_id, var: str) -> str | None:
    """${var} → 绑定数据集任一 sheet 行的字段值（首个非空字符串值）。"""
    if not dataset_id:
        return None
    rows = (db.query(models.DataSetRow)
            .filter(models.DataSetRow.dataset_id == dataset_id)
            .order_by(models.DataSetRow.row_index).all())
    for r in rows:
        v = (r.data or {}).get(var) if isinstance(r.data, dict) else None
        if isinstance(v, str) and v.strip():
            return v
    return None


def node_steps(params: dict) -> list[dict]:
    steps = params.get("steps") if isinstance(params.get("steps"), list) else [params]
    return [s for s in steps if isinstance(s, dict)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        running = (db.query(models.ExecutionRecord)
                   .filter(models.ExecutionRecord.status == "running").count())
        if running:
            print(f"[abort] 有 {running} 个执行进行中，等执行结束再跑")
            return 1

        el_scope = {e.id: e.page_scope for e in db.query(models.UiElement).all()}
        all_scopes = sorted(set(el_scope.values()), key=len, reverse=True)
        labels = {l.page_scope: l.label for l in db.query(models.PageScopeLabel).all()}
        print(f"元素库 {len(el_scope)} 个元素，{len(all_scopes)} 个页面域；"
              f"域名字典 {len(labels)} 条")

        rows = (db.query(models.CaseNodeConfig)
                .join(models.TestCase, models.TestCase.id == models.CaseNodeConfig.case_id)
                .filter(models.CaseNodeConfig.step_type == "ui",
                        models.TestCase.case_type == "normal").all())
        by_case: dict[int, list] = {}
        for cfg in rows:
            by_case.setdefault(cfg.case_id, []).append(cfg)
        print(f"normal 用例的 UI 节点配置 {len(rows)} 行，分布在 {len(by_case)} 个用例\n")

        how = Counter()
        report, multi_nodes, unassigned, missing_in_dag = [], [], [], []
        planned_cfg: list[tuple] = []   # (cfg, new_params, scope, reason)
        planned_dag: list[tuple] = []   # (case, new_dag)

        for cid in sorted(by_case):
            case = db.query(models.TestCase).get(cid)
            if not case or not case.dag_config:
                continue
            dag = case.dag_config
            dag_nodes = {n.get("id"): n for n in dag.get("nodes", [])}
            order = topo_order(dag)
            # 用例内两遍：先定有依据的域，再做前后继承
            node_scope: dict[str, tuple[str, str]] = {}  # node_id -> (scope, reason)
            for cfg in by_case[cid]:
                params = cfg.ui_params or {}
                if str(params.get("scope") or "").strip():
                    node_scope[cfg.node_id] = (params["scope"], "已带域")
                    how["已带域"] += 1
                    continue
                steps = node_steps(params)
                scopes = {el_scope[int(el["element_id"])]
                          for st in steps
                          if isinstance(el := st.get("element"), dict)
                          and isinstance(el.get("element_id"), int)
                          and int(el["element_id"]) in el_scope}
                if len(scopes) > 1:
                    multi_nodes.append((cid, cfg.node_id, sorted(scopes)))
                    continue
                if len(scopes) == 1:
                    s = scopes.pop()
                    node_scope[cfg.node_id] = (s, "元素引用")
                    how["元素引用"] += 1
                    continue
                hit = None
                for st in steps:
                    if st.get("action") != "goto":
                        continue
                    url = str(st.get("url") or "")
                    hit = url_scope(url, all_scopes)
                    if not hit:
                        m = VAR_RE.match(url.strip())
                        if m:
                            val = dataset_var_value(db, case.dataset_id, m.group(1))
                            if val:
                                hit = url_scope(val, all_scopes)
                    if hit:
                        node_scope[cfg.node_id] = (hit, "goto URL")
                        how["goto URL"] += 1
                        break
            # 前驱继承（拓扑序）；仍空再后继继承
            for nid in order:
                if nid in node_scope:
                    continue
                prev = next((node_scope[p][0] for p in reversed(order[:order.index(nid)])
                             if p in node_scope), None)
                if prev:
                    node_scope[nid] = (prev, "前驱继承")
                    how["前驱继承"] += 1
            for nid in order:
                if nid in node_scope:
                    continue
                nxt = next((node_scope[n][0] for n in order[order.index(nid) + 1:]
                            if n in node_scope), None)
                if nxt:
                    node_scope[nid] = (nxt, "后继继承")
                    how["后继继承"] += 1

            for cfg in by_case[cid]:
                if cfg.node_id not in node_scope:
                    unassigned.append((cid, case.name, cfg.node_id))
                    how["未定域"] += 1
                    continue
                scope, reason = node_scope[cfg.node_id]
                params = json.loads(json.dumps(cfg.ui_params))  # 工作副本
                params["scope"] = scope
                planned_cfg.append((cfg, params, scope, reason))
                nd = dag_nodes.get(cfg.node_id)
                if nd is None:
                    missing_in_dag.append((cid, cfg.node_id))
                    continue
                data = dict(nd.get("data") or {})
                if data.get("label") and not data.get("desc"):
                    data["desc"] = data["label"]  # 原语义名留档
                data.update({"label": labels.get(scope, scope), "scope": scope,
                             "ui_action": "steps",
                             "ui_steps_len": len(node_steps(cfg.ui_params or {}))})
                nd["data"] = data
                report.append((cid, case.name, cfg.node_id, scope, labels.get(scope, scope), reason))

            if any(cfg.node_id in node_scope for cfg in by_case[cid]):
                planned_dag.append((case, json.loads(json.dumps(dag))))

        print("推导方式分布:", dict(how))
        print(f"\n{'已回填' if args.apply else '将回填（dry-run）'} "
              f"{len(planned_cfg)} 个节点配置 / {len(planned_dag)} 个用例 dag：")
        for cid, cname, nid, scope, label, reason in report:
            print(f"  case#{cid}「{cname}」{nid}: {label}（{scope}）← {reason}")
        if multi_nodes:
            print(f"\n[跳过] 多域节点 {len(multi_nodes)} 个（不自动拆分，需人工处理）：")
            for cid, nid, scopes in multi_nodes:
                print(f"  case#{cid} {nid}: {scopes}")
        if unassigned:
            print(f"\n[未定域] {len(unassigned)} 个节点（不写 scope，UI 上人工指派）：")
            for cid, cname, nid in unassigned:
                print(f"  case#{cid}「{cname}」{nid}")
        if missing_in_dag:
            print("\n[warn] 配置存在但 dag 无此节点（ui_params 已写，画布数据未动）：")
            for cid, nid in missing_in_dag:
                print(f"  case#{cid} {nid}")

        if args.apply:
            from sqlalchemy.orm.attributes import flag_modified
            for cfg, params, _s, _r in planned_cfg:
                cfg.ui_params = params
                flag_modified(cfg, "ui_params")
            for case, dag in planned_dag:
                case.dag_config = dag
                flag_modified(case, "dag_config")
            db.commit()
            print("\n已提交。")
        else:
            print("\ndry-run 结束（未写库）。确认后加 --apply 执行。")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
