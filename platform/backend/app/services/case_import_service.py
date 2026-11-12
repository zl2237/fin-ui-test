"""用例导入服务：消费导出 v2 迁移包（export_service.export_cases_json），无损重建用例。

匹配策略（尽量复用目标项目已有资产，缺什么补什么）：
- 接口：项目内 (method, path) 匹配 → 复用；未命中用节点 api_snapshot 重建（code 自动生成避撞）
- UI 元素：项目内 (page_scope, element_key) 匹配 → 复用；未命中用快照重建；ui_params 内
  element_id/custom_id（含动作组 steps 任意嵌套层级）按「源 id → 目标 id」重映射
- 页面域标签 / 自定义动作：page_scope / name 匹配，未命中重建
- 环境：不导出（含密钥）；导入时统一 env_id 覆盖绑定（不传则不绑定，执行前需手动配置）
- 数据集：全量重建（行含 label/field_desc/field_order 元数据），按导出时绑定名回绑 dataset_id

v1 导出文件（无 version 字段）缺 UI 节点参数/数据集元数据/资产快照，明确拒绝并提示重新导出。
dry_run=True 只做匹配统计（只读不落库），前端先预览再确认导入。
整批单事务：任一用例失败全部回滚，不留半批脏数据。
"""
import copy
import re

from sqlalchemy.orm import Session

from .. import models


class ImportPayloadError(ValueError):
    """载荷不合法（非本平台导出 / v1 旧版 / 结构残缺）——路由转 400。"""


def _validate_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise ImportPayloadError("导入内容需为 JSON 对象（平台导出的用例 JSON 文件）")
    if payload.get("type") != "cases":
        raise ImportPayloadError("仅支持「用例导出 JSON」文件（type=cases），当前文件不是用例导出件")
    version = payload.get("version")
    if version != 2:
        if version is None:
            raise ImportPayloadError(
                "这是旧版（v1）导出文件：缺少 UI 节点参数、数据集元数据与元素/接口快照，"
                "无法无损导入。请在源平台升级后重新导出，再导入此文件")
        raise ImportPayloadError(f"不支持的导出版本 v{version}（当前支持 v2）")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ImportPayloadError("导出文件中没有用例（items 为空）")
    return payload


def _remap_ui_refs(obj, elem_map: dict[int, int], action_map: dict[int, int]):
    """递归重映射 ui_params 中的 element_id / custom_id（源 id → 目标 id）。

    与导出端 _collect_ui_refs 对称：键可出现在任意嵌套层级（含动作组 steps）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("element_id", "custom_id") and v is not None:
                try:
                    src = int(v)
                except (TypeError, ValueError):
                    continue
                target = (elem_map if k == "element_id" else action_map).get(src)
                if target is not None:
                    obj[k] = target
            else:
                _remap_ui_refs(v, elem_map, action_map)
    elif isinstance(obj, list):
        for v in obj:
            _remap_ui_refs(v, elem_map, action_map)


def _gen_api_code(db: Session, method: str, path: str) -> str:
    """为快照重建的接口生成全局唯一 code：imported_{method}_{path slug}，撞码加序号。"""
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", path or "api").strip("_")[:60] or "api"
    base = f"imported_{method.lower()}_{slug}"[:100]
    code, n = base, 1
    while db.query(models.ApiDefinition).filter(models.ApiDefinition.code == code).first():
        n += 1
        code = f"{base}_{n}"
    return code


def _plan_assets(db: Session, payload: dict, project_id: int) -> dict:
    """资产匹配预演（只读）：对快照逐个决定 复用/新建，并给出源 id 映射。

    返回 {
      elements: [(src_id, snapshot, target_id_or_None)],   # target_id 非空=复用
      actions:   同上,
      scope_labels: [snapshot, ...],                        # 目标项目缺的页面域标签
      apis: {(method, path): (snapshot_or_None, target_id_or_None)},
      warnings: [str, ...],
    }
    """
    warnings: list[str] = []
    # 目标项目资产索引
    api_by_mp = {(a.method.upper(), a.path): a.id
                 for a in db.query(models.ApiDefinition)
                 .filter(models.ApiDefinition.project_id == project_id).all()}
    elem_by_key = {(e.page_scope, e.element_key): e.id
                   for e in db.query(models.UiElement)
                   .filter(models.UiElement.project_id == project_id).all()}
    action_by_name = {a.name: a.id
                      for a in db.query(models.CustomAction)
                      .filter(models.CustomAction.project_id == project_id).all()}
    label_scopes = {lb.page_scope for lb in db.query(models.PageScopeLabel)
                    .filter(models.PageScopeLabel.project_id == project_id).all()}

    # 元素/动作快照（导出带源 id；同批去重靠源 id 天然唯一）
    elements = []
    for snap in payload.get("elements") or []:
        key = (snap.get("page_scope"), snap.get("element_key"))
        if not all(key):
            warnings.append(f"元素快照残缺（page_scope/element_key 缺失），已跳过：{snap.get('element_key') or snap.get('id')}")
            continue
        elements.append((snap.get("id"), snap, elem_by_key.get(key)))
    actions = []
    for snap in payload.get("custom_actions") or []:
        if not snap.get("name"):
            warnings.append(f"自定义动作快照残缺（name 缺失），已跳过：{snap.get('id')}")
            continue
        actions.append((snap.get("id"), snap, action_by_name.get(snap["name"])))

    # 页面域标签：目标项目缺的才建
    scope_labels = [s for s in (payload.get("page_scope_labels") or [])
                    if s.get("page_scope") and s.get("label")
                    and s["page_scope"] not in label_scopes]

    # 接口快照：遍历用例节点的 api_snapshot
    apis: dict = {}
    for item in payload["items"]:
        for n in item.get("nodes") or []:
            snap = n.get("api_snapshot")
            src_api_id = n.get("api_id")
            if not snap:
                if src_api_id:
                    warnings.append(
                        f"用例「{item.get('name')}」节点 {n.get('id')} 引用的接口（源 id={src_api_id}）"
                        "在导出文件中无快照，导入后该节点不绑定接口")
                continue
            mp = ((snap.get("method") or "POST").upper(), snap.get("path"))
            if not mp[1]:
                warnings.append(f"接口快照残缺（path 缺失），已跳过：{snap.get('name')}")
                continue
            if mp not in apis:
                apis[mp] = (snap, api_by_mp.get(mp))
    return {"elements": elements, "actions": actions, "scope_labels": scope_labels,
            "apis": apis, "warnings": warnings}


def _preview(plan: dict, payload: dict, project_id: int, db: Session) -> dict:
    """dry_run 预览：复用/新建分类统计 + 逐用例概要 + 同名警告。"""
    existing_names = {c.name for c in db.query(models.TestCase.name)
                      .filter(models.TestCase.project_id == project_id).all()}
    warnings = list(plan["warnings"])
    case_rows = []
    for item in payload["items"]:
        name = item.get("name") or "（无名）"
        if name in existing_names:
            warnings.append(f"目标项目已存在同名用例「{name}」，导入会创建同名副本")
        nodes = item.get("nodes") or []
        case_rows.append({
            "name": name,
            "nodes": len(nodes),
            "ui_nodes": sum(1 for n in nodes if (n.get("step_type") or "api") == "ui"),
            "datasets": len(item.get("datasets") or []),
            "rows": sum(len(d.get("rows") or []) for d in (item.get("datasets") or [])),
        })
    reuse_apis = [f"{m} {p}" for (m, p), (s, tid) in plan["apis"].items() if tid]
    create_apis = [f"{m} {p}" for (m, p), (s, tid) in plan["apis"].items() if not tid]
    reuse_elems = [f"{s.get('page_scope')}/{s.get('element_key')}"
                   for _, s, tid in plan["elements"] if tid]
    create_elems = [f"{s.get('page_scope')}/{s.get('element_key')}"
                    for _, s, tid in plan["elements"] if not tid]
    reuse_actions = [s["name"] for _, s, tid in plan["actions"] if tid]
    create_actions = [s["name"] for _, s, tid in plan["actions"] if not tid]
    return {
        "dry_run": True,
        "case_count": len(case_rows),
        "cases": case_rows,
        "reuse_apis": reuse_apis, "create_apis": create_apis,
        "reuse_elements": reuse_elems, "create_elements": create_elems,
        "reuse_actions": reuse_actions, "create_actions": create_actions,
        "create_scope_labels": [s["label"] for s in plan["scope_labels"]],
        "warnings": warnings,
    }


def import_cases(db: Session, payload: dict, project_id: int, user_id: int | None = None, *,
                 group_id: int | None = None, env_id: int | None = None,
                 dry_run: bool = False) -> dict:
    """导入导出 v2 用例迁移包。dry_run=True 只统计不落库；否则整批单事务重建。

    group_id：导入用例统一分组（None=未分组）；env_id：统一环境绑定（None=不绑定）。
    """
    _validate_payload(payload)
    if not db.query(models.Project).get(project_id):
        raise ImportPayloadError(f"目标项目不存在: {project_id}")
    if group_id is not None and not db.query(models.CaseGroup).get(group_id):
        raise ImportPayloadError(f"目标分组不存在: {group_id}")
    if env_id is not None and not db.query(models.Environment).get(env_id):
        raise ImportPayloadError(f"指定环境不存在: {env_id}")

    plan = _plan_assets(db, payload, project_id)
    if dry_run:
        return _preview(plan, payload, project_id, db)

    warnings = list(plan["warnings"])

    # ---- 资产先行：页面域标签 → 元素 → 自定义动作 → 接口（后三者依赖前序无，顺序只为可读） ----
    for s in plan["scope_labels"]:
        db.add(models.PageScopeLabel(
            project_id=project_id, page_scope=s["page_scope"], label=s["label"],
            created_by=user_id, updated_by=user_id))
    elem_map: dict[int, int] = {}
    created_elements = 0
    for src_id, snap, target_id in plan["elements"]:
        if target_id:
            elem_map[src_id] = target_id
            continue
        elem_obj = models.UiElement(
            project_id=project_id, page_scope=snap["page_scope"],
            element_key=snap["element_key"], strategies=snap.get("strategies") or {},
            description=snap.get("description"), created_by=user_id, updated_by=user_id)
        db.add(elem_obj)
        db.flush()
        elem_map[src_id] = elem_obj.id
        created_elements += 1
    action_map: dict[int, int] = {}
    created_actions = 0
    for src_id, snap, target_id in plan["actions"]:
        if target_id:
            action_map[src_id] = target_id
            continue
        act_obj = models.CustomAction(
            project_id=project_id, name=snap["name"], script=snap.get("script") or "",
            description=snap.get("description"), created_by=user_id, updated_by=user_id)
        db.add(act_obj)
        db.flush()
        action_map[src_id] = act_obj.id
        created_actions += 1
    api_id_by_mp: dict = {}
    created_apis = 0
    for (method, path), (snap, target_id) in plan["apis"].items():
        if target_id:
            api_id_by_mp[(method, path)] = target_id
            continue
        api_obj = models.ApiDefinition(
            project_id=project_id, name=snap.get("name") or path,
            code=_gen_api_code(db, method, path),
            method=method, path=path, description=snap.get("description"),
            request_template={}, headers_template={},
            created_by=user_id, updated_by=user_id)
        db.add(api_obj)
        db.flush()
        for f in snap.get("fields") or []:
            db.add(models.ApiField(
                api_id=api_obj.id, key=f["key"], label=f.get("label"),
                field_type=f.get("field_type", "string"), required=f.get("required", False),
                default_value=f.get("default_value"), remark=f.get("remark"),
                sort_order=f.get("sort_order", 0)))
        api_id_by_mp[(method, path)] = api_obj.id
        created_apis += 1

    # ---- 用例主体：TestCase + node_configs + datasets（单事务，最后统一 commit） ----
    case_ids: list[int] = []
    created_rows = 0
    for item in payload["items"]:
        case = models.TestCase(
            project_id=project_id, group_id=group_id,
            name=item.get("name") or "导入用例",
            description=item.get("description"),
            dag_config={"nodes": item.get("nodes") or [], "edges": item.get("edges") or []},
            env_id=env_id, created_by=user_id, updated_by=user_id)
        db.add(case)
        db.flush()
        case_ids.append(case.id)

        for n in item.get("nodes") or []:
            cfg = n.get("config")
            if not cfg:
                continue  # 源库该节点无配置行，保持一致
            snap = n.get("api_snapshot")
            api_id = None
            if snap and snap.get("path"):
                api_id = api_id_by_mp.get(((snap.get("method") or "POST").upper(), snap["path"]))
            ui_params = copy.deepcopy(n.get("ui_params") or {})
            if ui_params:
                _remap_ui_refs(ui_params, elem_map, action_map)
            db.add(models.CaseNodeConfig(
                case_id=case.id, node_id=n.get("id") or "", api_id=api_id,
                step_type=n.get("step_type") or "api",
                ui_params=ui_params,
                pre_process=cfg.get("pre_process") or [],
                post_extract=cfg.get("post_extract") or [],
                assertions=cfg.get("assertions") or [],
                wait_after_ms=cfg.get("wait_after_ms") or 0))

        dataset_ids: dict[str, int] = {}
        first_ds: int | None = None
        for d in item.get("datasets") or []:
            ds = models.DataSet(
                project_id=project_id, case_id=case.id, name=d.get("name") or "导入数据集",
                description=d.get("description"), created_by=user_id, updated_by=user_id)
            db.add(ds)
            db.flush()
            dataset_ids[ds.name] = ds.id
            if first_ds is None:
                first_ds = ds.id
            for r in d.get("rows") or []:
                db.add(models.DataSetRow(
                    dataset_id=ds.id, row_index=r.get("row_index") or 0,
                    data=r.get("data") or {}, label=r.get("label"),
                    field_desc=r.get("field_desc"), field_order=r.get("field_order")))
                created_rows += 1
        # 数据集绑定回放：导出时绑定的数据集名优先，缺失则绑第一个
        bound = dataset_ids.get(item.get("dataset_name") or "") or first_ds
        if bound:
            case.dataset_id = bound

    db.commit()
    return {
        "dry_run": False,
        "case_count": len(case_ids),
        "case_ids": case_ids,
        "created": {
            "cases": len(case_ids), "apis": created_apis, "elements": created_elements,
            "custom_actions": created_actions, "page_scope_labels": len(plan["scope_labels"]),
            "datasets": sum(len(i.get("datasets") or []) for i in payload["items"]),
            "rows": created_rows,
        },
        "reused": {
            "apis": sum(1 for _, (_, tid) in plan["apis"].items() if tid),
            "elements": sum(1 for _, _, tid in plan["elements"] if tid),
            "custom_actions": sum(1 for _, _, tid in plan["actions"] if tid),
        },
        "warnings": warnings,
    }
