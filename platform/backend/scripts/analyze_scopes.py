"""页面域健康度分析（只读）：
1. 全部页面域 + 元素数
2. 归一化（去分隔符/小写）找高度相似域
3. 每个域被用例节点真实引用的元素数（ui_params.element.element_id）
"""
import os
import re
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


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> None:
    db = SessionLocal()
    els = db.query(models.UiElement).all()
    by_scope = defaultdict(list)
    for e in els:
        by_scope[e.page_scope].append(e)

    # 用例节点引用的 element_id 集合
    used_ids = set()
    for cfg in db.query(models.CaseNodeConfig).all():
        el = (cfg.ui_params or {}).get("element") if cfg.ui_params else None
        if isinstance(el, dict) and el.get("element_id"):
            used_ids.add(int(el["element_id"]))

    print(f"总元素 {len(els)}，页面域 {len(by_scope)} 个，被用例引用的元素 {len(used_ids)} 个\n")
    print("== 全部页面域（元素数/被引用数） ==")
    for s in sorted(by_scope):
        ids = [e.id for e in by_scope[s]]
        used = sum(1 for i in ids if i in used_ids)
        print(f"  {s}  {len(ids)}元素/{used}引用")

    print("\n== 归一化后高度相似的域组 ==")
    groups = defaultdict(list)
    for s in by_scope:
        groups[norm(s)].append(s)
    for k, ss in sorted(groups.items()):
        if len(ss) > 1:
            print(f"  组 [{k}]:")
            for s in sorted(ss):
                ids = [e.id for e in by_scope[s]]
                used = sum(1 for i in ids if i in used_ids)
                print(f"    {s}  {len(ids)}元素/{used}引用")

    # 相似组内元素 key 交集（判断是否同批元素被重复导入）
    print("\n== 相似组元素 key 交集 ==")
    for k, ss in sorted(groups.items()):
        if len(ss) > 1:
            sets = [{e.element_key for e in by_scope[s]} for s in sorted(ss)]
            inter = set.intersection(*sets)
            print(f"  组 [{k}] 共同 key {len(inter)} 个: {sorted(inter)[:8]}")
            for s, ks in zip(sorted(ss), sets):
                only = ks - set.union(*(x for x in sets if x is not ks)) if len(sets) > 1 else ks
                print(f"    {s} 独有 key {len(only)} 个")

    # 未被任何用例引用的元素（潜在的垃圾，含孤立域）
    unused = [e for e in els if e.id not in used_ids]
    print(f"\n== 未被引用元素 {len(unused)}/{len(els)}，按域汇总 ==")
    un_by_scope = defaultdict(int)
    for e in unused:
        un_by_scope[e.page_scope] += 1
    for s in sorted(un_by_scope):
        total = len(by_scope[s])
        print(f"  {s}: {un_by_scope[s]}/{total} 未引用")

    db.close()


if __name__ == "__main__":
    main()
