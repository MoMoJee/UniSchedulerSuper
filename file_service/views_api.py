import logging
import os
import re
from urllib.parse import quote

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from file_service.models import UserFile, UserFolder, UserStorageQuota
from file_service.parser import _strip_markdown, preparse_document, should_preparse
from file_service.storage import compute_file_hash

logger = logging.getLogger(__name__)


# ============================================================
# 核心上传逻辑
# ============================================================

def _sanitize_filename(filename: str) -> str:
    """清洗文件名：去除路径分隔符、空字节等危险字符"""
    filename = os.path.basename(filename)
    filename = filename.replace('\x00', '').replace('/', '').replace('\\', '')
    filename = re.sub(r'[<>:"|?*]', '_', filename)
    return filename[:255] if filename else 'untitled'


def _core_upload(user, file_obj, folder=None, source='upload') -> dict:
    """
    核心上传函数。校验 → 去重 → 存储 → 预解析 → 配额。

    Returns:
        {"success": True, "file": UserFile} 或 {"success": False, "error": str, "status": int}
    """
    mime_type = file_obj.content_type or ''

    # 1. MIME 白名单检查
    if mime_type not in UserFile.ALLOWED_MIME_TYPES:
        return {"success": False, "error": f"不支持的文件类型: {mime_type}", "status": 400}

    # 2. 配额检查
    quota = UserStorageQuota.get_or_create_for_user(user)
    can, reason = quota.can_upload(file_obj.size)
    if not can:
        return {"success": False, "error": reason, "status": 400}

    # 3. 文件名清洗
    filename = _sanitize_filename(file_obj.name or 'untitled')

    # 4. SHA-256 计算
    file_hash = compute_file_hash(file_obj)

    # 5. 同文件夹去重检查
    if folder:
        existing = UserFile.objects.filter(
            user=user, folder=folder, file_hash=file_hash, is_deleted=False
        ).first()
        if existing:
            return {"success": False, "error": "该文件夹中已存在相同文件", "status": 400}

    # 6. 确定分类
    category = UserFile.ALLOWED_MIME_TYPES[mime_type]

    # 7. 创建 UserFile
    user_file = UserFile(
        user=user,
        folder=folder,
        original_file=file_obj,
        filename=filename,
        file_size=file_obj.size,
        mime_type=mime_type,
        category=category,
        file_hash=file_hash,
        source=source,
    )

    if category == 'image':
        user_file.parse_status = 'none'
        user_file.save()
    else:
        # 尝试跨文件夹解析复用
        donor = UserFile.objects.filter(
            user=user, file_hash=file_hash,
            parse_status='completed', markdown_edited=False, is_deleted=False,
        ).first()
        if donor and donor.parsed_markdown:
            from django.utils import timezone
            user_file.parsed_markdown = donor.parsed_markdown
            user_file.search_text = donor.search_text
            user_file.text_preview = donor.text_preview
            user_file.parse_status = 'completed'
            user_file.parse_source = 'reused'
            user_file.parsed_at = timezone.now()
            user_file.save()
        else:
            user_file.parse_status = 'pending'
            user_file.save()
            # 同步预解析
            if should_preparse(mime_type):
                preparse_document(user_file)

    # 8. 更新配额
    quota.consume(user_file.file_size)

    return {"success": True, "file": user_file}


# ============================================================
# 文件上传
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_files(request):
    """
    POST /api/files/upload/
    上传文件（multipart/form-data，支持多文件）
    可选参数：folder_id
    """
    files = request.FILES.getlist('files') or request.FILES.getlist('file')
    if not files:
        return Response({"error": "未提供文件"}, status=400)

    folder_id = request.data.get('folder_id')
    folder = None
    if folder_id:
        folder = get_object_or_404(UserFolder, id=folder_id, user=request.user)

    results = []
    errors = []
    for f in files:
        result = _core_upload(request.user, f, folder=folder)
        if result['success']:
            results.append(result['file'].to_api_dict())
        else:
            errors.append({"filename": f.name, "error": result['error']})

    status_code = 201 if results else 400
    return Response({
        "uploaded": results,
        "errors": errors,
    }, status=status_code)


# ============================================================
# URL 上传
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_from_url(request):
    """
    POST /api/files/upload-url/
    Body: {"url": "https://example.com/file.pdf", "folder_id": 3}
    """
    url = request.data.get('url', '').strip()
    if not url:
        return Response({"error": "请提供 URL"}, status=400)

    folder_id = request.data.get('folder_id')
    folder = None
    if folder_id:
        folder = get_object_or_404(UserFolder, id=folder_id, user=request.user)

    from file_service.url_fetcher import fetch_url
    result = fetch_url(url, request.user)
    if not result['success']:
        return Response({"error": result['error']}, status=400)

    file_obj = result['file_obj']
    upload_result = _core_upload(request.user, file_obj, folder=folder, source='url')

    if not upload_result['success']:
        return Response({"error": upload_result['error']}, status=upload_result.get('status', 400))

    # 记录源 URL
    user_file = upload_result['file']
    user_file.source_url = url
    user_file.save(update_fields=['source_url'])

    return Response({"file": user_file.to_api_dict()}, status=201)


# ============================================================
# 文件列表
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_files(request):
    """
    GET /api/files/
    列出文件和文件夹。支持 folder_id、category 筛选。
    """
    user = request.user
    folder_id = request.query_params.get('folder_id')
    category = request.query_params.get('category')

    # 当前文件夹
    current_folder = None
    if folder_id:
        current_folder = get_object_or_404(UserFolder, id=folder_id, user=user)

    # 面包屑
    breadcrumb = [{"id": None, "name": "根目录", "path": "/"}]
    if current_folder:
        parts = [p for p in current_folder.path.strip('/').split('/') if p]
        path_accum = "/"
        for part in parts:
            path_accum = f"{path_accum}{part}/"
            try:
                f = UserFolder.objects.get(user=user, path=path_accum)
                breadcrumb.append({"id": f.id, "name": f.name, "path": f.path})
            except UserFolder.DoesNotExist:
                pass

    # 子文件夹
    folders_qs = UserFolder.objects.filter(user=user, parent=current_folder)
    folders_data = []
    for f in folders_qs:
        file_count = UserFile.objects.filter(user=user, folder=f, is_deleted=False).count()
        folders_data.append({
            "id": f.id,
            "name": f.name,
            "path": f.path,
            "file_count": file_count,
        })

    # 文件
    files_qs = UserFile.objects.filter(user=user, folder=current_folder, is_deleted=False)
    if category:
        files_qs = files_qs.filter(category=category)
    files_data = [uf.to_api_dict() for uf in files_qs]

    # 配额
    quota = UserStorageQuota.get_or_create_for_user(user)

    return Response({
        "current_folder": {
            "id": current_folder.id if current_folder else None,
            "name": current_folder.name if current_folder else "根目录",
            "path": current_folder.path if current_folder else "/",
        },
        "breadcrumb": breadcrumb,
        "folders": folders_data,
        "files": files_data,
        "quota": {
            "used_bytes": quota.used_bytes,
            "max_storage_bytes": quota.max_storage_bytes,
            "usage_percent": quota.usage_percent,
            "file_count": quota.file_count,
        },
    })


# ============================================================
# 文件详情
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_file(request, file_id):
    """GET /api/files/<id>/"""
    user_file = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    return Response(user_file.to_api_dict(include_content=True))


# ============================================================
# 文件删除（软删除）
# ============================================================

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_file(request, file_id):
    """DELETE /api/files/<id>/"""
    user_file = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    user_file.soft_delete()
    return Response({"message": "文件已删除"})


# ============================================================
# 文件重命名
# ============================================================

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def rename_file(request, file_id):
    """PUT /api/files/<id>/rename/"""
    user_file = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    new_name = request.data.get('filename', '').strip()
    if not new_name:
        return Response({"error": "文件名不能为空"}, status=400)
    user_file.filename = _sanitize_filename(new_name)
    user_file.save(update_fields=['filename', 'updated_at'])
    return Response({"id": user_file.id, "filename": user_file.filename})


# ============================================================
# 文件移动
# ============================================================

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def move_file(request, file_id):
    """PUT /api/files/<id>/move/  Body: {"folder_id": 5} 或 {"folder_id": null} 移到根目录"""
    user_file = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    folder_id = request.data.get('folder_id')

    target_folder = None
    if folder_id:
        target_folder = get_object_or_404(UserFolder, id=folder_id, user=request.user)

    # 目标文件夹去重检查
    existing = UserFile.objects.filter(
        user=request.user, folder=target_folder,
        file_hash=user_file.file_hash, is_deleted=False
    ).exclude(id=user_file.id).first()
    if existing:
        return Response({"error": "目标文件夹中已存在相同文件"}, status=400)

    user_file.folder = target_folder
    user_file.save(update_fields=['folder', 'updated_at'])
    return Response({"id": user_file.id, "folder_id": user_file.folder_id})


# ============================================================
# 文件下载
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_file(request, file_id):
    """GET /api/files/<id>/download/  下载原始文件"""
    user_file = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    if not user_file.original_file:
        return Response({"error": "文件不存在"}, status=404)

    response = FileResponse(
        user_file.original_file.open('rb'),
        content_type=user_file.mime_type,
    )
    response['Content-Disposition'] = (
        f"attachment; filename*=UTF-8''{quote(user_file.filename)}"
    )
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_markdown(request, file_id):
    """GET /api/files/<id>/download-md/  下载解析后的 Markdown"""
    user_file = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    if not user_file.parsed_markdown:
        return Response({"error": "该文件无 Markdown 内容"}, status=404)

    md_filename = os.path.splitext(user_file.filename)[0] + '.md'
    response = FileResponse(
        user_file.parsed_markdown.encode('utf-8'),
        content_type='text/markdown; charset=utf-8',
    )
    response['Content-Disposition'] = (
        f"attachment; filename*=UTF-8''{quote(md_filename)}"
    )
    return response


# ============================================================
# Markdown 读取/编辑
# ============================================================

@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def file_markdown(request, file_id):
    """
    GET  /api/files/<id>/markdown/  — 读取 Markdown 内容
    PUT  /api/files/<id>/markdown/  — 更新 Markdown 内容
    """
    user_file = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)

    if not user_file.is_document:
        return Response({"error": "仅文档类文件支持 Markdown 操作"}, status=400)

    if request.method == 'GET':
        return Response({
            "id": user_file.id,
            "filename": user_file.filename,
            "parsed_markdown": user_file.parsed_markdown,
            "markdown_edited": user_file.markdown_edited,
            "parse_status": user_file.parse_status,
        })

    # PUT: 更新
    content = request.data.get('content', '')
    if not content.strip():
        return Response({"error": "内容不能为空"}, status=400)

    plain_text = _strip_markdown(content)

    user_file.parsed_markdown = content
    user_file.search_text = plain_text
    user_file.text_preview = plain_text[:500]
    user_file.markdown_edited = True
    user_file.save(update_fields=[
        'parsed_markdown', 'search_text', 'text_preview', 'markdown_edited', 'updated_at'
    ])

    return Response({
        "id": user_file.id,
        "message": "保存成功",
        "markdown_edited": True,
    })


# ============================================================
# 文件夹 CRUD
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_folder(request):
    """POST /api/files/folders/  Body: {"name": "文档", "parent_id": null}"""
    name = request.data.get('name', '').strip()
    if not name:
        return Response({"error": "文件夹名称不能为空"}, status=400)

    # 清洗文件夹名
    name = re.sub(r'[/\\<>:"|?*\x00]', '_', name)[:255]

    parent_id = request.data.get('parent_id')
    parent = None
    if parent_id:
        parent = get_object_or_404(UserFolder, id=parent_id, user=request.user)

    # 计算目标路径
    if parent:
        target_path = f"{parent.path}{name}/"
    else:
        target_path = f"/{name}/"

    # 检查是否已存在
    if UserFolder.objects.filter(user=request.user, path=target_path).exists():
        return Response({"error": "该文件夹已存在"}, status=400)

    folder = UserFolder.objects.create(
        user=request.user, name=name, parent=parent
    )
    return Response({
        "id": folder.id,
        "name": folder.name,
        "path": folder.path,
    }, status=201)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_folder(request, folder_id):
    """DELETE /api/files/folders/<id>/  递归软删除文件夹及其内容"""
    folder = get_object_or_404(UserFolder, id=folder_id, user=request.user)

    # 递归收集所有子文件夹（包括自身）
    all_folders = list(UserFolder.objects.filter(
        user=request.user, path__startswith=folder.path
    ))
    folder_ids = [f.id for f in all_folders]

    # 软删除所有文件
    files_to_delete = UserFile.objects.filter(
        user=request.user, folder_id__in=folder_ids, is_deleted=False
    )
    for uf in files_to_delete:
        uf.soft_delete()

    # 删除文件夹记录
    UserFolder.objects.filter(id__in=folder_ids).delete()

    return Response({"message": "文件夹已删除"})


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def rename_folder(request, folder_id):
    """PUT /api/files/folders/<id>/rename/  Body: {"name": "新名称"}"""
    folder = get_object_or_404(UserFolder, id=folder_id, user=request.user)
    new_name = request.data.get('name', '').strip()
    if not new_name:
        return Response({"error": "文件夹名称不能为空"}, status=400)

    new_name = re.sub(r'[/\\<>:"|?*\x00]', '_', new_name)[:255]

    # 检查重名
    if folder.parent:
        new_path = f"{folder.parent.path}{new_name}/"
    else:
        new_path = f"/{new_name}/"

    if UserFolder.objects.filter(user=request.user, path=new_path).exclude(id=folder.id).exists():
        return Response({"error": "同名文件夹已存在"}, status=400)

    old_path = folder.path
    folder.name = new_name
    folder.save()  # save() 会自动重算 path

    # 递归更新子文件夹的 path
    for child in UserFolder.objects.filter(user=request.user, path__startswith=old_path).exclude(id=folder.id):
        child.path = child.path.replace(old_path, folder.path, 1)
        child.save(update_fields=['path', 'updated_at'])

    return Response({"id": folder.id, "name": folder.name, "path": folder.path})


# ============================================================
# 配额查询
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_quota(request):
    """GET /api/files/quota/"""
    quota = UserStorageQuota.get_or_create_for_user(request.user)
    return Response({
        "used_bytes": quota.used_bytes,
        "max_storage_bytes": quota.max_storage_bytes,
        "max_file_size": quota.max_file_size,
        "remaining_bytes": quota.remaining_bytes,
        "usage_percent": quota.usage_percent,
        "file_count": quota.file_count,
        "tier": quota.tier,
    })


# ============================================================
# 文件搜索（P7 实现，此处占位）
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_files(request):
    """GET /api/files/search/?q=xxx&category=document&limit=10"""
    query = request.query_params.get('q', '').strip()
    if not query:
        return Response({"error": "请提供搜索关键词"}, status=400)

    category = request.query_params.get('category')
    folder_id = request.query_params.get('folder_id')
    limit = min(int(request.query_params.get('limit', 10)), 50)

    from file_service.search import FileSearchEngine
    results = FileSearchEngine.search(
        user=request.user, query=query, limit=limit,
        category=category,
        folder_id=int(folder_id) if folder_id else None,
    )

    return Response({
        "query": query,
        "results": [
            {
                "id": r['file'].id,
                "filename": r['file'].filename,
                "category": r['file'].category,
                "score": r['score'],
                "snippet": r['snippet'],
                "text_preview": r['file'].text_preview,
                "created_at": r['file'].created_at.isoformat(),
            }
            for r in results
        ],
        "total": len(results),
    })


# ============================================================
# 聊天页文件选择列表
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pick_files(request):
    """GET /api/files/pick/?category=document  供聊天页'从云盘加载'弹窗使用"""
    user = request.user
    folder_id = request.query_params.get('folder_id')
    category = request.query_params.get('category')

    qs = UserFile.objects.filter(user=user, is_deleted=False)
    if folder_id:
        qs = qs.filter(folder_id=folder_id)
    if category:
        qs = qs.filter(category=category)

    # 同时返回文件夹结构
    folders = UserFolder.objects.filter(user=user)

    return Response({
        "folders": [
            {"id": f.id, "name": f.name, "path": f.path, "parent_id": f.parent_id}
            for f in folders
        ],
        "files": [
            {
                "id": uf.id,
                "filename": uf.filename,
                "file_size": uf.file_size,
                "category": uf.category,
                "folder_id": uf.folder_id,
                "parse_status": uf.parse_status,
            }
            for uf in qs[:100]
        ],
    })
