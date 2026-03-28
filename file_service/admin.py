from django.contrib import admin

from file_service.models import UserFile, UserFolder, UserStorageQuota


@admin.register(UserStorageQuota)
class UserStorageQuotaAdmin(admin.ModelAdmin):
    list_display = ['user', 'used_bytes', 'max_storage_bytes', 'file_count', 'tier', 'updated_at']
    list_filter = ['tier']
    search_fields = ['user__username']
    readonly_fields = ['used_bytes', 'file_count', 'created_at', 'updated_at']


@admin.register(UserFolder)
class UserFolderAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'path', 'parent', 'created_at']
    list_filter = ['user']
    search_fields = ['name', 'path']
    readonly_fields = ['path', 'created_at', 'updated_at']


@admin.register(UserFile)
class UserFileAdmin(admin.ModelAdmin):
    list_display = ['user', 'filename', 'category', 'file_size', 'parse_status', 'source', 'is_deleted', 'created_at']
    list_filter = ['category', 'parse_status', 'source', 'is_deleted']
    search_fields = ['filename', 'user__username']
    readonly_fields = ['file_hash', 'file_size', 'created_at', 'updated_at', 'parsed_at', 'deleted_at']
    raw_id_fields = ['user', 'folder']
