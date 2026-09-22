"""把 autotest-playwright 最长的用例（flow_generate_order_sub 全链 6 阶段，with_all_project 变体）
映射为平台 DAG 用例，写入真实平台库（project 1）。

阶段链（对应 flow/data/json/generate_order_sub_after_fee_add/flow_with_all_project.json）：
  s1 委托订单新增(entrust=1 生效) → s2 业务订单新增(submit=1 生效)
  → s3 自营订单编辑(报关/舱单/保险 供应商+服务人员) → s4 自营费用添加(报关应收/应付+确认)
  → s5 业务订单费用(订舱 应收/应付) → s6 生成子订单

映射约定：
- 数据：6 个 Excel 的单数据集按键前缀合并为一行（s1_/s3_/s5_…），bl_no/customer_id 全链共享
  （bl_no 由本脚本按原框架规则生成 uitestBlNo+时间戳）； DataSet 绑定用例 → 平台数据驱动
- 定位：优先元素库 element_id（locator JSON 原策略）；动态结构用探针确认过的稳定类名 xpath
- 弹窗链/条件交互（可选"继续提交"、确保未勾选）用 evaluate 原子化兜底
- 费用表头在执行时由 evaluate 节点 dump 进 facts（报告可查，便于列号校正）

用法：.venv\\Scripts\\python scripts\\build_case_generate_order_sub.py [--keep]
  默认先删除同名旧用例与旧数据集再重建（幂等）
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR.parent.parent))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")
import os

os.environ.setdefault("DB_PASSWORD", "x")

AUTOTEST = BACKEND_DIR.parent.parent.parent / "autotest-playwright"
PROJECT_ID = 1
ENV_ID = 1
CASE_NAME = "[UI迁移] 生成子订单全链路-包含所有服务项目"
# 费用两阶段（s4 自营费用/s5 业务费用）开关：新版费用弹层 DOM 与旧框架定位资产差异大
# （"新增行"按钮语义变化+表格容器深嵌套），待元素库按新版 DOM 重建后置 True 启用；
# False = before_fee_add 变体（原框架亦有此变体）：跳过费用直接生成子订单
INCLUDE_FEES = True

STAGE_FILES = [
    ("s1", "entrustedorderadd/data/entrusted_order_add_with_all_project.xlsx"),
    ("s2", "businessorderadd/data/business_order_add_with_all_project.xlsx"),
    ("s3", "orderselfdetails/data/order_self_edit_with_all_project.xlsx"),
    ("s4", "orderselfdetails/data/order_self_fee_add_with_all_project.xlsx"),
    ("s5", "businessorderdetails/data/real_fee_add_with_all_project.xlsx"),
    ("s6", "businessorderdetails/data/generate_order_sub_with_all_project.xlsx"),
]
# 各阶段跨页共享的键（不加重缀，全链一份）
SHARED_KEYS = {"bl_no", "customer_id"}

E1 = "ordermanage/entrustedorderadd"
E2 = "ordermanage/businessorderadd"
E3 = "ordermanage/orderselfdetails"
E6 = "ordermanage/businessorderdetails"


def load_excel_rows():
    sys.path.insert(0, str(AUTOTEST))
    from utils.data_helper import get_testdata
    rows = {}
    for prefix, rel in STAGE_FILES:
        data = get_testdata(str(AUTOTEST / "module" / "ordermanage" / rel), absolute_path=True)
        rows[prefix] = next(iter(data.values()))
    return rows


class NodeBuilder:
    def __init__(self, elem_ids: dict, row: dict):
        self.elem = elem_ids  # "scope.key" -> id
        self.row = row  # 合并后的数据行（含 s1_/s3_ 前缀与共享键）
        self.nodes: list[dict] = []
        self.specs: list[dict] = []

    def el(self, scope: str, key: str) -> dict:
        eid = self.elem.get(f"{scope}.{key}")
        if not eid:
            raise KeyError(f"元素库缺少 {scope}.{key}")
        return {"element_id": eid}

    def add(self, label: str, **params):
        nid = f"n{len(self.nodes) + 1:03d}"
        self.nodes.append({"id": nid, "data": {"label": label, "step_type": "ui"}})
        cfg = dict(params)
        assertions = cfg.pop("assertions", None) or []
        self.specs.append({"node_id": nid, "step_type": "ui", "ui_params": cfg,
                           "assertions": assertions, "api_id": None})
        return nid

    # --- 常用组合 ---
    def goto(self, label, route, wait_list=True):
        self.add(label, action="goto", url=route)
        if wait_list:
            # 等检索区提单号框出现（vxe 列表就绪信号；该框初始 readonly，点击后激活可输入）
            self.add("等待列表就绪", action="wait", value=800,
                     element={"strategy": "xpath", "value": "//input[@placeholder='提单号']"},
                     timeout_ms=15000)
        else:
            self.add(f"{label}-落地等待", action="wait", value=1500)

    def search(self, label="检索目标订单"):
        """列表检索（组合动作）：激活检索框→填提单号→回车→点查询→等业务行出现。
        全链 6 阶段共用同一检索范式（${bl_no} 数据驱动）。"""
        self.add(label, action="search", value="${bl_no}")

    def pick(self, label, scope, key, var):
        self.add(label, action="pick", element=self.el(scope, key), value=var)

    def fill(self, label, scope, key, var):
        self.add(label, action="fill", element=self.el(scope, key), value=var)

    def date(self, label, scope, key, var):
        self.add(label, action="date", element=self.el(scope, key), value=var)


def service_project_xpath(project: str, col: str) -> dict:
    """服务项目行（订舱/报关/…）的供应商/服务人员输入定位。
    行锚点用"行文本以项目名开头"（委托页/自营页通用，不依赖内部 p 的类名）"""
    return {"strategy": "xpath", "value":
            f"//div[contains(@class,'formSt-table-tr')][starts-with(normalize-space(.),'{project}')]"
            f"//div[contains(@class,'formSt-table-{col}')]//input[@class='el-input__inner']"}


def row_button(name: str) -> dict:
    """列表行内操作入口：vxe 操作列在固定列副本中，元素形态不定（span/a/button），
    检索后行唯一，按精确文本匹配任一标签形态"""
    return {"strategy": "xpath",
            "value": f"//*[self::span or self::a or self::button][normalize-space()='{name}']"}


def conditional_check(name: str) -> str:
    """服务项目条件勾选：行已存在（已勾选）则跳过；行不存在则点击项目文本勾选。
    （未勾选的项目没有 formSt 行，checkbox 以项目名文本呈现在服务项目选择区）"""
    label = json.dumps(name, ensure_ascii=False)
    return ("((n)=>{"
            "const rows=[...document.querySelectorAll('[class*=formSt-table-tr]')]"
            ".filter(r=>r.textContent.trim().startsWith(n));"
            "if(rows.length)return 'already';"
            "const t=[...document.querySelectorAll('.el-checkbox, .el-form-item')]"
            ".filter(e=>e.textContent.trim().endsWith(n)&&e.querySelector('input[type=checkbox]'));"
            "if(!t.length)return 'no-cb';"
            "t[0].querySelector('input[type=checkbox]').closest('label,.el-checkbox').click();"
            "return 'checked'})(" + label + ")")


def label_input(label: str) -> dict:
    """新版表单：按 label 文本定位表单项内的输入框（input 无 id，label 是唯一稳定锚点）"""
    return {"strategy": "xpath", "value":
            f"//div[contains(@class,'el-form-item')]"
            f"[.//label[contains(normalize-space(.),'{label}')]]//input[@class='el-input__inner']"}


def textarea_input(name: str) -> dict:
    """托书区 textarea（无 label 关联）：按表单项内任意文本节点锚定（如 发货人/收货人/通知人）"""
    return {"strategy": "xpath", "value":
            f"//div[contains(@class,'el-form-item')][.//*[contains(text(),'{name}')]]//textarea"}


def container_input(row_no: int, td: int, nth: int | None = None) -> dict:
    """集装箱表格第 row_no 行第 td 列的输入框（nth 用于同 td 多箱号/封号）"""
    xp = (f"//div[contains(@class,'app-edit__container')]//table[contains(@class,'el-table__body')]"
          f"//tbody//tr[{row_no}]/td[{td}]//input")
    if nth:
        xp = f"({xp})[{nth}]"
    return {"strategy": "xpath", "value": xp}


def build_nodes(b: NodeBuilder, rows):
    r = b.row
    # ================= 阶段1：委托订单新增（生效） =================
    b.goto("s1-打开委托订单列表", r["s1_entrusted_order_route"])
    b.add("s1-新建订单", action="click", element={"strategy": "button", "value": "新建订单"})
    b.add("s1-等待表单", action="wait", value=2500)
    # 新版表单：input 无 id，按 label 定位（label 文本来自真实 DOM 探针）
    b.add("s1-提单号", action="fill", element=label_input("提单号"), value="${bl_no}")
    b.add("s1-下单客户", action="pick", element=label_input("下单客户名称"), value="${customer_id}")
    b.add("s1-客户联系人", action="pick", element=label_input("客户联系人"), value="${s1_customer_contact_id}")
    b.add("s1-结算操作", action="pick", element=label_input("结算操作"), value="${s1_operator_id}")
    b.add("s1-政策类型", action="pick", element=label_input("政策类型"), value="${s1_policy_type}")
    b.add("s1-服务策略名称", action="pick", element=label_input("服务策略名称"), value="${s1_policy_id}")
    files_dir = AUTOTEST / "module" / "ordermanage" / "entrustedorderadd" / "files"
    b.add("s1-上传文件", action="upload", element={"strategy": "css", "value": "input[type=file]"},
          files=[str(files_dir / "供应商导入模板.xlsx"), str(files_dir / "邮件分发第3期测试报告.pdf")])
    # 服务项目勾选（条件勾选：未勾才点，避免取消默认勾选项）
    for proj_key, proj_name in [("booking_space", "订舱"), ("customs_clearance", "报关"),
                                ("manifest", "舱单"), ("insurance", "保险")]:
        if r.get(f"s1_{proj_key}") == "1":
            b.add(f"s1-勾选{proj_name}", action="evaluate", value=conditional_check(proj_name))
    # 服务项目勾选后 dump 行结构（调试：确认供应商/服务人员输入的真实定位）
    b.add("s1-dump服务项目区", action="evaluate", value=(
        "JSON.stringify([...document.querySelectorAll('[class*=formSt-table-tr]')]"
        ".map(r=>({cls:(r.className||'').toString().slice(0,50),"
        "txt:r.textContent.trim().slice(0,50), inputs:r.querySelectorAll('input').length})))"))
    # 订舱 供应商+服务人员（结算业务）；报关/舱单/保险 服务人员
    b.add("s1-订舱供应商", action="pick", element=service_project_xpath("订舱", "supplier"),
          value="${s1_booking_space_supplier}")
    b.add("s1-订舱服务人员", action="pick", element=service_project_xpath("订舱", "user"),
          value="${s1_booking_space_user}")
    b.add("s1-报关服务人员", action="pick", element=service_project_xpath("报关", "user"),
          value="${s1_customs_clearance_user}")
    b.add("s1-舱单服务人员", action="pick", element=service_project_xpath("舱单", "user"),
          value="${s1_manifest_user}")
    b.add("s1-保险服务人员", action="pick", element=service_project_xpath("保险", "user"),
          value="${s1_insurance_user}")
    # 运输信息（新版字段名：成交方式/结汇方式/M放货方式/卸货港/目的地）
    b.add("s1-业务类型", action="pick", element=label_input("业务类型"), value="${s1_business_type}")
    b.add("s1-成交方式", action="pick", element=label_input("成交方式"), value="${s1_trade_term}")
    b.add("s1-承运人", action="pick", element=label_input("承运人"), value="${s1_carrier}")
    b.add("s1-客户单号", action="fill", element=label_input("客户单号"), value="${customer_order_sn}")
    b.add("s1-ETD", action="date", element=label_input("预计开航(ETD)"), value="${s1_etd}")
    b.add("s1-ATD", action="date", element=label_input("实际开航(ATD)"), value="${s1_atd}")
    b.add("s1-船名", action="fill", element=label_input("船名"), value="${s1_ship_name}")
    b.add("s1-航次", action="fill", element=label_input("航次"), value="${s1_voy}")
    b.add("s1-起运港", action="pick", element=label_input("起运港"), value="${s1_pol}")
    b.add("s1-中转港", action="pick", element=label_input("中转港"), value="${s1_pot}")
    b.add("s1-卸货港", action="pick", element=label_input("卸货港"), value="${s1_pod}")
    b.add("s1-目的地", action="pick", element=label_input("目的地"), value="${s1_del}")
    b.add("s1-结汇方式", action="pick", element=label_input("结汇方式"), value="${s1_terms_payment}")
    b.add("s1-运输条款", action="pick", element=label_input("运输条款"), value="${s1_terms_transport}")
    b.add("s1-付款方式", action="pick", element=label_input("付款方式"), value="${s1_pay_type}")
    b.add("s1-M放货方式", action="pick", element=label_input("M放货方式"), value="${s1_m_delivery_type}")
    # 货物信息
    b.add("s1-货物类型", action="pick", element=label_input("货物类型"), value="${s1_cargo_type}")
    b.add("s1-件数", action="fill", element=label_input("件数"), value="${s1_num}")
    b.add("s1-毛重", action="fill", element=label_input("毛重"), value="${s1_gross_weight}")
    b.add("s1-体积", action="fill", element=label_input("体积"), value="${s1_bulk}")
    b.add("s1-包装", action="fill", element=label_input("包装"), value="${s1_packer}")
    # 集装箱（列：td2箱型 td3箱量 td4海运费单价 td5箱号 td6封号；组序=行号）
    groups = [g for g in str(r["s1_container_message"]).split(";") if g.strip()]
    for gi, group in enumerate(groups, start=1):
        parts = group.split("/")
        b.add(f"s1-新增集装箱{gi}", action="click", element=b.el(E1, "container_add_button"))
        b.add(f"s1-集装箱{gi}箱型", action="pick", element=container_input(gi, 2), value=parts[0])
        b.add(f"s1-集装箱{gi}箱量", action="fill", element=container_input(gi, 3), value=parts[1])
        b.add(f"s1-集装箱{gi}单价", action="fill", element=container_input(gi, 4), value=parts[2])
        for ni, box in enumerate(parts[3].split(","), start=1):
            b.add(f"s1-集装箱{gi}箱号{ni}", action="fill", element=container_input(gi, 5, ni), value=box)
        for ni, seal in enumerate(parts[4].split(","), start=1):
            b.add(f"s1-集装箱{gi}封号{ni}", action="fill", element=container_input(gi, 6, ni), value=seal)
    # 托书信息（textarea 无 label 关联，暂跳过——非必填不影响下单）
    # 委托生效 = 新版"分发"（点分发→确认弹窗→可选箱号校验→~4s后 toast+跳列表）
    b.add("s1-点击分发", action="click_text", value="分发")
    b.add("s1-等待确认弹窗", action="wait", value=1500)
    b.add("s1-确认提交", action="confirm")
    b.add("s1-等待箱号校验弹窗", action="wait", value=1500)
    b.add("s1-箱号校验(可选继续提交)", action="optional_confirm")
    b.add("s1-等待系统跳转落地", action="wait", value=2500)
    b.add("s1-校验分发成功", action="toast_watch", value="成功", timeout_ms=12000)

    # ================= 阶段2：业务订单新增（提交生效） =================
    b.goto("s2-打开业务订单列表", r["s2_business_order_route"])
    b.search("s2")
    b.add("s2-点击编辑(行内)", action="row_button", value="编辑")
    b.add("s2-等待编辑页", action="wait", value=2500)
    # 该页 file input 非 multiple，只能逐文件上传
    b.add("s2-上传文件1", action="upload", element={"strategy": "css", "value": "input[type=file]"},
          files=[str(files_dir / "供应商导入模板.xlsx")])
    b.add("s2-等待上传1", action="wait", value=1200)
    b.add("s2-上传文件2", action="upload", element={"strategy": "css", "value": "input[type=file]"},
          files=[str(files_dir / "邮件分发第3期测试报告.pdf")])
    b.add("s2-等待上传2", action="wait", value=1200)
    b.add("s2-业务类型", action="pick", element=label_input("业务类型"), value="${s2_business_type}")
    b.add("s2-成交方式", action="pick", element=label_input("成交方式"), value="${s2_trade_term}")
    b.add("s2-承运人", action="pick", element=label_input("承运人"), value="${s2_carrier}")
    b.add("s2-客户单号", action="fill", element=label_input("客户单号"), value="${customer_order_sn}")
    b.add("s2-ETD", action="date", element=label_input("预计开航(ETD)"), value="${s2_etd}")
    b.add("s2-ATD", action="date", element=label_input("实际开航(ATD)"), value="${s2_atd}")
    b.add("s2-船名", action="fill", element=label_input("船名"), value="${s2_ship_name}")
    b.add("s2-航次", action="fill", element=label_input("航次"), value="${s2_voy}")
    b.add("s2-起运港", action="pick", element=label_input("起运港"), value="${s2_pol}")
    b.add("s2-中转港", action="pick", element=label_input("中转港"), value="${s2_pot}")
    b.add("s2-卸货港", action="pick", element=label_input("卸货港"), value="${s2_pod}")
    b.add("s2-目的地", action="pick", element=label_input("目的地"), value="${s2_del}")
    b.add("s2-结汇方式", action="pick", element=label_input("结汇方式"), value="${s2_terms_payment}")
    b.add("s2-运输条款", action="pick", element=label_input("运输条款"), value="${s2_terms_transport}")
    b.add("s2-付款方式", action="pick", element=label_input("付款方式"), value="${s2_pay_type}")
    b.add("s2-M放货方式", action="pick", element=label_input("M放货方式"), value="${s2_m_delivery_type}")
    b.add("s2-货物类型", action="pick", element=label_input("货物类型"), value="${s2_cargo_type}")
    b.add("s2-件数", action="fill", element=label_input("件数"), value="${s2_num}")
    b.add("s2-毛重", action="fill", element=label_input("毛重"), value="${s2_gross_weight}")
    b.add("s2-体积", action="fill", element=label_input("体积"), value="${s2_bulk}")
    b.add("s2-包装", action="fill", element=label_input("包装"), value="${s2_packer}")
    # 托书信息（业务订单提交必填）。两段式：预填（DOM 序前 3 可见 textarea 兜底）→
    # 提交 → 按校验错误自愈（"请录入XX"错误元素所在容器内的 textarea 即目标字段）
    # 托书信息（业务订单提交必填）。textarea 无 label，按文档序精确定位（探针 taIdx 验证：
    # 发货人=1 收货人=2 通知人=4）；必须用 playwright fill（真实输入事件），JS setter Vue 接不住
    # 托书三件套（业务订单提交必填）。关键（probe16 闭环验证）：托书区组件懒渲染——
    # 必须先滚动到页面最底部激活真实组件，否则操作的是克隆 DOM（值不入 Vue 状态）；
    # 输入用 type（真实键盘）；DOM 序 0 号是页头隐藏框，目标=nth=1/2/3
    b.add("s2-滚动到页面底部", action="scroll_bottom")
    b.add("s2-等待底部渲染", action="wait", value=1200)
    for n, (key, name) in enumerate([("shipper", "发货人"), ("consignee", "收货人"), ("notifier", "通知人")]):
        b.add(f"s2-{name}(键盘输入)", action="type", value="${s2_%s}" % key,
              element={"strategy": "css", "value": f"textarea >> nth={n + 1}"})
    b.add("s2-点击提交", action="click_text", value="提交")
    b.add("s2-提交反馈dump", action="wait", value=1500)
    b.add("s2-等待确认弹窗", action="wait", value=1500)
    b.add("s2-确认提交", action="confirm")
    b.add("s2-等待箱号校验弹窗", action="wait", value=1500)
    b.add("s2-箱号校验(可选继续提交)", action="optional_confirm")
    b.add("s2-等待生效弹窗", action="wait", value=2500)
    b.add("s2-确认生效", action="confirm")
    b.add("s2-生效弹窗重试等待", action="wait", value=2000)
    b.add("s2-确认生效重试", action="confirm")
    b.add("s2-等待系统跳转落地", action="wait", value=2500)
    b.add("s2-校验提交成功", action="toast_watch", value="成功", timeout_ms=12000)

    # ================= 阶段3：自营订单编辑 =================
    b.goto("s3-打开自营订单列表", r["s3_order_self_route"])
    b.search("s3")
    b.add("s3-点击详情(行内)", action="row_button", value="详情")
    b.add("s3-等待详情页", action="wait", value=2500)
    b.add("s3-点击编辑", action="click_text", value="编辑")
    b.add("s3-等待编辑页", action="wait", value=2000)
    b.add("s3-确保无供应商未勾选", action="uncheck_all",
          element={"strategy": "css",
                   "value": ".formSt-table-tr .formSt-table-isNo input[type=checkbox]"})
    b.add("s3-dump自营项目区", action="evaluate", value=(
        "JSON.stringify({rows:[...document.querySelectorAll('[class*=formSt-table-tr]')]"
        ".map(r=>({cls:(r.className||'').toString().slice(0,40),txt:r.textContent.trim().slice(0,40),"
        "inputs:r.querySelectorAll('input').length})),"
        "checkboxes:document.querySelectorAll('input[type=checkbox]').length,"
        "bodyHead:document.body.innerText.replace(/\\s+/g,' ').slice(0,150)})"))
    # 只补供应商：服务人员已由 s1 委托分发继承；先供应商后pick人员会级联清空供应商
    # （run#569 实证：pick 人员后供应商丢失 → 保存失败 → s4 被供应商校验拦截）
    sup_expect = []
    for proj_key, proj_name in [("customs_clearance", "报关"), ("manifest", "舱单"), ("insurance", "保险")]:
        if r.get(f"s3_{proj_key}") == "1":
            b.add(f"s3-{proj_name}供应商", action="pick",
                  element=service_project_xpath(proj_name, "supplier"),
                  value="${s3_%s_supplier}" % proj_key)
            sup_expect.append(str(r.get(f"s3_{proj_key}_supplier") or ""))
    b.add("s3-保存并确认", action="save", value="保存成功", timeout_ms=15000)
    # 保存持久化实证：页面文本须包含全部期望供应商（防"成功但没存上"）
    if any(sup_expect):
        need_js = json.dumps([s for s in sup_expect if s], ensure_ascii=False)
        b.add("s3-校验供应商生效", action="evaluate", value=(
            "new Promise(res=>setTimeout(()=>{"
            "const t=document.body.innerText;"
            "const miss=" + need_js + ".filter(n=>!t.includes(n));"
            "res(miss.length?('miss:'+miss.join(',')):'ok:供应商已生效')},1500))"),
              assertions=[{"type": "json_path_contains", "path": "$.result", "expected": "ok:供应商"}])

    if INCLUDE_FEES:
        # ================= 阶段4：自营费用（按服务项目逐个编辑） =================
        # 结构（probe33/36 实证）：编辑X费用打开 pane 内联表单 form.el-form，
        # inner[1]=应收 inner[2]=应付；"新增标准费用"按钮[0]=加应收行 [1]=加应付行；
        # 新行仅预填结算对象+数量。行列（xpath 1 基，主表 body-wrapper 内）：
        # 4=费用名称(pick) 5=币制(pick) 6=含税单价(fill) 7=单位(pick)
        # 8=规格(pick,单位=箱型才填) 9=数量(fill) 10=备注(fill)；结算对象(3)已预填
        FEE_CELL = {
            "put": ("(//form[@class='el-form']/div[@class='inner'][1]"
                    "//div[contains(@class, 'el-table__body-wrapper')]/table"
                    "[contains(@class, 'el-table__body')]/tbody/tr[last()]/td[{td}]"
                    "//input[@class='el-input__inner'])[1]"),
            "pay": ("(//form[@class='el-form']/div[@class='inner'][2]"
                    "//div[contains(@class, 'el-table__body-wrapper')]/table"
                    "[contains(@class, 'el-table__body')]/tbody/tr[last()]/td[{td}]"
                    "//input[@class='el-input__inner'])[1]"),
        }
        FEE_COLS = {"cost_name": 4, "currency": 5, "unit_price": 6, "unit": 7,
                    "specs": 8, "num": 9, "remark": 10}
        FEE_PICK_COLS = {"cost_name", "currency", "unit", "specs"}
        SVC_META = {"customs_clearance": ("报关", "编辑报关费用"),
                    "manifest": ("舱单", "编辑舱单费用"),
                    "insurance": ("保险", "编辑保险费用")}
        b.goto("s4-打开自营订单列表", r["s4_order_self_route"])
        b.search("s4")
        b.add("s4-点击详情", action="click", element=b.el(E3, "details_button"))
        b.add("s4-等待详情页", action="wait", value=2500)
        for proj_key, proj_msg in rows["s4"]["service_project"].items():
            if proj_key not in SVC_META or not proj_msg.get("rows"):
                continue
            tab_name, fee_btn = SVC_META[proj_key]
            b.add(f"s4-{tab_name}tab", action="click",
                  element={"strategy": "role", "value": "tab", "name": tab_name})
            b.add(f"s4-{tab_name}等待tab", action="wait", value=1500)
            b.add(f"s4-点击{fee_btn}", action="click_text", value=fee_btn)
            b.add(f"s4-{tab_name}等待费用表单", action="wait", value=3000)
            b.add(f"s4-{tab_name}dump层内按钮", action="evaluate", value=(
                "JSON.stringify([...document.querySelectorAll('button')].filter(b=>b.offsetParent)"
                ".map(b=>(b.textContent||'').trim()||'(icon)').filter(Boolean).slice(0,12))"))
            for ri, row in enumerate(proj_msg.get("rows", []), 1):
                copy_pay = bool(row.get("is_copy_to_pay"))
                b.add(f"s4-{tab_name}r{ri}-新增应收行", action="click_text",
                      value="新增标准费用", index=0)
                if not copy_pay:
                    b.add(f"s4-{tab_name}r{ri}-新增应付行", action="click_text",
                          value="新增标准费用", index=1)
                b.add(f"s4-{tab_name}r{ri}-等待新行", action="wait", value=900)
                for sym in ("put", "pay"):
                    if sym == "pay" and copy_pay:
                        continue
                    for col, td in FEE_COLS.items():
                        val = row.get(f"{sym}_{col}")
                        if val in (None, ""):
                            continue
                        if col == "specs" and row.get(f"{sym}_unit") != "箱型":
                            continue
                        act = "pick" if col in FEE_PICK_COLS else "fill"
                        b.add(f"s4-{tab_name}r{ri}-{sym}-{col}", action=act,
                              element={"strategy": "xpath", "value": FEE_CELL[sym].format(td=td)},
                              value=str(val))
            b.add(f"s4-{tab_name}-保存并确认", action="save", value="保存成功", timeout_ms=15000)
            if proj_msg.get("is_confirm") == "1":
                b.add(f"s4-{tab_name}-业务确认", action="click_text", value="业务确认")
                b.add(f"s4-{tab_name}-校验确认", action="toast_watch",
                      value="确认完成", timeout_ms=12000)

        # ================= 阶段5：业务订单费用（新版=从自营费用导入） =================
        # 新版 UI（probe38-43 实证）：实际费用 tab 改名"订单费用"（#tab-order_actual_cost）；
        # "编辑费用"是下拉选择服务（报关/舱单/保险，订舱已不在可选集）；
        # 各服务只有"导入X费用"（从 s4 自营费用引入），旧版手工 booking_space
        # 费用行入口已不存在 → 本阶段语义调整为：逐服务导入 + 保存
        for si, (proj_key, proj_msg) in enumerate(rows["s4"]["service_project"].items(), 1):
            if proj_key not in SVC_META or not proj_msg.get("rows"):
                continue
            tab_name = SVC_META[proj_key][0]
            pfx = f"s5-{tab_name}"
            b.goto(f"{pfx}-打开业务订单列表", r["s5_order_self_route"])
            b.search(pfx)
            b.add(f"{pfx}-点击详情", action="row_button", value="详情")
            b.add(f"{pfx}-等待详情页", action="wait", value=2500)
            b.add(f"{pfx}-订单费用tab", action="click",
                  element={"strategy": "css", "value": "#tab-order_actual_cost"})
            b.add(f"{pfx}-等待tab", action="wait", value=1500)
            b.add(f"{pfx}-打开编辑费用下拉", action="click",
                  element={"strategy": "css", "value": "input[placeholder='编辑费用']"})
            b.add(f"{pfx}-选{tab_name}服务", action="popper_pick", value=tab_name)
            b.add(f"{pfx}-等待费用区", action="wait", value=2000)
            b.add(f"{pfx}-导入{tab_name}费用", action="click_text_contains", value="导入")
            b.add(f"{pfx}-轮询确认导入", action="confirm_wait")
            b.add(f"{pfx}-校验导入行", action="evaluate", value=(
                "(()=>{const s=document.querySelector(\"div[rowid='to_customer']\");"
                "const n=s?s.querySelectorAll('table.el-table__body tbody tr').length:0;"
                "return n>0?('ok:rows='+n):'no-rows'})()"),
                  assertions=[{"type": "json_path_contains", "path": "$.result", "expected": "ok:rows"}])
            b.add(f"{pfx}-dump两侧行数", action="evaluate", value=(
                "(()=>{const secs=[...document.querySelectorAll("
                "\"div[rowid='to_customer'],div[rowid='to_supplier']\")];"
                "return JSON.stringify(secs.map(s=>({rid:s.getAttribute('rowid'),"
                "rows:s.querySelectorAll('table.el-table__body tbody tr').length,"
                "inps:(s.querySelector('table.el-table__body tbody tr')||{querySelectorAll:()=>[]})"
                ".querySelectorAll('td input').length})))})()"))
            # 导入行缺业务费用必填列（应用子策略/补贴及补贴类别——s4 自营费用无这些字段，
            # run#579 实证保存被"必填项未填"拦截）。列位（xpath 1 基）：策略=td[3] 补贴=td[10]
            s5_rows = next(iter(rows["s5"]["service_projects"]["booking_space"].values()), [])
            s5_rows = s5_rows if isinstance(s5_rows, list) else []
            policy_v = str((s5_rows[0] or {}).get("put_policy_sub") or "易航道单主体")
            subsidy_v = str((s5_rows[0] or {}).get("put_subsidy_category") or "不参与补贴")
            n_imp = len(proj_msg.get("rows", []))
            S5_CELL = {
                "put": "//div[@rowid='to_customer']//table[contains(@class,'el-table__body')]"
                       "/tbody/tr[{ri}]/td[{td}]//input[@class='el-input__inner']",
                "pay": "//div[@rowid='to_supplier']//table[contains(@class,'el-table__body')]"
                       "/tbody/tr[{ri}]/td[{td}]//input[@class='el-input__inner']",
            }
            # 只补填应收侧：应付侧"应用子策略/补贴及补贴类别"为纯展示列
            # （disabled+readonly，run#589 dump 实证），其余列由导入带入
            for ri in range(1, n_imp + 1):
                b.add(f"{pfx}r{ri}-put策略", action="pick",
                      element={"strategy": "xpath",
                               "value": S5_CELL["put"].format(ri=ri, td=3)},
                      value=policy_v)
                b.add(f"{pfx}r{ri}-put补贴", action="pick",
                      element={"strategy": "xpath",
                               "value": S5_CELL["put"].format(ri=ri, td=10)},
                      value=subsidy_v)
                # 应付侧唯一缺失必填：费用主体（td7，可编辑；选项来自 run#596 dump，
                # 取与应用子策略匹配的主体）
                b.add(f"{pfx}r{ri}-pay费用主体", action="pick",
                      element={"strategy": "xpath",
                               "value": S5_CELL["pay"].format(ri=ri, td=7)},
                      value="青岛易航道物流科技有限公司")
            b.add(f"{pfx}-dumpPut补填后", action="evaluate", value=(
                "(()=>{const secs=[...document.querySelectorAll("
                "\"div[rowid='to_customer'],div[rowid='to_supplier']\")];"
                "return JSON.stringify(secs.map(s=>({rid:s.getAttribute('rowid'),"
                "rows:s.querySelectorAll('table.el-table__body tbody tr').length,"
                "inps:(s.querySelector('table.el-table__body tbody tr')||{querySelectorAll:()=>[]})"
                ".querySelectorAll('td input').length})))})()"))
            b.add(f"{pfx}-dump两侧行结构", action="evaluate", value=(
                "(async()=>{const out={};"
                "for(const rid of ['to_customer','to_supplier']){"
                "const sec=document.querySelector(\"div[rowid='\"+rid+\"']\");"
                "if(!sec){out[rid]='no-sec';continue;}"
                "const tbls=[...sec.querySelectorAll('table.el-table__body')];"
                "const tr=tbls.map(t=>t.querySelector('tbody tr'))"
                ".find(x=>x&&x.querySelectorAll('input').length>3);"
                "if(!tr){out[rid]='no-row';continue;}"
                "const cells=[...tr.querySelectorAll('td')].map((td,i)=>({c:i,"
                "n:td.querySelectorAll('input').length,"
                "dis:td.querySelector('input')?td.querySelector('input').disabled:null,"
                "v:td.querySelector('input')?(td.querySelector('input').value||'').slice(0,6):''}));"
                "out[rid]={cells:cells.filter(x=>x.n>0)}}"
                "const inp=[...document.querySelectorAll("
                "\"div[rowid='to_supplier'] table.el-table__body tbody tr td:nth-child(7) input\")]"
                ".filter(x=>!x.disabled);"
                "let opts=[];"
                "if(inp.length){inp[0].scrollIntoView({block:'center'});inp[0].click();"
                "await new Promise(r=>setTimeout(r,900));"
                "opts=[...document.querySelectorAll('li.el-select-dropdown__item')]"
                ".filter(x=>x.offsetParent).map(x=>x.textContent.trim()).slice(0,12);"
                "document.body.click();}"
                "out['主体下拉']=opts;return JSON.stringify(out)})()"))
            b.add(f"{pfx}-保存并确认", action="save", value="保存成功", timeout_ms=15000)

    # ================= 阶段6：生成子订单 =================
    b.goto("s6-打开业务订单列表", r["s6_business_order_route"])
    b.search("s6")
    b.add("s6-点击详情(行内)", action="row_button", value="详情")
    b.add("s6-等待详情页", action="wait", value=2500)
    # 生成子订单入口在页面底部（span 形态），先滚动到底再点
    b.add("s6-滚动到底", action="scroll_bottom")
    b.add("s6-点击生成子订单", action="click_text", value="生成子订单")
    b.add("s6-轮询确认生成", action="confirm_wait")
    b.add("s6-校验生成成功", action="toast_watch", value="生成子订单成功", timeout_ms=15000)


def main():
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    rows = load_excel_rows()

    # 合并数据行：阶段前缀 + 共享键
    merged: dict = {}
    for prefix, data in rows.items():
        for k, v in data.items():
            if k in ("relied_entrusted_order_data", "relied_business_order_data",
                     "relied_order_self_edit_data", "relied_order_self_fee_add_data",
                     "relied_real_fee_add_data", "relied_generate_order_sub_data"):
                continue  # 依赖链由 DAG 取代
            if k in SHARED_KEYS:
                continue
            merged[f"{prefix}_{k}"] = v
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    merged["bl_no"] = f"uitestBlNo{ts}"
    merged["customer_order_sn"] = f"uitestCustomerOrderSn{ts}"
    merged["customer_id"] = rows["s1"]["customer_id"]
    # 嵌套结构（service_project(s)）原样保留为 object 值（不上数据集行，节点参数已展开）

    # 元素库索引
    elem_ids = {f"{e.page_scope}.{e.element_key}": e.id
                for e in db.query(models.UiElement).filter(models.UiElement.project_id == PROJECT_ID).all()}

    b = NodeBuilder(elem_ids, merged)
    build_nodes(b, rows)
    edges = [{"id": f"e{i}", "source": b.nodes[i]["id"], "target": b.nodes[i + 1]["id"]}
             for i in range(len(b.nodes) - 1)]

    # 幂等重建：先解绑 dataset 引用（FK RESTRICT），再删旧同名用例与数据集
    for old in db.query(models.TestCase).filter(models.TestCase.name == CASE_NAME).all():
        old.dataset_id = None
        db.flush()
        for ds in db.query(models.DataSet).filter(models.DataSet.case_id == old.id).all():
            db.query(models.DataSetRow).filter(models.DataSetRow.dataset_id == ds.id).delete()
            db.delete(ds)
        db.delete(old)
    db.commit()

    case = models.TestCase(project_id=PROJECT_ID, name=CASE_NAME,
                           description="映射自 autotest-playwright flow_generate_order_sub（after_fee_add/with_all_project）："
                                       "委托下单→业务下单→自营编辑→自营费用→业务费用→生成子订单 全链 6 阶段",
                           dag_config={"nodes": b.nodes, "edges": edges})
    db.add(case)
    db.commit()
    for spec in b.specs:
        db.add(models.CaseNodeConfig(case_id=case.id, node_id=spec["node_id"], api_id=None,
                                     step_type="ui", ui_params=spec["ui_params"],
                                     assertions=spec["assertions"]))
    # 数据集（列从 merged 推导，嵌套 dict 值转 JSON 字符串）
    columns, row_data = [], {}
    for k, v in merged.items():
        if isinstance(v, dict):
            row_data[k] = json.dumps(v, ensure_ascii=False)
            columns.append({"key": k, "type": "object"})
        elif isinstance(v, list):
            row_data[k] = json.dumps(v, ensure_ascii=False)
            columns.append({"key": k, "type": "array"})
        else:
            row_data[k] = "" if v is None else str(v)
            columns.append({"key": k, "type": "string"})
    ds = models.DataSet(project_id=PROJECT_ID, case_id=case.id, name="with_all_project（全链合并）",
                        description="6 个阶段 Excel 单数据集按键前缀合并；bl_no/customer_id 全链共享",
                        columns=columns, node_configs=[])
    db.add(ds)
    db.commit()
    db.add(models.DataSetRow(dataset_id=ds.id, row_index=1, data=row_data))
    case.dataset_id = ds.id
    db.commit()

    print(f"用例已创建: id={case.id} name={CASE_NAME}")
    print(f"  节点数: {len(b.nodes)}  数据集: id={ds.id} 列数={len(columns)}")
    print(f"  bl_no: {merged['bl_no']}  customer: {merged['customer_id']}")
    stage_counts = {}
    for n in b.nodes:
        label = n["data"]["label"]
        m = re.match(r"(s\d)", label)
        stage_counts[m.group(1) if m else "?"] = stage_counts.get(m.group(1) if m else "?", 0) + 1
    print(f"  各阶段节点: {stage_counts}")
    db.close()


if __name__ == "__main__":
    main()
