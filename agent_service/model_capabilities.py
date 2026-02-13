"""
模型能力查询模块

封装对模型 supports_vision / supports_multimodal 字段的查询，
供 AttachmentHandler 决定向 AI 发送 base64 还是纯文本。
"""
from typing import Dict, Any

from logger import logger


class ModelCapabilities:
    """查询当前模型的多模态能力"""

    @staticmethod
    def get_capabilities(user) -> Dict[str, Any]:
        """
        返回当前模型的能力描述。

        Returns:
            {
                "model_id": str,
                "model_name": str,
                "supports_vision": bool,
                "supports_multimodal": bool,
                "context_window": int,
            }
        """
        from agent_service.context_optimizer import get_current_model_config

        try:
            model_id, model_config = get_current_model_config(user)
        except Exception as e:
            logger.warning(f"获取模型配置失败，使用默认值: {e}")
            return {
                "model_id": "system_deepseek",
                "model_name": "DeepSeek（系统默认）",
                "supports_vision": False,
                "supports_multimodal": False,
                "context_window": 65536,
            }

        return {
            "model_id": model_id,
            "model_name": model_config.get('name', model_id),
            "supports_vision": model_config.get('supports_vision', False),
            "supports_multimodal": model_config.get('supports_multimodal', False),
            "context_window": model_config.get('context_window', 65536),
        }

    @staticmethod
    def supports_vision(user) -> bool:
        """当前模型是否支持图片识别"""
        return ModelCapabilities.get_capabilities(user).get('supports_vision', False)

    @staticmethod
    def supports_multimodal(user) -> bool:
        """当前模型是否支持多模态（文件上传等）"""
        return ModelCapabilities.get_capabilities(user).get('supports_multimodal', False)
