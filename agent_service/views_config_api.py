"""
Agent Configuration API Views
处理 Agent 模型配置、Token 统计等功能
"""
import json
import logging
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from logger import logger
from core.models import UserData
from agent_service.models import DialogStyle
from agent_service.context_optimizer import (
    get_system_models,
    get_all_models,
    get_current_model_config,
    get_optimization_config,
    update_token_usage,
    get_token_usage_stats,
    SYSTEM_MODELS
)

# 导入加密模块
from config.encryption import SecureKeyStorage


# ==========================================
# UserData 辅助函数
# ==========================================

class MockRequest:
    """模拟 request 对象，用于调用 UserData.get_or_initialize"""
    def __init__(self, user):
        self.user = user


def get_user_data_value(user, key: str, default=None):
    """获取用户数据值的辅助函数"""
    mock_request = MockRequest(user)
    user_data, created, _ = UserData.get_or_initialize(mock_request, new_key=key)
    if user_data:
        return user_data.get_value() if not created else (default if default is not None else {})
    return default if default is not None else {}


def set_user_data_value(user, key: str, value):
    """设置用户数据值的辅助函数"""
    mock_request = MockRequest(user)
    user_data, created, _ = UserData.get_or_initialize(mock_request, new_key=key)
    if user_data:
        user_data.set_value(value)
    return user_data


def get_agent_config_decrypted(user) -> dict:
    """
    获取用户的 agent_config，并解密其中的 API 密钥
    """
    config = get_user_data_value(user, 'agent_config', {
        'current_model_id': 'system_deepseek',
        'custom_models': {}
    })
    return SecureKeyStorage.decrypt_model_config(config, user.id)


def set_agent_config_encrypted(user, config: dict):
    """
    保存用户的 agent_config，并加密其中的 API 密钥
    """
    encrypted_config = SecureKeyStorage.encrypt_model_config(config, user.id)
    return set_user_data_value(user, 'agent_config', encrypted_config)


# ==========================================
# 模型配置 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_model_config(request):
    """
    获取用户的模型配置
    GET /api/agent/model-config/
    
    返回:
    {
        "current_model_id": "system_deepseek",
        "current_model": {...},
        "system_models": {...},
        "custom_models": {...},  # API 密钥已掩码
        "all_models": {...}
    }
    """
    try:
        user = request.user
        
        # 获取当前模型配置
        current_model = get_current_model_config(user)
        
        # 获取所有可用模型
        all_models = get_all_models(user)
        
        # 获取用户自定义模型（解密后）
        agent_config = get_agent_config_decrypted(user)
        custom_models = agent_config.get('custom_models', {})
        current_model_id = agent_config.get('current_model_id', 'system_deepseek')
        
        # 对返回给前端的 custom_models 进行掩码处理（安全考虑）
        masked_custom_models = {}
        for model_id, model_config in custom_models.items():
            masked_config = model_config.copy()
            if 'api_key' in masked_config:
                masked_config['api_key'] = SecureKeyStorage.mask_api_key(masked_config['api_key'])
            masked_custom_models[model_id] = masked_config
        
        return Response({
            "success": True,
            "current_model_id": current_model_id,
            "current_model": current_model,
            "system_models": get_system_models(),
            "custom_models": masked_custom_models,
            "all_models": all_models
        })
        
    except Exception as e:
        logger.error(f"获取模型配置失败: {e}", exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_model_config(request):
    """
    更新用户的模型配置
    POST /api/agent/model-config/update/
    
    Body:
    {
        "current_model_id": "system_deepseek",  # 切换当前模型
        # 或者添加/更新自定义模型
        "add_custom_model": {
            "model_id": "my_gpt4",
            "name": "我的 GPT-4",
            "provider": "openai",
            "api_url": "https://api.openai.com/v1/chat/completions",
            "api_key": "sk-xxx",
            "model_name": "gpt-4",
            "context_window": 128000,
            "cost_per_1k_input": 0.01,
            "cost_per_1k_output": 0.03
        },
        # 或者删除自定义模型
        "delete_custom_model": "my_gpt4"
    }
    """
    try:
        user = request.user
        data = request.data
        
        # 获取当前配置（解密后）
        agent_config = get_agent_config_decrypted(user)
        
        # 切换当前模型
        if 'current_model_id' in data:
            model_id = data['current_model_id']
            all_models = get_all_models(user)
            
            if model_id not in all_models:
                return Response({
                    "success": False,
                    "error": f"模型 {model_id} 不存在"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            agent_config['current_model_id'] = model_id
            logger.info(f"用户 {user.username} 切换模型为 {model_id}")
        
        # 添加/更新自定义模型
        if 'add_custom_model' in data:
            model_data = data['add_custom_model']
            model_id = model_data.get('model_id')
            
            if not model_id:
                return Response({
                    "success": False,
                    "error": "model_id 是必需的"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 不允许覆盖系统模型
            if model_id.startswith('system_'):
                return Response({
                    "success": False,
                    "error": "不能使用 system_ 前缀"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 验证必需字段
            required_fields = ['name', 'api_url', 'api_key', 'model_name']
            for field in required_fields:
                if field not in model_data:
                    return Response({
                        "success": False,
                        "error": f"缺少必需字段: {field}"
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # 保存自定义模型
            custom_models = agent_config.get('custom_models', {})
            custom_models[model_id] = {
                'name': model_data['name'],
                'provider': model_data.get('provider', 'custom'),
                'api_url': model_data['api_url'],
                'api_key': model_data['api_key'],
                'model_name': model_data['model_name'],
                'context_window': model_data.get('context_window', 8192),
                'cost_per_1k_input': model_data.get('cost_per_1k_input', 0),
                'cost_per_1k_output': model_data.get('cost_per_1k_output', 0),
            }
            agent_config['custom_models'] = custom_models
            logger.info(f"用户 {user.username} 添加自定义模型 {model_id}")
        
        # 删除自定义模型
        if 'delete_custom_model' in data:
            model_id = data['delete_custom_model']
            custom_models = agent_config.get('custom_models', {})
            
            if model_id in custom_models:
                del custom_models[model_id]
                agent_config['custom_models'] = custom_models
                
                # 如果删除的是当前模型，切换回系统模型
                if agent_config.get('current_model_id') == model_id:
                    agent_config['current_model_id'] = 'system_deepseek'
                
                logger.info(f"用户 {user.username} 删除自定义模型 {model_id}")
            else:
                return Response({
                    "success": False,
                    "error": f"模型 {model_id} 不存在"
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # 保存配置（自动加密 API 密钥）
        set_agent_config_encrypted(user, agent_config)
        
        # 对返回的配置进行掩码处理
        masked_config = agent_config.copy()
        if 'custom_models' in masked_config:
            masked_models = {}
            for mid, mconfig in masked_config['custom_models'].items():
                mc = mconfig.copy()
                if 'api_key' in mc:
                    mc['api_key'] = SecureKeyStorage.mask_api_key(mc['api_key'])
                masked_models[mid] = mc
            masked_config['custom_models'] = masked_models
        
        return Response({
            "success": True,
            "message": "配置已更新",
            "agent_config": masked_config
        })
        
    except Exception as e:
        logger.error(f"更新模型配置失败: {e}", exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# 优化配置 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_opt_config(request):
    """
    获取用户的优化配置
    GET /api/agent/optimization-config/
    
    返回:
    {
        "enable_context_optimization": true,
        "optimization_config": {...}
    }
    """
    try:
        user = request.user
        
        # 获取 DialogStyle 中的开关
        dialog_style = DialogStyle.get_or_create_default(user)
        enable_optimization = getattr(dialog_style, 'enable_context_optimization', True)
        
        # 获取详细优化配置
        optimization_config = get_optimization_config(user)
        
        return Response({
            "success": True,
            "enable_context_optimization": enable_optimization,
            "optimization_config": optimization_config
        })
        
    except Exception as e:
        logger.error(f"获取优化配置失败: {e}", exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_opt_config(request):
    """
    更新用户的优化配置
    POST /api/agent/optimization-config/update/
    
    Body:
    {
        "enable_context_optimization": true,  # 总开关
        "optimization_config": {
            "target_usage_ratio": 0.6,
            "token_calculation_method": "actual",
            "summary_token_ratio": 0.26,
            "recent_token_ratio": 0.65,
            "enable_summarization": true,
            "summary_trigger_ratio": 0.5,
            "min_messages_before_summary": 20,
            "compress_tool_output": true,
            "tool_output_max_tokens": 200
        }
    }
    """
    try:
        user = request.user
        data = request.data
        
        # 更新 DialogStyle 中的总开关
        if 'enable_context_optimization' in data:
            dialog_style = DialogStyle.get_or_create_default(user)
            dialog_style.enable_context_optimization = data['enable_context_optimization']
            dialog_style.save()
            logger.info(f"用户 {user.username} 更新优化开关为 {data['enable_context_optimization']}")
        
        # 更新详细配置
        if 'optimization_config' in data:
            opt_data = data['optimization_config']
            
            # 获取当前配置
            current_config = get_user_data_value(user, 'agent_optimization_config', {})
            
            # 允许的字段
            allowed_fields = [
                'target_usage_ratio',
                'token_calculation_method',
                'summary_token_ratio',
                'recent_token_ratio',
                'enable_summarization',
                'summary_trigger_ratio',
                'min_messages_before_summary',
                'compress_tool_output',
                'tool_output_max_tokens'
            ]
            
            # 更新允许的字段
            for field in allowed_fields:
                if field in opt_data:
                    current_config[field] = opt_data[field]
            
            # 验证
            if 'target_usage_ratio' in current_config:
                ratio = current_config['target_usage_ratio']
                if not (0.3 <= ratio <= 0.9):
                    return Response({
                        "success": False,
                        "error": "target_usage_ratio 必须在 0.3 到 0.9 之间"
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            if 'token_calculation_method' in current_config:
                method = current_config['token_calculation_method']
                if method not in ['actual', 'tiktoken', 'estimate']:
                    return Response({
                        "success": False,
                        "error": "token_calculation_method 必须是 actual, tiktoken 或 estimate"
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # 保存配置
            set_user_data_value(user, 'agent_optimization_config', current_config)
            logger.info(f"用户 {user.username} 更新优化配置")
        
        return Response({
            "success": True,
            "message": "配置已更新"
        })
        
    except Exception as e:
        logger.error(f"更新优化配置失败: {e}", exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# Token 统计 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_token_stats(request):
    """
    获取用户的 Token 使用统计（新版）
    GET /api/agent/token-usage/
    
    返回:
    {
        "success": true,
        "current_month": "2026-01",
        "monthly_credit": 5.0,      // 本月抵用金 (CNY)
        "monthly_used": 2.35,       // 本月已使用 (CNY，仅系统模型)
        "remaining": 2.65,          // 剩余 (CNY)
        "models": {
            "system_deepseek": {
                "name": "DeepSeek Chat（系统提供）",
                "input_tokens": 12000,
                "output_tokens": 8000,
                "cost": 2.35,
                "is_system": true
            }
        },
        "history": {...}
    }
    """
    try:
        user = request.user
        stats = get_token_usage_stats(user)
        
        return Response({
            "success": True,
            **stats
        })
        
    except Exception as e:
        logger.error(f"获取 Token 统计失败: {e}", exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reset_token_stats(request):
    """
    重置用户的 Token 使用统计（仅重置当月统计，不影响历史记录）
    POST /api/agent/token-usage/reset/
    
    Body:
    {
        "reset_type": "current"  // current: 仅重置当月, all: 清空所有包括历史
    }
    """
    from datetime import datetime, timezone
    from config.api_keys_manager import DEFAULT_MONTHLY_CREDIT
    
    try:
        user = request.user
        data = request.data
        reset_type = data.get('reset_type', 'current')
        
        # 获取当前统计
        token_usage = get_user_data_value(user, 'agent_token_usage', {})
        current_month = datetime.now(timezone.utc).strftime('%Y-%m')
        
        if reset_type == 'all':
            # 完全重置，包括历史
            token_usage = {
                'current_month': current_month,
                'monthly_credit': DEFAULT_MONTHLY_CREDIT,
                'monthly_used': 0.0,
                'models': {},
                'history': {},
                'last_reset': datetime.now(timezone.utc).isoformat()
            }
        elif reset_type == 'current':
            # 仅重置当月数据
            token_usage['monthly_used'] = 0.0
            token_usage['models'] = {}
            token_usage['last_reset'] = datetime.now(timezone.utc).isoformat()
        else:
            return Response({
                "success": False,
                "error": f"无效的 reset_type: {reset_type}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        set_user_data_value(user, 'agent_token_usage', token_usage)
        logger.info(f"用户 {user.username} 重置 Token 统计 (type={reset_type})")
        
        return Response({
            "success": True,
            "message": f"已重置{('当月' if reset_type == 'current' else '所有')}统计"
        })
        
    except Exception as e:
        logger.error(f"重置 Token 统计失败: {e}", exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_quota(request):
    """
    更新用户的 Token 配额
    POST /api/agent/token-usage/quota/
    
    Body:
    {
        "quota": 1000000
    }
    """
    try:
        user = request.user
        data = request.data
        quota = data.get('quota')
        
        if quota is None or not isinstance(quota, (int, float)) or quota < 0:
            return Response({
                "success": False,
                "error": "quota 必须是非负数"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取当前统计
        token_usage = get_user_data_value(user, 'agent_token_usage', {})
        token_usage['quota'] = int(quota)
        
        set_user_data_value(user, 'agent_token_usage', token_usage)
        logger.info(f"用户 {user.username} 更新配额为 {quota}")
        
        return Response({
            "success": True,
            "message": "配额已更新",
            "quota": int(quota)
        })
        
    except Exception as e:
        logger.error(f"更新配额失败: {e}", exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# 综合配置 API（一次性获取所有配置）
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_all_agent_config(request):
    """
    获取用户的所有 Agent 配置
    GET /api/agent/config/
    
    返回所有配置的综合视图
    """
    try:
        user = request.user
        
        # 模型配置
        current_model = get_current_model_config(user)
        all_models = get_all_models(user)
        agent_config = get_user_data_value(user, 'agent_config', {})
        
        # 优化配置
        dialog_style = DialogStyle.get_or_create_default(user)
        enable_optimization = getattr(dialog_style, 'enable_context_optimization', True)
        optimization_config = get_optimization_config(user)
        
        # Token 统计
        token_stats = get_token_usage_stats(user)
        
        return Response({
            "success": True,
            "model": {
                "current_model_id": agent_config.get('current_model_id', 'system_deepseek'),
                "current_model": current_model,
                "system_models": get_system_models(),
                "custom_models": agent_config.get('custom_models', {}),
                "all_models": all_models
            },
            "optimization": {
                "enable_context_optimization": enable_optimization,
                "config": optimization_config
            },
            "token_usage": token_stats
        })
        
    except Exception as e:
        logger.error(f"获取 Agent 配置失败: {e}", exc_info=True)
        return Response({
            "success": False,
            "error": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
