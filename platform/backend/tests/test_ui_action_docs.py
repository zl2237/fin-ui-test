"""UiActionDoc（非原生动作用法文档）单测：action_key 契约 + upsert 语义 + schema 契约。

不连数据库：crud 层用内存替身 Session 验证 add/update/delete 分支语义。
"""
from types import SimpleNamespace

import pytest

from app import schemas
from app.crud import ui_action_docs as crud_docs
from app.routers.ui_action_docs import _ACTION_KEY_RE


class TestActionKeyContract:
    """action_key 约定：预设动作名（小写+下划线）或 custom:{id}"""

    @pytest.mark.parametrize("key", [
        "toast_watch", "save", "click_text", "scroll_bottom", "custom:5", "custom:123",
    ])
    def test_valid_keys(self, key):
        assert _ACTION_KEY_RE.match(key)

    @pytest.mark.parametrize("key", [
        "Bad Key", "custom:abc", "custom:", "DROP TABLE", "eval();", "a" * 50,
        "goto ", "1goto",
    ])
    def test_invalid_keys(self, key):
        assert not _ACTION_KEY_RE.match(key)


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    """内存替身：只实现 crud 用到的 query/add/delete/commit/refresh"""

    def __init__(self, rows=()):
        self._rows = list(rows)
        self.added = []
        self.deleted = []
        self.commits = 0

    def query(self, model):
        return _Query(self._rows)

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


def _upsert_data(text):
    return schemas.UiActionDocUpsert(project_id=1, usage_text=text)


class TestUpsertSemantics:
    def test_create_when_absent(self):
        db = _Session()
        obj = crud_docs.upsert_ui_action_doc(db, 1, "toast_watch", _upsert_data("  等待成功提示  "), user_id=3)
        assert obj is not None and obj.usage_text == "等待成功提示"   # 首尾空白剥离
        assert len(db.added) == 1 and obj.action_key == "toast_watch"
        assert db.commits == 1
        assert obj.created_by == 3 and obj.updated_by == 3

    def test_update_existing_overwrites_text(self):
        old = SimpleNamespace(project_id=1, action_key="save", usage_text="旧说明",
                              created_by=3, updated_by=3)
        db = _Session([old])
        obj = crud_docs.upsert_ui_action_doc(db, 1, "save", _upsert_data("新说明"), user_id=7)
        assert obj is old                       # 原对象更新
        assert old.usage_text == "新说明" and old.updated_by == 7
        assert not db.added                     # 不新增行

    def test_empty_text_deletes_override(self):
        old = SimpleNamespace(project_id=1, action_key="save", usage_text="旧说明")
        db = _Session([old])
        obj = crud_docs.upsert_ui_action_doc(db, 1, "save", _upsert_data("   "), user_id=7)
        assert obj is None                      # 空文本 = 删除覆盖（回落内置说明）
        assert db.deleted == [old] and db.commits == 1

    def test_empty_text_without_existing_is_noop(self):
        db = _Session()
        obj = crud_docs.upsert_ui_action_doc(db, 1, "save", _upsert_data(""), user_id=7)
        assert obj is None
        assert not db.added and not db.deleted and db.commits == 0


class TestSchemaContract:
    def test_upsert_fields(self):
        assert set(schemas.UiActionDocUpsert.model_fields) == {"project_id", "usage_text"}

    def test_out_fields_with_audit(self):
        fields = set(schemas.UiActionDocOut.model_fields)
        assert {"id", "project_id", "action_key", "usage_text", "updated_by_name"} <= fields
