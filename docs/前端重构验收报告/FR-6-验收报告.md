# FR-6 验收报告：搜索、设置、Agent 配置与导入

验收日期：2026-07-14；结论：通过。

- 搜索使用 `/api/v2/search/`、250ms 防抖和 AbortSignal；支持类型筛选、中文、键盘上下/Enter/Escape、结果深链。
- 设置保存仅使用非 Planner 偏好接口；模型/思考模式、Skills、上下文优化、Token 用量均使用 Agent 配置接口，敏感 Cookie/API key 不写入 URL 或 localStorage。
- 课程导入覆盖学期、内存 Cookie、解析预览、勾选确认、成功后 Planner Query 失效。
- Playwright 覆盖搜索防抖/V2 路径、保存设置、键盘、优化保存、课程解析导入和 Cookie 清空；Axe 在搜索、设置和文件路由无违规（色彩对比由设计视觉验收单独检查）。

独立模板分类：`home_react.html` 为 React 壳；`home.html` 保留至 FR-8 的受控 legacy 回退；认证、公开介绍/帮助、密码重置、Token/用户数据、实验演示和导出模板继续由 Django 独立提供，不在本阶段删除或断链；`file_service/files.html` 保留为 legacy 对照，React `/home/files` 为新入口。
