"""文件中心新功能单测：截图归档（分类保障+执行人）+ 批量删除（多条件+引用计数）。

用内存 SQLite 建真实表（模型无 MySQL 方言类型），走真实 CRUD 路径；
save_screenshot_file 的物理落盘通过 monkeypatch UPLOAD_ROOT 重定向到 tmp 目录。
"""
import hashlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.crud import (
    batch_delete_files,
    create_file_record,
    ensure_file_category_by_name,
    query_files_for_batch,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_file(db, project_id=1, created_by=None, category_id=None,
              name="a.png", content_type="image/png", created_at=None, sha=None):
    sha = sha or hashlib.sha256(name.encode()).hexdigest()
    return create_file_record(
        db, project_id=project_id, name=name, original_name=name,
        content_type=content_type, size=len(name), sha256=sha,
        storage_path=f"files/{sha[:2]}/{sha}", category_id=category_id, user_id=created_by,
    )


# ============ ensure_file_category_by_name：get-or-create ============

class TestEnsureCategory:
    def test_creates_top_level_category(self, db):
        cat = ensure_file_category_by_name(db, project_id=1, name="UI执行截图", user_id=7)
        assert cat.id is not None
        assert cat.project_id == 1
        assert cat.parent_id is None
        assert cat.name == "UI执行截图"
        assert cat.created_by == 7

    def test_idempotent_returns_same_row(self, db):
        first = ensure_file_category_by_name(db, project_id=1, name="UI执行截图")
        second = ensure_file_category_by_name(db, project_id=1, name="UI执行截图", user_id=9)
        assert first.id == second.id
        # 已存在时不重复建：created_by 保持首次值
        assert second.created_by is None
        assert db.query(models.FileCategory).count() == 1

    def test_project_isolation(self, db):
        cat_a = ensure_file_category_by_name(db, project_id=1, name="UI执行截图")
        cat_b = ensure_file_category_by_name(db, project_id=2, name="UI执行截图")
        assert cat_a.id != cat_b.id
        assert db.query(models.FileCategory).count() == 2


# ============ query_files_for_batch：条件 AND 组合 ============

class TestQueryForBatch:
    def _base(self):
        return schemas.FileBatchDeleteRequest(project_id=1, ids=[1])

    def test_project_strong_scope(self, db):
        _add_file(db, project_id=1, name="p1.png")
        _add_file(db, project_id=2, name="p2.png")
        data = schemas.FileBatchDeleteRequest(project_id=1, name_contains="p")
        rows = query_files_for_batch(db, data)
        assert [r.name for r in rows] == ["p1.png"]

    def test_ids_filter(self, db):
        f1 = _add_file(db, name="f1.png")
        _add_file(db, name="f2.png")
        rows = query_files_for_batch(db, schemas.FileBatchDeleteRequest(project_id=1, ids=[f1.id]))
        assert [r.name for r in rows] == ["f1.png"]

    def test_name_and_type_combined(self, db):
        _add_file(db, name="ui_g5_x.png", content_type="image/png")
        _add_file(db, name="ui_g5_y.txt", content_type="text/plain")
        _add_file(db, name="report.png", content_type="image/png")
        data = schemas.FileBatchDeleteRequest(
            project_id=1, name_contains="ui_g5_", content_type_prefix="image/")
        rows = query_files_for_batch(db, data)
        assert [r.name for r in rows] == ["ui_g5_x.png"]

    def test_created_by_and_time_range(self, db):
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        old = _add_file(db, name="old.png", created_by=7)
        old.created_at = t0 - timedelta(days=1)
        new = _add_file(db, name="new.png", created_by=7)
        new.created_at = t0
        other = _add_file(db, name="other.png", created_by=8)
        other.created_at = t0
        db.commit()
        data = schemas.FileBatchDeleteRequest(
            project_id=1, created_by=7,
            created_after=t0 - timedelta(hours=1), created_before=t0 + timedelta(hours=1))
        rows = query_files_for_batch(db, data)
        assert [r.name for r in rows] == ["new.png"]

    def test_category_filter(self, db):
        cat = ensure_file_category_by_name(db, project_id=1, name="UI执行截图")
        _add_file(db, name="shot.png", category_id=cat.id)
        _add_file(db, name="plain.png", category_id=None)
        data = schemas.FileBatchDeleteRequest(project_id=1, category_id=cat.id)
        rows = query_files_for_batch(db, data)
        assert [r.name for r in rows] == ["shot.png"]


# ============ batch_delete_files：引用计数语义 ============

class TestBatchDelete:
    def test_ref1_collects_physical_path(self, db):
        f = _add_file(db, name="single.png")
        result = batch_delete_files(db, [f])
        assert result["deleted"] == 1
        assert result["physical_paths"] == [f.storage_path]
        assert db.query(models.TestFile).count() == 0

    def test_ref2_keeps_physical_path(self, db):
        f = _add_file(db, name="dup.png")
        f.ref_count = 2
        db.commit()
        result = batch_delete_files(db, [f])
        assert result["deleted"] == 1
        assert result["physical_paths"] == []
        assert db.query(models.TestFile).count() == 0

    def test_empty_rows(self, db):
        assert batch_delete_files(db, []) == {"deleted": 0, "physical_paths": []}


# ============ save_screenshot_file：归档分类 + 执行人 + 去重回填 ============

class TestSaveScreenshot:
    def _save(self, db, monkeypatch, tmp_path, content=b"png-bytes", **kw):
        from app.services import file_helpers
        monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
        from app.services.ui_runtime import save_screenshot_file
        return save_screenshot_file(db, 1, content, kw.pop("name", "ui_n1.png"), **kw)

    def test_archives_to_ui_category_with_executor(self, db, monkeypatch, tmp_path):
        from app.services import file_helpers
        fid = self._save(db, monkeypatch, tmp_path, user_id=7)
        assert fid is not None
        obj = db.get(models.TestFile, fid)
        assert obj.content_type == "image/png"
        assert obj.created_by == 7  # 上传人 = 执行人
        assert obj.category_id is not None  # 不落未分组
        cat = db.get(models.FileCategory, obj.category_id)
        assert cat.name == "UI执行截图"
        assert cat.parent_id is None
        # 物理文件真实落盘（重定向到 tmp）
        physical = file_helpers.resolve_physical_path(obj.storage_path)
        assert physical.exists()
        assert physical.read_bytes() == b"png-bytes"

    def test_explicit_category_respected(self, db, monkeypatch, tmp_path):
        cat = ensure_file_category_by_name(db, project_id=1, name="指定分类")
        fid = self._save(db, monkeypatch, tmp_path, user_id=1, category_id=cat.id)
        obj = db.get(models.TestFile, fid)
        assert obj.category_id == cat.id
        assert db.query(models.FileCategory).count() == 1  # 未再自动建「UI执行截图」

    def test_no_user_records_null(self, db, monkeypatch, tmp_path):
        fid = self._save(db, monkeypatch, tmp_path)
        obj = db.get(models.TestFile, fid)
        assert obj.created_by is None

    def test_invalid_input_returns_none(self, db, monkeypatch, tmp_path):
        assert self._save(db, monkeypatch, tmp_path, content=b"") is None
        assert save_screenshot_none_project(db, monkeypatch, tmp_path) is None

    def test_dedupe_backfills_legacy_record(self, db, monkeypatch, tmp_path):
        content = b"same-content"
        sha = hashlib.sha256(content).hexdigest()
        # 早期截图：无分类、无上传人、同内容
        legacy = create_file_record(
            db, project_id=1, name="legacy.png", original_name="legacy.png",
            content_type="image/png", size=len(content), sha256=sha,
            storage_path=f"files/{sha[:2]}/{sha}", category_id=None, user_id=None)
        fid = self._save(db, monkeypatch, tmp_path, content=content, user_id=7)
        assert fid == legacy.id
        db.refresh(legacy)
        assert legacy.ref_count == 2
        assert legacy.category_id is not None  # 回填归档分类
        cat = db.get(models.FileCategory, legacy.category_id)
        assert cat.name == "UI执行截图"
        assert legacy.created_by == 7  # 回填执行人
        assert db.query(models.TestFile).count() == 1  # 未新建重复记录


def save_screenshot_none_project(db, monkeypatch, tmp_path):
    from app.services import file_helpers
    monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
    from app.services.ui_runtime import save_screenshot_file
    return save_screenshot_file(db, None, b"x", "x.png", user_id=7)
