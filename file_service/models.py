from django.conf import settings
from django.contrib.auth.models import User
from django.db import models

from file_service.storage import user_file_upload_to


class UserStorageQuota(models.Model):
    """
    用户存储配额

    设计要点：
    - 每个用户一条记录（OneToOne）
    - max_storage_bytes 和 max_file_size 可按用户单独调整（付费升级）
    - used_bytes 由文件上传/删除时主动维护，避免每次实时扫描
    """
    DEFAULT_MAX_STORAGE = 255 * 1024 * 1024      # 255 MB
    DEFAULT_MAX_FILE_SIZE = 20 * 1024 * 1024      # 20 MB

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='storage_quota')

    # 配额配置
    max_storage_bytes = models.BigIntegerField(
        default=DEFAULT_MAX_STORAGE,
        help_text="存储空间上限（字节），默认 255MB"
    )
    max_file_size = models.BigIntegerField(
        default=DEFAULT_MAX_FILE_SIZE,
        help_text="单文件大小上限（字节），默认 20MB"
    )

    # 实时用量（由上传/删除操作维护）
    used_bytes = models.BigIntegerField(default=0, help_text="已用存储空间（字节）")
    file_count = models.IntegerField(default=0, help_text="文件总数")

    # 付费等级预留
    tier = models.CharField(
        max_length=20,
        default='free',
        choices=[
            ('free', '免费版'),
            ('basic', '基础版'),
            ('pro', '专业版'),
            ('enterprise', '企业版'),
        ],
        help_text="用户存储等级（预留付费扩容）"
    )
    tier_expires_at = models.DateTimeField(null=True, blank=True, help_text="付费等级到期时间")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "用户存储配额"
        verbose_name_plural = "用户存储配额"

    def __str__(self):
        used_mb = self.used_bytes / (1024 * 1024)
        max_mb = self.max_storage_bytes / (1024 * 1024)
        return f"{self.user.username}: {used_mb:.1f}/{max_mb:.1f} MB ({self.tier})"

    @property
    def remaining_bytes(self):
        return max(0, self.max_storage_bytes - self.used_bytes)

    @property
    def usage_percent(self):
        if self.max_storage_bytes == 0:
            return 100.0
        return round(self.used_bytes / self.max_storage_bytes * 100, 1)

    def can_upload(self, file_size: int) -> tuple[bool, str]:
        """检查是否允许上传指定大小的文件"""
        if file_size > self.max_file_size:
            max_mb = self.max_file_size / (1024 * 1024)
            return False, f"文件大小超过限制（上限 {max_mb:.0f}MB）"
        if self.used_bytes + file_size > self.max_storage_bytes:
            remaining_mb = self.remaining_bytes / (1024 * 1024)
            return False, f"存储空间不足（剩余 {remaining_mb:.1f}MB）"
        return True, ""

    def consume(self, file_size: int):
        """上传文件后增加用量"""
        self.used_bytes += file_size
        self.file_count += 1
        self.save(update_fields=['used_bytes', 'file_count', 'updated_at'])

    def release(self, file_size: int):
        """删除文件后释放用量"""
        self.used_bytes = max(0, self.used_bytes - file_size)
        self.file_count = max(0, self.file_count - 1)
        self.save(update_fields=['used_bytes', 'file_count', 'updated_at'])

    @classmethod
    def get_or_create_for_user(cls, user):
        """获取或创建用户配额记录"""
        quota, _ = cls.objects.get_or_create(user=user)
        return quota


class UserFolder(models.Model):
    """
    用户文件夹（树形结构）

    使用物化路径（materialized path）方便查询子树。
    示例：parent=None, path="/" 为根；parent=根, path="/文档/" 为一级子文件夹。
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='folders')
    name = models.CharField(max_length=255, help_text="文件夹名称")
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE, related_name='children'
    )
    path = models.CharField(
        max_length=2048, db_index=True,
        help_text="物化路径，如 /文档/工作/"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "用户文件夹"
        verbose_name_plural = "用户文件夹"
        unique_together = [('user', 'path')]
        ordering = ['path']

    def __str__(self):
        return f"{self.user.username}:{self.path}"

    def save(self, *args, **kwargs):
        """保存时自动计算物化路径"""
        if self.parent:
            self.path = f"{self.parent.path}{self.name}/"
        else:
            self.path = f"/{self.name}/"
        super().save(*args, **kwargs)

    @classmethod
    def ensure_path(cls, user, path: str) -> 'UserFolder':
        """确保路径存在，不存在则递归创建（类似 mkdir -p）"""
        parts = [p for p in path.strip('/').split('/') if p]
        current_parent = None
        current_path = "/"
        folder = None

        for part in parts:
            current_path = f"{current_path}{part}/"
            folder, _ = cls.objects.get_or_create(
                user=user,
                path=current_path,
                defaults={'name': part, 'parent': current_parent}
            )
            current_parent = folder

        return folder


class UserFile(models.Model):
    """
    用户文件（云盘核心模型）

    设计要点：
    - original_file 保留原始文件，永远不会被修改
    - parsed_markdown 上传时预解析，后续 Agent 调用直接取 MD
    - search_text 是去除 Markdown 格式后的纯文本，用于全文检索
    - file_hash (SHA-256) 用于解析结果复用：同 hash + 未编辑 → 跳过重复解析
    - 存储去重仅限同一文件夹内（同用户+同文件夹+同 hash），不同文件夹允许独立副本
    - 图片文件 parse_status='none'，不做预解析
    - markdown_edited=True 标记用户编辑过 MD，后续不会被自动重解析覆盖
    """

    # ========== 支持的文件类型 ==========
    ALLOWED_MIME_TYPES = {
        # 文档（上传时预解析为 MD）
        'application/pdf': 'document',
        'application/msword': 'document',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'document',
        'application/vnd.ms-excel': 'document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'document',
        # 图片（不预解析，后续按需处置）
        'image/jpeg': 'image',
        'image/png': 'image',
        'image/gif': 'image',
        'image/webp': 'image',
    }

    FILE_CATEGORY_CHOICES = [
        ('document', '文档'),
        ('image', '图片'),
    ]

    SOURCE_CHOICES = [
        ('upload', '本地上传'),
        ('url', 'URL上传'),
        ('chat_upload', '聊天上传'),
    ]

    PARSE_STATUS_CHOICES = [
        ('none', '无需解析'),       # 图片
        ('pending', '待解析'),
        ('processing', '解析中'),
        ('completed', '已完成'),
        ('failed', '解析失败'),
    ]

    # ========== 基础信息 ==========
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cloud_files')
    folder = models.ForeignKey(
        UserFolder, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='files'
    )

    # ========== 原始文件 ==========
    original_file = models.FileField(upload_to=user_file_upload_to, help_text="原始文件")
    filename = models.CharField(max_length=512, help_text="用户可见的文件名")
    file_size = models.BigIntegerField(default=0, help_text="文件大小（字节）")
    mime_type = models.CharField(max_length=100, help_text="MIME 类型")
    category = models.CharField(max_length=20, choices=FILE_CATEGORY_CHOICES, help_text="文件分类")
    file_hash = models.CharField(max_length=64, db_index=True, help_text="SHA-256 文件哈希，用于去重")

    # ========== 解析产物（仅文档类型） ==========
    parsed_markdown = models.TextField(blank=True, default='', help_text="预解析的 Markdown 内容")
    parsed_at = models.DateTimeField(null=True, blank=True, help_text="解析完成时间")
    parse_status = models.CharField(
        max_length=20, choices=PARSE_STATUS_CHOICES, default='pending',
        help_text="解析状态"
    )
    parse_source = models.CharField(
        max_length=30, blank=True, default='',
        help_text="解析来源：baidu_cloud / local_fallback / reused / reused_from_attachment / none"
    )
    parse_error = models.TextField(blank=True, default='', help_text="解析错误信息")
    markdown_edited = models.BooleanField(default=False, help_text="用户是否手动编辑过 Markdown")

    # ========== 检索辅助 ==========
    text_preview = models.CharField(max_length=500, blank=True, default='', help_text="前 500 字摘要")
    search_text = models.TextField(blank=True, default='', help_text="去除 MD 格式的纯文本，用于全文检索")

    # ========== 来源追踪 ==========
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='upload', help_text="上传来源")
    source_url = models.URLField(max_length=2048, blank=True, default='', help_text="URL 上传时的原始地址")

    # ========== 软删除 ==========
    is_deleted = models.BooleanField(default=False, help_text="是否已软删除")
    deleted_at = models.DateTimeField(null=True, blank=True)

    # ========== 时间戳 ==========
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "用户文件"
        verbose_name_plural = "用户文件"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'folder', 'is_deleted']),
            models.Index(fields=['user', 'category', 'is_deleted']),
            models.Index(fields=['user', 'is_deleted', '-created_at']),
            models.Index(fields=['file_hash']),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.filename} ({self.category})"

    @property
    def is_document(self):
        return self.category == 'document'

    @property
    def is_image(self):
        return self.category == 'image'

    @property
    def is_parsed(self):
        return self.parse_status == 'completed'

    @property
    def has_markdown(self):
        return bool(self.parsed_markdown)

    def soft_delete(self):
        """软删除文件并释放配额"""
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])
        quota = UserStorageQuota.get_or_create_for_user(self.user)
        quota.release(self.file_size)

    def hard_delete(self):
        """物理删除文件和数据库记录"""
        if self.original_file:
            try:
                self.original_file.delete(save=False)
            except Exception:
                pass
        self.delete()

    def to_api_dict(self, include_content=False):
        """转为 API 响应格式"""
        result = {
            'id': self.id,
            'filename': self.filename,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'category': self.category,
            'folder_id': self.folder_id,
            'parse_status': self.parse_status,
            'markdown_edited': self.markdown_edited,
            'source': self.source,
            'text_preview': self.text_preview,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
        if self.original_file:
            result['file_url'] = self.original_file.url
        if include_content and self.parsed_markdown:
            result['parsed_markdown'] = self.parsed_markdown
        return result
