# 回滚 270 中误改的节点：仅保留 n005（s1 提单号输入）为动态生成，其余恢复 ${bl_no}
import sys

sys.path.insert(0, '.')
import app.path_setup  # noqa: E402,F401 副作用导入（路径初始化）
from app.database import SessionLocal  # noqa: E402
from app.models import CaseNodeConfig  # noqa: E402
from sqlalchemy import select  # noqa: E402

DYN = "${generate_bl_no(prefix='uitest')}"

s = SessionLocal()
try:
    for x in s.scalars(select(CaseNodeConfig).where(CaseNodeConfig.case_id == 270)).all():
        up = x.ui_params or {}
        if up.get('value') == DYN:
            if x.node_id == 'n005':
                print('保留 n005 动态生成 + 提取')
                continue
            up['value'] = '${bl_no}'
            x.post_extract = []
            print('回滚', x.node_id, '-> value=${bl_no}, post_extract=[]')
    s.commit()
    from app.services.dataset_service import sync_case_datasets
    sync_case_datasets(s, 270)
    s.commit()
    print('270 快照已重新同步')
finally:
    s.close()
