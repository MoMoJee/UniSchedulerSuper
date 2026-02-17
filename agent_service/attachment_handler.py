"""
附件处理器

集成解析器、模型能力查询、SessionAttachment 模型，提供统一的业务逻辑接口：
  - handle_upload():   处理外部文件上传
  - handle_internal(): 处理内部元素附件
  - format_for_message(): 根据当前模型能力，格式化附件列表为 AI 消息内容
  - soft_delete_by_rollback(): 回滚时软删除
  - cleanup_expired():  清理过期的软删除附件
"""
import os
import uuid
from typing import Dict, Any, List, Optional

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from logger import logger


class AttachmentHandler:
    """附件业务逻辑处理器"""

    # ================================================================
    # 文件上传
    # ================================================================

    @staticmethod
    def handle_upload(
        user,
        session_id: str,
        uploaded_file: UploadedFile,
    ) -> Dict[str, Any]:
        """
        处理外部文件上传。

        流程：
          1. 校验 MIME、大小
          2. 存储文件
          3. 调用对应解析器
          4. 创建 SessionAttachment 记录

        Returns:
            {"success": bool, "attachment": SessionAttachment|None, "error": str}
        """
        from agent_service.models import SessionAttachment

        # ---------- 1. 校验 ----------
        mime_type = uploaded_file.content_type or ''
        file_size = uploaded_file.size or 0

        if mime_type not in SessionAttachment.ALLOWED_MIME_TYPES:
            return {
                "success": False,
                "attachment": None,
                "error": f"不支持的文件类型: {mime_type}"
            }

        max_size = getattr(settings, 'ATTACHMENT_MAX_FILE_SIZE', 20 * 1024 * 1024)
        if file_size > max_size:
            return {
                "success": False,
                "attachment": None,
                "error": f"文件过大: {file_size} 字节（上限 {max_size // 1024 // 1024}MB）"
            }

        att_type = SessionAttachment.ALLOWED_MIME_TYPES[mime_type]

        # ---------- 2. 创建 Attachment 记录（先保存文件）----------
        attachment = SessionAttachment(
            user=user,
            session_id=session_id,
            type=att_type,
            filename=uploaded_file.name or 'untitled',
            file=uploaded_file,
            file_size=file_size,
            mime_type=mime_type,
            parse_status='processing',
        )
        attachment.save()

        # ---------- 3. 解析 ----------
        try:
            AttachmentHandler._parse_file_attachment(attachment)
        except Exception as e:
            logger.error(f"附件解析异常 [{attachment.id}]: {e}")
            attachment.parse_status = 'failed'
            attachment.parse_error = str(e)
            attachment.save(update_fields=['parse_status', 'parse_error'])

        return {
            "success": True,
            "attachment": attachment,
            "error": ""
        }

    @staticmethod
    def _parse_file_attachment(attachment):
        """调用对应解析器处理外部文件"""
        from agent_service.parsers import parser_factory

        file_path = attachment.file.path
        mime_type = attachment.mime_type

        parser = parser_factory.get_parser(mime_type)
        if not parser:
            attachment.parse_status = 'failed'
            attachment.parse_error = f"无可用解析器: {mime_type}"
            attachment.save(update_fields=['parse_status', 'parse_error'])
            return

        # 如果当前模型支持 vision 且是图片，跳过耗时的 OCR
        parse_kwargs = {}
        if attachment.type == 'image':
            try:
                from agent_service.model_capabilities import ModelCapabilities
                if ModelCapabilities.supports_vision(attachment.user):
                    parse_kwargs['skip_ocr'] = True
            except Exception as e:
                logger.warning(f"检查模型 vision 能力失败，继续执行 OCR: {e}")

        result = parser.parse(file_path, **parse_kwargs)

        if result.get('success'):
            attachment.parsed_text = result.get('text', '')
            attachment.parse_status = 'completed'
            attachment.parse_error = ''

            # 图片额外处理: base64 + 缩略图
            if attachment.type == 'image':
                attachment.base64_data = result.get('base64', '')
                AttachmentHandler._generate_thumbnail(attachment, parser)
        else:
            attachment.parse_status = 'failed'
            attachment.parse_error = result.get('error', '解析失败')

        update_fields = ['parsed_text', 'base64_data', 'parse_status', 'parse_error']
        if attachment.type == 'image' and attachment.thumbnail:
            update_fields.append('thumbnail')
        attachment.save(update_fields=update_fields)

    @staticmethod
    def _generate_thumbnail(attachment, parser):
        """为图片生成缩略图"""
        try:
            from django.core.files.base import ContentFile

            thumb_dir = os.path.join(
                settings.MEDIA_ROOT, 'attachments', 'thumbs',
                timezone.now().strftime('%Y/%m/%d'),
            )
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_name = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
            thumb_path = os.path.join(thumb_dir, thumb_name)

            parser.generate_thumbnail(attachment.file.path, thumb_path, size=(200, 200))

            if os.path.exists(thumb_path):
                rel_path = os.path.relpath(thumb_path, settings.MEDIA_ROOT)
                attachment.thumbnail.name = rel_path.replace('\\', '/')
        except Exception as e:
            logger.warning(f"缩略图生成失败 [{attachment.id}]: {e}")

    # ================================================================
    # 内部元素附件
    # ================================================================

    @staticmethod
    def handle_internal(
        user,
        session_id: str,
        element_type: str,
        element_id: str,
    ) -> Dict[str, Any]:
        """
        将内部元素绑定为附件。

        流程：
          1. 用 InternalElementParser 解析元素
          2. 保存快照
          3. 创建 SessionAttachment 记录

        Returns:
            {"success": bool, "attachment": SessionAttachment|None, "error": str}
        """
        from agent_service.models import SessionAttachment
        from agent_service.parsers import parser_factory

        valid_types = ('event', 'todo', 'reminder', 'workflow')
        if element_type not in valid_types:
            return {
                "success": False,
                "attachment": None,
                "error": f"不支持的内部类型: {element_type}"
            }

        parser = parser_factory.get_internal_parser()
        result = parser.parse(
            element_type=element_type,
            element_id=element_id,
            user=user,
        )

        if not result.get('success'):
            return {
                "success": False,
                "attachment": None,
                "error": result.get('error', '元素解析失败')
            }

        # 获取快照数据
        snapshot = AttachmentHandler._build_snapshot(user, element_type, element_id)

        attachment = SessionAttachment(
            user=user,
            session_id=session_id,
            type=element_type,
            filename=result.get('metadata', {}).get('title') or result.get('metadata', {}).get('name') or f"{element_type}:{element_id}",
            internal_type=element_type,
            internal_id=element_id,
            internal_snapshot=snapshot,
            parsed_text=result.get('text', ''),
            parse_status='completed',
        )
        attachment.save()

        return {
            "success": True,
            "attachment": attachment,
            "error": ""
        }

    @staticmethod
    def _build_snapshot(user, element_type: str, element_id: str) -> dict:
        """构建内部元素快照，防止原数据删除后丢失"""
        from agent_service.parsers.internal_parser import InternalElementParser

        if element_type == 'workflow':
            from agent_service.models import WorkflowRule
            try:
                rule = WorkflowRule.objects.get(id=int(element_id), user=user)
                return {
                    'name': rule.name,
                    'trigger': rule.trigger,
                    'steps': rule.steps,
                    'is_active': rule.is_active,
                }
            except (WorkflowRule.DoesNotExist, ValueError):
                return {}
        else:
            key_map = {
                'event': 'events',
                'todo': 'todos',
                'reminder': 'reminders',
            }
            key = key_map.get(element_type)
            if not key:
                return {}

            item = InternalElementParser._find_in_userdata(user, key, element_id)
            return dict(item) if item else {}

    # ================================================================
    # 格式化：准备发送给 AI 的内容
    # ================================================================

    @staticmethod
    def format_for_message(
        attachments: List,
        user=None,
        model_supports_vision: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        将附件列表格式化为 AI 消息可消费的内容块。

        Args:
            attachments: SessionAttachment queryset 或 list
            user: 用户对象（如果 model_supports_vision 未指定，自动查询）
            model_supports_vision: 是否支持 vision（传入可避免重复查询）

        Returns:
            list[dict]:
              - {"type": "text", "text": "..."}                        纯文本
              - {"type": "image_url", "image_url": {"url": "data:..."}} vision 图片
        """
        if model_supports_vision is None and user:
            from agent_service.model_capabilities import ModelCapabilities
            model_supports_vision = ModelCapabilities.supports_vision(user)

        content_blocks = []

        for att in attachments:
            if att.is_deleted:
                continue

            formatted = att.get_formatted_content(
                model_supports_vision=bool(model_supports_vision)
            )

            fmt_type = formatted.get('type')
            content = formatted.get('content', '')

            if fmt_type == 'base64' and content:
                # OpenAI / compatible vision 格式
                mime = att.mime_type or 'image/jpeg'
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{content}",
                        "detail": "auto",
                    }
                })
            elif content:
                # 文本 / Markdown
                prefix = f"[附件: {att.filename}]\n" if att.is_file_attachment else ''
                content_blocks.append({
                    "type": "text",
                    "text": f"{prefix}{content}",
                })

        return content_blocks

    @staticmethod
    def format_single(attachment, model_supports_vision: bool = False) -> Dict[str, Any]:
        """格式化单个附件，便于预览"""
        formatted = attachment.get_formatted_content(
            model_supports_vision=model_supports_vision
        )
        return {
            "id": attachment.id,
            "type": attachment.type,
            "filename": attachment.filename,
            "format": formatted.get('type'),
            "content_preview": formatted.get('content', '')[:500],
            "metadata": formatted.get('metadata', {}),
        }

    # ================================================================
    # 回滚 & 清理
    # ================================================================

    @staticmethod
    def soft_delete_by_rollback(session_id: str, message_index: int):
        """
        回滚操作：软删除该消息索引及之后的所有附件。

        Args:
            session_id: 会话 ID
            message_index: 回滚到的消息索引
        """
        from agent_service.models import SessionAttachment

        attachments = SessionAttachment.objects.filter(
            session_id=session_id,
            is_deleted=False,
            message_index__gte=message_index,
        )

        count = attachments.count()
        if count > 0:
            now = timezone.now()
            attachments.update(
                is_deleted=True,
                deleted_at=now,
                deleted_reason='rollback',
                deleted_with_message_index=message_index,
            )
            logger.info(
                f"回滚软删除 {count} 个附件 "
                f"(session={session_id}, from_msg={message_index})"
            )

        return count

    @staticmethod
    def restore_by_rollback(session_id: str, message_index: int) -> int:
        """
        撤销回滚：恢复该消息索引相关的软删除附件。
        """
        from agent_service.models import SessionAttachment

        attachments = SessionAttachment.objects.filter(
            session_id=session_id,
            is_deleted=True,
            deleted_reason='rollback',
            deleted_with_message_index=message_index,
        )

        count = attachments.count()
        if count > 0:
            attachments.update(
                is_deleted=False,
                deleted_at=None,
                deleted_reason='',
                deleted_with_message_index=None,
            )
            logger.info(
                f"恢复 {count} 个附件 "
                f"(session={session_id}, msg_index={message_index})"
            )

        return count

    @staticmethod
    def cleanup_expired(days: int = 7) -> int:
        """
        物理清理过期的软删除附件。

        Args:
            days: 软删除超过多少天后执行物理删除

        Returns:
            清理的数量
        """
        from agent_service.models import SessionAttachment

        cutoff = timezone.now() - timezone.timedelta(days=days)
        expired = SessionAttachment.objects.filter(
            is_deleted=True,
            deleted_at__lt=cutoff,
        )

        count = 0
        for att in expired:
            try:
                att.hard_delete()
                count += 1
            except Exception as e:
                logger.error(f"物理清理失败 [{att.id}]: {e}")

        if count:
            logger.info(f"物理清理 {count} 个过期附件")

        return count

    # ================================================================
    # 查询辅助
    # ================================================================

    @staticmethod
    def get_session_attachments(session_id: str, include_deleted: bool = False):
        """获取会话的附件列表"""
        from agent_service.models import SessionAttachment

        qs = SessionAttachment.objects.filter(session_id=session_id)
        if not include_deleted:
            qs = qs.filter(is_deleted=False)
        return qs

    @staticmethod
    def get_pending_attachments(session_id: str):
        """获取已上传但尚未发送的附件（无 message_index）"""
        from agent_service.models import SessionAttachment

        return SessionAttachment.objects.filter(
            session_id=session_id,
            is_deleted=False,
            message_index__isnull=True,
        )

    @staticmethod
    def mark_sent(attachment_ids: list, message_index: int, model_id: str = ''):
        """标记附件为已发送"""
        from agent_service.models import SessionAttachment

        now = timezone.now()
        SessionAttachment.objects.filter(id__in=attachment_ids).update(
            message_index=message_index,
            sent_at=now,
            sent_with_model=model_id,
        )

    # ================================================================
    # 多模态切换支持
    # ================================================================

    @staticmethod
    def get_images_without_ocr(session_id: str) -> List[Dict[str, Any]]:
        """
        获取会话中没有 OCR 结果的图片附件列表
        
        Returns:
            list[dict]: 每项包含 id, filename, thumbnail_url
        """
        from agent_service.models import SessionAttachment
        
        attachments = SessionAttachment.objects.filter(
            session_id=session_id,
            is_deleted=False,
            type='image',
            message_index__isnull=False,  # 只检查已发送的
        ).filter(
            # parsed_text 为空或是默认占位符
            parsed_text__in=['', '[图片，无可识别文字内容]']
        )
        
        return [
            {
                'id': att.id,
                'filename': att.filename,
                'thumbnail_url': att.thumbnail.url if att.thumbnail else None,
                'has_base64': bool(att.base64_data),
            }
            for att in attachments
        ]

    @staticmethod
    def run_ocr_on_attachment(attachment_id: int, user) -> Dict[str, Any]:
        """
        对指定附件执行 OCR
        
        Returns:
            {"success": bool, "text": str, "error": str}
        """
        from agent_service.models import SessionAttachment
        from agent_service.parsers.image_parser import ImageParser
        
        try:
            att = SessionAttachment.objects.get(id=attachment_id, user=user, is_deleted=False)
        except SessionAttachment.DoesNotExist:
            return {"success": False, "text": "", "error": "附件不存在"}
        
        if att.type != 'image':
            return {"success": False, "text": "", "error": "仅支持图片附件"}
        
        if not att.file:
            return {"success": False, "text": "", "error": "附件文件不存在"}
        
        # 如果已有有效的 OCR 结果，直接返回
        if att.parsed_text and att.parsed_text not in ['', '[图片，无可识别文字内容]']:
            return {"success": True, "text": att.parsed_text, "error": ""}
        
        try:
            parser = ImageParser()
            ocr_text = parser._extract_text_ocr(att.file.path)
            
            # 更新附件
            att.parsed_text = ocr_text or "[图片，无可识别文字内容]"
            att.save(update_fields=['parsed_text'])
            
            return {"success": True, "text": att.parsed_text, "error": ""}
        except Exception as e:
            logger.error(f"OCR 失败 [{attachment_id}]: {e}")
            return {"success": False, "text": "", "error": str(e)}

    @staticmethod
    def batch_run_ocr(attachment_ids: List[int], user) -> Dict[str, Any]:
        """
        批量执行 OCR
        
        Returns:
            {"success": int, "failed": int, "results": list}
        """
        results = []
        success_count = 0
        failed_count = 0
        
        for att_id in attachment_ids:
            result = AttachmentHandler.run_ocr_on_attachment(att_id, user)
            results.append({
                'id': att_id,
                'success': result['success'],
                'error': result.get('error', ''),
            })
            if result['success']:
                success_count += 1
            else:
                failed_count += 1
        
        return {
            "success": success_count,
            "failed": failed_count,
            "results": results,
        }

    @staticmethod
    def rebuild_message_content_for_model(
        original_content,
        attachment_ids: List[int],
        user,
        supports_vision: bool
    ) -> any:
        """
        根据模型能力重建消息内容
        
        Args:
            original_content: 原始消息内容（string 或 multimodal array）
            attachment_ids: 附件 ID 列表
            user: 用户对象
            supports_vision: 当前模型是否支持视觉
            
        Returns:
            重建后的内容（string 或 multimodal array）
        """
        from agent_service.models import SessionAttachment
        
        if not attachment_ids:
            return original_content
        
        # 获取附件
        attachments = SessionAttachment.objects.filter(
            id__in=attachment_ids, user=user, is_deleted=False
        )
        
        image_atts = [a for a in attachments if a.type == 'image']
        
        if not image_atts:
            return original_content
        
        # 提取原始文本内容
        text_content = ""
        if isinstance(original_content, str):
            text_content = original_content
        elif isinstance(original_content, list):
            text_parts = []
            for block in original_content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
                elif isinstance(block, str):
                    text_parts.append(block)
            text_content = '\n'.join(text_parts)
        
        if supports_vision:
            # 重建为多模态格式
            content = [{"type": "text", "text": text_content}] if text_content else []
            
            for att in image_atts:
                if att.base64_data:
                    mime = att.mime_type or 'image/jpeg'
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{att.base64_data}",
                            "detail": "auto",
                        }
                    })
                else:
                    # 没有 base64，添加占位说明
                    content.append({
                        "type": "text",
                        "text": f"[图片: {att.filename}，base64 数据不可用]"
                    })
            
            return content if content else text_content
        else:
            # 重建为纯文本格式
            text_parts = [text_content] if text_content else []
            
            for att in image_atts:
                if att.parsed_text and att.parsed_text not in ['', '[图片，无可识别文字内容]']:
                    text_parts.append(f"[图片 {att.filename} 的内容]\n{att.parsed_text}")
                elif att.parsed_text == '[图片，无可识别文字内容]':
                    text_parts.append(f"[图片: {att.filename}，无可识别文字内容]")
                else:
                    # 没有 OCR 结果
                    text_parts.append(f"[图片: {att.filename}，待 OCR 处理]")
            
            return '\n\n'.join(text_parts)
