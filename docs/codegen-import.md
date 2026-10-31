# codegen 录制 → 平台用例导入工具链

> 沉淀自 2026-10-29 case 314（委托订单·分发链路）全链路自测；工作方式：**同一业务表单的
> 语义一次沉淀进规则库，之后该表单的复录一键导入**。新表单/新流程首次仍需人工（探针+自测）
> 转正，规则库随录制越多越厚。

## 组成

| 文件 | 职责 |
|---|---|
| `platform/backend/scripts/import_codegen.py` | 主导入器：AST 解析 → 表单识别 → 元素补齐 → 转换+增强 → 三栏清单 → `--apply` 落库 |
| `platform/backend/scripts/form_probe.py` | 表单指纹探针（非破坏性）：枚举表单项+下拉真实选项；陌生表单生成草稿规则 |
| `platform/backend/scripts/codegen_rules/<form>.json` | 规则库：一个业务表单一份（detect 识别 / 元素 strategies 自包含 / nth·css·字面值映射 / 按钮行为 / 探针配置） |

## 日常流程（已知表单复录）

```bash
cd platform/backend
python scripts/import_codegen.py ../../record.py           # dry-run：看三栏清单 + 预览 case JSON
python scripts/import_codegen.py ../../record.py --apply   # 落库：补缺失元素 → 建用例+数据集+绑定
```

随后自测：`POST /api/testcases/{id}/execute`（登录 admin/admin123 拿 token），失败看
`GET /api/reports/executions/{id}` 的 `response_body.error` 与逐步 facts。

## 新表单首次接入

1. `python scripts/form_probe.py --env 1 --route '#/xxx/yyy' --add-button 新建X --draft my_form`
   → 生成 `codegen_rules/my_form.json` 草稿 + `my_form.fingerprint.json` 指纹（nth→label/options）
2. 按草稿内 `_todo` 清单转正：字段名语义化（对照指纹 options「选项反查」）、`detect.nav_link_texts`
   补菜单链接名、`group_id`/`node_labels`、`text_input_rules`（字面值→数据集字段，生成规则写单元格）、
   `button_behaviors` 补看门狗关键词（保存/分发/提交/生效…以业务实际 toast 文案为准）
3. `import_codegen.py` dry-run 复核 → `--apply` → 平台执行自测 → 通过后把 `proven` 更新为实证记录、删 `_todo`

## 规则文件关键字段

- `detect`：录制识别依据（菜单链接名 / goto 路由子串）；多规则命中冲突会报错列出
- `elements`：本流程引用元素的 strategies 快照（自包含）——库里缺谁导入时自动建谁（`POST /ui-elements`），
  **换环境（本地↔线上）导入不依赖元素 id**
- `nth_select_guesses`：录制 `请选择.nth(i)` → [字段名, 元素key, 置信度说明]；`css_picks` 同理按 css 选择器
- `button_behaviors`：`node_split`（开新节点，长链路）/ `confirm_watchdog`（wait+confirm+成功看门狗，
  关键词即数据）/ `absorb`（confirm 已接管）/ `row_button`（行内按钮）
- `probe`：探针配置（进表单按钮、预填级联字段）；`field_suggestions`：录制「点首项」时的建议值

## 纪律（实测教训，勿违反）

1. **evaluate 模板只按关键词拼装，永不重构**：本地 `page.evaluate` 对含中文 JS 的验证跨进程非确定性
   翻转（同一字节串此进程 SyntaxError 彼进程正常），唯一可信判据是平台自身执行；模板串改用
   f-string 曾两次引入多余 `}`（f-string 续行是普通字符串，`}}` 不转义）——一律 `%s` 拼装。
2. **单会话互踢**：探针/执行共用业务系统账号，探针后 ≥90s 再执行，否则 goto 即挂（被踢回登录页）。
3. **探针非破坏性**：只开下拉读选项+Esc；预填仅选值绝不点保存；对业务系统行为有疑问先问不要猜。
4. **「看似可选」字段可能是后续动作必填**：保存成功 ≠ 分发能过（314 教训：服务项目-供应商/业务员
   保存不校验、分发必填）——新流程必须自测到链路终点才算转正。
5. SQLAlchemy 直接改用例 JSON 列（`ui_params`/`data_set_rows.data`）必须 `flag_modified`，否则
   unit-of-work 按 `==` 判无变更**静默不发 UPDATE**。
6. 本机 Windows：含中文脚本一律文件落盘 UTF-8 跑 + `PYTHONIOENCODING=utf-8`，不走管道。
7. **节点尾 URL 断言防 SPA 跳转竞态**（288 run898 教训）：节点末步若是「点开新建/编辑」等触发路由
   跳转的点击，节点终态 URL 在「跳转前/后」两态间竞态（本地绿线上红即是此因）。断言取两态路由的
   公共子串（如 `entrustedOrder` 同时匹配列表 `orderManage/entrustedOrder` 与建单 `entrustedOrderAdd`），
   不要断言点击前页面的完整路由。
8. **线上→本地整库覆盖的导入方法**：`gunzip -c x.sql.gz > x.sql` 后
   `mysql --default-character-set=utf8mb4 --binary-mode=1 ... < x.sql`——纯管道导入会在含 `\"` 的
   大 INSERT（case_node_configs 等 JSON 列）上报 `Unknown command '\"'`，加 --binary-mode 的管道
   也不行，必须文件重定向。线上库为唯一源，规则文件用 group_name/env.base_url_contains 按名解析
   跨库 id（自增 id 两库不一致）。
9. **链式规则（--chain）**：`stages[]` 按序消费起点标记（nav_link/goto_contains/button/text/
   text_startswith）；**标记语句本身开启新阶段切片**（首标记之前=登录段整段剔除）；`skip: true`
   的阶段=截断丢弃（P1 先导入前段、后续阶段逐步扩）；每阶段独立 scope，元素跨域绑定平台报 400。
10. **behaviors 键要对齐 crossref 实际命中的库内 ekey**：crossref 按元素库 element_key 字母序
   取第一个 text/button/toast 匹配，规则里自命名的元素键未必是执行时命中的那个——同一按钮的
   多个候选库键（confirm_button/dialog_sure_button/submit_sure_button…）都要登记行为。
11. **css 定位语句逐条处理，不整段吞并**：fill 头查 css_fills（键 `css@nth`，el-table_N/column_N
   归一匹配复录）；click 头查 css_picks 并配对紧随选项点击（可隔 press/下拉检索框 fill 噪声）；
   尾随 fill 的聚焦点击并入 fill。整段吞并会把同一表格行里后续 fill 全吃掉（289 教训）。
12. **nth 键取可访问名**：role 定位器的 nth_key 用 name（如「请输入关键词@0」）不是 value
   （「textbox@0」）；查询框分支要求 exact=True 以免把表单里的请输入 fill 误当列表检索词。
13. **表格行内元素禁用 `el-table_N_column_M` 链**：N 是页面 el-table 实例序号、跨渲染漂移
   （同一页面实测 el-table_1↔el-table_3），且列数随表单状态扩张（录制时 20+ 列、复跑时 7 列）。
   录制里的 column_18/20 链在复跑渲染下要么命中他处 riseTitleSt 输入（必填列漏填→「检测到
   未填写必填项」）、要么超时。行内单元格一律改为**td 锚定**（`.el-table__row td:nth-child(K) input`，
   K 按列头序），元素库里同名旧策略需删除重建（ensure_elements 只建不更，291 实证）。
14. **编辑入口区分两条路由**：业务订单列表「编辑」→ `#/businessOrderAdd/{id}`（简表单，箱表 7 列），
   委托订单列表「编辑」→ `#/entrustedOrderAdd/{id}`（59 项大表单）——同一单 id 两个表单，
   探针/规则必须与录制走同一入口（录制 L49 的链接文本决定），否则枚举到错误的表单结构。

## 纪律 15：录制 nth 下标不可复用 —— get_by_role 只数「可见且无值」的下拉
录制器的 `get_by_role("textbox", name="请选择").nth(N)` 按可访问名匹配：已填值的下拉可访问名=值（不算），
隐藏容器内的不算，复跑时行的预填状态与录制时不同 → nth 漂移不可复原（#291 n3 实证：录制的 nth(3/4/5)
在复跑页分别落在 结算对象/币制/单位，而录制意图是 币制/费用名称/单位）。必须语义重绑：
探针枚举「录制视角」(get_by_role) 与「DOM 视角」(placeholder xpath) 两套索引+列头，按列名绑定。

## 纪律 16：费用表 = 22 列可编辑 el-table，列锚定 css 命中所有镜像
列头：序号/应用子策略/策略标识/费用种类/服务项目/费用名称/补贴及补贴类别/补贴版本-补贴名称/费用主体/
结算对象/币制/含税单价/单位/规格/数量/含税折前金额/折扣/含税折后金额/备注/费用状态/操作。
费用名称=td7、币制=td12、含税单价=td13、单位=td14、规格=td15（td.textContent 读不到 input 值，
pick 的双向校验才是权威）。`.el-table__row td:nth-child(K) input` 在该页全部命中费用表（实证 count=6 全对）。

## 纪律 17：规格列 disabled 联动 —— 单位=箱型 才启用
规格(箱型)下拉在 单位≠箱型 时 disabled（点击 30s 超时/选项点选无效）。录制的 hover 首项点击
实为重选「高亮项=已选值」，录制时单位默认箱型 → 重选箱型后规格才可选 20GP。
联动依赖列先选启用条件列再选受控列。

## 纪律 18：列表段必带查询前置（pre_query）
row_button 的 vxe 兜底只认首行（run#690 实证：操作列 div 渲染不在 tr 内）。录制时目标单恰在首行，
复跑时被历史单挤走 → 规则 stage 加 `"pre_query": {"field": "bl_no", "wait_ms": 1200}`，
converter 注入 fill(placeholder=请输入)+click_text 查询+wait 把列表收敛到目标单。

## 纪律 19：费用行 应用子策略 必选 —— 策略标识=异常 会让 保 存 被必填校验拒
新增标准费用模板行的 应用子策略(td3) 不选时 策略标识=异常；选 订舱全穿透-道承担 后 变正常。
保存 toast「检测到未填写必填项」且无 is-required 标记可循时，先查联动父列。
补贴及补贴类别(td9) 在该策略下不渲染输入控件（无补贴策略），勿盲选。
converter 支持 stage 规则 `inject_steps`（after_element 锚点注入 + dataset 取值）补录制漏录的联动选择。

## 纪律 20：服务端必填无 DOM 标记 —— 保存被拒以网络响应为准（实证）

费用表「补贴及补贴类别」（td8）服务端必填（`to_customer.0.subsidy_category`），
但 DOM 无 is-required 标记、无 el-form-item__error，客户端完全看不出。点击 保 存
后先发 `POST /api/order/orderFee/bookRealAmountEdit`（body `action:"check"`），
403 响应 msg 里逐字段给因。诊断口径：**保存类被拒一律挂 response 监听抓该接口响应**，
别信 toast（toast 只给「检测到未填写必填项」笼统文案）。
选项实测：不参与补贴 / 国内段杂费 / 国际段运费 / 手填折后金额；链路取 `不参与补贴`（dataset `fee_subsidy`）。

## 纪律 21：费用表只有 1 行模板 —— 不存在「第二空行」

新增标准费用后费用表仅 1 数据行（主表+fixed 左右镜像各 1 份，`.el-table__row`
全表计数=3 是镜像不是行数）。保存被拒与「第二空行」无关；操作列按钮 span 文本
带尾随空格（`删除 `），xpath 精确匹配 `span='删除'` 必失败。

## 纪律 22：vxe 勾选一律 cell 级锚定，勿限定 fixed-left，勿用 icon span

- icon span（`.vxe-checkbox--unchecked-icon`）点击不可靠（解析到但不可见/隐藏页签同名结构干扰）；
  锚 `.vxe-cell--checkbox:not(.is--disabled)`（cell 有盒，实证一点即全选/勾行）。
- **fixed-left/fixed-right 克隆与视口宽度相关**：录制窗口宽时有 fixed 包装，无头 1920 下可能没有
  ——选择器加了 fixed-left 前缀就会整页找不到（n6 实证：审批中心首行勾选超时两轮才定位）。
- 详情页费用锁定不开弹层：点按钮后页面上对客/对商费用 vxe 表转可选模式，对商表 checkbox
  带 `is--disabled` 不可选。
- n4 生成子订单确认后页面刷新回默认页签，el-tabs 隐藏页签 DOM 仍在但 display:none——
  n5 类接续节点先显式切 tab（inject_steps before_element 机制）。
