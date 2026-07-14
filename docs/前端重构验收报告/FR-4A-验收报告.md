# FR-4A Group 与 Event 写入验收报告

> 验收日期：2026-07-14  
> 结论：**通过（以现有 V2 capability 为边界）**。

## 已交付

- 个人组：创建、改名、颜色修改、删除；删除前可明确选择是否一并删除组内项目。每次 PATCH/DELETE 都携带当前 `expected_version`。
- Event：创建、编辑、删除、组、全天、时间、RRule（日/周/月/年、间隔、每周日期、次数、结束日期/无限）以及正常/重复实例的 `single`、`future`、`all` 范围。
- 重复实例操作从服务端实例获取 `occurrence_ref` 和 `source_version`；前端的 `future` 被严格编码成 V2 wire contract 的 `this_and_future`。
- 非重复 Event 的拖拽/resize 直接 PATCH V2；重复 Event 一律先回退 FullCalendar 的临时移动并打开范围编辑，绝不会因缺少 ref 静默退化成“仅改当前显示项”。共享只读项目不可编辑。

存在附件/共享成员选择器的 UI 未在本切片伪造：当前 Event V2 command contract 不提供该写入字段，统一附件和共享选择交由 FR-5 的资源引用模型接入。

## 测试结果

| 场景 | 结果 |
| --- | --- |
| 创建 Event | Playwright 断言仅 POST `/api/v2/events/`，创建时不带 `expected_version`。 |
| 重复 Event 编辑 | Playwright 断言 PATCH body 含 `expected_version: 3`、`scope: all`、完整 `occurrence_ref`。 |
| RRule 编解码 | Vitest 覆盖 weekly interval/BYDAY/COUNT 往返、无规则和互斥 COUNT/UNTIL 拒绝。 |
| 版本/ref 客户端保护 | Vitest 拒绝没有 occurrence ref 的 single/future；断言 future 转换为 `this_and_future`。 |
| 错误/刷新 | mutation 失败不关闭 Sheet；成功后失效所有 `planner` query，以服务端重新投影为准。 |

上述用例、TypeScript、lint、build、格式检查与 V2 legacy 静态扫描均通过。
