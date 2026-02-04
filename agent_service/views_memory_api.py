"""
记忆管理 API
提供个人信息、对话风格、工作流规则的 CRUD 操作
"""
import json
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from agent_service.models import UserPersonalInfo, DialogStyle, WorkflowRule
from logger import logger


# ==========================================
# 个人信息 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_personal_info(request):
    """
    获取用户所有个人信息
    GET /api/agent/memory/personal-info/
    """
    user = request.user
    infos = UserPersonalInfo.objects.filter(user=user).order_by('key')
    
    data = [{
        'id': info.id,
        'key': info.key,
        'value': info.value,
        'description': info.description,
        'created_at': info.created_at.isoformat(),
        'updated_at': info.updated_at.isoformat()
    } for info in infos]
    
    return Response({'items': data, 'count': len(data)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_personal_info(request):
    """
    创建个人信息
    POST /api/agent/memory/personal-info/
    Body: {"key": "...", "value": "...", "description": "..."}
    """
    user = request.user
    data = request.data
    
    key = data.get('key', '').strip()
    value = data.get('value', '').strip()
    description = data.get('description', '').strip()
    
    if not key or not value:
        return Response({'error': '键和值不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    
    # 检查是否已存在
    if UserPersonalInfo.objects.filter(user=user, key=key).exists():
        return Response({'error': f'键 "{key}" 已存在'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        info = UserPersonalInfo.objects.create(
            user=user,
            key=key,
            value=value,
            description=description
        )
        return Response({
            'id': info.id,
            'key': info.key,
            'value': info.value,
            'description': info.description,
            'message': '创建成功'
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.exception(f"创建个人信息失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_personal_info(request, pk):
    """
    更新个人信息
    PUT /api/agent/memory/personal-info/<pk>/
    Body: {"key": "...", "value": "...", "description": "..."}
    """
    user = request.user
    data = request.data
    
    try:
        info = UserPersonalInfo.objects.get(id=pk, user=user)
    except UserPersonalInfo.DoesNotExist:
        return Response({'error': '未找到该记录'}, status=status.HTTP_404_NOT_FOUND)
    
    key = data.get('key', info.key).strip()
    value = data.get('value', info.value).strip()
    description = data.get('description', info.description)
    if description:
        description = description.strip()
    
    if not key or not value:
        return Response({'error': '键和值不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    
    # 检查新 key 是否与其他记录冲突
    if key != info.key and UserPersonalInfo.objects.filter(user=user, key=key).exists():
        return Response({'error': f'键 "{key}" 已存在'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        info.key = key
        info.value = value
        info.description = description or ''
        info.save()
        return Response({
            'id': info.id,
            'key': info.key,
            'value': info.value,
            'description': info.description,
            'message': '更新成功'
        })
    except Exception as e:
        logger.exception(f"更新个人信息失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_personal_info(request, pk):
    """
    删除个人信息
    DELETE /api/agent/memory/personal-info/<pk>/
    """
    user = request.user
    
    try:
        info = UserPersonalInfo.objects.get(id=pk, user=user)
        key = info.key
        info.delete()
        return Response({'message': f'已删除 "{key}"'})
    except UserPersonalInfo.DoesNotExist:
        return Response({'error': '未找到该记录'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.exception(f"删除个人信息失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# 对话风格 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dialog_style(request):
    """
    获取用户对话风格配置
    GET /api/agent/memory/dialog-style/
    """
    user = request.user
    style = DialogStyle.get_or_create_default(user)
    
    return Response({
        'id': style.id,
        'tone': style.tone,
        'verbosity': style.verbosity,
        'language': style.language,
        'custom_instructions': style.custom_instructions,
        'content': style.content,
        # 选项列表（包含自定义）
        'tone_choices': style.get_all_tone_choices(),
        'verbosity_choices': style.get_all_verbosity_choices(),
        'language_choices': style.get_all_language_choices(),
        # 自定义选项（用于编辑）
        'custom_tones': style.custom_tones,
        'custom_verbosities': style.custom_verbosities,
        'custom_languages': style.custom_languages,
        'memory_batch_size': style.memory_batch_size,
        'updated_at': style.updated_at.isoformat()
    })


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_dialog_style(request):
    """
    更新对话风格配置
    PUT /api/agent/memory/dialog-style/update/
    Body: {
        "tone": "neutral",
        "verbosity": "normal", 
        "language": "zh-CN",
        "custom_instructions": "...",
        "custom_tones": [...],
        "custom_verbosities": [...],
        "custom_languages": [...],
        "memory_batch_size": 20
    }
    """
    user = request.user
    data = request.data
    
    try:
        style = DialogStyle.get_or_create_default(user)
        
        # 更新基本字段
        if 'tone' in data:
            style.tone = data['tone']
        if 'verbosity' in data:
            style.verbosity = data['verbosity']
        if 'language' in data:
            style.language = data['language']
        if 'custom_instructions' in data:
            style.custom_instructions = data['custom_instructions']
        
        # 更新记忆优化设置
        if 'memory_batch_size' in data:
            try:
                batch_size = int(data['memory_batch_size'])
                if 5 <= batch_size <= 100:
                    style.memory_batch_size = batch_size
            except ValueError:
                pass
        
        # 更新自定义选项
        if 'custom_tones' in data:
            style.custom_tones = data['custom_tones']
        if 'custom_verbosities' in data:
            style.custom_verbosities = data['custom_verbosities']
        if 'custom_languages' in data:
            style.custom_languages = data['custom_languages']
        
        style.save()  # 自动生成 content
        
        return Response({
            'id': style.id,
            'tone': style.tone,
            'verbosity': style.verbosity,
            'language': style.language,
            'custom_instructions': style.custom_instructions,
            'content': style.content,
            'message': '更新成功'
        })
    except Exception as e:
        logger.exception(f"更新对话风格失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reset_dialog_style(request):
    """
    重置对话风格为默认配置
    POST /api/agent/memory/dialog-style/reset/
    """
    user = request.user
    
    try:
        style = DialogStyle.get_or_create_default(user)
        style.tone = 'neutral'
        style.verbosity = 'normal'
        style.language = 'zh-CN'
        style.custom_instructions = ''
        style.custom_tones = []
        style.custom_verbosities = []
        style.custom_languages = []
        style.save()
        
        return Response({
            'id': style.id,
            'tone': style.tone,
            'verbosity': style.verbosity,
            'language': style.language,
            'custom_instructions': style.custom_instructions,
            'content': style.content,
            'message': '已重置为默认配置'
        })
    except Exception as e:
        logger.exception(f"重置对话风格失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==========================================
# 工作流规则 API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_workflow_rules(request):
    """
    获取用户所有工作流规则
    GET /api/agent/memory/workflow-rules/
    """
    user = request.user
    rules = WorkflowRule.objects.filter(user=user).order_by('-is_active', 'name')
    
    data = [{
        'id': rule.id,
        'name': rule.name,
        'trigger': rule.trigger,
        'steps': rule.steps,
        'is_active': rule.is_active,
        'created_at': rule.created_at.isoformat(),
        'updated_at': rule.updated_at.isoformat()
    } for rule in rules]
    
    return Response({'items': data, 'count': len(data)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_workflow_rule(request):
    """
    创建工作流规则
    POST /api/agent/memory/workflow-rules/
    Body: {"name": "...", "trigger": "...", "steps": "...", "is_active": true}
    """
    user = request.user
    data = request.data
    
    name = data.get('name', '').strip()
    trigger = data.get('trigger', '').strip()
    steps = data.get('steps', '').strip()
    is_active = data.get('is_active', True)
    
    if not name:
        return Response({'error': '规则名称不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    
    # 检查是否已存在
    if WorkflowRule.objects.filter(user=user, name=name).exists():
        return Response({'error': f'规则 "{name}" 已存在'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        rule = WorkflowRule.objects.create(
            user=user,
            name=name,
            trigger=trigger,
            steps=steps,
            is_active=is_active
        )
        return Response({
            'id': rule.id,
            'name': rule.name,
            'trigger': rule.trigger,
            'steps': rule.steps,
            'is_active': rule.is_active,
            'message': '创建成功'
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.exception(f"创建工作流规则失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_workflow_rule(request, pk):
    """
    更新工作流规则
    PUT /api/agent/memory/workflow-rules/<pk>/
    Body: {"name": "...", "trigger": "...", "steps": "...", "is_active": true}
    """
    user = request.user
    data = request.data
    
    try:
        rule = WorkflowRule.objects.get(id=pk, user=user)
    except WorkflowRule.DoesNotExist:
        return Response({'error': '未找到该规则'}, status=status.HTTP_404_NOT_FOUND)
    
    name = data.get('name', rule.name).strip()
    trigger = data.get('trigger', rule.trigger).strip()
    steps = data.get('steps', rule.steps).strip()
    is_active = data.get('is_active', rule.is_active)
    
    if not name:
        return Response({'error': '规则名称不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    
    # 检查新 name 是否与其他记录冲突
    if name != rule.name and WorkflowRule.objects.filter(user=user, name=name).exists():
        return Response({'error': f'规则 "{name}" 已存在'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        rule.name = name
        rule.trigger = trigger
        rule.steps = steps
        rule.is_active = is_active
        rule.save()
        return Response({
            'id': rule.id,
            'name': rule.name,
            'trigger': rule.trigger,
            'steps': rule.steps,
            'is_active': rule.is_active,
            'message': '更新成功'
        })
    except Exception as e:
        logger.exception(f"更新工作流规则失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_workflow_rule(request, pk):
    """
    删除工作流规则
    DELETE /api/agent/memory/workflow-rules/<pk>/
    """
    user = request.user
    
    try:
        rule = WorkflowRule.objects.get(id=pk, user=user)
        name = rule.name
        rule.delete()
        return Response({'message': f'已删除规则 "{name}"'})
    except WorkflowRule.DoesNotExist:
        return Response({'error': '未找到该规则'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.exception(f"删除工作流规则失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_workflow_rule(request, pk):
    """
    切换工作流规则启用状态
    POST /api/agent/memory/workflow-rules/<pk>/toggle/
    """
    user = request.user
    
    try:
        rule = WorkflowRule.objects.get(id=pk, user=user)
        rule.is_active = not rule.is_active
        rule.save()
        return Response({
            'id': rule.id,
            'is_active': rule.is_active,
            'message': f'规则已{"启用" if rule.is_active else "禁用"}'
        })
    except WorkflowRule.DoesNotExist:
        return Response({'error': '未找到该规则'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.exception(f"切换工作流规则状态失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
