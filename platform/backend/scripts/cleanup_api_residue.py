# 清除 UI 平台库中的 API 平台数据残留（一次性修复脚本，幂等可重跑）
#
# 背景：fin-ui-test 库早期从 API 平台库复制而来，残留以下 API 数据：
#   1. project_versions 5 条 —— 快照内容为 API 接口+API 用例（版本库页可见的“混入记录”）
#   2. api_definitions / api_fields / api_groups —— API 接口三表数据（UI 用例无 api 节点，无消费者）
#   3. operation_logs 中 api / api_group / project_version 日志，以及 2026-10 前（API 期）
#      指向已删除 API 用例/分组/定时任务的孤儿日志
#
# 保留：环境/用户/文件/字段字典/数据集等 UI 活功能的日志与数据。
# 表结构不动（模型仍定义这些表，引擎留有 API 节点能力，仅清数据）。
#
# 执行前已用 mysqldump 备份：backups/api_residue_backup_*.sql
import sys
from datetime import datetime

sys.path.insert(0, '.')
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ApiDefinition, ApiField, ApiGroup, OperationLog, ProjectVersion,
)

API_LOG_TYPES = ('api', 'api_group', 'project_version')
# UI 平台 2026-10 起才有本平台用例/分组/定时任务；此前的相关日志均指向已删除的 API 对象
ORPHAN_CUTOFF = datetime(2026, 10, 1)
ORPHAN_LOG_TYPES = ('testcase', 'case_group', 'schedule')


def main() -> None:
    db = SessionLocal()
    try:
        n_versions = db.query(ProjectVersion).count()
        n_apis = db.query(ApiDefinition).count()
        n_fields = db.query(ApiField).count()
        n_groups = db.query(ApiGroup).count()
        api_logs = db.query(OperationLog).filter(
            OperationLog.target_type.in_(API_LOG_TYPES))
        n_api_logs = api_logs.count()
        orphan_logs = db.query(OperationLog).filter(
            OperationLog.target_type.in_(ORPHAN_LOG_TYPES),
            OperationLog.created_at < ORPHAN_CUTOFF)
        n_orphan_logs = orphan_logs.count()

        print(f'待删除：版本 {n_versions} | api_definitions {n_apis} | '
              f'api_fields {n_fields} | api_groups {n_groups} | '
              f'API 日志 {n_api_logs} | API 期孤儿日志 {n_orphan_logs}')

        db.query(ProjectVersion).delete(synchronize_session=False)
        db.query(ApiField).delete(synchronize_session=False)
        db.query(ApiDefinition).delete(synchronize_session=False)
        # 自引用外键（parent_id → 自身）会挡整表 DELETE，先断链再删（同 crud/versions.py 回滚逻辑）
        db.query(ApiGroup).update({ApiGroup.parent_id: None}, synchronize_session=False)
        db.query(ApiGroup).delete(synchronize_session=False)
        api_logs.delete(synchronize_session=False)
        orphan_logs.delete(synchronize_session=False)
        db.commit()

        remain = {
            'project_versions': db.query(ProjectVersion).count(),
            'api_definitions': db.query(ApiDefinition).count(),
            'api_fields': db.query(ApiField).count(),
            'api_groups': db.query(ApiGroup).count(),
            'api 日志': db.query(OperationLog).filter(
                OperationLog.target_type.in_(API_LOG_TYPES)).count(),
            'operation_logs 总数': db.query(OperationLog).count(),
        }
        print('清理后残留计数（应全为 0，除日志总数）：', remain)
    finally:
        db.close()


if __name__ == '__main__':
    main()
