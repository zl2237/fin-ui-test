"""PageScopeLabel（页面域字典）单测：批量 upsert 语义 + map 契约。

不连数据库：crud 层用内存替身 Session 验证 插入/更新/空label删除 分支语义。
"""
from types import SimpleNamespace

from app import crud, schemas


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    """内存替身：只实现 crud 用到的 query/add/delete/commit"""

    def __init__(self, rows=()):
        self._rows = list(rows)
        self.added = []
        self.deleted = []
        self.commits = 0

    def query(self, *a):
        return _Query(self._rows)

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.commits += 1


def _items(*pairs):
    return [schemas.PageScopeLabelItemIn(page_scope=s, label=l) for s, l in pairs]


class TestBatchUpsertSemantics:
    def test_insert_when_absent(self):
        db = _Session()
        n = crud.batch_upsert_page_scope_labels(
            db, 1, _items(("ordermanage/business_order_add", "新建委托订单")), user_id=3)
        assert n == 1 and len(db.added) == 1
        obj = db.added[0]
        assert obj.page_scope == "ordermanage/business_order_add" and obj.label == "新建委托订单"
        assert obj.created_by == 3 and obj.updated_by == 3
        assert db.commits == 1

    def test_update_existing_overwrites_label(self):
        old = SimpleNamespace(project_id=1, page_scope="workbench/approval_center",
                              label="审批中心", updated_by=3)
        db = _Session([old])
        n = crud.batch_upsert_page_scope_labels(
            db, 1, _items(("workbench/approval_center", "产研审批中心")), user_id=7)
        assert n == 1 and not db.added          # 不新增行
        assert old.label == "产研审批中心" and old.updated_by == 7

    def test_empty_label_deletes_mapping(self):
        old = SimpleNamespace(project_id=1, page_scope="x/y", label="旧语义", updated_by=3)
        db = _Session([old])
        n = crud.batch_upsert_page_scope_labels(db, 1, _items(("x/y", "")), user_id=7)
        assert n == 1 and db.deleted == [old]   # 空文本 = 清除语义

    def test_empty_label_without_existing_is_noop(self):
        db = _Session()
        n = crud.batch_upsert_page_scope_labels(db, 1, _items(("x/y", "")), user_id=7)
        assert n == 0 and not db.added and not db.deleted

    def test_mixed_batch_counts_effected_only(self):
        db = _Session()
        n = crud.batch_upsert_page_scope_labels(
            db, 1, _items(("a/b", "语义A"), ("c/d", "")), user_id=7)
        assert n == 1                            # 只有生效行计数


class TestMapContract:
    def test_map_builds_scope_to_label(self):
        db = _Session([("ordermanage/business_order_add", "新建委托订单"),
                       ("workbench/approval_center", "审批中心")])
        m = crud.get_page_scope_label_map(db, 1)
        assert m == {"ordermanage/business_order_add": "新建委托订单",
                     "workbench/approval_center": "审批中心"}


class TestSchemaContract:
    def test_batch_in_fields(self):
        data = schemas.PageScopeLabelBatchIn(project_id=1, items=_items(("a/b", "甲")))
        assert data.items[0].page_scope == "a/b" and data.items[0].label == "甲"
