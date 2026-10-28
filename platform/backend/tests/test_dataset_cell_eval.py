# -*- coding: utf-8 -*-
"""数据集单元格生成规则求值（2026-10-28 数据收口）：
- evaluate_dataset_cell：整串 ${函数(...)} 求值，其余原样
- ExecutionContext 注入：${sheet.字段} 与裸 ${字段} 取到同一个生成值
  （选中 sheet 双通道注入只求值一次——generate_bl_no 含随机段）
"""
from app.engine.context import ExecutionContext
from app.engine.expression import ExpressionEngine, evaluate_dataset_cell


class TestEvaluateDatasetCell:
    def test_whole_fn_call_evaluated(self):
        v = evaluate_dataset_cell("${generate_bl_no(prefix='UIBL')}")
        assert isinstance(v, str) and v.startswith("UIBL") and v != "${generate_bl_no(prefix='UIBL')}"

    def test_constant_untouched(self):
        assert evaluate_dataset_cell("海运费") == "海运费"
        assert evaluate_dataset_cell("") == ""
        assert evaluate_dataset_cell(800) == 800
        assert evaluate_dataset_cell(None) is None

    def test_reference_untouched(self):
        """${sheet.字段} 引用不是生成规则：不求值（引用语义留给步骤表达式）"""
        v = "${编辑自营项目.bl_no1}"
        assert evaluate_dataset_cell(v) == v

    def test_embedded_expression_untouched(self):
        v = "ABC-${generate_bl_no(prefix='X')}"
        assert evaluate_dataset_cell(v) == v

    def test_unknown_fn_untouched(self):
        """未知名不是生成规则（可能是引用名），不求值"""
        v = "${nope_fn(a=1)}"
        assert evaluate_dataset_cell(v) == v

    def test_bad_args_untouched(self):
        """参数坏（函数抛错）保留原文：执行时填出原文即暴露，可回数据集修。
        _parse_kwargs 不抛错（宽松转字符串），坏参要靠函数自己抛——
        date_add(base=非日期) fromisoformat ValueError 即真抛错样例"""
        v = "${date_add(base='bad-date')}"
        assert evaluate_dataset_cell(v) == v


class TestContextInjection:
    def _ctx(self):
        sheet = {
            "label": "添加委托订单",
            "data": {
                "bl_no": "${generate_bl_no(prefix='UIBL')}",
                "customer_id": "C001",
                "nodes": {"n1": {"params": {}}},
            },
        }
        # 双通道：dataset_vars = 选中 sheet 的 data（执行展开计划的构造方式）
        return ExecutionContext(dataset_vars=dict(sheet["data"]), dataset_sheets=[sheet])

    def test_bare_ref_gets_generated_value(self):
        ctx = self._ctx()
        val = ExpressionEngine(ctx)._eval_str("${bl_no}")
        assert isinstance(val, str) and val.startswith("UIBL") and "${" not in val

    def test_sheet_ref_same_value_as_bare_ref(self):
        """${label.字段} 与裸 ${字段} 同一单元格 → 同一个生成值（只求值一次）"""
        ctx = self._ctx()
        engine = ExpressionEngine(ctx)
        bare = engine._eval_str("${bl_no}")
        named = engine._eval_str("${添加委托订单.bl_no}")
        assert bare == named

    def test_constant_cell_injected(self):
        ctx = self._ctx()
        assert ExpressionEngine(ctx)._eval_str("${customer_id}") == "C001"

    def test_nodes_not_injected(self):
        ctx = self._ctx()
        assert ExpressionEngine(ctx)._eval_str("${nodes}") == "${nodes}"

    def test_distinct_fields_generate_independently(self):
        """同规则不同字段各自求值（两条提单号互不相同）"""
        sheet = {"label": "S", "data": {
            "a": "${generate_bl_no(prefix='X')}",
            "b": "${generate_bl_no(prefix='X')}",
        }}
        ctx = ExecutionContext(dataset_vars=dict(sheet["data"]), dataset_sheets=[sheet])
        engine = ExpressionEngine(ctx)
        assert engine._eval_str("${a}") != engine._eval_str("${b}")

    def test_selected_sheet_evaluated_once_across_channels(self):
        """选中 sheet 在 sheets 与 dataset_vars 都出现：两通道值一致"""
        data = {"bl_no": "${generate_bl_no(prefix='Y')}"}
        ctx = ExecutionContext(dataset_vars=dict(data),
                               dataset_sheets=[{"label": "选中", "data": dict(data)}])
        engine = ExpressionEngine(ctx)
        assert engine._eval_str("${bl_no}") == engine._eval_str("${选中.bl_no}")
