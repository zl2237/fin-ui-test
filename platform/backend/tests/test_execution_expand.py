"""执行展开：绑定多选数据集 × 全 sheet 展开（2026-11-12 B3 删链定案）。

seam：
- dataset_service.plan_case_expansion：展开计划纯读函数（每个 bound/选中
  数据集的每个 sheet 一条 item，多场景由此承接，替代旧链模式「每轮瞬移」）
- crud.executions.create_execution：dataset 快照落 record（失败可溯源是哪套数据）
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.crud import executions as exec_domain
from app.services import dataset_service as svc


def _ds(rows, columns=None, case_id=11, ds_id=7, name="运单数据"):
    return SimpleNamespace(id=ds_id, case_id=case_id, name=name,
                           rows=rows)


def _rows(n, labels=None, ds_id=7):
    """labels=None → 全部历史行（label=None，走回退）；否则按行序给真名"""
    out = []
    for i in range(1, n + 1):
        lab = None if labels is None else labels[i - 1]
        out.append(SimpleNamespace(id=i, dataset_id=ds_id, row_index=i, label=lab,
                                   data={"bl_no": f"BL{i:03d}"}))
    return out


class TestPlanCaseExpansion:
    def test_unbound_case_rejected(self):
        """无 bound 数据集 → 拒绝执行（入参无默认值兜底，全空参数无意义）"""
        case = SimpleNamespace(id=11)
        with patch.object(svc.crud, "list_bound_datasets", return_value=[]):
            with pytest.raises(ValueError, match="未绑定数据集"):
                svc.plan_case_expansion(SimpleNamespace(), case)

    def test_bound_expands_every_sheet(self):
        """单 bound 数据集多 sheet → 每 sheet 一条 item（全 sheet 展开承接多场景）；
        历史行 label 回退「数据集名 第N行」"""
        case = SimpleNamespace(id=11)
        rows = _rows(3)
        with patch.object(svc.crud, "list_bound_datasets", return_value=[_ds(rows)]), \
             patch.object(svc.crud, "list_rows", return_value=rows):
            plan = svc.plan_case_expansion(SimpleNamespace(), case)
        assert len(plan) == 3
        assert [(p["row"]["row_index"], p["row"]["data"]["bl_no"]) for p in plan] == \
            [(1, "BL001"), (2, "BL002"), (3, "BL003")]
        assert plan[1]["row"]["label"] == "运单数据 第2行"

    def test_single_sheet_label_has_no_suffix(self):
        """单 sheet 数据集 label 不带行号后缀（一行无歧义，保持简洁）"""
        case = SimpleNamespace(id=11)
        rows = _rows(1)
        with patch.object(svc.crud, "list_bound_datasets", return_value=[_ds(rows)]), \
             patch.object(svc.crud, "list_rows", return_value=rows):
            plan = svc.plan_case_expansion(SimpleNamespace(), case)
        assert len(plan) == 1
        assert plan[0]["row"]["label"] == "运单数据"

    def test_real_label_wins_over_legacy_suffix(self):
        """有真 sheet 名：row.label 用真名（${label.字段} 引用的稳定锚点）"""
        case = SimpleNamespace(id=11)
        rows = _rows(2, labels=["正常单", "退款单"])
        with patch.object(svc.crud, "list_bound_datasets", return_value=[_ds(rows)]), \
             patch.object(svc.crud, "list_rows", return_value=rows):
            plan = svc.plan_case_expansion(SimpleNamespace(), case)
        assert [p["row"]["label"] for p in plan] == ["正常单", "退款单"]

    def test_multi_bound_each_expands_own_sheets(self):
        """多 bound 数据集 → 各按自己的 sheet 数展开；item.sheets 只携带
        本数据集的全 sheet（不跨数据集混，${sheet.字段} 引用不串台）"""
        case = SimpleNamespace(id=11)
        ds7 = _ds(_rows(2, labels=["A1", "A2"], ds_id=7), ds_id=7, name="场景A")
        ds8 = _ds(_rows(1, ds_id=8), ds_id=8, name="场景B")
        rows_by_ds = {7: ds7.rows, 8: ds8.rows}
        with patch.object(svc.crud, "list_bound_datasets", return_value=[ds7, ds8]), \
             patch.object(svc.crud, "list_rows",
                          side_effect=lambda db, did: rows_by_ds[did]):
            plan = svc.plan_case_expansion(SimpleNamespace(), case)
        assert [(p["dataset_id"], p["row"]["label"]) for p in plan] == \
            [(7, "A1"), (7, "A2"), (8, "场景B")]
        assert [s["label"] for s in plan[0]["sheets"]] == ["A1", "A2"]
        # sheets 清单回退 Sheet{row_index}（与 row 快照的数据集名回退不同源）
        assert [s["label"] for s in plan[2]["sheets"]] == ["Sheet1"]

    def test_sheets_carries_all_rows_with_fallback_labels(self):
        """sheets 携带全部行（${sheet.字段} 全 sheet 注入源）；历史行 label
        回退 Sheet{row_index}（与迁移回填一致）"""
        case = SimpleNamespace(id=11)
        rows = _rows(3, labels=["正常单", None, "退款单"])
        with patch.object(svc.crud, "list_bound_datasets", return_value=[_ds(rows)]), \
             patch.object(svc.crud, "list_rows", return_value=rows):
            plan = svc.plan_case_expansion(SimpleNamespace(), case)
        assert plan[0]["sheets"] == [
            {"row_index": 1, "label": "正常单", "data": {"bl_no": "BL001"}},
            {"row_index": 2, "label": "Sheet2", "data": {"bl_no": "BL002"}},
            {"row_index": 3, "label": "退款单", "data": {"bl_no": "BL003"}},
        ]

    def test_row_index_pins_single_sheet(self):
        """row_index 显式选行（执行面板单发）：只发该 sheet 一条，sheets 仍带全量
        （引擎 ${sheet.字段} 可引用非选中 sheet）"""
        case = SimpleNamespace(id=11)
        rows = _rows(3, labels=["正常单", "退款单", "取消单"])
        with patch.object(svc.crud, "list_bound_datasets", return_value=[_ds(rows)]), \
             patch.object(svc.crud, "list_rows", return_value=rows):
            plan = svc.plan_case_expansion(SimpleNamespace(), case, row_index=2)
        assert len(plan) == 1
        assert plan[0]["row"] == {"row_index": 2, "data": {"bl_no": "BL002"},
                                  "label": "退款单"}
        assert len(plan[0]["sheets"]) == 3

    def test_row_index_out_of_range_rejected(self):
        """row_index 不存在 → 拒绝并列出现有 sheet（手填/数据已删时的明确报错）"""
        case = SimpleNamespace(id=11)
        rows = _rows(2)
        with patch.object(svc.crud, "list_bound_datasets", return_value=[_ds(rows)]), \
             patch.object(svc.crud, "list_rows", return_value=rows):
            with pytest.raises(ValueError, match=r"没有第 9 个 sheet（现有：1\(Sheet1\)、2\(Sheet2\)）"):
                svc.plan_case_expansion(SimpleNamespace(), case, row_index=9)

    def test_zero_rows_rejected(self):
        """bound 但数据集无数据 → 拒绝执行（先在数据集页完成入参配置）"""
        case = SimpleNamespace(id=11)
        with patch.object(svc.crud, "list_bound_datasets", return_value=[_ds([])]), \
             patch.object(svc.crud, "list_rows", return_value=[]):
            with pytest.raises(ValueError, match="无数据行"):
                svc.plan_case_expansion(SimpleNamespace(), case)

    def test_explicit_dataset_ids_override_binding(self):
        """显式 dataset_ids（执行面板换数据集/方案成员多选）：按名单展开，
        不读用例绑定"""
        case = SimpleNamespace(id=11)
        rows = _rows(2, labels=["A1", "A2"])
        with patch.object(svc.crud, "get_dataset", return_value=_ds(rows)) as g, \
             patch.object(svc.crud, "list_bound_datasets") as lb, \
             patch.object(svc.crud, "list_rows", return_value=rows):
            plan = svc.plan_case_expansion(SimpleNamespace(), case, dataset_ids=[7])
        assert [p["row"]["label"] for p in plan] == ["A1", "A2"]
        g.assert_called_once()
        lb.assert_not_called()

    def test_other_case_dataset_rejected(self):
        """显式指定的数据集属于别的用例 → 拒（用例间隔离）"""
        case = SimpleNamespace(id=11)
        with patch.object(svc.crud, "get_dataset", return_value=_ds(_rows(2), case_id=99)):
            with pytest.raises(ValueError, match="不属于该用例|隔离"):
                svc.plan_case_expansion(SimpleNamespace(), case, dataset_ids=[7])

    def test_bound_dataset_missing_rejected(self):
        """显式指定的数据集不存在（防御）→ 明确报错而非静默单条"""
        case = SimpleNamespace(id=11)
        with patch.object(svc.crud, "get_dataset", return_value=None):
            with pytest.raises(ValueError, match="数据集不存在"):
                svc.plan_case_expansion(SimpleNamespace(), case, dataset_ids=[7])


class TestRowMapExpansion:
    """row_map 子集展开（执行面板「按 sheet 选择执行」弹窗，2026-11-12）：
    {dataset_id: [row_index...]} 圈定哪几个数据集的哪几个 sheet，临时生效"""

    def test_multi_dataset_sheet_subset(self):
        """两个数据集各选部分 sheet → 只展开所选；sheets 仍携带该数据集全量
        （${sheet.字段} 引用不因圈定而缺命名空间）"""
        case = SimpleNamespace(id=11)
        ds7 = _ds(_rows(3, labels=["A1", "A2", "A3"], ds_id=7), ds_id=7, name="场景A")
        ds8 = _ds(_rows(2, labels=["B1", "B2"], ds_id=8), ds_id=8, name="场景B")
        rows_by_ds = {7: ds7.rows, 8: ds8.rows}
        ds_by_id = {7: ds7, 8: ds8}
        with patch.object(svc.crud, "get_dataset",
                          side_effect=lambda db, did: ds_by_id[did]), \
             patch.object(svc.crud, "list_rows",
                          side_effect=lambda db, did: rows_by_ds[did]), \
             patch.object(svc.crud, "list_bound_datasets") as lb:
            plan = svc.plan_case_expansion(SimpleNamespace(), case,
                                           row_map={7: [1, 3], 8: [2]})
        assert [(p["dataset_id"], p["row"]["label"]) for p in plan] == \
            [(7, "A1"), (7, "A3"), (8, "B2")]
        assert [s["label"] for s in plan[0]["sheets"]] == ["A1", "A2", "A3"]
        lb.assert_not_called()  # 圈定即选择集，不读绑定

    def test_unbound_dataset_picks_work(self):
        """圈定未 bound 的数据集也合法（临时跑非绑定数据，与旧单发口径一致）"""
        case = SimpleNamespace(id=11)
        ds8 = _ds(_rows(1, labels=["B1"], ds_id=8), ds_id=8, name="场景B")
        with patch.object(svc.crud, "get_dataset", return_value=ds8), \
             patch.object(svc.crud, "list_rows", return_value=ds8.rows), \
             patch.object(svc.crud, "list_bound_datasets") as lb:
            plan = svc.plan_case_expansion(SimpleNamespace(), case, row_map={8: [1]})
        assert [p["row"]["label"] for p in plan] == ["B1"]
        lb.assert_not_called()

    def test_pick_misses_all_rows_rejected(self):
        """某数据集名单内的 row_index 全不存在 → 报错列出现有 sheet"""
        case = SimpleNamespace(id=11)
        rows = _rows(2)
        with patch.object(svc.crud, "get_dataset", return_value=_ds(rows)), \
             patch.object(svc.crud, "list_rows", return_value=rows):
            with pytest.raises(ValueError, match=r"所选 sheet 无一存在（现有：1\(Sheet1\)、2\(Sheet2\)）"):
                svc.plan_case_expansion(SimpleNamespace(), case, row_map={7: [9]})

    def test_empty_row_indexes_rejected(self):
        """某数据集给了空名单 → 同样按选不到报错（防手滑清空后误发全量）"""
        case = SimpleNamespace(id=11)
        rows = _rows(2)
        with patch.object(svc.crud, "get_dataset", return_value=_ds(rows)), \
             patch.object(svc.crud, "list_rows", return_value=rows):
            with pytest.raises(ValueError, match="所选 sheet 无一存在"):
                svc.plan_case_expansion(SimpleNamespace(), case, row_map={7: []})

    def test_foreign_dataset_rejected(self):
        """圈定了别的用例的数据集 → 拒（用例间隔离）"""
        case = SimpleNamespace(id=11)
        with patch.object(svc.crud, "get_dataset",
                          return_value=_ds(_rows(2), case_id=99)):
            with pytest.raises(ValueError, match="不属于该用例|隔离"):
                svc.plan_case_expansion(SimpleNamespace(), case, row_map={7: [1]})

    def test_empty_map_rejected(self):
        """row_map 为空 dict → 未选择任何数据集/sheet（显式报错，不回落绑定全量）"""
        case = SimpleNamespace(id=11)
        with patch.object(svc.crud, "list_bound_datasets") as lb:
            with pytest.raises(ValueError, match="未选择任何数据集/sheet"):
                svc.plan_case_expansion(SimpleNamespace(), case, row_map={})
        lb.assert_not_called()


class TestSetCaseBinding:
    """绑定整组替换（PUT /testcases/{id}/dataset-binding 背后）"""

    def _db(self, datasets, case_id=11):
        """替身 db：query(DataSet).filter(case_id ==).all() 按归属过滤"""
        return SimpleNamespace(
            query=lambda m: SimpleNamespace(
                filter=lambda *a, **k: SimpleNamespace(
                    all=lambda: [d for d in datasets if d.case_id == case_id])),
            commit=lambda: None)

    def test_whole_replace_sets_bound_flags(self):
        """名单内置 True、名单外置 False（整组替换语义）"""
        ds7, ds8, ds9 = _ds([], ds_id=7), _ds([], ds_id=8), _ds([], ds_id=9)
        svc.set_case_binding(self._db([ds7, ds8, ds9]), SimpleNamespace(id=11), [7, 9])
        assert (ds7.bound, ds8.bound, ds9.bound) == (True, False, True)

    def test_empty_list_unbinds_all(self):
        """空列表 = 全部解绑（用例将不可执行，执行强绑定口径）"""
        ds7, ds8 = _ds([], ds_id=7), _ds([], ds_id=8)
        svc.set_case_binding(self._db([ds7, ds8]), SimpleNamespace(id=11), [])
        assert (ds7.bound, ds8.bound) == (False, False)

    def test_foreign_dataset_rejected(self):
        """名单含别的用例的数据集 → 拒绝"""
        ds7 = _ds([], ds_id=7, case_id=99)
        with pytest.raises(ValueError, match="不属于该用例"):
            svc.set_case_binding(self._db([ds7]), SimpleNamespace(id=11), [7])


class TestRecordSnapshot:
    def test_create_execution_persists_dataset_snapshot(self):
        """create_execution 落 dataset_id + dataset_row 快照（历史记录保留当次真实数据）"""
        captured = {}

        def fake_add(obj):
            captured["rec"] = obj

        db = SimpleNamespace(add=fake_add, commit=lambda: None, refresh=lambda o: None)
        rec = exec_domain.create_execution(
            db, case_id=1, env_id=2, user_id=3,
            dataset_id=7, dataset_row={"row_index": 2, "data": {"bl_no": "BL002"}, "label": "BL002"})
        assert captured["rec"].dataset_id == 7
        assert captured["rec"].dataset_row["row_index"] == 2
        assert rec is captured["rec"]

    def test_create_execution_without_dataset_unchanged(self):
        """未传快照：record 的 dataset 字段为 None（现状回归）"""
        captured = {}

        def fake_add(obj):
            captured["rec"] = obj

        db = SimpleNamespace(add=fake_add, commit=lambda: None, refresh=lambda o: None)
        exec_domain.create_execution(db, case_id=1, env_id=2, user_id=3)
        assert captured["rec"].dataset_id is None
        assert captured["rec"].dataset_row is None


class TestBatchExecuteCounts:
    """批量执行次数（counts）与并发数（concurrency）校验：路由层在触达 db 前完成参数检查"""

    def _call(self, counts, concurrency=4):
        from app.routers.executions import batch_execute
        from app.schemas import BatchExecutionCreate

        return batch_execute(
            BatchExecutionCreate(case_ids=[1, 2, 3], env_id=1, counts=counts, concurrency=concurrency),
            db=None, user=None)

    def test_counts_length_mismatch_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as e:
            self._call([1, 2])  # 3 个用例只给 2 个次数
        assert e.value.status_code == 400
        assert "一致" in e.value.detail

    def test_counts_out_of_range_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as e:
            self._call([1, 0, 2])  # 0 次非法
        assert e.value.status_code == 400
        assert "1~9999" in e.value.detail

    def test_counts_over_limit_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as e:
            self._call([10000, 1, 1])  # 超过上限 9999（仅防手滑）
        assert e.value.status_code == 400

    def test_counts_large_but_within_limit_passes(self):
        """100 次循环这类大次数合法（原 20 上限已放开）"""
        from fastapi import HTTPException

        with patch("app.routers.executions.crud.get_testcase", return_value=None):
            with pytest.raises(HTTPException) as e:
                self._call([100, 1, 1])
        assert e.value.status_code == 404  # 通过参数校验，停在用例检查

    def test_concurrency_out_of_range_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as e:
            self._call([1, 1, 1], concurrency=0)
        assert e.value.status_code == 400
        assert "1~16" in e.value.detail

        with pytest.raises(HTTPException) as e:
            self._call([1, 1, 1], concurrency=17)
        assert e.value.status_code == 400

    def test_concurrency_one_passes_validation(self):
        """并发数 1（串行）合法，继续走到用例检查"""
        from fastapi import HTTPException

        with patch("app.routers.executions.crud.get_testcase", return_value=None):
            with pytest.raises(HTTPException) as e:
                self._call([1, 1, 1], concurrency=1)
        assert e.value.status_code == 404

    def test_valid_counts_passes_validation_and_fails_on_case(self):
        """合法 counts 通过参数校验，继续走到用例检查（无 db 时在用例处被拦即可证明顺序）"""
        from fastapi import HTTPException

        with patch("app.routers.executions.crud.get_testcase", return_value=None):
            with pytest.raises(HTTPException) as e:
                self._call([3, 1, 2])  # 用户示例：A×3 B×1 C×2
        assert e.value.status_code == 404  # 用例不存在：参数校验已放行
