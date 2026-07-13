# 模板与 CDN 规范

> 现行版本：2026-07-13。Planner 页必须加载 `planner-v2-client.js` 并注入由后端序列化的 cohort entrypoints；不得从模板注入 legacy Planner JSON 作为写入回退。

> 描述 Django 模板结构约定与 CDN 双轨加载策略。

---

## 1. 模板基本结构

每个页面模板的 `<head>` 区域应包含以下顺序：

```html
{% load static %}
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>页面标题 - UniSchedulerSuper</title>
    <link rel="icon" type="image/png" href="/static/faction.png">

    <!-- 1. CDN 竞速脚本（必须第一个 include） -->
    {% include '_cdn_init.html' %}

    <!-- 2. CDN CSS（通过 __cdnCSS 加载） -->
    <script>__cdnCSS('bootstrap@5.1.3/dist/css/bootstrap.min.css','bootstrap/5.1.3/css/bootstrap.min.css');</script>
    <script>__cdnCSS('@fortawesome/fontawesome-free@6.0.0/css/all.min.css','font-awesome/6.0.0/css/all.min.css');</script>

    <!-- 3. 项目自定义 CSS（静态文件，带版本号） -->
    <link rel="stylesheet" href="{% static 'css/home-styles.css' %}?v=20251107-011">
</head>
<body>
    ...

    <!-- 4. CDN JS（静态 script 标签 + onerror 降级） -->
    <script src="https://cdn.bootcdn.net/ajax/libs/bootstrap/5.1.3/js/bootstrap.bundle.min.js"
            onerror="var s=document.createElement('script');s.src='https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js';document.head.appendChild(s)"></script>

    <!-- 5. 本地 JS 模块（带版本号） -->
    <script src="{% static 'js/theme-manager.js' %}?v=20251107-002"></script>
    ...

    <!-- 6. 全局变量注入 + 模块初始化 -->
    <script>
        window.CSRF_TOKEN = '{{ csrf_token }}';
    // Planner cohort 数据使用 JSON script 标签注入，供 PlannerV2Client 读取。
        window.eventManager = new EventManager();
    </script>
</body>
</html>
```

---

## 2. CDN 双轨加载策略

### 2.1 工作原理

`_cdn_init.html` 在页面 `<head>` 最顶部执行，负责：

1. **版本检查**：`localStorage['cdn_ver']` 与常量 `VER='3'` 比对，不一致时清除旧偏好，防止历史设置失效
2. **读取偏好**：`localStorage['cdn_pref']` 为 `'cn'`（BootCDN）或 `'intl'`（jsDelivr），默认 `'cn'`
3. **CSS 加载函数**：注册 `window.__cdnCSS(iPath, cPath)` — 创建 `<link>` 标签，3 秒内无响应自动切换备用 CDN
4. **后台竞速**（每小时一次）：`Promise.race()` 让两个 CDN 赛跑，胜者写入 `localStorage['cdn_pref']`

### 2.2 CSS 引入方式

**必须使用 `__cdnCSS()`**，禁止直接写 `<link href="cdn.xxx">`：

```html
<!-- ✅ 正确 -->
<script>__cdnCSS('bootstrap@5.1.3/dist/css/bootstrap.min.css', 'bootstrap/5.1.3/css/bootstrap.min.css');</script>

<!-- ❌ 错误：跳过 CDN 选择逻辑 -->
<link href="https://cdn.bootcdn.net/ajax/libs/bootstrap/5.1.3/css/bootstrap.min.css" rel="stylesheet">
```

参数说明：
- 第 1 个参数：jsDelivr 路径（国际 CDN，相对于 `https://cdn.jsdelivr.net/npm/`）
- 第 2 个参数：BootCDN 路径（国内 CDN，相对于 `https://cdn.bootcdn.net/ajax/libs/`）

### 2.3 JS 引入方式

JS 资源**禁止使用 `document.write`**（Chrome 在慢网络下会静默丢弃跨域 `document.write`），改用静态 `<script src>` + `onerror` 降级：

```html
<!-- ✅ 正确：主 CDN 失败时 onerror 动态插入备用 script -->
<script src="https://cdn.bootcdn.net/ajax/libs/bootstrap/5.1.3/js/bootstrap.bundle.min.js"
        onerror="var s=document.createElement('script');s.src='https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js';document.head.appendChild(s)"></script>

<!-- ❌ 错误：document.write 在慢网下不稳定 -->
<script>
    document.write('<script src="..."><\/script>');
</script>
```

---

## 3. 静态文件版本管理

### 3.1 版本号格式

格式：`?v=YYYYMMDD-NNN`（日期-序号）：
- `YYYYMMDD`：修改日期
- `NNN`：当日第 N 次修改（三位数，如 `001`、`012`）

```html
<link rel="stylesheet" href="{% static 'css/agent-chat.css' %}?v=20251201-001">
<script src="{% static 'js/event-manager.js' %}?v=20260312-002"></script>
```

### 3.2 更新规则

- 每次修改文件内容后，**必须同步更新**对应模板中的版本号
- 若同一天第二次修改，序号递增：`20260312-001` → `20260312-002`

### 3.3 本地加载的第三方库

FullCalendar 等较大的第三方库放在 `core/static/` 下本地加载，不走 CDN：

```html
<script src="{% static 'fullcalendar_index.global.js' %}"></script>
```

---

## 4. 全局变量注入规范

后端数据通过 `<script>` 块注入到 `window` 全局变量，放置在 `</body>` 前：

```html
<script>
    window.CSRF_TOKEN = '{{ csrf_token }}';          // CSRF Token（必须）
</script>
{{ planner_entrypoints|json_script:"planner-entrypoints-data" }}
```

**规则**：
- `window.CSRF_TOKEN` 是同源写请求的必须注入变量。
- Planner 页面应以 `<script id="planner-entrypoints-data" type="application/json">` 注入由后端 JSON 序列化的 entrypoints，并由 `PlannerV2Client` bootstrap 复核；不得注入 `events/todos/reminders` legacy archive 作为事实源。
- 使用 `|safe` 过滤器时必须确保后端已对数据进行 JSON 序列化（`json.dumps` 或 DRF 序列化器输出）
- 不得通过模板注入原始未转义的用户输入（XSS 防护）

---

## 5. 模板组织

```
core/templates/
├── _cdn_init.html          # CDN 初始化片段（所有页面共用）
├── home.html               # 主页面（日历 + Todo + Agent）
├── login.html              # 登录页
├── help.html               # 帮助页
└── ...
```

片段模板（`_`开头）：只通过 `{% include %}` 方式引用，不单独渲染。
