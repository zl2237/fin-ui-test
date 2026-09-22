"""UI 管线集成测试（step_type=ui 分发 + ui_runtime 纯函数层）。

覆盖三层：
1. ui_runtime.build_locator / _resolve_element_spec：策略链解析（纯函数，fake page）；
2. DagExecutor UI 节点分发：注入替身 ui_runtime，验证 facts → 提取/断言/事件全链路
   （沿用 test_execute_node.py 的 FakeDb + MemorySink 接缝风格，不拉起真实浏览器）；
3. 快照配置透传：数据集 node_config_overrides 携带 step_type/ui_params。
"""
from types import SimpleNamespace
from typing import Any

import pytest

from app.engine.dag_executor import DagExecutor
from app.engine.events import StepResult
from app.services.ui_runtime import UiActionError, _resolve_element_spec, build_locator


# ---------- 替身 ----------
class FakeDb:
    """最小 Session 替身：支持 query().filter().first() 链式调用"""

    def __init__(self, first_results: list[Any] | None = None):
        self._firsts = list(first_results or [])
        self.added: list[Any] = []

    def query(self, *_a, **_kw):
        db = self

        class _Q:
            def filter(self, *a, **kw):
                return self

            def first(self):
                return db._firsts.pop(0) if db._firsts else None

        return _Q()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def refresh(self, _obj):
        pass


class MemorySink:
    def __init__(self):
        self.steps: list[StepResult] = []

    def record_step(self, result: StepResult) -> None:
        self.steps.append(result)


class FakeLocator:
    def __init__(self, tag):
        self.tag = tag


class FakePage:
    """记录各定位构造器调用，返回带标记的 FakeLocator"""

    def __init__(self):
        self.calls: list[tuple[str, Any]] = []

    def get_by_test_id(self, v):
        self.calls.append(("test_id", v))
        return FakeLocator(f"test_id:{v}")

    def get_by_label(self, v):
        self.calls.append(("label", v))
        return FakeLocator(f"label:{v}")

    def get_by_placeholder(self, v):
        self.calls.append(("placeholder", v))
        return FakeLocator(f"placeholder:{v}")

    def get_by_text(self, v, exact=False):
        self.calls.append(("text", v))
        return FakeLocator(f"text:{v}")

    def get_by_role(self, role, name=None):
        self.calls.append(("role", (role, name)))
        return FakeLocator(f"role:{role}:{name}")

    def locator(self, v):
        self.calls.append(("locator", v))
        return FakeLocator(f"locator:{v}")


class FakeUiRuntime:
    """ui_runtime 替身：不拉浏览器，动作结果可预设"""

    def __init__(self, facts: dict | None = None, error: str | None = None,
                 screenshot: bytes | None = b"\x89PNG-fake"):
        self.facts = facts if facts is not None else {
            "action": "goto", "url": "https://sut.example.com/order", "title": "订单", "status": "success",
        }
        self.error = error
        self.screenshot_bytes = screenshot
        self.closed = False
        self.received: list[dict] = []

    def run_action(self, params: dict) -> dict:
        self.received.append(params)
        if self.error:
            raise UiActionError(self.error)
        return dict(self.facts)

    def take_screenshot(self) -> bytes | None:
        return self.screenshot_bytes

    def close(self):
        self.closed = True


def _executor(db, sink, ui_runtime=None, env=None, execution_record=None) -> DagExecutor:
    env = env or SimpleNamespace(variables={}, timeout=5)
    case = SimpleNamespace(id=1, project_id=7, dag_config={"nodes": [], "edges": []})
    return DagExecutor(db, case, env, execution_record=execution_record, sink=sink, ui_runtime=ui_runtime)


def _ui_config(**over):
    base = dict(api_id=None, step_type="ui", ui_params={"action": "goto", "url": "${base}/order"},
                pre_process=None, post_extract=None, assertions=None, wait_after_ms=0)
    base.update(over)
    return SimpleNamespace(**base)


# ---------- 策略链解析 ----------
class TestBuildLocator:
    def test_priority_for_before_text(self):
        page = FakePage()
        loc = build_locator(page, {"text": "提单号", "for": "bl_no", "full_xpath": "//div"})
        # for 语义与原框架一致：label[for=X] 后兄弟容器内首个 input/textarea
        # （被测系统 label 的 for 值并非真实 DOM id，[id=X] 直查定位不到——实证）
        expected = ("locator",
                    "xpath=(//label[@for='bl_no']/following-sibling::div"
                    "//*[name()='input' or name()='textarea'])[1]")
        assert loc.tag == "locator:" + expected[1]
        assert page.calls[0] == expected

    def test_button_maps_to_role(self):
        page = FakePage()
        loc = build_locator(page, {"button": "保存", "full_xpath": "//button"})
        assert loc.tag == "role:button:保存"

    def test_full_xpath_fallback(self):
        page = FakePage()
        loc = build_locator(page, {"full_xpath": "//*[@id='app']/div[3]"})
        assert loc.tag == "locator:xpath=//*[@id='app']/div[3]"

    def test_empty_strategies_raise(self):
        with pytest.raises(UiActionError):
            build_locator(FakePage(), {})

    def test_unknown_only_strategies_raise(self):
        with pytest.raises(UiActionError):
            build_locator(FakePage(), {"origin": "page.locator('#x')"})


class TestResolveElementSpec:
    def test_inline_strategy_expands(self):
        spec = _resolve_element_spec(None, {"strategy": "css", "value": "#save"})
        assert spec == {"css": "#save"}

    def test_invalid_inline_strategy_raises(self):
        with pytest.raises(UiActionError):
            _resolve_element_spec(None, {"strategy": "qrcode", "value": "x"})

    def test_strategies_dict_passthrough(self):
        raw = {"text": "保存", "full_xpath": "//x"}
        assert _resolve_element_spec(None, {"strategies": raw}) == raw

    def test_missing_element_raises(self):
        with pytest.raises(UiActionError):
            _resolve_element_spec(None, None)


# ---------- UI 节点分发 ----------
class TestUiNodeDispatch:
    def test_ui_node_success_with_extract_and_assertion(self):
        """ui 节点成功：facts 进 response_body，提取/断言复用 API 管线，事件带 step_kind=ui"""
        config = _ui_config(
            post_extract=[{"name": "page_url", "json_path": "$.url"}],
            assertions=[{"type": "json_path_contains", "path": "$.url", "expected": "/order"}],
        )
        db = FakeDb(first_results=[config])
        sink = MemorySink()
        runtime = FakeUiRuntime()
        ex = _executor(db, sink, ui_runtime=runtime)

        passed, wait_ms = ex._execute_node(100, "n1", {"id": "n1", "data": {"label": "打开订单页"}})

        assert passed is True
        assert wait_ms == 0
        ev = sink.steps[0]
        assert ev.status == "success"
        assert ev.step_kind == "ui"
        assert ev.api_method == "UI"
        assert ev.api_name == "打开订单页"
        assert ev.api_path == "https://sut.example.com/order"
        assert ev.response_body["url"] == "https://sut.example.com/order"
        # 提取变量入上下文池，供后续节点 ${page_url} 引用
        assert ex.context.extracted["page_url"] == "https://sut.example.com/order"
        # 断言对 facts 求值通过
        assert ev.assertions[0].passed is True

    def test_ui_node_failure_records_error_and_screenshot(self, monkeypatch):
        """ui 动作失败：failed 事件携带 error，on_failure 策略触发截图落库"""
        import app.services.ui_runtime as uirt

        saved: list[tuple] = []
        monkeypatch.setattr(uirt, "save_screenshot_file",
                            lambda db, pid, png, name, user_id=None, category_id=None:
                            saved.append((pid, png, name, user_id, category_id)) or 55)

        config = _ui_config()
        db = FakeDb(first_results=[config])
        sink = MemorySink()
        runtime = FakeUiRuntime(error="定位超时: bl_no_input")
        # 预建执行记录带执行人：截图上传人记为执行人（created_by）
        record = SimpleNamespace(created_by=3)
        ex = _executor(db, sink, ui_runtime=runtime, execution_record=record)

        passed, _ = ex._execute_node(100, "n1", {"id": "n1"})

        assert passed is False
        ev = sink.steps[0]
        assert ev.status == "failed"
        assert "定位超时" in str(ev.response_body["error"])
        assert ev.step_kind == "ui"
        # 截图已按 (project_id, png, name) 落文件中心，id 进事件；
        # 上传人 = 执行人 3；未指定分类时传 None（由 save 侧归到「UI执行截图」）
        assert ev.screenshot_file_id == 55
        assert saved and saved[0] == (7, runtime.screenshot_bytes, saved[0][2], 3, None)

    def test_ui_node_success_no_screenshot_by_default(self, monkeypatch):
        """on_failure 默认策略下成功步骤不截图"""
        import app.services.ui_runtime as uirt

        called = []
        monkeypatch.setattr(uirt, "save_screenshot_file",
                            lambda *a, **kw: called.append(1) or 1)

        config = _ui_config()
        db = FakeDb(first_results=[config])
        sink = MemorySink()
        ex = _executor(db, sink, ui_runtime=FakeUiRuntime())

        passed, _ = ex._execute_node(100, "n1", {"id": "n1"})

        assert passed is True
        assert called == []
        assert sink.steps[0].screenshot_file_id is None

    def test_ui_node_needs_no_api_definition(self):
        """ui 节点不查 ApiDefinition：FakeDb 只弹一次 config，无第二次查询也不报错"""
        config = _ui_config()
        db = FakeDb(first_results=[config])
        sink = MemorySink()
        ex = _executor(db, sink, ui_runtime=FakeUiRuntime())

        passed, _ = ex._execute_node(100, "n1", {"id": "n1"})

        assert passed is True
        assert sink.steps[0].api_method == "UI"

    def test_api_node_without_step_type_attr_still_works(self):
        """历史配置（SimpleNamespace 无 step_type 属性）走 API 分支不受分发切口影响"""
        config = SimpleNamespace(api_id=None, pre_process=None, post_extract=None,
                                 assertions=None, wait_after_ms=0)
        db = FakeDb(first_results=[config])  # 无 api → 失败步骤（历史行为）
        sink = MemorySink()
        ex = _executor(db, sink)

        passed, _ = ex._execute_node(100, "n1", {"id": "n1"})

        assert passed is False
        ev = sink.steps[0]
        assert ev.step_kind == "api"
        assert "未绑定接口" in str(ev.response_body)


class TestSnapshotCarriesUiFields:
    def test_node_config_overrides_include_step_type_and_ui_params(self):
        """数据集快照命中 ui 节点：step_type/ui_params 整块替换生效"""
        ex = _executor(FakeDb(), MemorySink())
        ex.node_config_overrides = {
            "n1": {"step_type": "ui", "ui_params": {"action": "click", "element": {"strategy": "text", "value": "保存"}},
                   "api_id": None, "pre_process": [], "post_extract": [], "assertions": [], "wait_after_ms": 100},
        }
        snap = ex._resolve_node_config("n1")
        assert snap.step_type == "ui"
        assert snap.ui_params["action"] == "click"
        assert snap.wait_after_ms == 100

    def test_snapshot_defaults_to_api(self):
        """旧数据集快照无 step_type 字段：默认回落 api（向后兼容）"""
        ex = _executor(FakeDb(), MemorySink())
        ex.node_config_overrides = {"n1": {"api_id": 10}}
        snap = ex._resolve_node_config("n1")
        assert snap.step_type == "api"
        assert snap.ui_params == {}


class TestUiRuntimeLifecycle:
    def test_close_is_idempotent_and_marks_closed(self):
        runtime = FakeUiRuntime()
        runtime.close()
        runtime.close()
        assert runtime.closed is True

    def test_missing_action_raises_action_error(self):
        from app.services.ui_runtime import UiRuntime

        env = SimpleNamespace(variables={}, timeout=5, base_url="https://sut.example.com",
                              browser_config={}, id=2)
        runtime = UiRuntime(db=FakeDb(), env=env, context=SimpleNamespace(extracted={}),
                            project_id=1)
        with pytest.raises(UiActionError):
            runtime.run_action({})
