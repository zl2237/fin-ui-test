"""UI 动作用法文档路由：非原生动作的项目级说明（帮助中心展示 / 动作库管理编辑）。

action_key 约定：预设封装动作用动作名（如 toast_watch）；自定义动作用 custom:{id}。
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/api/ui-action-docs", tags=["UI动作文档"])

# 预设动作名（字母/数字/下划线）或 custom:{id}
_ACTION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$|^custom:\d+$")


@router.get("", response_model=list[schemas.UiActionDocOut])
def list_all(
    project_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """项目内全部用法文本覆盖（帮助中心「UI 动作解析」合并展示）"""
    objs = crud.list_ui_action_docs(db, project_id)
    crud.fill_audit_names_batch(db, objs)
    return objs


@router.put("/{action_key}", response_model=schemas.UiActionDocOut | None)
def upsert(
    action_key: str,
    data: schemas.UiActionDocUpsert,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """保存/清除一条用法文本（空文本=删除覆盖）；引用的自定义动作需真实存在"""
    if not _ACTION_KEY_RE.match(action_key):
        raise HTTPException(400, f"非法动作标识: {action_key}")
    if action_key.startswith("custom:"):
        ca = crud.get_custom_action(db, int(action_key.split(":", 1)[1]))
        if not ca or ca.project_id != data.project_id:
            raise HTTPException(404, "自定义动作不存在")
    obj = crud.upsert_ui_action_doc(db, data.project_id, action_key, data, user.id)
    if obj is None:
        return None
    crud.fill_audit_names(db, obj)
    crud.log_operation(db, user, "update", "ui_action_doc", obj.id, action_key)
    return obj
