# 腾讯云SMTP连接问题排查

## 错误信息
```
SMTP错误: Connection unexpectedly closed
```

## 问题原因

腾讯云邮件服务有多种SMTP服务器地址，需要根据你的具体服务类型选择正确的服务器。

---

## 解决方案：尝试不同的SMTP服务器

### 方案1：腾讯企业邮箱（最常用）✅
```json
{
  "smtp_host": "smtp.exmail.qq.com",
  "smtp_port": 465,
  "smtp_use_ssl": true
}
```

### 方案2：腾讯云邮件推送（SES）
```json
{
  "smtp_host": "smtp.qcloudmail.com",
  "smtp_port": 465,
  "smtp_use_ssl": true
}
```

### 方案3：使用TLS而非SSL
```json
{
  "smtp_host": "smtp.exmail.qq.com",
  "smtp_port": 587,
  "smtp_use_ssl": false
}
```

### 方案4：普通QQ邮箱（如果用的是QQ邮箱）
```json
{
  "smtp_host": "smtp.qq.com",
  "smtp_port": 465,
  "smtp_use_ssl": true
}
```

---

## 已应用的修复

### 1. 更新SMTP服务器 ✅
已将 `smtp.qcloudmail.com` 改为 `smtp.exmail.qq.com`（腾讯企业邮箱）

### 2. 添加超时设置 ✅
添加了30秒连接超时，避免长时间挂起

---

## 如何确定你的邮件服务类型

### 腾讯企业邮箱
- 如果你购买的是"腾讯企业邮箱"
- 域名配置在企业邮箱管理后台
- 使用：`smtp.exmail.qq.com`

### 腾讯云邮件推送（SES）
- 如果你在腾讯云控制台使用"邮件推送"产品
- 需要API接口调用
- SMTP可能需要特殊配置

### 普通QQ邮箱
- 如果你使用 `xxx@qq.com` 作为发件地址
- 使用：`smtp.qq.com`
- 需要开启SMTP服务并获取授权码

---

## 测试步骤

### 1. 重启Django服务
```bash
# 停止服务（Ctrl+C）
python manage.py runserver
```

### 2. 测试邮件发送
访问找回密码页面，输入邮箱测试

### 3. 如果仍然失败，逐个尝试以下配置

**配置A - 企业邮箱SSL**：
```json
{
  "smtp_host": "smtp.exmail.qq.com",
  "smtp_port": 465,
  "smtp_use_ssl": true
}
```

**配置B - 企业邮箱TLS**：
```json
{
  "smtp_host": "smtp.exmail.qq.com",
  "smtp_port": 587,
  "smtp_use_ssl": false
}
```

**配置C - QQ邮箱**：
```json
{
  "smtp_host": "smtp.qq.com",
  "smtp_port": 465,
  "smtp_use_ssl": true
}
```

**配置D - QQ邮箱TLS**：
```json
{
  "smtp_host": "smtp.qq.com",
  "smtp_port": 587,
  "smtp_use_ssl": false
}
```

---

## 使用Python直接测试SMTP连接

创建测试脚本 `test_smtp.py`：

```python
import smtplib
from email.mime.text import MIMEText

# 测试配置
configs = [
    {"host": "smtp.exmail.qq.com", "port": 465, "ssl": True, "name": "企业邮箱SSL"},
    {"host": "smtp.exmail.qq.com", "port": 587, "ssl": False, "name": "企业邮箱TLS"},
    {"host": "smtp.qq.com", "port": 465, "ssl": True, "name": "QQ邮箱SSL"},
    {"host": "smtp.qq.com", "port": 587, "ssl": False, "name": "QQ邮箱TLS"},
    {"host": "smtp.qcloudmail.com", "port": 465, "ssl": True, "name": "腾讯云SES"},
]

smtp_user = "verify@unischedulersuper.online"
smtp_password = "yzh11621@411314inYZH"

for config in configs:
    try:
        print(f"\n测试 {config['name']}: {config['host']}:{config['port']}")
        
        if config['ssl']:
            server = smtplib.SMTP_SSL(config['host'], config['port'], timeout=10)
        else:
            server = smtplib.SMTP(config['host'], config['port'], timeout=10)
            server.starttls()
        
        server.login(smtp_user, smtp_password)
        server.quit()
        
        print(f"✅ {config['name']} 连接成功！")
        print(f"   使用此配置:")
        print(f"   smtp_host: {config['host']}")
        print(f"   smtp_port: {config['port']}")
        print(f"   smtp_use_ssl: {config['ssl']}")
        break
        
    except Exception as e:
        print(f"❌ {config['name']} 失败: {str(e)}")

print("\n测试完成")
```

运行测试：
```bash
python test_smtp.py
```

---

## 检查腾讯云/企业邮箱设置

### 腾讯企业邮箱
1. 登录管理后台：https://exmail.qq.com/login
2. 检查发信地址是否存在
3. 确认SMTP服务已开启
4. 确认密码正确（可能需要重置）

### 腾讯云邮件推送
1. 登录控制台：https://console.cloud.tencent.com/ses
2. 检查发信域名状态（需要验证通过）
3. 检查发信地址状态
4. 查看SMTP密码（可能与登录密码不同）

---

## 其他可能的问题

### 1. 防火墙阻止
检查服务器防火墙是否阻止SMTP端口（465或587）

### 2. IP白名单
某些邮件服务需要配置IP白名单

### 3. 域名未验证
确保域名 `unischedulersuper.online` 已完成验证

### 4. 密码错误
确认SMTP密码是否正确：
- 企业邮箱：邮箱密码
- QQ邮箱：授权码（非QQ密码）
- 腾讯云SES：SMTP密码

---

## 推荐配置顺序

根据你的域名 `unischedulersuper.online`，推荐按以下顺序尝试：

1. **腾讯企业邮箱SSL**（最可能）✅ 已应用
   ```json
   {"smtp_host": "smtp.exmail.qq.com", "smtp_port": 465, "smtp_use_ssl": true}
   ```

2. **腾讯企业邮箱TLS**
   ```json
   {"smtp_host": "smtp.exmail.qq.com", "smtp_port": 587, "smtp_use_ssl": false}
   ```

3. **腾讯云邮件推送**
   ```json
   {"smtp_host": "smtp.qcloudmail.com", "smtp_port": 465, "smtp_use_ssl": true}
   ```

---

## 快速解决方案

**如果你不确定是哪种服务**，使用上面的测试脚本 `test_smtp.py` 快速找出正确配置！

运行后会自动测试所有可能的配置，并告诉你哪个能用。
