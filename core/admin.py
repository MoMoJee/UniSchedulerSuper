from django.contrib import admin
from .models import (
    UserData, 
    UserProfile, 
    CollaborativeCalendarGroup, 
    GroupMembership, 
    GroupCalendarData
)

# 在admin界面展示、修改用户的UserData模型值
@admin.register(UserData)
class UserDataAdmin(admin.ModelAdmin):
    list_display = ('user', 'key', 'value')
    search_fields = ('user__username', 'key')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'date_joined')
    search_fields = ('user__username', 'key')


# ==================== 群组协作功能 Admin ====================

@admin.register(CollaborativeCalendarGroup)
class CollaborativeCalendarGroupAdmin(admin.ModelAdmin):
    list_display = ('share_group_id', 'share_group_name', 'owner', 'member_count', 'created_at')
    search_fields = ('share_group_name', 'owner__username', 'share_group_id')
    list_filter = ('created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')
    
    def member_count(self, obj):
        """显示成员数量"""
        return obj.memberships.count()
    member_count.short_description = '成员数'


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'share_group', 'role', 'joined_at')
    list_filter = ('role', 'joined_at')
    search_fields = ('user__username', 'share_group__share_group_name')
    readonly_fields = ('joined_at',)


@admin.register(GroupCalendarData)
class GroupCalendarDataAdmin(admin.ModelAdmin):
    list_display = ('share_group', 'version', 'event_count', 'last_updated')
    readonly_fields = ('last_updated',)
    search_fields = ('share_group__share_group_name',)
    
    def event_count(self, obj):
        """显示事件数量"""
        if isinstance(obj.events_data, list):
            return len(obj.events_data)
        return 0
    event_count.short_description = '事件数'
