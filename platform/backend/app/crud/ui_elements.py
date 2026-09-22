"""UI 元素库域：项目级页面元素定位器的 CRUD 与批量导入。

承接 autotest-playwright 的 locator JSON（module/<模块>/<页面>/locator/<页面>.json
的 {key: {策略字段, description}} 结构），page_scope 即原"页面"维度。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models, schemas


def list_ui_elements(db: Session, project_id: int, page_scope: str | None = None,
                     keyword: str | None = None) -> list[models.UiElement]:
    """列出项目下元素，支持按页面域过滤、element_key/description 模糊搜索"""
    q = db.query(models.UiElement).filter(models.UiElement.project_id == project_id)
    if page_scope:
        q = q.filter(models.UiElement.page_scope == page_scope)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            models.UiElement.element_key.like(like)
            | models.UiElement.description.like(like)
        )
    return q.order_by(models.UiElement.page_scope, models.UiElement.element_key).all()


def get_ui_element(db: Session, element_id: int) -> models.UiElement | None:
    return db.query(models.UiElement).filter(models.UiElement.id == element_id).first()


def get_ui_element_by_key(db: Session, project_id: int, page_scope: str,
                          element_key: str) -> models.UiElement | None:
    return db.query(models.UiElement).filter(
        models.UiElement.project_id == project_id,
        models.UiElement.page_scope == page_scope,
        models.UiElement.element_key == element_key,
    ).first()


def create_ui_element(db: Session, data: schemas.UiElementCreate, user_id: int | None) -> models.UiElement:
    obj = models.UiElement(
        project_id=data.project_id,
        page_scope=data.page_scope,
        element_key=data.element_key,
        strategies=data.strategies or {},
        description=data.description,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_ui_element(db: Session, obj: models.UiElement, data: schemas.UiElementUpdate,
                      user_id: int | None) -> models.UiElement:
    """setattr 泛型更新（与仓库其他域一致：exclude_unset 只动传入字段）"""
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    obj.updated_by = user_id
    db.commit()
    db.refresh(obj)
    return obj


def delete_ui_element(db: Session, obj: models.UiElement) -> None:
    db.delete(obj)
    db.commit()


def batch_upsert_ui_elements(db: Session, project_id: int, page_scope: str,
                             items: list[schemas.UiElementItemIn], user_id: int | None) -> int:
    """覆盖式批量导入：同 (page_scope, element_key) 更新 strategies，新 key 插入。"""
    count = 0
    for item in items:
        obj = get_ui_element_by_key(db, project_id, page_scope, item.element_key)
        if obj:
            obj.strategies = item.strategies or {}
            obj.description = item.description
            obj.updated_by = user_id
        else:
            db.add(models.UiElement(
                project_id=project_id,
                page_scope=page_scope,
                element_key=item.element_key,
                strategies=item.strategies or {},
                description=item.description,
                created_by=user_id,
                updated_by=user_id,
            ))
        count += 1
    db.commit()
    return count


def list_page_scopes(db: Session, project_id: int) -> list[dict]:
    """项目下已有页面域清单（元素库左侧树用）：[{page_scope, count}]"""
    from sqlalchemy import func
    rows = (
        db.query(models.UiElement.page_scope, func.count(models.UiElement.id))
        .filter(models.UiElement.project_id == project_id)
        .group_by(models.UiElement.page_scope)
        .order_by(models.UiElement.page_scope)
        .all()
    )
    return [{"page_scope": scope, "count": cnt} for scope, cnt in rows]
