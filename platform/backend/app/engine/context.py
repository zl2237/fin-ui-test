"""执行上下文 v2：节点命名空间变量注册表（2026-09-30 参数模型定案）。

取代旧「row_vars/suite_vars 双域池 + extracted 统一池 dict.update 覆盖」：
- 套件上游白名单注入 __suite__ 伪命名空间
- 断点续跑 seed 注入各前缀节点命名空间（报告虚拟上下文）
- 节点运行时产出（参数解析结果 / 后置提取 / SQL 参数结果）写入各自节点命名空间
- 同名冲突三场景从根上消除：引用结构化携带 {"node_id", "var_path"}
- API 参数侧：数据集行不再以平铺键值参与解析（2026-09-30 入参收敛定案：
  行数据承载各节点 params 配置，跨节点共享值改引用上游产出；dataset_vars
  由 DagExecutor 读取作节点入参配置源）
- UI 自由文本侧：legacy 平铺行键（行数据非 {"nodes"} 包装的剩余键，如
  {"bl_no": ...}）注入 __dataset__ 伪命名空间——UI 步骤 ${} 的数据来源是
  平铺池（expression.py），无 per-node 通道，平铺键不可静默丢弃；先于
  套件/续跑注入，优先级最低（运行时产出 > 套件 > 数据集行）
- 全 sheet 注入（2026-10-27 sheet 化）：dataset_sheets 各 sheet 以 label 为
  命名空间注入 → ${sheet.字段} 精确引用非选中 sheet 的值（首点切 ns 查法，
  expression.py 零改动）；注入顺序见 __init__ docstring
- 单元格生成规则求值（2026-10-28 数据收口）：注入前对平铺单元格过
  evaluate_dataset_cell——整串 ${函数(...)} 在此求值（生成规则写在数据集，
  编排层只引用 ${sheet.字段}）。选中 sheet 经 sheets 与 dataset_vars 双通道
  注入，同一单元格只求值一次（按原始数据相等复用），保证 ${label.字段} 与
  裸 ${字段} 取到同一个生成值（generate_bl_no 含随机段，两次求值必不同）
"""
from typing import Any

from .expression import evaluate_dataset_cell
from .variables import DATASET_NS, SUITE_NS, VariableRegistry


class ExecutionContext:
    def __init__(self, dataset_vars: dict[str, Any] | None = None,
                 suite_vars: dict[str, Any] | None = None,
                 resume_seed: dict[str, dict[str, Any]] | None = None,
                 dataset_sheets: list[dict[str, Any]] | None = None):
        """dataset_vars：选中 sheet 的行数据。{"nodes": {...}} 为节点入参配置源
        （由 DagExecutor 消费，不注入注册表）；其余平铺键为 legacy 数据驱动
        行（如 {"bl_no": ...}），注入 __dataset__ 供 UI 步骤 ${} 引用。

        dataset_sheets：全部 sheet [{label, data}]（执行展开计划携带）。平铺
        单元格注入前求值生成规则（evaluate_dataset_cell，仅整串 ${函数(...)}）。
        注入顺序契约（_flat_pool 按 ns 插入序合并，顺序即裸 ${字段} 优先级）：
        1. 各 sheet（行序）以 label 为 ns 注入平铺键（除 "nodes"）；
        2. 选中 sheet 平铺注入 __dataset__（数据集类注入的最后）→ 裸 ${字段}
           同名冲突时选中 sheet 胜；
        3. __suite__（不变，仍压数据集）；4. resume_seed；5. 运行时节点写入
           最后胜出（不变）。label 与 node_id 撞名时 ns 合并、后写胜——运行时
           节点产出在注入之后写 → 节点胜（跨域无法预校验，dataset_service 的
           保留字校验只兜底 expression 硬拦截前缀）。仅含 "nodes" 的 sheet
           注入空 ns（合法，${label.x} 自然不命中）。

        resume_seed 为嵌套结构 {node_id: {变量名: 值}}（report_context 产出）：
        断点续跑时前缀成功步骤的提取值按原节点命名空间还原，下游 {{节点.变量}}
        引用链保持完整。"""
        self.dataset_vars: dict[str, Any] = dataset_vars or {}
        self.registry = VariableRegistry()
        evaluated: list[tuple[dict, dict]] = []  # (原始 data, 求值后平铺) —— 选中 sheet 复用
        for s in dataset_sheets or []:
            label = (s.get("label") or "").strip()
            if not label:
                continue  # 防御：无标签 sheet 无命名空间，跳过（正常不会出现）
            raw = s.get("data") or {}
            flat_sheet = {k: evaluate_dataset_cell(v) for k, v in raw.items() if k != "nodes"}
            evaluated.append((raw, flat_sheet))
            self.registry.inject(label, flat_sheet)
        flat: dict[str, Any] | None = None
        for raw, ev in evaluated:
            # 选中 sheet 双通道注入：与某 sheet 原始数据相等 → 复用其求值结果
            if raw == self.dataset_vars:
                flat = dict(ev)
                break
        if flat is None:
            flat = {k: evaluate_dataset_cell(v) for k, v in self.dataset_vars.items() if k != "nodes"}
        if flat:
            self.registry.inject(DATASET_NS, flat)
        self.registry.inject(SUITE_NS, suite_vars)
        for node_id, vars_ in (resume_seed or {}).items():
            self.registry.inject(node_id, vars_)
