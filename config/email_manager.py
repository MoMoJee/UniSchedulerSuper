"""
邮件服务管理模块
用于管理邮件发送配置和发送邮件
"""
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# 配置文件路径
CONFIG_DIR = Path(__file__).parent
EMAIL_CONFIG_FILE = CONFIG_DIR / "email.json"
EMAIL_EXAMPLE_FILE = CONFIG_DIR / "email.example.json"


def get_email_config():
    """
    获取邮件配置
    
    返回格式:
    {
        'enabled': bool,  # 是否启用邮件发送
        'smtp_host': str,  # SMTP服务器地址
        'smtp_port': int,  # SMTP端口
        'smtp_use_ssl': bool,  # 是否使用SSL
        'smtp_user': str,  # SMTP用户名
        'smtp_password': str,  # SMTP密码
        'from_email': str,  # 发件人邮箱
        'from_name': str  # 发件人名称
    }
    
    如果配置文件不存在或读取失败，返回禁用状态的默认配置
    """
    default_config = {
        'enabled': False,
        'smtp_host': '',
        'smtp_port': 465,
        'smtp_use_ssl': True,
        'smtp_user': '',
        'smtp_password': '',
        'from_email': '',
        'from_name': '时间管理大师'
    }
    
    # 如果配置文件不存在，返回默认配置
    if not EMAIL_CONFIG_FILE.exists():
        logger.warning(f"邮件配置文件不存在: {EMAIL_CONFIG_FILE}")
        return default_config
    
    try:
        with open(EMAIL_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        # 合并默认配置，确保所有字段都存在
        result = default_config.copy()
        result.update(config)
        
        return result
        
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"读取邮件配置文件失败: {e}")
        return default_config


def send_email(to_email, subject, html_content, text_content=None):
    """
    发送邮件
    
    Args:
        to_email: 收件人邮箱
        subject: 邮件主题
        html_content: HTML格式的邮件内容
        text_content: 纯文本格式的邮件内容（可选，用于不支持HTML的邮件客户端）
        
    Returns:
        tuple: (success: bool, message: str)
    """
    config = get_email_config()
    
    # 检查是否启用邮件发送
    if not config.get('enabled', False):
        logger.warning("邮件发送功能未启用")
        return False, "邮件发送功能未启用"
    
    # 检查必要配置
    required_fields = ['smtp_host', 'smtp_user', 'smtp_password', 'from_email']
    for field in required_fields:
        if not config.get(field):
            logger.error(f"邮件配置不完整，缺少字段: {field}")
            return False, f"邮件配置不完整，缺少字段: {field}"
    
    try:
        # 创建邮件对象
        msg = MIMEMultipart('alternative')
        msg['From'] = f"{config['from_name']} <{config['from_email']}>"
        msg['To'] = to_email
        msg['Subject'] = str(Header(subject, 'utf-8'))
        
        # 添加纯文本版本（如果提供）
        if text_content:
            text_part = MIMEText(text_content, 'plain', 'utf-8')
            msg.attach(text_part)
        
        # 添加HTML版本
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # 连接SMTP服务器并发送邮件
        if config.get('smtp_use_ssl', True):
            # 使用SSL连接
            server = smtplib.SMTP_SSL(config['smtp_host'], config['smtp_port'], timeout=30)
            server.set_debuglevel(0)
        else:
            # 使用TLS连接
            server = smtplib.SMTP(config['smtp_host'], config['smtp_port'], timeout=30)
            server.starttls()
        
        # 登录
        server.login(config['smtp_user'], config['smtp_password'])
        
        # 发送邮件
        server.sendmail(config['from_email'], to_email, msg.as_string())
        
        # 关闭连接
        server.quit()
        
        logger.info(f"邮件发送成功: {to_email} - {subject}")
        return True, "邮件发送成功"
        
    except smtplib.SMTPAuthenticationError as e:
        error_msg = f"SMTP认证失败: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
    except smtplib.SMTPException as e:
        error_msg = f"SMTP错误: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"发送邮件失败: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def send_verification_code_email(to_email, code, purpose='register'):
    """
    发送验证码邮件
    
    Args:
        to_email: 收件人邮箱
        code: 验证码
        purpose: 用途，'register'表示注册，'reset_password'表示找回密码
        
    Returns:
        tuple: (success: bool, message: str)
    """
    if purpose == 'register':
        subject = "欢迎注册 - 邮箱验证码"
        title = "欢迎注册时间管理大师"
        greeting = "感谢您注册我们的服务！"
        instruction = "请使用以下验证码完成注册："
    else:  # reset_password
        subject = "密码重置 - 验证码"
        title = "密码重置验证"
        greeting = "您正在重置密码。"
        instruction = "请使用以下验证码完成密码重置："
    
    # HTML邮件内容
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{subject}</title>
    </head>
    <body style="margin: 0; padding: 0; font-family: 'Microsoft YaHei', 'Segoe UI', Arial, sans-serif; background-color: #f5f5f5;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f5f5f5; padding: 40px 0;">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                        <!-- Header -->
                        <tr>
                            <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 8px 8px 0 0; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: normal;">{title}</h1>
                            </td>
                        </tr>
                        
                        <!-- Content -->
                        <tr>
                            <td style="padding: 40px 30px;">
                                <p style="margin: 0 0 20px; color: #333333; font-size: 16px; line-height: 1.6;">
                                    {greeting}
                                </p>
                                <p style="margin: 0 0 30px; color: #666666; font-size: 14px; line-height: 1.6;">
                                    {instruction}
                                </p>
                                
                                <!-- Verification Code Box -->
                                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                    <tr>
                                        <td align="center" style="padding: 20px; background-color: #f8f9fa; border-radius: 6px;">
                                            <div style="font-size: 32px; font-weight: bold; color: #667eea; letter-spacing: 8px; font-family: 'Courier New', monospace;">
                                                {code}
                                            </div>
                                        </td>
                                    </tr>
                                </table>
                                
                                <p style="margin: 30px 0 0; color: #999999; font-size: 13px; line-height: 1.6;">
                                    <strong>注意事项：</strong><br>
                                    • 验证码有效期为 <strong>15分钟</strong><br>
                                    • 请勿将验证码泄露给他人<br>
                                    • 如果这不是您本人的操作，请忽略此邮件
                                </p>
                            </td>
                        </tr>
                        
                        <!-- Footer -->
                        <tr>
                            <td style="padding: 20px 30px; background-color: #f8f9fa; border-radius: 0 0 8px 8px; text-align: center;">
                                <p style="margin: 0; color: #999999; font-size: 12px;">
                                    此邮件由系统自动发送，请勿直接回复<br>
                                    © 2026 UniSchedulerSuper. All rights reserved.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    # 纯文本版本（用于不支持HTML的邮件客户端）
    text_content = f"""
{title}

{greeting}

{instruction}

验证码: {code}

注意事项：
• 验证码有效期为 15分钟
• 请勿将验证码泄露给他人
• 如果这不是您本人的操作，请忽略此邮件

此邮件由系统自动发送，请勿直接回复
© 2026 UniSchedulerSuper. All rights reserved.
    """
    
    return send_email(to_email, subject, html_content, text_content)


def test_email_config():
    """
    测试邮件配置是否正确
    
    Returns:
        tuple: (success: bool, message: str)
    """
    config = get_email_config()
    
    if not config.get('enabled', False):
        return False, "邮件发送功能未启用"
    
    # 发送测试邮件到配置的发件邮箱
    test_code = "123456"
    return send_verification_code_email(
        config['from_email'],
        test_code,
        purpose='register'
    )
