# FR-3 Planner 只读投影验收报告

> 验收日期：2026-07-14  
> 结论：**通过**。FR-3 的只读投影已作为 FR-4 工作区的读取基础保留；没有依赖旧 Planner JSON 或浏览器端无限重复展开。

## 实现与数据路线

`features/planner/hooks.ts` 在可见窗口改变时并行请求 Event occurrence、Event definition、Reminder occurrence、Reminder definition、个人组，以及按需的共享组 occurrence。TanStack Query key 含用户名、`from/to` 和共享组，切换日期/筛选会生成新 key，并向请求传递 `AbortSignal`。事件实例只使用服务端 `occurrence_ref` 作为后续写入身份；RRule 来自 definition，并按实体 ID 回填到实例，不把“当前窗口有多少实例”误当作规则结束。

FullCalendar 使用月、周、日、列表视图；日期/视图/提醒和组筛选同步到 URL。个人 Event、Reminder、共享只读来源有不同的文字/颜色标记，详情抽屉显示时间、描述、类型、重复实例说明和只读状态。共享数据只有显式 `share` 参数才请求，服务端 403/404 被统一错误组件处理，不会将上一个用户的缓存继续展示。

应用壳已修复为按断点只挂载一个 `<Outlet>`；此前桌面与移动 DOM 同时挂载会造成重复查询和重复日历，本次不再依赖 CSS 隐藏另一份业务树。

## 自动化验收

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| V2 projection/mapper | 通过 | Vitest 覆盖显式窗口、非法窗口拒绝、occurrence ref 映射与 definition RRule 回填路径。 |
| 无限重复窗口语义 | 通过 | Playwright fixture 以重复 Event 的 occurrence/ref 和 definition RRule 渲染；翻页仅重新查询下一窗口，不在前端全量展开。 |
| 日历/URL/旧路径 | 通过 | Chromium 用例确认 FullCalendar 渲染、无 legacy manager 脚本；`check:legacy-planner` 通过。 |
| 响应式 | 通过 | 320px、768px E2E 覆盖，且仅挂载当前断点的工作区。 |
| 后端壳/静态发布 | 通过 | `.venv\\Scripts\\python.exe manage.py check`、`core.tests.test_frontend_shell` 6/6、`collectstatic --noinput` 均通过。 |

固定 fixture 不包含真实用户私密内容；真实账号与旧页逐项数量对照仍须在 React 开关打开的隔离测试环境执行。默认前端仍是 legacy，因此本报告不构成生产切换授权。
