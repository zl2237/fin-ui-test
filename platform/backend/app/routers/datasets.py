"""数据集管理路由（多套数据维护入口，2026-10-23 补齐）。

数据集按用例 1:N 隔离；本路由补上此前的维护缺口——前端只有执行时只读选择，
建/改/删全靠脚本。操作口径与 dataset_service 一致：
- 新建：空行起步或复制现有数据集（多场景 = 复制后改值，执行时换绑）
- 行维护：整体替换（前端编辑完一次保存，重编行号 1..n）
- 删除：被用例绑定时拒绝（先解绑）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..services import dataset_service as svc

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


class DataSetCreateIn(schemas.DataSetCreate):
    # project_id 以归属用例为准（body 可不传，防口径漂移）；copy_from 为复制来源
    project_id: int | None = None
    copy_from_dataset_id: int | None = None


class DataSetRowsReplaceIn(BaseModel):
    rows: list[dict]  # 行数据对象数组，整体替换、重编行号


def _owned_dataset(db: Session, dataset_id: int) -> models.DataSet:
    ds = crud.get_dataset(db, dataset_id)
    if not ds:
        raise HTTPException(404, f"数据集不存在: {dataset_id}")
    return ds


def _fill_out(db: Session, ds: models.DataSet) -> schemas.DataSetOut:
    out = schemas.DataSetOut.model_validate(ds)
    out.case_bound_count = crud.count_cases_bound_to_dataset(db, ds.id)
    return out


@router.get("", response_model=list[schemas.DataSetOut])
def list_datasets(project_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    """项目级数据集清单（独立数据集管理页）：按归属用例过滤，含绑定计数。"""
    return [_fill_out(db, ds) for ds in svc.list_by_project(db, project_id)]


@router.post("", response_model=schemas.DataSetOut)
def create_dataset(data: DataSetCreateIn, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    """新建数据集（归属用例隔离）。copy_from_dataset_id 时全量拷贝来源行数据。"""
    case = crud.get_testcase(db, data.case_id)
    if not case:
        raise HTTPException(404, f"用例不存在: {data.case_id}")
    rows_data = None
    if data.copy_from_dataset_id is not None:
        src = _owned_dataset(db, data.copy_from_dataset_id)
        if src.case_id != data.case_id:
            raise HTTPException(400, "只能复制本用例的数据集（数据集按用例隔离）")
        rows_data = [svc.sheet_payload_of(r) for r in (src.rows or [])]
    try:
        ds = svc.create_dataset(db, project_id=case.project_id, name=data.name,
                                user_id=user.id, description=data.description,
                                rows_data=rows_data, case_id=case.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    crud.log_operation(db, user, "create", "dataset", ds.id, ds.name)
    return _fill_out(db, ds)


@router.put("/{dataset_id}", response_model=schemas.DataSetOut)
def update_dataset(dataset_id: int, data: schemas.DataSetUpdate,
                   db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """改名/改描述。"""
    _owned_dataset(db, dataset_id)
    try:
        ds = svc.update_dataset(db, dataset_id, name=data.name, description=data.description)
    except ValueError as e:
        raise HTTPException(400, str(e))
    crud.log_operation(db, user, "update", "dataset", ds.id, ds.name)
    return _fill_out(db, ds)


@router.post("/{dataset_id}/copy", response_model=schemas.DataSetOut)
def copy_dataset(dataset_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(get_current_user)):
    """复制数据集（值全量深拷贝，默认名「原名-副本」）——多场景标准起步。"""
    src = _owned_dataset(db, dataset_id)
    ds = svc.copy_dataset(db, dataset_id, user_id=user.id)
    crud.log_operation(db, user, "copy", "dataset", ds.id, f"复制自 {src.name}")
    return _fill_out(db, ds)


@router.delete("/{dataset_id}", response_model=schemas.MessageOut)
def delete_dataset(dataset_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    """删除数据集（级联删行；被用例绑定时拒绝，先在用例上解绑）。"""
    ds = _owned_dataset(db, dataset_id)
    try:
        svc.delete_dataset(db, dataset_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    crud.log_operation(db, user, "delete", "dataset", ds.id, ds.name)
    return {"message": "已删除"}


@router.put("/{dataset_id}/rows", response_model=schemas.DataSetOut)
def replace_rows(dataset_id: int, data: DataSetRowsReplaceIn,
                 db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """整体替换数据集行（管理面板编辑保存）：重编行号 1..n，至少一行。"""
    _owned_dataset(db, dataset_id)
    try:
        ds = svc.replace_rows(db, dataset_id, data.rows, user_id=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    crud.log_operation(db, user, "update", "dataset", ds.id, f"{ds.name} 行数据")
    return _fill_out(db, ds)
