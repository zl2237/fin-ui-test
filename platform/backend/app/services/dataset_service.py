"""dataset_service：数据集服务层（入参收敛语义，2026-09-30 定案）。

数据集 = 各节点入参配置的一套完整取值：行数据 {"nodes": {节点ID: {params}}}。
用例编排只负责结构（串联顺序/接口绑定/后置提取/断言），入参唯一入口收敛到数据集：
- 多数据集 = 多场景（复制后改配置，执行时换绑即换全套入参）
- 执行强绑定：未绑定数据集的用例拒绝执行（2026-09-30 用户定案）

职责：
- 数据集 CRUD（归属用例隔离，复制复用；行 = Excel sheet：label/field_desc/field_order
  展示元数据 + data 平铺运行时源，2026-10-27 sheet 化定案）
- 单节点入参配置保存 / 悬空节点配置清理（行内 nodes 读写）
- 执行展开计划（选中行 → 节点入参配置注入 + 全 sheet 清单供 ${sheet.字段} 引用）
- 跨用例克隆与组合用例合并（行数据纯值操作）

已拆除（历史概念，勿再引入）：
- 变量池 / 列 schema / 参数三态 / 节点手动覆盖（写节点 pre_process）/ 前置动作
  （set_field/iterate_set 等——字段设置语义全部收敛到 params 取值来源声明）
- __dataset__ 平铺键值注入（跨节点共享值改引用上游产出）
"""
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from .. import crud, models


# ============ 行数据访问（首行兜底；多行=多变体，执行面板可选行） ============

def row_data(ds: models.DataSet) -> dict[str, Any]:
    """数据集行数据（无行时空 dict；容忍历史多行取首行）。"""
    rows = ds.rows or []
    return dict(rows[0].data or {}) if rows else {}


def node_configs(row: dict[str, Any]) -> dict[str, dict]:
    """行数据内的节点入参配置集 {"节点ID": {"params": ...}}。"""
    nodes = row.get("nodes")
    return dict(nodes) if isinstance(nodes, dict) else {}


def _ensure_row(db: Session, ds: models.DataSet) -> models.DataSetRow:
    """取/建首行（多行为合法数据：执行面板可选行，见 plan_case_expansion；
    这里只保证「至少一行」供节点配置读写，不再把多行收敛为一行）。"""
    row = (db.query(models.DataSetRow)
           .filter(models.DataSetRow.dataset_id == ds.id)
           .order_by(models.DataSetRow.row_index).first())
    if row:
        return row
    row = models.DataSetRow(dataset_id=ds.id, row_index=1, data={"nodes": {}}, label="Sheet1")
    db.add(row)
    db.flush()
    return row


# ============ sheet 归一与校验（新形态 [{label, data, field_desc?, field_order?}]，兼容旧 [dict]） ============

# ${} 求值硬拦截的前缀（expression.py：context. / db.）+ 数据集保留键：
# sheet 取这些名字会通过不了首点切 ns 的查法或与保留语义冲突，保存即拒
_RESERVED_LABELS = {"nodes", "context", "db"}


def _validate_sheet_label(i: int, label: str) -> None:
    """sheet 名称合法性：非空、≤100、可作 ${label.字段} 命名空间（禁 . $ { }、
    禁 __ 前缀与保留字；中文允许）。i 为 1 起序号，用于定位报错。"""
    if not label or not label.strip():
        raise ValueError(f"第 {i} 个 sheet 名称不能为空")
    label = label.strip()
    if len(label) > 100:
        raise ValueError(f"第 {i} 个 sheet 名称最多 100 字符")
    if any(ch in label for ch in ".${}"):
        raise ValueError(f"第 {i} 个 sheet 名称「{label}」含非法字符（不可用 . $ {{ }}）")
    if label.startswith("__"):
        raise ValueError(f"第 {i} 个 sheet 名称「{label}」不可用 __ 前缀（伪命名空间保留）")
    if label in _RESERVED_LABELS:
        raise ValueError(f"第 {i} 个 sheet 名称「{label}」为保留字（{ '/'.join(sorted(_RESERVED_LABELS)) }），请换一个")


def sheet_payload_of(r: models.DataSetRow) -> dict:
    """DataSetRow 模型 → 新 sheet 形态载荷（复制/克隆路径透传 label/desc/order）。"""
    return {
        "label": r.label or f"Sheet{r.row_index}",
        "data": deepcopy(r.data or {}),
        "field_desc": deepcopy(r.field_desc) if r.field_desc else None,
        "field_order": deepcopy(r.field_order) if r.field_order else None,
    }


def _normalize_rows_input(rows_data: list) -> list[dict]:
    """行输入归一为 sheet 形态 [{label, data, field_desc, field_order}]。

    新形态判定：dict 且含 "label" 键且 "data" 是 dict（历史行数据的键形如
    s1_atd / nodes，不会恰好同时满足）；旧形态 [data_dict] → label 缺省 None
    （调用方按 Sheet{i} 兜底）。返回前完成 label 校验、查重与缺省命名。"""
    normalized: list[dict] = []
    seen: set[str] = set()
    for i, el in enumerate(rows_data, start=1):
        if isinstance(el, dict) and "label" in el and isinstance(el.get("data"), dict):
            data = el["data"]
            label = el.get("label")
            label = label.strip() if isinstance(label, str) else None
            if label is None or label == "":
                label = f"Sheet{i}"
            _validate_sheet_label(i, label)
            field_desc = el.get("field_desc")
            field_order = el.get("field_order")
        elif isinstance(el, dict):
            # 旧形态：纯数据 dict（replace_rows 历史载荷 / 复制路径历史调用）
            data = el
            label = f"Sheet{i}"
            field_desc = None
            field_order = None
        else:
            raise ValueError(f"第 {i} 个 sheet 的数据必须是对象")
        if label in seen:
            raise ValueError(f"第 {i} 个 sheet 名称重复：{label}")
        seen.add(label)
        normalized.append({
            "label": label,
            "data": data,
            "field_desc": dict(field_desc) if isinstance(field_desc, dict) and field_desc else None,
            "field_order": [k for k in field_order if isinstance(k, str)] if isinstance(field_order, list) and field_order else None,
        })
    return normalized


def replace_rows(db: Session, dataset_id: int, rows_data: list,
                 user_id: int | None = None) -> models.DataSet:
    """整体替换数据集行（数据集管理面板保存）：重编 row_index 1..n。

    至少一行（空数据集无法执行，plan_case_expansion 会拒）；载荷为新 sheet 形态
    [{label, data, field_desc?, field_order?}]，兼容旧 [dict]（label 自动 Sheet{i}）。
    """
    if not rows_data:
        raise ValueError("至少保留一个 sheet（空数据集无法执行）")
    if len(rows_data) > 999:
        raise ValueError("sheet 数量过多（上限 999）")
    sheets = _normalize_rows_input(rows_data)
    ds = get_dataset(db, dataset_id)
    db.query(models.DataSetRow).filter(models.DataSetRow.dataset_id == ds.id).delete()
    for i, s in enumerate(sheets, start=1):
        db.add(models.DataSetRow(dataset_id=ds.id, row_index=i, data=deepcopy(s["data"]),
                                 label=s["label"], field_desc=s["field_desc"], field_order=s["field_order"]))
    if user_id is not None:
        ds.updated_by = user_id
    db.commit()
    db.refresh(ds)
    return ds


# ============ 数据集 CRUD ============

def list_by_project(db: Session, project_id: int) -> list[models.DataSet]:
    """项目级数据集清单（独立数据集管理页）：按归属用例过滤，按用例+id 稳定排序。"""
    return (db.query(models.DataSet)
            .join(models.TestCase, models.TestCase.id == models.DataSet.case_id)
            .filter(models.TestCase.project_id == project_id)
            .order_by(models.DataSet.case_id, models.DataSet.id)
            .all())


def create_dataset(db: Session, project_id: int | None, name: str,
                   user_id: int | None, description: str | None = None,
                   rows_data: list | None = None, case_id: int | None = None) -> models.DataSet:
    """建数据集；rows_data 可选（复制/克隆即带行数据的原子写入路径）。"""
    if not name or not name.strip():
        raise ValueError("数据集名称不能为空")
    if len(name) > 100:
        raise ValueError("名称最多 100 字符")
    obj = models.DataSet(project_id=project_id, case_id=case_id,
                         name=name, description=description,
                         created_by=user_id, updated_by=user_id)
    db.add(obj)
    if rows_data:
        db.flush()  # 先拿 id，行数据外键依赖
        for i, s in enumerate(_normalize_rows_input(rows_data), start=1):
            db.add(models.DataSetRow(dataset_id=obj.id, row_index=i,
                                     data=dict(s["data"]), label=s["label"],
                                     field_desc=s["field_desc"], field_order=s["field_order"]))
    db.commit()
    db.refresh(obj)
    return obj


def get_dataset(db: Session, dataset_id: int) -> models.DataSet:
    obj = crud.get_dataset(db, dataset_id)
    if not obj:
        raise ValueError(f"数据集不存在: {dataset_id}")
    return obj


def update_dataset(db: Session, dataset_id: int, name: str | None = None,
                   description: str | None = None) -> models.DataSet:
    obj = get_dataset(db, dataset_id)
    if name is not None:
        if not name.strip():
            raise ValueError("数据集名称不能为空")
        obj.name = name
    if description is not None:
        obj.description = description
    db.commit()
    db.refresh(obj)
    return obj


def delete_dataset(db: Session, dataset_id: int) -> None:
    """删除数据集：被用例绑定时拒绝；成功级联删行。"""
    obj = get_dataset(db, dataset_id)
    n = crud.count_cases_bound_to_dataset(db, dataset_id)
    if n:
        raise ValueError(f"数据集被 {n} 个用例绑定，请先在用例中解绑后再删除")
    db.query(models.DataSetRow).filter(models.DataSetRow.dataset_id == dataset_id).delete()
    db.delete(obj)
    db.commit()


# ============ 单节点入参配置保存（数据集页节点 tab） ============

def save_node_config(db: Session, dataset_id: int, node_id: str,
                     params: dict | None,
                     user_id: int | None = None) -> models.DataSet:
    """保存单节点入参配置（整体替换该节点的 params）。"""
    if not node_id:
        raise ValueError("node_id 不能为空")
    ds = get_dataset(db, dataset_id)
    row = _ensure_row(db, ds)
    data = dict(row.data or {})
    raw_nodes = data.get("nodes")
    nodes = dict(raw_nodes) if isinstance(raw_nodes, dict) else {}
    nodes[node_id] = {"params": params or {}}
    data["nodes"] = nodes
    row.data = data
    if user_id is not None:
        ds.updated_by = user_id
    db.commit()
    db.refresh(ds)
    return ds


def remove_node_config(db: Session, dataset_id: int, node_id: str,
                       user_id: int | None = None) -> models.DataSet:
    """清理悬空节点配置（画布节点已删，行内配置不再被执行）。"""
    ds = get_dataset(db, dataset_id)
    rows = ds.rows or []
    if not rows:
        return ds
    row = rows[0]
    data = dict(row.data or {})
    raw_nodes = data.get("nodes")
    if isinstance(raw_nodes, dict) and node_id in raw_nodes:
        nodes = dict(raw_nodes)
        del nodes[node_id]
        data["nodes"] = nodes
        row.data = data
        if user_id is not None:
            ds.updated_by = user_id
        db.commit()
        db.refresh(ds)
    return ds


# ============ 执行展开（单套语义：每个数据集 = 一套入参配置） ============

def list_case_rows(db: Session, case, dataset_id=None) -> list[dict]:
    """列出绑定数据集的全部数据行（row 形状与 plan_case_expansion 一致，不带 sheets）。

    串行链整链轮次取值用：第 r 轮取第 r 个 sheet（不足沿用末个）——
    校验口径与 plan_case_expansion 完全一致（未绑定/悬空/无数据行均在此报错）。
    """
    effective = dataset_id if dataset_id is not None else getattr(case, "dataset_id", None)
    if not effective:
        raise ValueError("用例未绑定数据集：请先在用例管理绑定，并在数据集页完成入参配置")
    ds = crud.get_dataset(db, effective)
    if not ds:
        raise ValueError(f"用例绑定的数据集不存在: {effective}")
    if ds.case_id != case.id:
        raise ValueError("数据集不属于该用例（数据集按用例隔离，请在用例自己的数据集中选择）")
    rows = crud.list_rows(db, effective)
    if not rows:
        raise ValueError("数据集无数据行，请先在数据集页完成入参配置")
    return [{
        "row_index": x.row_index,
        "data": dict(x.data or {}),
        "label": x.label or (ds.name + (f" 第{x.row_index}行" if len(rows) > 1 else "")),
    } for x in rows]


def plan_case_expansion(db: Session, case, dataset_id=None, row_index=None) -> list:
    """按用例绑定生成执行展开计划。

    - 未绑定（且未临时指定）→ ValueError：执行强绑定（2026-09-30 定案，
      「未绑数据集执行放行」的旧语义废止）
    - 绑定数据集 → 单条：行数据（各节点入参配置）注入执行上下文
    - dataset_id 传入时临时覆盖用例绑定（执行面板换数据集，不改绑定本身）
    - row_index 传入时选指定数据行（执行面板换行，值=DataSetRow.row_index，
      缺省第 1 行；不影响数据集内容）
    """
    effective = dataset_id if dataset_id is not None else getattr(case, "dataset_id", None)
    if not effective:
        raise ValueError("用例未绑定数据集：请先在用例管理绑定，并在数据集页完成入参配置")
    ds = crud.get_dataset(db, effective)
    if not ds:
        raise ValueError(f"用例绑定的数据集不存在: {effective}")
    if ds.case_id != case.id:
        raise ValueError("数据集不属于该用例（数据集按用例隔离，请在用例自己的数据集中选择）")
    rows = crud.list_rows(db, effective)
    if not rows:
        raise ValueError("数据集无数据行，请先在数据集页完成入参配置")
    if row_index is not None:
        r = next((x for x in rows if x.row_index == row_index), None)
        if r is None:
            avail = "、".join(f"{x.row_index}({x.label or f'Sheet{x.row_index}'})" for x in rows)
            raise ValueError(f"数据集「{ds.name}」没有第 {row_index} 个 sheet（现有：{avail}）")
    else:
        r = rows[0]
    # row.label 优先真 sheet 名（历史行无 label 回退旧合成形式）；
    # sheets 携带全部 sheet 供引擎以 ${sheet.字段} 命名空间注入（context.py）
    return [{
        "dataset_id": effective,
        "row": {
            "row_index": r.row_index,
            "data": dict(r.data or {}),
            "label": r.label or (ds.name + (f" 第{r.row_index}行" if len(rows) > 1 else "")),
        },
        "sheets": [
            {"row_index": x.row_index, "label": x.label or f"Sheet{x.row_index}", "data": dict(x.data or {})}
            for x in rows
        ],
    }]


# ============ 绑定校验（执行面板换绑 / 用例保存显式传 dataset_id） ============

def validate_binding(db: Session, case, dataset_id: int | None) -> None:
    if dataset_id is None:
        return
    ds = crud.get_dataset(db, dataset_id)
    if not ds:
        raise ValueError(f"数据集不存在: {dataset_id}")
    if ds.case_id != case.id:
        raise ValueError("数据集不属于该用例（数据集按用例隔离）")


# ============ 保存用例钩子：默认数据集初始化 + 画布节点增量（Q7，2026-10-10 定案） ============

def _node_initial_params(db: Session, case) -> dict[str, dict]:
    """画布节点 → 初始入参配置 {"节点ID": {"params": {"body": ...}}}。

    按各节点绑定接口的字段生成（示例值拆解，Q9-B：object/array 按结构拆
    叶子路径逐字段 constant），口径与契约同步一致（contract_sync.apply_node_sync）。
    未绑定接口的节点不初始化（执行时也无请求）。
    """
    from .contract_sync import apply_node_sync  # 函数内延迟：contract_sync 依赖本模块

    struct = {c.node_id: c for c in db.query(models.CaseNodeConfig)
              .filter(models.CaseNodeConfig.case_id == case.id).all()}
    api_ids = {c.api_id for c in struct.values() if c.api_id}
    apis = {a.id: a for a in db.query(models.ApiDefinition)
            .filter(models.ApiDefinition.id.in_(api_ids)).all()} if api_ids else {}
    dag_nodes = [str(n["id"]) for n in ((case.dag_config or {}).get("nodes") or [])
                 if isinstance(n, dict) and n.get("id")]
    out: dict[str, dict] = {}
    for nid in dag_nodes:
        c = struct.get(nid)
        api = apis.get(c.api_id) if (c and c.api_id) else None
        if api is None:
            continue
        body, _ = apply_node_sync(None, api.fields)
        if body:
            out[nid] = {"params": {"body": body}}
    return out


def ensure_case_dataset(db: Session, case, user_id: int | None = None,
                        *, allow_create: bool = True) -> None:
    """保存用例钩子：未绑定 → 自动建「默认数据集」（示例值初始化全部节点）并绑定；
    已绑定 → 行内缺失的画布节点（新加节点）按接口字段补初始参数。
    - 已有节点的参数一律不动（契约出入走接口保存/数据集保存的同步弹窗许可）
    - allow_create=False 用于用户显式解绑数据集的保存：不重建绑定，仅增量
    - 初始化失败不阻断保存（打印日志，数据集页可见未配置状态）
    """
    try:
        if not getattr(case, "dataset_id", None):
            if not allow_create:
                return
            # 恒带首行（Sheet1）：零行数据集既无法执行也无法在节点配置新增 ${sheet.字段}
            # （2026-11-05；纯 UI 用例 nodes 为空 dict 也照建，与更新分支 _ensure_row 产物同形）
            nodes = _node_initial_params(db, case)
            rows_data = [{"nodes": nodes}]
            ds = create_dataset(db, project_id=case.project_id, name="默认数据集",
                                user_id=user_id, case_id=case.id, rows_data=rows_data)
            case.dataset_id = ds.id
            db.commit()
            return
        bound = crud.get_dataset(db, case.dataset_id)
        if not bound:
            return
        row = _ensure_row(db, bound)
        data = dict(row.data or {})
        raw_nodes = data.get("nodes")
        nodes = dict(raw_nodes) if isinstance(raw_nodes, dict) else {}
        fresh = False
        for nid, cfg in _node_initial_params(db, case).items():
            if nid not in nodes:
                nodes[nid] = cfg
                fresh = True
        if fresh:
            data["nodes"] = nodes
            row.data = data
            db.commit()
    except Exception as e:
        print(f"[数据集初始化] 跳过（失败不阻断保存）: {e}")
        db.rollback()


# ============ 复制 / 克隆 / 组合合并（纯值操作） ============

def copy_dataset(db: Session, dataset_id: int, name: str | None = None, user_id: int | None = None) -> models.DataSet:
    """复制数据集（值全量深拷贝，归属同用例）。默认命名「原名-副本」，重名递增。"""
    src = get_dataset(db, dataset_id)
    base = name or src.name
    if not name:
        if base.endswith("-副本") or "-副本" in base:
            stem, _, num = base.rpartition("-副本")
            try:
                n = int(num) if num else 1
            except ValueError:
                stem, n = base, 1
            base = f"{stem}-副本{n + 1}"
        else:
            base = f"{base}-副本"
        dup = (db.query(models.DataSet)
               .filter(models.DataSet.case_id == src.case_id, models.DataSet.name == base)
               .first())
        while dup:
            stem, _, num = base.rpartition("-副本")
            n = int(num) + 1 if num.isdigit() else 2
            base = f"{stem}-副本{n}"
            dup = (db.query(models.DataSet)
                   .filter(models.DataSet.case_id == src.case_id, models.DataSet.name == base)
                   .first())
    elif len(name) > 100:
        raise ValueError("名称最多 100 字符")
    return create_dataset(
        db, project_id=src.project_id, case_id=src.case_id,
        name=base, user_id=user_id, description=src.description,
        rows_data=[sheet_payload_of(r) for r in (src.rows or [])],
    )


def clone_dataset_to_case(db: Session, src: models.DataSet, target_case_id: int,
                          user_id: int | None = None) -> models.DataSet:
    """跨用例克隆数据集（行内节点入参配置全量深拷贝，保持原名）：复制/拆分用例的数据资产随迁。"""
    return create_dataset(
        db, project_id=src.project_id, case_id=target_case_id,
        name=src.name, user_id=user_id, description=src.description,
        rows_data=[sheet_payload_of(r) for r in (src.rows or [])],
    )
