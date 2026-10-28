# -*- coding: utf-8 -*-
"""用例元素引用重映射：2026-10-28 元素库重建后修复悬空引用。

背景：10-28 元素库整库重建——旧 snake_case 域元素（id 1~495）全部删除，
从 autotest-playwright locator JSON 按路由式域（orderManage/businessOrder 等）
重新导入（新 id 500+）。用例 case_node_configs 里的 element_id 仍指旧 id →
页面域显示空、元素显示裸数字、执行报「元素库中不存在 element_id=N」。

修复：备份 dump（含旧库全量 ui_elements）解析 old_id → (旧域, key)，
经 SCOPE_MAP 归一到新域，再按 (新域, key) 查当前库得 new_id，改写引用。
同名碰撞（多个旧 id 同 key）已核实策略一致（analyze 见会话记录），重映射安全。

用法（在 platform/backend 目录下，目标库由 backend/.env 或环境变量决定）：
    python scripts/remap_element_refs.py                     # 默认 dry-run：只列改动
    python scripts/remap_element_refs.py --apply             # 实际写库
    DB_HOST=192.168.2.51 DB_PORT=20001 DB_USER=dev-wifi DB_PASSWORD=*** \\
        python scripts/remap_element_refs.py --apply         # 指向线上库

幂等：已指向现存元素的引用跳过；重复执行无副作用。
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

import os

os.environ.setdefault("DB_PASSWORD", "x")

from app.database import SessionLocal
from app import models

# 备份 dump（10-27 全量备份，含旧 ui_elements）；文件缺失时可用 --dump 指定
DEFAULT_DUMP = BACKEND_DIR / "backups" / "fin_ui_test_full_for_prod_20261027_150054.sql"

# 旧域（备份中的 canonical 域）→ 新域（路由式；表来源 migrate_locator_to_elements.py）
SCOPE_MAP = {
    "ordermanage/business_order_add": "orderManage/businessOrder",
    "ordermanage/business_order_details": "orderManage/businessOrder",
    "dataproccess/order_document": "orderManage/businessOrder",
    "ordermanage/entrusted_order_add": "orderManage/entrustedOrder",
    "dataprocess": "orderManage/entrustedOrder",
    "ordermanage/order_self_details": "orderManage/ordersSelf",
    "workbench/approval_center": "workbench/approvalCenter",
    "financemanage/receivable/reconciliationbatch": "financialManage/receivable/reconciliationBatch",
}
# 备份中还存在 dup 域（10-28 cleanup 前的重复导入；引用已迁 canonical，防御性补齐）
SCOPE_MAP.update({
    "ordermanage/businessorderadd": "orderManage/businessOrder",
    "ordermanage/businessorderdetails": "orderManage/businessOrder",
    "dataproccess/orderdocumentpage": "orderManage/businessOrder",
    "ordermanage/entrustedorderadd": "orderManage/entrustedOrder",
    "ordermanage/orderselfdetails": "orderManage/ordersSelf",
    "workbench/approvalcenter": "workbench/approvalCenter",
})


def parse_values(s: str) -> list[list[str]]:
    """逐字符解析 INSERT VALUES 元组串，尊重单引号字符串（\\ 转义与 '' 双写转义）。"""
    out, i, n = [], 0, len(s)
    while i < n:
        assert s[i] == "(", s[i - 5:i + 10]
        fields, cur, in_str, i = [], "", False, i + 1
        while True:
            c = s[i]
            if in_str:
                if c == "\\":
                    cur += s[i + 1]
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and s[i + 1] == "'":
                        cur += "'"
                        i += 2
                        continue
                    in_str = False
                    i += 1
                    continue
                cur += c
                i += 1
                continue
            if c == "'":
                in_str = True
                i += 1
                continue
            if c == ",":
                fields.append(cur.strip())
                cur = ""
                i += 1
                continue
            if c == ")":
                fields.append(cur.strip())
                i += 1
                break
            cur += c
            i += 1
        out.append(fields)
        if i < n and s[i] == ",":
            i += 1
            continue
        if i < n and s[i] == ";":
            break
    return out


def load_old_elements(dump: Path) -> dict[int, tuple[str, str, str]]:
    """备份 dump → {old_id: (page_scope, element_key, description)}"""
    rows: list[list[str]] = []
    with open(dump, encoding="utf-8") as f:
        for line in f:
            if line.startswith("INSERT INTO `ui_elements`"):
                body = line[line.index("VALUES") + 6:].strip()
                rows.extend(parse_values(body))
    # 列序同 models.UiElement：id(0) project_id(1) page_scope(2) element_key(3)
    # strategies(4) description(5) ...
    return {int(r[0]): (r[2], r[3], r[5]) for r in rows}


def remap_ids(node, old_map: dict, new_lib: dict, by_id: dict, stats: dict):
    """递归改写 dict/list 树中的 element 引用（原地），返回是否发生改动"""
    changed = False
    if isinstance(node, dict):
        el = node.get("element")
        if isinstance(el, dict) and isinstance(el.get("element_id"), int):
            oid = el["element_id"]
            if oid in by_id:
                pass  # 现存有效引用：不动（幂等）
            elif oid in old_map:
                old_scope, key, _desc = old_map[oid]
                new_scope = SCOPE_MAP.get(old_scope)
                hit = new_lib.get((new_scope, key)) if new_scope else None
                if hit:
                    el["element_id"] = hit
                    stats["remapped"] += 1
                    changed = True
                else:
                    stats["unmapped"].append((oid, old_scope, key, _desc))
            else:
                stats["unknown"].append(oid)
        for v in node.values():
            if remap_ids(v, old_map, new_lib, by_id, stats):
                changed = True
    elif isinstance(node, list):
        for v in node:
            if remap_ids(v, old_map, new_lib, by_id, stats):
                changed = True
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    ap.add_argument("--dump", default=str(DEFAULT_DUMP), help="含旧 ui_elements 的备份 dump 路径")
    args = ap.parse_args()

    dump = Path(args.dump)
    if not dump.exists():
        print(f"[abort] 备份 dump 不存在：{dump}")
        return 1
    old_map = load_old_elements(dump)
    print(f"备份解析：旧元素 {len(old_map)} 个（id {min(old_map)}~{max(old_map)}）")

    db = SessionLocal()
    try:
        # 运行中执行守卫：执行线程读库内配置，改引用会串版本
        running = (db.query(models.ExecutionRecord)
                   .filter(models.ExecutionRecord.status == "running").count())
        if running:
            print(f"[abort] 有 {running} 个执行进行中，等执行结束再跑")
            return 1

        # 现存元素库索引：(scope, key) → id；id → (scope, key)（幂等跳过现存引用）
        by_pair = {(e.page_scope, e.element_key): e.id for e in db.query(models.UiElement).all()}
        by_id = {e.id: (e.page_scope, e.element_key)
                 for e in db.query(models.UiElement).all()}
        print(f"当前库元素 {len(by_pair)} 个（id {min(by_id)}~{max(by_id)}）")

        rows = (db.query(models.CaseNodeConfig)
                .filter(models.CaseNodeConfig.step_type == "ui").all())
        print(f"UI 节点配置 {len(rows)} 行")

        # dry-run 与 apply 共用改写器：apply=False 时只统计不落库
        planned = []
        stats = {"remapped": 0, "unmapped": [], "unknown": []}
        for cfg in rows:
            if not cfg.ui_params:
                continue
            params = json.loads(json.dumps(cfg.ui_params))  # 工作副本（dry-run 不污染 ORM）
            before = json.dumps(params, ensure_ascii=False)
            remap_ids(params, old_map, by_pair, by_id, stats)
            after = json.dumps(params, ensure_ascii=False)
            if after != before:
                planned.append((cfg.case_id, cfg.node_id, before, after))
                if args.apply:
                    cfg.ui_params = params

        print(f"\n{'已改写' if args.apply else '将改写（dry-run）'} {len(planned)} 行节点配置，"
              f"共 {stats['remapped']} 处引用")
        for cid, nid, before, after in planned:
            olds = sorted({int(m) for m in __import__("re").findall(r'"element_id": (\d+)', before)})
            news = sorted({int(m) for m in __import__("re").findall(r'"element_id": (\d+)', after)})
            print(f"  case#{cid} {nid}: element_id {olds} -> {news}")
        if stats["unmapped"]:
            print(f"\n[warn] {len(stats['unmapped'])} 处旧域/键在新库无对应（未改动）：")
            for oid, scope, key, desc in stats["unmapped"]:
                print(f"  old#{oid} {scope}/{key}（{desc}）")
        if stats["unknown"]:
            print(f"\n[warn] 引用的 id 不在备份中（未改动）：{sorted(set(stats['unknown']))}")

        if args.apply:
            db.commit()
            print("\n已提交。")
        else:
            print("\ndry-run 结束（未写库）。确认后加 --apply 执行。")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
