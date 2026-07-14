# FR-5 验收报告：Agent、附件与回滚

验收日期：2026-07-14。结论：通过自动化与后端契约验收；真实已登录浏览器调用因 Codex 浏览器运行时初始化的环境级 `Cannot redefine property: process` 失败，未以模拟结果替代，待你在 React 入口按下述用例补做一次。

## 已交付

- `AgentWorkspace` 以项目既有 WebSocket 协议发送 `{ type: "message", content, attachment_ids }`；解析连接、流式文本、工具调用/结果、结束、停止和错误帧。
- 会话新建、切换、重命名、删除；当前窗口回滚恢复文本和服务端附件 ID，`410` 显示为不可回滚窗口。
- Event/Todo/Reminder/工作流内部附件、云盘附件、本地上传、粘贴/拖入、本地与云盘附件失效前预览校验；历史附件为只读，不再显示无效“移除”按钮。
- 工具选择通过 `active_tools` WebSocket 参数重连生效；Quick Action 独立调用其任务 API；上下文用量、会话任务与记忆优化入口已迁移。

## 自动化证据

- Vitest：14 文件、31 断言通过。
- Playwright：`agent.spec.ts` 4 项通过。覆盖 Event 附件 ID=12 的发送/服务端流回显、回滚重发、Quick Action 轮询、会话重命名、工具白名单重连、云盘/本地附件、键盘打开附件面板和 Axe 扫描。
- Django：`core.tests.test_frontend_shell` 与 `agent_service.tests.test_frontend_ws_smoke` 共 7 项通过。

附件脱敏样例：`attachment_ids: [12]`；工具重连样例：`active_tools=search_items`。测试未调用真实模型或写入真实 Planner 数据。

## 待人工真实调用（React 入口）

以 MoMoJee 新建临时会话，发送“只回复确认、不调用工具”，再各选择一个 Event、Todo、Reminder、云盘文件和图片发送；确认 Agent 明确读取附件。随后对含附件消息回滚并重发，确认仍可读取。最后测试一次 Quick Action、会话重命名、关闭/重连和 `410` 历史回滚提示。完成后删除临时会话。
