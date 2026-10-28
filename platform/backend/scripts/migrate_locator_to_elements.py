# -*- coding: utf-8 -*-
"""存量迁移：autotest-playwright 的 locator JSON → 平台 ui_elements 元素库。

数据源：<autotest-root>/module/**/locator/*.json，结构 {元素key: {定位策略字段..., description}}。
description 不是定位策略，单独存 UiElement.description；其余字段（full_xpath/text/
label/for/button/checkbox/toast/...）原样进 strategies，由平台 ui_runtime 按
策略优先级链解析（full_xpath 永远兜底）。

映射规则：
    page_scope  = SCOPE_MAP[模块目录]（模块目录 → 业务系统真实路由，见下表）。
                  页面域统一用真实路由命名（如 orderManage/businessOrder），
                  不再用测试仓模块目录名——目录名曾导致两种拼写各导入一次的重复域
                  （businessorderadd vs business_order_add，2026-10-28 已清理合并）。
                  模块目录不在表内时默认中止（防再灌模块名域），可 --allow-unmapped 放行
                  （放行时按目录名命名，并对库里已存在的归一化相似域大声警告）。
    element_key = JSON 顶层 key
    strategies  = 该 key 下除 description 外的全部字段
    description = 该 key 下的 description（可缺失）

写入走 app.crud.batch_upsert_ui_elements（覆盖式：同 (page_scope, element_key)
更新 strategies/description，新 key 插入，可重复执行）。

用法（在 platform/backend 目录下，DB 配置来自 backend/.env 或环境变量）：
    python scripts/migrate_locator_to_elements.py --project-id 1 --dry-run
    python scripts/migrate_locator_to_elements.py --project-id 1
    python scripts/migrate_locator_to_elements.py --project-id 1 --autotest-root D:/CODE/PyCharm/pythonProject/autotest-playwright
"""
import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# 默认源项目根：与 fin-ui-test 平级的 autotest-playwright（脚本向上 5 级目录）
DEFAULT_AUTOTEST_ROOT = Path(__file__).resolve().parents[4] / "autotest-playwright"

# 模块目录 → 业务系统真实路由（路由实证自平台用例/数据集实际访问值 #/development/...）。
# 测试仓目录名与路由不一致（且自带拼写错误目录 dataproccess/），必须显式映射。
# 新增模块目录时先补此表再跑；不在表内默认中止。
SCOPE_MAP = {
    "ordermanage/businessorderadd": "orderManage/businessOrder",
    "ordermanage/businessorderdetails": "orderManage/businessOrder",
    "dataproccess/orderdocumentpage": "orderManage/businessOrder",  # 源目录拼写错误，待测试仓改名
    "ordermanage/entrustedorderadd": "orderManage/entrustedOrder",
    "dataprocess": "orderManage/entrustedOrder",
    "ordermanage/orderselfdetails": "orderManage/ordersSelf",
    "workbench/approvalcenter": "workbench/approvalCenter",
    "financemanage/receivable/reconciliationbatch": "financialManage/receivable/reconciliationBatch",
}


def _norm(s: str) -> str:
    """归一化（去非字母数字 + 小写）：相似域检测用"""
    import re
    return re.sub(r"[^a-z0-9]", "", s.lower())

# 脚本不经 app.main 启动：自行加载 backend/.env（存在时真实配置优先）
from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

# --help / --dry-run 不连库也要能导入 app.*（app.database 导入期要求 DB_PASSWORD）
os.environ.setdefault("JWT_SECRET_KEY", "migrate-script")
os.environ.setdefault("DB_PASSWORD", "migrate-script")

# 允许从任意 cwd 运行：把 backend 目录加入 sys.path
sys.path.insert(0, str(BACKEND_DIR))

from app import crud, schemas  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="迁移 autotest-playwright 的 locator JSON 到平台 ui_elements 元素库"
                    "（覆盖式 upsert，同 page_scope+element_key 更新、新 key 插入）")
    parser.add_argument("--project-id", type=int, required=True,
                        help="目标项目 ID（元素库归属，必填）")
    parser.add_argument("--autotest-root", default=str(DEFAULT_AUTOTEST_ROOT),
                        help=f"autotest-playwright 项目根目录（默认与 fin-ui-test 平级: "
                             f"{DEFAULT_AUTOTEST_ROOT}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将导入的 (page_scope, element_key, 策略键列表)，不写库")
    parser.add_argument("--allow-unmapped", action="store_true",
                        help="放行不在 SCOPE_MAP 的模块目录（按目录名命名域并警告；"
                             "默认中止，防再灌出模块名/拼写错域）")
    return parser.parse_args()


def iter_locator_files(module_dir: Path, unmapped: set):
    """遍历 module/**/locator/*.json，产出 (page_scope, 文件路径)。

    page_scope 经 SCOPE_MAP 映射为真实路由；未映射目录记入 unmapped 由调用方处置。
    """
    for path in sorted(module_dir.rglob("locator/*.json")):
        module_scope = "/".join(path.relative_to(module_dir).parts[:-2])
        if not module_scope:
            print(f"[警告] 跳过无页面域的 locator 文件（module 直下）: {path}")
            continue
        page_scope = SCOPE_MAP.get(module_scope)
        if page_scope is None:
            unmapped.add(module_scope)
            page_scope = module_scope  # 先按目录名占位，是否放行由调用方决定
        yield page_scope, path


def load_page_items(path: Path) -> list[schemas.UiElementItemIn]:
    """读单个 locator JSON，展开为批量导入条目（description 与策略字段分离）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for key, spec in data.items():
        if not isinstance(spec, dict):
            print(f"[警告] {path.name} 的 {key!r} 值不是字典，跳过")
            continue
        items.append(schemas.UiElementItemIn(
            element_key=key,
            strategies={k: v for k, v in spec.items() if k != "description"},
            description=spec.get("description"),
        ))
    return items


def main():
    args = parse_args()
    module_dir = Path(args.autotest_root).resolve() / "module"
    if not module_dir.is_dir():
        sys.exit(f"未找到模块目录: {module_dir}（用 --autotest-root 指定源项目根）")

    unmapped: set = set()
    files = list(iter_locator_files(module_dir, unmapped))
    if not files:
        sys.exit(f"{module_dir} 下未发现 locator/*.json")

    # 未映射目录：默认中止（防再灌模块名/拼写错域），--allow-unmapped 才放行
    if unmapped:
        for m in sorted(unmapped):
            print(f"[拦截] 模块目录不在 SCOPE_MAP: {m}")
        if not args.allow_unmapped:
            sys.exit("上述目录未配置真实路由映射，已中止。"
                     "请在脚本 SCOPE_MAP 补充映射后重跑，或 --allow-unmapped 放行（按目录名命名）。")
        print("[警告] --allow-unmapped 放行，以上目录按目录名命名页面域\n")

    print(f"源项目 module 目录: {module_dir}")
    print(f"目标 project_id: {args.project_id}"
          + ("（dry-run，不写库）" if args.dry_run else "") + "\n")

    # 放行模式下：对库里归一化相似的已有域大声警告（重复域就是这么来的）
    if unmapped and args.allow_unmapped and not args.dry_run:
        db_check = SessionLocal()
        try:
            existing = {s["page_scope"]: s["count"]
                        for s in crud.list_page_scopes(db_check, args.project_id)}
        finally:
            db_check.close()
        for m in sorted(unmapped):
            for scope in existing:
                if _norm(m) == _norm(scope) or (_norm(m) and _norm(m) in _norm(scope)) \
                        or (_norm(scope) and _norm(scope) in _norm(m)):
                    print(f"[警告] 未映射域 {m} 与已有域 {scope}（{existing[scope]} 元素）"
                          f"归一化后高度相似，极可能灌出重复域！")

    db = None if args.dry_run else SessionLocal()
    total = 0
    try:
        for page_scope, path in files:
            items = load_page_items(path)
            if args.dry_run:
                print(f"[{page_scope}] {path.name}（{len(items)} 个元素）")
                for it in items:
                    print(f"    {page_scope} | {it.element_key} | 策略: {sorted(it.strategies)}")
                total += len(items)
                continue
            n = crud.batch_upsert_ui_elements(db, args.project_id, page_scope, items, user_id=None)
            total += n
            print(f"[{page_scope}] {path.name} → 写入/更新 {n} 个元素")
    finally:
        if db is not None:
            db.close()

    print(f"\n完成：{'dry-run 共解析' if args.dry_run else '共写入'} {total} 个元素，"
          f"覆盖 {len({s for s, _ in files})} 个页面域（{len(files)} 个 locator 文件）")


if __name__ == "__main__":
    main()
