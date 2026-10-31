# -*- coding: utf-8 -*-
"""UI 浏览器槽位泄漏回收（exec1009 实录：两个卡死线程占满 2 槽，后续执行 600s 排队
后全废）。覆盖：登记/注销、terminate 定向回收、终态自愈扫描、双放保护与幂等。
不启动真浏览器：信号量手动 acquire 模拟卡死占位，runtime 用最小桩对象。"""
import types

import pytest

from app.services import ui_runtime as ur


class _FakeRuntime:
    def __init__(self):
        self._semaphore_held = True


class _SeqDb:
    """query(...).filter(...).first() 链桩：按调用次序回放状态。

    force_release 的自愈扫描逐 holder 查一次记录（注册序），
    用迭代器按序回放 terminated/running 即可，无需真 SQLAlchemy 条件求值。"""

    def __init__(self, states):
        self._states = iter(states)

    def query(self, model):  # noqa: ANN001
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return types.SimpleNamespace(status=next(self._states, "running"))


@pytest.fixture(autouse=True)
def _clean_registry():
    """只清注册表；信号量收支由各测试自平衡（BoundedSemaphore 封顶初始值，
    只会欠不会溢，欠额正是被测的泄漏语义，不能在 fixture 里凭空补）。"""
    ur._UI_HOLDERS.clear()
    yield
    ur._UI_HOLDERS.clear()


def _slot_free() -> bool:
    got = ur.UI_SEMAPHORE.acquire(timeout=1)
    if got:
        ur.UI_SEMAPHORE.release()
    return got


def test_force_release_by_exec_id():
    assert ur.UI_SEMAPHORE.acquire(timeout=1), "前置：拿一个槽模拟卡死线程占位"
    rt = _FakeRuntime()
    ur.register_ui_holder(rt, 4242)

    freed = ur.force_release_ui_holders(exec_ids=[4242])

    assert freed == 1
    assert rt._semaphore_held is False    # 僵尸线程日后走到 _release() 不会双放
    assert _slot_free(), "回收后槽位应立即可用"
    assert id(rt) not in ur._UI_HOLDERS
    assert ur.force_release_ui_holders(exec_ids=[4242]) == 0  # 幂等：已注销


def test_force_release_skips_other_executions():
    rt1, rt2 = _FakeRuntime(), _FakeRuntime()
    ur.register_ui_holder(rt1, 1)
    ur.register_ui_holder(rt2, 2)

    freed = ur.force_release_ui_holders(exec_ids=[1])

    # rt1 未真占槽：release 会被 BoundedSemaphore 拒绝（超放），标志回滚、不计数
    assert freed == 0
    assert rt1._semaphore_held is True and rt2._semaphore_held is True
    assert id(rt1) in ur._UI_HOLDERS and id(rt2) in ur._UI_HOLDERS


def test_sweep_releases_terminal_only():
    assert ur.UI_SEMAPHORE.acquire(timeout=1), "前置：拿一个槽模拟卡死线程占位"
    rt_dead, rt_live = _FakeRuntime(), _FakeRuntime()
    ur.register_ui_holder(rt_dead, 10)   # 注册序 = 扫描查询序
    ur.register_ui_holder(rt_live, 11)
    db = _SeqDb(["terminated", "running"])

    freed = ur.force_release_ui_holders(db=db)

    assert freed == 1
    assert rt_dead._semaphore_held is False
    assert rt_live._semaphore_held is True      # running 的持有者不动
    assert id(rt_live) in ur._UI_HOLDERS        # 活持有者保留登记
    assert id(rt_dead) not in ur._UI_HOLDERS
    assert _slot_free()


def test_sweep_without_db_is_noop():
    rt = _FakeRuntime()
    ur.register_ui_holder(rt, 99)
    assert ur.force_release_ui_holders(db=None) == 0   # 无 db/无 exec_id 不猜
    assert rt._semaphore_held is True
    assert id(rt) in ur._UI_HOLDERS


def test_unregister_on_release_keeps_registry_clean():
    rt = _FakeRuntime()
    ur.register_ui_holder(rt, 77)
    ur._unregister_ui_holder(rt)
    assert ur.force_release_ui_holders(exec_ids=[77]) == 0  # 已注销：无处可回收
