"""修复 283 合并 DAG 的段间串边（merge_283.py 首版 bug：seg_tail 用未映射旧 id
计算，串边全接在各段 n1 上，导致段内 n2+ 全部被阻断；run#855 实证 m82_n2 起
全部 leftover）。本脚本按「段内出度0=尾、入度0=头」重算并重写串边。"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR.parent.parent))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

SEGMENTS = ["g", "m75", "m82", "m81", "m79", "m73", "m76"]  # 链序（前缀）


def seg_of(node_id: str) -> str:
    return "g" if not node_id.startswith("m") else node_id.rsplit("_", 1)[0]


def main() -> int:
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    c = db.query(models.TestCase).filter(models.TestCase.id == 283).first()
    dag = c.dag_config or {}
    nodes = [n["id"] for n in dag["nodes"]]
    inner = [e for e in dag["edges"] if not e["id"].startswith("chain_")]
    chain = [e for e in dag["edges"] if e["id"].startswith("chain_")]

    # 各段头/尾（段内边算度；段内为线性链）
    heads, tails = {}, {}
    for seg in SEGMENTS:
        seg_nodes = [n for n in nodes if seg_of(n) == seg]
        seg_edges = [e for e in inner if seg_of(e["source"]) == seg]
        assert seg_nodes, f"段 {seg} 无节点"
        srcs = {e["source"] for e in seg_edges}
        tgts = {e["target"] for e in seg_edges}
        h = [n for n in seg_nodes if n not in tgts]
        t = [n for n in seg_nodes if n not in srcs]
        assert len(h) == 1 and len(t) == 1, f"段 {seg} 非单头/单尾: head={h} tail={t}"
        heads[seg], tails[seg] = h[0], t[0]

    # 重写串边：段 k 尾 → 段 k+1 头
    fixed = []
    for k in range(1, len(SEGMENTS)):
        src, tgt = tails[SEGMENTS[k - 1]], heads[SEGMENTS[k]]
        old = next((e for e in chain if e["id"] == f"chain_{k}"), None)
        assert old, f"串边 chain_{k} 缺失"
        if old["source"] != src or old["target"] != tgt:
            fixed.append((old["source"], old["target"], src, tgt))
            old["source"], old["target"] = src, tgt
    # JSON 列原地改写 + 同对象回赋 SQLAlchemy 判无变化不落库（run#856 用坏边实证），
    # 必须 flag_modified 显式标脏
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(c, "dag_config")
    db.commit()

    print("段头/尾:", {s: (heads[s], tails[s]) for s in SEGMENTS})
    print(f"修复串边 {len(fixed)} 条:")
    for o_s, o_t, s, t in fixed:
        print(f"  {o_s} -> {o_t}  修正为  {s} -> {t}")

    # 校验：每对相邻段都有 段k-1尾 → 段k头 的串边在库
    db.expire_all()
    c2 = db.query(models.TestCase).filter(models.TestCase.id == 283).first()
    d2 = c2.dag_config
    edge_set = {(e["source"], e["target"]) for e in d2["edges"]}
    for k in range(1, len(SEGMENTS)):
        want = (tails[SEGMENTS[k - 1]], heads[SEGMENTS[k]])
        assert want in edge_set, f"串边缺失: {want}"
    print(f"校验通过：{len(SEGMENTS)} 段串边齐全")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
