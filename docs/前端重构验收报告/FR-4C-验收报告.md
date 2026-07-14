# FR-4C Reminder 写入验收报告

> 验收日期：2026-07-14  
> 结论：**通过（能力矩阵已落实）**。

## Reminder capability 矩阵

| 能力 | 状态 | 请求/界面规则 |
| --- | --- | --- |
| 创建单次与重复 Reminder | 支持 | `POST /api/v2/reminders/`；RRule 可为无限、次数或截止时间。 |
| 单次→重复、重复→单次 | 支持 | 编辑器只有用户改动重复控件时才提交 `recurrence`；选“不重复”发送 `null`。 |
| 编辑/删除整个系列 | 支持 | `PATCH/DELETE /api/v2/reminders/<id>/`，`scope: all`，带 version/ref。 |
| 完成、忽略、延后一小时 | 支持 | 单实例状态动作只走 `/api/v2/reminders/occurrences/action/`，带 occurrence ref/version。 |
| Reminder single/future 定义编辑 | 不在本 UI 开放 | 为避免误改，定义编辑只显示“整个系列”；单实例只允许状态动作。 |
| 日历与详情同步 | 支持 | 所有成功 mutation 失效 `planner` query；不保留会造成“详情旧、编辑新”的本地副本。 |

## 回归与验收

Playwright 创建每周 Reminder，断言 V2 请求的 `recurrence.rrule === "FREQ=WEEKLY"`；API 单元测试断言 occurrence-action 的 action、version 和 ref。查询同时读取 Reminder definition 与窗口 occurrence，左侧/中央投影均基于同一 occurrence 集合，避免把一个系列行误当所有可见实例。

已通过类型、lint、29 个 Vitest、8 个 Chromium E2E、构建、格式与 legacy Planner 扫描。错误响应不关闭面板，成功后依赖服务端重取；默认 React 开关仍关闭。
