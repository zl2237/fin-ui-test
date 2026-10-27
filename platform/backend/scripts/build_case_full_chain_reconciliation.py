# -*- coding: utf-8 -*-
"""构建用例：委托订单全链路·到对账（283 全链 + 费用锁定/订单锁定/应收对账批次）。

来源与流程（对齐 scripts/build_case_generate_order_sub.py 的幂等重建模式）：
    1. 整图克隆用例「委托订单全链路（272产单→费用→推送→审批→通知单→编辑自营）」
       （节点展示层 dag_config + 节点配置 CaseNodeConfig，元素引用 id 原样保留）；
    2. 在尾节点 m76_n4 后追加新阶段节点（映射 autotest-playwright 对应页面对象）：
         费用锁定 real_amount_lock_submit  → 审批（approval_center）
         订单锁定 real_amount_submit      → 审批（approval_center）
         应收对账批次 receive_reconciliation_batch
    3. 数据集：克隆源用例全部数据行，每行追加对账所需键
       （main_name / put_settle_object_id / reconciliation_batch_route）。

新增节点复用的既有平台机制（均已在 283 上验证）：
    - post_extract 别名：节点内 `$.steps[n].value` 把 ${bl_no} 复注册进本节点命名空间，
      供 SQL 提取用 {{节点.bl_no}} 命名空间精确引用（m81_n1/m81_n5 同款）；
    - custom 11/12/13：pick_audit_radios / switch_login / search_approval；
    - 审批编号 SQL 提取：sys_audit 按 audit_type + audit_status=1(审批中) 取最新
      （类型码经业务库实证：费用锁定=actualCostFeeLockApplication，
        订单锁定=actualCostLockApplication）；
    - search 动作 field 参数（筛选区检索）/ element 参数（固定检索框）；
    - evaluate 内 ${变量} 先解析（批次简称核对、用户名读取）。

对账批次列表页的两处特例（2026-10-26 业务页实证，探针+业务库双重核实）：
    - 该页筛选区是「展开/收起 + search flex-middle/select-title」结构，无「更多筛选」，
      search(field=) 分支不可用：创建人为 el-select 多选 → 专建 creator_select_input
      元素走 pick；展开/收起态自适应(收起=有残留筛选先重置)由 JS_RECON_EXPAND 处理；
    - 批次创建人是审批链 switch_login 之后的账号（陆旭阳）而非初始登录账号，
      故 rc_n5 从导航栏读 create_by；列表按批次号升序服务端分页，同账号历史批次
      多页并存，按唯一简称翻页查找目标行（JS_RECON_FIND_AND_DETAIL）。

用法（platform/backend 目录下）：
    python scripts/build_case_full_chain_reconciliation.py
"""
import copy
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")
os.environ.setdefault("JWT_SECRET_KEY", "build-script")
os.environ.setdefault("DB_PASSWORD", "build-script")
sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402

PROJECT_ID = 1
ENV_ID = 1
SOURCE_CASE_NAME = "委托订单全链路（272产单→费用→推送→审批→通知单→编辑自营）"
CASE_NAME = "委托订单全链路·到对账（产单→费用→推送→审批→通知单→编辑自营→费用锁定→订单锁定→应收对账）"
BUSINESS_ORDER_URL = "#/development/orderManage/businessOrder"
RECON_ROUTE_KEY = "reconciliation_batch_route"
RECON_ROUTE = "#/development/financialManage/receivable/reconciliationBatch"
MAIN_NAME = "青岛易航道物流科技有限公司"

# ---- 元素库（现命名作用域；元素由 scripts/migrate_locator_to_elements.py 同步） ----
BD = "ordermanage/businessorderdetails"
RC = "financemanage/receivable/reconciliationbatch"
# approval 中心沿用 283 已引用的旧命名作用域元素（audit_confirm/audit_sure）
EL_APPROVE_CONFIRM = 278
EL_APPROVE_SURE = 279


def el(scope: str, key: str, ids: dict) -> dict:
    eid = ids.get(f"{scope}.{key}")
    if eid is None:
        raise SystemExit(f"元素库缺少 {scope}.{key}（先跑 migrate_locator_to_elements.py）")
    return {"element_id": eid}


# 283 m76_n1 同款：清残留遮罩（v-modal），返回是否有残留弹层
# （纯箭头函数表达式，不带 IIFE 尾部调用——`() => {...})()` 缺起始括号会 SyntaxError，run#876 实证）
JS_CLEAR_MODAL = (
    "() => { const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);"
    " const hasDialog = [...document.querySelectorAll('.el-dialog__wrapper,.el-message-box__wrapper,.el-drawer')].some(vis);"
    " if (!hasDialog) document.querySelectorAll('.v-modal').forEach(e => e.remove());"
    " return hasDialog ? 'dialog-open' : 'cleaned'; }"
)

# 283 m81_n4 同款：可见弹层里点 确认/确定
JS_DIALOG_CONFIRM = (
    "() => {const vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);"
    "const dlg=[...document.querySelectorAll('.el-dialog__wrapper')].find(d=>vis(d));"
    "if(!dlg)return 'no-dialog';"
    "let btn=[...dlg.querySelectorAll('button')].find(b=>(b.textContent||'').replace(/\\s+/g,'')==='确认');"
    "if(!btn)btn=[...dlg.querySelectorAll('button')].find(b=>(b.textContent||'').replace(/\\s+/g,'')==='确定');"
    "if(!btn)return 'no-btn';btn.click();return 'confirmed'}"
)

# 费用锁定·勾选费用行（移植 business_order_details.real_amount_lock_submit：
# inner[1]=应收全选；inner[2]=应付跳过 服务项目=订舱 与 is--disabled 行；
# 表头按 col--checkbox / 文本=服务项目 动态定位列，表头顺序调整不破）
JS_LOCK_CHECKBOXES = """async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const pane = document.querySelector("div[id='pane-order_actual_cost']");
    if (!pane) return 'no-fee-pane';
    const pick = (innerIdx, skipBooking) => {
        const inner = pane.querySelectorAll("div.inner")[innerIdx];
        if (!inner) return 'no-inner' + innerIdx;
        const header = inner.querySelector("div.vxe-table--header-wrapper.body--wrapper");
        if (!header) return 'no-header' + innerIdx;
        const ths = [...header.querySelectorAll("thead tr th")]
            .filter(th => !(th.getAttribute('class') || '').includes('vxe-header--gutter'));
        let cbIdx = -1, spIdx = -1;
        ths.forEach((th, i) => {
            const cls = th.getAttribute('class') || '';
            const span = th.querySelector('div span');
            const txt = span ? span.textContent.trim() : '';
            if (cls.includes('col--checkbox')) cbIdx = i;
            else if (txt === '服务项目') spIdx = i;
        });
        if (cbIdx < 0) return 'no-checkbox-col' + innerIdx;
        const wrapper = inner.querySelector("div.vxe-table--body-wrapper.fixed-left--wrapper");
        if (!wrapper) return 'no-body' + innerIdx;
        const rows = [...wrapper.querySelectorAll("table.vxe-table--body tbody tr")];
        let clicked = 0, skipped = 0;
        for (const tr of rows) {
            const tds = tr.querySelectorAll("td");
            const cell = tds[cbIdx];
            if (!cell) continue;
            const box = cell.querySelector('div span') || cell;
            if (skipBooking) {
                const cls = (box.getAttribute('class') || '');
                if (cls.includes('is--disabled')) { skipped++; continue; }
                if (spIdx >= 0 && tds[spIdx]) {
                    const sp = tds[spIdx].querySelector('div span');
                    if (sp && sp.textContent.trim() === '订舱') { skipped++; continue; }
                }
            }
            box.click(); clicked++;
        }
        return 'clicked=' + clicked + ',skipped=' + skipped;
    };
    const put = pick(0, false);
    await sleep(300);
    const pay = pick(1, true);
    return 'put[' + put + '] pay[' + pay + ']';
}"""

# 对账批次·跨页全选费用（移植 receive_reconciliation_batch._select_first_to_n_checkboxes
# 的 n=全部 语义：虚拟滚动 vxe 按 rowid scrollToRow 滚入视野后真实点击，翻页续勾；
# 已选统计由 change 事件驱动，setCheckboxRow 不触发事件故必须真实点击）
JS_RECON_SELECT_ALL = """async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const xp = p => document.evaluate(p, document, null, 9, null).singleNodeValue;
    const findTable = () => xp("//div[@class='vxe-table--body-wrapper fixed-left--wrapper']//table[@class='vxe-table--body']");
    const getApi = () => {
        const t = findTable(); if (!t) return [null, 'no-table'];
        const root = t.closest('.vxe-table'); if (!root) return [null, 'no-root'];
        const vm = root.__vueParentComponent?.proxy || root.__vue__; if (!vm) return [null, 'no-vm'];
        let a = null;
        if (vm.$refs) for (const k of Object.keys(vm.$refs)) {
            const r = vm.$refs[k];
            if (r && typeof r.setCheckboxRow === 'function') { a = r; break; }
        }
        if (!a && typeof vm.setCheckboxRow === 'function') a = vm;
        return [a, a ? 'ok' : 'no-api'];
    };
    let total = 0, pages = 0;
    while (pages < 50) {
        pages++;
        const [api, msg] = getApi(); if (!api) return 'fail@p' + pages + ':' + msg;
        const data = api.getData() || [];
        if (!data.length) return 'empty@p' + pages;
        const rowid = r => typeof api.getRowid === 'function' ? api.getRowid(r) : r._XID;
        const tbl = findTable();
        for (let i = 0; i < data.length; i++) {
            await api.scrollToRow(data[i]); await sleep(50);
            const tr = tbl.querySelector(`tbody tr[data-rowid='${rowid(data[i])}']`);
            const cell = tr && tr.querySelector('td.col--checkbox');
            if (!cell) return 'no-cell@p' + pages + 'i' + i;
            (cell.querySelector('.vxe-cell--checkbox') || cell).click();
            total++;
        }
        await sleep(150);
        const next = xp("//div[contains(@class,'pagination-container')]//button[contains(@class,'btn-next')]");
        if (!next || next.disabled || next.getAttribute('disabled') !== null) break;
        next.click(); await sleep(1200);
    }
    await sleep(200);
    const [api2] = getApi();
    const sel = api2 ? (api2.getCheckboxRecords() || []).length : -1;
    return 'totalClicked=' + total + ',selected=' + sel + ',pages=' + pages;
}"""

# 对账批次·读分页总数（共 N 条）
JS_RECON_TOTAL = (
    "() => {const m=document.body.innerText.match(/共\\s*(\\d+)\\s*条/);"
    "return m?parseInt(m[1],10):-1}"
)

# 对账批次·读右上角当前登录用户名（移植 login.get_username 的 self_name_menu）
JS_GET_USERNAME = (
    "() => {const el=document.evaluate("
    "\"//div[contains(@class,'navbar')]//div[contains(@class,'right-menu-item')]//div//span\","
    " document, null, 9, null).singleNodeValue;"
    "if(!el)throw new Error('未找到右上角用户名');return el.textContent.trim()}"
)

# 对账批次详情·核对简称 + 读批次号（for_span 语义内嵌：label[for=X]→兄弟 butRight span；
# evaluate 的返回值进 facts.result，post_extract 用 $.steps[n].result.xxx 取字段）
JS_VERIFY_BATCH = (
    "() => {const xp=k=>document.evaluate("
    "\"//label[@for='\"+k+\"']/following-sibling::div/div[@class='butRight']/span\","
    " document, null, 9, null).singleNodeValue;"
    "const s=xp('account_simple_name');if(!s)throw new Error('未读到批次简称span');"
    "const actual=s.textContent.trim();const expected='${rc_n2.account_simple_name}';"
    "if(actual!==expected)throw new Error('批次简称不符: '+actual+' != '+expected);"
    "const no=xp('receive_account_no');"
    "return {verify:'ok', account_simple_name:actual,"
    " receive_account_no:no?no.textContent.trim():''}}"
)

# 对账批次列表筛选区：非「更多筛选」自定义区，search(field=) 分支不可用——
# 对齐 autotest SearchMixin 语义：收起态(筛选项有缓存)先点重置清空，否则点展开
JS_RECON_EXPAND = (
    "async () => {"
    "const vis=e=>!!(e.offsetParent);"
    "const labels=[...document.querySelectorAll('div.top label')].filter(vis);"
    "const fold=labels.find(e=>e.textContent.trim()==='收起');"
    "if(fold){const reset=[...document.querySelectorAll('button')].filter(vis)"
    ".find(b=>b.textContent.replace(/\\s+/g,'')==='重置');"
    "if(!reset)throw new Error('收起态未见重置按钮');reset.click();return 'reset'}"
    "const exp=labels.find(e=>e.textContent.trim()==='展开');"
    "if(!exp)throw new Error('未见展开按钮');exp.click();return 'expanded'}"
)

# 对账批次列表定位本批：服务端分页且默认按批次号升序，历史 UItest 批次多页并存，
# 按唯一批次简称翻页查找(btn-next，上限10页)；vxe 行三 wrapper 拷贝均含操作列
# 按钮，命中行内直接 JS 点详情（行含 data-rowid，进 facts 备查）
JS_RECON_FIND_AND_DETAIL = (
    "async () => {"
    "const kw='${rc_n2.account_simple_name}';"
    "const vis=e=>!!(e.offsetParent);"
    "const findRow=()=>[...document.querySelectorAll('tbody tr')]"
    ".filter(t=>vis(t)&&t.textContent.includes(kw))[0];"
    "let row=findRow();let pages=0;"
    "while(!row&&pages<10){"
    "const next=[...document.querySelectorAll('.el-pagination button.btn-next')]"
    ".filter(vis)[0];"
    "if(!next||next.disabled)break;"
    "next.click();pages++;"
    "await new Promise(r=>setTimeout(r,1500));"
    "row=findRow()}"
    "if(!row)throw new Error('翻页'+pages+'页后仍未找到简称 '+kw+' 的对账批次');"
    "const btn=[...row.querySelectorAll('button')]"
    ".find(b=>(b.textContent||'').replace(/\\s+/g,'')==='详情');"
    "if(!btn)throw new Error('目标批次行内未找到详情按钮');"
    "btn.click();"
    "return {rowid:row.getAttribute('data-rowid'),pages}}"
)


class Adder:
    """新节点装配器：steps + 展示层节点 + 线性边。"""

    def __init__(self, ids: dict, start_y: int):
        self.ids = ids
        self.y = start_y
        self.nodes = []
        self.specs = []
        self.prev = "m76_n4"  # 源用例尾节点

    def add(self, node_id: str, label: str, steps: list, post_extract=None):
        self.y += 170
        self.nodes.append({
            "id": node_id,
            "data": {"label": label, "step_type": "ui", "ui_action": "steps",
                     "ui_steps_len": len(steps)},
            "label": label,
            "position": {"x": 200, "y": self.y},
        })
        self.specs.append({"node_id": node_id, "ui_params": {"steps": steps},
                           "post_extract": post_extract or [],
                           "assertions": []})


def build(db) -> None:
    src = db.query(models.TestCase).filter(
        models.TestCase.project_id == PROJECT_ID,
        models.TestCase.name == SOURCE_CASE_NAME).first()
    if not src:
        raise SystemExit(f"源用例不存在: {SOURCE_CASE_NAME}")
    src_cfgs = db.query(models.CaseNodeConfig).filter(
        models.CaseNodeConfig.case_id == src.id).all()
    src_ds = db.get(models.DataSet, src.dataset_id)
    src_rows = db.query(models.DataSetRow).filter(
        models.DataSetRow.dataset_id == src_ds.id).order_by(
        models.DataSetRow.row_index).all()
    if not src_rows:
        raise SystemExit("源数据集无数据行")

    # 列表筛选区创建人下拉：autotest search_fixed_value_input='创建人' 的平台化等价
    # 元素（本页筛选区无「更多筛选」，search(field=) 分支定位不到；创建人为
    # el-select 多选，取块内 el-select__input 作 pick 触发器）。幂等 upsert。
    creator_el = db.query(models.UiElement).filter(
        models.UiElement.project_id == PROJECT_ID,
        models.UiElement.page_scope == RC,
        models.UiElement.element_key == "creator_select_input").first()
    creator_strategies = {
        "xpath": "//div[@class='search flex-middle']"
                 "[.//div[@class='select-title flex-middle'][normalize-space()='创建人']]"
                 "//input[contains(@class,'el-select__input')]"
    }
    if creator_el is None:
        creator_el = models.UiElement(
            project_id=PROJECT_ID, page_scope=RC, element_key="creator_select_input",
            strategies=creator_strategies,
            description="列表筛选区·创建人多选下拉检索输入框")
        db.add(creator_el)
        db.flush()
    else:
        creator_el.strategies = creator_strategies

    ids = {f"{e.page_scope}.{e.element_key}": e.id
           for e in db.query(models.UiElement).filter(
               models.UiElement.project_id == PROJECT_ID).all()}

    nodes = copy.deepcopy(src.dag_config["nodes"])
    edges = copy.deepcopy(src.dag_config["edges"])
    max_y = max(n["position"]["y"] for n in nodes)
    b = Adder(ids, max_y)

    # ===== 阶段7 费用锁定（real_amount_lock_submit）=====
    b.add("lk1_n1", "费用锁定-检索订单", [
        {"action": "goto", "url": BUSINESS_ORDER_URL},
        {"action": "evaluate", "value": JS_CLEAR_MODAL},
        {"action": "search", "value": "${bl_no}"},
    ], post_extract=[{"name": "bl_no", "source": "response", "json_path": "$.steps[2].value"}])
    b.add("lk1_n2", "费用锁定-进详情实际费用tab", [
        {"action": "row_button", "row": "${bl_no}", "value": "详情"},
        {"action": "click", "element": el(BD, "order_real_fee_tab", ids)},
        {"action": "wait", "value": 1500},
    ])
    b.add("lk1_n3", "费用锁定-打开锁定视图", [
        {"action": "click", "element": el(BD, "real_amount_lock_button", ids)},
        {"action": "wait", "value": 3000},
    ])
    b.add("lk1_n4", "费用锁定-勾选费用行", [
        {"action": "evaluate", "value": JS_LOCK_CHECKBOXES},
        {"action": "wait", "value": 300},
    ])
    b.add("lk1_n5", "费用锁定-提交并取审批号", [
        {"action": "click", "element": el(BD, "real_amount_lock_submit_button", ids)},
        {"action": "wait", "value": 1200},
        {"action": "custom", "custom_id": 11, "value": "${audit_nodes_json}"},
        {"action": "evaluate", "value": JS_DIALOG_CONFIRM},
        {"action": "wait", "value": 1000},
        {"action": "toast_watch", "value": "提交费用锁定审批流成功", "timeout_ms": 15000},
        {"action": "wait", "value": 500},
    ], post_extract=[{
        "name": "audit_no", "source": "db", "field": "audit_no",
        "sql": "SELECT audit_no FROM sys_audit WHERE relation_id=(SELECT order_id FROM sys_order"
               " WHERE bl_no={{lk1_n1.bl_no}} ORDER BY order_id DESC LIMIT 1)"
               " AND audit_type='actualCostFeeLockApplication' AND audit_status=1"
               " ORDER BY audit_id DESC LIMIT 1"}])

    # ===== 阶段8 费用锁定审批（approval_center·克隆 m79 模式）=====
    b.add("ap1_n1", "锁定审批-切换登录人", [
        {"action": "goto", "url": "/"},
        {"action": "custom", "custom_id": 12, "value": "${audit_user1}"},
        {"action": "wait", "value": 4000},
    ])
    b.add("ap1_n2", "锁定审批-检索审批单", [
        {"action": "goto", "url": "${approval_route}"},
        {"action": "custom", "custom_id": 13, "value": "${lk1_n5.audit_no}"},
    ])
    b.add("ap1_n3", "锁定审批-审核通过", [
        {"action": "click_text", "value": "审核"},
        {"action": "custom", "custom_id": 11, "value": "${audit_result_json}"},
        {"action": "click", "element": {"element_id": EL_APPROVE_CONFIRM}},
        {"action": "click", "element": {"element_id": EL_APPROVE_SURE}},
        {"action": "toast_watch", "value": "审批成功"},
    ])

    # ===== 阶段9 订单锁定（real_amount_submit）=====
    b.add("lk2_n1", "订单锁定-检索订单", [
        {"action": "goto", "url": BUSINESS_ORDER_URL},
        {"action": "evaluate", "value": JS_CLEAR_MODAL},
        {"action": "search", "value": "${bl_no}"},
    ], post_extract=[{"name": "bl_no", "source": "response", "json_path": "$.steps[2].value"}])
    b.add("lk2_n2", "订单锁定-进详情实际费用tab", [
        {"action": "row_button", "row": "${bl_no}", "value": "详情"},
        {"action": "click", "element": el(BD, "order_real_fee_tab", ids)},
        {"action": "wait", "value": 1500},
    ])
    b.add("lk2_n3", "订单锁定-提交并取审批号", [
        {"action": "click", "element": el(BD, "real_amount_submit_button", ids)},
        {"action": "wait", "value": 800},
        {"action": "click", "element": el(BD, "confirm_button", ids)},
        {"action": "wait", "value": 1200},
        {"action": "custom", "custom_id": 11, "value": "${audit_nodes_json}"},
        {"action": "evaluate", "value": JS_DIALOG_CONFIRM},
        {"action": "wait", "value": 1000},
        {"action": "toast_watch", "value": "提交订单锁定申请成功！", "timeout_ms": 15000},
        {"action": "wait", "value": 500},
    ], post_extract=[{
        "name": "audit_no", "source": "db", "field": "audit_no",
        "sql": "SELECT audit_no FROM sys_audit WHERE relation_id=(SELECT order_id FROM sys_order"
               " WHERE bl_no={{lk2_n1.bl_no}} ORDER BY order_id DESC LIMIT 1)"
               " AND audit_type='actualCostLockApplication' AND audit_status=1"
               " ORDER BY audit_id DESC LIMIT 1"}])

    # ===== 阶段10 订单锁定审批 =====
    b.add("ap2_n1", "订单审批-切换登录人", [
        {"action": "goto", "url": "/"},
        {"action": "custom", "custom_id": 12, "value": "${audit_user1}"},
        {"action": "wait", "value": 4000},
    ])
    b.add("ap2_n2", "订单审批-检索审批单", [
        {"action": "goto", "url": "${approval_route}"},
        {"action": "custom", "custom_id": 13, "value": "${lk2_n3.audit_no}"},
    ])
    b.add("ap2_n3", "订单审批-审核通过", [
        {"action": "click_text", "value": "审核"},
        {"action": "custom", "custom_id": 11, "value": "${audit_result_json}"},
        {"action": "click", "element": {"element_id": EL_APPROVE_CONFIRM}},
        {"action": "click", "element": {"element_id": EL_APPROVE_SURE}},
        {"action": "toast_watch", "value": "审批成功"},
    ])

    # ===== 阶段11 应收对账批次（receive_reconciliation_batch）=====
    b.add("rc_n1", "对账-打开批次页", [
        {"action": "goto", "url": "${" + RECON_ROUTE_KEY + "}"},
        {"action": "wait", "value": 2000},
        {"action": "evaluate", "value": JS_CLEAR_MODAL},
    ])
    b.add("rc_n2", "对账-发起批次表单", [
        {"action": "click", "element": el(RC, "add_by_cost_button", ids)},
        {"action": "wait", "value": 1200},
        {"action": "fill", "element": el(RC, "account_simple_name_input", ids),
         "value": "${generate_bl_no(prefix='UItest对账批次')}"},
        {"action": "click", "element": el(RC, "cross_customer_radio", ids)},
        {"action": "wait", "value": 400},
        {"action": "pick", "element": el(RC, "customer_id_selector", ids), "value": "${customer_id}"},
        {"action": "pick", "element": el(RC, "put_settle_object_id_selector", ids),
         "value": "${put_settle_object_id}"},
        {"action": "pick", "element": el(RC, "main_id_selector", ids), "value": "${main_name}"},
    ], post_extract=[{"name": "account_simple_name", "source": "response",
                      "json_path": "$.steps[2].value"}])
    b.add("rc_n3", "对账-检索费用", [
        {"action": "search", "element": el(RC, "bl_no_search_input", ids), "value": "${bl_no}"},
        {"action": "wait", "value": 800},
        {"action": "click", "element": el(RC, "query_button", ids)},
        {"action": "wait", "value": 1500},
        {"action": "evaluate", "value": JS_RECON_TOTAL},
    ], post_extract=[{"name": "fee_total", "source": "response", "json_path": "$.steps[4].result"}])
    b.add("rc_n4", "对账-全选并提交", [
        {"action": "evaluate", "value": JS_RECON_SELECT_ALL},
        {"action": "wait", "value": 500},
        {"action": "click", "element": el(RC, "submit_button", ids)},
        {"action": "wait", "value": 800},
        {"action": "click", "element": el(RC, "confirm_button", ids)},
        {"action": "wait", "value": 1500},
    ])
    b.add("rc_n5", "对账-回列表取创建人", [
        {"action": "goto", "url": "${" + RECON_ROUTE_KEY + "}"},
        {"action": "wait", "value": 2000},
        {"action": "evaluate", "value": JS_CLEAR_MODAL},
        {"action": "evaluate", "value": JS_GET_USERNAME},
    ], post_extract=[{"name": "create_by", "source": "response", "json_path": "$.steps[3].result"}])
    b.add("rc_n6", "对账-按创建人检索本批并进详情", [
        {"action": "evaluate", "value": JS_RECON_EXPAND},
        {"action": "wait", "value": 800},
        {"action": "pick", "element": el(RC, "creator_select_input", ids),
         "value": "${rc_n5.create_by}"},
        {"action": "click", "element": el(RC, "query_button", ids)},
        {"action": "wait", "value": 1200},
        {"action": "evaluate", "value": JS_RECON_FIND_AND_DETAIL},
        {"action": "wait", "value": 1500},
    ])
    b.add("rc_n7", "对账-核对并完成", [
        {"action": "evaluate", "value": JS_VERIFY_BATCH},
        {"action": "click", "element": el(RC, "reconciliation_finish_button", ids)},
        {"action": "wait", "value": 800},
        {"action": "click", "element": el(RC, "sure_button", ids)},
        {"action": "toast_watch", "value": "确认成功", "timeout_ms": 15000},
    ], post_extract=[{"name": "receive_account_no", "source": "response",
                      "json_path": "$.steps[0].result.receive_account_no"}])

    nodes += b.nodes
    chain = ["m76_n4"] + [s["node_id"] for s in b.specs]
    edges += [{"id": f"nx_{chain[i]}_{chain[i + 1]}",
               "source": chain[i], "target": chain[i + 1]}
              for i in range(len(chain) - 1)]

    # ===== 数据集：克隆源行 + 追加对账键（put_settle_object 随行内 customer_id）=====
    new_rows = []
    for r in src_rows:
        data = dict(r.data or {})
        data["main_name"] = MAIN_NAME
        data["put_settle_object_id"] = data.get("customer_id") or ""
        data[RECON_ROUTE_KEY] = RECON_ROUTE
        new_rows.append(data)

    # ===== 幂等重建：先解绑 dataset 引用，再删旧同名用例与数据集 =====
    for old in db.query(models.TestCase).filter(
            models.TestCase.project_id == PROJECT_ID,
            models.TestCase.name == CASE_NAME).all():
        old.dataset_id = None
        db.flush()
        for ds in db.query(models.DataSet).filter(models.DataSet.case_id == old.id).all():
            db.query(models.DataSetRow).filter(
                models.DataSetRow.dataset_id == ds.id).delete()
            db.delete(ds)
        db.delete(old)
    db.commit()

    case = models.TestCase(
        project_id=PROJECT_ID, name=CASE_NAME, env_id=ENV_ID, group_id=src.group_id,
        description="克隆 283 全链并延长到应收对账：产单→费用→推送→审批→通知单→编辑自营"
                    "→费用锁定→审批→订单锁定→审批→应收对账批次（按费用对账/跨下单客户/全选提交/对账完成）。"
                    "映射自 autotest-playwright real_amount_lock_submit / real_amount_submit /"
                    " receive_reconciliation_batch。",
        dag_config={"nodes": nodes, "edges": edges})
    db.add(case)
    db.commit()
    for spec in b.specs:
        db.add(models.CaseNodeConfig(case_id=case.id, node_id=spec["node_id"], api_id=None,
                                     step_type="ui", ui_params=spec["ui_params"],
                                     post_extract=spec["post_extract"],
                                     assertions=spec["assertions"]))
    for cfg in src_cfgs:  # 克隆源节点配置（元素引用 id 原样）
        db.add(models.CaseNodeConfig(case_id=case.id, node_id=cfg.node_id, api_id=cfg.api_id,
                                     step_type=cfg.step_type, ui_params=cfg.ui_params,
                                     pre_process=cfg.pre_process,
                                     post_extract=cfg.post_extract,
                                     assertions=cfg.assertions,
                                     wait_after_ms=cfg.wait_after_ms))
    ds = models.DataSet(project_id=PROJECT_ID, case_id=case.id,
                        name="全链路到对账·合并变体",
                        description="克隆 283 数据集全部行，追加 main_name/put_settle_object_id/"
                                    "reconciliation_batch_route 对账键")
    db.add(ds)
    db.commit()
    for i, data in enumerate(new_rows, 1):
        db.add(models.DataSetRow(dataset_id=ds.id, row_index=i,
                                 data={k: (json.dumps(v, ensure_ascii=False)
                                           if isinstance(v, (dict, list)) else v)
                                       for k, v in data.items()}))
    case.dataset_id = ds.id
    db.commit()

    print(f"用例已创建: id={case.id} name={CASE_NAME}")
    print(f"  节点: 源克隆 {len(src_cfgs)} + 新增 {len(b.specs)} = {len(nodes)}；边 {len(edges)}")
    print(f"  数据集: id={ds.id} 行数={len(new_rows)} 列数={len(new_rows[0])}")
    print(f"  新增阶段节点: {[s['node_id'] for s in b.specs]}")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        build(db)
    finally:
        db.close()
