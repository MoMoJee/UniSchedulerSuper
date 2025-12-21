from django.db import models
from django.contrib.auth.models import User

class UserMemory(models.Model):
    """
    用户核心画像 (Core Profile)
    存储用户的长期偏好、身份信息等结构化数据。
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


class AgentTransaction(models.Model):
    """
    Agent 事务记录
    用于追踪 Agent 执行的操作，支持回滚功能。
    """
    session_id = models.CharField(max_length=200, db_index=True, help_text="会话 ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agent_transactions', null=True, blank=True)
    action_type = models.CharField(max_length=100, help_text="操作类型 (create_event, delete_todo, etc.)")
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
