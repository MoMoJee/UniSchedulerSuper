"""
聊天上传文件 → 云盘同步模块

将聊天页上传的文件自动同步到云盘 /聊天上传/ 目录，
并回填 SessionAttachment.cloud_file 关联。
"""
from django.utils import timezone
from logger import logger

from file_service.models import UserFile, UserFolder, UserStorageQuota
from file_service.storage import compute_file_hash
from file_service.parser import _strip_markdown


def sync_chat_upload_to_cloud(user, uploaded_file, session_attachment) -> UserFile:
    """
    将聊天上传的文件同步到云盘默认路径 /聊天上传/

    流程：
    1. 确保 /聊天上传/ 文件夹存在（UserFolder.ensure_path）
    2. 计算 file_hash → 检查去重
    3. 创建 UserFile（复用 SessionAttachment 的解析结果）
    4. 回填 SessionAttachment.cloud_file
    5. 更新配额
    """
    # 确保默认文件夹
    folder = UserFolder.ensure_path(user, '/聊天上传/')

    # 去重检查：同文件夹内禁止重复
    file_hash = compute_file_hash(uploaded_file)
    existing_in_folder = UserFile.objects.filter(
        user=user, folder=folder, file_hash=file_hash, is_deleted=False
    ).first()

    if existing_in_folder:
        # 同文件夹下已有相同文件，直接关联，不重复创建
        session_attachment.cloud_file = existing_in_folder
        session_attachment.save(update_fields=['cloud_file'])
        logger.info(f"聊天上传同步: 复用已有云盘文件 id={existing_in_folder.id}")
        return existing_in_folder

    # 创建 UserFile
    mime_type = uploaded_file.content_type or ''
    category_map = UserFile.ALLOWED_MIME_TYPES
    category = category_map.get(mime_type, 'document')

    user_file = UserFile(
        user=user,
        folder=folder,
        original_file=uploaded_file,
        filename=uploaded_file.name or 'untitled',
        file_size=uploaded_file.size or 0,
        mime_type=mime_type,
        category=category,
        file_hash=file_hash,
        source='chat_upload',
    )

    # 解析结果复用策略（优先级从高到低）：
    # 1. 从 SessionAttachment 复用（当次聊天刚解析过）
    # 2. 从云盘中同 hash 已解析文件复用
    # 3. 标记为 pending，由后续流程解析
    if category == 'image':
        user_file.parse_status = 'none'
    elif session_attachment.parsed_text:
        user_file.parsed_markdown = session_attachment.parsed_text
        user_file.search_text = _strip_markdown(session_attachment.parsed_text)
        user_file.text_preview = user_file.search_text[:500]
        user_file.parse_status = 'completed'
        user_file.parse_source = 'reused_from_attachment'
    else:
        donor = UserFile.objects.filter(
            user=user, file_hash=file_hash,
            parse_status='completed', markdown_edited=False, is_deleted=False,
        ).first()
        if donor and donor.parsed_markdown:
            user_file.parsed_markdown = donor.parsed_markdown
            user_file.search_text = donor.search_text
            user_file.text_preview = donor.text_preview
            user_file.parse_status = 'completed'
            user_file.parse_source = 'reused'
        else:
            user_file.parse_status = 'pending'

    user_file.save()

    # 关联
    session_attachment.cloud_file = user_file
    session_attachment.save(update_fields=['cloud_file'])

    # 更新配额
    quota = UserStorageQuota.get_or_create_for_user(user)
    quota.consume(user_file.file_size)

    logger.info(f"聊天上传同步: 创建云盘文件 id={user_file.id}, parse_status={user_file.parse_status}")
    return user_file
