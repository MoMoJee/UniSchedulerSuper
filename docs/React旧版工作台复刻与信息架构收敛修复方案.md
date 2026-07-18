# React 旧版工作台复刻与信息架构收敛修复方案

> 状态：R0–R5 已完成并通过自动化与 MoMoJee 真实浏览器验收。创建日期：2026-07-15，完成日期：2026-07-15。  
> 范围：React Home 工作台、待办、提醒、日程弹窗、搜索、顶端入口、分享组、文件、设置与路由收敛。  
> 前置事实源：`docs/前端重构旧版UI复刻审计与缺陷台账.md` 的截图 001–208；Planner 继续只使用 `/api/v2/`，不改变 P1–P6 数据模型或接口语义。

## 1. 本轮问题结论

当前 React 版本存在两种互相竞争的信息架构：

1. `/home/`：已恢复左侧待办/提醒摘要、中间日历、右侧 Agent 的三栏壳；
2. `/home/todos`、`/home/share`、`/home/files`、`/home/settings`：早期迁移形成的全页 workspace。

这使 Home 的摘要只能跳转到另一套页面，且后者的密度、控件、路由切换和旧版审计基线不一致。截图中可见的“日程组 chip 常驻、共享 tab 过高、文件文字重叠、侧拉 Sheet”均是这种收敛尚未完成的直接表现，而不是单个颜色或间距问题。

### 1.1 已定位的实现位置

| 用户反馈 | 当前实现位置 | 直接原因 |
|---|---|---|
| 左上 Todo / 左下 Reminder 不像旧版 | `frontend/src/features/planner/home-sidebar.tsx` | 仅做了只读紧凑投影；没有旧版的列表/四象限切换、筛选、详情/编辑 modal、卡片元数据和独立滚动容器。 |
| 弹窗变侧拉 | `frontend/src/components/ui/sheet.tsx`；`event-editor.tsx`、`reminder-panel.tsx`、`group-manager.tsx`、`tool-picker.tsx`、`search-workspace.tsx` 等 | 把通用右侧 Sheet 当成所有弹层的唯一容器；旧版业务操作实际是居中遮罩 modal。 |
| 搜索不是旧版 | `app/app-shell.tsx`、`features/search/search-workspace.tsx` | 顶部入口虽已存在，但打开的是 Sheet；缺少顶部原位扩展、四类筛选、结果下拉和点击外关闭语义。 |
| 顶部“灵动岛”缺失 | `app/app-shell.tsx` | 当前搜索、设置、工作区菜单分散在 header；没有统一的浮动胶囊和四项菜单层。 |
| 日程组筛选常驻 | `features/planner/planner-workspace.tsx` 的 `group-filter-list` | 将旧版 Calendar toolbar 的筛选浮层直接展开在页面中，挤压日历主体。 |
| 分享组切换错误/样式异常 | `planner-workspace.tsx` 的 `planner-scope-tabs` 与 `share-groups-workspace.tsx` | 共享 occurrence 投影已接入，但 scope tab 没有采用旧版紧凑 tab；切换 loading、当前范围、空态和 V2 返回值需隔离验证。 |
| 文件页混乱 | `features/files/files-workspace.tsx` | 从卡片页逐步加回树、搜索、视图切换，尚未按旧版独立文件管理器的左右结构/工具条/列表行重组。 |
| 设置不符合旧版 | `features/settings/settings-workspace.tsx` | 旧版六 tab 居中设置 modal 被迁成纵向全页表单；字段虽然部分存在，层级、取消/保存和禁用态已丢失。 |
| 重复路由/逻辑 | `app/routes.tsx` 的 `/todos`、`/share`、`/search`、`/files`、`/settings` | 每个路由都懒加载一套 workspace，和 Home 内摘要/弹窗并存。 |

## 2. 目标信息架构：一个 Home 工作台、多个 surface

### 2.1 唯一产品入口

登录后的日常工作只保留一个规范入口：`/home/`。

```text
Home 固定壳（20 / 50 / 30）
├─ 左栏：Todo（列表 / 四象限） + Reminder（卡片 / 筛选）
├─ 中栏：Calendar（个人 / 分享 tab、工具栏、筛选浮层）
├─ 右栏：Agent（常驻，不因 overlay 或 tab 切换卸载）
└─ Overlay 层：搜索、设置、文件、分享组、创建/详情/编辑/删除确认、工具选择
```

旧版的文件管理虽具有独立完整工作区，但**从 Home 顶端入口打开时仍覆盖于当前工作台之上**；关闭后回到原来的日期、日历视图、筛选、Agent 会话和输入草稿。

### 2.2 URL 策略与过渡兼容

| 需求 | 新规范 | 过渡处理 |
|---|---|---|
| Home 主状态 | `/home/?date=&view=&groups=&share=` | 保留；只保存可恢复的日历状态。 |
| Overlay | `?surface=search/settings/files/share&dialog=...`，由 React 解析并支持浏览器前进/后退关闭 | 不向服务端提交 UI 状态。 |
| 旧 React 深链接 | `/home/todos`、`/home/files`、`/home/settings`、`/home/share`、`/home/search` | 在 FR-UI-R5 改为客户端重定向到 `/home/?surface=…`；保留一版兼容测试后删除对应全页 route 组件入口。 |
| 公开页面 | `/help/`、`/about/`、`/files/` 之外的公共/认证页面 | 不强行迁入 Home；从顶端菜单用完整页面跳转。 |

这不是删除功能：`TodoWorkspace`、`FilesWorkspace`、`SettingsWorkspace`、`ShareGroupsWorkspace` 的**业务子组件与 V2 hooks 将被拆出复用**，只删除重复的“全页壳”。

### 2.3 Overlay 分级

| 容器 | 用途 | 旧版对应 |
|---|---|---|
| `CenteredModal` | 创建/详情/编辑日程、待办、提醒；日程组、分享组、设置、工具选择、搜索 | 金色标题栏、居中遮罩、固定底栏、内容内部滚动。 |
| `InlinePopover` | Calendar 筛选、顶部菜单、日程组下拉、附件类型 | 在触发控件附近展开；不改变三栏尺寸。 |
| `FullscreenSurface` | 文件管理（窄屏可全屏）与 Agent 展开聊天 | 从 Home 打开，关闭回到 Home；不使用右侧 Sheet。 |
| `Sheet` | 仅保留给附件预览、Markdown 编辑、窄屏详情等确实需要侧栏语义的情况 | 不再用于本方案列出的业务 modal。 |

## 3. 分阶段实施方案

## FR-UI-R0：基础容器与路由收敛准备

### 实施

1. 新建 `components/ui/centered-modal.tsx`，基于 Radix Dialog：遮罩、金色/主题化标题栏、关闭按钮、`max-height`、内部 ScrollArea、固定 footer slot、焦点回退和 Escape/点击遮罩关闭。
2. 新建 `app/workbench-surface-store.ts`：只管理 `surface`、`dialog`、选中实体、未提交草稿；与 URL 双向同步，但不保存 Planner 数据。
3. 把现有 `Sheet` 使用点分类迁移；先迁移日程、待办、提醒、日程组、Agent ToolPicker、搜索，文件预览暂不迁移。
4. 将 `app/routes.tsx` 的旧工作区页面标为 compatibility route；先改为打开同一 `surface`，不删 V2 hook。

### 测试与验收

- 单元：modal 关闭回焦、Escape、overlay URL 前进/后退；关闭不触发 API 写入。
- 浏览器：依次打开/关闭 8 类 modal，背景日历日期、左栏滚动位置、Agent 会话/草稿均不变。
- 可访问性：dialog 唯一标题、焦点不泄漏、移动端有可见关闭入口。
- 验收：页面中不再出现“创建日程/提醒/组、工具选择、搜索”右侧 Sheet。

## FR-UI-R1：左栏 Todo 与 Reminder 完整复刻

### Todo

1. 将 `TodoWorkspace` 的 V2 query、mutation、编辑表单拆为 `todo-data.ts` 与 `TodoModal`；`home-sidebar.tsx` 变为真正的 `TodoPane`。
2. 复刻旧版两个视图：默认紧凑列表、2×2 Eisenhower 四象限；两者共享状态、筛选和当前滚动容器。
3. 恢复筛选 popover：重要性多选、日程组多选、完成状态；恢复卡片色条、相对截止时间、完成勾选、详情、编辑、删除、转日程确认。
4. Todo 新建/编辑/详情进入 `CenteredModal`；成功后只失效 Todo query，不重载 Calendar/Agent。

### Reminder

1. 从 `ReminderPanel` 拆出定义编辑与左栏 `ReminderPane`；读取有限窗口内 V2 reminder occurrence，定义/实例动作严格按 `occurrence_ref` 分流。
2. 复刻时间范围、状态、优先级、类型（单次/重复）筛选和紧凑卡片；每条显示时间、重复标识、状态与操作。
3. 单次完成/忽略/延后使用 V2 occurrence action；整个系列编辑使用 V2 reminder command。不能向 legacy `/api/reminders/*` 回退。

### 测试与验收

- 每种 Todo/Reminder 筛选单独、组合、重置、刷新恢复；列表/四象限切换不丢筛选。
- 空态、长文本、20+ 项溢出、完成/删除确认、失败错误态。
- 重复提醒：中央 Calendar 与左栏显示同一限定窗口 occurrence；编辑/动作后两者同步刷新。
- 截图对照审计 024–036、085–089、193。

## FR-UI-R2：Calendar toolbar、筛选与分享 tab 复刻

### 实施

1. 把 `group-filter-list`、重复/DDL/提醒控制移入“筛选”按钮的 `InlinePopover`；按旧版分组为四象限、DDL、重复、提醒、个人组、分享成员，提供应用与重置。
2. 日历顶部仅保留高频按钮：创建日程、日程组管理、课表导入、筛选、今天/翻页、月/周/2日/list。
3. 将 `planner-scope-tabs` 改为横向紧凑 button tab：`我的日程` + 分享组色点；不得纵向拉高工作区。`管理分享组` 放在 tab 末端图标。
4. 为每次切换增加显式 `activeScope` 与 query key；个人 scope 只读个人 occurrence，分享 scope 只读 `/api/v2/share-groups/<id>/occurrences/`。切换时取消旧请求、展示局部 loading，禁止复用个人数据为共享数据。
5. 若 V2 共享 endpoint 返回空，展示该组空态而非回落个人日程；403/404 展示权限/群组错误并保留上一个有效 tab。

### 测试与验收

- 个人、每一个真实分享组、无权限组、空组；切换后检查请求 URL、事件数量/所有者只读状态与颜色。
- 对比截图 001、006–008、090–091、150、193；日历主体在 1366×900 下占中栏主要高度。
- 拖拽选择、普通移动、重复实例 `single/future/all` 不被 filter/tab 重置。

## FR-UI-R3：顶部灵动岛与全局搜索复刻

### 实施

1. 将 header 重组为品牌左侧 + 居中 `TopIsland`；TopIsland 默认显示搜索触发、设置/更多触发，展开后以旧版圆角胶囊承载搜索或四项菜单。
2. 顶部菜单固定为：文件管理、设置、帮助、退出；点击文件/设置不导航到重复 workspace，而打开 `surface`。
3. 搜索用中心/原位浮层而非 Sheet：关键词、类型、个人日程组、分享组、时间范围四类控制；结果列表限制高度、键盘上下/Enter/Escape、清除与点击外关闭。
4. 搜索结果跳转到同一 Home 的日期/视图/详情 dialog；不替换整个三栏壳。

### 测试与验收

- 截图 037–044、097、151、153；桌面和 390px 断点。
- 搜索空态、加载、错误、组合筛选、键盘、关闭后 Home 状态恢复。
- 菜单中“退出”必须显示确认；帮助使用常规完整页导航。

## FR-UI-R4：分享组管理和文件管理复刻

### 分享组

1. `ShareGroupsWorkspace` 拆为 `ShareGroupManagerModal`：我的群组/创建/加入三个 tab；卡片显示色点、角色、成员数、创建时间、复制 ID、详情、编辑/删除或退出。
2. 群组元数据继续使用当前群组管理端点；日程读取只走 V2 shared occurrences。创建/加入/退出/删除成功时失效 `share-groups`、scope tabs 和当前投影。

### 文件

1. 保留 `FilesWorkspace` 的 API/hook，替换显示壳为 `FileManagerSurface`：独立标题栏（返回 Home、配额、主题）、左树、右侧面包屑/工具条、搜索/网格列表切换、文件行/卡片、解析状态。
2. 统一响应式：桌面树 + 内容并列；窄屏树收进 popover，不允许文字重叠。
3. 保留上传、拖入、URL 上传、新建目录、预览/Markdown、下载、重命名、移动、删除和附件稳定 ID；所有确认继续用应用内 modal。

### 测试与验收

- 分享组 owner/member 两种权限、创建/加入错误、复制 ID、详情成员列表。
- 文件根/子目录、长文件名、0/大量文件、网格/列表、搜索、拖入、移动、Markdown、图片、失败/配额。
- 截图 058–064、073–074、157、173。

## FR-UI-R5：设置 modal 与重复路由删除

### 实施

1. 将 `SettingsWorkspace` 重构为中心 `UserSettingsModal`：基本设置、日程偏好、显示偏好、提醒设置、AI 设置、我的六 tab；内部滚动，固定“取消/保存”底栏。
2. 显示偏好保留 13 个主题、即时预览、系统主题监听、金色主题开关与明确 disabled 的“即将推出”项；取消恢复打开前快照且不写后端。
3. AI 子层保留模型、对话风格、工作流、上下文、Token、Skills；各自保存操作保留明确反馈。
4. compatibility route 全部重定向到 Home surface；移除全页 `TodoWorkspace`/`ShareGroupsWorkspace`/`FilesWorkspace`/`SettingsWorkspace` 的路由渲染，只保留其拆出的业务组件。

### 测试与验收

- 各 tab 打开/切换/关闭/取消/保存；主题切换后 Calendar、Agent、modal、表单、滚动条都同步变化，刷新后按服务器偏好恢复。
- 直接访问旧深链接应无白屏且只打开正确 surface；关闭后 URL 回到 `/home/` 并恢复工作台状态。
- 对比截图 045–057、155–156、181–192。

## 4. API、数据与性能约束

- 本方案不新增 legacy Planner 调用；所有 Event/Todo/Reminder/Group 查询与写入保持 V2、有限 range、`expected_version` 和重复 `occurrence_ref` 约束。
- 所有 overlay 的打开/关闭都是本地 UI 状态，不能造成 API 写入；成功 mutation 后只失效对应 React Query key。
- 分享组 metadata 与 V2 occurrence 查询分离缓存，query key 必须包含 `shareGroupId/from/to`，避免个人事件残留到群组 tab。
- Agent 不得因 surface 切换卸载；WebSocket、会话、附件草稿、回滚资格始终由既有服务端会话决定。
- 使用 CSS grid/minmax、容器内滚动和 `overflow-wrap:anywhere` 处理文件名/卡片长文本；禁止用全页滚动掩盖布局错误。

## 5. 总体验收门禁

1. 源码门禁：`npm run typecheck`、`npm run lint`、`npm run format:check`、`npm run check:legacy-planner`、`npm run test:unit`、`npm run build`。
2. 后端门禁：`manage.py check`、`manage.py test core.tests.test_frontend_shell agent_service.tests.test_frontend_ws_smoke`、`collectstatic --noinput`。
3. 浏览器矩阵：1366×900、1920×1080、390×844；浅色、深色、中国红、赛博朋克、system；个人日历和每个真实分享组。
4. 真实 Agent 验收：保持同一会话，分别打开/关闭搜索、设置、文件、分享组、事件编辑、工具选择；确认 Agent 保持已连接，草稿/附件/回滚按钮不丢失。
5. 截图验收：为每个 R 阶段新增“旧版截图 → React 截图 → 差异结论”三列，并回填审计台账；未具备截图、交互、错误/空态证据的条目不得标记完成。

## 6. 实施顺序与停止条件

严格顺序：R0 → R1 → R2 → R3 → R4 → R5。每个阶段完成后先执行该阶段测试和截图对照，再进入下一阶段；不得在仍有双全页 workspace、业务 modal 侧拉、个人数据泄漏到分享 tab、或文件文字重叠时宣布 React 入口达到复刻验收。

## 7. 实施结果（2026-07-15）

| 阶段 | 完成结果 | 关键验收证据 |
|---|---|---|
| R0 | 新增 `CenteredModal`、`FullscreenSurface`、workbench surface store；日程、提醒、日程组、详情、Todo、Agent ToolPicker 和搜索不再使用业务侧拉 Sheet。 | 模态 Escape、焦点恢复和状态 store 单测通过；浏览器测得弹框水平/垂直居中，关闭后 Agent 仍连接。 |
| R1 | Home 左栏已具备 Todo 列表/四象限、状态/重要性筛选、卡片动作和中央编辑框；Reminder 已具备时间/重复筛选、实例完成/忽略/延后及系列编辑。 | MoMoJee 真实数据加载 43 个 Todo 卡片；左栏创建 Todo、Reminder 均打开唯一中央 dialog；未执行破坏性写入。 |
| R2 | 日历筛选收进 popover；分享组成为紧凑 tab；个人与共享 projection 完全互斥，共享 scope 只请求 shared occurrence 和组元数据。 | 新增共享隔离回归测试；浏览器切换 Home 分享组后 URL、pressed tab 和 occurrence 数量独立；筛选前后 FullCalendar 高度一致。 |
| R3 | 顶部入口收敛成灵动岛；搜索具备类型、个人组、分享组和时间范围，并支持键盘选择与同一 Home 定位。 | 搜索打开 `surface=search`，关闭后 URL、Agent、Home 均保持；390px 顶栏无横向溢出。 |
| R4 | 分享组管理进入中央 modal，支持创建/加入、复制 ID、查看、退出/删除；文件管理改为全屏 surface，并保留树、面包屑、搜索、网格/列表及既有文件动作。 | MoMoJee 读取 4 个真实分享组；文件 surface 读取 1 个目录树和 5 个卡片，双栏布局无文字重叠。 |
| R5 | 设置改为六 tab 中央 modal，主题即时预览、取消恢复快照；旧 `/todos|share|search|files|settings` 只做 compatibility redirect。 | 13 主题选项可用；实测 light → china-red → 取消恢复 light；五个旧深链接均回到 Home/正确 surface，无白屏。 |

完整命令、测试数字、浏览器矩阵和已知非阻断项记录于 `docs/ChangeLogs/20260715-1.md`。

## 8. 布局契约加固（2026-07-17）

R0–R5 完成后，分享组管理在特定窗口宽度暴露出“内容逐字竖排”的系统性缺陷。根因不是 React，而是中央弹窗、业务卡片和全局 CSS 之间没有明确的收缩契约：卡片使用 `auto / 1fr / auto`，操作区先占据固有宽度，内容列可被压缩到单字宽度；同时多个业务 surface 依赖同一份全局选择器，后加载规则可能覆盖先前响应式规则。

本次补充以下强制约束：

1. `CenteredModal`、分享组、设置、文件、搜索和 Planner 各自使用 CSS Module，避免跨模块选择器碰撞。
2. 所有可收缩内容轨道使用 `minmax(0, 1fr)`，结构容器及其关键子项显式 `min-width: 0`；操作区不得与正文竞争同一行的剩余宽度。
3. 分享组卡片改为命名网格区域：色点和正文位于首行，操作区独占整行；窄卡片由 container query 切换为 2 列或 1 列按钮。
4. 页面根边界统一处理长文本、表单和媒体最大宽度；Planner 的 FullCalendar 工具栏在窄容器中堆叠并允许按钮换行。
5. 新增 `layout-contracts.spec.ts`，在 1440、760、390 三档视口断言正文可读宽度、操作区宽度及页面/卡片无横向溢出，并覆盖设置、搜索和文件 surface。
6. 开发环境的 Daphne ASGI 入口在 `DEBUG` 下使用 `ASGIStaticFilesHandler`，使 React 静态资源和 `/ws/agent/` 可由同一开发服务器验收；生产 `DEBUG=False` 时仍由 nginx 提供静态资源。

详细结果见 `docs/前端重构验收报告/FR-UI-布局契约修复验收报告.md`。
