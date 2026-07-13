# FR-0 工程基座、开发规范与安全发布通道验收报告

> 验收日期：2026-07-14  
> 结论：**通过**。FR-1 可以开始；`FRONTEND_MODE` 仍默认 `legacy`，没有迁移任何 Planner 业务界面或数据。

## 1. 范围与交付物

FR-0 按 [前端现代化重构详细实施与验收方案](../前端现代化重构详细实施与验收方案.md) 实施了隔离的 React 工程和 Django 发布通道。

| 交付项 | 结果 |
| --- | --- |
| React + TypeScript + Vite 工程 | 新增 `frontend/`，含 strict TypeScript、ESLint、Prettier、Vitest/RTL、MSW 依赖预留、Playwright/axe 依赖预留和 `package-lock.json`。 |
| Django 入口 | 新增 `home_react.html`、`frontend_assets.vite_entry`；`/home/` 按 `FRONTEND_MODE` 选择 React 或旧模板。 |
| 默认安全性 | 设置默认 `FRONTEND_MODE=legacy`；非法值 fail-closed；生产环境设置 `VITE_DEV_SERVER_URL` 直接拒绝启动。 |
| 启动契约 | `frontend-bootstrap` JSON 只含用户名、CSRF token、`/home/` 与 `/ws/agent/` 路径；没有 Planner 数据、Token 或业务逻辑内联脚本。 |
| 静态发布 | Vite 输出 `core/static/react/manifest.json` 和 hash 资源；`collectstatic` 可发布至 `staticfiles/react/`。 |
| 回退 | 把环境变量改回 `legacy` 即恢复旧 `home.html`；无数据库迁移、无 API 降级。 |

本阶段没有新增任何 Planner 请求，也没有改动 P1–P6 数据模型、V2 接口、cohort 或 Agent 回滚机制。

## 2. 实施中发现并修复的问题

1. 初始选择的 TypeScript `7.0.2` 与 `typescript-eslint@8.63.0` peer range 不兼容，`npm install --package-lock-only` 正确拒绝了解析。已改为受支持的 `TypeScript 6.0.3`，未使用 `--force` 或 `--legacy-peer-deps`。
2. Vite production manifest 的入口键是 `index.html`，而开发服务器需加载 `src/main.tsx`。模板标签现显式管理该映射，避免生产模板查询错误入口。
3. Vite 默认将 manifest 放入隐藏 `.vite/` 目录，Django `collectstatic` 会跳过该目录。已指定 `manifest: "manifest.json"`，并实测 `staticfiles/react/manifest.json` 与其 hash CSS/JS 均被收集。
4. 新增的 WebSocket 测试最初将每个 communicator 操作放在不同事件循环中，导致连接在握手中被取消。现将 connect/receive/ping/disconnect 固定在同一个 async 测试协程中，测试的是实际 ASGI 路由而非伪造 socket。

## 3. 自动化测试结果

环境：Windows、Node `v22.20.0`、npm `10.9.3`、Python `3.11.9`（项目 `.venv`）。Playwright 首次安装了 Chromium/headless shell；浏览器缓存不进入仓库。

| 命令/用例 | 结果 | 证据 |
| --- | --- | --- |
| `npm ci --ignore-scripts` | 通过 | 锁文件可复现安装，289 个包。 |
| `npm run format:check` | 通过 | Prettier 无格式差异。 |
| `npm run typecheck` | 通过 | strict TypeScript 无错误。 |
| `npm run lint` | 通过 | ESLint `--max-warnings=0` 无 warning/error。 |
| `npm run test:unit` | 通过 | 2 个文件、3 个测试：启动配置正常/缺字段 fail-closed，React 壳不访问 Planner。 |
| `npm run build` | 通过 | 17 modules；产出 hash CSS 1.02 kB、JS 191.69 kB（gzip 60.71 kB）和 `manifest.json`。 |
| `npm run test:e2e` | 通过 | Chromium 1/1；Vite dev 页面可加载，未加载 legacy `planner-v2-client`。 |
| `npm audit --registry=https://registry.npmjs.org --audit-level=high` | 通过 | 0 vulnerabilities。默认镜像不支持 npm audit 的 POST 接口（405），故审计显式使用官方 registry；这不影响 lockfile 安装。 |
| `manage.py check` | 通过 | `System check identified no issues (0 silenced)`。 |
| Django 壳测试 | 通过 | 7 个 `core.tests.test_frontend_shell`/`test_static_version` 测试：未登录重定向、legacy 默认模板、React bootstrap、manifest 正/反例、CSRF 缺失 403/带 token 200。 |
| ASGI WebSocket 冒烟 | 通过 | 1 个真实 `AuthMiddlewareStack` 测试：Session Cookie 认证、`/ws/agent/`、`connected` 和 `ping → pong`；Agent 图与回滚持久化在测试中 mock，未调用模型。 |
| `manage.py collectstatic --noinput` | 通过 | `staticfiles/react/manifest.json`、对应 CSS/JS 和 `index.html` 均存在。 |

注：Django 启动日志会尝试发现已有的外部 MCP 服务，测试中 12306 MCP 连接失败有日志记录，但 `manage.py check` 和本阶段全部测试仍通过；React FR-0 未调用该外部服务，因此它不构成 FR-0 缺陷。

## 4. 手工/发布核验

1. 查看 Vite manifest：production key 为 `index.html`，模板标签正确输出 `/static/react/assets/<hash>.css` 与 `/static/react/assets/<hash>.js`。
2. 查看 collectstatic 目录：非隐藏 manifest 和引用资源完整存在，修复了隐藏 `.vite` 目录不会被发布的问题。
3. 开关审计：代码默认 `legacy`，React 壳不引用 `planner-v2-client.js`、`event-manager.js` 或任何 legacy manager；旧 `home.html` 未被修改，默认行为保持不变。
4. 回退审计：不存在数据库 schema/data 改动；设置 `FRONTEND_MODE=legacy` 即可回到原页面。生产禁止 `VITE_DEV_SERVER_URL`，避免错误从开发服务器加载资源。
5. 源码扫描：`frontend/src` 与 `frontend/e2e` 未命中旧 `/get_calendar/`、`/events/create_event/`、`/api/todos/`、`/api/reminders/` 路径或 legacy manager；FR-0 无任何 Planner 网络调用。

## 5. 未迁移内容与风险

- Event、Todo、Reminder、共享、搜索、文件、Quick Action、Agent UI/附件/回滚业务渲染均未迁移；这是 FR-1 至 FR-7 的既定范围，不是 FR-0 缺陷。
- 浏览器 E2E 当前覆盖 Vite 开发壳；已登录 Django 浏览器业务流尚无必要业务 UI。Django test client 覆盖登录/CSRF，Channels 测试覆盖认证 WebSocket。FR-3 之后将增加真实已登录 Planner E2E。
- 生产首次启用 React 前必须执行：`npm ci` → `npm run build` → `collectstatic --noinput`，并确认 `staticfiles/react/manifest.json` 存在。没有构建产物时 React 模板会 fail-closed，不能作为发布成功。

## 6. 放行与下一阶段

FR-0 的工程隔离、静态发布、默认安全开关、认证/CSRF、WebSocket 路径和基础质量门禁均达成。允许按方案进入 **FR-1：类型化 API、DTO 映射、错误模型与查询核心**。FR-1 开始前继续保持 `FRONTEND_MODE=legacy` 默认值，React 新代码只读取 V2 契约的测试 fixture，暂不对真实 Planner 发写请求。
