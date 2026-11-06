<p align="center">
  <img src="banner.svg" alt="Fin UI Test Platform" width="100%" />
</p>

# Fin UI Test Platform

> 把 UI 用例从"一段代码"变成"一张可复用、可 diff 的 DAG 图"。

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.6-009688.svg)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.x-2EAD33.svg)](https://playwright.dev/)
[![Vue](https://img.shields.io/badge/Vue-3.5-42b883.svg)](https://vuejs.org/)
[![Element Plus](https://img.shields.io/badge/Element_Plus-2.9-409EFF.svg)](https://element-plus.org/)
[![Vue Flow](https://img.shields.io/badge/Vue_Flow-DAG-ff6b6b.svg)](https://vueflow.dev/)
[![Tests](https://img.shields.io/badge/pytest-1003_passed-brightgreen.svg)](#testing)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](../LICENSE)

## Features

- **DAG 可视化编排** — 拖拽 UI 操作节点 + 连线描述执行顺序，自动布局 / 新节点防重叠 / minimap；**节点即页面域**（元素按域沉淀，保存期 `validate_ui_scope_bindings` 强校验缺域/库外元素/跨域绑定三类 400，执行期 `_locator` 跨域引用即抛错）
- **20 个内置浏览器动作 + 动作库 JS 模板** — 原生 goto / click / fill / press / upload / evaluate + 业务封装 pick（下拉增强）/ save（保存并确认）/ confirm（弹窗确认）/ search（列表检索）/ row_button（行内按钮）/ toast_watch（提示断言）等；每节点产出结构化 facts（url / title / text，逐步 result 留档）。词表见前端 `utils/ui.ts`，已下线动作（screenshot / select_option）存量步骤引擎侧永久兼容
- **元素库 + 动作库** — 多策略 + 兜底链定位（test_id / for / label / placeholder / button / text / role / css / xpath，固定优先级、首个有值键生效），元素按名引用，内联策略可随用随配；自定义 JS 模板沉淀复用
- **数据集收口（2026-10-28）** — UI 步骤 value/url/field/row 禁自带 `${函数(...)}` / `${db.query_*}`（保存校验拒绝）；生成规则写数据集单元格（整串 `${函数(...)}` 执行时求值，`evaluate_dataset_cell`，坏规则保留原文暴露），步骤只引用 `${sheet.字段}`；选中 sheet 双通道注入按原始数据相等去重；Excel 场景表一键迁移（migrate_excel_datasets.py，幂等）；批量导入（2026-11-06）——数据集页粘贴一批数据（Excel 复制 Tab 分隔 / CSV / 单列纯值），前端解析成 N 个 sheet（首行=字段名，sheet 名=首列值；单列字段名预填现有 sheet 首字段），支持追加/覆盖
- **提取 + 17 种断言** — 页面事实 JSONPath 提取入节点命名空间；JSONPath / 耗时 / DB 查询 / DB 交叉校验断言复用共享引擎，DB 断言支持重试应对异步落库
- **失败取证** — UI 节点失败自动截图入文件中心（按执行人归属），事件携带 `step_kind=ui` 与 `screenshot_file_id`
- **执行方案** — 跨系统用例编排：`combo` 并行组合 / `chain` 串行链（整链轮数 × 轮间并行正交、相邻成员 `pass_vars` 名单定向传参注入 `__prev__`、失败阻断本轮下游；第 r 轮取成员第 r 个 sheet）、成员级数据集换绑、方案内嵌定时（2026-10-28 套件收口承接）；执行弹窗「全部 sheet」（2026-11-06）——chain 一键执行时本次轮数覆盖为成员数据集最大行数（`POST /plans/{id}/execute` body.rounds，仅本次生效不回写配置），批量数据逐 sheet 跑的标准入口
- **结构化报告** — 每步 facts / 断言 / 耗时全量落库，响应体 JSON 可展开收起；后端导出 CSV（Excel 兼容）/ HTML（可打印 PDF）
- **工程化** — JWT 鉴权 + admin/member 角色 + 操作审计 + Alembic 迁移 + 亮暗主题 + 标签页 + 命令面板（Ctrl+K）

> 本平台由 fin-api-test 的 DAG 编排核心派生：执行器 / 变量注册表 / 断言引擎 / 报告链路与 API 平台同源；接口注册工作面已裁撤（历史 API 节点仍可执行回放），数据集改造为 UI 场景驱动的 sheet 模型。

## Quick Start

```bash
# 1. 建库
mysql -u root -p -e "CREATE DATABASE fin_ui_test DEFAULT CHARSET utf8mb4"

# 2. 配置后端
cd platform/backend
cp .env.example .env   # 填写 DB_PASSWORD 与 JWT_SECRET_KEY
pip install -r requirements.txt
python -m playwright install chromium   # 浏览器内核
python -m uvicorn app.main:app --port 8000   # 自动迁移建表 + 创建 admin 账号

# 3. 启动前端
cd platform/frontend
npm install && npm run dev
```

访问 http://localhost:5173 · 默认账号 `admin` / `admin123`（首登强制改密）· Swagger http://127.0.0.1:8000/docs

## Architecture

```
┌─────────────────────────────────────────────────┐
│        前端 Vue3 + Element Plus + Vue Flow        │
│  views (20 页) ← composables                      │
│  useExecutionRunner / useGroupTree / useRefGroups │
│       │                    ↑ 复用轮询/分组/引用图   │
│       │ api/index.ts ← types/api.gen.ts (OpenAPI) │
└──────────────────────────┬──────────────────────┘
                           │ /api
┌──────────────────────────▼──────────────────────┐
│                 路由层 routers/                   │
│  HTTP 语义 + 鉴权 + 审计日志（薄层，无业务逻辑）      │
├─────────────────────────────────────────────────┤
│       数据访问层 crud/（按域拆分，显式 re-export）   │
│  users · auth · executions · datasets           │
│  ui_elements · custom_actions · ui_action_docs   │
│  files_center · versions · legacy                │
├─────────────────────────────────────────────────┤
│                 服务层 services/                   │
│  execution_launcher · runtime · ui_runtime       │
│  scheduler · plan_executor · contract_sync       │
│  report_export · replay_service · notifier       │
└──────────────────────────┬──────────────────────┘
                           │ 线程池异步执行
┌──────────────────────────▼──────────────────────┐
│              DAG 执行引擎 engine/                  │
│  topo_order 唯一实现 → step_type 分发              │
│  ui: ui_runtime 动作链 → facts → 提取/断言/截图     │
│  api: prepare_request → 请求 → 提取 → 断言（历史）  │
│  events.py: StepResult → ExecutionSink 接缝       │
│  variables.py: 节点命名空间变量注册表                │
└──────────────────────────┬──────────────────────┘
                ┌─────────┴─────────┐
                ▼                   ▼
          Playwright           MySQL Client
          浏览器动作/截图        DB 取数与交叉校验
```

**分层规约**（由测试守卫）：

- 路由层不内联 ORM，业务不变量下沉 `crud/` 域模块（如登录锁定策略在 `crud/auth.py`）
- 执行编排（建记录→提交→聚合通知）只有一份实现 `services/execution_launcher.py`，
  单次/批量/定时三入口共用
- UI 节点提取/断言复用 DAG 执行器 `_extract_and_assert` 收口（与 API 节点同一条管线，
  facts 即 response_body）
- 表达式求值单点 `engine/expression.py`（数据集单元格生成规则求值 `evaluate_dataset_cell` +
  步骤 `${sheet.字段}` 引用解析；函数集复用 `engine/functions.py` 注册表，与 API 平台同源）
- Kahn 拓扑排序单点 `engine/topo.py`；企微通知门控单点 `services/notifier.py`
- 执行引擎产出 `StepResult` 事件经 `ExecutionSink` 落库（`DbSink`），
  引擎不反向 import 路由层 —— `test_engine_does_not_import_routers` 守卫
- 报告导出为后端纯函数 `services/report_export.py`，`GET /reports/executions/{id}/export?format=csv|html`

## 前后端类型单一事实来源

后端 Pydantic schema → `npm run gen:api` 生成 `src/types/api.gen.ts` 供前端消费，字段漂移在 vue-tsc 编译期暴露。
错误契约显式化：拦截器把一切失败规整为 `ApiError`（message 必为后端 detail），视图 catch 只读 `e.message`。

## Testing

```bash
cd platform/backend
python -m pytest tests/ -q          # 1003 passed
python -m ruff check --select F .   # 与 CI backend-lint 同口径
python -m mypy app                  # 0 错误（本地口径；CI 未设 mypy 门禁）
cd ../frontend && npx vue-tsc --noEmit   # 与 CI frontend-lint 同口径
cd ../frontend && npm test -- --run      # vitest 191 passed
```

测试布局（fake-db 单测，不依赖真实 MySQL、不拉起浏览器）：

| 域 | 文件 | 覆盖 |
|---|---|---|
| 执行编排 | `test_execution_launcher.py` | 展开→提交→聚合编排 + ExecutionSpec 组装 |
| 执行引擎 | `test_execute_node.py` | 单节点管线 + 分层守卫 |
| UI 集成 | `test_ui_integration.py` | 定位策略链 / ui_runtime 纯函数 / step_type=ui 分发（facts→提取→断言→截图事件全链路，替身不拉浏览器） |
| UI 动作 | `test_ui_actions.py` | 动作词表 / CaseNodeConfig 的 step_type+ui_params 结构写回 |
| 请求发送 | `test_request_sender.py` | 分发/multipart/异常分类 + 防平行实现守卫 |
| 通知 | `test_notifier.py` | 门控开关/单条与聚合通知/环境查无 |
| 拓扑排序 | `test_dag_executor_topo.py` | Kahn 排序唯一实现 |
| 测试套件 → 执行方案 | `test_plans.py` | 方案 CRUD/成员保存校验/combo 并行提交/chain 轮次传参与失败阻断/内嵌定时 |
| 页面域编排 | `test_page_scope_labels.py` | 域中文名映射/节点域绑定 |
| 动作库文档 | `test_ui_action_docs.py` | 动作词表与用法文档一致性 |
| 变量注册表 | `test_variables.py` | 命名空间隔离/引用取不到即失败/order_params 参数拓扑与环检测 |
| 保存校验 | `test_validation.py` | 悬空引用/未知节点与函数/依赖环拒绝保存并定位参数 |
| 续跑与重放 | `test_{resume_executor,orchestration_fingerprint,report_context}.py` | 结构指纹锁定/续跑起点定位/报告虚拟上下文 seed 还原 |
| crud 域 | `test_{users,auth,executions}_domain.py` | 登录锁定/首管理员/最后管理员保护等 |
| 报告导出 | `test_report_export.py` | CSV/HTML 契约 |
| schema | `test_audit_mixin.py` | 审计字段继承 + Out 契约 |

## Tech Stack

FastAPI · SQLAlchemy 2.0 · Pydantic 2 · Alembic · PyMySQL · Playwright ｜ Vue 3.5 · Element Plus · Vue Flow · Pinia · Vite · openapi-typescript

## FAQ

- **uvicorn 无 access log** — `alembic/env.py` 的 `fileConfig()` 需设 `disable_existing_loggers=False`
- **路由切换后页面空白** — 顶层 `<router-view>` 不可加 `:key="route.path"`，会触发 MainLayout 重挂载丢状态
- **UI 节点定位不到元素** — 优先在元素库配多策略兜底链；`for` 语义按 label[for=X] 后兄弟容器首个输入件定位（被测系统 for 值非真实 DOM id，[id=X] 直查定位不到——实证）

## License

[MIT](../LICENSE)
