from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import json
import os
import uuid


def attachment_upload_to(instance, filename):
    """
    自定义附件文件存储路径和文件名。
    
    生成规则：attachments/YYYY/MM/DD/uuid_原文件名.ext
    使用 UUID 前缀避免文件名冲突，同时保留原文件名便于识别。
    """
    import os
    from django.utils import timezone
    
    # 提取文件扩展名
    ext = os.path.splitext(filename)[1].lower()  # 例如 '.png'
    # 生成唯一文件名：uuid前8位_原文件名
    unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
    # 返回完整路径：attachments/2026/02/17/abc12345_screenshot.png
    return timezone.now().strftime(f'attachments/%Y/%m/%d/{unique_filename}')


class AgentSession(models.Model):
    """
    Agent 会话记录
    存储用户的聊天会话信息，支持历史记录切换
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agent_sessions')
    session_id = models.CharField(max_length=200, unique=True, db_index=True, help_text="会话 ID (thread_id)")
    name = models.CharField(max_length=200, blank=True, default="", help_text="会话名称")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, help_text="是否为活跃会话")
    message_count = models.IntegerField(default=0, help_text="消息数量")
    last_message_preview = models.CharField(max_length=200, blank=True, default="", help_text="最后一条消息预览（用户消息）")
    
    # ========== 会话命名相关字段 ==========
    is_naming = models.BooleanField(default=False, help_text="是否正在自动命名")
    is_auto_named = models.BooleanField(default=False, help_text="是否已自动命名过")
    
    # ========== 历史总结相关字段 ==========
    summary_text = models.TextField(blank=True, default="", help_text="对话历史总结文本")
    summary_until_index = models.IntegerField(default=0, help_text="总结覆盖到的消息索引（不包含）")
    summary_tokens = models.IntegerField(default=0, help_text="总结文本的 token 数（LLM 真实返回值）")
    summary_input_tokens = models.IntegerField(default=0, help_text="总结时的 input_tokens（LLM 真实返回值，用于上下文计算）")
    summary_tokens_source = models.CharField(max_length=20, default='estimated', help_text="Token 数据来源: actual/estimated")
    summary_created_at = models.DateTimeField(null=True, blank=True, help_text="总结创建时间")
    is_summarizing = models.BooleanField(default=False, help_text="是否正在进行总结")
    # 总结历史版本，用于回滚时恢复之前的总结
    # 格式: [{"summary": "...", "until_index": 80, "tokens": 500, "created_at": "..."}, ...]
    summary_history = models.JSONField(default=list, blank=True, help_text="总结历史版本")
    
    # ========== 上下文使用量追踪字段（LLM 真实返回值）==========
    last_input_tokens = models.IntegerField(default=0, help_text="最近一次请求的 input_tokens（LLM 真实返回值）")
    last_input_tokens_source = models.CharField(max_length=20, default='estimated', help_text="Token 数据来源: actual/estimated")
    last_input_tokens_updated_at = models.DateTimeField(null=True, blank=True, help_text="最近一次更新时间")
    # 每轮对话的 Token 快照，用于回滚时恢复上下文使用量显示
    # 格式: {"0": {"input_tokens": 3949, "source": "actual", "timestamp": "2024-..."}, "1": {...}, ...}
    # 键为消息索引（字符串），值为该轮对话的 input_tokens 数据
    token_snapshots = models.JSONField(default=dict, blank=True, help_text="每轮对话的 Token 快照")
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = "Agent 会话"
        verbose_name_plural = "Agent 会话"

    def __str__(self):
        return f"{self.user.username}: {self.name or self.session_id}"
    
    @classmethod
    def get_or_create_session(cls, user, session_id=None, name=None):
        """
        获取或创建会话
        关键安全检查：验证 session_id 是否属于当前用户
        """
        import uuid
        if not session_id:
            session_id = f"user_{user.id}_{uuid.uuid4().hex[:8]}"
        
        # 先检查是否存在该 session_id
        existing = cls.objects.filter(session_id=session_id).first()
        if existing:
            # 安全检查：如果会话存在但不属于当前用户，创建新会话
            if existing.user_id != user.id:
                # 会话 ID 冲突，为当前用户生成新的会话 ID
                session_id = f"user_{user.id}_{uuid.uuid4().hex[:8]}"
                session = cls.objects.create(
                    session_id=session_id,
                    user=user,
                    name=name or f"对话 {cls.objects.filter(user=user).count() + 1}"
                )
                return session, True
            else:
                return existing, False
        
        # 会话不存在，创建新会话
        session = cls.objects.create(
            session_id=session_id,
            user=user,
            name=name or f"对话 {cls.objects.filter(user=user).count() + 1}"
        )
        return session, True
    
    def get_summary_metadata(self):
        """
        获取总结元数据（如果有）
        Returns:
            dict 或 None
        """
        if not self.summary_text:
            return None
        return {
            "summary": self.summary_text,
            "summarized_until": self.summary_until_index,
            "summary_tokens": self.summary_tokens,
            "created_at": self.summary_created_at.isoformat() if self.summary_created_at else None,
        }
    
    def save_summary(self, summary_text: str, summarized_until: int, summary_tokens: int, summary_input_tokens: int = 0, tokens_source: str = 'estimated'):
        """
        保存总结，并将旧总结存入历史版本
        Args:
            summary_text: 总结文本
            summarized_until: 总结覆盖到的消息索引
            summary_tokens: 总结输出 token 数（output_tokens）
            summary_input_tokens: 总结时的 input_tokens（用于上下文计算）
            tokens_source: Token 数据来源 ('actual' 或 'estimated')
        """
        from django.utils import timezone
        
        # 如果有旧总结，先存入历史
        if self.summary_text and self.summary_until_index > 0:
            history = self.summary_history or []
            history.append({
                "summary": self.summary_text,
                "until_index": self.summary_until_index,
                "tokens": self.summary_tokens,
                "input_tokens": self.summary_input_tokens,
                "tokens_source": self.summary_tokens_source,
                "created_at": self.summary_created_at.isoformat() if self.summary_created_at else None,
            })
            # 只保留最近 10 个历史版本，避免数据过大
            if len(history) > 10:
                history = history[-10:]
            self.summary_history = history
        
        # 保存新总结
        self.summary_text = summary_text
        self.summary_until_index = summarized_until
        self.summary_tokens = summary_tokens
        self.summary_input_tokens = summary_input_tokens
        self.summary_tokens_source = tokens_source
        self.summary_created_at = timezone.now()
        self.is_summarizing = False
        self.save(update_fields=[
            'summary_text', 'summary_until_index', 'summary_tokens', 
            'summary_input_tokens', 'summary_tokens_source',
            'summary_created_at', 'is_summarizing', 'summary_history'
        ])
    
    def set_summarizing(self, is_summarizing: bool):
        """设置正在总结状态"""
        self.is_summarizing = is_summarizing
        self.save(update_fields=['is_summarizing'])
    
    def update_context_tokens(self, input_tokens: int, tokens_source: str = 'actual'):
        """
        更新最近一次请求的上下文 Token 数（LLM 真实返回值）
        
        Args:
            input_tokens: LLM 返回的 input_tokens（包含所有上下文）
            tokens_source: Token 数据来源 ('actual' 或 'estimated')
        """
        from django.utils import timezone
        
        self.last_input_tokens = input_tokens
        self.last_input_tokens_source = tokens_source
        self.last_input_tokens_updated_at = timezone.now()
        self.save(update_fields=['last_input_tokens', 'last_input_tokens_source', 'last_input_tokens_updated_at'])
    
    def save_token_snapshot(self, message_index: int, input_tokens: int, tokens_source: str = 'actual'):
        """
        保存某轮对话的 Token 快照（用于回滚时恢复显示）
        
        Args:
            message_index: 消息索引（0-based）
            input_tokens: LLM 返回的 input_tokens
            tokens_source: Token 数据来源 ('actual' 或 'estimated')
        """
        from django.utils import timezone
        import logging
        logger = logging.getLogger(__name__)
        
        if self.token_snapshots is None:
            self.token_snapshots = {}
        
        # 使用字符串作为键（JSON 要求）
        snapshot_key = str(message_index)
        self.token_snapshots[snapshot_key] = {
            "input_tokens": input_tokens,
            "source": tokens_source,
            "timestamp": timezone.now().isoformat()
        }
        
        self.save(update_fields=['token_snapshots'])
        logger.debug(f"[Token快照存储] session={self.session_id}, index={message_index}, tokens={input_tokens}, 当前快照数={len(self.token_snapshots)}")
    
    def get_token_snapshot(self, message_index: int) -> dict:
        """
        获取某个消息索引的 Token 快照
        
        Args:
            message_index: 消息索引（0-based）
            
        Returns:
            包含 input_tokens, source, timestamp 的字典，如果不存在则返回 None
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not self.token_snapshots:
            logger.debug(f"[Token快照读取] session={self.session_id}, index={message_index}: token_snapshots 为空")
            return None
        
        snapshot_key = str(message_index)
        snapshot = self.token_snapshots.get(snapshot_key)
        
        if snapshot:
            logger.debug(f"[Token快照读取] session={self.session_id}, index={message_index}: 找到快照 tokens={snapshot.get('input_tokens')}")
        else:
            available_keys = list(self.token_snapshots.keys())
            logger.debug(f"[Token快照读取] session={self.session_id}, index={message_index}: 未找到，可用索引={available_keys}")
        
        return snapshot
    
    def cleanup_token_snapshots(self, keep_until_index: int):
        """
        清理指定索引之后的 Token 快照（回滚时调用）
        
        Args:
            keep_until_index: 保留到这个索引之前的快照（不包含此索引）
        """
        if not self.token_snapshots:
            return
        
        # 删除 >= keep_until_index 的快照
        keys_to_delete = [k for k in self.token_snapshots.keys() if int(k) >= keep_until_index]
        for key in keys_to_delete:
            del self.token_snapshots[key]
        
        self.save(update_fields=['token_snapshots'])
    
    def rollback_summary(self, target_message_index: int) -> bool:
        """
        回滚总结到适合目标消息索引的版本
        
        Args:
            target_message_index: 回滚后的消息数量
            
        Returns:
            是否执行了回滚
        """
        from django.utils import timezone
        from datetime import datetime
        
        # 如果当前没有总结，不需要回滚
        if not self.summary_text and self.summary_until_index == 0:
            return False
        
        # 如果目标位置 >= 当前总结覆盖位置，不需要回滚
        if target_message_index >= self.summary_until_index:
            return False
        
        # 从历史中找到适合的版本
        # 找 until_index <= target_message_index 的最新版本
        history = self.summary_history or []
        suitable_version = None
        
        for version in reversed(history):
            if version.get('until_index', 0) <= target_message_index:
                suitable_version = version
                break
        
        if suitable_version:
            # 恢复到历史版本
            self.summary_text = suitable_version.get('summary', '')
            self.summary_until_index = suitable_version.get('until_index', 0)
            self.summary_tokens = suitable_version.get('tokens', 0)
            created_at_str = suitable_version.get('created_at')
            if created_at_str:
                try:
                    self.summary_created_at = datetime.fromisoformat(created_at_str)
                except:
                    self.summary_created_at = None
            else:
                self.summary_created_at = None
            
            # 从历史中移除被恢复版本之后的所有版本（包括被恢复的版本）
            version_index = history.index(suitable_version)
            self.summary_history = history[:version_index]
        else:
            # 没有合适的历史版本，清除总结
            self.summary_text = ""
            self.summary_until_index = 0
            self.summary_tokens = 0
            self.summary_created_at = None
            self.summary_history = []
        
        self.is_summarizing = False
        self.save(update_fields=['summary_text', 'summary_until_index', 'summary_tokens', 'summary_created_at', 'is_summarizing', 'summary_history'])
        return True


class UserMemory(models.Model):
    """
    用户核心画像 (Core Profile)
    存储用户的长期偏好、身份信息等结构化数据。
    【旧模型，保留用于数据迁移】
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='memory')
    profile_data = models.JSONField(default=dict, help_text="核心画像数据 (JSON)")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Memory Profile for {self.user.username}"

class MemoryItem(models.Model):
    """
    细节记忆 (Detailed Memories)
    存储用户的具体对话片段、事实性信息等。
    【旧模型，保留用于数据迁移，新记忆使用 UserPersonalInfo】
    """
    memory = models.ForeignKey(UserMemory, on_delete=models.CASCADE, related_name='items', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memory_items')
    content = models.TextField(help_text="记忆内容")
    category = models.CharField(max_length=50, default='general', help_text="类别 (preference, fact, plan, general)")
    importance = models.IntegerField(default=1, help_text="重要性 (1-5)")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-importance', '-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.content[:50]}..."


# ==========================================
# 新记忆系统模型 (Phase 1)
# ==========================================

class UserPersonalInfo(models.Model):
    """
    用户个人信息记忆
    存储用户的基本信息、偏好等键值对数据
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='personal_infos')
    key = models.CharField(max_length=100, help_text="信息键，如 '姓名', '生日', '饮食偏好'")
    value = models.TextField(help_text="信息值")
    description = models.TextField(blank=True, default="", help_text="补充说明")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'key']
        ordering = ['-updated_at']
        verbose_name = "用户个人信息"
        verbose_name_plural = "用户个人信息"
    
    def __str__(self):
        return f"{self.user.username}: {self.key} = {self.value[:30]}..."


class DialogStyle(models.Model):
    """
    对话风格/角色设定
    支持结构化配置和自定义指令
    """
    # 语气选项
    TONE_CHOICES = [
        ('neutral', '中性'),
        ('formal', '正式'),
        ('casual', '轻松'),
        ('professional', '专业'),
        ('friendly', '友好'),
    ]
    
    # 详细程度选项
    VERBOSITY_CHOICES = [
        ('concise', '简洁'),
        ('normal', '适中'),
        ('detailed', '详细'),
    ]
    
    # 语言选项
    LANGUAGE_CHOICES = [
        ('zh-CN', '简体中文'),
        ('en', 'English'),
        ('auto', '自动检测'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='dialog_style')
    
    # 结构化字段
    tone = models.CharField(max_length=20, choices=TONE_CHOICES, default='neutral', help_text="语气风格")
    verbosity = models.CharField(max_length=20, choices=VERBOSITY_CHOICES, default='normal', help_text="详细程度")
    language = models.CharField(max_length=20, choices=LANGUAGE_CHOICES, default='zh-CN', help_text="语言偏好")
    custom_instructions = models.TextField(blank=True, default='', help_text="自定义指令")
    
    # 自定义选项（JSON 存储用户添加的选项）
    custom_tones = models.JSONField(default=list, blank=True, help_text="用户自定义的语气选项")
    custom_verbosities = models.JSONField(default=list, blank=True, help_text="用户自定义的详细程度选项")
    custom_languages = models.JSONField(default=list, blank=True, help_text="用户自定义的语言选项")
    
    # 记忆优化设置
    memory_batch_size = models.IntegerField(default=20, help_text="记忆优化批次大小")
    
    # Agent 上下文优化开关（详细配置存储在 UserData.agent_optimization_config）
    enable_context_optimization = models.BooleanField(
        default=True, 
        help_text="是否启用 Agent 上下文优化（Token 管理、智能总结等）"
    )

    # 保留 content 字段用于生成完整模板
    content = models.TextField(blank=True, help_text="完整的对话风格模板（自动生成）")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # 默认模板基础
    DEFAULT_TEMPLATE = """你是一个智能日程管理助手。
你的职责是帮助用户管理日程、提醒、待办事项。
回答风格：简洁明了，友好专业。
当需要执行操作时，使用可用的工具完成任务。
如果用户提出了复杂的多步骤任务，你可以使用工作流规则来指导执行顺序。"""
    
    class Meta:
        verbose_name = "对话风格"
        verbose_name_plural = "对话风格"
    
    def __str__(self):
        return f"DialogStyle for {self.user.username}"
    
    def generate_content(self):
        """根据结构化设置生成完整的对话风格模板"""
        tone_map = dict(self.TONE_CHOICES)
        verbosity_map = dict(self.VERBOSITY_CHOICES)
        language_map = dict(self.LANGUAGE_CHOICES)
        
        tone_text = tone_map.get(self.tone, self.tone)
        verbosity_text = verbosity_map.get(self.verbosity, self.verbosity)
        language_text = language_map.get(self.language, self.language)
        
        content = f"""你是一个智能日程管理助手。
你的职责是帮助用户管理日程、提醒、待办事项。

【对话风格】
- 语气风格：{tone_text}
- 回答详细程度：{verbosity_text}
- 使用语言：{language_text}

当需要执行操作时，使用可用的工具完成任务。
如果用户提出了复杂的多步骤任务，你可以使用工作流规则来指导执行顺序。"""
        
        if self.custom_instructions:
            content += f"\n\n【自定义指令】\n{self.custom_instructions}"
        
        return content
    
    def save(self, *args, **kwargs):
        """保存时自动生成 content"""
        self.content = self.generate_content()
        super().save(*args, **kwargs)
    
    @classmethod
    def get_or_create_default(cls, user):
        """获取用户的对话风格，如果不存在则创建默认配置"""
        style, created = cls.objects.get_or_create(
            user=user,
            defaults={
                'tone': 'neutral',
                'verbosity': 'normal',
                'language': 'zh-CN',
                'custom_instructions': '',
            }
        )
        if created:
            style.save()  # 触发 generate_content
        return style
    
    def get_all_tone_choices(self):
        """获取所有语气选项（包括自定义）"""
        choices = list(self.TONE_CHOICES)
        for custom in self.custom_tones:
            if isinstance(custom, dict) and 'value' in custom and 'label' in custom:
                choices.append((custom['value'], custom['label']))
        return choices
    
    def get_all_verbosity_choices(self):
        """获取所有详细程度选项（包括自定义）"""
        choices = list(self.VERBOSITY_CHOICES)
        for custom in self.custom_verbosities:
            if isinstance(custom, dict) and 'value' in custom and 'label' in custom:
                choices.append((custom['value'], custom['label']))
        return choices
    
    def get_all_language_choices(self):
        """获取所有语言选项（包括自定义）"""
        choices = list(self.LANGUAGE_CHOICES)
        for custom in self.custom_languages:
            if isinstance(custom, dict) and 'value' in custom and 'label' in custom:
                choices.append((custom['value'], custom['label']))
        return choices


class WorkflowRule(models.Model):
    """
    工作流程规则
    纯文本的任务执行流程指导
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='workflow_rules')
    name = models.CharField(max_length=100, help_text="规则名称，如 '创建日程流程'")
    trigger = models.CharField(max_length=200, help_text="触发条件描述，如 '当用户要求创建日程时'")
    steps = models.TextField(help_text="纯文本步骤描述")
    is_active = models.BooleanField(default=True, help_text="是否启用")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = "工作流规则"
        verbose_name_plural = "工作流规则"
    
    def __str__(self):
        status = "✓" if self.is_active else "✗"
        return f"[{status}] {self.user.username}: {self.name}"


class SessionTodoItem(models.Model):
    """
    会话级 TODO 列表
    支持跨对话和回滚
    """
    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('in_progress', '进行中'),
        ('done', '已完成'),
    ]
    
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name='todo_items')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='session_todos')
    title = models.CharField(max_length=200, help_text="TODO 标题")
    description = models.TextField(blank=True, default="", help_text="详细描述")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', help_text="状态")
    order = models.IntegerField(default=0, help_text="排序顺序")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['order', 'created_at']
        verbose_name = "会话 TODO"
        verbose_name_plural = "会话 TODO"
    
    def __str__(self):
        status_icons = {'pending': '☐', 'in_progress': '⏳', 'done': '✅'}
        icon = status_icons.get(self.status, '?')
        return f"{icon} {self.title}"
    
    def get_status_display_icon(self):
        """获取状态图标"""
        status_icons = {'pending': '☐', 'in_progress': '⏳', 'done': '✅'}
        return status_icons.get(self.status, '?')


class SessionTodoSnapshot(models.Model):
    """
    TODO 列表快照
    用于回滚同步（类似日程回滚机制）
    """
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name='todo_snapshots')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='todo_snapshots')
    checkpoint_id = models.CharField(max_length=100, db_index=True, help_text="对应的对话检查点ID")
    snapshot_data = models.TextField(help_text="JSON: 该检查点时刻的 TODO 列表完整状态")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "TODO 快照"
        verbose_name_plural = "TODO 快照"
    
    def __str__(self):
        return f"Snapshot {self.checkpoint_id} for session {self.session_id}"
    
    def get_todos_data(self) -> list:
        """解析并返回 TODO 数据列表"""
        try:
            return json.loads(self.snapshot_data)
        except json.JSONDecodeError:
            return []
    
    @classmethod
    def create_snapshot(cls, session, checkpoint_id):
        """为当前会话创建 TODO 快照"""
        todos = SessionTodoItem.objects.filter(session=session)
        snapshot_data = json.dumps([{
            'id': t.id,
            'title': t.title,
            'description': t.description,
            'status': t.status,
            'order': t.order
        } for t in todos], ensure_ascii=False)
        
        return cls.objects.create(
            session=session,
            user=session.user,
            checkpoint_id=checkpoint_id,
            snapshot_data=snapshot_data
        )


class AgentTransaction(models.Model):
    """
    Agent 事务记录
    用于追踪 Agent 执行的操作，支持回滚功能。
    """
    session_id = models.CharField(max_length=200, db_index=True, help_text="会话 ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agent_transactions', null=True, blank=True)
    action_type = models.CharField(max_length=100, help_text="操作类型 (create_event, delete_todo, etc.)")
    description = models.TextField(blank=True, default="", help_text="操作描述")
    revision_id = models.IntegerField(null=True, blank=True, help_text="django-reversion 的 Revision ID")
    metadata = models.JSONField(default=dict, help_text="额外的元数据")
    is_rolled_back = models.BooleanField(default=False, help_text="是否已回滚")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Agent 事务"
        verbose_name_plural = "Agent 事务"

    def __str__(self):
        return f"[{self.session_id}] {self.action_type} at {self.created_at}"


# ==========================================
# Planner 工具优化模型
# ==========================================

class SearchResultCache(models.Model):
    """
    搜索结果缓存 - 存储编号到UUID的映射
    
    支持智能去重和会话级持久化:
    - 同一个UUID在不同搜索中复用相同编号
    - 使用LRU策略限制缓存大小
    - 会话级别存储，支持回滚同步清除
    """
    # 最大缓存项目数
    MAX_CACHE_SIZE = 100
    
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name='search_caches')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='search_result_caches')
    
    # 缓存的结果类型: event, todo, reminder, mixed (混合搜索)
    result_type = models.CharField(max_length=20, help_text="event/todo/reminder/mixed")
    
    # 编号 → UUID 映射 (JSON)
    # 格式: {"#1": {"uuid": "xxx", "type": "event", "title": "会议", "last_seen": 1738483200}, ...}
    index_mapping = models.JSONField(default=dict, help_text="编号到UUID的映射")
    
    # UUID → 编号 反向映射 (JSON) - 用于快速查找和去重
    # 格式: {"uuid-xxx": "#1", "uuid-yyy": "#2", ...}
    uuid_to_index = models.JSONField(default=dict, help_text="UUID到编号的反向映射")
    
    # 名称 → UUID 映射 (JSON) - 用于按标题匹配
    # 格式: {"会议": {"uuid": "xxx", "type": "event"}, ...}
    title_mapping = models.JSONField(default=dict, help_text="标题到UUID的映射")
    
    # 下一个可用编号（从1开始递增）
    next_index = models.IntegerField(default=1, help_text="下一个可用编号")
    
    # 最后一次查询的筛选条件（用于调试）
    query_params = models.JSONField(default=dict, help_text="查询参数")
    
    # 关联的检查点ID（用于回滚同步，可选）
    checkpoint_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "搜索结果缓存"
        verbose_name_plural = "搜索结果缓存"
        indexes = [
            models.Index(fields=['session', 'result_type']),
            models.Index(fields=['session', 'updated_at']),
        ]
    
    def __str__(self):
        return f"Cache for {self.session.session_id} ({self.result_type})"
    
    def get_uuid_by_index(self, index: str) -> dict:
        """根据编号获取UUID和类型"""
        return self.index_mapping.get(index, None)
    
    def get_index_by_uuid(self, uuid: str) -> str:
        """根据UUID获取编号"""
        return self.uuid_to_index.get(uuid, None)
    
    def get_uuid_by_title(self, title: str) -> dict:
        """根据标题获取UUID和类型（模糊匹配）"""
        # 精确匹配
        if title in self.title_mapping:
            return self.title_mapping[title]
        # 模糊匹配
        for cached_title, info in self.title_mapping.items():
            if title in cached_title or cached_title in title:
                return info
        return None
    
    def cleanup_lru(self):
        """
        清理最久未使用的缓存项，保持在 MAX_CACHE_SIZE 以内
        """
        if len(self.index_mapping) <= self.MAX_CACHE_SIZE:
            return
        
        # 按 last_seen 排序
        sorted_items = sorted(
            self.index_mapping.items(),
            key=lambda x: x[1].get('last_seen', 0)
        )
        
        # 计算需要删除的数量
        to_delete = len(self.index_mapping) - self.MAX_CACHE_SIZE
        
        # 删除最旧的项目
        for idx, (index_key, info) in enumerate(sorted_items):
            if idx >= to_delete:
                break
            item_uuid = info.get('uuid')
            item_title = info.get('title', '')
            
            # 从各个映射中删除
            if index_key in self.index_mapping:
                del self.index_mapping[index_key]
            if item_uuid and item_uuid in self.uuid_to_index:
                del self.uuid_to_index[item_uuid]
            if item_title and item_title in self.title_mapping:
                del self.title_mapping[item_title]


class EventGroupCache(models.Model):
    """
    日程组名称缓存
    自动建立名称→UUID映射，减少用户输入复杂度
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='event_group_cache')
    
    # 名称 → UUID 映射
    # 格式: {"工作": "uuid-xxx", "个人": "uuid-yyy", ...}
    name_to_uuid = models.JSONField(default=dict, help_text="名称到UUID的映射")
    
    # UUID → 完整信息 反向映射（用于展示）
    # 格式: {"uuid-xxx": {"name": "工作", "color": "#FF5733", "description": "..."}, ...}
    uuid_to_info = models.JSONField(default=dict, help_text="UUID到完整信息的映射")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "日程组缓存"
        verbose_name_plural = "日程组缓存"
    
    def __str__(self):
        return f"EventGroupCache for {self.user.username}"
    
    def get_uuid_by_name(self, name: str) -> str:
        """根据名称获取UUID"""
        return self.name_to_uuid.get(name, None)
    
    def get_info_by_uuid(self, uuid: str) -> dict:
        """根据UUID获取完整信息"""
        return self.uuid_to_info.get(uuid, None)
    
    def get_name_by_uuid(self, uuid: str) -> str:
        """根据UUID获取名称"""
        info = self.uuid_to_info.get(uuid, {})
        return info.get('name', '')
    
    def is_stale(self, ttl_seconds: int = 300) -> bool:
        """检查缓存是否过期（默认5分钟）"""
        from django.utils import timezone
        from datetime import timedelta
        return timezone.now() - self.updated_at > timedelta(seconds=ttl_seconds)
    
    def is_valid(self, ttl_seconds: int = 3600) -> bool:
        """检查缓存是否有效（未过期）"""
        return not self.is_stale(ttl_seconds)
    
    def refresh_from_db_data(self, event_groups: list):
        """从日程组数据刷新缓存"""
        self.name_to_uuid = {}
        self.uuid_to_info = {}
        
        for group in event_groups:
            group_id = group.get('id', '')
            group_name = group.get('name', '')
            if group_id and group_name:
                self.name_to_uuid[group_name] = group_id
                self.uuid_to_info[group_id] = {
                    'name': group_name,
                    'color': group.get('color', ''),
                    'description': group.get('description', '')
                }
        
        self.save()


class ShareGroupCache(models.Model):
    """
    分享组名称缓存
    自动建立名称→ID映射，减少用户输入复杂度
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='share_group_cache')
    
    # 名称 → ID 映射
    # 格式: {"工作协作组": "share_group_xxx", "家庭日程": "share_group_yyy", ...}
    name_to_id = models.JSONField(default=dict, help_text="名称到ID的映射")
    
    # ID → 完整信息 反向映射（用于展示）
    # 格式: {"share_group_xxx": {"share_group_name": "工作协作组", "role": "owner", ...}, ...}
    id_to_info = models.JSONField(default=dict, help_text="ID到完整信息的映射")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "分享组缓存"
        verbose_name_plural = "分享组缓存"
    
    def __str__(self):
        return f"ShareGroupCache for {self.user.username}"
    
    def get_id_by_name(self, name: str) -> str:
        """根据名称获取ID"""
        return self.name_to_id.get(name.lower(), None)
    
    def get_info_by_id(self, share_group_id: str) -> dict:
        """根据ID获取完整信息"""
        return self.id_to_info.get(share_group_id, None)
    
    def get_name_by_id(self, share_group_id: str) -> str:
        """根据ID获取名称"""
        info = self.id_to_info.get(share_group_id, {})
        return info.get('share_group_name', '')
    
    def is_stale(self, ttl_seconds: int = 300) -> bool:
        """检查缓存是否过期（默认5分钟）"""
        from django.utils import timezone
        from datetime import timedelta
        return timezone.now() - self.updated_at > timedelta(seconds=ttl_seconds)
    
    def is_valid(self, ttl_seconds: int = 3600) -> bool:
        """检查缓存是否有效（未过期）"""
        return not self.is_stale(ttl_seconds)


# ==========================================
# Quick Action 快速操作模型
# ==========================================

import uuid as uuid_module

class QuickActionTask(models.Model):
    """
    快速操作任务
    
    用于追踪通过 HTTP API 触发的快速操作执行状态。
    支持异步执行和长轮询查询结果。
    """
    
    # 状态选项
    STATUS_CHOICES = [
        ('pending', '等待执行'),
        ('processing', '执行中'),
        ('success', '成功'),
        ('failed', '失败'),
        ('timeout', '超时'),
    ]
    
    # 结果类型选项
    RESULT_TYPE_CHOICES = [
        ('action_completed', '操作完成'),
        ('need_clarification', '需要补充信息'),
        ('error', '错误'),
    ]
    
    task_id = models.UUIDField(primary_key=True, default=uuid_module.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quick_action_tasks')
    
    # 输入
    input_text = models.TextField(verbose_name="用户输入", help_text="用户的快速操作指令")
    
    # 状态
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES,
        default='pending', 
        db_index=True,
        help_text="任务执行状态"
    )
    
    # 结果类型
    result_type = models.CharField(
        max_length=30, 
        choices=RESULT_TYPE_CHOICES,
        blank=True,
        help_text="结果类型：action_completed/need_clarification/error"
    )
    
    # 结果详情（JSON）
    # 格式: {"message": "...", "details": {...}, "items_affected": [...]}
    result = models.JSONField(
        null=True, 
        blank=True,
        help_text="执行结果详情"
    )
    
    # 执行追踪
    # 格式: [{"tool": "search_items", "args": {...}, "result": {...}, "timestamp": "..."}, ...]
    tool_calls = models.JSONField(
        default=list,
        help_text="工具调用记录"
    )
    agent_reasoning = models.TextField(
        blank=True,
        help_text="Agent 推理过程"
    )
    
    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True, help_text="开始执行时间")
    completed_at = models.DateTimeField(null=True, blank=True, help_text="完成时间")
    
    # Token 消耗（按用户配置的模型计费）
    input_tokens = models.IntegerField(default=0, help_text="输入 token 数")
    output_tokens = models.IntegerField(default=0, help_text="输出 token 数")
    total_cost = models.FloatField(default=0.0, help_text="总成本 (CNY)")
    model_used = models.CharField(max_length=100, blank=True, help_text="使用的模型名称")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "快速操作任务"
        verbose_name_plural = "快速操作任务"
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.input_text[:30]}... - {self.status}"
    
    def mark_processing(self):
        """标记为执行中"""
        from django.utils import timezone
        self.status = 'processing'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    def mark_completed(self, result_type: str, result: dict, 
                       input_tokens: int = 0, output_tokens: int = 0,
                       total_cost: float = 0.0, model_used: str = '',
                       agent_reasoning: str = ''):
        """标记为完成（成功或失败）"""
        from django.utils import timezone
        self.status = 'success' if result_type == 'action_completed' else 'failed'
        self.result_type = result_type
        self.result = result
        self.completed_at = timezone.now()
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_cost = total_cost
        self.model_used = model_used
        self.agent_reasoning = agent_reasoning
        self.save()
    
    def mark_timeout(self):
        """标记为超时"""
        from django.utils import timezone
        self.status = 'timeout'
        self.result_type = 'error'
        self.result = {'message': '执行超时，请稍后重试', 'error': 'timeout'}
        self.completed_at = timezone.now()
        self.save()
    
    def add_tool_call(self, tool_name: str, args: dict, result: dict):
        """添加工具调用记录"""
        from django.utils import timezone
        call_record = {
            'tool': tool_name,
            'args': args,
            'result': result,
            'timestamp': timezone.now().isoformat()
        }
        if not isinstance(self.tool_calls, list):
            self.tool_calls = []
        self.tool_calls.append(call_record)
        self.save(update_fields=['tool_calls'])
    
    def get_execution_time_ms(self) -> int:
        """获取执行时间（毫秒）"""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return 0
    
    def to_response_dict(self) -> dict:
        """转换为 API 响应格式"""
        return {
            'task_id': str(self.task_id),
            'status': self.status,
            'result_type': self.result_type,
            'result': self.result,
            'input_text': self.input_text,
            'tool_calls_count': len(self.tool_calls) if self.tool_calls else 0,
            'execution_time_ms': self.get_execution_time_ms(),
            'tokens': {
                'input': self.input_tokens,
                'output': self.output_tokens,
                'cost': self.total_cost,
                'model': self.model_used
            },
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


# ==========================================
# 统一附件系统
# ==========================================

class SessionAttachment(models.Model):
    """
    会话附件模型
    支持外部文件上传和内部元素（events/todos/reminders/工作流）作为附件
    
    设计要点：
    - events/todos/reminders 存储在 UserData (JSON)，不是独立 ORM 模型
    - 内部元素通过 internal_snapshot 保存快照，防止数据变更后信息丢失
    - 双格式存储: base64_data (vision) + parsed_text (非 vision 降级)
    - 软删除支持: 回滚时标记删除，7天后物理清理
    """
    
    # ========== 类型定义 ==========
    TYPE_CHOICES = [
        ('image', '图片'),
        ('pdf', 'PDF文档'),
        ('word', 'Word文档'),
        ('excel', 'Excel表格'),
        ('workflow', '工作流规则'),
        ('event', '日程事件'),
        ('todo', '待办事项'),
        ('reminder', '提醒'),
    ]
    
    # 文件类型 MIME 白名单
    ALLOWED_MIME_TYPES = {
        'image/jpeg': 'image',
        'image/png': 'image',
        'image/gif': 'image',
        'image/webp': 'image',
        'application/pdf': 'pdf',
        'application/msword': 'word',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'word',
        'application/vnd.ms-excel': 'excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'excel',
    }
    
    # 文件大小上限 (20MB)
    MAX_FILE_SIZE = 20 * 1024 * 1024
    
    # ========== 基础信息 ==========
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='session_attachments')
    session_id = models.CharField(max_length=200, db_index=True, help_text="关联的 AgentSession.session_id")
    
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, help_text="附件类型")
    filename = models.CharField(max_length=255, help_text="文件名或元素标题")
    
    # ========== 消息关联 ==========
    message_index = models.IntegerField(
        null=True, 
        blank=True, 
        help_text="附件被发送时的消息索引（LangGraph messages 数组索引）"
    )
    sent_at = models.DateTimeField(null=True, blank=True, help_text="发送时间")
    
    # ========== 文件存储（外部文件） ==========
    file = models.FileField(
        upload_to=attachment_upload_to, 
        null=True, 
        blank=True, 
        help_text="原始文件"
    )
    file_size = models.BigIntegerField(default=0, help_text="文件大小（字节）")
    mime_type = models.CharField(max_length=100, blank=True, default='', help_text="MIME 类型")
    thumbnail = models.ImageField(
        upload_to='attachments/thumbs/%Y/%m/%d/',
        null=True,
        blank=True,
        help_text="缩略图"
    )
    
    # ========== 多模态支持 ==========
    base64_data = models.TextField(
        blank=True, 
        default='', 
        help_text="Base64 编码的图片数据（用于 vision 模型）"
    )
    
    # ========== 降级方案 ==========
    parsed_text = models.TextField(
        blank=True, 
        default='', 
        help_text="解析后的文本内容（OCR/文档提取，用于非 vision 模型）"
    )
    parse_status = models.CharField(
        max_length=20,
        default='pending',
        choices=[
            ('pending', '待处理'),
            ('processing', '处理中'),
            ('completed', '已完成'),
            ('failed', '失败'),
        ],
        help_text="解析状态"
    )
    parse_error = models.TextField(blank=True, default='', help_text="解析错误信息")
    
    # ========== 内部元素引用 ==========
    internal_type = models.CharField(
        max_length=20, 
        blank=True, 
        default='', 
        help_text="内部元素类型：event, todo, reminder, workflow"
    )
    internal_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="内部元素 ID（UserData JSON 中的 id 字段，或 WorkflowRule.id）"
    )
    internal_snapshot = models.JSONField(
        default=dict, 
        blank=True, 
        help_text="内部元素的快照数据（防止元素被删除后无法回溯）"
    )
    
    # ========== 发送记录 ==========
    sent_as_format = models.CharField(
        max_length=20, 
        blank=True, 
        default='', 
        help_text="实际发送格式：base64, text, markdown"
    )
    sent_with_model = models.CharField(
        max_length=100, 
        blank=True, 
        default='', 
        help_text="发送时使用的模型 ID"
    )
    
    # ========== 软删除支持 ==========
    is_deleted = models.BooleanField(default=False, help_text="是否已软删除")
    deleted_at = models.DateTimeField(null=True, blank=True, help_text="软删除时间")
    deleted_with_message_index = models.IntegerField(
        null=True, 
        blank=True, 
        help_text="回滚时关联删除的消息索引"
    )
    deleted_reason = models.CharField(
        max_length=50, 
        blank=True, 
        default='', 
        help_text="删除原因：rollback, manual, expired"
    )
    
    # ========== 时间戳 ==========
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "会话附件"
        verbose_name_plural = "会话附件"
        indexes = [
            models.Index(fields=['session_id', 'is_deleted']),
            models.Index(fields=['user', 'is_deleted']),
            models.Index(fields=['deleted_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username}: {self.filename} ({self.type})"
    
    # ========== 属性 ==========
    
    @property
    def can_restore(self):
        """是否可以恢复（7天内的软删除附件）"""
        if not self.is_deleted or not self.deleted_at:
            return False
        grace_period = timedelta(days=7)
        return timezone.now() - self.deleted_at < grace_period
    
    @property
    def is_internal(self):
        """是否为内部元素附件"""
        return self.type in ('event', 'todo', 'reminder', 'workflow')
    
    @property
    def is_file_attachment(self):
        """是否为外部文件附件"""
        return self.type in ('image', 'pdf', 'word', 'excel')
    
    @property
    def is_ready(self):
        """内容是否已解析完成，可以发送"""
        if self.is_internal:
            return True  # 内部元素无需异步解析
        return self.parse_status == 'completed'
    
    # ========== 格式化方法 ==========
    
    def get_formatted_content(self, model_supports_vision=False):
        """
        根据模型能力返回格式化内容
        
        Args:
            model_supports_vision: 当前模型是否支持 vision
            
        Returns:
            dict: {"type": "base64"|"text"|"markdown", "content": str, "metadata": dict}
        """
        if self.is_internal:
            # 内部元素始终返回 Markdown
            content = self.parsed_text or self._format_internal_element()
            return {
                "type": "markdown",
                "content": content,
                "metadata": {
                    "internal_type": self.internal_type,
                    "internal_id": self.internal_id,
                    "filename": self.filename,
                }
            }
        
        # 外部文件
        if model_supports_vision and self.base64_data and self.type == 'image':
            return {
                "type": "base64",
                "content": self.base64_data,
                "metadata": {
                    "filename": self.filename,
                    "mime_type": self.mime_type,
                }
            }
        else:
            return {
                "type": "text",
                "content": self.parsed_text or f"[文件: {self.filename}，内容未解析]",
                "metadata": {
                    "filename": self.filename,
                    "original_type": self.type,
                }
            }
    
    def _format_internal_element(self):
        """格式化内部元素为 Markdown"""
        snapshot = self.internal_snapshot or {}
        
        if self.internal_type == 'event':
            title = snapshot.get('title', '无标题事件')
            start = snapshot.get('start', '')
            end = snapshot.get('end', '')
            desc = snapshot.get('description', '')
            location = snapshot.get('location', '')
            
            md = f"### 📅 {title}\n"
            md += f"- **时间**: {start} ~ {end}\n"
            if location:
                md += f"- **地点**: {location}\n"
            if desc:
                md += f"- **描述**: {desc}\n"
            return md
        
        elif self.internal_type == 'todo':
            title = snapshot.get('title', '无标题待办')
            status = snapshot.get('status', 'pending')
            due_date = snapshot.get('due_date', '')
            desc = snapshot.get('description', '')
            importance = snapshot.get('importance', '')
            urgency = snapshot.get('urgency', '')
            
            status_map = {'pending': '待完成', 'in-progress': '进行中', 'completed': '已完成', 'cancelled': '已取消'}
            icon = '✅' if status == 'completed' else '⬜'
            
            md = f"### {icon} {title}\n"
            md += f"- **状态**: {status_map.get(status, status)}\n"
            if due_date:
                md += f"- **截止时间**: {due_date}\n"
            if importance:
                md += f"- **重要性**: {importance}\n"
            if urgency:
                md += f"- **紧急度**: {urgency}\n"
            if desc:
                md += f"- **描述**: {desc}\n"
            return md
        
        elif self.internal_type == 'reminder':
            title = snapshot.get('title', '无标题提醒')
            trigger_time = snapshot.get('trigger_time', '')
            content = snapshot.get('content', '')
            priority = snapshot.get('priority', 'normal')
            
            md = f"### ⏰ {title}\n"
            md += f"- **提醒时间**: {trigger_time}\n"
            md += f"- **优先级**: {priority}\n"
            if content:
                md += f"- **内容**: {content}\n"
            return md
        
        elif self.internal_type == 'workflow':
            name = snapshot.get('name', '工作流规则')
            trigger = snapshot.get('trigger', '')
            steps = snapshot.get('steps', '')
            
            md = f"### 🔄 {name}\n"
            md += f"**触发条件**: {trigger}\n"
            md += f"**执行步骤**: {steps}\n"
            return md
        
        return f"[{self.internal_type}: {self.filename}]"
    
    # ========== 生命周期方法 ==========
    
    def soft_delete(self, reason='manual', message_index=None):
        """软删除附件"""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_reason = reason
        if message_index is not None:
            self.deleted_with_message_index = message_index
        self.save(update_fields=[
            'is_deleted', 'deleted_at', 'deleted_reason', 'deleted_with_message_index'
        ])
    
    def restore(self):
        """恢复软删除的附件"""
        if not self.can_restore:
            return False
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_reason = ''
        self.deleted_with_message_index = None
        self.save(update_fields=[
            'is_deleted', 'deleted_at', 'deleted_reason', 'deleted_with_message_index'
        ])
        return True
    
    def hard_delete(self):
        """物理删除（包括文件）"""
        # 删除原始文件
        if self.file:
            try:
                self.file.delete(save=False)
            except Exception:
                pass
        
        # 删除缩略图
        if self.thumbnail:
            try:
                self.thumbnail.delete(save=False)
            except Exception:
                pass
        
        # 删除数据库记录
        self.delete()
    
    def to_api_dict(self):
        """转换为 API 响应格式"""
        result = {
            'id': self.id,
            'type': self.type,
            'filename': self.filename,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'parse_status': self.parse_status,
            'is_internal': self.is_internal,
            'created_at': self.created_at.isoformat(),
        }
        
        if self.is_internal:
            result['internal_type'] = self.internal_type
            result['internal_id'] = self.internal_id
            result['preview'] = (self.parsed_text or self._format_internal_element())[:200]
        
        if self.file:
            result['file_url'] = self.file.url
        if self.thumbnail:
            result['thumbnail_url'] = self.thumbnail.url
        
        if self.message_index is not None:
            result['message_index'] = self.message_index
            result['sent_at'] = self.sent_at.isoformat() if self.sent_at else None
        
        return result