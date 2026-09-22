"""UI 动作用法文档 CRUD：项目级（预设动作覆盖 / 自定义动作补充）"""
from sqlalchemy.orm import Session

from .. import models, schemas


def list_ui_action_docs(db: Session, project_id: int) -> list[models.UiActionDoc]:
    return (
        db.query(models.UiActionDoc)
        .filter(models.UiActionDoc.project_id == project_id)
        .order_by(models.UiActionDoc.id)
        .all()
    )


def get_ui_action_doc(db: Session, project_id: int, action_key: str) -> models.UiActionDoc | None:
    return (
        db.query(models.UiActionDoc)
        .filter(models.UiActionDoc.project_id == project_id,
                models.UiActionDoc.action_key == action_key)
        .first()
    )


def upsert_ui_action_doc(
    db: Session, project_id: int, action_key: str, data: schemas.UiActionDocUpsert, user_id: int
) -> models.UiActionDoc | None:
    """保存项目级用法文本；空文本 = 删除覆盖（回落动作内置说明），返回 None 表示已删"""
    obj = get_ui_action_doc(db, project_id, action_key)
    text = (data.usage_text or "").strip()
    if not text:
        if obj:
            db.delete(obj)
            db.commit()
        return None
    if obj:
        obj.usage_text = text
        obj.updated_by = user_id
    else:
        obj = models.UiActionDoc(
            project_id=project_id, action_key=action_key,
            usage_text=text, created_by=user_id, updated_by=user_id,
        )
        db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
