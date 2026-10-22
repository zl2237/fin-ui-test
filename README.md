# Fin UI Test

> 面向金融业务系统的 UI 自动化测试平台 · Playwright 驱动 · DAG 可视化编排 · 元素库 · 结构化报告

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-1.x-green.svg)](https://playwright.dev/)]
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

金融业务系统的页面操作链路长、录入项多、状态流转复杂。本项目把「打开页面 → 定位录入 → 提交流转 → 结果校验」搬上可视化画布：用例即 DAG，节点即 UI 操作，不再把操作顺序写死在代码里。

## Features

- **DAG 可视化编排** — 画布上把 UI 操作节点连成流程，双击节点配置动作链、提取与断言
- **60+ 浏览器动作** — goto / click / fill / hover / 断言类动作 / 组合动作，事实（facts）结构统一
- **元素库沉淀** — 多策略 + 兜底链定位（test_id / label / text / xpath…），按名引用，系统改版只改一处
- **`${}` 表达式** — 步骤值引用上游提取变量、内置函数（`now()` / `generate_bl_no()` 等）、`db.query_one` 取数
- **提取 + 断言引擎** — 页面事实 JSONPath 提取、17 种断言规则、DB 交叉校验、失败自动重试
- **失败取证** — 失败节点自动截图入文件中心，报告内直接查看
- **环境管理** — 多环境（地址 / 登录 / 数据库连接），连通性即时测试，执行严格绑定用例环境
- **套件编排** — 跨系统串联用例成链，上游变量白名单注入下游

## Quick Start

```bash
cd platform/backend
cp .env.example .env        # 填 MySQL 连接、JWT 密钥
python -m uvicorn app.main:app --port 8000

cd ../frontend
npm install && npm run dev  # http://localhost:5173
```

五步上手：建项目 → 配环境 → （可选）沉淀元素 → 画布编排用例 → 执行看报告。
详见平台内「上手指南」与 [platform/README.md](./platform/README.md)。

## Architecture

```
用例编排 (CaseDesigner)        DAG 画布：UI 操作节点 / 提取 / 断言 / 等待
     ↓
DAG 执行器 (dag_executor)      拓扑调度 · 变量注册表（节点命名空间）· 断言引擎
     ↓
UI 运行时 (ui_runtime)         Playwright 动作链 · 多策略定位 · facts 产出 · 失败截图
     ↓
元素库 | 文件中心 | 结构化报告   元素沉淀 · 截图留档 · 步骤级回放
```

## Tech Stack

[FastAPI](https://fastapi.tiangolo.com/) · [SQLAlchemy](https://www.sqlalchemy.org/) · [Playwright](https://playwright.dev/) · [Vue 3](https://vuejs.org/) · [TypeScript](https://www.typescriptlang.org/) · [Element Plus](https://element-plus.org/) · [Vue Flow](https://vueflow.dev/)

> 本项目由 fin-api-test（API 自动化平台）的 DAG 编排核心派生，共享执行器 / 变量池 / 断言引擎等基础设施；接口注册与数据集入参两个 API 工作面已裁撤。

## License

[MIT](LICENSE)
