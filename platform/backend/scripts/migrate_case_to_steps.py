# 迁移：把用例 270（333 单动作节点）按阶段聚合为「页面节点 + 动作组（steps）」新用例
# 规则：
#   1. 原 DAG 为纯线性链（n001→n333），按 label 的 sN 前缀切组（无前缀节点继承前驱组）
#   2. 每组一个新节点：steps = 组内各节点 ui_params（按链序）
#   3. 断言改写：原节点断言 $.result → $.steps[i].result（i=该步组内下标），合并到组节点
#   4. 组间边按原跨组顺序连接；数据集/项目继承原用例
import re
import sys
from collections import Counter

sys.path.insert(0, '.')
from sqlalchemy import select  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import TestCase, CaseNodeConfig  # noqa: E402

SRC_ID = 270
NEW_NAME = '[UI迁移·页面节点] 生成子订单全链路-包含所有服务项目'

s = SessionLocal()
try:
    src = s.scalar(select(TestCase).where(TestCase.id == SRC_ID))
    nodes = src.dag_config['nodes']
    edges = src.dag_config['edges']
    cfgs = s.scalars(select(CaseNodeConfig).where(CaseNodeConfig.case_id == SRC_ID)).all()
    cfgm = {x.node_id: x for x in cfgs}

    label = {n['id']: n['data'].get('label', '') for n in nodes}
    succ = {e['source']: e['target'] for e in edges}
    indeg = Counter(e['target'] for e in edges)

    # 沿链排序（线性链已实证：出入度均 ≤1）
    head = next(n['id'] for n in nodes if indeg.get(n['id'], 0) == 0)
    chain = []
    cur = head
    while cur:
        chain.append(cur)
        cur = succ.get(cur)
    assert len(chain) == len(nodes), '链未覆盖全部节点'

    # 分组：sN 前缀切组；无前缀（等待列表就绪等）继承前驱组
    groups: list[dict] = []  # {name, key, node_ids}
    for nid in chain:
        m = re.match(r'^(s\d+)', label[nid])
        if m and (not groups or groups[-1]['key'] != m.group(1)):
            groups.append({'key': m.group(1), 'name': label[nid], 'node_ids': []})
        assert groups, '首节点无阶段前缀'
        groups[-1]['node_ids'].append(nid)
    print('分组:', [(g['key'], len(g['node_ids'])) for g in groups])

    # 生成组节点与配置
    new_nodes, new_edges, new_cfgs = [], [], []
    for gi, g in enumerate(groups):
        gid = f'g{gi + 1}'
        steps = []
        merged_assertions = []
        for i, nid in enumerate(g['node_ids']):
            cfg = cfgm.get(nid)
            if not cfg or not cfg.ui_params:
                raise SystemExit(f'{nid}({label[nid]}) 无 ui_params，无法迁移')
            p = dict(cfg.ui_params)
            assert not isinstance(p.get('steps'), list), f'{nid} 已是组形态'
            steps.append(p)
            for a in (cfg.assertions or []):
                a = dict(a)
                # 断言路径改写：原对单节点 facts 的 $.result → 组内第 i 步明细
                if a.get('path') == '$.result':
                    a['path'] = f'$.steps[{i}].result'
                merged_assertions.append(a)
        new_nodes.append({
            'id': gid,
            'position': {'x': 320, 'y': 80 + gi * 170},
            'data': {'label': g['name'], 'step_type': 'ui', 'ui_action': 'steps', 'ui_steps_len': len(steps)},
            'label': g['name'],
        })
        new_cfgs.append({
            'node_id': gid,
            'step_type': 'ui',
            'ui_params': {'steps': steps},
            'assertions': merged_assertions,
            'pre_process': [],
            'post_extract': [],
            'wait_after_ms': 0,
        })
        if gi:
            new_edges.append({'id': f'e_{gid}', 'source': f'g{gi}', 'target': gid})
    total_steps = sum(len(c['ui_params']['steps']) for c in new_cfgs)
    total_asserts = sum(len(c['assertions']) for c in new_cfgs)
    print(f'新用例: {len(new_nodes)} 组节点 / {total_steps} 步 / {total_asserts} 断言（原 4）')
    assert total_steps == len(nodes)

    # 写入：已存在（同名）则仅恢复 node_configs（保留既有 dag_config 布局/数据集绑定/执行历史）；否则新建
    old = s.scalars(select(TestCase).where(TestCase.name == NEW_NAME)).all()
    if old:
        nc = old[0]
        s.query(CaseNodeConfig).filter(CaseNodeConfig.case_id == nc.id).delete()
    else:
        nc = TestCase(project_id=src.project_id, name=NEW_NAME, case_type='normal',
                      dataset_id=src.dataset_id,
                      dag_config={'nodes': new_nodes, 'edges': new_edges},
                      created_by=1, updated_by=1)
        s.add(nc)
        s.flush()
    for c in new_cfgs:
        s.add(CaseNodeConfig(case_id=nc.id, **c))
    s.commit()
    print(f'用例 id={nc.id} name={nc.name} dataset_id={nc.dataset_id}（{"恢复 configs" if old else "新建"}）')
finally:
    s.close()
