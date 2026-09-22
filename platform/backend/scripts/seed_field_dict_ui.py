# 一次性：补齐全链用例（阶段前缀）数据集缺失的字段字典词条（幂等：已存在跳过）
import sys

sys.path.insert(0, '.')
from app.database import SessionLocal  # noqa: E402
from app.models import FieldDictionary  # noqa: E402
from sqlalchemy import select  # noqa: E402

# 词条中文名依据 build_case_generate_order_sub.py 的业务语义
ENTRIES = {
    "entrusted_order_route": "委托订单列表路由",
    "business_order_route": "业务订单列表路由",
    "order_self_route": "自营订单列表路由",
    "entrust": "新增委托订单（开关）",
    "submit": "提交（开关）",
    "save": "保存（开关）",
    "save_draft": "暂存（开关）",
    "booking_space": "订舱（服务勾选）",
    "booking_space_supplier": "订舱供应商",
    "booking_space_user": "订舱经办人",
    "customs_clearance": "报关（服务勾选）",
    "customs_clearance_supplier": "报关供应商",
    "customs_clearance_user": "报关经办人",
    "manifest": "舱单（服务勾选）",
    "manifest_supplier": "舱单供应商",
    "manifest_user": "舱单经办人",
    "insurance": "保险（服务勾选）",
    "insurance_supplier": "保险供应商",
    "insurance_user": "保险经办人",
    "trucking": "拖车（服务勾选）",
    "trucking_supplier": "拖车供应商",
    "trucking_user": "拖车经办人",
    "is_no_customs_clearance_supplier": "无报关供应商（列）",
    "is_no_insurance_supplier": "无保险供应商（列）",
    "is_no_manifest_supplier": "无舱单供应商（列）",
    "service_projects": "服务项目（费用行数据）",
    "upload_files": "上传文件（附件）",
    "container_message": "箱件信息",
    "m_delivery_type": "M放货方式",
    "pod": "卸货港",
    "pot": "中转港",
    "del": "交货期",
}

s = SessionLocal()
try:
    pid = 1
    existing = {f.key for f in s.scalars(
        select(FieldDictionary).where(FieldDictionary.project_id == pid)).all()}
    added = 0
    for key, label in ENTRIES.items():
        if key in existing:
            continue
        s.add(FieldDictionary(project_id=pid, key=key, label=label,
                              created_by=1, updated_by=1))
        added += 1
    s.commit()
    total = len(s.scalars(select(FieldDictionary).where(
        FieldDictionary.project_id == pid)).all())
    print(f"新增 {added} 条，项目字典现有 {total} 条")
finally:
    s.close()
