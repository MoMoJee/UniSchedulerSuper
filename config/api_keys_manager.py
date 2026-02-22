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
from logger import logger
from typing import Optional, Dict, Any
from pathlib import Path
from functools import lru_cache

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
        # 优先从 mcp_services 读取
        config = cls.get_mcp_service_config('amap')
        if not config:
            # 向后兼容：从 map_services 读取
            config = cls.get_map_service_config('amap')
        
        if not config:
            return ''
        
        base_url = config.get('mcp_url', 'https://mcp.amap.com/sse')
        api_key = config.get('api_key', '')
        
        if api_key:
            # 高德地图使用 key 参数
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
    
    # ==================== MCP 服务相关 ====================
    
    @classmethod
    def get_mcp_service_config(cls, service_name: str) -> Optional[Dict[str, Any]]:
        """
        获取 MCP 服务配置
        
        Args:
            service_name: 服务名称，如 '12306', 'amap'
        """
        config = cls._load_config()
        mcp_services = config.get('mcp_services', {})
        service_config = mcp_services.get(service_name, {})
        
        if not service_config or not service_config.get('enabled', False):
            return None
        
        return service_config
    
    @classmethod
    def get_12306_mcp_url(cls) -> str:
        """获取 12306 MCP 服务 URL"""
        config = cls.get_mcp_service_config('12306')
        if not config:
            return ''
        
        return config.get('mcp_url', 'http://localhost:8001/mcp')
    
    @classmethod
    def get_all_mcp_services(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有启用的 MCP 服务配置"""
        config = cls._load_config()
        mcp_services = config.get('mcp_services', {})
        
        # 过滤出启用的服务（排除以 _ 开头的注释字段）
        enabled_services = {
            name: service_config
            for name, service_config in mcp_services.items()
            if not name.startswith('_') and service_config.get('enabled', False)
        }
        
        return enabled_services
    
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
    
    # ==================== OCR 服务相关 ====================

    @classmethod
    def get_ocr_service_config(cls, provider: str) -> Optional[Dict[str, Any]]:
        """
        获取 OCR 服务的完整配置
        
        Args:
            provider: 提供商名称，如 'baidu', 'aliyun', 'tesseract', 'easyocr'
        
        Returns:
            配置字典，未找到或未启用返回 None
        """
        config = cls._load_config()
        ocr_config = config.get('ocr_services', {}).get(provider, {})
        
        if not ocr_config or not ocr_config.get('enabled', False):
            return None
        
        # 环境变量覆盖（百度 OCR）
        if provider == 'baidu':
            result = ocr_config.copy()
            if os.environ.get('BAIDU_OCR_API_KEY'):
                result['api_key'] = os.environ['BAIDU_OCR_API_KEY']
            if os.environ.get('BAIDU_OCR_SECRET_KEY'):
                result['secret_key'] = os.environ['BAIDU_OCR_SECRET_KEY']
            return result
        
        return ocr_config
    
    @classmethod
    def get_ocr_fallback_chain(cls) -> list:
        """
        获取 OCR 降级链（按配置中启用的服务排序）
        
        Returns:
            已启用的 OCR 服务名称列表，如 ['baidu', 'easyocr', 'tesseract']
        """
        # 固定优先级顺序：云端优先，本地兜底
        priority_order = ['baidu', 'aliyun', 'easyocr', 'tesseract']
        config = cls._load_config()
        ocr_services = config.get('ocr_services', {})
        
        chain = []
        for provider in priority_order:
            svc = ocr_services.get(provider, {})
            if isinstance(svc, dict) and svc.get('enabled', False):
                chain.append(provider)
        
        return chain

    # ==================== 文档解析服务相关 ====================

    @classmethod
    def get_document_service_config(cls, provider: str) -> Optional[Dict[str, Any]]:
        """
        获取文档解析服务的完整配置

        Args:
            provider: 提供商名称，目前支持 'baidu'

        Returns:
            配置字典，未找到或未启用返回 None
        """
        config = cls._load_config()
        svc = config.get('document_services', {}).get(provider, {})

        if not svc or not svc.get('enabled', False):
            return None

        # 环境变量覆盖（百度）
        if provider == 'baidu':
            result = svc.copy()
            if os.environ.get('BAIDU_DOC_API_KEY'):
                result['api_key'] = os.environ['BAIDU_DOC_API_KEY']
            if os.environ.get('BAIDU_DOC_SECRET_KEY'):
                result['secret_key'] = os.environ['BAIDU_DOC_SECRET_KEY']
            return result

        return svc.copy()

    @classmethod
    def get_document_fallback_chain(cls) -> list:
        """
        获取文档解析降级链

        Returns:
            已启用的文档解析服务名称列表，如 ['baidu']；为空时仅用本地解析器
        """
        priority_order = ['baidu']
        config = cls._load_config()
        doc_services = config.get('document_services', {})

        chain = []
        for provider in priority_order:
            svc = doc_services.get(provider, {})
            if isinstance(svc, dict) and svc.get('enabled', False):
                chain.append(provider)

        return chain

    # ==================== 语音识别服务相关 ====================

    @classmethod
    def get_speech_service_config(cls, provider: str) -> Optional[Dict[str, Any]]:
        """
        获取语音识别服务的完整配置

        Args:
            provider: 提供商名称，目前支持 'baidu'

        Returns:
            配置字典，未找到或未启用返回 None
        """
        config = cls._load_config()
        svc = config.get('speech_services', {}).get(provider, {})

        if not svc or not svc.get('enabled', False):
            return None

        if provider == 'baidu':
            result = svc.copy()
            if os.environ.get('BAIDU_SPEECH_API_KEY'):
                result['api_key'] = os.environ['BAIDU_SPEECH_API_KEY']
            if os.environ.get('BAIDU_SPEECH_SECRET_KEY'):
                result['secret_key'] = os.environ['BAIDU_SPEECH_SECRET_KEY']
            return result

        return svc.copy()

    @classmethod
    def get_speech_fallback_chain(cls) -> list:
        """
        获取语音识别降级链。

        优先级固定：baidu（云端） → faster_whisper（本地轻量级）

        Returns:
            已启用的服务名称列表，如 ['baidu', 'faster_whisper']
        """
        priority_order = ['baidu', 'faster_whisper']
        config = cls._load_config()
        speech_services = config.get('speech_services', {})

        chain = []
        for provider in priority_order:
            svc = speech_services.get(provider, {})
            if isinstance(svc, dict) and svc.get('enabled', False):
                chain.append(provider)

        # 保证至少有本地兜底（即使配置文件中没有 faster_whisper 条目）
        if not chain:
            chain = ['faster_whisper']

        return chain

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
    
    # ==================== 系统模型配置（从统一配置读取） ====================
    
    @classmethod
    def get_system_models(cls) -> Dict[str, Dict[str, Any]]:
        """
        获取所有系统提供的模型配置
        
        Returns:
            模型字典 {model_id: model_config}
        """
        config = cls._load_config()
        system_models = config.get('system_models', {})
        
        # 过滤掉以 _ 开头的描述字段，只保留已启用的模型
        result = {}
        for model_id, model_config in system_models.items():
            if model_id.startswith('_'):
                continue
            if model_config.get('enabled', True):
                result[model_id] = model_config.copy()
        
        return result
    
    @classmethod
    def get_system_model_config(cls, model_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定系统模型的完整配置
        
        Args:
            model_id: 模型 ID，如 'system_deepseek'
        
        Returns:
            模型配置字典，未找到返回 None
        """
        system_models = cls.get_system_models()
        return system_models.get(model_id)
    
    @classmethod
    def get_monthly_credit(cls) -> float:
        """获取每月抵用金额度 (CNY)"""
        config = cls._load_config()
        billing = config.get('billing', {})
        return billing.get('monthly_credit', 5.0)


# ==================== 系统模型成本配置（兼容旧代码，从新配置读取） ====================

def _get_system_model_costs() -> Dict[str, Dict[str, Any]]:
    """
    动态获取系统模型成本配置
    
    Returns:
        包含所有系统模型成本配置的字典
    """
    system_models = APIKeyManager.get_system_models()
    costs = {}
    for model_id, config in system_models.items():
        costs[model_id] = {
            "name": config.get('name', model_id),
            "cost_per_1k_input": config.get('cost_per_1k_input', 0),
            "cost_per_1k_output": config.get('cost_per_1k_output', 0),
        }
    return costs


# 兼容旧代码：SYSTEM_MODEL_COSTS 现在从配置文件动态加载
# 注意：这是一个运行时计算的值，不是静态常量
def get_system_model_costs() -> Dict[str, Dict[str, Any]]:
    """获取系统模型成本配置（动态从 api_keys.json 加载）"""
    return _get_system_model_costs()


# 每月默认抵用金 (CNY) - 从配置文件读取
def get_default_monthly_credit() -> float:
    """获取每月默认抵用金额度"""
    return APIKeyManager.get_monthly_credit()


# 兼容旧代码的常量（已弃用，请使用函数版本）
SYSTEM_MODEL_COSTS = property(lambda self: _get_system_model_costs())
DEFAULT_MONTHLY_CREDIT = 5.0  # 保留作为默认值，实际使用 get_default_monthly_credit()


def get_model_cost_config(model_id: str) -> Optional[Dict[str, Any]]:
    """
    获取模型的成本配置
    
    Args:
        model_id: 模型 ID，如 'system_deepseek' 或用户自定义模型 ID
    
    Returns:
        包含 cost_per_1k_input, cost_per_1k_output 的配置字典
        如果是系统模型，返回预定义配置
        如果是自定义模型，需要从用户配置中获取（由调用方处理）
        未找到返回 None
    """
    # 优先从新配置读取
    model_config = APIKeyManager.get_system_model_config(model_id)
    if model_config:
        return {
            "name": model_config.get('name', model_id),
            "cost_per_1k_input": model_config.get('cost_per_1k_input', 0),
            "cost_per_1k_output": model_config.get('cost_per_1k_output', 0),
        }
    return None


def is_system_model(model_id: str) -> bool:
    """判断是否为系统提供的模型"""
    if model_id.startswith('system_'):
        # 检查是否确实存在于配置中
        return APIKeyManager.get_system_model_config(model_id) is not None
    return False


def calculate_cost(input_tokens: int, output_tokens: int, cost_config: Dict) -> float:
    """
    计算成本 (CNY)
    
    Args:
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        cost_config: 包含 cost_per_1k_input, cost_per_1k_output 的配置
    
    Returns:
        成本 (CNY)
    """
    cost_input = cost_config.get('cost_per_1k_input', 0)
    cost_output = cost_config.get('cost_per_1k_output', 0)
    return (input_tokens * cost_input + output_tokens * cost_output) / 1000


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
