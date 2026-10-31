# -*- coding: utf-8 -*-
"""并发上限按用例类型收敛（2026-10-31）：

两级并发模型——批次线程池 concurrency（1~16）与进程级浏览器闸门
UI_SEMAPHORE（默认 2）。含 UI 用例的并发必须 ≤ 浏览器槽位数，
配置期拦截（plans 保存/成员替换）+ 执行预检（run_plan）+ 批量执行入口三处同款。
"""
import pytest

import app.services.ui_runtime as ui_runtime_mod
from app.services.execution_launcher import (
    case_ids_with_ui_nodes,
    ui_concurrency_cap,
    validate_concurrency_for_cases,
)


class FakeDb:
    """只支持 case_ids_with_ui_nodes 所需形态的 Session 替身。"""

    def __init__(self, ui_case_ids):
        self.rows = [(c,) for c in ui_case_ids]

    def query(self, _model):
        db = self

        class _Q:
            def filter(self, *a, **kw):
                return self

            def distinct(self):
                return self

            def all(self):
                return db.rows

        return _Q()


@pytest.fixture
def cap2(monkeypatch):
    monkeypatch.setattr(ui_runtime_mod, "UI_BROWSER_CONCURRENCY", 2)


def test_ui_cap_reads_runtime_constant(cap2):
    assert ui_concurrency_cap() == 2


def test_ui_cap_floors_at_one(monkeypatch):
    monkeypatch.setattr(ui_runtime_mod, "UI_BROWSER_CONCURRENCY", 0)
    assert ui_concurrency_cap() == 1


def test_case_ids_with_ui_nodes_filters_and_dedups():
    db = FakeDb([7, 7, 9])
    assert case_ids_with_ui_nodes(db, [5, 7, 9, None, 7]) == {7, 9}
    assert case_ids_with_ui_nodes(db, []) == set()


def test_api_only_cases_allow_full_concurrency(cap2):
    db = FakeDb([])  # 无 UI 节点
    validate_concurrency_for_cases(db, 16, [1, 2, 3])  # 不抛


def test_ui_case_rejects_concurrency_above_cap(cap2):
    db = FakeDb([3])
    with pytest.raises(ValueError, match="UI"):
        validate_concurrency_for_cases(db, 3, [1, 2, 3])


def test_ui_case_at_cap_passes(cap2):
    db = FakeDb([3])
    validate_concurrency_for_cases(db, 2, [1, 2, 3])  # 不抛


def test_serial_concurrency_always_passes(cap2):
    db = FakeDb([1])
    validate_concurrency_for_cases(db, 1, [1])  # 串行无槽位竞争
