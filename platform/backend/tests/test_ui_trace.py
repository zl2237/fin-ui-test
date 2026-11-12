"""Playwright trace（browser_config.trace）单测：收集判定矩阵 + 落文件中心。

不启动真浏览器：FakeContext 替身记录 tracing.start/stop 调用（stop(path=) 会
写真 zip 文件），UiRuntime 手工构造注入替身 context；文件中心走真 SQLite 内存库
（物理落盘 monkeypatch UPLOAD_ROOT 重定向 tmp，同 test_files_center 模式）。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.services import ui_runtime as ur
from app.services.file_helpers import resolve_physical_path


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


class FakeTracing:
    """tracing 替身：stop(path=) 写真 zip 字节（可校验落盘内容），调用全记录。"""

    def __init__(self, zip_bytes=b"PK-trace-zip"):
        self.zip_bytes = zip_bytes
        self.calls: list = []  # ("start",) / ("stop", path|None)

    def start(self, **kwargs):
        self.calls.append(("start",))

    def stop(self, path=None):
        self.calls.append(("stop", path))
        if path:
            with open(path, "wb") as fh:
                fh.write(self.zip_bytes)


class FakeContext:
    def __init__(self, tracing: FakeTracing):
        self.tracing = tracing

    def close(self):
        pass


def _runtime(db, trace: str, tracing: FakeTracing, *, execution_id=88):
    """手工构造 UiRuntime（不起浏览器），browser_config.trace 注入 + 替身 context。"""
    env = models.Environment(name="test", base_url="http://t",
                             browser_config={"trace": trace})
    db.add(env)
    db.commit()
    rt = ur.UiRuntime(db=db, env=env, context=None, project_id=1, execution_id=execution_id)
    rt._context = FakeContext(tracing)
    return rt


def _trace_record(db):
    """落盘的 trace 记录（按分类「UI执行Trace」查）"""
    cat = (db.query(models.FileCategory)
           .filter(models.FileCategory.name == "UI执行Trace").first())
    return cat, (db.query(models.TestFile).filter(
        models.TestFile.category_id == cat.id).all() if cat else [])


# ============ 收集判定矩阵（on_failure / always / off × 终态） ============

class TestCollectTraceDecision:
    def test_off_never_started(self, db):
        tracing = FakeTracing()
        rt = _runtime(db, "off", tracing)
        rt.final_status = "failed"
        rt._collect_trace()
        assert tracing.calls == []  # 未开启：start/stop 都不调
        assert rt.trace_file_id is None

    def test_on_failure_success_discards(self, db):
        tracing = FakeTracing()
        rt = _runtime(db, "on_failure", tracing)
        rt.final_status = "success"
        rt._collect_trace()
        # 成功丢弃：stop 不带 path
        assert tracing.calls == [("stop", None)]
        assert rt.trace_file_id is None

    @pytest.mark.parametrize("status", ["failed", "terminated"])
    def test_on_failure_bad_status_keeps(self, db, monkeypatch, tmp_path, status):
        from app.services import file_helpers
        monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
        tracing = FakeTracing()
        rt = _runtime(db, "on_failure", tracing)
        rt.final_status = status
        rt._collect_trace()
        assert rt.trace_file_id is not None
        stop_calls = [c for c in tracing.calls if c[0] == "stop"]
        assert stop_calls and stop_calls[0][1]  # stop(path=...) 落盘

    def test_always_keeps_even_success(self, db, monkeypatch, tmp_path):
        from app.services import file_helpers
        monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
        tracing = FakeTracing()
        rt = _runtime(db, "always", tracing)
        rt.final_status = "success"
        rt._collect_trace()
        assert rt.trace_file_id is not None

    def test_missing_final_status_keeps(self, db, monkeypatch, tmp_path):
        """终态未注入（异常兜底路径，close 被独立调用）：宁留勿丢"""
        from app.services import file_helpers
        monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
        tracing = FakeTracing()
        rt = _runtime(db, "on_failure", tracing)  # final_status 保持 None
        rt._collect_trace()
        assert rt.trace_file_id is not None

    def test_idempotent_second_call_noop(self, db, monkeypatch, tmp_path):
        from app.services import file_helpers
        monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
        tracing = FakeTracing()
        rt = _runtime(db, "always", tracing)
        rt.final_status = "success"
        rt._collect_trace()
        n_calls = len(tracing.calls)
        rt._collect_trace()  # 重复收尾（close 幂等语义）：不再 stop
        assert len(tracing.calls) == n_calls

    def test_trace_stop_failure_not_fatal(self, db):
        """tracing.stop 抛异常：只打日志，不向外抛（附加产物失败安全）"""
        class BrokenTracing(FakeTracing):
            def stop(self, path=None):
                raise RuntimeError("boom")

        rt = _runtime(db, "always", BrokenTracing())
        rt.final_status = "success"
        rt._collect_trace()  # 不抛即通过
        assert rt.trace_file_id is None


# ============ 落文件中心（分类/字节/命名/执行人） ============

class TestTraceArchive:
    def test_archives_to_trace_category(self, db, monkeypatch, tmp_path):
        from app.services import file_helpers
        monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
        tracing = FakeTracing(zip_bytes=b"PK-TRACE-CONTENT")
        rt = _runtime(db, "on_failure", tracing, execution_id=4321)
        rt.final_status = "failed"
        rt._collect_trace()

        assert rt.trace_file_id is not None
        cat, files = _trace_record(db)
        assert cat is not None and cat.name == "UI执行Trace"
        assert len(files) == 1
        rec = files[0]
        assert rec.name == "exec_4321.zip"
        assert rec.content_type == "application/zip"
        assert rec.size == len(b"PK-TRACE-CONTENT")
        # 物理文件真实落盘且内容一致
        physical = resolve_physical_path(rec.storage_path)
        assert physical.exists() and physical.read_bytes() == b"PK-TRACE-CONTENT"

    def test_video_user_id_used_as_archiver(self, db, monkeypatch, tmp_path):
        """trace 归档执行人沿用 video_user_id（dag_executor 注入的执行人）"""
        from app.services import file_helpers
        monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
        tracing = FakeTracing()
        rt = _runtime(db, "always", tracing)
        rt.video_user_id = 9
        rt.final_status = "success"
        rt._collect_trace()
        rec = db.query(models.TestFile).get(rt.trace_file_id)
        assert rec.created_by == 9

    def test_dedup_by_sha(self, db, monkeypatch, tmp_path):
        """同内容 trace 二次归档：sha 去重走既有记录（ref_count +1），不重复落盘"""
        from app.services import file_helpers
        monkeypatch.setattr(file_helpers, "UPLOAD_ROOT", str(tmp_path))
        tracing = FakeTracing(zip_bytes=b"same-bytes")
        rt1 = _runtime(db, "always", tracing, execution_id=1)
        rt1.final_status = "success"
        rt1._collect_trace()
        rt2 = _runtime(db, "always", tracing, execution_id=2)
        rt2.final_status = "success"
        rt2._collect_trace()
        assert rt1.trace_file_id == rt2.trace_file_id
        _, files = _trace_record(db)
        assert len(files) == 1 and files[0].ref_count == 2


# ============ save_trace_file 直测（与 save_video_file 同构的兜底） ============

class TestSaveTraceFile:
    def test_no_project_returns_none(self, db):
        assert ur.save_trace_file(db, None, b"x", "t.zip") is None

    def test_empty_bytes_returns_none(self, db):
        assert ur.save_trace_file(db, 1, b"", "t.zip") is None
