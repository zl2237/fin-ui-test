"""执行编排（execution launcher）：单套值展开 → 建记录 → 批量提交的唯一入口。

- build_launch_plan：一个用例的一次发射计划（可与其他 plan 合并后一次 commit）
- commit_launch：把若干 plan 平铺为一份 specs 提交线程池

调用方只剩两类：executions 路由（手动/批量，concurrency 可配）与 scheduler
（定时触发，默认并发）。新触发来源只需调用这两个函数即可接入全部语义。

环境严格绑定（2026-10-15 定案）：执行环境是用例属性（case.env_id），
本模块不再接收环境参数——普通用例未绑定环境抛 ValueError，由调用方决定 4xx 或跳过；

"""
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .. import crud
from ..crud import executions as exec_domain
from ..engine.runner import (
    DEFAULT_CONCURRENCY,
    ExecutionSpec,
    submit_batch_execution,
)
from . import dataset_service


@dataclass
class LaunchPlan:
    """一个用例（× run_count 轮）的发射计划。commit 前可与其他 plan 合并。"""

    records: list = field(default_factory=list)
    specs: list[ExecutionSpec] = field(default_factory=list)


def build_launch_plan(db: Session, case, user_id: int, *,
                      trigger_type: str = "manual",
                      dataset_id: int | None = None,
                      dataset_row_index: int | None = None,
                      run_count: int = 1,
                      plan_id: int | None = None) -> LaunchPlan:
    """规划一个用例的一次发射：展开 → 建记录 → 组装 specs。

    数据集不可执行（无数据/不存在）或用例未绑定环境抛 ValueError，由调用方决定 4xx 或跳过。
    单套语义：绑定数据集恒展开 1 条（该数据集唯一一套数据）；
    run_count>1 时复用一次规划重复提交（run_count 次执行）。"""
    if not getattr(case, "env_id", None):
        raise ValueError(f"用例「{case.name}」未绑定执行环境，请先在用例编辑中选择")
    if not crud.get_environment(db, case.env_id):
        raise ValueError(f"用例「{case.name}」绑定的环境已不存在（id={case.env_id}），请重新绑定")
    plan_items = dataset_service.plan_case_expansion(
        db, case, dataset_id=dataset_id, row_index=dataset_row_index)

    # 执行记录与 spec 的环境：用例绑定环境
    launch_env_id = case.env_id

    launch = LaunchPlan()
    for _ in range(run_count):
        for item in plan_items:
            record = exec_domain.create_execution(db, case_id=case.id, env_id=launch_env_id,
                                                  user_id=user_id, trigger_type=trigger_type,
                                                  dataset_id=item["dataset_id"],
                                                  dataset_row=item["row"], plan_id=plan_id)
            launch.records.append(record)
            launch.specs.append(ExecutionSpec(
                execution_id=record.id,
                case_id=case.id,
                env_id=launch_env_id,
                dataset_row=(item["row"] or {}).get("data"),
                dataset_sheets=[{"label": s["label"], "data": s["data"]}
                                for s in (item.get("sheets") or [])],
            ))

    for record in launch.records:
        crud.fill_audit_names(db, record)
        crud.fill_exec_names(db, record)
    return launch


def commit_launch(plans: list[LaunchPlan],
                  concurrency: int = DEFAULT_CONCURRENCY) -> None:
    """提交若干 plan（非阻塞）：全部 specs 平铺进一个批次专用线程池，
    concurrency=1 串行、>1 并行（环境为每 spec 自带，批次可混环境）。"""
    specs = [spec for plan in plans for spec in plan.specs]
    if specs:
        submit_batch_execution(specs, concurrency=concurrency)


# ============ 并发上限按用例类型收敛（2026-10-31 定案） ============
# 平台两级并发：批次线程池 concurrency（1~MAX_CONCURRENCY=16）管线程数；
# UI 执行另有进程级浏览器闸门 UI_SEMAPHORE（默认 2，环境变量
# UI_BROWSER_CONCURRENCY 覆盖）——每个 UI 执行独占一个 Chromium 槽位，
# 超出槽位数的并行 UI 执行 acquire 排队，UI_ACQUIRE_TIMEOUT_S（默认 600s）
# 等不到即整条作废。配置期按槽位数收敛，而不是执行期排队超时。


def ui_concurrency_cap() -> int:
    """UI 用例的有效并发上限 = 浏览器槽位数（进程级常量，lazy 读避免链式 import）。"""
    from .ui_runtime import UI_BROWSER_CONCURRENCY
    return max(1, int(UI_BROWSER_CONCURRENCY))


def case_ids_with_ui_nodes(db: Session, case_ids: list[int]) -> set[int]:
    """case_ids 中含 UI 节点（case_node_configs.step_type='ui'）的用例 id 集。"""
    ids = sorted({c for c in case_ids if c})
    if not ids:
        return set()
    from .. import models
    rows = db.query(models.CaseNodeConfig.case_id).filter(
        models.CaseNodeConfig.case_id.in_(ids),
        models.CaseNodeConfig.step_type == "ui").distinct().all()
    return {r[0] for r in rows}


def validate_concurrency_for_cases(db: Session, concurrency: int,
                                   case_ids: list[int]) -> None:
    """并发数按成员用例类型收敛：含 UI 用例 → 并发 ≤ 浏览器槽位数，超出抛 ValueError。

    通用上限（1~16）由调用方先行校验；concurrency=1 恒通过（串行无槽位竞争）。
    覆盖三入口：方案保存/成员替换（配置期提示）、方案执行（预检兜底，含定时）、
    手动单发/批量执行。"""
    if concurrency <= 1:
        return
    if not case_ids_with_ui_nodes(db, case_ids):
        return
    cap = ui_concurrency_cap()
    if concurrency > cap:
        raise ValueError(
            f"并发数 {concurrency} 超出 UI 用例支撑上限 {cap}"
            f"（浏览器槽位 UI_BROWSER_CONCURRENCY，同时存活的 Chromium 数；"
            f"超出的 UI 执行会排队、10 分钟等不到槽位即作废）。"
            f"成员含 UI 用例时并发请 ≤ {cap}，或把 UI 用例拆到单独方案串行跑")

