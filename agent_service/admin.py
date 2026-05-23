from django.contrib import admin
from .models import AgentUsageRecord, UserMemory, MemoryItem


@admin.register(AgentUsageRecord)
class AgentUsageRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'model_id', 'call_site', 'cost_total', 'source', 'created_at')
    list_filter = ('month', 'call_site', 'source', 'style', 'is_system_model')
    search_fields = ('user__username', 'model_id', 'model_name', 'record_id')
    readonly_fields = ('record_id', 'created_at')

@admin.register(UserMemory)
class UserMemoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    search_fields = ('user__username',)

@admin.register(MemoryItem)
class MemoryItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'content', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'content')
