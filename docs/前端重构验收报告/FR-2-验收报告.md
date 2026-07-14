# FR-2 设计系统、应用壳与跨模块交互原语验收报告

> 验收日期：2026-07-14  
> 结论：**通过**。本阶段只构建 React 应用壳与通用原语；日程、待办、提醒、Agent、文件均未接入真实读取或写入流程。

## 1. 实现范围

| 项目 | 实现文件 | 结果 |
| --- | --- | --- |
| Token 与主题 | `styles/index.css`、`app/theme-controller.tsx`、`stores/ui-store.ts` | 浅色/深色/system token，只有主题和安全面板比例进入 localStorage。 |
| AppShell | `app/app-shell.tsx`、`app/routes.tsx` | 顶栏、主导航、中间占位工作区、右侧 Agent 占位区；桌面三栏可调整，窄屏改为可关闭面板。 |
| 路由 | `app/routes.tsx`、`core/urls.py`、`core/views.py` | `/home/...` 可在 React 模式直接刷新；legacy 子路径明确 404，不改变旧路由语义。当前路由只是无数据迁移占位页。 |
| 可访问原语 | `components/ui/` | Radix AlertDialog/Dialog/Popover/Dropdown/ScrollArea/Select/Switch/Toast、Tabs、Sheet、Tooltip；Button 支持 ref 以正确恢复焦点；Lucide 取代图标字体依赖。 |
| 共享状态/安全 | `components/shared/`、`app/error-boundary.tsx` | Error notice、Skeleton/Badge、SafeMarkdown（不注入 HTML）、应用错误边界。 |
| 动效/布局 | `motion/react`、`react-resizable-panels` | 仅短页面进入过渡；尊重 `prefers-reduced-motion`；面板最小宽度受限。 |

未迁移旧文件：`core/templates/home.html`、旧 Planner manager、旧 Agent DOM 管理器均未修改。React 默认入口仍关闭，因此不存在双写或数据迁移。

## 2. 验收测试结果

| 层级 | 结果 | 证据 |
| --- | --- | --- |
| 静态 / 构建 | 通过 | `format:check`、`typecheck`、`lint`、`build` 全通过。 |
| RTL / axe | 通过，26 单元测试中的 AppShell/ConfirmDialog 覆盖 | AppShell 的严重/高危 axe 违规为 0；确认框打开后焦点进入取消按钮，Escape 后回到触发按钮。 |
| Chromium E2E | 通过，4/4 | React 壳不加载 legacy Planner manager；320px 可开/关导航与 Agent；768px 内容可达；dark preference 正确恢复。 |
| Django | 通过，8 shell/static 测试 | React `/home/todos/` 可直达；legacy `/home/todos/` 为 404；CSRF/manifest/collectstatic 正常。 |
| 手工可复核截图 | 已生成 | `frontend/test-results/.../fr-2-mobile-320.png`、`fr-2-tablet-768.png`、`fr-2-dark-desktop.png`（Playwright 运行产物，未纳入版本库）。 |

键盘路径已验证：Tab 可进入导航；移动端由带 `aria-label` 的按钮打开导航/Agent；确认框的初始焦点、Escape 关闭、焦点恢复均由 RTL 验证。AppShell、导航、Agent 区均有语义 landmark/label；图标按钮同时有 Tooltip 和 `aria-label`。

## 3. 视觉与响应式结论

1. 断点：桌面使用可调整三栏；`<=1023px` 采用单工作区及覆盖式导航/Agent；最小页面宽度 `320px`。
2. 主题：浅色和深色均使用同一语义 token；warning/danger 与普通文本不会因主题切换变成无意义颜色。系统主题在没有用户偏好时生效，已持久化 `dark` 时以用户选择优先。
3. 动效：入口过渡 160ms，减弱动效时关闭；没有动画等待网络或掩盖失败状态。

## 4. 已知非阻断项与后续前置条件

production 初始 JS 为 553.88 kB（gzip 178.30 kB），Vite 给出大 chunk 提示。当前只含工程壳且不对用户开放，不构成功能/安全缺陷；在 FR-3 引入 FullCalendar 前必须按 feature route 动态加载，重新记录 bundle 结果，避免日历代码进入所有路由首包。

FR-3 开始前继续保持：

1. `FRONTEND_MODE=legacy` 默认值；
2. 不开放 React Planner mutation；
3. 任何只读页面仅调用 `/api/v2/...`，并对真实/脱敏 fixture 做旧新投影对照；
4. 新增组件不得在 `components/ui` 内发 HTTP 请求。
