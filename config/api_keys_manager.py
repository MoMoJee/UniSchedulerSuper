"""
API 密钥管理模块

统一管理所有外部服务的 API 密钥，支持：
1. 从配置文件读取
2. 从环境变量读取（优先级更高）
3. 可扩展的服务类型

使用示例：
    from config.api_keys_manager import APIKeyManager
    
    # 获取 LLM 密钥
    deepseek_key = APIKeyManager.get_llm_key('deepseek')
    
    # 获取地图服务密钥
    amap_key = APIKeyManager.get_map_service_key('amap')
    
    # 获取完整配置
    deepseek_config = APIKeyManager.get_llm_config('deepseek')
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)

# 配置文件路径
CONFIG_DIR = Path(__file__).parent
API_KEYS_FILE = CONFIG_DIR / 'api_keys.json'


class APIKeyManager:
    """API 密钥管理器"""
    
    _config: Optional[Dict[str, Any]] = None
    _loaded: bool = False
    
    @classmethod
    def _load_config(cls) -> Dict[str, Any]:
        """加载配置文件"""
        if cls._loaded and cls._config is not None:
            return cls._config
        
        cls._config = {}
        
        if API_KEYS_FILE.exists():
            try:
                with open(API_KEYS_FILE, 'r', encoding='utf-8') as f:
                    cls._config = json.load(f)
                logger.info(f"已加载 API 密钥配置: {API_KEYS_FILE}")
            except Exception as e:
                logger.error(f"加载 API 密钥配置失败: {e}")
        else:
            logger.warning(f"API 密钥配置文件不存在: {API_KEYS_FILE}")
            logger.warning("请复制 api_keys.example.json 为 api_keys.json 并填入实际密钥")
        
        cls._loaded = True
        return cls._config or {}
    
    @classmethod
    def reload_config(cls):
        """重新加载配置"""
        cls._loaded = False
        cls._config = None
        cls._load_config()
    
    # ==================== LLM 相关 ====================
    
    @classmethod
    def get_llm_config(cls, provider: str) -> Optional[Dict[str, Any]]:
        """
        获取 LLM 提供商的完整配置
        
        Args:
            provider: 提供商名称，如 'deepseek', 'moonshot', 'openai'
        
        Returns:
            包含 api_key, base_url, default_model 的配置字典
        """
        config = cls._load_config()
        llm_config = config.get('llm', {}).get(provider, {})
        
        if not llm_config:
            return None
        
        # 环境变量优先级更高
        env_key_name = f"{provider.upper()}_API_KEY"
        env_base_url = f"{provider.upper()}_BASE_URL"
        
        result = llm_config.copy()
        if os.environ.get(env_key_name):
            result['api_key'] = os.environ.get(env_key_name)
        if os.environ.get(env_base_url):
            result['base_url'] = os.environ.get(env_base_url)
        
        return result
    
    @classmethod
    def get_llm_key(cls, provider: str) -> str:
        """
        获取 LLM API 密钥
        
        Args:
            provider: 提供商名称
        
        Returns:
            API 密钥字符串，未找到返回空字符串
        """
        # 先检查环境变量
        env_key_name = f"{provider.upper()}_API_KEY"
        env_key = os.environ.get(env_key_name)
        if env_key:
            return env_key
        
        # 从配置文件读取
        config = cls.get_llm_config(provider)
        return config.get('api_key', '') if config else ''
    
    @classmethod
    def get_llm_base_url(cls, provider: str) -> str:
        """获取 LLM API Base URL"""
        config = cls.get_llm_config(provider)
        return config.get('base_url', '') if config else ''
    
    @classmethod
    def get_default_llm_provider(cls) -> str:
        """获取默认 LLM 提供商"""
        # 优先使用有 API key 的提供商
        for provider in ['deepseek', 'moonshot', 'openai']:
            if cls.get_llm_key(provider):
                return provider
        return 'deepseek'
    
    # ==================== 地图服务相关 ====================
    
    @classmethod
    def get_map_service_config(cls, provider: str) -> Optional[Dict[str, Any]]:
        """
        获取地图服务的完整配置
        
        Args:
            provider: 提供商名称，如 'amap'
        """
        config = cls._load_config()
        map_config = config.get('map_services', {}).get(provider, {})
        
        if not map_config:
            return None
        
        # 环境变量优先
        env_key_name = f"{provider.upper()}_API_KEY"
        result = map_config.copy()
        if os.environ.get(env_key_name):
            result['api_key'] = os.environ.get(env_key_name)
        
        return result
    
    @classmethod
    def get_map_service_key(cls, provider: str) -> str:
        """获取地图服务 API 密钥"""
        env_key_name = f"{provider.upper()}_API_KEY"
        env_key = os.environ.get(env_key_name)
        if env_key:
            return env_key
        
        config = cls.get_map_service_config(provider)
        return config.get('api_key', '') if config else ''
    
    @classmethod
    def get_amap_mcp_url(cls) -> str:
        """获取高德地图 MCP 服务完整 URL（包含 key）"""
        config = cls.get_map_service_config('amap')
        if not config:
            return ''
        
        base_url = config.get('mcp_url', 'https://mcp.amap.com/sse')
        api_key = config.get('api_key', '')
        
        if api_key:
            return f"{base_url}?key={api_key}"
        return base_url
    
    # ==================== 搜索服务相关 ====================
    
    @classmethod
    def get_search_service_config(cls, provider: str) -> Optional[Dict[str, Any]]:
        """
        获取搜索服务的完整配置
        
        Args:
            provider: 提供商名称，如 'tavily', 'serper'
        """
        config = cls._load_config()
        search_config = config.get('search_services', {}).get(provider, {})
        
        if not search_config:
            return None
        
        env_key_name = f"{provider.upper()}_API_KEY"
        result = search_config.copy()
        if os.environ.get(env_key_name):
            result['api_key'] = os.environ.get(env_key_name)
        
        return result
    
    @classmethod
    def get_search_service_key(cls, provider: str) -> str:
        """获取搜索服务 API 密钥"""
        env_key_name = f"{provider.upper()}_API_KEY"
        env_key = os.environ.get(env_key_name)
        if env_key:
            return env_key
        
        config = cls.get_search_service_config(provider)
        return config.get('api_key', '') if config else ''
    
    # ==================== 其他服务 ====================
    
    @classmethod
    def get_other_service_key(cls, service_name: str) -> str:
        """
        获取其他服务的 API 密钥
        
        Args:
            service_name: 服务名称
        """
        # 先检查环境变量
        env_key_name = f"{service_name.upper()}_API_KEY"
        env_key = os.environ.get(env_key_name)
        if env_key:
            return env_key
        
        # 从配置文件读取
        config = cls._load_config()
        other_config = config.get('other_services', {}).get(service_name, {})
        return other_config.get('api_key', '') if other_config else ''
    
    # ==================== 通用方法 ====================
    
    @classmethod
    def get_all_configured_llm_providers(cls) -> list:
        """获取所有已配置（有 API key）的 LLM 提供商"""
        config = cls._load_config()
        llm_configs = config.get('llm', {})
        
        providers = []
        for provider in llm_configs:
            if provider.startswith('_'):
                continue
            if cls.get_llm_key(provider):
                providers.append(provider)
        
        return providers
    
    @classmethod
    def validate_config(cls) -> Dict[str, bool]:
        """
        验证配置完整性
        
        Returns:
            各服务配置状态字典
        """
        result = {}
        
        # 检查 LLM
        for provider in ['deepseek', 'moonshot', 'openai']:
            result[f'llm_{provider}'] = bool(cls.get_llm_key(provider))
        
        # 检查地图服务
        result['map_amap'] = bool(cls.get_map_service_key('amap'))
        
        # 检查搜索服务
        for provider in ['tavily', 'serper']:
            result[f'search_{provider}'] = bool(cls.get_search_service_key(provider))
        
        return result


# 便捷函数
def get_deepseek_key() -> str:
    """获取 DeepSeek API 密钥"""
    return APIKeyManager.get_llm_key('deepseek')


def get_deepseek_base_url() -> str:
    """获取 DeepSeek Base URL"""
    return APIKeyManager.get_llm_base_url('deepseek')


def get_moonshot_key() -> str:
    """获取 Moonshot API 密钥"""
    return APIKeyManager.get_llm_key('moonshot')


def get_openai_key() -> str:
    """获取 OpenAI API 密钥"""
    return APIKeyManager.get_llm_key('openai')


def get_amap_key() -> str:
    """获取高德地图 API 密钥"""
    return APIKeyManager.get_map_service_key('amap')
