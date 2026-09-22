"""自定义 UI 动作路由：项目级 JS 动作模板 CRUD（所有登录用户可编辑）"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/api/custom-actions", tags=["自定义动作"])


@router.get("", response_model=list[schemas.CustomActionOut])
def list_all(
    project_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """项目自定义动作清单（编排动作下拉并入显示）"""
    objs = crud.list_custom_actions(db, project_id)
    crud.fill_audit_names_batch(db, objs)
    return objs


@router.post("", response_model=schemas.CustomActionOut)
def create(
    data: schemas.CustomActionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """新建自定义动作（script 为 JS 函数体，入参 args，return 值进 facts.result）"""
    if crud.get_custom_action_by_name(db, data.project_id, data.name):
        raise HTTPException(400, f"同名自定义动作已存在: {data.name}")
    obj = crud.create_custom_action(db, data, user.id)
    crud.fill_audit_names(db, obj)
    crud.log_operation(db, user, "create", "custom_action", obj.id, obj.name)
    return obj


@router.put("/{action_id}", response_model=schemas.CustomActionOut)
def update(
    action_id: int,
    data: schemas.CustomActionUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """更新自定义动作"""
    obj = crud.get_custom_action(db, action_id)
    if not obj:
        raise HTTPException(404, "自定义动作不存在")
    if data.name and data.name != obj.name:
        if crud.get_custom_action_by_name(db, obj.project_id, data.name):
            raise HTTPException(400, f"同名自定义动作已存在: {data.name}")
    obj = crud.update_custom_action(db, obj, data, user.id)
    crud.fill_audit_names(db, obj)
    crud.log_operation(db, user, "update", "custom_action", obj.id, obj.name)
    return obj


@router.delete("/{action_id}")
def remove(
    action_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """删除自定义动作（引用它的节点执行时会明确报错提示重新选择）"""
    obj = crud.get_custom_action(db, action_id)
    if not obj:
        raise HTTPException(404, "自定义动作不存在")
    crud.log_operation(db, user, "delete", "custom_action", obj.id, obj.name)
    crud.delete_custom_action(db, obj)
    return {"message": "已删除"}
