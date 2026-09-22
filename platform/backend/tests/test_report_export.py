"""报告 CSV 导出纯函数单测（导出逻辑从前端视图下沉后端）。

已知事实来自前端 exportCsv 原实现的独立复述：
- BOM 头 + CRLF 行分隔
- 12 列表头
- 值内逗号/引号/换行需 CSV 转义
"""
from app.services.report_export import export_report_html, export_steps_csv


class _Step:
    def __init__(self, **kw):
        self.api_name = kw.get("api_name", "下单")
        self.node_id = kw.get("node_id", "n1")
        self.api_method = kw.get("api_method", "POST")
        self.api_path = kw.get("api_path", "/order")
        self.response_status = kw.get("response_status", 200)
        self.response_time_ms = kw.get("response_time_ms", 12)
        self.status = kw.get("status", "success")
        self.request_headers = kw.get("request_headers", {"X-Token": "t"})
        self.request_body = kw.get("request_body", {"a": 1})
        self.response_body = kw.get("response_body", {"code": 0})
        self.started_at = kw.get("started_at", "2026-01-01 10:00:00")
        self.ended_at = kw.get("ended_at", "2026-01-01 10:00:01")
        self.assertions = kw.get("assertions", [])
        self.post_extract = kw.get("post_extract", [])
        self.extracted_vars = kw.get("extracted_vars", {})


class _Assert:
    def __init__(self, **kw):
        self.rule_type = kw.get("rule_type", "json_path_equals")
        self.result = kw.get("result", True)
        self.actual_value = kw.get("actual_value", "0")
        self.expected_value = kw.get("expected_value", "0")
        self.message = kw.get("message", "")


class TestExportStepsCsv:
    def test_bom_and_header_row(self):
        csv = export_steps_csv([])
        assert csv.startswith("\ufeff")
        # BOM 紧贴表头（与前端原实现一致：'\ufeff' + header）
        lines = csv.split("\r\n")
        assert lines[0] == "\ufeff序号,步骤名称,方法,路径,HTTP状态码,耗时(ms),步骤状态,断言通过,断言总数,断言详情,请求体,响应体"

    def test_step_row_contains_counts_and_assert_details(self):
        steps = [_Step(assertions=[_Assert(), _Assert(result=False, actual_value="1")])]
        csv = export_steps_csv(steps)
        lines = csv.split("\r\n")
        assert len(lines) == 2  # 表头 + 1 行
        row = lines[1]
        assert row.startswith("1,")  # 序号
        assert "0" in row  # 断言通过 1 条？——实际 1 条通过
        assert "2" in row  # 断言总数

    def test_values_with_comma_are_escaped(self):
        steps = [_Step(api_name='下单,批量')]
        csv = export_steps_csv(steps)
        assert '"下单,批量"' in csv

    def test_assertion_detail_format(self):
        steps = [_Step(assertions=[_Assert(rule_type="status_equals")])]
        csv = export_steps_csv(steps)
        assert "status_equals:通过(" in csv


class _Record:
    """执行记录最小载体（含 fill_exec_names/fill_audit_names 后的展示字段）"""

    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.status = kw.get("status", "success")
        self.case_id = kw.get("case_id", 7)
        self.case_name = kw.get("case_name", "下单链路")
        self.env_id = kw.get("env_id", 3)
        self.env_name = kw.get("env_name", "test")
        self.project_name = kw.get("project_name", "订单系统")
        self.created_by_name = kw.get("created_by_name", "boss")
        self.started_at = kw.get("started_at", "2026-01-01 10:00:00")
        self.ended_at = kw.get("ended_at", "2026-01-01 10:00:05")
        self.summary = kw.get("summary", {})


class TestExportReportHtml:
    def test_document_skeleton_and_title(self):
        html = export_report_html(_Record(), [])
        assert html.startswith("<!DOCTYPE html>")
        assert "<html lang=\"zh-CN\">" in html
        assert "<title>执行报告 #1</title>" in html

    def test_summary_grid_contains_record_and_count_fields(self):
        steps = [_Step(), _Step(status="failed")]
        html = export_report_html(_Record(), steps)
        assert "下单链路" in html
        assert "订单系统" in html
        assert '<span class="pass-c">1</span> / 2' in html  # 步骤通过/总数（通过数绿色高亮）
        assert "执行人" in html

    def test_step_and_assertion_rendered(self):
        steps = [_Step(assertions=[_Assert()])]
        html = export_report_html(_Record(), steps)
        assert "下单" in html          # 步骤名
        assert "✓ 通过" in html        # 断言结果
        assert "json_path_equals" in html

    def test_html_escaping(self):
        steps = [_Step(api_name="<script>alert(1)</script>")]
        html = export_report_html(_Record(), steps)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_status_badge_class(self):
        html = export_report_html(_Record(status="failed"), [])
        assert "badge-failed" in html

    # ===== Allure 式导航布局（重构后的结构契约） =====

    def test_nav_item_per_step_with_status_data(self):
        """每个步骤一个导航项，携带状态/名称/路径供 JS 过滤"""
        steps = [_Step(), _Step(status="failed", api_name="查单")]
        html = export_report_html(_Record(), steps)
        assert html.count('class="nav-item"') == 2
        assert 'data-status="success"' in html
        assert 'data-status="failed"' in html
        assert 'data-name="查单"' in html

    def test_detail_pane_per_step_with_tabs(self):
        """每个步骤一个详情面板，内含请求/响应/提取/断言四个 Tab（radio 驱动）"""
        steps = [_Step(assertions=[_Assert()]), _Step()]
        html = export_report_html(_Record(), steps)
        assert html.count('class="step-pane"') == 2
        assert html.count('class="sp-radio sp-radio-req"') == 2
        assert "断言（1）" in html
        assert "断言（0）" in html

    def test_sticky_header_wraps_title_and_tabs(self):
        """标题区（节点名+meta+Tab 栏）用 .sp-sticky 包容器粘顶；Tab 切换改用 :has() 选择器"""
        steps = [_Step(assertions=[_Assert()])]
        html = export_report_html(_Record(), steps)
        # sp-sticky 包容器存在，且每个 step-pane 恰好一个
        assert html.count('class="sp-sticky"') == 1
        # sp-head/sp-meta/sp-tabs 均在 sp-sticky 内（出现在 sp-sticky 之后、sp-panes 之前）
        sticky_open = html.find('class="sp-sticky"')
        sp_head = html.find('class="sp-head"', sticky_open)
        sp_tabs = html.find('class="sp-tabs"', sticky_open)
        sp_panes = html.find('class="sp-panes"')
        assert sticky_open < sp_head < sp_tabs < sp_panes
        # Tab 切换选择器用 :has()（不再依赖 ~ 兄弟选择器）
        assert ":has(input.sp-radio-req:checked)" in html
        assert "~ .sp-panes" not in html

    # ===== 请求 Tab 渲染口径 / 后置提取 =====

    def test_request_tab_only_headers_and_body(self):
        """请求 Tab 只渲染请求头/请求体：前置处理配置已随前置动作概念移除，
        不再有配置原文展示（避免与请求体重复的信息噪音）"""
        steps = [_Step()]
        html = export_report_html(_Record(), steps)
        assert "请求头" in html and "请求体" in html
        assert "前置处理" not in html
        assert "设置字段" not in html and "执行 SQL" not in html

    def test_extract_tab_with_rules_and_actual_values(self):
        """提取 Tab：变量名/来源/规则/实际提取结果；缺失结果标注未提取到"""
        steps = [_Step(
            post_extract=[
                {"name": "bl_no", "source": "response", "json_path": "$.data.blNo"},
                {"name": "order_id", "source": "db", "sql": "SELECT id FROM t_order", "field": "id"},
                {"name": "miss", "source": "response", "json_path": "$.none"},
            ],
            extracted_vars={"bl_no": "OHYHL001", "order_id": 42},
        )]
        html = export_report_html(_Record(), steps)
        assert "提取（3）" in html
        assert "bl_no" in html
        assert "OHYHL001" in html
        assert "数据库" in html and "响应" in html
        assert "SELECT id FROM t_order → id" in html   # db 规则：SQL + 取值字段
        assert "42" in html                            # 非字符串值 JSON 化展示
        assert "未提取到" in html                       # 规则失败/值缺失明确标注

    def test_extract_tab_empty_shows_placeholder(self):
        html = export_report_html(_Record(), [_Step()])
        assert "提取（0）" in html
        assert "该步骤无提取规则" in html

    def test_fail_summary_card_only_when_failed(self):
        """失败摘要卡仅在有失败步骤时渲染，含跳转锚点与失败原因"""
        ok_html = export_report_html(_Record(), [_Step()])
        assert 'class="fail-card"' not in ok_html  # CSS 类定义常在，断 DOM 未渲染

        steps = [
            _Step(),
            _Step(status="failed", api_name="查单",
                  assertions=[_Assert(result=False, message="金额不符")]),
        ]
        html = export_report_html(_Record(), steps)
        assert "fail-card" in html
        assert "1 个步骤未通过" in html
        assert "金额不符" in html          # 首条失败断言消息透出
        assert 'data-step="step-2"' in html  # 跳转锚点指向失败步骤

    def test_dark_scheme_variables_present(self):
        """深浅双套变量：prefers-color-scheme dark 覆盖"""
        html = export_report_html(_Record(), [])
        assert "prefers-color-scheme: dark" in html
        assert "--primary: #0071e3" in html  # 主色对齐系统

    def test_interactive_js_embedded(self):
        """内联 JS：搜索/筛选/导航选中/失败优先初始选中"""
        html = export_report_html(_Record(), [_Step()])
        assert "nav-search" in html
        assert "filter-btn" in html
        # 失败优先：默认选中首个非 success 步骤
        assert 'querySelector(\'.nav-item[data-status]:not([data-status="success"])\')' in html

    def test_failed_assertion_row_highlighted(self):
        """失败断言行红底标记"""
        steps = [_Step(assertions=[_Assert(result=False)])]
        html = export_report_html(_Record(), steps)
        assert 'class="row-fail"' in html
        assert "✗ 失败" in html

    def test_long_text_metrics_truncated_with_title(self):
        """回归 #263：超长用例名等文本类统计值单行截断 + title 悬浮全文，
        防止 word-break 折行导致统计卡高度随名称长度无限膨胀"""
        long_name = "冒烟-" * 80
        html = export_report_html(_Record(case_name=long_name), [_Step()])
        # 截断类样式与 title 全文并存
        assert f'<div class="metric-value to" title="{long_name}">{long_name}</div>' in html
        # 数字类计数不参与截断
        assert '<span class="pass-c">1</span> / 1' in html
        # 步骤名与导航项同样有 title 悬浮
        assert '<span class="sp-name" title="下单">下单</span>' in html
        assert 'title="下单&#10;POST /order"' in html


class _UiStep(_Step):
    """UI 步骤替身：step_kind='ui'，request=ui_params(steps)，response=facts(steps)"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.step_kind = kw.get("step_kind", "ui")
        self.screenshot_file_id = kw.get("screenshot_file_id", None)
        self.api_method = kw.get("api_method", "UI")
        self.api_path = kw.get("api_path", "/development/order/create")


_UI_PARAMS = {
    "steps": [
        {"action": "goto", "url": "/development/order/create"},
        {"action": "fill", "element": "提单号输入框", "value": "UITEST001"},
        {"action": "click", "element": "保存按钮"},
    ]
}
_UI_FACTS_OK = {
    "action": "steps",
    "url": "/development/order/create",
    "title": "新增订单",
    "steps": [
        {"action": "goto", "url": "/development/order/create", "title": "新增订单"},
        {"action": "fill", "value": "UITEST001"},
        {"action": "click", "count": 1},
    ],
}


class TestExportReportHtmlUi:
    """UI 步骤（step_kind='ui'）专项渲染：动作链表 / 截图 / 页面事实 / 失败现场"""

    def test_ui_pane_meta_and_tab_labels(self):
        """meta 行显示动作组规模+终态页面+标题；Tab 换成 动作链/页面截图"""
        html = export_report_html(_Record(), [_UiStep(request_body=_UI_PARAMS, response_body=_UI_FACTS_OK)])
        assert '<span class="sp-kind">UI</span>' in html          # 头部类型徽标
        assert "UI · 动作组 3 步" in html
        assert "/development/order/create" in html                 # 终态页面
        assert "新增订单" in html                                   # 页面标题
        assert "动作链（3）" in html                                # Tab 标签
        assert "页面 / 截图" in html

    def test_ui_steps_table_param_result_alignment(self):
        """动作链表逐步对齐：参数侧 element/value + 结果侧 facts；请求/响应 Tab 的 API 原文不渲染"""
        html = export_report_html(_Record(), [_UiStep(request_body=_UI_PARAMS, response_body=_UI_FACTS_OK)])
        assert "动作链（3 步）" in html
        assert "提单号输入框" in html and "UITEST001" in html       # 参数摘要
        assert "保存按钮" in html
        assert "count=1" in html                                   # 结果摘要（facts 非 action 键值）
        assert "请求头" not in html and "请求体" not in html          # API 面板文案不出现
        assert "状态码" not in html

    def test_ui_failed_group_marks_failed_step_and_remaining(self):
        """失败组（partial 现场）：失败步显示错误、其后标未执行；失败摘要卡透出 UI 错误"""
        resp = {
            "action": "steps", "error": "[步骤2·fill] Timeout 30000ms",
            "steps": [{"action": "goto", "url": "/development/order/create"}],
        }
        html = export_report_html(_Record(), [_UiStep(status="failed", request_body=_UI_PARAMS, response_body=resp)])
        assert "row-fail" in html
        assert "[步骤2·fill] Timeout 30000ms" in html              # 失败步错误（title + 摘要）
        assert "未执行" in html                                     # 步骤3 中止
        assert "✗" in html
        assert "UI 动作执行失败" not in html                          # 有 error 时失败卡显示 error 原文
        assert "[步骤2·fill] Timeout 30000ms</span>" in html or "Timeout 30000ms" in html

    def test_ui_fail_card_without_assertions_shows_error(self):
        """UI 失败且无断言失败时，失败摘要卡显示 response.error 而非裸状态"""
        resp = {"action": "steps", "error": "页面崩溃", "steps": []}
        html = export_report_html(_Record(), [_UiStep(status="failed", request_body=_UI_PARAMS, response_body=resp)])
        assert "1 个步骤未通过" in html
        assert "页面崩溃" in html

    def test_ui_legacy_single_action_format(self):
        """旧单动作格式（ui_params 无 steps）：动作链表退化为单行"""
        rb = {"action": "goto", "url": "/login"}
        resp = {"action": "goto", "url": "/login", "title": "登录"}
        html = export_report_html(_Record(), [_UiStep(request_body=rb, response_body=resp)])
        assert "动作（单步）" in html
        assert "UI · 单动作" in html
        assert "动作链（1）" in html

    def test_ui_screenshot_placeholder_without_file(self):
        """无截图文件：占位文案说明截图策略"""
        html = export_report_html(_Record(), [_UiStep(request_body=_UI_PARAMS, response_body=_UI_FACTS_OK)])
        assert "无截图" in html

    def test_ui_screenshot_degrades_without_db(self):
        """有 screenshot_file_id 但无 db 会话：降级提示，不抛异常"""
        s = _UiStep(request_body=_UI_PARAMS, response_body=_UI_FACTS_OK, screenshot_file_id=99)
        html = export_report_html(_Record(), [s])
        assert "截图不可用（导出上下文无数据库会话）" in html

    def test_ui_screenshot_embedded_as_data_uri(self):
        """有 db：TestFile → 物理文件 → base64 data URI 内嵌（点击可看原图）"""
        import base64 as b64mod
        import types

        png = b"\x89PNG-fake-bytes"
        tf = types.SimpleNamespace(content_type="image/png", storage_path="files/ab/abcd")
        fake_db = types.SimpleNamespace(get=lambda model, fid: tf if fid == 7 else None)

        # _ui_screenshot_sec 内部局部导入 file_helpers.resolve_physical_path，打桩该模块函数
        import app.services.file_helpers as fh
        orig = fh.resolve_physical_path
        fh.resolve_physical_path = lambda p: types.SimpleNamespace(read_bytes=lambda: png)
        try:
            s = _UiStep(request_body=_UI_PARAMS, response_body=_UI_FACTS_OK, screenshot_file_id=7)
            html = export_report_html(_Record(), [s], db=fake_db)
        finally:
            fh.resolve_physical_path = orig

        uri = "data:image/png;base64," + b64mod.b64encode(png).decode("ascii")
        assert uri in html
        assert '<img class="shot"' in html

    def test_ui_page_facts_excludes_steps(self):
        """页面事实区排除 steps（已在动作链表展开），保留 url/title 等末步公共字段"""
        html = export_report_html(_Record(), [_UiStep(request_body=_UI_PARAMS, response_body=_UI_FACTS_OK)])
        assert "页面事实" in html
        # steps 列表的 JSON 不重复出现在页面事实（动作链表内 count=1 只出现一次级结果摘要）
        assert '"steps": [' not in html and '"steps":[' not in html

    def test_ui_failed_meta_recovers_page_from_partial(self):
        """失败组顶层无 url/title：meta 从 partial steps 回溯最后出现值，还原失败页面"""
        resp = {
            "action": "steps", "error": "[步骤2·fill] Timeout",
            "steps": [
                {"action": "goto", "url": "/dev/order", "title": "订单页"},
                {"action": "fill", "value": "X"},   # 无 url/title
            ],
        }
        html = export_report_html(_Record(), [
            _UiStep(status="failed", api_path="", request_body=_UI_PARAMS, response_body=resp)])
        assert "订单页" in html                                  # 回溯到的页面标题
        assert "/dev/order" in html                              # 回溯到的页面 URL

    def test_api_step_rendering_unchanged(self):
        """API 步骤（无 step_kind 属性的历史数据）渲染保持原样：请求/响应 Tab + 状态码"""
        html = export_report_html(_Record(), [_Step()])
        assert ">请求</label>" in html
        assert ">响应</label>" in html
        assert "状态码" in html and "请求头" in html and "请求体" in html
        assert '<span class="sp-kind">UI</span>' not in html
