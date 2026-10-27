"""把 autotest-playwright 原始 Excel 严格迁移为平台数据集 sheet（幂等，可重跑）。

背景（2026-10-27 数据集 Excel 化后按用户要求重新迁移）：
    原框架语义（utils/data_helper.py）＝ 一个 xlsx 文件 = 一个场景数据集
    （行1 场景名 / 行2 key·description·value 表头 / 行3 起字段行，第二列描述，
    合并单元格表达分组与嵌套）；页面变体是同目录兄弟文件。
    首次迁移的三处偏差（本次修正）：
    1. 委托订单/自营费用只搬了部分变体且丢了差异字段 → 现按变体文件逐个成 sheet；
    2. entrusted_order_edit.xlsx 的 66 个 bl_no 字段被逐个炸成 66 个 sheet
       → 现恢复为 1 个 sheet「编辑自营项目」66 字段；
    3. service_project 嵌套对象被拍平成 service_project_json 字符串
       → 现按解析结果原样保留对象（引擎单占位符传原生 dict，custom 10 兼容）。

映射规则（用户 2026-10-27 确认）：
    - 每个源 xlsx → 1 个 sheet：label=场景名，data=get_testdata 解析结果原样
      （嵌套 rows/分组保持对象），field_desc=Excel 描述列，field_order=字段行序；
    - relied_* 依赖链键剔除（平台 DAG 已取代依赖链，剔除后网格只留业务字段）；
    - order_self_fee_add 各变体 bl_no 原值为空 → 保留空值，描述列追加注记
      「由依赖链生成，独立执行前请先填现有单号」；
    - 草稿单巡检仅严格镜像：节点 278-n1 检索值改 ${编辑自营项目.bl_no1}
      （一次执行巡 1 单，想巡哪单改引用序号）；
    - 全链路 283/287 的数据行是六阶段 Excel 按前缀合并的产物（节点即按它生成），
      不再重读源文件：保留现第 1 行为唯一 sheet（剔除 relied 键），删除复制行。

用法（platform/backend 目录下）：
    python scripts/migrate_excel_datasets.py [--dry-run]
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AUTOTEST_ROOT = Path(os.environ.get(
    "AUTOTEST_ROOT", r"D:\CODE\PyCharm\pythonProject\autotest-playwright"))

sys.path.insert(0, str(AUTOTEST_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from openpyxl import load_workbook  # noqa: E402

from utils.data_helper import get_testdata  # noqa: E402  (autotest-playwright)

from app.database import SessionLocal  # noqa: E402
from app.models import CaseNodeConfig, DataSet, DataSetRow  # noqa: E402

# relied_* 依赖链键 / 全链路合并行的 s<N>_relied_* 前缀键 → 剔除
RELIED_KEY = re.compile(r"^(s\d+_)?relied_")

# order_self_fee_add 各变体 bl_no 为空的注记（描述列追加）
BL_NO_NOTE = "由依赖链生成，独立执行前请先填现有单号"


def sheet_from_excel(xlsx: Path, bl_no_note: bool = False) -> dict:
    """一个源 xlsx → 一个 sheet 形态 {label, data, field_desc, field_order}。

    get_testdata 保证与原框架逐字段同语义（含合并单元格分组/嵌套）；描述列
    直接读原表第二列（get_testdata 不返回描述），只对出现在解析结果顶层的
    键取值。relied_* 键剔除（用户确认，平台 DAG 已取代依赖链）。
    """
    td = get_testdata(str(xlsx), absolute_path=True)
    if len(td) != 1:
        raise ValueError(f"{xlsx.name}: 期望单场景文件，实际 {len(td)} 个数据集: {list(td)}")
    label, ds = next(iter(td.items()))

    # 描述列：跳过场景名行(行1)与 key/description 表头行，取 顶层键 → 第二列
    desc: dict[str, str] = {}
    wb = load_workbook(xlsx, data_only=True)
    ws = wb[wb.sheetnames[0]]
    for row in ws.iter_rows(max_col=2):
        key = row[0].value
        d = row[1].value
        if key is None or d is None:
            continue
        key, d = str(key).strip(), str(d).strip()
        if key.lower() == "key" or key == label or key in desc:
            continue
        desc[key] = d
    wb.close()

    data = {k: v for k, v in ds.items() if not RELIED_KEY.match(k)}
    field_desc = {k: v for k, v in desc.items() if k in data and v}
    if bl_no_note and "bl_no" in data and not str(data.get("bl_no") or "").strip():
        field_desc["bl_no"] = f"{field_desc.get('bl_no', '提单号')}；{BL_NO_NOTE}"
    return {
        "label": label,
        "data": data,
        "field_desc": field_desc,
        "field_order": list(data.keys()),  # get_testdata 顶层键序 = Excel 字段行序
    }


def variant_sheets(pattern: str, bl_no_note: bool = False) -> list[dict]:
    """按变体文件批量构建 sheet：with_all_project 主场景置首，其余按文件名序。"""
    files = sorted(AUTOTEST_ROOT.glob(pattern))
    if not files:
        raise FileNotFoundError(f"{AUTOTEST_ROOT} 下未找到: {pattern}")
    files.sort(key=lambda p: (0 if "with_all_project" in p.stem else 1, p.name))
    return [sheet_from_excel(f, bl_no_note) for f in files]


def keep_single_sheet(db, dataset_id: int, label: str) -> dict:
    """全链路类：保留现第 1 行为唯一 sheet（节点即按它生成），剔除 relied 键。"""
    rows = (db.query(DataSetRow)
              .filter(DataSetRow.dataset_id == dataset_id)
              .order_by(DataSetRow.row_index).all())
    if not rows:
        raise ValueError(f"dataset {dataset_id} 无数据行，无法保留")
    first = rows[0]
    data = {k: v for k, v in (first.data or {}).items() if not RELIED_KEY.match(k)}
    return {
        "label": label,
        "data": data,
        "field_desc": {k: v for k, v in (first.field_desc or {}).items()
                       if k in data and v},
        "field_order": list(data.keys()),
    }


def replace_dataset_rows(db, dataset_id: int, sheets: list[dict]) -> None:
    """整删整插（与服务层 replace_rows 同语义；脚本内直接写库）。"""
    db.query(DataSetRow).filter(DataSetRow.dataset_id == dataset_id).delete()
    for i, s in enumerate(sheets, start=1):
        db.add(DataSetRow(
            dataset_id=dataset_id, row_index=i,
            label=s["label"], data=s["data"],
            field_desc=s["field_desc"] or None,
            field_order=s["field_order"] or None,
        ))


def patch_node(db, case_id: int, node_id: str, replacements: dict[str, str]) -> None:
    """节点 ui_params 内的步骤值整串替换（如 ${service_project_json}→${service_project}）。"""
    cfg = (db.query(CaseNodeConfig)
             .filter(CaseNodeConfig.case_id == case_id,
                     CaseNodeConfig.node_id == node_id).first())
    if not cfg:
        raise ValueError(f"case {case_id} 节点 {node_id} 不存在")
    blob = json.dumps(cfg.ui_params, ensure_ascii=False)
    changed = []
    for old, new in replacements.items():
        if old in blob:
            blob = blob.replace(old, new)
            changed.append(old)
    cfg.ui_params = json.loads(blob)
    print(f"  节点 case{case_id}/{node_id}: {changed or '无变化'}")


def main() -> None:
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        plan = [
            # dataset_id, 说明, sheets 构建器
            (150, "添加委托订单 ← entrusted_order_add_*.xlsx ×7",
             lambda: variant_sheets(
                 "module/ordermanage/entrustedorderadd/data/entrusted_order_add_*.xlsx")),
            (155, "添加自营费用 ← order_self_fee_add_*.xlsx ×7",
             lambda: variant_sheets(
                 "module/ordermanage/orderselfdetails/data/order_self_fee_add_*.xlsx",
                 bl_no_note=True)),
            (156, "草稿单巡检 ← entrusted_order_edit.xlsx ×1（66 字段恢复为 1 sheet）",
             lambda: [sheet_from_excel(
                 AUTOTEST_ROOT / "module/dataprocess/data/entrusted_order_edit.xlsx")]),
            (159, "全链路 283 ← 保留现第 1 行为唯一 sheet（剔除 relied 键、删复制行）",
             lambda: [keep_single_sheet(db, 159, "全链路·包含所有服务项目")]),
            (167, "全链路到对账 287 ← 同上",
             lambda: [keep_single_sheet(db, 167, "全链路到对账·包含所有服务项目")]),
        ]
        for ds_id, desc, build in plan:
            ds = db.get(DataSet, ds_id)
            if not ds:
                raise ValueError(f"dataset {ds_id} 不存在")
            sheets = build()
            print(f"== #{ds_id} {ds.name}: {desc}")
            for s in sheets:
                print(f"   sheet「{s['label']}」{len(s['data'])} 字段")
            if not dry:
                replace_dataset_rows(db, ds_id, sheets)

        if not dry:
            # 节点引用联动（2 处，均为整串占位符替换）
            patch_node(db, 277, "n3", {"${service_project_json}": "${service_project}"})
            patch_node(db, 278, "n1", {"${bl_no}": "${编辑自营项目.bl_no1}"})
            db.commit()
            print("\n已提交。")
        else:
            print("\n[dry-run] 未写库。")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
