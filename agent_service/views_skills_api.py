"""
技能管理 API
提供 Agent Skill 的 CRUD 操作和导入功能
"""
import re
import html
import os
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status

from agent_service.models import AgentSkill
from logger import logger

# ==========================================
# 安全过滤
# ==========================================

# 危险模式列表（拒绝包含这些模式的内容）
_DANGEROUS_PATTERNS = [
    re.compile(r'<\s*script', re.IGNORECASE),
    re.compile(r'javascript\s*:', re.IGNORECASE),
    re.compile(r'\beval\s*\(', re.IGNORECASE),
    re.compile(r'\bexec\s*\(', re.IGNORECASE),
    re.compile(r'\bFunction\s*\(', re.IGNORECASE),
    re.compile(r'on\w+\s*=', re.IGNORECASE),  # onclick=, onerror= 等
    re.compile(r'<\s*iframe', re.IGNORECASE),
    re.compile(r'<\s*object', re.IGNORECASE),
    re.compile(r'<\s*embed', re.IGNORECASE),
]

# 允许导入的文件扩展名
_ALLOWED_EXTENSIONS = {'.txt', '.md'}

# 允许导入的 MIME 类型
_ALLOWED_MIME_TYPES = {
    'text/plain',
    'text/markdown',
    'text/x-markdown',
    'application/octet-stream',  # 某些系统将 .md 识别为 octet-stream
}

# 最大文件大小 (1MB)
_MAX_FILE_SIZE = 1 * 1024 * 1024


def _sanitize_content(content: str) -> str:
    """
    对 skill 内容进行安全过滤。
    
    - 检测并拒绝含脚本/危险模式的内容
    - 去除 HTML 标签，保留纯文本
    
    Returns:
        过滤后的纯文本
    
    Raises:
        ValueError: 内容包含危险模式
    """
    if not content:
        return ""
    
    # 检测危险模式
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(content):
            raise ValueError(f"内容包含不安全的模式，不允许包含脚本代码或 HTML 事件处理器")
    
    # 去除 HTML 标签：先 escape 再 unescape 确保纯文本
    # 这样 <b>text</b> → &lt;b&gt;text&lt;/b&gt; → <b>text</b> 但原始标签已被检查过
    # 实际上我们直接使用正则去除所有 HTML 标签
    cleaned = re.sub(r'<[^>]+>', '', content)
    
    return cleaned.strip()


# ==========================================
# Skill CRUD API
# ==========================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_skills(request):
    """
    获取用户所有技能（不含 content）
    GET /api/agent/skills/
    """
    skills = AgentSkill.objects.filter(user=request.user)

    data = [{
        'id': s.id,
        'name': s.name,
        'description': s.description,
        'is_active': s.is_active,
        'source': s.source,
        'created_at': s.created_at.isoformat(),
        'updated_at': s.updated_at.isoformat(),
    } for s in skills]

    return Response({'items': data, 'count': len(data)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_skill(request):
    """
    创建技能
    POST /api/agent/skills/create/
    Body: {"name": "...", "description": "...", "content": "..."}
    """
    data = request.data
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    content = (data.get('content') or '').strip()

    if not name:
        return Response({'error': '技能名称不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    if not description:
        return Response({'error': '技能描述不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    if not content:
        return Response({'error': '技能内容不能为空'}, status=status.HTTP_400_BAD_REQUEST)

    # 安全过滤
    try:
        content = _sanitize_content(content)
        description = _sanitize_content(description)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    if AgentSkill.objects.filter(user=request.user, name=name).exists():
        return Response({'error': f'技能 "{name}" 已存在'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        skill = AgentSkill.objects.create(
            user=request.user,
            name=name,
            description=description,
            content=content,
            source=data.get('source', 'manual'),
        )
        return Response({
            'id': skill.id,
            'name': skill.name,
            'description': skill.description,
            'is_active': skill.is_active,
            'source': skill.source,
            'message': '创建成功',
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.exception(f"创建技能失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def skill_detail(request, pk):
    """
    获取/更新单个技能
    GET  /api/agent/skills/<pk>/   → 含 content
    PUT  /api/agent/skills/<pk>/   → 更新
    """
    try:
        skill = AgentSkill.objects.get(id=pk, user=request.user)
    except AgentSkill.DoesNotExist:
        return Response({'error': '未找到该技能'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response({
            'id': skill.id,
            'name': skill.name,
            'description': skill.description,
            'content': skill.content,
            'is_active': skill.is_active,
            'source': skill.source,
            'created_at': skill.created_at.isoformat(),
            'updated_at': skill.updated_at.isoformat(),
        })

    # PUT
    data = request.data
    name = (data.get('name') or skill.name).strip()
    description = (data.get('description') or skill.description).strip()
    content = (data.get('content') or skill.content).strip()

    if not name:
        return Response({'error': '技能名称不能为空'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        content = _sanitize_content(content)
        description = _sanitize_content(description)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # 名称冲突检测
    if name != skill.name and AgentSkill.objects.filter(user=request.user, name=name).exists():
        return Response({'error': f'技能 "{name}" 已存在'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        skill.name = name
        skill.description = description
        skill.content = content
        skill.save()
        return Response({
            'id': skill.id,
            'name': skill.name,
            'description': skill.description,
            'content': skill.content,
            'is_active': skill.is_active,
            'source': skill.source,
            'message': '更新成功',
        })
    except Exception as e:
        logger.exception(f"更新技能失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_skill(request, pk):
    """
    删除技能
    DELETE /api/agent/skills/<pk>/delete/
    """
    try:
        skill = AgentSkill.objects.get(id=pk, user=request.user)
        name = skill.name
        skill.delete()
        return Response({'message': f'已删除技能 "{name}"'})
    except AgentSkill.DoesNotExist:
        return Response({'error': '未找到该技能'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.exception(f"删除技能失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_skill(request, pk):
    """
    切换技能 is_active 状态
    POST /api/agent/skills/<pk>/toggle/
    """
    try:
        skill = AgentSkill.objects.get(id=pk, user=request.user)
        skill.is_active = not skill.is_active
        skill.save()
        return Response({
            'id': skill.id,
            'is_active': skill.is_active,
            'message': f'技能已{"启用" if skill.is_active else "禁用"}',
        })
    except AgentSkill.DoesNotExist:
        return Response({'error': '未找到该技能'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.exception(f"切换技能状态失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def import_skill(request):
    """
    导入技能（从文件或粘贴文本）
    POST /api/agent/skills/import/
    
    文件导入: multipart/form-data
        - file: .txt 或 .md 文件（最大 1MB）
        - name: 技能名称（可选，默认使用文件名）
        - description: 简短描述
    
    文本导入: application/json
        - name: 技能名称
        - description: 简短描述
        - content: 技能内容文本
    """
    # 判断是文件导入还是文本导入
    uploaded_file = request.FILES.get('file')

    if uploaded_file:
        # ===== 文件导入 =====
        # 扩展名检查
        _, ext = os.path.splitext(uploaded_file.name)
        ext = ext.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            return Response(
                {'error': f'不支持的文件类型 "{ext}"，仅支持 .txt 和 .md'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 大小检查
        if uploaded_file.size > _MAX_FILE_SIZE:
            return Response(
                {'error': f'文件过大（{uploaded_file.size / 1024:.0f}KB），最大 1MB'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 读取内容
        try:
            content = uploaded_file.read().decode('utf-8')
        except UnicodeDecodeError:
            return Response({'error': '文件编码不是 UTF-8，请转换后重试'}, status=status.HTTP_400_BAD_REQUEST)

        name = (request.data.get('name') or '').strip()
        if not name:
            # 使用文件名（去掉扩展名）
            name = os.path.splitext(uploaded_file.name)[0].strip()
        description = (request.data.get('description') or '').strip()
    else:
        # ===== 文本导入 =====
        name = (request.data.get('name') or '').strip()
        description = (request.data.get('description') or '').strip()
        content = (request.data.get('content') or '').strip()

    if not name:
        return Response({'error': '技能名称不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    if not content:
        return Response({'error': '技能内容不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    if not description:
        return Response({'error': '技能描述不能为空'}, status=status.HTTP_400_BAD_REQUEST)

    # 安全过滤
    try:
        content = _sanitize_content(content)
        description = _sanitize_content(description)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # 检查名称冲突
    if AgentSkill.objects.filter(user=request.user, name=name).exists():
        return Response({'error': f'技能 "{name}" 已存在'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        skill = AgentSkill.objects.create(
            user=request.user,
            name=name,
            description=description,
            content=content,
            source='imported',
        )
        return Response({
            'id': skill.id,
            'name': skill.name,
            'description': skill.description,
            'is_active': skill.is_active,
            'source': skill.source,
            'message': '导入成功',
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.exception(f"导入技能失败: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
