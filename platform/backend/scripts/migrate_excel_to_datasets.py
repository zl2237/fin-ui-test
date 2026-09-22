# -*- coding: utf-8 -*-
"""存量迁移：autotest-playwright 的 Excel 测试数据 → 平台 data_sets 数据集。

数据源：<autotest-root>/module/**/data/*.xlsx。解析复用源项目
utils/data_helper.get_testdata(file_name, absolute_path=True)（纯函数入口，返回
{"<数据集名>": {字段: 值}}），自动覆盖其三种格式：
    - 多数据集列式（表头每列一个数据集名，字段值为字符串）
    - 单数据集多行式（嵌套：数据集级字段 + "rows": [...] + 分组字段 {组名: {...}}）
    - 场景名表头式（行1 场景名，行3 起数据，支持分组/嵌套子分组）
后两种产出的 dict/list 嵌套值按 object/array 列规则无损承载，不改写源数据。

映射规则：
    一个 Excel 文件 → 一个 DataSet（name = 文件名去扩展名，可加 --prefix 前缀）
    Excel 内每个"<数据集名>" → 一条 DataSetRow（行 data = 该数据集的字段字典）
    columns 从所有行键并集推导：dict→object / list→array / bool→bool / int→int /
    其余 string（同键异型时取更复杂的一端）
    归属：--case-id 指定用例（DataSet.case_id，用例级 1:N 隔离）；project_id 查库
    取该用例的 project_id。node_configs 保持 []（UI 用例的节点配置快照由平台侧
    另行生成）。

注意：脚本每次执行都新建数据集（无 upsert），重复执行会产生同名新数据集。

用法（在 platform/backend 目录下，DB 配置来自 backend/.env 或环境变量）：
    python scripts/migrate_excel_to_datasets.py --case-id 3 --dry-run
    python scripts/migrate_excel_to_datasets.py --case-id 3
    python scripts/migrate_excel_to_datasets.py --case-id 3 --prefix ordermanage_
        --autotest-root D:/CODE/PyCharm/pythonProject/autotest-playwright
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# 默认源项目根：与 fin-api-test 平级的 autotest-playwright（脚本向上 5 级目录）
DEFAULT_AUTOTEST_ROOT = Path(__file__).resolve().parents[4] / "autotest-playwright"

# 脚本不经 app.main 启动：自行加载 backend/.env（存在时真实配置优先）
from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

# --help / --dry-run 不连库也要能导入 app.*（app.database 导入期要求 DB_PASSWORD）
os.environ.setdefault("JWT_SECRET_KEY", "migrate-script")
os.environ.setdefault("DB_PASSWORD", "migrate-script")

# 允许从任意 cwd 运行：把 backend 目录加入 sys.path
sys.path.insert(0, str(BACKEND_DIR))

# path_setup 把 fin-api-test 仓库根也挂入 sys.path：dataset_service 的导入链
# （body_builder → preprocessor → expression）依赖仓库根下的 utils.generator_util
from app import models, path_setup  # noqa: E402,F401
from app.database import SessionLocal  # noqa: E402
from app.services.dataset_service import _infer_col_type, create_dataset  # noqa: E402

# 列类型冲突时的取舍优先级：复杂类型优先（object/array 承载嵌套结构不丢信息）
_TYPE_PRIORITY = ("object", "array", "bool", "int", "string")


def parse_args():
    parser = argparse.ArgumentParser(
        description="迁移 autotest-playwright 的 Excel 测试数据到平台 data_sets"
                    "（一个 Excel 文件 → 一个数据集，每个数据集名 → 一行）")
    parser.add_argument("--case-id", type=int, required=True,
                        help="归属用例 ID（DataSet.case_id 必填；project_id 取该用例所属项目）")
    parser.add_argument("--prefix", default="",
                        help="数据集名称前缀（默认无前缀）")
    parser.add_argument("--autotest-root", default=str(DEFAULT_AUTOTEST_ROOT),
                        help=f"autotest-playwright 项目根目录（默认与 fin-api-test 平级: "
                             f"{DEFAULT_AUTOTEST_ROOT}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印 文件→数据集名→行数→列清单，不写库")
    return parser.parse_args()


def infer_columns(rows_data: list[dict]) -> list[dict]:
    """所有行键并集推导列定义（键序取首次出现顺序，类型冲突取更复杂一端）。"""
    order, types = [], {}
    for data in rows_data:
        for key, value in data.items():
            if key not in types:
                types[key] = set()
                order.append(key)
            types[key].add(_infer_col_type(value))
    return [
        {"key": key, "type": next(t for t in _TYPE_PRIORITY if t in types[key])}
        for key in order
    ]


def main():
    args = parse_args()
    root = Path(args.autotest_root).resolve()
    module_dir = root / "module"
    if not module_dir.is_dir():
        sys.exit(f"未找到模块目录: {module_dir}（用 --autotest-root 指定源项目根）")

    # 挂上源项目根以复用其 get_testdata（absolute_path=True 不依赖调用方文件栈）
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from utils.data_helper import get_testdata

    files = [p for p in sorted(module_dir.rglob("data/*.xlsx"))
             if not p.name.startswith("~$")]  # 排除 Excel 打开时的锁文件
    if not files:
        sys.exit(f"{module_dir} 下未发现 data/*.xlsx")

    db, case = None, None
    if not args.dry_run:
        db = SessionLocal()
        case = db.query(models.TestCase).filter(models.TestCase.id == args.case_id).first()
        if case is None:
            db.close()
            sys.exit(f"--case-id {args.case_id} 对应的用例不存在")
        if case.project_id is None:
            db.close()
            sys.exit(f"用例 {args.case_id} 未归属任何项目，无法确定 project_id")

    print(f"源项目 module 目录: {module_dir}")
    print(f"归属 case_id: {args.case_id}"
          + (f"（project_id={case.project_id}）" if case is not None else "")
          + ("（dry-run，不写库）" if args.dry_run else "") + "\n")

    created = failed = 0
    try:
        for path in files:
            rel = path.relative_to(root)
            try:
                datasets = get_testdata(str(path), absolute_path=True) or {}
            except Exception as exc:  # 单文件解析失败不中断整体迁移
                failed += 1
                print(f"[失败] {rel}: {exc}")
                continue

            name = f"{args.prefix}{path.stem}"
            rows_data = [dict(fields) for fields in datasets.values()]
            columns = infer_columns(rows_data)
            print(f"{rel} → 数据集「{name}」")
            print(f"    数据集名: {'、'.join(datasets) or '（无）'}")
            print(f"    行数: {len(rows_data)}    列: "
                  + (", ".join(f"{c['key']}:{c['type']}" for c in columns) or "（无）"))

            if args.dry_run:
                continue
            if not rows_data or not columns:
                print("    [跳过] 空数据文件")
                continue
            try:
                create_dataset(db, project_id=case.project_id, name=name, columns=columns,
                               user_id=None, case_id=case.id,
                               node_configs=[], rows_data=rows_data)
                created += 1
                print(f"    已创建数据集「{name}」（{len(rows_data)} 行）")
            except ValueError as exc:  # 列名不合法等业务校验失败
                failed += 1
                print(f"    [失败] {exc}")
    finally:
        if db is not None:
            db.close()

    summary = "dry-run 解析完成" if args.dry_run else f"创建 {created} 个数据集"
    print(f"\n完成：{summary}，共扫描 {len(files)} 个文件"
          + (f"，失败 {failed} 个" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
