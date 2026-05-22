"""
聊天上传文件 → 云盘同步模块

将聊天页上传的文件自动同步到云盘 /聊天上传/ 目录，
并回填 SessionAttachment.cloud_file 关联。
"""
import hashlib

from django.utils import timezone
from logger import logger

from file_service.models import UserFile, UserFolder, UserStorageQuota
from file_service.parser import _strip_markdown


def _hash_from_path(file_path: str) -> str:
    """从磁盘已保存文件计算 SHA-256，避免依赖可能已耗尽的上传流。"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def sync_chat_upload_to_cloud(user, uploaded_file, session_attachment) -> 'UserFile | None':
    """
    将聊天上传的文件同步到云盘默认路径 /聊天上传/

    流程：
    1. 确保 /聊天上传/ 文件夹存在（UserFolder.ensure_path）
    2. 从 session_attachment 的已落盘文件计算 file_hash（避免依赖已耗尽的上传流）
    3. 去重检查
    4. 配额检查（不通过则跳过同步，不影响聊天功能）
    5. 创建 UserFile，复用 session_attachment.file 路径（不二次写盘）
    6. 回填 SessionAttachment.cloud_file
    7. 更新配额
    """
    # 确保默认文件夹
    folder = UserFolder.ensure_path(user, '/聊天上传/')

    # 从已落盘的附件文件计算 hash（session_attachment.file 已由 AttachmentHandler 保存）
    try:
        file_hash = _hash_from_path(session_attachment.file.path)
    except Exception as e:
        logger.warning(f"聊天上传同步: 无法计算文件hash，跳过同步 - {e}")
        return None

    existing_in_folder = UserFile.objects.filter(
        user=user, folder=folder, file_hash=file_hash, is_deleted=False
    ).first()

    if existing_in_folder:
        # 同文件夹下已有相同文件，直接关联，不重复创建
        session_attachment.cloud_file = existing_in_folder
        session_attachment.save(update_fields=['cloud_file'])
        logger.info(f"聊天上传同步: 复用已有云盘文件 id={existing_in_folder.id}")
        return existing_in_folder

    # 配额检查（不通过则跳过同步，不影响聊天功能）
    file_size = session_attachment.file_size or 0
    quota = UserStorageQuota.get_or_create_for_user(user)
    can, reason = quota.can_upload(file_size)
    if not can:
        logger.warning(f"聊天上传同步: 配额不足，跳过同步 - {reason}")
        return None

    # 创建 UserFile
    mime_type = session_attachment.mime_type or ''
    category_map = UserFile.ALLOWED_MIME_TYPES
    category = category_map.get(mime_type, 'document')

    # 直接引用 session_attachment 已落盘的文件路径，不再二次写盘
    user_file = UserFile(
        user=user,
        folder=folder,
        original_file=session_attachment.file.name,  # 字符串赋值 = 只存路径，不复制文件
        filename=session_attachment.filename or 'untitled',
        file_size=file_size,
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

    # 更新配额（配额检查已通过，此处只记账）
    quota.consume(file_size)

    logger.info(f"聊天上传同步: 创建云盘文件 id={user_file.id}, parse_status={user_file.parse_status}")
    return user_file
