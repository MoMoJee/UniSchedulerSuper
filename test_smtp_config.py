"""
SMTP配置测试工具
快速测试所有可能的SMTP服务器配置，找出正确的连接方式
"""
import smtplib
import sys

# 测试配置列表
configs = [
    {"host": "smtp.exmail.qq.com", "port": 465, "ssl": True, "name": "腾讯企业邮箱(SSL)"},
    {"host": "smtp.exmail.qq.com", "port": 587, "ssl": False, "name": "腾讯企业邮箱(TLS)"},
    {"host": "smtp.qq.com", "port": 465, "ssl": True, "name": "QQ邮箱(SSL)"},
    {"host": "smtp.qq.com", "port": 587, "ssl": False, "name": "QQ邮箱(TLS)"},
    {"host": "smtp.qcloudmail.com", "port": 465, "ssl": True, "name": "腾讯云邮件推送(SSL)"},
    {"host": "smtp.qcloudmail.com", "port": 587, "ssl": False, "name": "腾讯云邮件推送(TLS)"},
]

# 邮箱配置（从config/email.json读取）
smtp_user = "verify@unischedulersuper.online"
smtp_password = "yzh11621@411314inYZH"

print("=" * 70)
print("SMTP配置自动测试工具")
print("=" * 70)
print(f"测试账号: {smtp_user}")
print(f"测试密码: {'*' * len(smtp_password)}")
print("=" * 70)
print()

success_configs = []

for i, config in enumerate(configs, 1):
    print(f"[{i}/{len(configs)}] 测试 {config['name']}")
    print(f"      服务器: {config['host']}:{config['port']}")
    print(f"      加密: {'SSL' if config['ssl'] else 'TLS'}")
    
    try:
        # 创建连接
        if config['ssl']:
            server = smtplib.SMTP_SSL(config['host'], config['port'], timeout=15)
        else:
            server = smtplib.SMTP(config['host'], config['port'], timeout=15)
            server.starttls()
        
        # 尝试登录
        server.login(smtp_user, smtp_password)
        server.quit()
        
        print(f"      结果: ✅ 连接成功！")
        success_configs.append(config)
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"      结果: ❌ 认证失败 - {str(e)}")
        print(f"      提示: 可能是密码错误或账号未开启SMTP服务")
        
    except smtplib.SMTPConnectError as e:
        print(f"      结果: ❌ 连接失败 - {str(e)}")
        
    except ConnectionRefusedError:
        print(f"      结果: ❌ 连接被拒绝 - 服务器可能不存在或端口被封")
        
    except Exception as e:
        print(f"      结果: ❌ 错误 - {str(e)}")
    
    print()

print("=" * 70)
print("测试完成")
print("=" * 70)
print()

if success_configs:
    print("✅ 找到可用配置！")
    print()
    for i, config in enumerate(success_configs, 1):
        print(f"配置方案 {i}: {config['name']}")
        print("请将以下内容复制到 config/email.json:")
        print("-" * 70)
        print("{")
        print('  "enabled": true,')
        print(f'  "smtp_host": "{config["host"]}",')
        print(f'  "smtp_port": {config["port"]},')
        print(f'  "smtp_use_ssl": {str(config["ssl"]).lower()},')
        print(f'  "smtp_user": "{smtp_user}",')
        print(f'  "smtp_password": "{smtp_password}",')
        print(f'  "from_email": "{smtp_user}",')
        print('  "from_name": "UniSchedulerSuper时间管理系统"')
        print("}")
        print("-" * 70)
        print()
else:
    print("❌ 未找到可用配置")
    print()
    print("可能的原因:")
    print("1. SMTP密码错误")
    print("   - QQ邮箱需要授权码，不是登录密码")
    print("   - 企业邮箱需要邮箱密码")
    print("   - 腾讯云SES需要SMTP密码")
    print()
    print("2. 账号未开启SMTP服务")
    print("   - QQ邮箱: 设置 → 账户 → 开启POP3/SMTP")
    print("   - 企业邮箱: 管理后台检查SMTP是否开启")
    print("   - 腾讯云SES: 控制台检查发信地址状态")
    print()
    print("3. 网络或防火墙问题")
    print("   - 检查防火墙是否阻止465/587端口")
    print("   - 尝试使用VPN或更换网络环境")
    print()
    print("4. 邮箱地址配置错误")
    print(f"   - 当前使用: {smtp_user}")
    print("   - 确认该邮箱确实存在且已配置")
    print()

print("=" * 70)
print("提示:")
print("  运行: python test_smtp_config.py")
print("  重启Django后测试: python manage.py runserver")
print("=" * 70)
