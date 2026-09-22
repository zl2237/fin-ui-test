"""自定义 UI 动作 CRUD：项目级 JS 动作模板"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas


def list_custom_actions(db: Session, project_id: int) -> list[models.CustomAction]:
    return (
        db.query(models.CustomAction)
        .filter(models.CustomAction.project_id == project_id)
        .order_by(models.CustomAction.id)
        .all()
    )


def get_custom_action(db: Session, action_id: int) -> models.CustomAction | None:
    return db.query(models.CustomAction).filter(models.CustomAction.id == action_id).first()


def get_custom_action_by_name(db: Session, project_id: int, name: str) -> models.CustomAction | None:
    return (
        db.query(models.CustomAction)
        .filter(models.CustomAction.project_id == project_id, models.CustomAction.name == name)
        .first()
    )


def create_custom_action(db: Session, data: schemas.CustomActionCreate, user_id: int) -> models.CustomAction:
    if not data.script.strip():
        raise HTTPException(400, "脚本不能为空")
    obj = models.CustomAction(
        project_id=data.project_id,
        name=data.name,
        description=data.description,
        script=data.script,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_custom_action(
    db: Session, obj: models.CustomAction, data: schemas.CustomActionUpdate, user_id: int
) -> models.CustomAction:
    if data.script is not None and not data.script.strip():
        raise HTTPException(400, "脚本不能为空")
    if data.name is not None:
        obj.name = data.name
    if data.description is not None:
        obj.description = data.description
    if data.script is not None:
        obj.script = data.script
    obj.updated_by = user_id
    db.commit()
    db.refresh(obj)
    return obj


def delete_custom_action(db: Session, obj: models.CustomAction) -> None:
    db.delete(obj)
    db.commit()
