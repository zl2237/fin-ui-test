# 重做：bl_no 动态化（SQLAlchemy JSON 列须整体重新赋值，原地修改不持久化）
import sys

sys.path.insert(0, '.')
import app.path_setup  # noqa: E402,F401 副作用导入（路径初始化）
from copy import deepcopy  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import CaseNodeConfig  # noqa: E402
from sqlalchemy import select  # noqa: E402

BL = '${bl_no}'
DYN = "${generate_bl_no(prefix='uitest')}"

s = SessionLocal()
try:
    # ① 272 g1：fill 步（value=${bl_no}）改动态生成；post_extract 已在（$.steps[4].value）
    g1 = s.scalar(select(CaseNodeConfig).where(CaseNodeConfig.case_id == 272, CaseNodeConfig.node_id == 'g1'))
    ui = deepcopy(g1.ui_params)
    hit = None
    for i, st in enumerate(ui.get('steps') or []):
        if st.get('value') == BL:
            st['value'] = DYN
            hit = i
    assert hit is not None, '272 g1 未找到 fill ${bl_no}'
    g1.ui_params = ui  # 整体赋值：JSON 列变更可被追踪
    g1.post_extract = [{'name': 'bl_no', 'source': 'response', 'json_path': f'$.steps[{hit}].value'}]
    print(f'272 g1 步骤{hit} -> 动态单号 + 提取 $.steps[{hit}].value')

    # ② 270：仅 n005（s1 提单号）动态化；其余节点清掉误加的提取
    for x in s.scalars(select(CaseNodeConfig).where(CaseNodeConfig.case_id == 270)).all():
        up = x.ui_params
        if not up:
            continue
        if x.node_id == 'n005':
            nu = deepcopy(up)
            nu['value'] = DYN
            x.ui_params = nu
            x.post_extract = [{'name': 'bl_no', 'source': 'response', 'json_path': '$.value'}]
            print('270 n005 -> 动态单号 + 提取 $.value')
        elif (up.get('value') == BL) and x.post_extract:
            x.post_extract = []
            print('270', x.node_id, '清空多余提取（检索引用保持 ${bl_no}）')
    s.commit()

    # ③ 同步数据集快照
    from app.services.dataset_service import sync_case_datasets
    for cid in (272, 270):
        sync_case_datasets(s, cid)
    s.commit()

    # ④ 复核
    g1b = s.scalar(select(CaseNodeConfig).where(CaseNodeConfig.case_id == 272, CaseNodeConfig.node_id == 'g1'))
    v = (g1b.ui_params['steps'][hit]['value'])
    print('复核 272 步骤值:', v[:50])
    assert v == DYN
finally:
    s.close()
