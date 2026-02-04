# FullCalendar 主题适配优化文档

## 优化概述

对日历视图的所有界面元素进行主题适配，确保"2日"、"month"、"week"等按钮，以及日期数字、时间标签等文字颜色和风格都与当前主题保持一致。

## 优化内容

### 1. 新增CSS变量（所有13个主题）

为每个主题添加了以下CSS变量：

```css
/* 按钮样式变量 */
--button-bg: #颜色;              /* 按钮背景色 */
--button-text: #颜色;            /* 按钮文字颜色 */
--button-hover-bg: #颜色;        /* 按钮悬停背景色 */
--button-hover-text: #颜色;      /* 按钮悬停文字颜色 */
--bg-hover: #颜色;               /* 悬停时的背景色 */
```

对于渐变主题（dopamine、sunset、ocean、cyberpunk），还添加了：

```css
/* 渐变效果变量 */
--gradient-primary: linear-gradient(...);  /* 主要渐变 */
--gradient-hover: linear-gradient(...);    /* 悬停渐变 */
```

### 2. FullCalendar元素全面主题化

#### 工具栏按钮
- ✅ 所有视图切换按钮（2日、月、周、列表）
- ✅ 今天按钮
- ✅ 前后导航按钮
- ✅ 自定义筛选按钮
- ✅ 激活状态按钮高亮

优化效果：
- 使用 `var(--button-bg)` 和 `var(--button-text)` 适配按钮颜色
- 悬停效果使用 `var(--button-hover-bg)`
- 激活状态使用 `var(--primary)` 主题色
- 添加阴影和过渡动画提升交互体验

#### 日期数字和文字
- ✅ 日期数字颜色：`var(--text-primary)`
- ✅ 星期标题：`var(--text-secondary)`
- ✅ 时间标签：`var(--text-secondary)`
- ✅ 今天的日期：`var(--primary)` 主题色高亮

#### 日历网格和边框
- ✅ 所有网格边框：`var(--border-color)`
- ✅ 列标题背景：`var(--bg-secondary)`
- ✅ 日期单元格背景：`var(--bg-primary)`
- ✅ 今天背景高亮：`var(--fc-today-bg)`

#### 当前时间指示
- ✅ 时间线颜色：`var(--primary)`
- ✅ 时间箭头颜色：`var(--primary)`

#### 列表视图
- ✅ 日期栏背景：`var(--bg-tertiary)`
- ✅ 事件标题：`var(--text-primary)`
- ✅ 悬停效果：`var(--bg-hover)`

#### 更多事件弹出层
- ✅ 弹出层背景：`var(--card-bg)`
- ✅ 弹出层边框：`var(--border-color)`
- ✅ 标题栏背景：`var(--bg-tertiary)`

#### 滚动条
- ✅ 轨道颜色：`var(--scrollbar-track)`
- ✅ 滑块颜色：`var(--scrollbar-thumb)`
- ✅ 悬停颜色：`var(--scrollbar-thumb-hover)`

### 3. 特殊主题的渐变效果

为创意主题（dopamine、sunset、ocean、cyberpunk）添加了特殊的渐变按钮效果：

```css
/* 激活状态的按钮使用渐变 */
.fc .fc-button-active {
    background: var(--gradient-primary) !important;
    box-shadow: 0 4px 12px rgba(var(--primary-rgb), 0.4) !important;
}

/* 悬停时使用渐变悬停效果 */
.fc .fc-button:hover {
    background: var(--gradient-hover) !important;
    box-shadow: 0 6px 16px rgba(var(--primary-rgb), 0.5) !important;
}
```

## CSS类覆盖清单

### 按钮相关
- `.fc .fc-button` - 所有按钮基础样式
- `.fc .fc-button:hover` - 按钮悬停
- `.fc .fc-button:active` - 按钮按下
- `.fc .fc-button:disabled` - 禁用状态
- `.fc .fc-button-active` - 激活状态（当前视图）
- `.fc .fc-button-primary` - 主要按钮

### 文字相关
- `.fc .fc-toolbar-title` - 日历标题
- `.fc .fc-daygrid-day-number` - 日期数字
- `.fc .fc-col-header-cell-cushion` - 列标题（星期）
- `.fc .fc-timegrid-slot-label-cushion` - 时间轴标签
- `.fc .fc-list-event-time` - 列表视图时间
- `.fc .fc-list-event-title` - 列表视图标题

### 容器和背景
- `.fc` - 日历根容器
- `.fc .fc-daygrid-day` - 日期单元格
- `.fc .fc-timegrid-col` - 时间网格列
- `.fc .fc-col-header-cell` - 列标题单元格
- `.fc .fc-scrollgrid` - 滚动网格
- `.fc .fc-popover` - 弹出层

### 特殊状态
- `.fc .fc-day-today` - 今天
- `.fc .fc-day-other` - 非当前月日期
- `.fc .fc-daygrid-more-link` - 更多事件链接
- `.fc .fc-timegrid-now-indicator-line` - 当前时间线
- `.fc .fc-timegrid-now-indicator-arrow` - 当前时间箭头

## 13个主题的按钮配色方案

### 浅色系主题
1. **Light (默认)**: 浅灰背景 + 深色文字
2. **China-red**: 浅红背景 + 深棕文字
3. **Warm-pastel**: 粉白背景 + 灰棕文字
4. **Cool-pastel**: 浅蓝绿背景 + 深青文字
5. **Macaron**: 奶油浅色背景 + 深棕文字
6. **Forest**: 浅绿背景 + 深绿文字
7. **Sunset**: 温暖黄昏背景 + 深棕文字
8. **Ocean**: 天蓝背景 + 深蓝文字
9. **Sakura**: 樱花粉背景 + 深棕文字

### 深色系主题
10. **Dark**: 深灰背景 + 亮灰文字

### 高对比度主题
11. **Dopamine**: 明亮背景 + 深色文字 + 彩虹渐变
12. **Cyberpunk**: 深紫黑背景 + 霓虹蓝文字 + 霓虹渐变

## 交互增强

### 按钮悬停效果
- 添加 `transform: translateY(-1px)` 上浮效果
- 增强阴影深度
- 悬停时边框变为主题色

### 按钮点击效果
- 点击时取消上浮效果
- 减少阴影突显按下感

### 激活状态突出
- 背景使用主题主色
- 文字变为白色（高对比度）
- 添加彩色阴影（创意主题）

## 使用说明

所有优化自动生效，无需额外配置。切换主题时，日历界面会自动适配：

1. 点击右上角设置图标
2. 选择主题标签
3. 选择任意主题
4. 日历自动刷新并应用新主题

## 兼容性说明

- ✅ 所有现代浏览器（Chrome、Firefox、Edge、Safari）
- ✅ 支持深色模式
- ✅ 支持高对比度模式
- ✅ 响应式设计兼容
- ✅ 触摸设备优化

## 技术实现

### 1. CSS变量继承
通过根元素的 `[data-theme="xxx"]` 属性动态切换CSS变量。

### 2. 选择器优先级
使用 `!important` 确保主题样式优先级高于FullCalendar默认样式。

### 3. 渐变背景
使用 `linear-gradient()` 为创意主题添加视觉冲击力。

### 4. 性能优化
- 使用CSS变量减少重复代码
- 利用GPU加速的 `transform` 属性
- 避免使用影响布局的动画属性

## 文件修改

- ✅ `core/static/css/home-styles.css` 
  - 添加了13个主题的按钮CSS变量定义
  - 添加了完整的FullCalendar元素主题适配样式
  - 添加了特殊主题的渐变效果

## 测试建议

1. 切换所有13个主题，检查按钮颜色是否正确
2. 悬停按钮，检查悬停效果是否流畅
3. 点击按钮，检查激活状态是否突出
4. 检查日期数字在所有主题下是否清晰可读
5. 检查今天的日期高亮是否明显
6. 检查渐变主题的按钮渐变效果

## 后续优化方向

- [ ] 添加暗色模式下的特殊调整
- [ ] 为移动端优化按钮尺寸
- [ ] 添加按钮图标的主题适配
- [ ] 支持用户自定义按钮配色
