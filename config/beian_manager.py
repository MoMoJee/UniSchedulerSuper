"""
备案信息管理模块
用于读取和管理网站备案信息配置
"""
import json
import os
from pathlib import Path

# 配置文件路径
CONFIG_DIR = Path(__file__).parent
BEIAN_CONFIG_FILE = CONFIG_DIR / "beian.json"
BEIAN_EXAMPLE_FILE = CONFIG_DIR / "beian.example.json"


def get_beian_info():
    """
    获取备案信息配置
    
    返回格式:
    {
        'enabled': bool,  # 是否启用备案信息显示
        'icp_number': str,  # ICP备案号
        'icp_link': str,  # ICP备案链接
        'gongan_number': str,  # 公安备案号（可选）
        'gongan_link': str,  # 公安备案链接（可选）
        'display_text': str  # 自定义显示文本（可选）
    }
    
    如果配置文件不存在或读取失败，返回禁用状态的默认配置
    """
    default_config = {
        'enabled': False,
        'icp_number': '',
        'icp_link': 'https://beian.miit.gov.cn',
        'gongan_number': '',
        'gongan_link': '',
        'display_text': ''
    }
    
    # 如果配置文件不存在，返回默认配置
    if not BEIAN_CONFIG_FILE.exists():
        return default_config
    
    try:
        with open(BEIAN_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        # 合并默认配置，确保所有字段都存在
        result = default_config.copy()
        result.update(config)
        
        return result
        
    except (json.JSONDecodeError, IOError) as e:
        print(f"警告：读取备案配置文件失败: {e}")
        return default_config


def format_beian_html(beian_info):
    """
    根据备案信息生成HTML代码
    
    Args:
        beian_info: get_beian_info()返回的配置字典
        
    Returns:
        str: 格式化的HTML代码，如果未启用则返回空字符串
    """
    if not beian_info or not beian_info.get('enabled', False):
        return ''
    
    html_parts = []
    
    # 如果有自定义显示文本，直接使用
    if beian_info.get('display_text'):
        return beian_info['display_text']
    
    # ICP备案信息
    if beian_info.get('icp_number'):
        icp_link = beian_info.get('icp_link', 'https://beian.miit.gov.cn')
        html_parts.append(
            f'<a href="{icp_link}" target="_blank" rel="noopener noreferrer" '
            f'style="color: inherit; text-decoration: none;">{beian_info["icp_number"]}</a>'
        )
    
    # 公安备案信息（如果有）
    if beian_info.get('gongan_number'):
        gongan_link = beian_info.get('gongan_link', '#')
        html_parts.append(
            f'<a href="{gongan_link}" target="_blank" rel="noopener noreferrer" '
            f'style="color: inherit; text-decoration: none;">{beian_info["gongan_number"]}</a>'
        )
    
    # 用空格分隔多个备案信息
    return ' | '.join(html_parts) if html_parts else ''
