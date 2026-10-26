"""套件 283 → 单条普通用例（用户 2026-10-23 定案：单系统不需要套件）。

合并方案：
- 7 成员按套件顺序串成一条 DAG：272(g1..g6 原名) + 275(m75_*) + 282(m82_*)
  + 281(m81_*) + 279(m79_*) + 273(m73_*) + 276(m76_*)，段内边保留、段间尾→头串边
- 282 的 ${service_projects_json} 改名 ${import_projects_json}（与 275 撞名不同值）
- 数据集合并为 5 行变体：272 行1 常量 + 275/282/276 第 i 行变体 + 281/279 常量
  （bl_no 全链共用：g1 运行时提取覆盖数据集旧值，272 单跑 #846 已实证）
- 283 原地转 normal（保留自身执行历史），清空套件成员
- 删 7 成员 + 280（280 需草稿态业务订单，链路永不存在，用户拍板删除）
"""
import copy
import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR.parent.parent))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

SEGMENTS = [272, 275, 282, 281, 279, 273, 276]  # 套件定稿顺序
PREFIX = {272: None, 275: "m75", 282: "m82", 281: "m81", 279: "m79", 273: "m73", 276: "m76"}
REF = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def main() -> int:
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()

    # ---- 预检 ----
    suite = db.query(models.TestCase).filter(models.TestCase.id == 283).first()
    assert suite and suite.case_type == "suite", "283 不是套件"
    members = (db.query(models.SuiteMember)
               .filter(models.SuiteMember.suite_case_id == 283)
               .order_by(models.SuiteMember.sort_order).all())
    assert [m.member_case_id for m in members] == SEGMENTS, \
        f"套件成员与定稿不符: {[m.member_case_id for m in members]}"
    # 结构化 node_id 字段不应存在；{{node.var}} 引用（如 281 n5 SQL 的 {{n1.bl_no}}）
    # 段内改写为新节点 id
    for cid in SEGMENTS:
        for cf in db.query(models.CaseNodeConfig).filter(models.CaseNodeConfig.case_id == cid).all():
            blob = json.dumps(cf.ui_params or {}) + json.dumps(cf.post_extract or [])
            assert '"node_id"' not in blob, f"case {cid} {cf.node_id} 存在结构化节点引用，需人工改写"
    print("预检通过：成员集合、无结构化 node_id 字段（{{node.var}} 引用走段内改写）")

    # ---- 1. 合并 DAG ----
    nodes, edges = [], []
    node_map = {}      # (cid, old_id) -> new_id
    tail = None        # 上一段尾节点
    for k, cid in enumerate(SEGMENTS):
        c = db.query(models.TestCase).filter(models.TestCase.id == cid).first()
        dag = c.dag_config or {}
        seg_nodes = copy.deepcopy(dag.get("nodes") or [])
        seg_edges = copy.deepcopy(dag.get("edges") or [])
        assert seg_nodes, f"case {cid} 无 DAG 节点"
        pre = PREFIX[cid]
        min_x = min(n["position"]["x"] for n in seg_nodes)
        min_y = min(n["position"]["y"] for n in seg_nodes)
        for n in seg_nodes:
            old = n["id"]
            new = f"{pre}_{old}" if pre else old
            assert new not in node_map.values(), f"节点 id 冲突: {new}"
            node_map[(cid, old)] = new
            n["id"] = new
            # 分段纵向排布：272 占 y60..300，成员段自 y=460 起每段一横带
            n["position"] = {"x": n["position"]["x"] - min_x + 80,
                             "y": n["position"]["y"] - min_y + (460 + 170 * (k - 1) if k else 0)}
            nodes.append(n)
        for e in seg_edges:
            e = dict(e)
            e["id"] = f"s{k}_{e['id']}"
            e["source"] = node_map[(cid, e["source"])]
            e["target"] = node_map[(cid, e["target"])]
            edges.append(e)
        # 段内顺序：入度0为头、出度0为尾（用映射后的新 id 集合算，
        # 边表在 append 时已复制改写，这里从 edges 取本段新边）
        seg_new = [e for e in edges if e["id"].startswith(f"s{k}_")]
        srcs = {e["source"] for e in seg_new} if seg_new else set()
        tgts = {e["target"] for e in seg_new} if seg_new else set()
        ids = [node_map[(cid, n["id"])] for n in dag.get("nodes") or []]
        head = next(i for i in ids if i not in tgts)
        seg_tail = next(i for i in ids if i not in srcs)
        if tail:
            edges.append({"id": f"chain_{k}", "source": tail, "target": head})
        tail = seg_tail
    print(f"1. 合并 DAG：{len(nodes)} 节点 / {len(edges)} 边（含段间串边 6 条）")

    # ---- 2. 合并节点配置（282 段换引用名；{{node.var}} 段内改写新 id）----
    cfgs = []
    for cid in SEGMENTS:
        pre = PREFIX[cid]
        for cf in (db.query(models.CaseNodeConfig)
                   .filter(models.CaseNodeConfig.case_id == cid)
                   .order_by(models.CaseNodeConfig.node_id).all()):
            ui = copy.deepcopy(cf.ui_params or {})
            post = copy.deepcopy(cf.post_extract or [])
            if pre or cid == 282:
                ui_blob = json.dumps(ui, ensure_ascii=False)
                post_blob = json.dumps(post, ensure_ascii=False)
                if cid == 282:
                    assert set(REF.findall(ui_blob)) <= {"bl_no", "service_projects_json"}, \
                        f"282 引用超出预期: {REF.findall(ui_blob)}"
                    ui_blob = ui_blob.replace("${service_projects_json}", "${import_projects_json}")
                    post_blob = post_blob.replace("${service_projects_json}", "${import_projects_json}")
                if pre:  # {{旧id. → {{新id.（锚定双花括号，避免子串误伤）
                    for old, new in node_map.items():
                        if old[0] == cid:
                            ui_blob = ui_blob.replace("{{" + old[1] + ".", "{{" + new + ".")
                            post_blob = post_blob.replace("{{" + old[1] + ".", "{{" + new + ".")
                ui, post = json.loads(ui_blob), json.loads(post_blob)
            cfgs.append(models.CaseNodeConfig(
                case_id=283, node_id=node_map[(cid, cf.node_id)],
                api_id=cf.api_id, step_type=cf.step_type or "ui",
                ui_params=ui, pre_process=cf.pre_process or [],
                post_extract=post,
                assertions=cf.assertions or [], wait_after_ms=cf.wait_after_ms or 0))
    assert len(cfgs) == len(nodes), f"节点配置 {len(cfgs)} != DAG 节点 {len(nodes)}"
    print(f"2. 合并节点配置 {len(cfgs)} 条（282 段引用已改 import_projects_json）")

    # ---- 3. 合并数据集（5 行变体）----
    rows_src = {}
    for cid in SEGMENTS:
        c = db.query(models.TestCase).filter(models.TestCase.id == cid).first()
        rows_src[cid] = (db.query(models.DataSetRow)
                         .filter(models.DataSetRow.dataset_id == c.dataset_id)
                         .order_by(models.DataSetRow.row_index).all())
    n_var = min(len(rows_src[cid]) for cid in (275, 282, 276))
    assert n_var == 5, f"变体行数异常: {n_var}"
    merged_rows = []
    for i in range(n_var):
        d = dict(rows_src[272][0].data or {})           # 272 常量（bl_no 运行时被 g1 提取覆盖）
        d["service_projects_json"] = (rows_src[275][i].data or {}).get("service_projects_json", "")
        d["import_projects_json"] = (rows_src[282][i].data or {}).get("service_projects_json", "")
        r281 = rows_src[281][0].data or {}
        d["audit_nodes_json"] = r281.get("audit_nodes_json", "")
        r279 = rows_src[279][0].data or {}
        for k2 in ("approval_route", "approval_type", "audit_result_json", "audit_user1"):
            d[k2] = r279.get(k2, "")
        r276 = rows_src[276][i].data or {}
        d["order_self_route"] = r276.get("order_self_route", "")
        d["self_projects_json"] = r276.get("self_projects_json", "")
        merged_rows.append(d)
    ds = models.DataSet(project_id=1, case_id=283, name="全链路数据·合并变体",
                        created_by=1, updated_by=1)
    db.add(ds)
    db.flush()
    for i, data in enumerate(merged_rows, start=1):
        db.add(models.DataSetRow(dataset_id=ds.id, row_index=i, data=data))
    print(f"3. 合并数据集 {ds.id}：{len(merged_rows)} 行变体")

    # ---- 4. 283 转普通用例 ----
    db.query(models.SuiteMember).filter(models.SuiteMember.suite_case_id == 283).delete()
    db.query(models.CaseNodeConfig).filter(models.CaseNodeConfig.case_id == 283).delete()
    suite.case_type = "normal"
    suite.name = "委托订单全链路（272产单→费用→推送→审批→通知单→编辑自营）"
    suite.dag_config = {"nodes": nodes, "edges": edges}
    suite.dataset_id = ds.id
    suite.shared_vars = None
    db.add_all(cfgs)
    db.commit()
    print(f"4. 283 已转普通用例：{len(nodes)} 节点，绑定数据集 {ds.id}")

    # ---- 5. 删成员 + 280 ----
    from app.crud.legacy import delete_testcase
    for cid in SEGMENTS + [280]:
        db.query(models.TestSchedule).filter(models.TestSchedule.case_id == cid).delete()
        obj = db.query(models.TestCase).filter(models.TestCase.id == cid).first()
        assert obj, f"case {cid} 不存在"
        delete_testcase(db, obj)
        print(f"   已删除 case {cid} {obj.name[:20]}")
    db.commit()

    # ---- 6. 回读校验 ----
    db.expire_all()
    c = db.query(models.TestCase).filter(models.TestCase.id == 283).first()
    dag = c.dag_config or {}
    assert c.case_type == "normal" and len(dag["nodes"]) == len(nodes)
    assert not db.query(models.SuiteMember).filter(models.SuiteMember.suite_case_id == 283).count()
    for cid in SEGMENTS + [280]:
        assert not db.query(models.TestCase).filter(models.TestCase.id == cid).first()
        assert not db.query(models.ExecutionRecord).filter(models.ExecutionRecord.case_id == cid).count()
    blob = "".join(json.dumps(cf.ui_params or {}, ensure_ascii=False) + json.dumps(cf.post_extract or [], ensure_ascii=False)
                   for cf in db.query(models.CaseNodeConfig).filter(models.CaseNodeConfig.case_id == 283).all())
    assert "${service_projects_json}" in blob and "${import_projects_json}" in blob
    assert "{{m81_n1.bl_no}}" in blob and "{{n1." not in blob
    print("6. 回读校验通过：283 normal / 成员与 280 已清 / 引用名双轨 + 节点引用改写在位")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
