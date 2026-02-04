# 基于 API Token 的密码重置功能文档

## 功能概述

除了邮箱验证码方式，用户现在可以使用**用户名 + API Token**的方式快速重置密码。这种方式特别适合：
- API 用户
- 已经生成过 Token 的用户
- 需要快速重置密码的用户

## 实现方案

### API 端点

**POST** `/api/password-reset/token/`

**请求体：**
```json
{
  "username": "用户名",
  "token": "API Token 字符串",
  "new_password": "新密码",
  "confirm_password": "确认新密码"
}
```

**成功响应：**
```json
{
  "message": "密码重置成功，请使用新密码登录"
}
```

**错误响应：**
```json
{
  "error": "错误信息"
}
```

### 验证流程

1. **验证输入完整性**
   - 检查用户名、Token、密码是否都已提供
   - 检查两次密码输入是否一致

2. **验证用户存在性**
   - 根据用户名查找用户
   - 如果用户不存在，返回错误（防止用户枚举，使用相同错误消息）

3. **验证 Token 有效性**
   - 检查 Token 是否存在
   - 检查 Token 是否属于该用户
   - 任何验证失败都返回相同错误消息

4. **验证密码强度**
   - 使用 Django 内置密码验证器
   - 检查：最小长度、相似性、常见密码、纯数字等

5. **重置密码**
   - 使用 `user.set_password()` 设置新密码
   - 保存用户信息
   - 记录日志

## 前端界面

### 选项卡设计

找回密码页面提供两种方式的选项卡：

**1. 邮箱验证码**（默认）
- 三步骤流程
- 适合所有用户

**2. API Token**
- 一步完成
- 需要用户名和 Token

### Token 方式表单

```html
<form id="tokenResetForm">
  <input id="tokenUsername" placeholder="请输入用户名">
  <input id="apiToken" placeholder="请输入您的 API Token">
  <input id="tokenNewPassword" type="password" placeholder="请输入新密码">
  <input id="tokenConfirmPassword" type="password" placeholder="再次输入新密码">
  <button type="submit">重置密码</button>
</form>
```

**用户提示：**
> Token 可以在"我的" → "API Token 管理"中找到

## 安全特性

### ✅ 安全措施

1. **防用户枚举**
   - 用户名不存在和 Token 错误返回相同错误消息
   - "用户名或 Token 错误"

2. **Token 验证严格**
   - 必须同时验证 Token 存在性和所有权
   - Token 必须属于指定用户

3. **密码强度检查**
   - 与注册和修改密码使用相同的验证器
   - 保证一致的安全标准

4. **日志记录**
   - 记录所有密码重置操作
   - 便于安全审计

### ⚠️ 注意事项

1. **Token 不会过期**
   - Token 一直有效直到被删除
   - 用户需要妥善保管 Token

2. **Token 不会因密码修改而失效**
   - 重置密码后 Token 仍然有效
   - 如需撤销访问，用户需手动删除 Token

3. **Token 被删除后无法使用**
   - 如果用户删除了 Token，此方式不可用
   - 需要改用邮箱验证码方式

## 两种方式对比

| 特性 | 邮箱验证码 | API Token |
|------|-----------|-----------|
| **适用范围** | 所有用户 | 已生成 Token 的用户 |
| **前提条件** | 注册邮箱 | 提前生成 Token |
| **步骤数量** | 3步（输入邮箱→验证码→新密码） | 1步（直接重置） |
| **时间限制** | 15分钟 | 无限制 |
| **验证方式** | 验证码（6位数字） | Token（40字符） |
| **安全性** | 需要访问邮箱 | 需要保管 Token |
| **便捷性** | 需要查收邮件 | 直接输入即可 |
| **失败风险** | 验证码过期、邮箱收不到 | Token 被删除 |

## 使用场景

### 📧 推荐使用邮箱验证码：

- 普通 Web 用户
- 首次找回密码
- 没有生成过 Token
- Token 已删除

### 🔑 推荐使用 API Token：

- API 用户/开发者
- 已生成并保存了 Token
- 需要快速重置密码
- 邮箱不可用或未配置

## 代码实现

### 后端 API (`core/views.py`)

```python
@api_view(['POST'])
@permission_classes([])  # 允许未认证用户访问
def reset_password_with_token(request):
    """使用用户名和 API Token 重置密码"""
    # 1. 获取并验证输入
    username = data.get('username', '').strip()
    token_key = data.get('token', '').strip()
    new_password = data.get('new_password', '')
    
    # 2. 验证用户
    user = User.objects.get(username=username)
    
    # 3. 验证 Token
    token = Token.objects.get(key=token_key)
    if token.user != user:
        return Response({'error': '用户名或 Token 错误'})
    
    # 4. 验证密码强度
    validate_password(new_password, user=user)
    
    # 5. 重置密码
    user.set_password(new_password)
    user.save()
    
    return Response({'message': '密码重置成功'})
```

### 前端 JavaScript

```javascript
document.getElementById('tokenResetForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const response = await fetch('/api/password-reset/token/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken
    },
    body: JSON.stringify({
      username: username,
      token: token,
      new_password: newPassword,
      confirm_password: confirmPassword
    })
  });
  
  if (response.ok) {
    showToast('密码重置成功！');
    window.location.href = '/user_login/';
  }
});
```

## 测试验证

### 测试脚本：`test_token_password_reset.py`

测试覆盖：
- ✅ Token 生成和验证
- ✅ 正确的用户名和 Token 组合
- ✅ 错误的 Token 被拒绝
- ✅ 用户名和 Token 不匹配检测
- ✅ 密码重置成功
- ✅ 旧密码失效
- ✅ Token 在密码重置后仍有效

### 测试结果

```
1. 创建测试用户... ✅
2. 生成 API Token... ✅
3. 测试 Token 验证... ✅
4. 测试错误的 Token... ✅
5. 测试用户名和 Token 不匹配... ✅
6. 模拟重置密码... ✅
7. 测试 Token 在密码重置后的状态... ✅
```

## 文件清单

### 新增文件
- `test_token_password_reset.py` - 测试脚本

### 修改文件
- `core/views.py` - 添加 `reset_password_with_token()` 函数
- `core/urls.py` - 添加 `/api/password-reset/token/` 路由
- `core/templates/password_reset.html` - 添加 Token 方式选项卡

## 用户指南

### 如何使用 Token 重置密码

1. **获取 Token**
   - 登录系统
   - 进入"我的" → "API Token 管理"
   - 复制 Token 字符串

2. **重置密码**
   - 访问找回密码页面
   - 切换到"API Token"选项卡
   - 输入：用户名、Token、新密码
   - 点击"重置密码"

3. **使用新密码登录**
   - 密码重置成功后自动跳转到登录页
   - 使用新密码登录

### 常见问题

**Q: Token 在哪里找？**
A: 登录后在"我的" → "API Token 管理"中查看或生成。

**Q: Token 会过期吗？**
A: 不会，Token 一直有效直到手动删除。

**Q: 重置密码后 Token 还能用吗？**
A: 可以，Token 不会因密码修改而失效。

**Q: 如果忘记用户名怎么办？**
A: 使用邮箱验证码方式重置，只需要邮箱地址。

**Q: Token 被删除了怎么办？**
A: 使用邮箱验证码方式重置密码。

## 安全建议

### 对用户

1. **妥善保管 Token**
   - Token 等同于密码
   - 不要在公共场合泄露
   - 定期刷新 Token

2. **及时删除不用的 Token**
   - 在"API Token 管理"中删除
   - 防止滥用

3. **使用强密码**
   - 遵守系统密码要求
   - 不使用常见密码

### 对管理员

1. **监控日志**
   - 定期检查密码重置日志
   - 发现异常及时处理

2. **考虑添加限流**
   - 防止暴力破解
   - 限制失败次数

3. **邮件通知**
   - 密码修改后发送邮件通知
   - 让用户知晓账户变化

## 未来改进方向

1. **Token 过期机制**
   - 添加 Token 有效期
   - 自动清理过期 Token

2. **多因素认证**
   - 结合邮箱验证
   - 提高安全性

3. **Token 使用记录**
   - 记录每个 Token 的使用情况
   - 便于安全审计

4. **限流保护**
   - 防止 Token 暴力破解
   - IP 限制

5. **邮件通知**
   - 密码重置成功后发送邮件
   - 异常登录提醒
