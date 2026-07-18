# FR-UI 布局契约修复验收报告

> 日期：2026-07-17  
> 结论：截图中的分享组文字竖排已修复；同类风险已在中央弹窗、分享组、设置、搜索、文件、Planner 和应用根边界统一加固。

## 修复内容

- 中央弹窗改为独立 CSS Module，限定动态视口高度、内部滚动、标题/正文/底栏收缩边界和移动端尺寸。
- 分享组卡片从会互相抢宽度的三列布局改为命名网格区域；正文使用 `minmax(0, 1fr)`，按钮区独占第二行并按卡片实际宽度响应。
- 设置、文件、搜索、Planner 使用组件级 container query，不再依赖浏览器总宽度猜测弹窗内部可用空间。
- AppShell 增加统一布局边界，结构容器、文本、表单和媒体不能把父容器撑破。
- 为首屏 lazy route 增加可见且可访问的加载占位，消除初始化空白和 React Router `HydrateFallback` 警告。
- FullCalendar 工具栏在窄 Planner 容器中改为三行布局；各 chunk 可换行且无横向溢出。
- 修复 TodoModal 与 ReminderPanel 关闭态 sibling key 重复，避免 React 错误复用弹窗实例。
- Daphne 开发 ASGI 在 `DEBUG` 下能够直接提供已构建 React 静态文件；真实 Agent WebSocket 因此可与页面同源验收。生产静态资源路径不变。

## 自动化验收

| 项目 | 结果 |
|---|---|
| TypeScript typecheck | 通过 |
| ESLint | 通过，0 warning |
| Prettier | 通过 |
| legacy Planner URL 门禁 | 通过 |
| Vitest | 17 个文件、36 项通过 |
| Vite production build | 通过 |
| Playwright layout contracts | 4 项通过 |
| Django system check | 通过，0 issue |
| shell + WebSocket smoke | 7 项通过 |

Playwright 覆盖 1440×900、760×900、390×844。每张分享组卡片均断言正文宽度大于 160px、操作区占卡片宽度 85% 以上、卡片与文档无水平滚动；390px 下还逐页验收设置、搜索和文件管理。

## MoMoJee 真实浏览器验收

- 分享组弹窗在桌面、中等宽度和窄屏均保持正常横排文字，操作按钮位于独立行。
- 窄屏页面、Planner、日历工具栏、日历视图、Agent 标题和输入区均无水平溢出。
- 真实日历数据正常读取；本轮浏览器验收没有创建、修改或删除 Planner 数据。
- 普通 `runserver` 的 `/ws/agent/` 404 被确认是错误的验收启动方式。改用修复后的 Daphne ASGI 后，MoMoJee Agent 显示“已连接”，历史消息与输入框正常加载。

## 已知非阻断项

- 主入口 bundle 仍有大于 500 kB 的构建提示，属于后续性能拆包事项，不影响本次布局正确性。
- 本地 12306 MCP 服务连接失败；高德 MCP 正常。该外部服务状态与本次前端布局修复无关。
