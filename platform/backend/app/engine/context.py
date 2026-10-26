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
"""
from typing import Any

from .variables import DATASET_NS, SUITE_NS, VariableRegistry


class ExecutionContext:
    def __init__(self, dataset_vars: dict[str, Any] | None = None,
                 suite_vars: dict[str, Any] | None = None,
                 resume_seed: dict[str, dict[str, Any]] | None = None):
        """dataset_vars：数据集行数据。{"nodes": {...}} 为节点入参配置源
        （由 DagExecutor 消费，不注入注册表）；其余平铺键为 legacy 数据驱动
        行（如 {"bl_no": ...}），注入 __dataset__ 供 UI 步骤 ${} 引用。

        resume_seed 为嵌套结构 {node_id: {变量名: 值}}（report_context 产出）：
        断点续跑时前缀成功步骤的提取值按原节点命名空间还原，下游 {{节点.变量}}
        引用链保持完整。"""
        self.dataset_vars: dict[str, Any] = dataset_vars or {}
        self.registry = VariableRegistry()
        flat = {k: v for k, v in self.dataset_vars.items() if k != "nodes"}
        if flat:
            self.registry.inject(DATASET_NS, flat)
        self.registry.inject(SUITE_NS, suite_vars)
        for node_id, vars_ in (resume_seed or {}).items():
            self.registry.inject(node_id, vars_)
