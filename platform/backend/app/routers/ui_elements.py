"""UI 元素库路由：页面元素定位器 CRUD + locator JSON 批量导入（所有登录用户可编辑）"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/api/ui-elements", tags=["UI元素库"])


@router.get("", response_model=list[schemas.UiElementOut])
def list_all(
    project_id: int,
    page_scope: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """查询项目元素库，支持按页面域过滤、key/描述搜索"""
    objs = crud.list_ui_elements(db, project_id, page_scope, keyword)
    crud.fill_audit_names_batch(db, objs)
    return objs


@router.get("/scopes")
def list_scopes(
    project_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """项目下已有页面域清单：[{page_scope, count}]"""
    return crud.list_page_scopes(db, project_id)


@router.post("", response_model=schemas.UiElementOut)
def create(
    data: schemas.UiElementCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """新增元素"""
    if crud.get_ui_element_by_key(db, data.project_id, data.page_scope, data.element_key):
        raise HTTPException(400, f"元素已存在: {data.page_scope}.{data.element_key}")
    obj = crud.create_ui_element(db, data, user.id)
    crud.fill_audit_names(db, obj)
    crud.log_operation(db, user, "create", "ui_element", obj.id, obj.element_key)
    return obj


@router.post("/batch")
def batch_import(
    data: schemas.UiElementBatchIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """按页面域批量导入元素（覆盖式：同 key 更新 strategies，新 key 插入）

    请求体示例（承接 locator JSON 的 {key: {策略字段, description}} 展开结果）：
    {
      "project_id": 1,
      "page_scope": "ordermanage/business_order_add",
      "items": [
        {"element_key": "bl_no_input", "strategies": {"full_xpath": "//...", "label": "提单号 *"},
         "description": "提单号输入框"}
      ]
    }
    """
    if not data.items:
        raise HTTPException(400, "导入列表不能为空")
    count = crud.batch_upsert_ui_elements(db, data.project_id, data.page_scope, data.items, user.id)
    crud.log_operation(db, user, "batch_import", "ui_element", None, f"{count} items")
    return {"message": f"已导入 {count} 个元素", "count": count}


@router.put("/{element_id}", response_model=schemas.UiElementOut)
def update(
    element_id: int,
    data: schemas.UiElementUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """更新元素"""
    obj = crud.get_ui_element(db, element_id)
    if not obj:
        raise HTTPException(404, "元素不存在")
    if data.element_key and data.element_key != obj.element_key:
        if crud.get_ui_element_by_key(db, obj.project_id, obj.page_scope, data.element_key):
            raise HTTPException(400, f"元素已存在: {obj.page_scope}.{data.element_key}")
    obj = crud.update_ui_element(db, obj, data, user.id)
    crud.fill_audit_names(db, obj)
    crud.log_operation(db, user, "update", "ui_element", obj.id, obj.element_key)
    return obj


@router.delete("/{element_id}")
def remove(
    element_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """删除元素"""
    obj = crud.get_ui_element(db, element_id)
    if not obj:
        raise HTTPException(404, "元素不存在")
    crud.log_operation(db, user, "delete", "ui_element", obj.id, obj.element_key)
    crud.delete_ui_element(db, obj)
    return {"message": "已删除"}
