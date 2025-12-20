from django.contrib import admin
from .models import UserMemory, MemoryItem

@admin.register(UserMemory)
class UserMemoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    search_fields = ('user__username',)

@admin.register(MemoryItem)
class MemoryItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'content', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'content')
