"""页面域清理（用户已确认方案）：

4 组重复域 = 同一批定位 JSON 以两种命名各导入一次。动作：
1. 引用迁移：重复域中被用例引用的元素 → 规范域内同 key 元素（改 element_id）
2. 删除重复域元素：entrustedorderadd / orderselfdetails / businessorderdetails /
   business_order_add（旧 8 元素子集）
3. 改名规范：businessorderadd → business_order_add（55 元素，0 引用，id 不变）

dataproccess/order_document（拼写）与 workbench/approval_center 保留不动。
执行前校验各域元素数与预期一致，不一致即中止（防止分析过期）。
"""
import os
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
os.environ.setdefault("DB_PASSWORD", "x")

from app.database import SessionLocal
from app import models

# 重复域 → 规范域
DUP_TO_CANONICAL = {
    "ordermanage/entrustedorderadd": "ordermanage/entrusted_order_add",
    "ordermanage/orderselfdetails": "ordermanage/order_self_details",
    "ordermanage/businessorderdetails": "ordermanage/business_order_details",
    "ordermanage/business_order_add": "ordermanage/business_order_add_new",  # 占位：先删旧子集再改名，见下
}
# 各重复域删除前的预期元素数（防分析过期）
EXPECTED = {
    "ordermanage/entrustedorderadd": 60,
    "ordermanage/orderselfdetails": 23,
    "ordermanage/businessorderdetails": 10,
    "ordermanage/business_order_add": 8,
    "ordermanage/businessorderadd": 55,
}


def walk_element_ids(ui_params: dict):
    """递归取出 ui_params 中所有 element.element_id（steps 数组任意深度）。"""
    ids = []

    def walk(node):
        if isinstance(node, dict):
            el = node.get("element")
            if isinstance(el, dict) and el.get("element_id"):
                ids.append(int(el["element_id"]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(ui_params or {})
    return ids


def set_element_id(node, old_id: int, new_id: int) -> bool:
    """递归替换 element.element_id == old_id 为 new_id，返回是否改过。"""
    changed = False
    if isinstance(node, dict):
        el = node.get("element")
        if isinstance(el, dict) and el.get("element_id") == old_id:
            el["element_id"] = new_id
            changed = True
        for v in node.values():
            changed |= set_element_id(v, old_id, new_id)
    elif isinstance(node, list):
        for v in node:
            changed |= set_element_id(v, old_id, new_id)
    return changed


def main() -> None:
    db = SessionLocal()
    els = db.query(models.UiElement).all()
    by_scope = defaultdict(list)
    for e in els:
        by_scope[e.page_scope].append(e)

    # ---- 前置校验：元素数与预期一致 ----
    for scope, n in EXPECTED.items():
        actual = len(by_scope.get(scope, []))
        if actual != n:
            print(f"[中止] {scope} 元素数 {actual} ≠ 预期 {n}，请重新分析")
            sys.exit(1)
    print("元素数校验通过")

    # key → 元素 索引（规范域）
    canon_by_key = {}
    for canon in ("ordermanage/entrusted_order_add", "ordermanage/order_self_details",
                  "ordermanage/business_order_details", "ordermanage/businessorderadd"):
        for e in by_scope.get(canon, []):
            canon_by_key[(e.page_scope, e.element_key)] = e

    # ---- 1. 引用迁移 ----
    # 旧 business_order_add 8 元素是 businessorderadd 55 的子集 → 迁移目标在 businessorderadd 里
    dup_scopes = list(DUP_TO_CANONICAL)
    dup_els = {e.id: e for s in dup_scopes for e in by_scope[s]}
    target_of = {}
    for eid, e in dup_els.items():
        canon_scope = ("ordermanage/businessorderadd"
                       if e.page_scope == "ordermanage/business_order_add" else DUP_TO_CANONICAL[e.page_scope])
        t = canon_by_key.get((canon_scope, e.element_key))
        if t is None:
            print(f"[中止] 规范域 {canon_scope} 缺少同 key 元素 {e.element_key}（#{eid}），无法迁移")
            sys.exit(1)
        target_of[eid] = t.id

    ref_counts = defaultdict(int)
    nodes = db.query(models.CaseNodeConfig).all()
    touched_nodes = 0
    from sqlalchemy.orm.attributes import flag_modified
    for cfg in nodes:
        ids = walk_element_ids(cfg.ui_params)
        hits = [i for i in ids if i in target_of]
        for i in hits:
            ref_counts[i] += 1
        if not hits:
            continue
        for old in set(hits):
            set_element_id(cfg.ui_params, old, target_of[old])
        flag_modified(cfg, "ui_params")
        touched_nodes += 1
    print(f"引用迁移：{touched_nodes} 个节点，{sum(ref_counts.values())} 处引用 "
          f"({ {f'#{k}->{v}' for k, v in ref_counts.items()} })")
    db.commit()

    # ---- 2. 删除重复域元素 ----
    for s in dup_scopes:
        for e in by_scope[s]:
            db.delete(e)
    db.commit()
    print(f"已删除重复域元素 {len(dup_els)} 个：{', '.join(dup_scopes)}")

    # ---- 3. businessorderadd → business_order_add ----
    renamed = db.query(models.UiElement).filter(
        models.UiElement.page_scope == "ordermanage/businessorderadd").all()
    for e in renamed:
        e.page_scope = "ordermanage/business_order_add"
    db.commit()
    print(f"已改名 businessorderadd → business_order_add（{len(renamed)} 元素，id 不变）")

    # ---- 结果汇总 ----
    els = db.query(models.UiElement).all()
    by_scope = defaultdict(int)
    for e in els:
        by_scope[e.page_scope] += 1
    print("\n清理后页面域：")
    for s in sorted(by_scope):
        print(f"  {s}  {by_scope[s]}元素")
    db.close()


if __name__ == "__main__":
    main()
