# -*- coding: utf-8 -*-
"""保存校验器单测：四来源参数模型静态完整性。"""
import pytest

from app.engine.validation import validate_case_configs, validate_ui_step_data_sources

DAG = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": [{"source": "n1", "target": "n2"}]}


def n1_config(**kw):
    base = {"node_id": "n1", "params": {},
            "post_extract": [{"name": "order_id", "source": "response", "json_path": "$.data.id"}],
            "assertions": []}
    base.update(kw)
    return base


class TestPass:
    def test_ok_config(self):
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {"bl_no": {"source": "func", "func": "generate_bl_no", "args": []}}}),
            {"node_id": "n2", "params": {"body": {"oid": {"source": "ref", "node_id": "n1", "var_path": "order_id"}}},
             "post_extract": [], "assertions": []},
        ])
        assert errs == []

    def test_suite_ref_allowed(self):
        """__suite__ 白名单运行期注入，保存期放行（__dataset__ 平铺键已退役）"""
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {"pol": {"source": "ref", "node_id": "__suite__", "var_path": "pol"}}}),
        ])
        assert errs == []

    def test_constant_null_value_allowed(self):
        """constant 显式 null（value=None）保存期放行：发 JSON null 的合法语义
        （2026-10-10 定案；null 与缺失是两种语义，不做旧语法/来源拦截）"""
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {
                "bl_no": {"source": "constant", "value": None},
                "teu": {"source": "constant", "value": None},
            }}),
        ])
        assert errs == []

    def test_self_sql_param_ref(self):
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {
                "a": {"source": "sql", "sql": "SELECT 1"},
                "b": {"source": "func", "func": "upper", "args": [
                    {"name": "s", "kind": "ref", "node_id": "n1", "var_path": "a"}]},
            }}),
        ])
        assert errs == []

    def test_param_self_ref_to_own_param_path(self):
        """参数自引用本节点其他参数（完整路径或末段别名）：合法——
        解析顺序由 order_params 拓扑保证（成环另有用例拒绝）。"""
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {
                "user.city": {"source": "constant", "value": "SH"},
                "memo": {"source": "ref", "node_id": "n1", "var_path": "city"},  # 末段别名引用
                "tag": {"source": "ref", "node_id": "n1", "var_path": "memo"},  # 完整路径链式引用
            }}),
        ])
        assert errs == []


class TestReject:
    def test_dangling_var(self):
        errs = validate_case_configs(DAG, [
            {"node_id": "n2", "params": {"body": {"x": {"source": "ref", "node_id": "n1", "var_path": "ghost"}}},
             "post_extract": [], "assertions": []},
        ])
        assert any("悬空引用" in e for e in errs)

    def test_unknown_node(self):
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {"x": {"source": "ref", "node_id": "n9", "var_path": "a"}}}),
        ])
        assert any("不存在的节点" in e for e in errs)

    def test_posterior_node_ref(self):
        """引用拓扑后置节点必须拒绝（未执行先引用）。"""
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {"x": {"source": "ref", "node_id": "n2", "var_path": "a"}}}),
        ])
        assert any("拓扑后置" in e for e in errs)

    def test_dataset_ns_retired(self):
        """__dataset__ 伪命名空间已退役：引用它按「不存在的节点」拒绝（跨节点共享值改引用上游产出）"""
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {"x": {"source": "ref", "node_id": "__dataset__", "var_path": "nope"}}}),
        ])
        assert any("不存在的节点" in e for e in errs)

    def test_unknown_function(self):
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {"x": {"source": "func", "func": "nope", "args": []}}}),
        ])
        assert any("未知函数" in e for e in errs)

    def test_param_cycle(self):
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {
                "a": {"source": "sql", "sql": "SELECT {{n1.b}}"},
                "b": {"source": "sql", "sql": "SELECT {{n1.a}}"},
            }}),
        ])
        assert any("成环" in e for e in errs)

    def test_old_syntax_residue(self):
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {"x": {"source": "constant", "value": "${order_id}"}}}),
        ])
        assert any("旧表达式" in e for e in errs)

    def test_constant_container_embedded_sql_forbidden(self):
        """constant 容器值内嵌 SQL 来源：拒绝——读库取值须声明为独立参数。"""
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {
                "x": {"source": "constant",
                      "value": ["plain", {"source": "sql", "sql": "SELECT 1"}]},
            }}),
        ])
        assert any("容器常量内嵌 SQL 来源禁用" in e for e in errs)

    def test_param_self_ref_to_missing_var_rejected(self):
        """参数引用本节点不存在的变量：拒绝（合法集只含本节点参数路径/末段）。"""
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {
                "x": {"source": "ref", "node_id": "n1", "var_path": "ghost_var"},
            }}),
        ])
        assert any("自引用" in e and "未在本节点产出" in e for e in errs)

    def test_param_ref_to_extract_var_rejected(self):
        """参数自引用 post_extract 提名：拒绝——提取在请求后执行，
        参数解析先于提取，提取提名不在参数自引用合法集。"""
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {
                "x": {"source": "ref", "node_id": "n1", "var_path": "order_id"},
            }}),
        ])
        assert any("自引用 'order_id'" in e and "未在本节点产出" in e for e in errs)

    def test_sql_placeholder_dangling(self):
        errs = validate_case_configs(DAG, [
            n1_config(params={"body": {"x": {"source": "sql", "sql": "SELECT {{n1.ghost}}"}}}),
        ])
        assert any("ghost" in e for e in errs)


class TestUiStepDataSources:
    """UI 动作取值收口（2026-10-28）：生成/取数规则只允许写在数据集单元格。"""

    NAMED_DAG = {"nodes": [{"id": "n1", "data": {"label": "填提单号"}}], "edges": []}

    def ui_node(self, steps):
        return {"node_id": "n1", "step_type": "ui", "ui_params": {"steps": steps},
                "post_extract": [], "assertions": []}

    def test_whole_fn_call_rejected(self):
        with pytest.raises(ValueError, match="非数据集数据源"):
            validate_ui_step_data_sources(
                [self.ui_node([{"action": "fill", "value": "${generate_bl_no(prefix='UIBL')}"}])],
                self.NAMED_DAG)

    def test_embedded_fn_call_rejected(self):
        with pytest.raises(ValueError, match="内嵌了数据生成"):
            validate_ui_step_data_sources(
                [self.ui_node([{"action": "fill", "value": "BL-${uuid()}"}])], self.NAMED_DAG)

    def test_db_query_rejected(self):
        with pytest.raises(ValueError, match="非数据集数据源"):
            validate_ui_step_data_sources(
                [self.ui_node([{"action": "fill",
                                "value": "${db.query_value(sql='SELECT 1')}"}])], self.NAMED_DAG)

    def test_dataset_ref_allowed(self):
        validate_ui_step_data_sources(
            [self.ui_node([{"action": "fill", "value": "${bl_no}"},
                           {"action": "fill", "value": "${编辑自营项目.bl_no1}"}])],
            self.NAMED_DAG)

    def test_literal_and_element_locator_allowed(self):
        """字面量与 element 定位值（${变量} 求值属定位参数）不受收口约束"""
        validate_ui_step_data_sources(
            [self.ui_node([{"action": "fill", "value": "海运费"},
                           {"action": "click", "element": {"strategy": "text",
                                                           "value": "${bl_no}行内详情"}},
                           {"action": "goto", "url": "/order/detail?bl=${bl_no}"}])],
            self.NAMED_DAG)

    def test_evaluate_js_embedded_allowed(self):
        """evaluate 的 value 是 JS 脚本：内嵌 ${fn(...)} 属页面逻辑，不拦截"""
        validate_ui_step_data_sources(
            [self.ui_node([{"action": "evaluate",
                            "value": "const s=`${generate_bl_no(prefix='X')}`;return s"}])],
            self.NAMED_DAG)

    def test_evaluate_whole_fn_rejected(self):
        """整串函数调用作为 evaluate 值 = 编排层数据源声明，仍拦截"""
        with pytest.raises(ValueError):
            validate_ui_step_data_sources(
                [self.ui_node([{"action": "evaluate", "value": "${now()}"}])], self.NAMED_DAG)

    def test_row_and_field_fields_scanned(self):
        with pytest.raises(ValueError):
            validate_ui_step_data_sources(
                [self.ui_node([{"action": "row_button", "value": "详情",
                                "row": "${uuid()}"}])], self.NAMED_DAG)

    def test_api_node_ignored(self):
        validate_ui_step_data_sources(
            [{"node_id": "n2", "post_extract": [], "assertions": [],
              "params": {"body": {"x": {"source": "func", "func": "generate_bl_no", "args": []}}}}],
            self.NAMED_DAG)

    def test_single_step_form_scanned(self):
        """无 steps 包装的单动作形态（历史节点）同样校验"""
        with pytest.raises(ValueError):
            validate_ui_step_data_sources(
                [{"node_id": "n1", "step_type": "ui",
                  "ui_params": {"action": "fill", "value": "${uuid()}"},
                  "post_extract": [], "assertions": []}], self.NAMED_DAG)

    def test_message_shows_node_label(self):
        with pytest.raises(ValueError, match="「填提单号」"):
            validate_ui_step_data_sources(
                [self.ui_node([{"action": "fill", "value": "${uuid()}"}])], self.NAMED_DAG)


class TestChineseNodeNames:
    """校验消息展示中文节点名（「label」(node_id)）：画布节点 data.label 可读性。"""

    NAMED_DAG = {
        "nodes": [
            {"id": "n1", "data": {"label": "新建订单"}},
            {"id": "n2", "data": {"label": "审核"}},
        ],
        "edges": [{"source": "n1", "target": "n2"}],
    }

    def test_posterior_ref_shows_labels(self):
        errs = validate_case_configs(self.NAMED_DAG, [
            {"node_id": "n1", "params": {"body": {"x": {"source": "ref", "node_id": "n2", "var_path": "a"}}},
             "post_extract": [], "assertions": []},
        ])
        assert any("拓扑后置" in e and "「新建订单」(n1)" in e and "「审核」(n2)" in e for e in errs)

    def test_dangling_ref_shows_ref_label(self):
        # n2 引用拓扑前置节点 n1 的不存在变量 → 走悬空引用分支
        errs = validate_case_configs(self.NAMED_DAG, [
            n1_config(),
            {"node_id": "n2", "params": {"body": {"x": {"source": "ref", "node_id": "n1", "var_path": "ghost"}}},
             "post_extract": [], "assertions": []},
        ])
        assert any("悬空引用" in e and "「新建订单」(n1)" in e for e in errs)

    def test_unlabeled_node_falls_back_to_id(self):
        errs = validate_case_configs(DAG, [  # DAG 无 label
            n1_config(params={"body": {"x": {"source": "ref", "node_id": "n2", "var_path": "a"}}}),
        ])
        assert any("拓扑后置" in e and "n1" in e for e in errs)
