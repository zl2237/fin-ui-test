# UI 用例新建手册

从零把一条 UI 自动化用例搭起来并跑通的完整操作指引。目标读者：第一次在本平台编排 UI 用例的测试同学。

平台入口：
- 前端开发模式 http://localhost:5173（vite 热更，日常用这个）
- 前端生产模式 http://localhost:8000（后端托管 dist，改动需重新构建）

---

## 1. UI 用例模型速览

- 用例是一张 **DAG 画布**，节点分两类：**API 接口节点**（绑定接口定义）和 **UI 操作节点**（页面级动作组）。两类节点可任意混排连线——典型用法：API 造数 → UI 操作页面 → API/DB 断言落库结果。
- 一个 UI 节点 = **一组有序步骤**（`steps[]`）。首个 UI 节点执行时才启动浏览器，整个执行共享同一个浏览器会话。
- 步骤三要素：**动作**（点/填/选…）+ **元素定位**（元素库引用或自定义策略）+ **参数值**（文本/按键/超时…，支持 `${变量}`）。

## 2. 前置准备

### 2.1 环境（必须）

「环境管理」新建/编辑执行环境，UI 用例至少要用到：

| 配置 | 用途 | 说明 |
|---|---|---|
| Base URL | `goto` 相对路径拼接、cookie 注入域 | UI 用例必填 |
| 登录配置 login_config | token 注入 cookie，免登录直达 | 推荐配置；不配则用例里自己走登录页 |
| 数据库 db_config | db_* 断言 / source=db 提取 | 可选，不配时跳过 DB 能力 |
| browser_config | 浏览器行为 | 可选，JSON 字段，默认 headless 截图 on_failure |

`browser_config` 可调项（存于环境，前端未暴露表单，需经 API 更新）：

```json
{
  "headless": true,              // 有头模式调试时改 false
  "screenshot": "on_failure",    // on_failure（默认）/ always / off
  "screenshot_category_id": 8,   // 截图归档分类；缺省自动建「UI执行截图」
  "slow_mo_ms": 0,               // 有头调试时放慢操作
  "viewport": { "width": 1920, "height": 1080 },
  "launch_args": ["--disable-dev-shm-usage"]
}
```

### 2.2 元素库（推荐）

「元素库」页维护，两条路：

1. **批量导入**：粘贴原 autotest-playwright 的 locator JSON（`{ "key": { "full_xpath": "…", "label": "…", "description": "…" } }`），选目标页面域一次导入。
2. **手工新增**：页面域（如 `ordermanage/business_order_add`，按 `/` 分层成树）+ 元素 Key（同域唯一，如 `bl_no_input`）+ 定位策略键值。

执行时后端按**策略优先级链**依次尝试定位（full_xpath/xpath/css/text/label…共 13 种），任一命中即用。元素库的好处：一处改定位，所有引用它的步骤同步生效。

### 2.3 动作库（按需）

预设 26 种动作（13 原生 + 13 封装）开箱即用。「元素库」页右上「动作库管理」：

- **封装动作**：可编辑用法描述（项目级覆盖，帮助中心问号视图同步展示）。
- **自定义动作**：JS 模板（脚本内以 `args` 访问传参，return 值进 `$.result`），支持新增/修改/删除。

## 3. 新建用例（画布编排）

1. 「用例管理」→ 新建用例（或打开已有用例进入设计器）。
2. 左侧面板切到 **「UI 操作」** 页签：动作按「原生/封装」分组列出（名称 + action 标识 + 说明）。
3. **点击动作条目**即添加一个 UI 节点到画布（首步为该动作；节点名取动作中文名）。常用起点：`goto`（导航）。
4. 需要混排 API 时切回「接口」页签点接口添加。
5. 顶部「连线模式」依次点源节点、目标节点建立执行顺序；「自动布局」整理版面。
6. **双击节点**（或回车）打开节点配置抽屉。
7. 保存用例。UI 节点在画布上显示 `UI·组N动作` 徽标。

## 4. 节点配置抽屉（UI 节点）

### 4.1 编辑步骤

抽屉里是步骤列表，可增删改、上下移。每个步骤表单：

**① 动作类型**——下拉三组：原生 / 封装 / 项目自定义（直列模板，选中即绑定）。

**② 元素定位**（需要定位的动作出现）——两种模式二选一：
- **从元素库选择**：先选页面域 → 再选元素（搜索 element_key/描述）。
- **自定义**：选定位方式（CSS / XPath / 可见文本 / ARIA角色 / placeholder / label / data-testid / label-for）+ 定位值；`role` 需补角色名称。

**③ 参数值**——随动作变形：fill 的输入内容、pick 的选项文本、press 的键名、wait 的毫秒、evaluate 的 JS 表达式、custom 的模板传参……所有文本参数支持 `${变量}`。

**④ 超时时间**——本步骤元素定位/页面加载上限，默认 15000ms。页面慢就调大，不用改全局。

### 4.2 提取与断言（与 API 节点同一套引擎）

UI 步骤执行后产出 **facts**（页面事实），供提取与断言消费：

| JSONPath | 内容 |
|---|---|
| `$.url` / `$.title` | 当前页 URL / 标题 |
| `$.text` | 页面主要文本 |
| `$.steps[0].text` | 第 1 步产出的元素文本 |
| `$.result` | evaluate / 自定义动作的 JS 返回值 |

- **提取**（post_extract）：`source=response` + JSONPath，取出的值进变量池（`${变量}` 引用，后续步骤/SQL/断言可用）。
- **断言**（assertions）：`json_path_*` 家族对 facts 求值，如 `$.url contains detail`、`$.result equals 42`；配了 db_config 还可用 `db_query_*` 做落库校验。
- **wait_after_ms**：本节点全部步骤完成后额外等待毫秒数（如等列表刷新）。

### 4.3 `${变量}` 从哪来

数据集行变量（数据驱动执行时）、前序节点的提取变量，出现在：URL、输入/选项/按键/JS 文本、SQL。例：`fill` 输入 `${bl_no}`，`goto` 打开 `/detail/${order_id}`。

## 5. 执行与查看结果

1. 用例列表/设计器点「运行」，选环境（UI 用例不配 Base URL 会直接报错）。
2. 执行记录页/报告详情看进度：每个 UI 节点一条 step，展开看每步动作、命中元素、耗时与错误现场。
3. **截图**：默认失败节点自动截图；成功也想要就配 `browser_config.screenshot: "always"`。截图统一归档到文件中心 **「UI执行截图」分类**（自动创建），**上传人 = 执行人**，报告里可直接查看。
4. 调试建议：环境 `headless: false` + `slow_mo_ms: 300` 肉眼跟一遍，再切回 headless。

## 6. 动作速查（26 预设）

**原生（Playwright 直映射）**：`goto` 导航 · `click` 点击（JS模式绕遮挡） · `fill` 输入 · `select_option` 原生下拉 · `check` 勾选 · `press` 按键 · `type` 逐字输入（自定义组件） · `wait` 等待（元素可见/时长） · `upload` 上传（文件中心ID/绝对路径） · `screenshot` 截图 · `evaluate` 执行JS

**封装（组件适配/实测沉淀）**：`pick` 下拉选择(增强，防"看似选中") · `date` 日期时间 · `custom` 自定义动作模板 · `search` 列表检索 · `click_text` 按文本点击（同名序号/包含匹配） · `row_button` 行内按钮（vxe固定列） · `scroll_bottom` 滚动到底 · `confirm` 弹窗确认（轮询/可选） · `popper_pick` 浮层选项 · `toast_watch` 提示断言 · `save` 保存并确认（一体化） · `uncheck_all` 批量取消勾选

高频组合套路：

```
录入页：goto → fill ×N → pick ×N → date → click_text「保 存」 → toast_watch「保存成功」
列表页：search「${bl_no}」 → row_button「详情」 → (API/DB 断言)
保存场景：save（一步=点保存+确认弹窗+等提示，必填校验失败会报出具体错误列）
下拉被遮挡：click 打开下拉 → popper_pick 点选项
```

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| 元素定位超时 | 步骤超时调大；定位换更稳的策略；被遮挡/固定列副本区用 `click` JS 模式或 `force` |
| Element 下拉选了没生效 | 用 `pick`（自动校验选中值，未生效自动重试） |
| 保存点了没反应 | 用 `save` 一体化动作（自动补点确认/反馈） |
| 弹窗延迟出现 | `confirm` 开「轮询等待」 |
| 页面跳转瞬间脚本报 context destroyed | 跳转前加 `wait` 步骤稳定时机 |
| 浏览器启动失败 | 确认服务端装好 playwright + chromium（`playwright install chromium`）；平台已内置 Windows/reload 兼容修复 |
| 登录态失效 | token 注入失效时目前无 OCR 登录兜底，需更新环境 token；表单登录链路为待补能力 |
| 看不到新加的自定义动作 | 5173 与 8000 是两个站点（localStorage 隔离），确认在当前站点选择了同一项目；动作是项目级的 |
