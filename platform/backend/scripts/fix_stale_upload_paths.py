# -*- coding: utf-8 -*-
"""修复迁移残留的本地绝对路径上传文件引用（2026-10-28）。

现象：线上执行 case 283/287（project 1）upload 步骤报
「上传文件无法解析: 'D:\\CODE\\...\\供应商导入模板.xlsx'（文件中心无此名称文件，且非绝对路径/id）」。
原因：autotest-playwright 迁移数据在 case_node_configs.ui_params 的 steps[].files[]
里保留了本机 Windows 绝对路径；Linux 执行机上 os.path.isabs 不认 D:\\ 开头路径，
且整段路径不是文件中心名称 → 解析失败。文件本体已导入文件中心（id 48/49，project 1）。
修法：把绝对路径替换为文件中心文件名（_resolve_file_path 的名称检索分支，
按 (project_id, name) 命中），纯配置修复，不改代码。双库（线上+本地）同步执行。

幂等：已无 autotest-playwright 残留时直接跳过。dry-run 默认，APPLY=1 落库。
用法：
    python scripts/fix_stale_upload_paths.py                     # dry-run（本地库）
    DB_HOST=192.168.2.51 DB_PORT=20001 DB_USER=dev-wifi DB_PASSWORD=... \
        APPLY=1 python scripts/fix_stale_upload_paths.py         # 线上库
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pymysql

APPLY = os.environ.get("APPLY") == "1"
STALE_DIR = r"D:\CODE\PyCharm\pythonProject\autotest-playwright\module\ordermanage\entrustedorderadd\files"
# 绝对路径 → 文件中心名称（须与 test_files.name 完全一致）
REPLACES = {
    STALE_DIR + "\\供应商导入模板.xlsx": "供应商导入模板.xlsx",
    STALE_DIR + "\\邮件分发第3期测试报告.pdf": "邮件分发第3期测试报告.pdf",
}


def fix_values(obj):
    """递归替换 steps[].files[] 等处的精确匹配字符串，返回替换次数。"""
    n = 0
    if isinstance(obj, dict):
        for v in obj.values():
            n += fix_values(v)
    elif isinstance(obj, list):
        for v in obj:
            n += fix_values(v)
    elif isinstance(obj, str) and obj in REPLACES:
        # 就地替换由上层写回，这里只统计；调用处用返回值重写
        n += 1
    return n


def rewrite(obj):
    if isinstance(obj, dict):
        return {k: rewrite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rewrite(v) for v in obj]
    if isinstance(obj, str) and obj in REPLACES:
        return REPLACES[obj]
    return obj


def main():
    conn = pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "123456"),
        database=os.environ.get("DB_NAME", "fin_ui_test"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as c:
            # 前置校验：目标文件在文件中心（同项目）确实存在
            for name in REPLACES.values():
                c.execute(
                    "SELECT id, project_id FROM test_files WHERE name=%s ORDER BY id DESC LIMIT 1",
                    (name,))
                f = c.fetchone()
                if not f:
                    raise SystemExit(f"文件中心缺少 {name}，中止（先导入文件中心再修复）")
                print(f"文件中心就绪: {name} -> id={f['id']} (project {f['project_id']})")

            c.execute(
                "SELECT id, case_id, node_id, ui_params FROM case_node_configs "
                "WHERE ui_params LIKE %s", ("%autotest-playwright%",))
            rows = c.fetchall()
            print(f"\n残留节点配置 {len(rows)} 行")
            if not rows:
                print("无可修复行，退出")
                return

            out_dir = Path(__file__).resolve().parent / "backups"
            out_dir.mkdir(exist_ok=True)
            backup = out_dir / f"stale_upload_paths_{datetime.now():%Y%m%d_%H%M%S}.json"
            backup.write_text(
                json.dumps(rows, ensure_ascii=False, indent=1, default=str),
                encoding="utf-8")
            print(f"已备份原值 → {backup.name}")

            for r in rows:
                up = json.loads(r["ui_params"]) if isinstance(r["ui_params"], str) else r["ui_params"]
                n = fix_values(up)
                new_up = rewrite(up)
                print(f"  cfg#{r['id']} case {r['case_id']} node {r['node_id']}: 替换 {n} 处")
                if APPLY and n:
                    c.execute(
                        "UPDATE case_node_configs SET ui_params=%s WHERE id=%s",
                        (json.dumps(new_up, ensure_ascii=False), r["id"]))
            if APPLY:
                c.execute(
                    "SELECT COUNT(*) AS n FROM case_node_configs WHERE ui_params LIKE %s",
                    ("%autotest-playwright%",))
                left = c.fetchone()["n"]
                conn.commit()
                print(f"\nAPPLY 已提交，剩余残留 {left} 行")
            else:
                conn.rollback()
                print("\nDRY-RUN（APPLY=1 落库）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
