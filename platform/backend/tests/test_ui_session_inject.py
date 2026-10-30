"""UI 会话注入单测：EnvTokenCache → cookie，空缓存走 API 管线 shared 登录兜底。

回归背景（execution 867）：后端重启清空 EnvTokenCache，套件首个节点是 UI
节点时无 API 节点先登录 → 静默无 cookie → 整轮落登录页。修复后空缓存
借 build_http_client + login() 登录入缓存（与 API 节点同路径）。
不依赖 playwright：直接调 _inject_session_cookies，浏览器上下文用假对象。
"""
from types import SimpleNamespace

import app.services.runtime_service as runtime_service
from app.services.token_cache import EnvTokenCache
from app.services.ui_runtime import UiRuntime

TEST_ENV_ID = 987654  # 专用 env id，避免污染真实环境缓存


class FakeContext:
    """记录 add_cookies 调用的假 BrowserContext。"""

    def __init__(self):
        self.cookies = []

    def add_cookies(self, cookies):
        self.cookies.extend(cookies)


def _runtime(inject=True):
    env = SimpleNamespace(
        id=TEST_ENV_ID,
        base_url="http://test.local",
        browser_config=(
            {"inject_token_cookie": "Admin-Token", "login_detect_ms": 300} if inject else {}
        ),
    )
    return UiRuntime(db=None, env=env, context=None, project_id=1)


def setup_function(_):
    EnvTokenCache.invalidate(TEST_ENV_ID)


def teardown_function(_):
    EnvTokenCache.invalidate(TEST_ENV_ID)


def test_cached_token_injected_without_login(monkeypatch):
    """缓存已有 token：直接注入，不触发登录（复用既有的登录成果）。"""
    EnvTokenCache._tokens[TEST_ENV_ID] = "cached-token"  # noqa: SLF001 直接写测试缓存
    called = []
    monkeypatch.setattr(runtime_service, "build_http_client",
                        lambda env: called.append("build") or SimpleNamespace())
    monkeypatch.setattr(runtime_service, "login", lambda client, env: called.append("login"))

    ctx = FakeContext()
    _runtime()._inject_session_cookies(ctx)

    assert [c["name"] for c in ctx.cookies] == ["Admin-Token"]
    assert ctx.cookies[0]["value"] == "cached-token"
    assert called == []  # 有缓存绝不重复登录


def test_empty_cache_falls_back_to_shared_login(monkeypatch):
    """空缓存：构造 API client 走 login()（同 API 节点路径），成功后注入新 token。"""
    def fake_login(client, env):
        EnvTokenCache._tokens[TEST_ENV_ID] = "fresh-token"  # noqa: SLF001
    monkeypatch.setattr(runtime_service, "build_http_client",
                        lambda env: SimpleNamespace(fake="client"))
    monkeypatch.setattr(runtime_service, "login", fake_login)

    ctx = FakeContext()
    _runtime()._inject_session_cookies(ctx)

    assert [c["value"] for c in ctx.cookies] == ["fresh-token"]


def test_login_failure_degrades_to_no_cookie(monkeypatch):
    """兜底登录失败（未配登录/密码错）：不抛异常，降级为无 cookie。"""
    def boom(client, env):
        raise RuntimeError("登录失败：HTTP 401")
    monkeypatch.setattr(runtime_service, "build_http_client", lambda env: SimpleNamespace())
    monkeypatch.setattr(runtime_service, "login", boom)

    ctx = FakeContext()
    _runtime()._inject_session_cookies(ctx)  # 不应抛出

    assert ctx.cookies == []


def test_no_cookie_config_skips_everything(monkeypatch):
    """未配 inject_token_cookie：不查缓存也不登录（原行为不变）。"""
    called = []
    monkeypatch.setattr(runtime_service, "build_http_client",
                        lambda env: called.append("build"))

    ctx = FakeContext()
    _runtime(inject=False)._inject_session_cookies(ctx)

    assert ctx.cookies == []
    assert called == []


# ---------- goto 登录页重定向自动恢复（execution 888/889 回归） ----------

class FakePage:
    """假 Page：url 可变，goto 切换预设 URL；wait_for_timeout 后重定向落地。

    urls 语义：[0] 当前 URL；goto 弹出队首并显示下一个；wait_for_timeout
    再弹出下一个（模拟 SPA 在 load 事件之后一拍才跳登录页的真实时序）。
    """

    def __init__(self, urls, pwd_visible=False):
        self._urls = list(urls)
        self.goto_calls = []
        self.pwd_visible = pwd_visible

    @property
    def url(self):
        return self._urls[0]

    def goto(self, url, wait_until="load", timeout=0):
        self.goto_calls.append(url)
        self.pwd_visible = False  # 重新导航后登录表单消失（有效会话下不再渲染）
        if len(self._urls) > 1:
            self._urls.pop(0)

    def wait_for_timeout(self, ms):
        if len(self._urls) > 1:
            self._urls.pop(0)

    def locator(self, selector):
        return SimpleNamespace(first=SimpleNamespace(
            is_visible=lambda: self.pwd_visible))


def test_login_redirect_triggers_relogin_recovery(monkeypatch):
    """goto 落登录页：清缓存重登 → context 重注 cookie → 重 goto → 标记恢复。"""
    def fake_login(client, env):
        EnvTokenCache._tokens[TEST_ENV_ID] = "fresh-token"  # noqa: SLF001
    monkeypatch.setattr(runtime_service, "build_http_client", lambda env: SimpleNamespace())
    monkeypatch.setattr(runtime_service, "login", fake_login)
    EnvTokenCache._tokens[TEST_ENV_ID] = "stale-kicked-token"  # noqa: SLF001

    rt = _runtime()
    ctx = FakeContext()
    rt._context = ctx  # noqa: SLF001 模拟 ensure_browser 已保存 context
    # 落地登录页 → 恢复后 goto 回目标页
    page = FakePage(["http://test.local/#/login?redirect=%2Fdev", "http://test.local/#/dev/order"])

    assert rt._recover_from_login_redirect(
        page, "http://test.local/#/dev/order", "load", 15000) is True
    # 3d84139：re-goto 前先 about:blank 换文档，强制 SPA 重新读 cookie
    assert page.goto_calls == ["about:blank", "http://test.local/#/dev/order"]
    assert [c["value"] for c in ctx.cookies] == ["fresh-token"]  # 新 token 已注入
    assert EnvTokenCache.get(TEST_ENV_ID) == "fresh-token"  # 旧缓存被顶替


def test_no_recovery_when_target_is_login_page(monkeypatch):
    """目标本身就是登录页（测登录流程的用例）：不恢复不登录。"""
    called = []
    monkeypatch.setattr(runtime_service, "build_http_client",
                        lambda env: called.append("build"))
    rt = _runtime()
    page = FakePage(["http://test.local/#/login"])

    assert rt._recover_from_login_redirect(
        page, "http://test.local/#/login", "load", 15000) is False
    assert called == [] and page.goto_calls == []


def test_no_recovery_without_inject_config():
    """未配 inject_token_cookie：即便落登录页也不干预（无登录体系的系统）。"""
    rt = _runtime(inject=False)
    page = FakePage(["http://test.local/#/login?redirect=%2F"])

    assert rt._recover_from_login_redirect(
        page, "http://test.local/#/dev", "load", 15000) is False


def test_relogin_failure_raises_clear_error(monkeypatch):
    """重登失败：抛带「登录页」字样的明确错误，而非元素定位超时。"""
    def boom(client, env):
        raise RuntimeError("登录失败：HTTP 401")
    monkeypatch.setattr(runtime_service, "build_http_client", lambda env: SimpleNamespace())
    monkeypatch.setattr(runtime_service, "login", boom)

    from app.services.ui_runtime import UiActionError
    rt = _runtime()
    rt._context = FakeContext()  # noqa: SLF001
    page = FakePage(["http://test.local/#/login?redirect=%2Fdev"])

    try:
        rt._recover_from_login_redirect(page, "http://test.local/#/dev", "load", 15000)
        raise AssertionError("应当抛 UiActionError")
    except UiActionError as e:
        assert "登录页" in str(e) and "自动重登失败" in str(e)


def test_still_login_after_relogin_raises(monkeypatch):
    """重登后仍被跳登录页（账号被禁/密码改了）：明确报错而非静默循环。"""
    def fake_login(client, env):
        EnvTokenCache._tokens[TEST_ENV_ID] = "token-but-account-broken"  # noqa: SLF001
    monkeypatch.setattr(runtime_service, "build_http_client", lambda env: SimpleNamespace())
    monkeypatch.setattr(runtime_service, "login", fake_login)

    from app.services.ui_runtime import UiActionError
    rt = _runtime()
    rt._context = FakeContext()  # noqa: SLF001
    page = FakePage(["http://test.local/#/login?redirect=%2Fdev", "http://test.local/#/login"])

    try:
        rt._recover_from_login_redirect(page, "http://test.local/#/dev", "load", 15000)
        raise AssertionError("应当抛 UiActionError")
    except UiActionError as e:
        assert "仍被重定向到登录页" in str(e)


def test_password_input_dom_signal_triggers_recovery(monkeypatch):
    """URL 未翻转但密码框已可见（实测早 URL 0.5s）：DOM 信号也要触发恢复。"""
    def fake_login(client, env):
        EnvTokenCache._tokens[TEST_ENV_ID] = "fresh-token"  # noqa: SLF001
    monkeypatch.setattr(runtime_service, "build_http_client", lambda env: SimpleNamespace())
    monkeypatch.setattr(runtime_service, "login", fake_login)

    rt = _runtime()
    ctx = FakeContext()
    rt._context = ctx  # noqa: SLF001
    # URL 全程停在目标页，但密码框可见（登录表单先渲染、路由后跳的真实时序）
    page = FakePage(["http://test.local/#/dev/order",
                     "http://test.local/#/dev/order"], pwd_visible=True)

    assert rt._recover_from_login_redirect(
        page, "http://test.local/#/dev/order", "load", 15000) is True
    assert [c["value"] for c in ctx.cookies] == ["fresh-token"]


def test_login_check_runs_once_per_runtime(monkeypatch):
    """一次执行只检测一次：首次未命中后，同 runtime 后续 goto 不再空转检测窗。"""
    rt = _runtime()
    page1 = FakePage(["http://test.local/#/dev/order"])
    page2 = FakePage(["http://test.local/#/login?redirect=%2Fdev"])

    assert rt._recover_from_login_redirect(
        page1, "http://127.0.0.1:8000/x/#/dev/order", "load", 15000) is False
    # 第二次即便真的落了登录页也不再触发（保持既有行为：恢复成功后会话已新鲜）
    assert rt._recover_from_login_redirect(
        page2, "http://test.local/#/dev/order2", "load", 15000) is False
    assert page2.goto_calls == []
