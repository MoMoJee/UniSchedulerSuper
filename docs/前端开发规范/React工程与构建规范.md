# React 工程与构建规范

> 生效日期：2026-07-14（FR-0）  
> 适用范围：`frontend/` 内的 React + TypeScript + Vite 代码，以及 Django 的 React 模板/静态资源发布链路。

## 1. 目录与职责

```text
frontend/                   # 唯一的 React 源码、Node 配置、测试与 lockfile
  src/                      # TypeScript/React 源码
  e2e/                      # Playwright 浏览器测试
  vite.config.ts            # Vite、Vitest 与构建输出配置
core/templates/home_react.html
core/templatetags/frontend_assets.py
core/static/react/          # Vite 构建临时产物，git 忽略
staticfiles/react/          # collectstatic 发布产物，git 忽略
```

`frontend/` 是源码；`core/static/react/` 和 `staticfiles/react/` 都是可再生发布产物，不可手工编辑、不可作为业务源码提交。Django 继续负责登录、CSRF、API、WebSocket、模板入口和静态资源服务。

## 2. 运行时与依赖

- Node：`>=22.20.0 <23`；npm：`>=10.9.3 <11`。实际版本由 `frontend/package.json#engines` 和 `package-lock.json` 固定。
- 必须使用 `npm ci`，不得在 CI/发布环境使用无锁版本的 `npm install`。
- React 页面不保存认证 Token；同源请求使用 Django Session Cookie + CSRF。启动配置只通过 `frontend-bootstrap` JSON script 注入最小非敏感数据。
- 业务 API、Query、设计系统组件将自 FR-1 以后逐步加入；FR-0 页面不得读取或写入 Planner 数据。

## 3. 本地开发

```powershell
cd frontend
npm ci
npm run dev
```

另开 Django 终端，并仅在本地开发设置：

```powershell
$env:FRONTEND_MODE = 'react'
$env:VITE_DEV_SERVER_URL = 'http://127.0.0.1:5173'
.\.venv\Scripts\python.exe manage.py runserver
```

`VITE_DEV_SERVER_URL` 仅允许 `DEBUG=True`。生产或 staging 验收必须清空该变量、构建静态文件并测试 manifest 路径。

## 4. 质量命令

```powershell
cd frontend
npm run format:check
npm run typecheck
npm run lint
npm run test:unit
npm run build
npm run test:e2e
```

首次在新机器运行 Playwright 时执行 `npx playwright install`。不得以跳过 E2E、关闭 strict TypeScript 或增加 eslint warning 来使门禁通过。

后端配套门禁：

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test core.tests.test_frontend_shell agent_service.tests.test_frontend_ws_smoke
```

## 5. 构建、发布与缓存

发布顺序必须是：

```powershell
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

构建会生成 `core/static/react/manifest.json` 与 hash CSS/JS；`frontend_assets.vite_entry` 根据 manifest 输出资源标签。HTML 使用 Django 的 `never_cache`，资源文件名因内容变更而改变，因此普通刷新、硬刷新和旧标签页不会继续请求不存在的 bundle。

部署前必须验证 `staticfiles/react/manifest.json` 和其引用的 CSS/JS 都存在；manifest 入口键当前为 `index.html`，开发服务器入口为 `src/main.tsx`，两者不可混用。

## 6. 入口开关与回退

| 设置 | 行为 |
| --- | --- |
| `FRONTEND_MODE=legacy`（默认） | `/home/` 渲染现有 `home.html`。 |
| `FRONTEND_MODE=react` | `/home/` 渲染 `home_react.html`，由 Vite dev server 或 production manifest 加载。 |
| 非法值 | Django 启动失败，避免未知入口上线。 |

回退流程：把 `FRONTEND_MODE` 设回 `legacy`，重启应用并验证 `/home/`；不删除数据库、不执行数据迁移、不回退 P1–P6，也不得恢复旧 Planner API。若 React manifest 缺失，模板标签 fail-closed 并提示先构建，不能偷偷加载未 hash 的旧脚本。

## 7. 当前测试边界

FR-0 覆盖 React 构建壳、Django 登录/CSRF、manifest、ASGI WebSocket 握手/ping 和 Chromium Vite 冒烟。它不代表 Planner/Event/Todo/Reminder/文件/Agent 业务 UI 已迁移；这些在 FR-1 至 FR-7 分阶段验收。
