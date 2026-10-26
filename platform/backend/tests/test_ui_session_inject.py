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
        browser_config={"inject_token_cookie": "Admin-Token"} if inject else {},
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
