"""用例导入（导出 v2 迁移包）单测：真 SQLite 内存库走真 ORM 路径。

覆盖：v1/v3 拒绝、dry_run 资产分类统计（只读不落库）、真导入的资产复用与重建
（api 按 method+path、元素按 page_scope+element_key、动作按名）、ui_params 引用重映射
（含动作组 steps 嵌套）、数据集行全字段回放与绑定、env/group 覆盖、同名警告、
以及金标准——导出→导入→再导出的结构等价（roundtrip）。
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.services import case_import_service as imp
from app.services.export_service import export_cases_json


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _project(db, name="源项目"):
    p = models.Project(name=name)
    db.add(p)
    db.commit()
    return p


def _env(db, name="test"):
    e = models.Environment(name=name, base_url="http://t")
    db.add(e)
    db.commit()
    return e


def _api(db, project_id, name="创建订单", method="POST", path="/api/order/add", fields=None):
    a = models.ApiDefinition(
        project_id=project_id, name=name, code=f"p{project_id}_{path}_{method}".replace("/", "_"),
        method=method, path=path, request_template={}, headers_template={})
    db.add(a)
    db.commit()
    for f in (fields or []):
        db.add(models.ApiField(api_id=a.id, key=f["key"], label=f.get("label"),
                               field_type=f.get("field_type", "string"),
                               required=f.get("required", False),
                               default_value=f.get("default_value"),
                               sort_order=f.get("sort_order", 0)))
    db.commit()
    db.refresh(a)
    return a


def _element(db, project_id, scope="order/add", key="bl_no_input", strategies=None):
    e = models.UiElement(project_id=project_id, page_scope=scope, element_key=key,
                         strategies=strategies or {"full_xpath": "//input[@id='bl']"},
                         description="提单号输入框")
    db.add(e)
    db.commit()
    return e


def _action(db, project_id, name="toast_watch2", script="return 1"):
    a = models.CustomAction(project_id=project_id, name=name, script=script,
                            description="自定义动作")
    db.add(a)
    db.commit()
    return a


def _full_case(db, project_id, env, api, element, action, group_id=None):
    """混合用例：api 节点 + ui 节点（动作组 steps 内嵌元素/动作引用）+ 数据集两行。"""
    case = models.TestCase(
        project_id=project_id, group_id=group_id, name="下单冒烟",
        description="导入源用例", env_id=env.id,
        dag_config={
            "nodes": [
                {"id": "n1", "position": {"x": 1, "y": 2}, "data": {"label": "创建"}},
                {"id": "n2", "position": {"x": 3, "y": 4}, "data": {"label": "页面操作"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        })
    db.add(case)
    db.commit()
    db.add(models.CaseNodeConfig(
        case_id=case.id, node_id="n1", api_id=api.id, step_type="api",
        post_extract=[{"name": "order_id", "source": "body", "jsonpath": "$.data.id"}],
        assertions=[{"type": "response_status_equals", "expected": 200}],
        wait_after_ms=100))
    db.add(models.CaseNodeConfig(
        case_id=case.id, node_id="n2", step_type="ui",
        ui_params={"scope": "order/add", "steps": [
            {"action": "fill", "element": {"element_id": element.id}, "value": "BL001"},
            {"action": "custom", "custom_id": action.id},
        ]}))
    ds = models.DataSet(project_id=project_id, case_id=case.id, name="默认数据集", bound=True)
    db.add(ds)
    db.commit()
    db.add(models.DataSetRow(dataset_id=ds.id, row_index=1,
                             data={"nodes": {"n1": {"order_no": "A1"}}, "bl_no": "BL001"},
                             label="Sheet1", field_desc={"bl_no": "提单号"},
                             field_order=["bl_no", "order_no"]))
    db.add(models.DataSetRow(dataset_id=ds.id, row_index=2,
                             data={"nodes": {"n1": {"order_no": "A2"}}}, label="Sheet2"))
    db.commit()
    db.refresh(case)
    return case


def _export(db, cases, project):
    group_names: dict[int, str] = {}
    case_ids = [c.id for c in cases]
    dss = (db.query(models.DataSet)
           .filter(models.DataSet.case_id.in_(case_ids)).order_by(models.DataSet.id).all())
    datasets_by_case: dict[int, list] = {}
    for d in dss:
        if d.rows:
            datasets_by_case.setdefault(d.case_id, []).append(d)
    return json.loads(export_cases_json(cases, group_names, project.name, datasets_by_case, db=db))


def _normalize_ui(params: dict, elem_map: dict, act_map: dict) -> dict:
    """ui_params 归一化：element_id/custom_id 按 映射换占位，供跨库结构比对。"""
    import copy

    obj = copy.deepcopy(params)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "element_id" and v in elem_map:
                    o[k] = "ELEM"
                elif k == "custom_id" and v in act_map:
                    o[k] = "ACT"
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return obj


# ============ 载荷校验 ============

class TestPayloadValidation:
    def test_reject_v1(self, db):
        with pytest.raises(imp.ImportPayloadError, match="v1"):
            imp.import_cases(db, {"type": "cases", "items": [{"name": "x"}]}, 1)

    def test_reject_wrong_type(self, db):
        with pytest.raises(imp.ImportPayloadError, match="type=cases"):
            imp.import_cases(db, {"type": "apis", "version": 2}, 1)

    def test_reject_v3(self, db):
        with pytest.raises(imp.ImportPayloadError, match="v3"):
            imp.import_cases(db, {"type": "cases", "version": 3, "items": []}, 1)

    def test_reject_empty_items(self, db):
        with pytest.raises(imp.ImportPayloadError, match="items 为空"):
            imp.import_cases(db, {"type": "cases", "version": 2, "items": []}, 1)

    def test_reject_missing_project(self, db):
        _project(db)
        with pytest.raises(imp.ImportPayloadError, match="目标项目不存在"):
            imp.import_cases(db, {"type": "cases", "version": 2, "items": [{"name": "x"}]}, 999)

    def test_reject_bad_group_or_env(self, db):
        p = _project(db)
        payload = {"type": "cases", "version": 2, "items": [{"name": "x", "nodes": []}]}
        with pytest.raises(imp.ImportPayloadError, match="分组不存在"):
            imp.import_cases(db, payload, p.id, group_id=999)
        with pytest.raises(imp.ImportPayloadError, match="环境不存在"):
            imp.import_cases(db, payload, p.id, env_id=999)


# ============ dry_run 预演 ============

class TestDryRun:
    def test_plan_only_no_writes(self, db):
        p1, p2 = _project(db, "源"), _project(db, "目标")
        env = _env(db)
        api = _api(db, p1.id)
        elem = _element(db, p1.id)
        action = _action(db, p1.id)
        case = _full_case(db, p1.id, env, api, elem, action)
        payload = _export(db, [case], p1)
        # 目标项目预置同 method+path 接口 → 应判复用
        _api(db, p2.id, name="同名接口", method="POST", path="/api/order/add")

        result = imp.import_cases(db, payload, p2.id, dry_run=True)
        assert result["dry_run"] is True
        assert result["case_count"] == 1
        assert result["cases"][0] == {"name": "下单冒烟", "nodes": 2, "ui_nodes": 1,
                                      "datasets": 1, "rows": 2}
        assert result["reuse_apis"] == ["POST /api/order/add"] and result["create_apis"] == []
        # 元素/动作目标项目都没有 → 将新建
        assert result["create_elements"] == ["order/add/bl_no_input"]
        assert result["create_actions"] == ["toast_watch2"]
        assert result["reuse_elements"] == [] and result["reuse_actions"] == []
        assert result["create_scope_labels"] == []
        # 只读：目标项目零新增
        assert db.query(models.TestCase).filter(models.TestCase.project_id == p2.id).count() == 0
        assert db.query(models.UiElement).filter(models.UiElement.project_id == p2.id).count() == 0

    def test_same_name_warning(self, db):
        p1, p2 = _project(db, "源"), _project(db, "目标")
        env = _env(db)
        case = _full_case(db, p1.id, env, _api(db, p1.id), _element(db, p1.id), _action(db, p1.id))
        db.add(models.TestCase(project_id=p2.id, name="下单冒烟", dag_config={"nodes": [], "edges": []}))
        db.commit()
        payload = _export(db, [case], p1)
        result = imp.import_cases(db, payload, p2.id, dry_run=True)
        assert any("同名" in w for w in result["warnings"])


# ============ 真导入 ============

class TestImport:
    def _setup_two_projects(self, db):
        p1, p2 = _project(db, "源"), _project(db, "目标")
        env = _env(db)
        api = _api(db, p1.id, fields=[{"key": "order_no", "label": "订单号", "required": True,
                                       "default_value": "A1"}])
        elem = _element(db, p1.id)
        action = _action(db, p1.id)
        case = _full_case(db, p1.id, env, api, elem, action)
        payload = _export(db, [case], p1)
        return p1, p2, env, api, elem, action, case, payload

    def test_full_import_reuse_and_remap(self, db):
        p1, p2, env, api, elem, action, case, payload = self._setup_two_projects(db)
        # 目标项目预置：同 path 接口（复用）+ 同 key 元素（复用）；动作不预置（新建）
        target_api = _api(db, p2.id, name="目标已有", method="POST", path="/api/order/add")
        target_elem = _element(db, p2.id, scope="order/add", key="bl_no_input",
                               strategies={"css": "#bl"})
        env2 = _env(db, "prod")

        result = imp.import_cases(db, payload, p2.id, user_id=7, env_id=env2.id)
        assert result["dry_run"] is False and result["case_count"] == 1
        new_id = result["case_ids"][0]
        assert result["created"]["apis"] == 0 and result["reused"]["apis"] == 1
        assert result["created"]["elements"] == 0 and result["reused"]["elements"] == 1
        assert result["created"]["custom_actions"] == 1 and result["reused"]["custom_actions"] == 0

        new_case = db.query(models.TestCase).get(new_id)
        assert new_case.name == "下单冒烟" and new_case.project_id == p2.id
        assert new_case.env_id == env2.id  # 环境覆盖
        assert len(new_case.dag_config["nodes"]) == 2 and new_case.dag_config["edges"]
        cfgs = {nc.node_id: nc for nc in new_case.node_configs}
        assert cfgs["n1"].api_id == target_api.id  # method+path 复用目标已有接口
        assert cfgs["n1"].post_extract[0]["name"] == "order_id"
        # ui_params 重映射：steps 内元素指向目标项目元素、custom_id 指向新建动作
        new_action = (db.query(models.CustomAction)
                      .filter(models.CustomAction.project_id == p2.id).first())
        assert cfgs["n2"].ui_params["steps"][0]["element"]["element_id"] == target_elem.id
        assert cfgs["n2"].ui_params["steps"][1]["custom_id"] == new_action.id
        assert cfgs["n2"].ui_params["scope"] == "order/add"
        # 数据集：名称/行数/行元数据/绑定回放
        dss = db.query(models.DataSet).filter(models.DataSet.case_id == new_id).all()
        assert len(dss) == 1 and dss[0].name == "默认数据集"
        rows = db.query(models.DataSetRow).filter(
            models.DataSetRow.dataset_id == dss[0].id).order_by(models.DataSetRow.row_index).all()
        assert len(rows) == 2
        assert rows[0].label == "Sheet1" and rows[0].field_desc == {"bl_no": "提单号"}
        assert rows[0].field_order == ["bl_no", "order_no"] and rows[1].label == "Sheet2"
        assert dss[0].bound is True  # 绑定回放：bound 标志随导入重建

    def test_api_snapshot_rebuild_with_fields_and_code(self, db):
        """目标项目无同 path 接口：用快照重建（字段全量、code 自动生成）"""
        p1, p2, *_ , payload = self._setup_two_projects(db)
        result = imp.import_cases(db, payload, p2.id)
        assert result["created"]["apis"] == 1
        new_api = (db.query(models.ApiDefinition)
                   .filter(models.ApiDefinition.project_id == p2.id).first())
        assert new_api.method == "POST" and new_api.path == "/api/order/add"
        assert new_api.code.startswith("imported_post_api_order_add")
        fields = new_api.fields
        assert len(fields) == 1 and fields[0].key == "order_no" and fields[0].required is True

    def test_roundtrip_structure_equal(self, db):
        """金标准：导出 → 导入到新项目 → 再导出，两次结构等价（资产引用按目标库重编号后一致）"""
        p1, p2, env, api, elem, action, case, payload = self._setup_two_projects(db)
        imp.import_cases(db, payload, p2.id, env_id=env.id)
        new_case = db.query(models.TestCase).filter(
            models.TestCase.project_id == p2.id).first()
        payload2 = _export(db, [new_case], p2)

        a, b = payload["items"][0], payload2["items"][0]
        assert b["name"] == a["name"] and b["description"] == a["description"]
        assert b["env"] == a["env"] and b["bound_dataset_names"] == a["bound_dataset_names"]
        assert b["edges"] == a["edges"]
        assert [n["id"] for n in b["nodes"]] == [n["id"] for n in a["nodes"]]
        # api_snapshot（快照重建路径下由目标库再生成）与源一致
        assert b["nodes"][0]["api_snapshot"]["fields"] == a["nodes"][0]["api_snapshot"]["fields"]
        assert b["nodes"][0]["config"] == a["nodes"][0]["config"]
        # ui_params 结构一致（引用 id 归一化后比对）
        t_elem = db.query(models.UiElement).filter(
            models.UiElement.project_id == p2.id).first()
        t_act = db.query(models.CustomAction).filter(
            models.CustomAction.project_id == p2.id).first()
        ui_a = _normalize_ui(a["nodes"][1]["ui_params"], {elem.id: 1}, {action.id: 1})
        ui_b = _normalize_ui(b["nodes"][1]["ui_params"], {t_elem.id: 1}, {t_act.id: 1})
        assert ui_b == ui_a
        # 数据集行全字段等价
        assert b["datasets"][0]["rows"] == a["datasets"][0]["rows"]
        # 元素/动作快照语义等价（id 不同，业务键与内容一致；strategies 不可哈希，序列化比对）
        def _elem_sig(e):
            return (e["page_scope"], e["element_key"], json.dumps(e["strategies"], sort_keys=True))
        assert {_elem_sig(e) for e in payload2["elements"]} == {
            _elem_sig(e) for e in payload["elements"]}
        assert {c["name"]: c["script"] for c in payload2["custom_actions"]} == {
            c["name"]: c["script"] for c in payload["custom_actions"]}

    def test_import_twice_element_not_duplicated(self, db):
        """同一文件导入两次：资产按业务键幂等复用，不重复创建"""
        p1, p2, *_ , payload = self._setup_two_projects(db)
        imp.import_cases(db, payload, p2.id)
        result = imp.import_cases(db, payload, p2.id)
        assert result["created"]["elements"] == 0 and result["created"]["custom_actions"] == 0
        assert db.query(models.UiElement).filter(models.UiElement.project_id == p2.id).count() == 1
        assert db.query(models.CustomAction).filter(models.CustomAction.project_id == p2.id).count() == 1
        assert db.query(models.TestCase).filter(models.TestCase.project_id == p2.id).count() == 2

    def test_group_override(self, db):
        p1, p2, *_ , payload = self._setup_two_projects(db)
        g = models.CaseGroup(project_id=p2.id, name="冒烟组")
        db.add(g)
        db.commit()
        result = imp.import_cases(db, payload, p2.id, group_id=g.id)
        new_case = db.query(models.TestCase).get(result["case_ids"][0])
        assert new_case.group_id == g.id

    def test_node_without_config_skipped(self, db):
        """导出端无配置节点（config=None）：导入端不建 CaseNodeConfig 行，不报错"""
        p1, p2 = _project(db, "源"), _project(db, "目标")
        case = models.TestCase(project_id=p1.id, name="裸节点",
                               dag_config={"nodes": [{"id": "n1"}], "edges": []})
        db.add(case)
        db.commit()
        payload = _export(db, [case], p1)
        result = imp.import_cases(db, payload, p2.id)
        new_case = db.query(models.TestCase).get(result["case_ids"][0])
        assert new_case.node_configs == []

    def test_missing_api_snapshot_warns(self, db):
        """api_id 有值但快照缺失（源接口已删后导出）：节点不绑接口 + 警告"""
        p2 = _project(db, "目标")
        payload = {"type": "cases", "version": 2, "items": [{
            "name": "悬空", "nodes": [{"id": "n1", "api_id": 99, "step_type": "api",
                                       "ui_params": None, "api_snapshot": None,
                                       "config": {"post_extract": [], "assertions": [],
                                                  "wait_after_ms": 0, "pre_process": []}}],
            "edges": [], "datasets": []}]}
        result = imp.import_cases(db, payload, p2.id)
        assert any("无快照" in w for w in result["warnings"])
        nc = db.query(models.CaseNodeConfig).filter(
            models.CaseNodeConfig.case_id == result["case_ids"][0]).first()
        assert nc.api_id is None

    def test_scope_label_created_when_missing(self, db):
        """导出含页面域标签且目标项目缺失：导入补建"""
        p2 = _project(db, "目标")
        payload = {"type": "cases", "version": 2, "items": [{
            "name": "x", "nodes": [], "edges": [], "datasets": []}],
            "elements": [{"id": 5, "page_scope": "order/add", "element_key": "k",
                          "strategies": {}, "description": None}],
            "custom_actions": [],
            "page_scope_labels": [{"page_scope": "order/add", "label": "新建订单"}]}
        result = imp.import_cases(db, payload, p2.id)
        assert result["created"]["page_scope_labels"] == 1
        lb = db.query(models.PageScopeLabel).filter(
            models.PageScopeLabel.project_id == p2.id).first()
        assert lb.page_scope == "order/add" and lb.label == "新建订单"


# ============ 导出 v2：引用收集 ============

class TestCollectUiRefs:
    def test_nested_steps(self):
        elem_ids, action_ids = set(), set()
        imp_params = {"steps": [
            {"action": "fill", "element": {"element_id": 3}},
            {"action": "custom", "custom_id": 8},
            {"action": "click", "element": {"element_id": "5"}},  # 字符串数字也收
        ]}
        from app.services.export_service import _collect_ui_refs
        _collect_ui_refs(imp_params, elem_ids, action_ids)
        assert elem_ids == {3, 5} and action_ids == {8}

    def test_remap_roundtrip(self):
        obj = {"steps": [{"element": {"element_id": 3}}, {"custom_id": 8}]}
        imp._remap_ui_refs(obj, {3: 30}, {8: 80})
        assert obj["steps"][0]["element"]["element_id"] == 30
        assert obj["steps"][1]["custom_id"] == 80
