"""UI 执行管线（Playwright）：与 API 管线对称的浏览器运行时。

设计要点（承接 autotest-playwright 的既有约定，见其 core/base_page.py）：
- 生命周期：首个 UI 节点惰性启动浏览器（ensure_browser），整条用例全程复用一个
  Page（与 flow/trigger 的单 page 模型一致）；close() 在 DagExecutor.execute 的
  finally 中调用，异常路径同样清理；
- 线程边界：Playwright sync API 基于 greenlet、对象绑定创建线程——所有对象创建/
  使用/清理都必须留在 DagExecutor 的 worker 线程内，不得交给通知等其他线程；
- 并发闸门：进程级 UI_SEMAPHORE 限制同时存活的浏览器数（默认 2，环境变量
  UI_BROWSER_CONCURRENCY 覆盖），与批次线程池解耦，防止 16 并发拉爆内存；
- 会话复用：单会话系统（同账号互踢）下，优先把 EnvTokenCache 的 token 注入
  browser context cookie（对应被测系统的 Admin-Token 幂等检测），跳过页面表单
  登录且与 API 管线共享同一份会话；
- 定位策略：ui_params.element 支持 {strategy, value} 内联定位或 {element_id} 引用
  元素库；元素库 strategies 沿用 locator JSON 的多策略字段，按固定优先级链解析，
  首个命中即用（full_xpath 永远兜底）。

动作词表（ui_params.action）：
goto / click / fill / pick / date / select_option / check / press / wait / upload / screenshot / evaluate
（pick/date 为 Element-UI 定制：下拉"点击→检索→选项→Esc"、日期"fill+Enter"）

产出契约（facts dict，进 StepResult.response_body）：
后置提取与断言复用 API 管线的同一套机制——extractor 对 facts 做 json_path 提取、
AssertionEngine 对 facts 做 json_path_* 断言（db_* 断言不依赖 facts，直接可用），
因此 UI 节点的断言/提取配置界面与 API 节点完全同构（如 $.url contains、$.text equals）。
"""
import asyncio
import hashlib
import os
import sys
import threading
from datetime import datetime
from typing import Any

from ..engine.context import ExecutionContext
from ..engine.expression import ExpressionEngine

try:  # playwright 为可选依赖（仅 UI 节点执行时需要）；版本间导出路径有差异：
    from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover
    try:
        from playwright.sync_api import PlaywrightTimeoutError  # type: ignore[no-redef]
    except ImportError:
        class PlaywrightTimeoutError(Exception):  # type: ignore[no-redef]
            pass

# 进程级浏览器并发闸门：与批次线程池解耦，只限制同时存活的 Chromium 数
UI_BROWSER_CONCURRENCY = max(1, int(os.getenv("UI_BROWSER_CONCURRENCY", "2")))
UI_SEMAPHORE = threading.BoundedSemaphore(UI_BROWSER_CONCURRENCY)

# 元素库 strategies 的解析优先级（自 base_page._get_visible_locator 的策略链简化而来：
# 语义定位优先，full_xpath 永远兜底）
_STRATEGY_PRIORITY = [
    "test_id", "for", "label", "placeholder",
    "button", "tab", "role", "text", "checkbox", "toast",
    "css", "xpath", "full_xpath",
]

# 单策略 element spec 的合法取值（与元素库 strategies 的键保持同一套策略语言）
_INLINE_STRATEGIES = {"css", "xpath", "full_xpath", "text", "role", "placeholder", "label",
                      "test_id", "for", "button", "tab", "checkbox", "toast"}

_DEFAULT_TIMEOUT_MS = 15000


class UiActionError(Exception):
    """UI 动作执行失败（定位超时/参数缺失/playwright 缺失等业务级失败）。

    partial：动作组中途失败时已完成步骤的 facts 列表（失败现场，报告可见）。
    """

    def __init__(self, msg: str, partial: list | None = None):
        super().__init__(msg)
        self.partial = partial


def build_locator(page, strategies: dict):
    """按优先级链把 strategies 字典解析为 Playwright locator；无可用策略时抛错。

    strategies 兼容两种来源：
    - 元素库 UiElement.strategies / 迁移自 locator JSON 的多策略字段；
    - 内联单策略 {"strategy": "css", "value": "..."}（先行展开为单键字典）。
    """
    if not isinstance(strategies, dict) or not strategies:
        raise UiActionError("定位配置为空：element 需要 {strategy, value} 或元素库引用")
    for key in _STRATEGY_PRIORITY:
        val = strategies.get(key)
        if val is None or val == "":
            continue
        val = str(val)
        if key == "test_id":
            return page.get_by_test_id(val)
        if key == "for":
            # 语义与原框架一致：label[for=X] 的 following-sibling 容器内首个 input/textarea。
            # 不能用 [id=X] 直查——被测系统 label 的 for 值并非真实 DOM id（委托订单表单实证）
            return page.locator(
                f"xpath=(//label[@for='{val}']/following-sibling::div"
                f"//*[name()='input' or name()='textarea'])[1]")
        if key == "label":
            # 与原框架一致：表单项容器（el-form-item/basic-table-receive）文本包含
            # label 值时取容器内首个 input/textarea（has_text 语义）。不能用
            # get_by_label——全局模糊会误匹配 aria-label 相近的弹窗（实证）
            return page.locator(
                f"xpath=(//div[contains(@class,'el-form-item') or "
                f"contains(@class,'basic-table-receive')]"
                f"[contains(normalize-space(.), '{val}')]"
                f"//*[name()='input' or name()='textarea'])[1]")
        if key == "placeholder":
            # exact 精确匹配：检索区存在"提单号"/"提单号批量"同类 placeholder，子串会误中
            return page.get_by_placeholder(val, exact=True)
        if key == "button":
            return page.get_by_role("button", name=val)
        if key == "tab":
            # 原框架语义：value 是 tab 的 DOM id（如 tab-order_actual_cost），
            # 非 accessible name（get_by_role(name=id) 恒匹配不到——费用 tab 实证）
            return page.locator(f"[id='{val}']")
        if key == "role":
            # 内联角色定位：role=角色名，role_extra=可访问名（如 role=tab + name=报关）
            return page.get_by_role(val, name=strategies.get("role_extra") or None)
        if key in ("text", "checkbox", "toast"):
            # checkbox/toast 本质是"按可见文本定位"（Element UI 的复选框标签/全局提示）
            return page.get_by_text(val, exact=False)
        if key == "css":
            return page.locator(val)
        if key in ("xpath", "full_xpath"):
            return page.locator(f"xpath={val}")
    raise UiActionError(f"定位配置无可用策略：{sorted(strategies.keys())}")


def _resolve_element_spec(page, element: Any):
    """element 配置 → strategies 字典。支持内联单策略与多策略字典两种写法。"""
    if not isinstance(element, dict):
        raise UiActionError("element 配置缺失或格式错误")
    strategy = element.get("strategy")
    if strategy:
        if strategy not in _INLINE_STRATEGIES:
            raise UiActionError(f"不支持的定位方式: {strategy}（可选 {sorted(_INLINE_STRATEGIES)}）")
        spec = {"role_extra": element.get("name")} if strategy == "role" else {}
        spec[strategy] = element.get("value")
        return spec
    strategies = element.get("strategies")
    if isinstance(strategies, dict) and strategies:
        return strategies
    raise UiActionError("element 需要 {strategy, value} 或 {strategies: {...}}")


def save_screenshot_file(db, project_id: int | None, png_bytes: bytes, name: str,
                         user_id: int | None = None, category_id: int | None = None) -> int | None:
    """截图字节流落文件中心（sha256 去重 + ref_count 引用计数），返回 test_files.id。

    - user_id：执行人，落 created_by（文件中心「上传人」列）；命中同内容旧记录时回填空值
    - category_id：归档分类；None 时自动落到项目级「UI执行截图」分类（不存在则建）
    与 routers/files.py 的上传逻辑同一套存储约定（失败安全：落库失败返回 None，
    不影响执行主流程）。
    """
    if not png_bytes or project_id is None:
        return None
    try:
        from .. import crud  # models 仅类型层面使用，勿引入避免循环
        from .file_helpers import build_storage_path, resolve_physical_path

        if category_id is None:
            category_id = crud.ensure_file_category_by_name(db, project_id, "UI执行截图", user_id).id

        sha256 = hashlib.sha256(png_bytes).hexdigest()
        existing = crud.get_file_by_sha256(db, project_id, sha256)
        if existing:
            existing.ref_count += 1
            # 旧记录回填：早期截图无分类/无上传人，随引用逐步归位
            if existing.category_id is None:
                existing.category_id = category_id
            if existing.created_by is None and user_id is not None:
                existing.created_by = user_id
                existing.updated_by = user_id
            db.commit()
            return existing.id

        storage_path = build_storage_path(sha256)
        physical = resolve_physical_path(storage_path)
        physical.parent.mkdir(parents=True, exist_ok=True)
        if not physical.exists():
            physical.write_bytes(png_bytes)
        obj = crud.create_file_record(
            db,
            project_id=project_id,
            name=name,
            original_name=name,
            content_type="image/png",
            size=len(png_bytes),
            sha256=sha256,
            storage_path=storage_path,
            category_id=category_id,
            user_id=user_id,
        )
        return obj.id
    except Exception as e:  # noqa: BLE001 截图是附加产物，失败不阻断执行
        print(f"[UI截图] 保存失败（忽略）: {e}")
        return None


class UiRuntime:
    """单条用例的浏览器运行时：一个 Chromium + 一个 Page 贯穿全 DAG。"""

    def __init__(self, db, env, context: ExecutionContext, project_id: int | None = None,
                 db_client: Any = None):
        self.db = db
        self.env = env
        self.context = context
        self.project_id = project_id
        self.db_client = db_client
        cfg = getattr(env, "browser_config", None) or {}
        self.config: dict = cfg if isinstance(cfg, dict) else {}
        self._playwright = None
        self._browser = None
        self._page = None

    # ---------- 浏览器生命周期 ----------
    @staticmethod
    def _proactor_policy_guard():
        """Windows + uvicorn --reload：uvicorn 会把进程 policy 设为
        WindowsSelectorEventLoopPolicy（uvicorn/loops/asyncio.py），而 SelectorEventLoop
        不支持 asyncio subprocess——playwright 用 new_event_loop() 启动 node driver
        会直接 NotImplementedError（报错「浏览器启动失败:」空消息）。
        返回 (guard, prev_policy)：guard=False 表示无需处理；调用方 finally 里恢复。"""
        if sys.platform != "win32":
            return False, None
        prev = asyncio.get_event_loop_policy()
        if isinstance(prev, asyncio.WindowsProactorEventLoopPolicy):
            return False, None
        # 临时切 Proactor：playwright 在 UI_SEMAPHORE 闸门内串行启动，
        # 该窗口内无其他 new_event_loop 调用方，切换-恢复进程级 policy 是安全的
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        return True, prev

    def ensure_browser(self):
        """惰性启动浏览器（首个 UI 节点触发）；playwright 缺失时业务级报错。"""
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise UiActionError(
                "playwright 未安装：pip install playwright && playwright install --with-deps chromium"
            ) from e

        UI_SEMAPHORE.acquire()
        self._semaphore_held = True
        restore, prev_policy = self._proactor_policy_guard()
        try:
            self._playwright = sync_playwright().start()
            viewport = self.config.get("viewport") or {"width": 1920, "height": 1080}
            launch_args = list(self.config.get("launch_args") or ["--disable-dev-shm-usage"])
            self._browser = self._playwright.chromium.launch(
                headless=bool(self.config.get("headless", True)),
                slow_mo=int(self.config.get("slow_mo_ms", 0)),
                args=launch_args,
            )
            browser_context = self._browser.new_context(viewport=viewport)
            self._inject_session_cookies(browser_context)
            self._page = browser_context.new_page()
            return self._page
        except UiActionError:
            self._release()
            raise
        except Exception as e:
            self._release()
            # repr 而非 str：部分异常（如 NotImplementedError）str 为空，导致
            # 「浏览器启动失败: 」这类无法定位的空错误
            raise UiActionError(f"浏览器启动失败: {type(e).__name__}: {e!r}") from e
        finally:
            if restore:
                asyncio.set_event_loop_policy(prev_policy)

    def _inject_session_cookies(self, browser_context):
        """会话注入：EnvTokenCache 的 token → cookie（单会话系统防互踢 + 免表单登录）。"""
        cookie_name = self.config.get("inject_token_cookie")
        if not cookie_name:
            return
        try:
            from .token_cache import EnvTokenCache
            token = EnvTokenCache.get(self.env.id)
            if token:
                browser_context.add_cookies([{
                    "name": cookie_name,
                    "value": token,
                    "url": self.env.base_url,
                }])
        except Exception as e:  # noqa: BLE001 注入失败降级为无 cookie（走页面登录）
            print(f"[UI会话] token cookie 注入失败（忽略）: {e}")

    def close(self):
        """收尾：关浏览器 + 停 playwright + 释放并发闸门（幂等，失败安全）。"""
        for target in (self._page, self._browser):
            if target is not None:
                try:
                    target.close()
                except Exception as e:  # noqa: BLE001
                    print(f"[UI清理] 关闭失败（忽略）: {e}")
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception as e:  # noqa: BLE001
                print(f"[UI清理] playwright 停止失败（忽略）: {e}")
        self._page = self._browser = self._playwright = None
        self._release()

    def _release(self):
        # 只在确实持锁后释放（ensure_browser 成功拿到信号量后任意路径都要归还）
        if getattr(self, "_semaphore_held", False):
            self._semaphore_held = False
            try:
                UI_SEMAPHORE.release()
            except ValueError:  # pragma: no cover 双重释放保护
                pass

    # ---------- 截图 ----------
    def take_screenshot(self) -> bytes | None:
        if self._page is None:
            return None
        try:
            return self._page.screenshot(full_page=False, type="png")
        except Exception as e:  # noqa: BLE001
            print(f"[UI截图] 截图失败（忽略）: {e}")
            return None

    # ---------- 表达式求值（${列名}/${环境变量} 等） ----------
    def _evaluate(self, value: Any) -> Any:
        if not isinstance(value, (str, dict, list)):
            return value
        engine = ExpressionEngine(self.context, self.db_client)
        return engine.evaluate(value)

    def _timeout_ms(self, params: dict) -> int:
        return int(params.get("timeout_ms") or self.config.get("timeout_ms") or _DEFAULT_TIMEOUT_MS)

    # ---------- 元素定位 ----------
    def _locator(self, params: dict):
        """element 配置 → locator。优先元素库引用（element_id），其次内联配置。
        定位值支持 ${变量} 求值（如行内按钮按 ${bl_no} 锁定所在行）。"""
        element = params.get("element")
        element_id = element.get("element_id") if isinstance(element, dict) else None
        if element_id:
            from .. import models
            obj = self.db.query(models.UiElement).filter(models.UiElement.id == int(element_id)).first()
            if not obj:
                raise UiActionError(f"元素库中不存在 element_id={element_id}")
            strategies = obj.strategies or {}
            desc = f"{obj.page_scope}.{obj.element_key}"
        else:
            strategies = _resolve_element_spec(self._page, element)
            desc = str(strategies)
        # 定位值里的 ${变量} 求值（变量池/数据行）
        strategies = {k: (self._evaluate(v) if isinstance(v, str) else v) for k, v in strategies.items()}
        locator = build_locator(self._page, strategies)
        # 多匹配时取第一个（宽松策略），避免 strict mode 直接报错
        return locator.first, desc

    def _element_text(self, locator) -> str | None:
        try:
            return locator.inner_text(timeout=1000)
        except Exception:  # noqa: BLE001 文本是附加产物
            return None

    # ---------- 动作执行 ----------
    def run_action(self, params: dict) -> dict:
        """执行单个 UI 动作，返回 facts（进 response_body，供提取/断言消费）。

        支持两种形态：
        - 单动作：{action, ...}（历史/简单节点）
        - 动作组：{steps: [{action, ...}, ...]}——页面级节点内组装多个动作，
          顺序执行、聚合 facts（steps 明细数组 + 末步公共字段），
          失败抛 UiActionError 并标注 [步骤N·动作]。
        """
        if not isinstance(params, dict):
            raise UiActionError("ui_params 需为对象")
        if isinstance(params.get("steps"), list):
            return self._run_steps(params["steps"])
        if not params.get("action"):
            raise UiActionError(
                "ui_params 需要 action 或 steps（基础动作 goto/click/fill/pick/select_option/check/"
                "press/wait/upload/date/type/screenshot/evaluate；组合动作 search/js_click/"
                "click_text/click_text_contains/row_button/scroll_bottom/confirm/confirm_wait/"
                "optional_confirm/popper_pick/toast_watch/save/uncheck_all；"
                "或 steps: [{action,...}] 组成页面级动作序列）")
        action = str(params["action"])
        timeout_ms = self._timeout_ms(params)
        page = self.ensure_browser()

        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            raise UiActionError(f"不支持的 UI 动作: {action}")
        result = handler(page, params, timeout_ms)

        facts: dict = {
            "action": action,
            "url": page.url,
            "title": self._safe_title(page),
            "status": "success",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        if isinstance(result, dict):
            facts.update(result)
        return facts

    # 页面导航瞬态（Execution context was destroyed）可安全重试的读类动作：
    # 无点击/输入副作用，重试不会重复业务操作；写类动作重试有双击风险，失败即报
    _NAV_RETRY_ACTIONS = {"evaluate", "wait", "toast_watch", "screenshot"}

    def _run_steps(self, steps: list) -> dict:
        """动作组：顺序执行子动作，聚合 facts。

        facts 结构 = 末步公共字段（url/title/...）+ steps: [每步 facts]，
        断言可走 $.steps[N].xxx 精确到步；子步骤不允许再嵌套 steps。
        """
        if not steps:
            raise UiActionError("动作组 steps 为空，请在节点配置中添加动作")
        results: list[dict] = []
        for i, sp in enumerate(steps, 1):
            if not isinstance(sp, dict) or not sp.get("action"):
                raise UiActionError(f"[步骤{i}] 缺少 action")
            if isinstance(sp.get("steps"), list):
                raise UiActionError(f"[步骤{i}] 动作组不允许嵌套 steps")
            try:
                results.append(self.run_action(sp))
            except UiActionError as e:
                # 携带已完成步骤明细（含子步骤已带出的 partial），报告侧还原失败现场
                carried = (e.partial or []) if isinstance(e.partial, list) else []
                raise UiActionError(f"[步骤{i}·{sp['action']}] {e}",
                                    partial=carried or results) from e
            except Exception as e:  # noqa: BLE001
                # 页面导航瞬态（业务保存后刷新页面打断 evaluate）：读类动作等新文档就绪后重试一次
                if (sp.get("action") in self._NAV_RETRY_ACTIONS
                        and "context was destroyed" in str(e)):
                    try:
                        page = self.ensure_browser()
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                        page.wait_for_timeout(800)
                        results.append(self.run_action(sp))
                        continue
                    except Exception:  # noqa: BLE001 重试仍失败按失败处理（带现场）
                        pass
                # 非 UI 动作语义失败（浏览器/导航异常）也包装并携带已完成步骤现场
                raise UiActionError(f"[步骤{i}·{sp['action']}] UI 执行异常: {e}",
                                    partial=results) from e
        # 公共字段取末步（页面终态），明细完整保留
        facts: dict = {**results[-1], "steps": results}
        return facts

    @staticmethod
    def _safe_title(page) -> str:
        try:
            return page.title()
        except Exception:  # noqa: BLE001
            return ""

    # ---------- 各动作实现 ----------
    def _do_goto(self, page, params, timeout_ms):
        url = self._evaluate(params.get("url") or params.get("value") or "")
        if not url:
            raise UiActionError("goto 需要 url（支持 ${变量}，相对路径自动拼 base_url）")
        if not str(url).startswith(("http://", "https://")):
            url = str(self.env.base_url).rstrip("/") + "/" + str(url).lstrip("/")
        wait_until = params.get("wait_for") or "load"
        if wait_until not in ("load", "domcontentloaded", "networkidle"):
            wait_until = "load"
        page.goto(str(url), wait_until=wait_until, timeout=timeout_ms)
        return {"url": page.url}

    def _do_click(self, page, params, timeout_ms):
        """点击元素。mode='js' 时走 JS 直调（绕过可点击性校验，替换原 js_click）。"""
        locator, desc = self._locator(params)
        if params.get("mode") == "js":
            # 复刻 base_page.click_by_js：被遮挡/固定列副本区/动画中的元素
            locator.wait_for(state="attached", timeout=timeout_ms)
            locator.evaluate("el=>el.click()")
            return {"target": desc, "via": "js"}
        locator.click(timeout=timeout_ms, force=bool(params.get("force", False)))
        return {"target": desc, "text": self._element_text(locator)}

    def _do_fill(self, page, params, timeout_ms):
        locator, desc = self._locator(params)
        value = self._evaluate(params.get("value"))
        if value is None or str(value) == "":
            # 数据驱动稀疏列：${变量} 求值为空 = 数据行未提供该字段 → 跳过不填
            # （原框架「数据里没有的键不填」的条件填空语义，静态步骤 + 稀疏行等价实现）
            return {"target": desc, "skipped": "empty-value"}
        locator.fill(str(value), timeout=timeout_ms)
        return {"target": desc, "value": value}

    def _do_type(self, page, params, timeout_ms):
        """真实键盘逐字输入（press_sequentially）：对无视程序化赋值的自定义组件，
        等价人工敲键——fill/execCommand 均被忽略时的终极手段"""
        locator, desc = self._locator(params)
        value = str(self._evaluate(params.get("value") or "")
                    ).replace("\r", "").replace("\n", "")
        if not value:
            return {"target": desc, "skipped": "empty-value"}
        locator.click(timeout=timeout_ms)
        locator.press_sequentially(value, delay=60, timeout=timeout_ms)
        return {"target": desc, "value": value}

    def _do_select_option(self, page, params, timeout_ms):
        locator, desc = self._locator(params)
        values = params.get("values") or ([params["value"]] if params.get("value") is not None else [])
        values = [str(self._evaluate(v)) for v in values if str(self._evaluate(v)) != ""]
        if not values:
            return {"target": desc, "skipped": "empty-value"}
        locator.select_option(values, timeout=timeout_ms)
        return {"target": desc, "value": values}

    def _do_check(self, page, params, timeout_ms):
        locator, desc = self._locator(params)
        raw = self._evaluate(params.get("value", True))
        s = str(raw).strip().lower() if raw is not None else ""
        if s in ("", "none", "0"):
            # 稀疏列/显式 0 = 不动复选框（原框架：数据为 '1' 才勾，其余值不碰）
            return {"target": desc, "skipped": "empty-value"}
        checked = s not in ("false", "no")
        method = locator.check if checked else locator.uncheck
        method(timeout=timeout_ms)
        return {"target": desc, "value": checked}

    def _do_press(self, page, params, timeout_ms):
        key = str(self._evaluate(params.get("value") or params.get("key") or "Enter"))
        if params.get("element"):
            locator, desc = self._locator(params)
            locator.press(key, timeout=timeout_ms)
            return {"target": desc, "value": key}
        page.keyboard.press(key)
        return {"value": key}

    def _do_wait(self, page, params, timeout_ms):
        ms = int(self._evaluate(params.get("value") or params.get("ms") or 1000))
        if params.get("element"):
            locator, desc = self._locator(params)
            locator.wait_for(state="visible", timeout=timeout_ms)
            return {"target": desc, "value": ms}
        page.wait_for_timeout(ms)
        return {"value": ms}

    def _do_upload(self, page, params, timeout_ms):
        """文件上传：value/files 支持逗号分隔多文件（原框架 upload_file 语义），
        一次性 set 到同一 input；文件引用支持 文件中心ID / 绝对路径 / 文件名
        （文件中心按 name 检索，兼容原框架 module files 目录的迁移数据）。
        ElementHandle 直设：Vue 重渲染会让 locator 的 stability 等待循环超时
        （34×resolved 实证），handle 一次解析后直接执行不受重渲染影响。"""
        raw_files = params.get("files") or ([params["value"]] if params.get("value") else [])
        resolved: list[str] = []
        for f in raw_files:
            s = str(self._evaluate(f)).strip()
            resolved.extend(p.strip() for p in s.split(",") if p.strip())
        if not resolved:
            return {"target": "upload", "skipped": "empty-value"}
        paths = [self._resolve_file_path(p) for p in resolved]
        locator, desc = self._locator(params)
        handle = locator.element_handle(timeout=timeout_ms)
        if handle is None:
            raise UiActionError(f"upload 未定位到文件输入框: {desc}")
        handle.set_input_files(paths)
        return {"target": desc, "value": paths}

    def _do_screenshot(self, page, params, timeout_ms):  # noqa: ARG002
        # 截图落库由 DagExecutor 统一处理（screenshot=always 时每步都存），这里只返回标记
        return {"screenshot": True}

    # ---------- 组合动作库（零 JS 编排层） ----------
    # 来源一：原框架 base_page 剩余封装（search / click_by_js / 显隐等待语义）
    # 来源二：生成子订单全链 13 轮实测沉淀的坑位模式（激活式检索 / vxe 固定列
    #         行内按钮 / 懒渲染滚动 / 延迟确认弹窗 / toast 真实断言 / 保存一体化）
    # 设计：每个动作单节点完成语义完整的交互，内置轮询/重试/值校验；
    #       失败抛 UiActionError 并携带页面现场（toasts/错误列/URL），无需用户再配 JS。

    def _retry_evaluate(self, page, js: str, arg, attempts: int, interval_ms: int):
        """短轮询重试执行 JS：每次返回非 falsy 即停（对抗渲染时序抖动）。"""
        last = None
        for _ in range(attempts):
            last = page.evaluate(js, arg)
            if last:
                return last
            page.wait_for_timeout(interval_ms)
        return last

    def _do_search(self, page, params, timeout_ms):
        """列表检索（筛选区模式，对齐原框架 base_page.search）：
        收起可见→点「重置」清缓存筛选，否则点「展开」→ 确保筛选项存在
        （默认「提单号」，缺失时经「更多筛选」下拉添加）→ 填入关键字 →
        点「查询」→ 等待含关键字的业务行出现（内置断言）。
        field 可选：筛选项字段名（默认 提单号）；
        element 可选：指定检索框元素时走旧的激活式检索框路径。
        注意：不能走顶部联想检索框——其联想面板的行也带 vxe-body--row
        class，会误报 found 且「查询」并不消费联想框关键字（run#667-670 实证：
        body 有关键字而列表 60 行无一命中）。"""
        keyword = self._evaluate(params.get("value"))
        if not keyword:
            raise UiActionError("search 需要 value（检索关键字，支持 ${变量}）")
        if params.get("element"):
            trigger, desc = self._locator(params)
            trigger.click(timeout=timeout_ms)
            page.wait_for_timeout(400)
            trigger.fill(str(keyword), timeout=timeout_ms)
            page.keyboard.press("Enter")
            page.wait_for_timeout(800)
        else:
            field = self._evaluate(params.get("field") or "") or "提单号"
            desc = f"筛选区[{field}]"
            # SPA 渲染就绪等待（远程环境页面加载需数秒，过早点击展开无效——
            # run#673/674/680/681 实证：未就绪时展开点击被吞，筛选项永不出现）
            page.get_by_role("button", name="查询").first.wait_for(
                state="visible", timeout=timeout_ms)
            page.wait_for_timeout(1500)

            def _click_label(text: str, wait_ms: int = 600) -> bool:
                # normalize-space 兼容文本节点前后空白；locator 点击失败时 JS 兜底
                loc = page.locator(f"xpath=//label[normalize-space(.)='{text}']")
                if loc.count() and loc.first.is_visible():
                    try:
                        loc.first.click(timeout=timeout_ms)
                    except Exception:  # noqa: BLE001 被遮挡等 → JS 点击兜底
                        loc.first.evaluate("e=>e.click()")
                    page.wait_for_timeout(wait_ms)
                    return True
                return False

            # 展开或重置（原框架 _handle_expand_button：页面有筛选缓存，收起态先重置；
            # 重置可能连带收起筛选区，故重置后再尝试展开）
            if not _click_label("收起"):
                _click_label("展开")
            else:
                page.locator(
                    "xpath=//button/span[text()='重置']/..").first.click(timeout=timeout_ms)
                page.wait_for_timeout(600)
                _click_label("展开")

            # 筛选区结构（run#679/686 实证）：div.search.flex-middle = 字段选择下拉
            # （首项文案「该项固定不可更改」）+ 值输入框；值输入框只有选中字段后
            # 才以字段名为 accessible-name 出现（= 原框架 role-name 策略原理）。
            # 注意 placeholder=字段名 的是顶部联想快搜框，查询按钮不消费其值。
            input_loc = self._filter_field_input(page, field)
            for _ in range(3):  # 页面加载竞态容错：字段渲染稍晚
                if input_loc.count():
                    break
                page.wait_for_timeout(1000)
                input_loc = self._filter_field_input(page, field)
            if not input_loc.count():
                # 字段未选中：先在筛选区的字段下拉中选择目标字段
                # （对齐原框架 _add_more_search_option + picker 语义）
                key_input = page.locator(
                    "xpath=(//div[@class='search flex-middle']/div[1]//input)[last()]")
                if not key_input.count():
                    # 筛选区可能藏在「更多筛选」里：打开再取字段下拉
                    page.locator(
                        "xpath=//button/span[text()='更多筛选']/..").first.click(
                            timeout=timeout_ms)
                    page.wait_for_timeout(600)
                    key_input = page.locator(
                        "xpath=(//div[@class='search flex-middle']/div[1]//input)[last()]")
                key_input.first.click(timeout=timeout_ms)
                if key_input.first.get_attribute("readonly") is None:
                    key_input.first.fill(str(field))
                page.wait_for_timeout(500)
                opt = page.get_by_role("listitem").filter(
                    has=page.get_by_text(str(field))).first
                opt.wait_for(state="visible", timeout=timeout_ms)
                opt.click(timeout=timeout_ms)
                page.keyboard.press("Escape")
                page.wait_for_timeout(600)
                input_loc = self._filter_field_input(page, field)
            if not input_loc.count():
                raise UiActionError(
                    f"筛选项「{field}」不可用（筛选区未展开或字段不存在）")
            # 激活式输入框：click 激活（readonly 解除）→ fill 自动等待可编辑
            input_loc.first.click(timeout=timeout_ms)
            page.wait_for_timeout(500)
            try:
                input_loc.first.fill(str(keyword), timeout=timeout_ms)
            except Exception as e:  # noqa: BLE001 激活失败/仍 readonly 的明确报错
                raise UiActionError(
                    f"筛选项「{field}」填入失败（激活式输入框未激活或不可编辑）: {e}") from e
            page.wait_for_timeout(500)
        page.get_by_role("button", name="查询").first.click(timeout=timeout_ms)
        # 命中判定排除联想/下拉弹层内的行（popper 内的 vxe 行会误报 found，
        # run#667-672 实证：联想面板有目标行而主表未过滤）
        result = page.evaluate(
            "kw=>new Promise(res=>{const t0=Date.now();const iv=setInterval(()=>{"
            "const main=r=>!r.closest('.el-select-dropdown,.el-popper,.el-dropdown,"
            ".el-autocomplete-suggestion,[class*=dropdown]');"
            "const tr=[...document.querySelectorAll('tr.vxe-body--row')]"
            ".find(r=>r.textContent.includes(kw)&&main(r));"
            "if(tr){clearInterval(iv);"
            "const rc=[...document.querySelectorAll('tr.vxe-body--row')].filter(main).length;"
            "const tv=!!(tr.offsetWidth||tr.offsetHeight||tr.getClientRects().length);"
            "const chain=[];let p=tr;for(let i=0;i<6&&p;i++){"
            "chain.push((p.className||'').toString().slice(0,36)||p.tagName);p=p.parentElement}"
            "res('found|rows='+rc+'|vis='+tv+'|chain='+chain.join('>'))}"
            "else if(Date.now()-t0>20000){clearInterval(iv);"
            "const fr=[...document.querySelectorAll('tr.vxe-body--row')].filter(main)"
            ".slice(0,2).map(r=>(r.textContent||'').replace(/\\s+/g,' ').slice(0,80));"
            "res('not-found|bodyHas='+document.body.innerText.includes(kw)"
            "+'|r1='+(fr[0]||'-')+'|r2='+(fr[1]||'-'))}},600)})",
            str(keyword))
        if not str(result).startswith("found"):
            raise UiActionError(
                f"检索 {keyword!r} 后 20s 内主表未见业务行（{result}）——"
                f"关键字错误/列表未加载/订单被默认筛选（如订单生效状态）排除")
        # 命中行可能不在首屏（列表未过滤出唯一行时 rows>1），后续 row_button
        # 需带 row=关键字 精确定位行
        rows_n = 0
        if "|rows=" in str(result):
            try:
                rows_n = int(str(result).split("|rows=")[1].split("|")[0])
            except (ValueError, IndexError):
                rows_n = 0
        return {"target": desc, "value": keyword, "result": "found",
                "rows": rows_n, "detail": result}

    def _filter_field_input(self, page, field: str):
        """筛选区字段输入框：原框架 search_value_input 策略——
        div.top > div.search.flex-middle 中包含 accessible-name=字段名 的
        textbox 的条目，取其直接 div 子级的 input。"""
        area = page.locator("//div[@class='top']/div[@class='search flex-middle']")
        return area.filter(
            has=page.get_by_role("textbox", name=str(field), exact=True)
        ).locator("xpath=./div[@class]").locator("input")

    def _do_js_click(self, page, params, timeout_ms):
        """兼容别名：等价 click(mode='js')（base_page.click_by_js）。"""
        return self._do_click(page, {**params, "mode": "js"}, timeout_ms)

    def _do_click_text(self, page, params, timeout_ms):
        """按文本点按钮/链接（空白归一化，兼容「保 存」「编 辑」），
        匹配 span/button/a 任意形态；找不到时轮询重试。
        match='contains' 按包含匹配（如 导入 → 导入报关费用，替换原 click_text_contains）。
        index 可选：同名按钮取第 N 个（0 起，如费用表的两个「新增标准费用」）。
        optional=true 无则跳过：按钮可能不存在的条件场景（如「作废」仅在有生效单证时
        出现），未找到返回 result=absent 不报错，后续步骤按需编排。"""
        text = self._evaluate(params.get("value"))
        if not text:
            raise UiActionError("click_text 需要 value（按钮文本，支持 ${变量}）")
        idx = int(params.get("index") or 0)
        optional = bool(params.get("optional"))
        if params.get("match") == "contains":
            js = ("t=>{const v=(e)=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);"
                  "const n=(x)=>(x.textContent||'').replace(/\\s+/g,'');"
                  "t=String(t).replace(/\\s+/g,'');"  # 目标文本归一化（「保 存」→「保存」）。不能走 n()：字符串无 textContent，||'' 兜底会把目标清成空串——includes('') 恒真误点首个按钮
                  "const b=[...document.querySelectorAll('button')].filter(v)"
                  ".find(b=>n(b).includes(t));"
                  "if(!b)return '';b.click();return 'clicked:'+n(b)}")
            result = self._retry_evaluate(page, js, str(text), 6, 500)
            if not result:
                if optional:
                    return {"value": text, "match": "contains", "optional": True, "result": "absent"}
                raise UiActionError(f"未找到文本包含 {text!r} 的可见按钮")
            return {"value": text, "match": "contains", "result": result}
        # 精确匹配：候选按"真实点击目标"去重——span 与其外层 button 同指一个目标，
        # 不去重时 index 会错位（run#601 实证：index=1 点中按钮内层 span）。
        # 去重后按元素语义排序：真 <button> > <a> > 裸 span（同名噪声多时优先
        # 真按钮——run#699 实证「保 存」38 候选中首个是无效 span）。
        # 可见性用 rect 判定：offsetParent 对 position:fixed（固定底栏的 提交/保存）
        # 恒为 null 会漏杀（业务订单编辑页实证）
        js = ("([t,i])=>{const v=(e)=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);"
              "const n=(x)=>(x.textContent||'').replace(/\\s+/g,'');"
              "t=String(t).replace(/\\s+/g,'');"  # 目标文本归一化（「保 存」「编 辑」）。不能走 n()：字符串无 textContent 会被清成空串——=== '' 永假、全页按钮失配
              # 排除禁用按钮：JS click 对 disabled 按钮无事件（run#700 实证
              # 点击后无任何 toast——费用表单校验未过时保存钮 disabled）
              "const all=[...document.querySelectorAll('span,button,a')]"
              ".filter(e=>n(e)===t&&v(e)&&!(e.tagName==='BUTTON'&&e.disabled)"
              "&&!e.closest('[class*=search],[class*=filter]'));"
              "const seen=new Set();const uniq=[];"
              "for(const e of all){const tgt=e.closest('button,a')||e;"
              "if(!seen.has(tgt)){seen.add(tgt);uniq.push(tgt)}}"
              "const rank=e=>e.tagName==='BUTTON'?0:(e.tagName==='A'?1:2);"
              "uniq.sort((a,b)=>rank(a)-rank(b));"
              "const s=uniq[i];"
              "if(!s)return '';s.click();"
              "return 'clicked:'+uniq.length}"
              )
        result = self._retry_evaluate(page, js, [str(text), idx], 6, 500)
        if not result:
            if optional:
                return {"value": text, "index": idx, "optional": True, "result": "absent"}
            raise UiActionError(f"未找到可见的文本为 {text!r} 的按钮/链接"
                                + (f"（第 {idx + 1} 个）" if idx else ""))
        return {"value": text, "index": idx, "result": result}

    def _do_click_text_contains(self, page, params, timeout_ms):
        """兼容别名：等价 click_text(match='contains')。"""
        return self._do_click_text(page, {**params, "match": "contains"}, timeout_ms)

    def _do_row_button(self, page, params, timeout_ms):
        """表格行内按钮点击：直接在 table tbody 内找归一化文本匹配的 button/a
        （对齐原框架 xpath 结构 tbody/tr/td/div/div/button 与 Playwright
        role-name 空白归一化语义，系统按钮文案为「详 情」带空格形态）。
        row 可选：限定包含该关键字的行内点击（检索后多行并存时精确定位，
        如 row=${bl_no}；给了 row 但无匹配行则报错，不静默兜底）。
        排坑实证（run#652-662）：全页面候选法会被侧边栏 logo（文本恰为
        「详情」）、vxe 复选框格（vxe-cell--title/--checkbox）、el-button--text
        类名误杀等连环坑干扰，必须限定 tbody 内真实交互元素直查。"""
        text = self._evaluate(params.get("value"))
        if not text:
            raise UiActionError("row_button 需要 value（行内按钮名，如 详情/编辑）")
        row_kw = self._evaluate(params.get("row") or "")
        url_before = page.url
        js = ("([t,kw])=>{const v=(e)=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);"
              "const n=(x)=>(x.textContent||'').replace(/\\s+/g,'');"
              # own-text 匹配（自身文本节点）+ 正向限定 vxe 表格容器内优先——
              # 页面「详情」噪声过多：侧边栏 logo/面包屑/页签(tags-view)关闭钮/
              # 分页 prev-next/复选框列 label 字面都是「详情」（run#652-698 实证）
              "const own=e=>{let s='';for(const c of e.childNodes)"
              "{if(c.nodeType===3)s+=c.textContent}return s.replace(/\\s+/g,'')};"
              "let btns=[...document.querySelectorAll('button,a,span')]"
              ".filter(e=>own(e)===String(t).replace(/\\s+/g,'')&&v(e)"
              "&&!e.closest('[class*=sidebar],.el-pagination,[class*=checkbox]'));"
              "const inTbl=btns.filter(e=>e.closest('[class*=vxe-table]'));"
              "if(inTbl.length)btns=inTbl;"
              "const inter=e=>e.closest('button,a');"
              "const tgtOf=e=>inter(e)||e;"
              # 语义排序：真 button > a > 裸 span（自营列表首候选是无效果 span，
              # run#712 实证点击不导航；真按钮在同候选池中优先）
              "const rank=e=>{const g=inter(e)||e;"
              "return g.tagName==='BUTTON'?0:(g.tagName==='A'?1:2)};"
              "btns.sort((a,b)=>rank(a)-rank(b));"
              "if(kw){const rows=[...document.querySelectorAll('tr')]"
              ".filter(r=>(r.textContent||'').includes(kw));"
              "const inKw=btns.filter(e=>rows.includes(e.closest('tr')));"
              "const vxeAll=[...document.querySelectorAll('tr.vxe-body--row')];"
              "const vxeKw=vxeAll.filter(r=>r.textContent.includes(kw));"
              "if(inKw.length){btns=inKw;}"
              # vxe 操作列是 div 渲染不在 tr 内（run#690 实证过滤后 tr 内按钮=1
              # 而页面级可见「详情」唯一）；关键字命中首行时页面级首个匹配按钮
              # 即该行按钮（主表+固定列副本会产生 2 个按钮，同属一行）
              "else if(vxeAll.length&&vxeKw.length&&btns.length"
              "&&vxeKw.includes(vxeAll[0])){}"
              "else{const fr=vxeAll.slice(0,2)"
              ".map(r=>(r.textContent||'').replace(/\\s+/g,' ').slice(0,90));"
              "return 'no-row:'+kw"
              "+'|tr='+document.querySelectorAll('tr').length"
              "+'|vxe='+vxeAll.length"
              "+'|bodyHas='+document.body.innerText.includes(kw)"
              "+'|btns='+btns.length"
              "+'|r1='+(fr[0]||'-')+'|r2='+(fr[1]||'-');}}"
              "const b=btns[0];"
              "if(!b)return '';"
              "const pool=btns.slice(0,4).map(e=>"
              "(e.className||'').toString().slice(0,30)+'#'+(e.parentElement?"
              "(e.parentElement.className||'').toString().slice(0,25):'')).join(' ; ');"
              "const cls=(b.className||'').toString().slice(0,60);"
              "tgtOf(b).click();return 'clicked|'+cls+'|pool='+pool}")
        # 显式轮询（不用 _retry_evaluate：no-row 诊断串是 truthy 会让其提前停，
        # 而表格重渲染晚于点击数秒是常态——run#687 实证诊断时行已含关键字）
        result = ""
        for _ in range(10):
            result = page.evaluate(js, [str(text), str(row_kw)])
            if result and not str(result).startswith("no-row:"):
                break
            page.wait_for_timeout(800)
        if not result:
            raise UiActionError(f"未找到行内按钮 {text!r}（行未出现或按钮不存在）")
        if str(result).startswith("no-row:"):
            raise UiActionError(
                f"行内按钮 {text!r}：未找到包含 {row_kw!r} 的行 [{result}]")
        return {"value": text, "row": row_kw or None, "result": result,
                "url_before": url_before}

    def _do_scroll_bottom(self, page, params, timeout_ms):  # noqa: ARG002
        """滚动到页面底部（含所有滚动容器）：激活懒渲染区（托书三件套类场景）。"""
        page.evaluate(
            "(()=>{window.scrollTo(0,document.body.scrollHeight);"
            "document.documentElement.scrollTop=1e9;"
            "[...document.querySelectorAll('div,main,section')].forEach(e=>{"
            "const s=getComputedStyle(e);"
            "if(/(auto|scroll)/.test(s.overflowY)&&e.scrollHeight>e.clientHeight)"
            "e.scrollTop=e.scrollHeight});return 'scrolled'})()")
        page.wait_for_timeout(600)
        return {"result": "scrolled"}

    def _do_confirm(self, page, params, timeout_ms):  # noqa: ARG002
        """自适应点弹窗主按钮，三种形态合一：
        - 默认：单次尝试主按钮（确定/确认/继续提交/提交/生效 择优），无弹窗返回 no-dialog
        - wait=true：轮询模式（弹窗延迟数秒出现时持续监视并点击，替换原 confirm_wait）
        - optional=true：只点「继续提交」类，无弹窗跳过返回 absent（替换原 optional_confirm）"""
        if params.get("wait"):
            return self._confirm_poll(page)
        if params.get("optional"):
            return self._confirm_optional(page)
        js = ("()=>{const t=(x)=>(x.textContent||'').replace(/\\s+/g,'');"
              "const btns=[...document.querySelectorAll("
              "'.el-message-box button,.el-dialog button,"
              "[class*=dialog] button,[class*=message-box] button')]"
              ".filter(b=>b.offsetParent);"
              "if(!btns.length)return 'no-dialog';"
              "const b=btns.find(x=>['确定','确认','继续提交','提交','生效'].includes(t(x)));"
              "if(b){b.click();return 'clicked:'+t(b)}"
              "return 'dialog-btns:'+btns.map(t).join(',')}")
        return {"result": page.evaluate(js)}

    @staticmethod
    def _confirm_poll(page):
        """轮询确认弹窗（弹窗常在 XHR 完成后延迟数秒才出现，单次确认会错过）：
        持续监视并点击 确定/确认，点过后再安静 1.5s 收工。
        已点过的按钮打标记不重复点（弹窗未关闭时防连环点击——单测实证）。"""
        js = ("()=>new Promise(res=>{let n=0,clicked=0,quiet=0;"
              "const iv=setInterval(()=>{n++;"
              "const btns=[...document.querySelectorAll("
              "'.el-message-box button,.el-dialog button,"
              "[class*=dialog] button,[class*=message-box] button')]"
              ".filter(b=>b.offsetParent);"
              "const b=btns.find(x=>['确定','确认','继续提交'].includes("
              "(x.textContent||'').replace(/\\s+/g,''))&&!x.dataset.__uiHit);"
              "if(b){b.click();b.dataset.__uiHit='1';clicked++;quiet=0}else{quiet++}"
              "if((clicked>0&&quiet>=3)||n>=14){clearInterval(iv);"
              "res('clicked:'+clicked)}},500)})")
        return {"result": page.evaluate(js)}

    @staticmethod
    def _confirm_optional(page):
        """可选弹窗继续（如箱号重复警告的「继续提交」）：有则点、无则跳过。"""
        js = ("()=>{const btns=[...document.querySelectorAll('button')]"
              ".filter(b=>b.offsetParent);"
              "const t=(x)=>(x.textContent||'').replace(/\\s+/g,'');"
              "const b=btns.find(x=>t(x).includes('继续提交'))"
              "||btns.find(x=>t(x)==='确定'&&x.closest("
              "'.el-message-box,.el-dialog,[class*=dialog],[class*=message]'));"
              "if(b){b.click();return 'clicked:'+t(b)}return 'absent'}")
        return {"result": page.evaluate(js)}

    def _do_confirm_wait(self, page, params, timeout_ms):  # noqa: ARG002
        """兼容别名：等价 confirm(wait=true)。"""
        return self._confirm_poll(page)

    def _do_optional_confirm(self, page, params, timeout_ms):  # noqa: ARG002
        """兼容别名：等价 confirm(optional=true)。"""
        return self._confirm_optional(page)

    def _do_popper_pick(self, page, params, timeout_ms):
        """浮层选项点选（如「编辑费用」下拉里的服务项）：轮询可见 popper
        中精确文本匹配的 li 并点击（下拉渲染有动画时序，一次性查找会落空）。"""
        val = self._evaluate(params.get("value"))
        if not val:
            raise UiActionError("popper_pick 需要 value（选项文本）")
        js = ("v=>new Promise(res=>{const t0=Date.now();const iv=setInterval(()=>{"
              "const pprs=[...document.querySelectorAll('[class*=popper]')]"
              ".filter(x=>x.offsetParent);"
              "for(const pp of pprs){const li=[...pp.querySelectorAll('li')]"
              ".find(l=>l.textContent.trim()===v);"
              "if(li){li.click();clearInterval(iv);res('picked')}}"
              "if(Date.now()-t0>8000){clearInterval(iv);res('no-li')}},300)})")
        result = page.evaluate(js, str(val))
        if result != "picked":
            raise UiActionError(f"8s 内未见浮层选项 {val!r}（下拉未打开或选项不存在）")
        return {"value": val, "result": result}

    def _do_toast_watch(self, page, params, timeout_ms):
        """轮询断言页面 toast：异步提交的成功提示需数秒才出现，
        且编辑页 URL 恒不变（不能作成功判据——假阳性教训）。
        三种模式：
        - 正向（默认）：命中期望文本 → ok；超时抛错并携带轮询期间出现过的全部 toast
          （含已消失的错误提示——业务真实报错 3s 即逝，只看超时时点会漏）。
        - absent=true 反向：观察窗内出现匹配提示即失败（「点击后不得弹提示」的
          inverted 断言，如生成费用通知单——任何 toast 都意味着失败）。value 可空 =
          任何 toast 都算命中；窗口静默 → clean 通过。
        - optional=true 宽容：超时未命中返回 no-toast 不报错（配 optional 类点击使用——
          按钮不存在时对应 toast 也不会有的条件场景）。
        toast 选择器兼容两族结构：Element 的 .el-message 与被测系统 div>p 直挂
        body 的提示（原框架 toast xpath=/html/body/div/p[text()] 实证）。"""
        expected = str(self._evaluate(params.get("value")) or "")
        absent = bool(params.get("absent"))
        optional = bool(params.get("optional"))
        if not expected and not absent:
            raise UiActionError("toast_watch 需要 value（期望的提示文本，如 保存成功）")
        window_ms = min(timeout_ms, 15000)
        js = ("([exp,abs,win])=>new Promise(res=>{const t0=Date.now();"
              "const seen=[];"
              "const all=()=>[...document.querySelectorAll("
              "'.el-message, body > div:not(#app) > p')]"
              ".map(e=>e.textContent.trim()).filter(Boolean);"
              "const iv=setInterval(()=>{const toasts=all();"
              "toasts.forEach(t=>{if(!seen.includes(t))seen.push(t)});"
              "const hit=exp?toasts.find(t=>t.includes(exp)):toasts[0];"
              "if(hit){clearInterval(iv);"
              "res(abs?('HIT '+hit.slice(0,60)):('ok:'+hit.slice(0,60)))}"
              "else if(Date.now()-t0>win){clearInterval(iv);"
              "res(abs?'CLEAN':('TIMEOUT toasts='+seen.join(' | ').slice(0,200)))"
              "}},400)})")
        result = str(page.evaluate(js, [expected, absent, window_ms]))
        if absent:
            if result.startswith("HIT"):
                raise UiActionError(
                    f"出现不应出现的提示（观察窗 {window_ms}ms 内应为静默"
                    + (f"，不得含「{expected}」" if expected else "，不得有任何提示")
                    + f"）: {result}")
            return {"value": expected, "absent": True, "result": "clean"}
        if result.startswith("TIMEOUT"):
            if optional:
                return {"value": expected, "optional": True, "result": "no-toast"}
            raise UiActionError(f"超时未出现提示「{expected}」（{result}）")
        return {"value": expected, "result": result}

    def _do_save(self, page, params, timeout_ms):
        """保存一体化（全链实测最险的坑位合集）：点保存 → 出现确认弹窗就点确定
        （弹窗常延迟数秒）→ 无任何反馈且保存按钮还在时每 2s 补点一次（对抗点击
        静默失效）→ 以 toast 命中为成功（URL 判据在编辑态恒真，不可用）。
        element 可选（默认按文本「保存」定位）；value 可选（期望 toast，默认 保存成功）。"""
        expected = str(self._evaluate(params.get("value")) or "保存成功")
        if params.get("element"):
            locator, desc = self._locator(params)
            locator.click(timeout=timeout_ms)
        else:
            js_click_save = ("(()=>{const t=(x)=>(x.textContent||'').replace(/\\s+/g,'');"
                             "const bs=[...document.querySelectorAll('button')]"
                             ".filter(b=>b.offsetParent&&t(b)==='保存');"
                             "if(bs[0]){bs[0].click();return 'clicked'}return 'no-btn'})()")
            clicked = page.evaluate(js_click_save)
            desc = "保存按钮(文本)"
            if clicked != "clicked":
                raise UiActionError("未找到可见的「保 存」按钮")
        js = ("exp=>new Promise(res=>{const t0=Date.now();"
              "const t=(x)=>(x.textContent||'').replace(/\\s+/g,'');"
              "const iv=setInterval(()=>{"
              "const toasts=[...document.querySelectorAll('.el-message')]"
              ".map(e=>e.textContent.trim());"
              "if(toasts.some(s=>s.includes(exp))){clearInterval(iv);res('ok:'+exp)}"
              "const dlgBtns=[...document.querySelectorAll("
              "'.el-message-box button,.el-dialog button')].filter(b=>b.offsetParent);"
              "const cf=dlgBtns.find(b=>['确定','确认'].includes(t(b))&&!b.dataset.__uiHit);"
              "if(cf){cf.click();cf.dataset.__uiHit='1'}"
              "const save=[...document.querySelectorAll('button')]"
              ".find(b=>b.offsetParent&&t(b)==='保存');"
              "if(save&&!dlgBtns.length&&((Date.now()-t0)%2000)<500){save.click()}"
              "if(Date.now()-t0>" + str(min(timeout_ms, 15000)) + "){clearInterval(iv);"
              "const errs=[...document.querySelectorAll('.el-form-item__error')]"
              ".filter(e=>e.offsetParent).map(e=>{const td=e.closest('td');"
              "const rid=(td&&td.closest('[rowid]'))?td.closest('[rowid]')"
              ".getAttribute('rowid'):'?';return rid+':'+(td?td.cellIndex:'?')})"
              ".slice(0,10).join(',');"
              "res('TIMEOUT toasts='+toasts.join('|').slice(0,100)+' errs='+errs)}"
              "},500)})")
        result = page.evaluate(js, expected)
        if str(result).startswith("TIMEOUT"):
            raise UiActionError(f"保存未成功（未出现「{expected}」提示）：{result}")
        return {"target": desc, "value": expected, "result": result}

    def _do_uncheck_all(self, page, params, timeout_ms):
        """批量取消勾选（element 定位复选框集合，如「无供应商」勾选列）。
        el-checkbox 的原生 input 隐藏（playwright uncheck 会超时），走 label 点击。"""
        locator, desc = self._locator(params)
        boxes = locator.all()
        unchecked = 0
        for box in boxes:
            try:
                hit = box.evaluate(
                    "el=>{if(el.checked){const l=el.closest('label,.el-checkbox');"
                    "if(l){l.click();return 1}}return 0}")
                unchecked += int(hit or 0)
            except Exception:  # noqa: BLE001 单个失败不阻断（行可能已重渲染）
                continue
        return {"target": desc, "unchecked": unchecked}

    def _do_pick(self, page, params, timeout_ms):
        """Element-UI 下拉选择（复刻原框架 base_page.picker 语义）：
        点击触发器 →（输入框非只读时先输入检索词）→ 点选匹配选项 → Esc 收起。
        value 支持字符串或字符串数组（多选）。
        """
        locator, desc = self._locator(params)
        raw = params.get("values") if isinstance(params.get("values"), list) else [params.get("value")]
        values = [str(self._evaluate(v)) for v in raw if str(self._evaluate(v)).strip() != ""]
        if not values:
            # 稀疏列：数据行未提供该下拉的字段值 → 跳过（原框架条件填空语义）
            return {"target": desc, "skipped": "empty-value"}
        picked = []
        for val in values:
            picked_ok = False
            last_seen = ""
            for _attempt in range(3):
                try:
                    # 清残留下拉（旧 popper 未关完会抢选项点击）。条件化：仅当确有
                    # 可见浮层时才按 Esc——无浮层时按 Esc 会冒泡关闭上层弹层
                    # （s4 费用编辑层，run#600 实证）
                    if page.evaluate(
                            "()=>[...document.querySelectorAll('[class*=popper]')]"
                            ".some(x=>x.offsetParent)"):
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(200)
                    try:
                        locator.click(timeout=min(timeout_ms, 8000))
                    except PlaywrightTimeoutError:
                        # 视口外/被遮挡的触发器（费用表下方行，run#588 实证）：force 兜底。
                        # 不用 scroll_into_view——费用表内层滚动容器滚动会关掉下拉浮层（run#599 实证）
                        locator.click(force=True, timeout=3000)
                    if locator.get_attribute("readonly", timeout=timeout_ms) is None:
                        locator.fill(val, timeout=timeout_ms)
                    # 选项点选用轮询+JS click：el-select 关闭后 popper 仍挂载（隐藏 li 与可见 li
                    # 文本重叠），且 fill 会触发选项列表重渲染——playwright click 会因
                    # 节点替换/遮挡陷入 stability 重试；轮询到首个可见匹配项后 JS click
                    page.wait_for_timeout(400)  # 等下拉动画/过滤稳定，旧 popper 关闭
                    try:
                        page.wait_for_function(
                            "v=>{const lis=[...document.querySelectorAll('li.el-select-dropdown__item')]"
                            ".filter(x=>x.offsetParent);"
                            "const li=lis.find(x=>x.textContent.trim()===v)"
                            "||lis.find(x=>x.textContent.trim().includes(v));"
                            "if(li){li.click();return true}return false}",
                            arg=val, timeout=min(timeout_ms, 5000))
                    except PlaywrightTimeoutError:
                        pass  # 未出现可见选项，走下方校验重试
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(250)
                except PlaywrightTimeoutError:
                    continue  # 本轮任一步超时，整体重试
                # 真选中校验：未选中时 Esc 会清空筛选文本，input 显示模型值（空）。
                # 匹配放宽为双向包含：数据（Excel）与选项文案允许有出入
                # （如数据'韩方浦'对应选项'韩方浦1'——历史 8 轮运行实证）
                last_seen = locator.input_value(timeout=timeout_ms) or ""
                if not last_seen:
                    # multiple/tags 形态 el-select：选中值渲染为 el-select__tags 内的
                    # tag 文本而非 input value（检索区「订单生效状态」筛选项实证）——
                    # input 恒空会误报未生效，取 tags 文本兜底校验
                    try:
                        last_seen = locator.evaluate(
                            "el=>{const box=el.closest('.el-select');"
                            "return box?(box.querySelector('.el-select__tags')||{})"
                            ".textContent||'':''}") or ""
                    except Exception:  # noqa: BLE001 取 tags 失败按原值走校验
                        last_seen = ""
                if last_seen and (val in last_seen or last_seen in val):
                    picked_ok = True
                    break
            if not picked_ok:
                raise UiActionError(
                    f"pick 选项未生效（3 次重试后 input 值仍为 {last_seen!r}，期望 {val!r}）")
            picked.append(val)
        return {"target": desc, "value": picked if len(picked) > 1 else picked[0]}

    def _do_date(self, page, params, timeout_ms):
        """Element-UI 日期时间选择（复刻原框架 base_page.timepicker 语义）：fill(值) + Enter"""
        locator, desc = self._locator(params)
        value = str(self._evaluate(params.get("value") or "")).replace("/", "-")
        if not value:
            return {"target": desc, "skipped": "empty-value"}
        locator.fill(value, timeout=timeout_ms)
        locator.press("Enter", timeout=timeout_ms)
        return {"target": desc, "value": value}

    def _do_evaluate(self, page, params, timeout_ms):  # noqa: ARG002
        script = params.get("value") or params.get("script")
        if not script:
            raise UiActionError("evaluate 需要 value（JS 表达式，支持 ${变量} 注入）")
        result = page.evaluate(str(self._evaluate(script)))
        return {"result": result}

    def _do_custom(self, page, params, timeout_ms):  # noqa: ARG002
        """自定义动作（项目级 JS 模板）：custom_id 引用 custom_actions.script，
        函数体入参 args = 步骤 value（${变量} 求值后），return 值进 facts.result。"""
        cid = params.get("custom_id")
        if cid is None:
            raise UiActionError("custom 需要 custom_id（自定义动作库中维护）")
        from .. import models
        ca = self.db.query(models.CustomAction).filter(models.CustomAction.id == int(cid)).first()
        if not ca:
            raise UiActionError(f"自定义动作不存在 id={cid}（可能已被删除，请重新选择）")
        script = (ca.script or "").strip()
        if not script:
            raise UiActionError(f"自定义动作「{ca.name}」脚本为空")
        args = self._evaluate(params.get("value"))
        try:
            result = page.evaluate("args => {" + script + "\n}", args)
        except Exception as e:  # noqa: BLE001
            raise UiActionError(f"自定义动作「{ca.name}」执行失败: {e}") from e
        return {"custom": ca.name, "result": result}

    def _resolve_file_path(self, spec: Any) -> str:
        """上传文件解析：整数/数字串 → 文件中心 test_files.storage_path；
        绝对路径原样；相对文件名 → 文件中心按 name 检索（承接原框架
        module files 目录的迁移数据，文件预先导入文件中心即可）。"""
        spec = self._evaluate(spec)
        s = str(spec)
        if s.isdigit():
            from .. import models
            from .file_helpers import resolve_physical_path
            f = self.db.query(models.TestFile).filter(models.TestFile.id == int(s)).first()
            if not f:
                raise UiActionError(f"文件中心不存在文件 id={s}")
            return str(resolve_physical_path(f.storage_path))
        if os.path.isabs(s):
            return s
        from .. import models
        from .file_helpers import resolve_physical_path
        f = (self.db.query(models.TestFile)
             .filter(models.TestFile.project_id == self.project_id,
                     models.TestFile.name == s)
             .order_by(models.TestFile.id.desc()).first())
        if f:
            return str(resolve_physical_path(f.storage_path))
        raise UiActionError(
            f"上传文件无法解析: {s!r}（文件中心无此名称文件，且非绝对路径/id）")
