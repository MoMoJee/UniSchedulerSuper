# FR-7 验收报告：文件页与统一选择器

验收日期：2026-07-14；结论：通过当前服务端已提供的文件 API 验收。

## 实现

- `/files` React 路由：面包屑、文件夹创建/重命名/删除、文件上传/拖入、URL 上传、下载、重命名、目录式移动、删除、配额、图片预览和 Markdown 读取/编辑/下载。
- `FilePicker` 是 Agent 云盘附件唯一的共享选择实现，支持搜索、多选和进入文件夹；Agent 在发送前调用附件预览接口，避免已删除/无权限的幽灵 ID。
- 所有文件 mutation 失效 `fileKeys.all`，所以源/目标目录、选择器和配额会重新读取服务端真相。

## 测试

- Playwright 覆盖上传、建目录、Markdown 预览/保存、重命名、移动、URL 上传；验证没有 Planner legacy 请求。
- `filesApi` DTO 单元测试、全量 17 项 Playwright、Axe（搜索/设置/文件、reduced motion）均通过。
- 构建输出为 Django `core/static/react`；`npm run check:legacy-planner` 通过。

## 手工边界

服务端仍是文件类型/尺寸、解析、同文件夹去重与权限的唯一判定者。上线前用普通、无权限和已删除文件各验证一次预览、移动、下载及 Agent 发送失败文案；未知二进制使用下载而非伪预览。
