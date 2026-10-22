"""UI 步骤表达式求值（${} 字符串语法，ui_runtime 专用）。

API 节点入参已收敛到四来源参数模型（param_resolver，下拉配置禁止手输表达式）；
UI 步骤的 url/填充值/定位值等仍是自由文本，保留 ${} 语法（UI_CASE_GUIDE 口径）：
    ${order_id}                引用变量（跨节点平铺池，后写命名空间优先）
    ${n_create.bl_no}          按节点命名空间精确引用（registry.read）
    ${context.name}            兼容旧写法，等价于 ${name}
    ${now(format='%Y-%m-%d')}  内置函数（注册表同 param_resolver 来源2）
    ${db.query_one('SELECT …')} SQL 取数（UI 步骤专用保留；API 参数模型已废止该写法）
未定义变量保留原占位符不替换，便于排查与下游注入。

函数集不自持：复用 functions.call_function（与来源2同一注册表，单一事实源）。
"""
import re
from typing import Any

from .functions import call_function
from .variables import VariableRegistry


def _parse_kwargs(args_str: str) -> dict[str, Any]:
    """解析 key=value 形式的关键字参数，支持字符串与数字"""
    kwargs: dict[str, Any] = {}
    for part in re.split(r",\s*(?![^']*['])", args_str.strip()):
        if not part.strip():
            continue
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
            kwargs[k] = v[1:-1]
        else:
            try:
                kwargs[k] = int(v)
            except ValueError:
                try:
                    kwargs[k] = float(v)
                except ValueError:
                    kwargs[k] = v
    return kwargs


def _strip_quotes(s: str) -> str:
    """去掉首尾配对的单引号或双引号"""
    s = s.strip()
    if len(s) >= 2 and ((s[0] == "'" and s[-1] == "'") or (s[0] == '"' and s[-1] == '"')):
        return s[1:-1]
    return s


def _safe_int(val: Any, default: int = 0) -> int:
    """容错解析 int：_parse_kwargs 在数值参数后跟引号字符串参数时可能粘连，提取开头数字"""
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except (ValueError, TypeError):
        m = re.match(r"-?\d+", str(val))
        return int(m.group()) if m else default


def _sql_literal(val: Any) -> str:
    """值 → SQL 字面量（字符串转义防注入，与 param_resolver.render_placeholders 同口径）"""
    if isinstance(val, str):
        return "'" + val.replace("'", "''") + "'"
    if val is None:
        return "NULL"
    return str(val)


class ExpressionEngine:
    def __init__(self, context: Any, db_client: Any = None):
        """context：ExecutionContext（新参数模型，读 registry）；
        db_client：DBClient 替身（query(sql) → list[dict]，db.query_* 用）。"""
        self.context = context
        self.db_client = db_client

    # ---------- 平铺池：跨节点查找 ${name} ----------
    def _flat_pool(self) -> dict[str, Any]:
        registry: VariableRegistry = self.context.registry
        pool: dict[str, Any] = {}
        for ns_vars in registry.to_dict().values():
            pool.update(ns_vars or {})
        return pool

    def evaluate(self, expr: Any) -> Any:
        """递归求值：支持字符串、字典、列表"""
        if isinstance(expr, str):
            return self._eval_str(expr)
        if isinstance(expr, dict):
            return {k: self.evaluate(v) for k, v in expr.items()}
        if isinstance(expr, list):
            return [self.evaluate(v) for v in expr]
        return expr

    def _eval_str(self, expr: str) -> Any:
        # 整串就是一个 ${...} 表达式 → 求值后返回原生类型（int/dict 等）；
        # 未定义的变量（None）保留原占位符字符串，留给下游节点注入
        if expr.startswith("${") and expr.endswith("}"):
            val = self._eval_inner(expr[2:-1].strip())
            return expr if val is None else val

        # 字符串中内嵌多个 ${...} → 逐个替换（已求值的转字符串）
        if "${" in expr:
            def repl(m):
                val = self._eval_inner(m.group(1).strip())
                return m.group(0) if val is None else str(val)
            return re.sub(r"\$\{([^}]+)\}", repl, expr)
        return expr

    def _eval_inner(self, inner: str) -> Any:
        # ${context.name}：兼容旧写法，等价于 ${name}
        if inner.startswith("context."):
            inner = inner[len("context."):]
            return self._flat_pool().get(inner)
        # db.query_one(...) / db.query_value(...) / db.query(...)
        if inner.startswith("db."):
            return self._eval_db_func(inner)
        # ${节点.变量}：按命名空间精确引用（registry 缺失/取不到返回 None → 保留占位符）
        if "." in inner and "(" not in inner:
            node_id, _, var_path = inner.partition(".")
            return self.context.registry.read(node_id, var_path)
        # 函数调用 name(...)
        if "(" in inner and inner.endswith(")"):
            func_name = inner[:inner.index("(")]
            args_str = inner[inner.index("(") + 1:-1]
            kwargs = _parse_kwargs(args_str)
            try:
                return call_function(func_name, kwargs)
            except (ValueError, TypeError):
                return None
        # 无前缀 ${name}：跨节点平铺池取值（后写命名空间优先）
        return self._flat_pool().get(inner)

    # ---------- DB 函数（UI 步骤专用） ----------
    def _eval_db_func(self, inner: str) -> Any:
        if not self.db_client:
            return None
        try:
            func_name = inner[:inner.index("(")]
            args_str = inner[inner.index("(") + 1:-1]
            kwargs = _parse_kwargs(args_str)
        except Exception:
            return None

        # 第一个位置参数视为 SQL（可能被当成 key=value 解析，需要兼容）
        sql = kwargs.get("sql") or kwargs.get("0")
        if not sql:
            parts = re.split(r",\s*(?![^']*['])", args_str.strip(), maxsplit=1)
            sql = _strip_quotes(parts[0]) if parts else ""
            if len(parts) > 1:
                for p in re.split(r",\s*(?![^']*['])", parts[1].strip()):
                    if "=" in p:
                        k, v = p.split("=", 1)
                        kwargs[k.strip()] = _strip_quotes(v)
        sql = _strip_quotes(sql)
        if not sql:
            return None

        # 注入上下文变量（${xxx}，字符串转义防注入）
        pool = self._flat_pool()

        def inject(m):
            val = pool.get(m.group(1).strip())
            return m.group(0) if val is None else _sql_literal(val)

        sql = re.sub(r"\$\{([^}]+)\}", inject, sql)

        try:
            rows = self.db_client.query(sql)
        except Exception:
            return None

        if func_name == "db.query":
            return rows or []
        if func_name == "db.query_one":
            return rows[0] if rows else None
        if func_name == "db.query_value":
            field = kwargs.get("field")
            if not rows:
                return None
            if field:
                return rows[0].get(field) if isinstance(rows[0], dict) else None
            if isinstance(rows[0], dict) and rows[0]:
                return next(iter(rows[0].values()))
        return None
