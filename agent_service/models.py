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
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memory_items')
    content = models.TextField(help_text="记忆内容")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.content[:50]}..."
