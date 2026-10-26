"""页面域字典路由：项目级页面域英文标识 → 中文语义映射，所有登录用户可编辑"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/api/page-scope-labels", tags=["页面域字典"])


@router.get("/map")
def get_map(
    project_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """返回 {page_scope: label} 映射，元素库侧栏树展示用"""
    return crud.get_page_scope_label_map(db, project_id)


@router.post("/batch", response_model=schemas.BatchImportResultOut)
def batch_save(
    data: schemas.PageScopeLabelBatchIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """批量保存页面域语义（覆盖式：同 page_scope 更新 label，空 label 清除映射）

    请求体示例：
    {
      "project_id": 1,
      "items": [
        {"page_scope": "ordermanage/business_order_add", "label": "新建委托订单"},
        {"page_scope": "ordermanage/order_self_details", "label": ""}
      ]
    }
    """
    if not data.items:
        raise HTTPException(400, "保存列表不能为空")
    count = crud.batch_upsert_page_scope_labels(db, data.project_id, data.items, user.id)
    crud.log_operation(db, user, "batch_save", "page_scope_label", None, f"{count} items")
    return {"message": f"已保存 {count} 条页面域语义", "count": count}
