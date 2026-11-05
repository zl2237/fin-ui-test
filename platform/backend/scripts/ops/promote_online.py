# -*- coding: utf-8 -*-
"""修复晋升线上（用户已授权 2026-11-02「推送线上吧」）。
A) 线上库写入（单事务）：
   W1 ui_elements ×11（602,604,616,618,625,627,629,631,655,656,657）strategies+description ← 本地原样
   W2 data_set_rows 键级更新：ds150 operator_id；ds155 bl_no+3供应商；ds159/167 s1/s2_operator_id
   W3 case277/n1 ui_params ← 本地终态原样（16 步绿态，不重放 fix_277.py）
B) 线上平台 API：admin 登录 → POST /api/files/upload?project_id=1 ×2（中文名）
"""
import json
import sys

import pymysql

EL_IDS = [602, 604, 616, 618, 625, 627, 629, 631, 655, 656, 657]
DS_KEYS = {
    150: {  # row_index -> {key: local_value}
        "operator_id": None,  # 占位：实际值按行从本地取
    },
}
# 需要按行取本地值的键清单（键级合并，不动其他键）
DS_PATCH = {
    150: ["operator_id"],
    155: ["bl_no", "supplier_customs_clearance", "supplier_manifest", "supplier_insurance"],
    159: ["s1_operator_id", "s2_operator_id"],
    167: ["s1_operator_id", "s2_operator_id"],
}


def conn(local_):
    if local_:
        return pymysql.connect(host="127.0.0.1", port=3306, user="root",
                               password="123456", database="fin_ui_test", charset="utf8mb4")
    return pymysql.connect(host="192.168.2.51", port=20001, user="dev-wifi",
                           password="Dev%%0532", database="fin_ui_test", charset="utf8mb4")


def jload(x):
    return json.loads(x) if isinstance(x, str) else x


def main():
    apply = "--apply" in sys.argv
    lc, oc = conn(True), conn(False)
    lcur, ocur = lc.cursor(), oc.cursor()
    n = 0

    # W1 元素
    for eid in EL_IDS:
        lcur.execute("SELECT strategies, description FROM ui_elements WHERE id=%s", (eid,))
        st, desc = lcur.fetchone()
        ocur.execute("SELECT strategies FROM ui_elements WHERE id=%s", (eid,))
        ost = ocur.fetchone()
        if not ost:
            print(f"el{eid}: 线上不存在，跳过（异常！）")
            continue
        if ost[0] == st:
            print(f"el{eid}: 已一致")
            continue
        print(f"el{eid}: 重锚 <- 本地")
        if apply:
            ocur.execute("UPDATE ui_elements SET strategies=%s, description=%s WHERE id=%s",
                         (st, desc, eid))
            n += 1

    # W2 数据集（按 dataset_id+row_index 对齐，键级合并）
    for ds, keys in DS_PATCH.items():
        lcur.execute("SELECT row_index, data FROM data_set_rows WHERE dataset_id=%s ORDER BY row_index", (ds,))
        lrows = {ri: jload(d) for ri, d in lcur.fetchall()}
        ocur.execute("SELECT row_index, data FROM data_set_rows WHERE dataset_id=%s ORDER BY row_index", (ds,))
        orows = {ri: jload(d) for ri, d in ocur.fetchall()}
        for ri, ldata in lrows.items():
            if ri not in orows:
                print(f"ds{ds} row{ri}: 线上缺行，跳过（异常！）")
                continue
            odata = orows[ri]
            dirty = {}
            for k in keys:
                if k in ldata and odata.get(k) != ldata[k]:
                    dirty[k] = ldata[k]
            if not dirty:
                continue
            print(f"ds{ds} row{ri}: {json.dumps(dirty, ensure_ascii=False)[:120]}")
            if apply:
                odata.update(dirty)
                ocur.execute("UPDATE data_set_rows SET data=%s WHERE dataset_id=%s AND row_index=%s",
                             (json.dumps(odata, ensure_ascii=False), ds, ri))
                n += 1

    # W3 case277/n1 ui_params 整段拷贝（原样字节）
    lcur.execute("SELECT ui_params FROM case_node_configs WHERE case_id=277 AND node_id='n1'")
    lp = lcur.fetchone()[0]
    ocur.execute("SELECT ui_params FROM case_node_configs WHERE case_id=277 AND node_id='n1'")
    op = ocur.fetchone()[0]
    if lp == op:
        print("case277/n1: 已一致")
    else:
        ls = len(jload(lp).get("steps", [])) if lp else 0
        os_ = len(jload(op).get("steps", [])) if op else 0
        print(f"case277/n1: ui_params 整段 <- 本地（steps {os_} -> {ls}）")
        if apply:
            ocur.execute("UPDATE case_node_configs SET ui_params=%s WHERE case_id=277 AND node_id='n1'", (lp,))
            n += 1

    if apply:
        oc.commit()
    lc.close()
    oc.close()
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: {n} 处写入")


if __name__ == "__main__":
    main()
