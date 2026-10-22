"""执行平台库中的全链 UI 用例（build_case_generate_order_sub.py 产物）。

等价于平台"执行"按钮的后台路径：DagExecutor + 真实环境 + 数据集行变量。
用法：.venv\\Scripts\\python scripts\\run_ui_case.py [case_id]
"""
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR.parent.parent))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

CASE_ARG = sys.argv[1] if len(sys.argv) > 1 else "[UI迁移]"
ENV_ID = 1


def main():
    from app.database import SessionLocal
    from app import models
    from app.engine.dag_executor import DagExecutor

    db = SessionLocal()
    if CASE_ARG.isdigit():
        case = db.query(models.TestCase).filter(models.TestCase.id == int(CASE_ARG)).first()
    else:
        case = (db.query(models.TestCase)
                .filter(models.TestCase.name.like(f"%{CASE_ARG}%"))
                .order_by(models.TestCase.id.desc()).first())
    if not case:
        print(f"[RUN] 未找到用例: {CASE_ARG}")
        return 1
    env = db.query(models.Environment).filter(models.Environment.id == ENV_ID).first()
    # browser_config：真实环境跑 UI —— 保留 env 原配置，缺省补全
    bc = dict(env.browser_config or {})
    bc.setdefault("headless", True)
    bc.setdefault("screenshot", "always")
    bc.setdefault("timeout_ms", 15000)
    bc.setdefault("viewport", {"width": 1920, "height": 1080})
    bc["inject_token_cookie"] = "Admin-Token"
    env.browser_config = bc

    row_vars = None
    if case.dataset_id:
        row = (db.query(models.DataSetRow)
               .filter(models.DataSetRow.dataset_id == case.dataset_id)
               .order_by(models.DataSetRow.row_index).first())
        if row:
            row_vars = dict(row.data or {})

    print(f"[RUN] case={case.id} {case.name}")
    print(f"[RUN] env={env.name} {env.base_url}  数据行变量: {len(row_vars or {})} 个")
    started = time.time()
    ex = DagExecutor(db, case, env, dataset_row=row_vars, suppress_notify=True)
    record = ex.execute()
    elapsed = time.time() - started

    print("\n===== 执行结果 =====")
    print(f"状态: {record.status}   耗时: {elapsed:.0f}s")
    print(f"摘要: {json.dumps(record.summary, ensure_ascii=False)[:300]}")
    steps = (db.query(models.StepRecord)
             .filter(models.StepRecord.execution_id == record.id)
             .order_by(models.StepRecord.id).all())
    print(f"\n共 {len(steps)} 个步骤记录：")
    for s in steps:
        shot = f"# {s.screenshot_file_id}" if s.screenshot_file_id else "-"
        print(f"  [{s.status:>7}] {s.node_id} {s.api_name}  {s.response_time_ms}ms  截图{shot}")
        facts = s.response_body or {}
        if facts.get("error"):
            print(f"           错误: {str(facts['error'])[:240]}")
        if s.extracted_vars:
            print(f"           提取: {json.dumps(s.extracted_vars, ensure_ascii=False)[:200]}")
    if record.summary.get("leftover"):
        print(f"\n未执行节点: {record.summary['leftover'][:10]} ...")
    db.close()


if __name__ == "__main__":
    main()
