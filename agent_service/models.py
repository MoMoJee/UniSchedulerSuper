from django.db import models
from django.contrib.auth.models import User
import json

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
    last_message_preview = models.CharField(max_length=200, blank=True, default="", help_text="最后一条消息预览")
    
    # ========== 历史总结相关字段 ==========
    summary_text = models.TextField(blank=True, default="", help_text="对话历史总结文本")
    summary_until_index = models.IntegerField(default=0, help_text="总结覆盖到的消息索引（不包含）")
    summary_tokens = models.IntegerField(default=0, help_text="总结文本的 token 数")
    summary_created_at = models.DateTimeField(null=True, blank=True, help_text="总结创建时间")
    is_summarizing = models.BooleanField(default=False, help_text="是否正在进行总结")
    # 总结历史版本，用于回滚时恢复之前的总结
    # 格式: [{"summary": "...", "until_index": 80, "tokens": 500, "created_at": "..."}, ...]
    summary_history = models.JSONField(default=list, blank=True, help_text="总结历史版本")
    
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
    
    def save_summary(self, summary_text: str, summarized_until: int, summary_tokens: int):
        """
        保存总结，并将旧总结存入历史版本
        Args:
            summary_text: 总结文本
            summarized_until: 总结覆盖到的消息索引
            summary_tokens: 总结 token 数
        """
        from django.utils import timezone
        
        # 如果有旧总结，先存入历史
        if self.summary_text and self.summary_until_index > 0:
            history = self.summary_history or []
            history.append({
                "summary": self.summary_text,
                "until_index": self.summary_until_index,
                "tokens": self.summary_tokens,
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
        self.summary_created_at = timezone.now()
        self.is_summarizing = False
        self.save(update_fields=['summary_text', 'summary_until_index', 'summary_tokens', 'summary_created_at', 'is_summarizing', 'summary_history'])
    
    def set_summarizing(self, is_summarizing: bool):
        """设置正在总结状态"""
        self.is_summarizing = is_summarizing
        self.save(update_fields=['is_summarizing'])
    
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
    支持会话级别存储和回滚同步清除
    """
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name='search_caches')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='search_result_caches')
    
    # 缓存的结果类型: event, to do, reminder, mixed (混合搜索)
    result_type = models.CharField(max_length=20, help_text="event/todo/reminder/mixed")
    
    # 编号 → UUID 映射 (JSON)
    # 格式: {"#1": {"uuid": "xxx", "type": "event"}, "#2": {"uuid": "yyy", "type": "to do"}}
    index_mapping = models.JSONField(default=dict, help_text="编号到UUID的映射")
    
    # 名称 → UUID 映射 (JSON) - 用于按标题匹配
    # 格式: {"会议": {"uuid": "xxx", "type": "event"}, ...}
    title_mapping = models.JSONField(default=dict, help_text="标题到UUID的映射")
    
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
