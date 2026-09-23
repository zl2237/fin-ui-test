"""组合动作库单测：本地 Chromium + 注入假 Element DOM。

不依赖被测系统——用 page.set_content 构造 el-message / el-message-box /
vxe 行 / readonly 检索框等结构，回归 13 个组合动作的关键行为与失败语义
（本地先于真实系统拦截 JS 语法错误/选择器失效）。playwright 缺失时跳过。
"""
from types import SimpleNamespace

import pytest

from app.services.ui_runtime import UiActionError, UiRuntime

playwright = pytest.importorskip("playwright.sync_api", reason="playwright 未安装")


# ---------- 假 DOM ----------
BASE_DOM = """
<div id="log"></div>
<div class="search-area"><span id="fake-save">保存</span></div>
<button id="save-btn" onclick="window.__saved=(window.__saved||0)+1">保 存</button>
<button id="import-btn" onclick="document.getElementById('log').dataset.import=1">导入报关费用</button>
<span id="gen-sub" onclick="document.getElementById('log').dataset.gen=1">生成子订单</span>
<table><tbody>
  <tr class="vxe-body--row"><td>uitestBl2026</td><td><button class="row-det">详情</button></td></tr>
</tbody></table>
<div id="popper-host"></div>
"""

SEARCH_DOM = """
<input id="bl" placeholder="提单号" readonly
       onclick="this.removeAttribute('readonly')">
<button id="query-btn">查询</button>
<div id="log"></div>
<table><tbody><tr class="vxe-body--row"><td>uitestBl2026</td></tr></tbody></table>
<script>
  document.getElementById('query-btn').addEventListener('click', () => {
    document.getElementById('log').dataset.query = '1';
  });
</script>
"""


@pytest.fixture(scope="module")
def browser():
    p = playwright.sync_playwright().start()
    b = p.chromium.launch(headless=True)
    yield b
    b.close()
    p.stop()


@pytest.fixture()
def rt(browser):
    """UiRuntime 实例：直连 fixture 浏览器页面，绕过 ensure_browser 启动链。"""
    context = browser.new_context()
    page = context.new_page()
    runtime = UiRuntime(
        db=None,
        env=SimpleNamespace(id=1, base_url="http://test.local", browser_config={}),
        context=None,
        project_id=1,
    )
    runtime._evaluate = lambda v: v  # 绕过表达式引擎（无 ExecutionContext）
    runtime._page = page  # ensure_browser 见 _page 已设直接返回
    runtime.__ctx = context
    yield runtime
    context.close()


def _load(rt, dom):
    rt._page.set_content(dom)
    return rt._page


# ---------- 文本点击类 ----------
class TestClickText:
    def test_normalized_match_and_exclude_search_area(self, rt):
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "click_text", "value": "保存"})
        assert facts["result"].startswith("clicked")
        assert rt._page.evaluate("window.__saved") == 1  # 点中的是真按钮（空白归一化）
        assert rt._page.evaluate("document.getElementById('fake-save').textContent") == "保存"

    def test_index_selects_nth(self, rt):
        """同名按钮按 index 取第 N 个（费用表「新增标准费用」场景）"""
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<button onclick='this.dataset.hit=1'>新增标准费用</button>"
            "<button onclick='this.dataset.hit=1'>新增标准费用</button>\")")
        facts = rt.run_action({"action": "click_text", "value": "新增标准费用", "index": 1})
        assert facts["result"] == "clicked:2"
        assert rt._page.evaluate(
            "[...document.querySelectorAll('button')].filter(b=>b.dataset.hit).length") == 1
        assert rt._page.evaluate(
            "[...document.querySelectorAll('button')].filter(b=>b.dataset.hit)[0]"
            "===[...document.querySelectorAll('button')].filter(b=>"
            "b.textContent==='新增标准费用')[1]") is True

    def test_span_entry(self, rt):
        _load(rt, BASE_DOM)
        rt.run_action({"action": "click_text", "value": "生成子订单"})
        assert rt._page.evaluate("document.getElementById('log').dataset.gen") == "1"

    def test_not_found_raises(self, rt):
        _load(rt, BASE_DOM)
        with pytest.raises(UiActionError, match="未找到"):
            rt.run_action({"action": "click_text", "value": "不存在的按钮"})

    def test_optional_absent(self, rt):
        """无则跳过：按钮不存在时返回 absent 不报错（作废按钮条件出现场景）"""
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "click_text", "value": "作废", "optional": True})
        assert facts["result"] == "absent"
        assert facts["optional"] is True

    def test_optional_still_clicks_when_present(self, rt):
        """无则跳过：按钮存在时正常点击，optional 不影响点击行为"""
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<button onclick='this.dataset.hit=1'>作废</button>\")")
        facts = rt.run_action({"action": "click_text", "value": "作废", "optional": True})
        assert facts["result"].startswith("clicked")
        assert rt._page.evaluate(
            "[...document.querySelectorAll('button')].some(b=>b.dataset.hit)") is True

    def test_contains_match(self, rt):
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "click_text_contains", "value": "导入"})
        assert facts["result"].startswith("clicked:")
        assert "导入报关费用" in facts["result"]
        assert rt._page.evaluate("document.getElementById('log').dataset.import") == "1"

    def test_row_button(self, rt):
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "row_button", "value": "详情"})
        assert facts["result"].startswith("clicked")  # clicked|目标|pool=... 增强格式


# ---------- 弹窗类 ----------
class TestConfirm:
    def test_no_dialog_tolerant(self, rt):
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "confirm"})
        assert facts["result"] == "no-dialog"

    def test_clicks_primary(self, rt):
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<div class='el-message-box'><div class='el-message-box__btns'>"
            "<button onclick='this.dataset.hit=1'>取 消</button>"
            "<button onclick='this.dataset.hit=1'>确 定</button></div></div>\")")
        facts = rt.run_action({"action": "confirm"})
        assert facts["result"] == "clicked:确定"
        assert rt._page.evaluate(
            "[...document.querySelectorAll('.el-message-box__btns button')]"
            ".filter(b=>b.dataset.hit).length") == 1

    def test_optional_confirm_absent(self, rt):
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "optional_confirm"})
        assert facts["result"] == "absent"

    def test_confirm_wait(self, rt):
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "setTimeout(()=>document.body.insertAdjacentHTML('beforeend',"
            "\"<div class='el-message-box'><button onclick='this.dataset.hit=1'>确 定</button></div>\"),800)")
        facts = rt.run_action({"action": "confirm_wait"})
        assert facts["result"] == "clicked:1"


# ---------- toast / save ----------
class TestToastAndSave:
    def test_toast_watch_hit(self, rt):
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<div class='el-message'>保存成功</div>\")")
        facts = rt.run_action({"action": "toast_watch", "value": "保存成功"})
        assert facts["result"].startswith("ok:")

    def test_toast_watch_timeout_raises_with_scene(self, rt):
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<div class='el-message'>检测到未填写必填项</div>\")")
        with pytest.raises(UiActionError, match="检测到未填写必填项"):
            rt.run_action({"action": "toast_watch", "value": "保存成功", "timeout_ms": 1500})

    # ---------- 三模式扩展：absent 反向 / optional 宽容 / div>p toast 结构 ----------
    def test_toast_watch_absent_clean(self, rt):
        """反向断言：窗口静默 → clean 通过（生成费用通知单场景的成功判据）"""
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "toast_watch", "absent": True, "timeout_ms": 1200})
        assert facts["result"] == "clean"
        assert facts["absent"] is True

    def test_toast_watch_absent_hits_div_p_toast(self, rt):
        """反向断言：div>p 直挂 body 的 toast（本系统结构）出现即失败并带文本"""
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<div><p>存在未生效的费用通知单</p></div>\")")
        with pytest.raises(UiActionError, match="存在未生效的费用通知单"):
            rt.run_action({"action": "toast_watch", "absent": True, "timeout_ms": 3000})

    def test_toast_watch_absent_value_scopes_match(self, rt):
        """反向断言 + value：只拦截匹配文本，无关 toast 不误伤"""
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<div class='el-message'>其他无关提示</div>\")")
        facts = rt.run_action(
            {"action": "toast_watch", "value": "已存在生效", "absent": True, "timeout_ms": 1200})
        assert facts["result"] == "clean"

    def test_toast_watch_optional_no_toast(self, rt):
        """宽容模式：超时未出现返回 no-toast 不报错（配 optional 点击的条件场景）"""
        _load(rt, BASE_DOM)
        facts = rt.run_action(
            {"action": "toast_watch", "value": "作废成功", "optional": True, "timeout_ms": 1200})
        assert facts["result"] == "no-toast"
        assert facts["optional"] is True

    def test_toast_watch_div_p_positive(self, rt):
        """正向命中也认 div>p 结构（原框架 toast xpath=/html/body/div/p 实证）"""
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<div><p>作废成功</p></div>\")")
        facts = rt.run_action({"action": "toast_watch", "value": "作废成功"})
        assert facts["result"].startswith("ok:")

    def test_save_full_chain(self, rt):
        """保存→延迟确认弹窗（点确定）→延迟 toast（命中）→ok"""
        _load(rt, BASE_DOM)
        rt._page.evaluate("""(() => {
          document.getElementById('save-btn').addEventListener('click', () => {
            setTimeout(() => document.body.insertAdjacentHTML('beforeend',
              "<div class='el-message-box'><button>确 定</button></div>"), 600);
            setTimeout(() => document.body.insertAdjacentHTML('beforeend',
              "<div class='el-message'>保存成功</div>"), 1400);
          });
        })()""")
        facts = rt.run_action({"action": "save", "timeout_ms": 8000})
        assert facts["result"].startswith("ok:")
        assert rt._page.evaluate("window.__saved") == 1

    def test_save_no_button_raises(self, rt):
        _load(rt, "<div>空页面</div>")
        with pytest.raises(UiActionError, match="保 存"):
            rt.run_action({"action": "save"})


# ---------- 浮层/滚动/JS点击/勾选 ----------
class TestMisc:
    def test_popper_pick(self, rt):
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.getElementById('popper-host').innerHTML="
            "'<ul><li>舱单</li><li>报关</li></ul>';"
            "document.getElementById('popper-host').style.display='block';"
            "document.getElementById('popper-host').className='el-select-dropdown__popper';"
            "document.querySelectorAll('#popper-host li').forEach(l=>"
            "l.addEventListener('click',()=>l.dataset.hit=1))")
        facts = rt.run_action({"action": "popper_pick", "value": "报关"})
        assert facts["result"] == "picked"
        assert rt._page.evaluate(
            "[...document.querySelectorAll('#popper-host li')]"
            ".filter(l=>l.dataset.hit).map(l=>l.textContent)[0]") == "报关"

    def test_popper_pick_missing_raises(self, rt):
        _load(rt, BASE_DOM)
        with pytest.raises(UiActionError, match="浮层选项"):
            rt.run_action({"action": "popper_pick", "value": "保险"})

    def test_scroll_bottom(self, rt):
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "scroll_bottom"})
        assert facts["result"] == "scrolled"

    def test_js_click(self, rt):
        _load(rt, BASE_DOM)
        rt.run_action({"action": "js_click",
                       "element": {"strategy": "css", "value": "#import-btn"}})
        assert rt._page.evaluate("document.getElementById('log').dataset.import") == "1"

    def test_uncheck_all(self, rt):
        _load(rt, """
        <label id="l1"><input type="checkbox" id="c1" checked></label>
        <label id="l2"><input type="checkbox" id="c2"></label>
        """)
        facts = rt.run_action({"action": "uncheck_all",
                               "element": {"strategy": "css", "value": "input[type=checkbox]"}})
        assert facts["unchecked"] == 1
        assert rt._page.evaluate("document.getElementById('c1').checked") is False
        assert rt._page.evaluate("document.getElementById('c2').checked") is False


# ---------- 下拉选择（pick）----------
class TestPick:
    def test_pick_empty_value_skips(self, rt):
        """稀疏列语义：value 求值为空 → 跳过不填不报错（原框架条件填空）"""
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "pick",
                               "element": {"strategy": "css", "value": "#import-btn"},
                               "value": ""})
        assert facts.get("skipped") == "empty-value"

    def test_fill_empty_value_skips(self, rt):
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "fill",
                               "element": {"strategy": "css", "value": "#save-btn"},
                               "value": ""})
        assert facts.get("skipped") == "empty-value"
        assert rt._page.evaluate("document.getElementById('save-btn').textContent") == "保 存"

    def test_check_zero_value_skips(self, rt):
        """check 的 '0' = 不动复选框（原框架：数据 '1' 才勾）"""
        _load(rt, """
        <input type="checkbox" id="c1">
        """)
        facts = rt.run_action({"action": "check",
                               "element": {"strategy": "css", "value": "#c1"},
                               "value": "0"})
        assert facts.get("skipped") == "empty-value"
        assert rt._page.evaluate("document.getElementById('c1').checked") is False

    def test_pick_multiple_tags_form(self, rt):
        """multiple/tags 形态 el-select：选中值渲染为 el-select__tags 内 tag 文本，
        input value 恒空——校验需走 tags 兜底（检索区「订单生效状态」筛选项实证）"""
        _load(rt, """
        <div class="el-select" id="ms">
          <div class="el-select__tags" id="ms-tags"><span></span>
            <input class="el-select__input is-medium"></div>
          <div class="el-input">
            <input id="ms-input" class="el-input__inner" placeholder="请选择" readonly>
          </div>
        </div>
        <div class="el-select-dropdown__popper" style="display:block">
          <ul><li class="el-select-dropdown__item">已生效</li>
              <li class="el-select-dropdown__item">未生效</li></ul>
        </div>
        <script>
          document.querySelectorAll('li.el-select-dropdown__item').forEach(li =>
            li.addEventListener('click', () => {
              const s = document.createElement('span');
              s.textContent = li.textContent;
              document.getElementById('ms-tags').appendChild(s);
            }));
        </script>
        """)
        facts = rt.run_action({"action": "pick",
                               "element": {"strategy": "css", "value": "#ms-input"},
                               "value": "已生效"})
        assert facts["value"] == "已生效"
        assert "已生效" in rt._page.evaluate(
            "document.getElementById('ms-tags').textContent")

    def test_pick_single_input_form(self, rt):
        """普通形态：选中值写入 input value，原校验路径不回归"""
        _load(rt, """
        <div class="el-select">
          <div class="el-input">
            <input id="s-input" class="el-input__inner" placeholder="请选择" readonly>
          </div>
        </div>
        <div class="el-select-dropdown__popper" style="display:block">
          <ul><li class="el-select-dropdown__item">海运费</li></ul>
        </div>
        <script>
          document.querySelector('li.el-select-dropdown__item').addEventListener('click', () => {
            const i = document.getElementById('s-input');
            i.value = '海运费'; i.removeAttribute('readonly');
          });
        </script>
        """)
        facts = rt.run_action({"action": "pick",
                               "element": {"strategy": "css", "value": "#s-input"},
                               "value": "海运费"})
        assert facts["value"] == "海运费"


# ---------- 激活式检索 ----------
class TestSearch:
    # SEARCH_DOM 是激活式检索框结构（readonly 输入框，点击解除后填值回车），
    # 对应 search 的 element 路径；默认筛选区路径面向真实系统页面（展开/更多筛选/
    # 字段下拉），本地 DOM 无这些结构，走默认路径必在「更多筛选」处超时
    ELEMENT = {"strategy": "css", "value": "#bl"}

    def test_search_found(self, rt):
        _load(rt, SEARCH_DOM)
        facts = rt.run_action({"action": "search", "value": "uitestBl2026",
                               "element": self.ELEMENT})
        assert facts["result"] == "found"
        assert rt._page.evaluate("document.getElementById('bl').value") == "uitestBl2026"
        assert rt._page.evaluate("document.getElementById('log').dataset.query") == "1"

    def test_search_not_found_raises(self, rt):
        _load(rt, SEARCH_DOM)
        with pytest.raises(UiActionError, match="未见业务行"):
            rt.run_action({"action": "search", "value": "not-exist-key",
                           "element": self.ELEMENT})


# ---------- 参数校验 ----------
class TestParamValidation:
    @pytest.mark.parametrize("action", ["search", "click_text", "click_text_contains",
                                        "row_button", "popper_pick", "toast_watch"])
    def test_missing_value_raises(self, rt, action):
        _load(rt, BASE_DOM)
        with pytest.raises(UiActionError, match="需要 value"):
            rt.run_action({"action": action})


# ---------- 动作组（页面级节点 steps） ----------
class TestActionGroup:
    def test_steps_ordered_and_facts_aggregated(self, rt):
        """组内动作按序执行，facts 聚合 steps 明细 + 末步公共字段"""
        _load(rt, BASE_DOM)
        facts = rt.run_action({"steps": [
            {"action": "click_text", "value": "导入报关费用"},
            {"action": "click_text", "value": "保存"},
            {"action": "evaluate", "value": "document.getElementById('log').dataset.import"},
        ]})
        assert len(facts["steps"]) == 3
        # 各步 action 与返回值按序进入明细
        assert [s["action"] for s in facts["steps"]] == ["click_text", "click_text", "evaluate"]
        # 末步 evaluate 的结果在顶层（公共字段取末步；evaluate 返回 result 字段）
        assert facts["result"] == "1"
        # 前面步骤的副作用真实发生
        assert rt._page.evaluate("window.__saved") == 1

    def test_failure_annotates_step_no(self, rt):
        """中途失败标注 [步骤N·动作]，且前序步骤已执行"""
        _load(rt, BASE_DOM)
        with pytest.raises(UiActionError, match=r"\[步骤2·click_text\]"):
            rt.run_action({"steps": [
                {"action": "click_text", "value": "保存"},
                {"action": "click_text", "value": "不存在的按钮"},
            ]})
        assert rt._page.evaluate("window.__saved") == 1

    def test_empty_group_rejected(self, rt):
        _load(rt, BASE_DOM)
        with pytest.raises(UiActionError, match="steps 为空"):
            rt.run_action({"steps": []})

    def test_nested_group_rejected(self, rt):
        _load(rt, BASE_DOM)
        with pytest.raises(UiActionError, match="不允许嵌套"):
            rt.run_action({"steps": [{"action": "click", "steps": []}]})


# ---------- 合并参数化等价（click_text.match / confirm.wait/optional / click.mode） ----------
class TestMergedParams:
    def test_click_text_contains_match(self, rt):
        """match='contains' 等价原 click_text_contains（导入 → 导入报关费用）"""
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "click_text", "value": "导入", "match": "contains"})
        assert facts["result"] == "clicked:导入报关费用"
        assert rt._page.evaluate("document.getElementById('log').dataset.import") == "1"

    def test_click_text_default_is_exact(self, rt):
        """缺省 match 为精确匹配：片段文本不应命中"""
        _load(rt, BASE_DOM)
        with pytest.raises(UiActionError):
            rt.run_action({"action": "click_text", "value": "导入"})

    def test_confirm_wait_param(self, rt):
        """wait=true 等价原 confirm_wait（延迟弹窗轮询命中）"""
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "setTimeout(()=>document.body.insertAdjacentHTML('beforeend',"
            "\"<div class='el-message-box'><button onclick='this.dataset.hit=1'>确 定</button></div>\"),800)")
        facts = rt.run_action({"action": "confirm", "wait": True})
        assert facts["result"] == "clicked:1"

    def test_confirm_optional_param(self, rt):
        """optional=true 等价原 optional_confirm（无弹窗返回 absent）"""
        _load(rt, BASE_DOM)
        facts = rt.run_action({"action": "confirm", "optional": True})
        assert facts["result"] == "absent"

    def test_click_js_mode(self, rt):
        """mode='js' 等价原 js_click（JS 直调点击）"""
        _load(rt, BASE_DOM)
        rt._page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            "\"<button id='occl' onclick='this.dataset.hit=1'>被遮挡按钮</button>\")")
        facts = rt.run_action({"action": "click", "mode": "js",
                               "element": {"strategy": "css", "value": "#occl"}})
        assert facts["via"] == "js"
        assert rt._page.evaluate("document.querySelector('#occl').dataset.hit") == "1"


# ---------- 自定义动作（custom） ----------
class TestCustomAction:
    @staticmethod
    def _fake_db(rt, script):
        """注入内存 CustomAction 替身（不走数据库）"""
        from types import SimpleNamespace
        ca = SimpleNamespace(id=99, name="校验演示", script=script)
        class _Q:
            def __init__(self, obj): self._obj = obj
            def filter(self, *a, **k): return self
            def first(self): return self._obj
        rt.db = SimpleNamespace(query=lambda m: _Q(ca))
        return ca

    def test_custom_executes_script_with_args(self, rt):
        _load(rt, BASE_DOM)
        self._fake_db(rt, "return 'args=' + args")
        facts = rt.run_action({"action": "custom", "custom_id": 99, "value": "hello"})
        assert facts["custom"] == "校验演示"
        assert facts["result"] == "args=hello"

    def test_custom_script_error_wrapped(self, rt):
        _load(rt, BASE_DOM)
        self._fake_db(rt, "throw new Error('boom')")
        with pytest.raises(UiActionError, match="校验演示"):
            rt.run_action({"action": "custom", "custom_id": 99})

    def test_custom_requires_custom_id(self, rt):
        _load(rt, BASE_DOM)
        with pytest.raises(UiActionError, match="custom_id"):
            rt.run_action({"action": "custom"})

    def test_nav_transient_retry_for_read_action(self, rt, monkeypatch):
        """页面导航瞬态（context destroyed）：读类动作等待后重试该步一次即恢复"""
        _load(rt, BASE_DOM)
        calls = {"n": 0}
        orig = rt.run_action

        def flaky(params):
            if isinstance(params.get("steps"), list):
                return orig(params)  # 组调度本身不注入
            if params.get("action") == "evaluate":
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("Page.evaluate: Execution context was destroyed, "
                                       "most likely because of a navigation.")
            return orig(params)

        monkeypatch.setattr(rt, "run_action", flaky)
        facts = rt.run_action({"steps": [
            {"action": "click_text", "value": "保存"},
            {"action": "evaluate", "value": "document.title"},
        ]})
        assert calls["n"] == 2  # 瞬态失败一次 + 重试成功一次
        assert len(facts["steps"]) == 2

    def test_non_ui_exception_wrapped_with_partial(self, rt, monkeypatch):
        """非读类动作的意外异常：包装为 UiActionError 且保留已完成步骤现场"""
        _load(rt, BASE_DOM)
        orig = rt.run_action

        def boom(params):
            if isinstance(params.get("steps"), list):
                return orig(params)
            if params.get("action") == "click_text" and params.get("value") == "导入报关费用":
                raise RuntimeError("Page.evaluate: Execution context was destroyed")
            return orig(params)

        monkeypatch.setattr(rt, "run_action", boom)
        with pytest.raises(UiActionError, match=r"\[步骤2·click_text\] UI 执行异常") as ei:
            rt.run_action({"steps": [
                {"action": "click_text", "value": "保存"},
                {"action": "click_text", "value": "导入报关费用"},
            ]})
        assert len(ei.value.partial) == 1  # 第 1 步现场保留
        assert rt._page.evaluate("window.__saved") == 1
