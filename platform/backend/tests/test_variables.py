# -*- coding: utf-8 -*-
"""变量注册表 + 参数拓扑排序单测（新参数模型地基）。"""
import pytest

from app.engine.variables import (
    SUITE_NS,
    CycleError,
    ReferenceError,
    VariableRegistry,
    extract_refs,
    order_params,
    split_ref,
)


class TestVariableRegistry:
    def test_namespaced_isolation(self):
        """同名冲突三场景根治：不同节点同名变量互不覆盖。"""
        r = VariableRegistry()
        r.write("n_create", "order_id", 1)
        r.write("n_distribute", "order_id", "ORD-2")  # 同名异值异型
        r.write("n_stash", "order_id", {"nested": {"a": 1}})  # 同名嵌套层级不一致
        assert r.read("n_create", "order_id") == 1
        assert r.read("n_distribute", "order_id") == "ORD-2"
        assert r.read("n_stash", "order_id") == {"nested": {"a": 1}}

    def test_resolve_missing_raises(self):
        """取不到值必须抛错——旧引擎静默保留占位符的行为已废止。"""
        r = VariableRegistry()
        with pytest.raises(ReferenceError):
            r.resolve({"node_id": "n_a", "var_path": "x"})
        with pytest.raises(ReferenceError):
            r.resolve({"node_id": "", "var_path": "x"})

    def test_resolve_ok(self):
        r = VariableRegistry()
        r.write("n_a", "bl_no", "SMOKE-1")
        assert r.resolve({"node_id": "n_a", "var_path": "bl_no"}) == "SMOKE-1"

    def test_suite_pseudo_ns(self):
        """套件伪命名空间批量注入（API 参数侧平铺注入已退役；__dataset__ 仅承载
        legacy 平铺行键，见 TestDatasetFlatInjection）。"""
        r = VariableRegistry()
        r.inject(SUITE_NS, {"pol": "ANTING", "pod": "AOSHANWEI"})
        assert r.vars_of(SUITE_NS) == {"pol": "ANTING", "pod": "AOSHANWEI"}
        assert r.read(SUITE_NS, "pol") == "ANTING"

    def test_inject_and_write_no_cross_talk(self):
        r = VariableRegistry()
        r.inject("__suite__", {"a": 1})
        r.write("n1", "a", 2)
        assert r.read("__suite__", "a") == 1
        assert r.read("n1", "a") == 2

    def test_null_value_resolved_raises(self):
        r = VariableRegistry()
        r.write("n1", "x", None)
        with pytest.raises(ReferenceError):
            r.resolve({"node_id": "n1", "var_path": "x"})


class TestPlaceholder:
    def test_split_ref(self):
        assert split_ref("n_create.order_id") == ("n_create", "order_id")
        assert split_ref("__suite__.to_customer.a") == ("__suite__", "to_customer.a")

    def test_extract_refs(self):
        sql = "SELECT 1 FROM t WHERE bl_no={{n_create.bl_no}} AND id={{__suite__.main_id}}"
        assert extract_refs(sql) == [("n_create", "bl_no"), ("__suite__", "main_id")]

    def test_old_syntax_not_matched(self):
        """旧 ${xxx} 语法不再是占位符——迁移后残留应被校验拦截。"""
        assert extract_refs("SELECT ${x}") == []


class TestOrderParams:
    def test_no_deps_keeps_order(self):
        params = {"a": {"source": "constant", "value": 1}, "b": {"source": "constant", "value": 2}}
        assert order_params(params, "n1") == ["a", "b"]

    def test_func_arg_dep_on_sql_param(self):
        """B(func upper) 引用本节点 SQL 参数 A → A 先解析。"""
        params = {
            "b": {"source": "func", "func": "upper", "args": [
                {"kind": "ref", "node_id": "n1", "var_path": "a"}]},
            "a": {"source": "sql", "sql": "SELECT id FROM t"},
        }
        assert order_params(params, "n1") == ["a", "b"]

    def test_sql_placeholder_dep(self):
        params = {
            "x": {"source": "sql", "sql": "SELECT {{n1.y}} FROM t"},
            "y": {"source": "sql", "sql": "SELECT 1"},
        }
        assert order_params(params, "n1") == ["y", "x"]

    def test_cross_node_ref_not_local_dep(self):
        """引用前置节点变量不构成本节点参数间依赖。"""
        params = {
            "b": {"source": "func", "func": "upper", "args": [
                {"kind": "ref", "node_id": "n_prev", "var_path": "a"}]},
        }
        assert order_params(params, "n1") == ["b"]

    def test_cycle_raises(self):
        params = {
            "a": {"source": "sql", "sql": "SELECT {{n1.b}}"},
            "b": {"source": "sql", "sql": "SELECT {{n1.a}}"},
        }
        with pytest.raises(CycleError):
            order_params(params, "n1")


class TestDatasetFlatInjection:
    """legacy 平铺数据行键 → __dataset__ 伪命名空间（UI 步骤 ${} 数据来源）。

    背景：参数模型 v2 退役了 API 侧平铺解析，但 UI 步骤自由文本 ${} 走平铺池
    （expression.py），legacy 数据集行（如 {"bl_no": ...}）此前被静默丢弃——
    用例检索字面量 '${bl_no}'（case#278/282 实证）。"""

    def test_flat_row_keys_resolve_in_expression(self):
        from app.engine.context import ExecutionContext
        from app.engine.expression import ExpressionEngine

        ctx = ExecutionContext(dataset_vars={"bl_no": "GOSUQIN9055623"})
        eng = ExpressionEngine(ctx)
        assert eng.evaluate("${bl_no}") == "GOSUQIN9055623"
        assert eng.evaluate("prefix-${bl_no}") == "prefix-GOSUQIN9055623"

    def test_nodes_wrapper_not_injected(self):
        """v2 格式 {"nodes": {...}} 的行不是平铺变量——不进注册表。"""
        from app.engine.context import ExecutionContext
        from app.engine.expression import ExpressionEngine

        ctx = ExecutionContext(dataset_vars={"nodes": {"n1": {"params": {}}}})
        eng = ExpressionEngine(ctx)
        assert eng.evaluate("${nodes}") == "${nodes}"  # 未定义保留占位符

    def test_mixed_row_only_flat_keys_injected(self):
        from app.engine.context import ExecutionContext
        from app.engine.expression import ExpressionEngine

        ctx = ExecutionContext(dataset_vars={"nodes": {"n1": {}}, "bl_no": "X1"})
        assert ExpressionEngine(ctx).evaluate("${bl_no}") == "X1"

    def test_priority_suite_overrides_dataset(self):
        """平铺池后写命名空间优先：套件注入 > 数据集行。"""
        from app.engine.context import ExecutionContext
        from app.engine.expression import ExpressionEngine

        ctx = ExecutionContext(dataset_vars={"bl_no": "FROM-DATASET"},
                               suite_vars={"bl_no": "FROM-SUITE"})
        assert ExpressionEngine(ctx).evaluate("${bl_no}") == "FROM-SUITE"

    def test_priority_runtime_overrides_dataset(self):
        """运行时产出（后置提取写节点命名空间）覆盖数据集行同名键。"""
        from app.engine.context import ExecutionContext
        from app.engine.expression import ExpressionEngine

        ctx = ExecutionContext(dataset_vars={"bl_no": "FROM-DATASET"})
        ctx.registry.write("n1", "bl_no", "EXTRACTED")
        assert ExpressionEngine(ctx).evaluate("${bl_no}") == "EXTRACTED"


class TestAllSheetsInjection:
    """全 sheet 注入（2026-10-27 sheet 化）：dataset_sheets 各 sheet 以 label
    为命名空间注入 → ${sheet.字段} 精确引用；注入顺序契约见 context.py。"""

    def _ctx(self, **kw):
        from app.engine.context import ExecutionContext
        return ExecutionContext(**kw)

    def _eval(self, ctx, text):
        from app.engine.expression import ExpressionEngine
        return ExpressionEngine(ctx).evaluate(text)

    def test_named_sheet_ref_hits(self):
        """${sheet.字段} 非选中 sheet 也能取到（首点切 ns 查法）"""
        ctx = self._ctx(
            dataset_vars={"nodes": {}, "bl_no": "B2"},
            dataset_sheets=[
                {"label": "正常单", "data": {"nodes": {}, "bl_no": "B1", "seq": "S1"}},
                {"label": "退款单", "data": {"nodes": {}, "bl_no": "B2"}},
            ])
        assert self._eval(ctx, "${正常单.bl_no}") == "B1"
        assert self._eval(ctx, "${正常单.seq}") == "S1"
        assert self._eval(ctx, "${退款单.bl_no}") == "B2"

    def test_bare_ref_prefers_chosen_sheet(self):
        """裸 ${字段} 同名冲突：选中 sheet（__dataset__ 数据集类注入最后）胜"""
        ctx = self._ctx(
            dataset_vars={"bl_no": "CHOSEN"},
            dataset_sheets=[
                {"label": "s1", "data": {"bl_no": "OTHER"}},
                {"label": "s2", "data": {"bl_no": "OTHER2"}},
            ])
        assert self._eval(ctx, "${bl_no}") == "CHOSEN"

    def test_suite_still_overrides_sheets(self):
        """套件注入仍在数据集类注入之后：suite > sheet 具名注入"""
        ctx = self._ctx(
            dataset_vars={"bl_no": "CHOSEN"},
            suite_vars={"bl_no": "SUITE"},
            dataset_sheets=[{"label": "s1", "data": {"bl_no": "OTHER"}}])
        assert self._eval(ctx, "${bl_no}") == "SUITE"

    def test_label_collides_node_id_runtime_wins(self):
        """label 与 node_id 撞名：ns 合并后写胜——运行时节点产出（注入后写）胜"""
        ctx = self._ctx(
            dataset_vars={"x": "DS"},
            dataset_sheets=[{"label": "n1", "data": {"x": "SHEET"}}])
        assert self._eval(ctx, "${n1.x}") == "SHEET"  # 注入期 sheet 可读
        ctx.registry.write("n1", "x", "RUNTIME")
        assert self._eval(ctx, "${n1.x}") == "RUNTIME"  # 运行时写入后覆盖

    def test_nodes_key_not_injected_into_sheet_ns(self):
        """sheet 内 "nodes" 键是节点入参配置：不注入 label 命名空间"""
        ctx = self._ctx(
            dataset_sheets=[{"label": "s1", "data": {"nodes": {"n1": {"params": {}}}, "x": 1}}])
        assert self._eval(ctx, "${s1.x}") == 1
        assert self._eval(ctx, "${s1.nodes}") == "${s1.nodes}"  # 未定义保留占位符

    def test_empty_label_sheet_skipped(self):
        """防御：无标签 sheet 跳过注入（正常路径 plan_case_expansion 恒有 label）"""
        ctx = self._ctx(dataset_sheets=[{"label": "", "data": {"x": 1}}])
        assert self._eval(ctx, "${x}") == "${x}"

    def test_unknown_sheet_ref_keeps_placeholder(self):
        """引用不存在的 sheet：宽松求值保留占位符（与现有一致）"""
        ctx = self._ctx(dataset_vars={"a": 1},
                        dataset_sheets=[{"label": "s1", "data": {"a": 1}}])
        assert self._eval(ctx, "${nope.a}") == "${nope.a}"
