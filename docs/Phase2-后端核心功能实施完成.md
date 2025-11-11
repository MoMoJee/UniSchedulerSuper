# Phase 2: 后端核心功能实施完成 ✅

**完成时间**: 2025-11-11  
**实施人员**: AI Assistant  
**状态**: ✅ 已完成

---

## 📋 完成的任务清单

### ✅ Task 2.1: 创建 views_share_groups.py
- [x] 新建文件 `core/views_share_groups.py`
- [x] 实现 8 个核心函数：
  1. ✅ `create_share_group` - 创建群组
  2. ✅ `get_my_share_groups` - 获取我的群组
  3. ✅ `join_share_group` - 加入群组
  4. ✅ `leave_share_group` - 退出群组
  5. ✅ `delete_share_group` - 删除群组
  6. ✅ `get_share_group_events` - 获取群组日程
  7. ✅ `check_group_update` - 检查更新
  8. ✅ `sync_group_calendar_data` - **同步核心函数**

### ✅ Task 2.2: 修改 views_events.py
- [x] 在 `create_event_impl` 末尾添加同步逻辑
- [x] 在 `bulk_edit_events_impl` 的3个返回点添加同步逻辑
- [x] 在 `update_events_impl` 末尾添加同步逻辑
- [x] 创建辅助函数 `_sync_groups_after_edit`

### ✅ Task 2.3: 配置路由
- [x] 修改 `core/urls.py`，导入 `views_share_groups`
- [x] 添加 7 条新路由

---

## 🛠️ 新建文件

### 1. `core/views_share_groups.py` (598 行)

这是群组协作功能的核心视图文件，包含所有群组管理和数据同步的逻辑。

#### 📌 核心函数详解

##### 1️⃣ create_share_group
```python
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_share_group(request)
```
**功能**: 创建协作群组  
**流程**:
1. 验证群组名称是否为空
2. 生成唯一的 `share_group_id`（格式: `share_group_{12位随机字符}`）
3. 创建 `CollaborativeCalendarGroup` 记录
4. 添加创建者为群主成员（`role='owner'`）
5. 初始化 `GroupCalendarData`（version=0, events_data=[]）

**API 路由**: `POST /api/share-groups/create/`

---

##### 2️⃣ get_my_share_groups
```python
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_share_groups(request)
```
**功能**: 获取用户的所有群组列表（我创建的或我加入的）  
**返回信息**:
- 群组基本信息（ID、名称、颜色、描述）
- 用户在该群组的角色（owner/admin/member）
- 成员数量
- 群主信息

**API 路由**: `GET /api/share-groups/my-groups/`

---

##### 3️⃣ join_share_group
```python
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def join_share_group(request)
```
**功能**: 加入群组（通过群组ID）  
**验证**:
- 检查群组是否存在
- 检查用户是否已经是成员
- 创建 `GroupMembership` 记录（`role='member'`）

**API 路由**: `POST /api/share-groups/join/`

---

##### 4️⃣ leave_share_group
```python
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def leave_share_group(request, share_group_id)
```
**功能**: 退出群组  
**限制**: 群主不能退出（需要先转让群主或删除群组）  
**副作用**: 触发群组数据重新同步，移除该用户分享的日程

**API 路由**: `POST /api/share-groups/{share_group_id}/leave/`

---

##### 5️⃣ delete_share_group
```python
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_share_group(request, share_group_id)
```
**功能**: 删除群组（仅群主可操作）  
**级联删除**:
- `GroupMembership` 记录（所有成员关系）
- `GroupCalendarData` 记录

**API 路由**: `DELETE /api/share-groups/{share_group_id}/delete/`

---

##### 6️⃣ get_share_group_events
```python
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_share_group_events(request, share_group_id)
```
**功能**: 获取群组日程（带版本检测）  
**版本检测逻辑**:
- 前端传递 `?version={local_version}`
- 如果 `group_data.version == local_version`，返回 `no_update`
- 如果版本不同，返回完整的 `events` 数据

**API 路由**: `GET /api/share-groups/{share_group_id}/events/?version=124`

---

##### 7️⃣ check_group_update
```python
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_group_update(request, share_group_id)
```
**功能**: 检查群组是否有更新（轻量级接口）  
**返回**: `{"has_update": true/false, "current_version": 125}`

**API 路由**: `GET /api/share-groups/{share_group_id}/check-update/?version=124`

---

##### 8️⃣ sync_group_calendar_data ⭐ 核心
```python
def sync_group_calendar_data(share_group_ids: List[str], trigger_user=None)
```
**功能**: 同步群组日历数据（最核心的函数）  

**同步流程**:
```
1. 遍历每个群组ID
   ↓
2. 获取群组所有成员
   ↓
3. 遍历每个成员
   ↓
4. 获取成员的 UserData["events"]
   ↓
5. 筛选 shared_to_groups 包含该群组ID的日程
   ↓
6. 添加 owner_id, owner_name, is_readonly, shared_at 字段
   ↓
7. 汇总到 all_shared_events 列表
   ↓
8. 保存到 GroupCalendarData.events_data
   ↓
9. 递增 version 版本号
   ↓
10. 触发前端更新检测
```

**关键特性**:
- 每次同步都是完全重建（不是增量）
- 自动添加只读标记 `is_readonly: true`
- 记录分享者信息（owner_id, owner_name）
- 版本号自动递增

---

## 🔧 修改的文件

### 2. `core/views_events.py` (4 处修改)

#### 修改点1: 文件顶部 - 添加辅助函数
```python
def _sync_groups_after_edit(events: List[Dict], series_id: str, user):
    """编辑事件后同步群组数据的辅助函数"""
```

**功能**:
- 收集受影响的群组ID（包括新增和移除的）
- 调用 `sync_group_calendar_data` 触发同步
- 异常处理，不影响事件编辑的主流程

---

#### 修改点2: create_event_impl - 返回前添加同步
```python
# 新增：如果事件分享到了群组，触发同步
shared_to_groups = data.get('shared_to_groups', [])
if shared_to_groups:
    try:
        from .views_share_groups import sync_group_calendar_data
        sync_group_calendar_data(shared_to_groups, request.user)
        logger.info(f"创建事件后同步到群组: {shared_to_groups}")
    except Exception as e:
        logger.error(f"同步群组数据失败: {str(e)}")
```

**触发时机**: 创建新事件时，如果设置了 `shared_to_groups`

---

#### 修改点3: bulk_edit_events_impl - 三个返回点
```python
# 位置1: single 模式处理完成后
_sync_groups_after_edit(final_events, series_id, request.user)

# 位置2: all 模式处理完成后
_sync_groups_after_edit(events, series_id, request.user)

# 位置3: future/from_time 模式处理完成后
_sync_groups_after_edit(events, series_id, request.user)
```

**触发时机**: 
- 编辑弹窗保存（所有模式）
- 批量删除操作

---

#### 修改点4: update_events_impl - 返回前添加同步
```python
# 新增：同步群组数据
try:
    affected_groups = set()
    
    # 获取当前事件的分享群组
    if updated_event:
        shared_to_groups = data.get('shared_to_groups', [])
        if shared_to_groups:
            affected_groups.update(shared_to_groups)
        
        # 如果是重复事件，检查整个系列
        if is_recurring and series_id and rrule_change_scope in ['all', 'future', 'from_time']:
            for event in events:
                if event.get('series_id') == series_id:
                    event_shared_groups = event.get('shared_to_groups', [])
                    if event_shared_groups:
                        affected_groups.update(event_shared_groups)
    
    # 触发同步
    if affected_groups:
        from .views_share_groups import sync_group_calendar_data
        sync_group_calendar_data(list(affected_groups), request.user)
        logger.info(f"update_events 后同步到群组: {affected_groups}")
        
except Exception as sync_error:
    logger.error(f"同步群组数据失败: {str(sync_error)}")
```

**触发时机**: 
- 拖拽事件（改变时间）
- 快速编辑（通过前端直接调用）

---

### 3. `core/urls.py` (2 处修改)

#### 修改1: 导入新模块
```python
from . import views_share_groups
```

#### 修改2: 添加路由
```python
# ===== 分享群组 API =====
path('api/share-groups/create/', views_share_groups.create_share_group, name='create_share_group'),
path('api/share-groups/my-groups/', views_share_groups.get_my_share_groups, name='get_my_share_groups'),
path('api/share-groups/join/', views_share_groups.join_share_group, name='join_share_group'),
path('api/share-groups/<str:share_group_id>/leave/', views_share_groups.leave_share_group, name='leave_share_group'),
path('api/share-groups/<str:share_group_id>/delete/', views_share_groups.delete_share_group, name='delete_share_group'),
path('api/share-groups/<str:share_group_id>/events/', views_share_groups.get_share_group_events, name='get_share_group_events'),
path('api/share-groups/<str:share_group_id>/check-update/', views_share_groups.check_group_update, name='check_group_update'),
```

---

## 📡 API 接口总览

| 序号 | 方法 | 路由 | 功能 | 认证 |
|------|------|------|------|------|
| 1 | POST | `/api/share-groups/create/` | 创建群组 | ✅ |
| 2 | GET | `/api/share-groups/my-groups/` | 获取我的群组列表 | ✅ |
| 3 | POST | `/api/share-groups/join/` | 加入群组 | ✅ |
| 4 | POST | `/api/share-groups/<id>/leave/` | 退出群组 | ✅ |
| 5 | DELETE | `/api/share-groups/<id>/delete/` | 删除群组 | ✅ |
| 6 | GET | `/api/share-groups/<id>/events/` | 获取群组日程 | ✅ |
| 7 | GET | `/api/share-groups/<id>/check-update/` | 检查更新 | ✅ |

所有接口都需要 Token 认证（`@permission_classes([IsAuthenticated])`）

---

## 🔄 同步机制详解

### 触发同步的场景

1. **创建事件** (`create_event_impl`)
   - 检查 `data.get('shared_to_groups')`
   - 如果非空，触发同步

2. **编辑事件** (`bulk_edit_events_impl`)
   - Single 模式：检查当前事件的 `shared_to_groups`
   - All/Future/From_time 模式：检查整个系列的所有事件

3. **拖拽/快速编辑** (`update_events_impl`)
   - 检查 `data.get('shared_to_groups')`
   - 如果是重复事件且编辑整个系列，检查所有实例

4. **退出群组** (`leave_share_group`)
   - 退出后触发该群组的重新同步
   - 自动移除该用户分享的日程

### 同步的数据流

```
用户A编辑日程
    ↓
添加/修改 shared_to_groups: ["share_group_work"]
    ↓
保存到 UserData["events"]
    ↓
触发 sync_group_calendar_data(["share_group_work"])
    ↓
查询 share_group_work 的所有成员
    ↓
遍历每个成员的 UserData["events"]
    ↓
筛选 shared_to_groups 包含 "share_group_work" 的日程
    ↓
添加 owner_id, owner_name, is_readonly=true
    ↓
汇总到 GroupCalendarData.events_data
    ↓
version += 1 (124 → 125)
    ↓
用户B轮询检测到版本变化
    ↓
重新加载群组日程
```

---

## 🧪 测试建议

### 1️⃣ 测试创建群组
```bash
curl -X POST http://localhost:8000/api/share-groups/create/ \
  -H "Authorization: Token YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "share_group_name": "测试群组",
    "share_group_color": "#ff6b6b",
    "share_group_description": "这是一个测试群组"
  }'
```

### 2️⃣ 测试获取群组列表
```bash
curl http://localhost:8000/api/share-groups/my-groups/ \
  -H "Authorization: Token YOUR_TOKEN"
```

### 3️⃣ 测试分享日程到群组
使用现有的事件编辑接口，添加 `shared_to_groups` 字段：
```bash
curl -X POST http://localhost:8000/api/events/bulk-edit/ \
  -H "Authorization: Token YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "event_123",
    "operation": "edit",
    "edit_scope": "single",
    "shared_to_groups": ["share_group_xxx"]
  }'
```

### 4️⃣ 测试获取群组日程
```bash
curl "http://localhost:8000/api/share-groups/share_group_xxx/events/?version=0" \
  -H "Authorization: Token YOUR_TOKEN"
```

### 5️⃣ 测试版本检测
```bash
curl "http://localhost:8000/api/share-groups/share_group_xxx/check-update/?version=0" \
  -H "Authorization: Token YOUR_TOKEN"
```

---

## ⚠️ 注意事项

### 1. 性能考虑
- `sync_group_calendar_data` 每次都是完全重建，数据量大时可能耗时
- 建议未来优化为增量同步
- 考虑添加缓存机制

### 2. 异常处理
- 所有同步逻辑都用 `try-except` 包裹
- 同步失败**不影响**事件编辑的主流程
- 错误日志记录到 `logger`

### 3. 权限控制
- 所有 API 都需要 Token 认证
- 检查用户是否是群组成员
- 群主权限检查（删除群组、转让群主等）

### 4. 数据一致性
- 使用 Django ORM 事务
- 级联删除已配置（`on_delete=models.CASCADE`）
- 版本号递增保证原子性

---

## 🎯 下一步计划

Phase 2 已完成！接下来进入 **Phase 3: 前端 UI 实现**。

### Phase 3 待完成任务：

#### Step 3.1: 选项卡切换组件 ⏳
- [ ] 修改 `templates/home_new.html`，添加 `.calendar-tabs-container`
- [ ] 新建 `static/css/share-groups.css` 样式文件
- [ ] 实现 JavaScript 切换逻辑

#### Step 3.2: 编辑弹窗修改 ⏳
- [ ] 在编辑日程弹窗中添加"分享到群组"选项
- [ ] 实现群组列表动态加载
- [ ] 保存时收集 `shared_to_groups` 数据

#### Step 3.3: 事件渲染样式 ⏳
- [ ] 添加只读事件样式（灰色背景+锁图标）
- [ ] 添加已分享事件样式（蓝色边框+分享图标）
- [ ] 实现点击只读事件时的提示

#### Step 3.4: 群组管理界面 ⏳
- [ ] 创建群组弹窗
- [ ] 加入群组弹窗
- [ ] 群组成员管理界面

#### Step 3.5: 更新提示 ⏳
- [ ] 实现版本检测轮询（30秒）
- [ ] 显示更新徽章
- [ ] 自动刷新逻辑

---

**Phase 2 完成！后端 API 已全部就绪！** 🎉
