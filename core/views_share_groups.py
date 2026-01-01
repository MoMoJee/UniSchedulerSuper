"""
群组协作功能视图 - 处理分享群组相关的API
"""

import json
import uuid
import datetime
from typing import List

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from core.models import (
    CollaborativeCalendarGroup,
    GroupMembership,
    GroupCalendarData,
    UserData
)
from logger import logger
from core.utils.validators import validate_body


def get_django_request(request):
    """
    通过 request 对象，获取原生的 Django HttpRequest 对象
    兼容 Django HttpRequest 和 DRF Request
    """
    from rest_framework.request import Request as DRFRequest
    if isinstance(request, DRFRequest):
        return request._request
    return request


@validate_body({
    'share_group_name': {'type': str, 'required': True, 'comment': '群组名称'},
    'share_group_color': {'type': str, 'required': False, 'default': '#3498db', 'comment': '群组颜色'},
    'share_group_description': {'type': str, 'required': False, 'default': '', 'comment': '群组描述'},
    'member_color': {'type': str, 'required': False, 'default': '#3498db', 'comment': '创建者的成员颜色'},
})
def create_share_group(request):
    """
    创建协作群组
    
    POST /api/share-groups/create/
    Request:
    {
        "share_group_name": "工作协作组",
        "share_group_color": "#3498db",
        "share_group_description": "项目协作用"
    }
    
    Response:
    {
        "status": "success",
        "group": {
            "share_group_id": "share_group_xxx",
            "share_group_name": "工作协作组",
            "share_group_color": "#3498db",
            "owner_id": 1,
            "owner_name": "张三",
            "created_at": "2025-11-11T10:00:00"
        }
    }
    """
    try:
        # 解析请求数据
        data = request.validated_data
        
        share_group_name = data.get('share_group_name')
        share_group_color = data.get('share_group_color', '#3498db')
        share_group_description = data.get('share_group_description', '')
        member_color = data.get('member_color', '#3498db')  # 创建者的成员颜色
        
        # 验证必填字段
        if not share_group_name:
            return JsonResponse({
                'status': 'error',
                'message': '群组名称不能为空'
            }, status=400)
        
        # 生成唯一的群组ID
        share_group_id = f"share_group_{uuid.uuid4().hex[:12]}"
        
        # 创建群组
        group = CollaborativeCalendarGroup.objects.create(
            share_group_id=share_group_id,
            share_group_name=share_group_name,
            share_group_color=share_group_color,
            share_group_description=share_group_description,
            owner=request.user
        )
        
        # 添加创建者为群主成员
        GroupMembership.objects.create(
            share_group=group,
            user=request.user,
            role='owner',
            member_color=member_color
        )
        
        # 初始化群组日历数据
        GroupCalendarData.objects.create(
            share_group=group,
            events_data=[],
            version=0
        )
        
        logger.info(f"用户 {request.user.username} 创建了群组 {share_group_id}: {share_group_name}")
        
        return JsonResponse({
            'status': 'success',
            'group': {
                'share_group_id': group.share_group_id,
                'share_group_name': group.share_group_name,
                'share_group_color': group.share_group_color,
                'share_group_description': group.share_group_description,
                'owner_id': request.user.id,
                'owner_name': request.user.username,
                'created_at': group.created_at.isoformat()
            }
        })
        
    except Exception as e:
        logger.error(f"创建群组失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'创建群组失败: {str(e)}'
        }, status=500)


def get_my_share_groups(request):
    """
    获取我的群组列表（我创建的或我加入的）
    
    GET /api/share-groups/my-groups/
    
    Response:
    {
        "status": "success",
        "groups": [
            {
                "share_group_id": "share_group_work",
                "share_group_name": "工作协作组",
                "share_group_color": "#3498db",
                "share_group_description": "...",
                "role": "owner",
                "member_count": 5,
                "owner_name": "张三",
                "created_at": "2025-11-11T10:00:00",
                "version": 10
            }
        ]
    }
    """
    try:
        # 获取用户的所有群组成员关系
        memberships = GroupMembership.objects.filter(user=request.user).select_related('share_group')
        
        # 预加载所有群组的版本号，避免 N+1 查询
        group_ids = [m.share_group.share_group_id for m in memberships]
        group_versions = {
            gcd.share_group_id: gcd.version 
            for gcd in GroupCalendarData.objects.filter(share_group_id__in=group_ids)
        }
        
        groups = []
        for membership in memberships:
            group = membership.share_group
            member_count = GroupMembership.objects.filter(share_group=group).count()
            
            groups.append({
                'share_group_id': group.share_group_id,
                'share_group_name': group.share_group_name,
                'share_group_color': group.share_group_color,
                'share_group_description': group.share_group_description,
                'role': membership.role,
                'my_member_color': membership.member_color,  # 新增：我的成员颜色
                'member_count': member_count,
                'owner_id': group.owner.id,
                'owner_name': group.owner.username,
                'created_at': group.created_at.isoformat(),
                'joined_at': membership.joined_at.isoformat(),
                'version': group_versions.get(group.share_group_id, 0)  # 返回版本号，用于前端初始化轮询
            })
        
        return JsonResponse({
            'status': 'success',
            'groups': groups
        })
        
    except Exception as e:
        logger.error(f"获取群组列表失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'获取群组列表失败: {str(e)}'
        }, status=500)


@validate_body({
    'share_group_id': {'type': str, 'required': True, 'comment': '群组ID'},
    'member_color': {'type': str, 'required': False, 'default': '#3498db', 'comment': '加入时的成员颜色'},
})
def join_share_group(request):
    """
    加入群组（通过群组ID或邀请码）
    
    POST /api/share-groups/join/
    Request:
    {
        "share_group_id": "share_group_xxx"
    }
    
    Response:
    {
        "status": "success",
        "message": "成功加入群组"
    }
    """
    try:
        data = request.validated_data
        share_group_id = data.get('share_group_id')
        member_color = data.get('member_color', '#3498db')  # 加入时的成员颜色
        
        if not share_group_id:
            return JsonResponse({
                'status': 'error',
                'message': '群组ID不能为空'
            }, status=400)
        
        # 检查群组是否存在
        try:
            group = CollaborativeCalendarGroup.objects.get(share_group_id=share_group_id)
        except CollaborativeCalendarGroup.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '群组不存在'
            }, status=404)
        
        # 检查用户是否已经是成员
        if GroupMembership.objects.filter(share_group=group, user=request.user).exists():
            return JsonResponse({
                'status': 'error',
                'message': '您已经是该群组的成员了'
            }, status=400)
        
        # 添加成员
        GroupMembership.objects.create(
            share_group=group,
            user=request.user,
            role='member',
            member_color=member_color
        )
        
        logger.info(f"用户 {request.user.username} 加入了群组 {share_group_id}")
        
        return JsonResponse({
            'status': 'success',
            'message': f'成功加入群组 "{group.share_group_name}"',
            'group': {
                'share_group_id': group.share_group_id,
                'share_group_name': group.share_group_name,
                'share_group_color': group.share_group_color
            }
        })
        
    except Exception as e:
        logger.error(f"加入群组失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'加入群组失败: {str(e)}'
        }, status=500)


def leave_share_group(request, share_group_id):
    """
    退出群组
    
    POST /api/share-groups/{share_group_id}/leave/
    
    Response:
    {
        "status": "success",
        "message": "已退出群组"
    }
    """
    try:
        # 检查群组是否存在
        try:
            group = CollaborativeCalendarGroup.objects.get(share_group_id=share_group_id)
        except CollaborativeCalendarGroup.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '群组不存在'
            }, status=404)
        
        # 检查用户是否是成员
        try:
            membership = GroupMembership.objects.get(share_group=group, user=request.user)
        except GroupMembership.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '您不是该群组的成员'
            }, status=400)
        
        # 群主不能退出（需要先转让群主或删除群组）
        if membership.role == 'owner':
            return JsonResponse({
                'status': 'error',
                'message': '群主不能退出群组，请先转让群主或删除群组'
            }, status=400)
        
        # 删除成员关系
        membership.delete()
        
        # 重新同步群组数据（移除该用户分享的日程）
        sync_group_calendar_data([share_group_id], request.user)
        
        logger.info(f"用户 {request.user.username} 退出了群组 {share_group_id}")
        
        return JsonResponse({
            'status': 'success',
            'message': f'已退出群组 "{group.share_group_name}"'
        })
        
    except Exception as e:
        logger.error(f"退出群组失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'退出群组失败: {str(e)}'
        }, status=500)


def delete_share_group(request, share_group_id):
    """
    删除群组（仅群主可操作）
    
    DELETE /api/share-groups/{share_group_id}/delete/
    
    Response:
    {
        "status": "success",
        "message": "群组已删除"
    }
    """
    try:
        # 检查群组是否存在
        try:
            group = CollaborativeCalendarGroup.objects.get(share_group_id=share_group_id)
        except CollaborativeCalendarGroup.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '群组不存在'
            }, status=404)
        
        # 检查是否是群主
        if group.owner != request.user:
            return JsonResponse({
                'status': 'error',
                'message': '只有群主可以删除群组'
            }, status=403)
        
        group_name = group.share_group_name
        
        # 删除群组（会级联删除成员关系和日历数据）
        group.delete()
        
        logger.info(f"用户 {request.user.username} 删除了群组 {share_group_id}: {group_name}")
        
        return JsonResponse({
            'status': 'success',
            'message': f'群组 "{group_name}" 已删除'
        })
        
    except Exception as e:
        logger.error(f"删除群组失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'删除群组失败: {str(e)}'
        }, status=500)


def get_share_group_events(request, share_group_id):
    """
    获取群组日程（带版本检测）
    
    GET /api/share-groups/{share_group_id}/events/?version=124
    
    Response (有更新):
    {
        "status": "updated",
        "version": 125,
        "events": [...],
        "last_updated": "2025-11-11T10:30:00"
    }
    
    Response (无更新):
    {
        "status": "no_update",
        "version": 124
    }
    """
    try:
        local_version = int(request.GET.get('version', 0))
        
        # 检查用户是否是该群组成员
        if not GroupMembership.objects.filter(
            share_group_id=share_group_id,
            user=request.user
        ).exists():
            return JsonResponse({
                'status': 'error',
                'message': '您不是该群组成员，无权查看'
            }, status=403)
        
        # 获取群组数据
        try:
            group_data = GroupCalendarData.objects.get(share_group_id=share_group_id)
        except GroupCalendarData.DoesNotExist:
            # 如果不存在，返回空数据（包含成员信息）
            members = GroupMembership.objects.filter(share_group_id=share_group_id).select_related('user')
            members_data = []
            for membership in members:
                members_data.append({
                    'user_id': membership.user.id,
                    'username': membership.user.username,
                    'member_color': membership.member_color or '#6c757d'
                })
            
            return JsonResponse({
                'status': 'updated',
                'version': 0,
                'events': [],
                'current_user_id': request.user.id,  # 新增：当前用户ID
                'members': members_data,  # 新增：成员列表
                'last_updated': None
            })
        
        # 版本检测
        if group_data.version == local_version:
            # 即使没有更新，也返回成员信息（用于筛选功能）
            members = GroupMembership.objects.filter(share_group_id=share_group_id).select_related('user')
            members_data = []
            for membership in members:
                members_data.append({
                    'user_id': membership.user.id,
                    'username': membership.user.username,
                    'member_color': membership.member_color or '#6c757d'
                })
            
            return JsonResponse({
                'status': 'no_update',
                'version': local_version,
                'current_user_id': request.user.id,  # 新增：当前用户ID
                'members': members_data  # 新增：成员列表
            })
        
        # 获取当前用户的所有事件ID（用于标识哪些是自己的事件）
        user_events_data, created, result = UserData.get_or_initialize(
            request, new_key="events", data=[]
        )
        user_events = user_events_data.get_value() or [] if user_events_data else []
        user_event_ids = {event.get('id') for event in user_events if isinstance(event, dict)}
        
        # 为每个事件添加 owner_id 标识
        events_with_owner = []
        for event in group_data.events_data:
            event_copy = event.copy()
            # 如果事件ID在当前用户的事件列表中，标记为当前用户的事件
            if event.get('id') in user_event_ids:
                event_copy['owner_id'] = request.user.id
                event_copy['user_id'] = request.user.id
            events_with_owner.append(event_copy)
        
        # 获取群组成员信息（包含颜色）
        members = GroupMembership.objects.filter(share_group_id=share_group_id).select_related('user')
        members_data = []
        for membership in members:
            members_data.append({
                'user_id': membership.user.id,
                'username': membership.user.username,
                'member_color': membership.member_color or '#6c757d'
            })
        
        # 返回最新数据
        return JsonResponse({
            'status': 'updated',
            'version': group_data.version,
            'events': events_with_owner,  # 使用添加了 owner_id 的事件列表
            'current_user_id': request.user.id,  # 新增：当前用户ID
            'members': members_data,  # 新增：成员列表
            'last_updated': group_data.last_updated.isoformat()
        })
        
    except Exception as e:
        logger.error(f"获取群组日程失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'获取群组日程失败: {str(e)}'
        }, status=500)


def check_group_update(request, share_group_id):
    """
    检查群组是否有更新
    
    GET /api/share-groups/{share_group_id}/check-update/?version=124
    
    Response:
    {
        "has_update": true,
        "current_version": 125
    }
    """
    try:
        local_version = int(request.GET.get('version', 0))
        
        # 检查用户是否是该群组成员
        if not GroupMembership.objects.filter(
            share_group_id=share_group_id,
            user=request.user
        ).exists():
            return JsonResponse({
                'status': 'error',
                'message': '您不是该群组成员'
            }, status=403)
        
        # 获取群组数据
        try:
            group_data = GroupCalendarData.objects.get(share_group_id=share_group_id)
            current_version = group_data.version
        except GroupCalendarData.DoesNotExist:
            current_version = 0
        
        has_update = current_version != local_version
        
        return JsonResponse({
            'has_update': has_update,
            'current_version': current_version
        })
        
    except Exception as e:
        logger.error(f"检查群组更新失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'检查群组更新失败: {str(e)}'
        }, status=500)


def get_share_group_members(request, share_group_id):
    """
    获取群组成员列表
    
    GET /api/share-groups/{share_group_id}/members/
    
    Response:
    {
        "status": "success",
        "group": {
            "share_group_id": "share_group_xxx",
            "name": "工作协作组",
            "description": "...",
            "owner_id": 1
        },
        "members": [
            {
                "user_id": 1,
                "username": "张三",
                "role": "owner",
                "joined_at": "2025-11-11T10:00:00"
            },
            {
                "user_id": 2,
                "username": "李四",
                "role": "member",
                "joined_at": "2025-11-11T11:00:00"
            }
        ]
    }
    """
    try:
        # 检查群组是否存在
        try:
            group = CollaborativeCalendarGroup.objects.get(share_group_id=share_group_id)
        except CollaborativeCalendarGroup.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '群组不存在'
            }, status=404)
        
        # 检查用户是否是该群组成员
        if not GroupMembership.objects.filter(
            share_group=group,
            user=request.user
        ).exists():
            return JsonResponse({
                'status': 'error',
                'message': '您不是该群组成员，无权查看'
            }, status=403)
        
        # 获取所有成员
        memberships = GroupMembership.objects.filter(share_group=group).select_related('user').order_by('joined_at')
        
        members = []
        for membership in memberships:
            members.append({
                'user_id': membership.user.id,
                'username': membership.user.username,
                'role': membership.role,
                'member_color': membership.member_color,  # 新增：成员颜色
                'joined_at': membership.joined_at.isoformat()
            })
        
        return JsonResponse({
            'status': 'success',
            'group': {
                'share_group_id': group.share_group_id,
                'name': group.share_group_name,
                'color': group.share_group_color,  # 新增：群组颜色
                'description': group.share_group_description,
                'owner_id': group.owner.id,
                'created_at': group.created_at.isoformat()
            },
            'members': members
        })
        
    except Exception as e:
        logger.error(f"获取群组成员列表失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'获取群组成员列表失败: {str(e)}'
        }, status=500)


@validate_body({
    'share_group_name': {'type': str, 'required': False, 'comment': '新的群组名称'},
    'share_group_color': {'type': str, 'required': False, 'comment': '新的群组颜色'},
    'share_group_description': {'type': str, 'required': False, 'comment': '新的群组描述'},
})
def update_share_group(request, share_group_id):
    """
    更新群组信息（仅群主可操作）
    
    PUT /api/share-groups/{share_group_id}/update/
    Request:
    {
        "share_group_name": "新的群组名称",
        "share_group_color": "#ff0000",
        "share_group_description": "新的描述"
    }
    
    Response:
    {
        "status": "success",
        "message": "群组信息已更新",
        "group": {
            "share_group_id": "share_group_xxx",
            "share_group_name": "新的群组名称",
            "share_group_color": "#ff0000",
            "share_group_description": "新的描述"
        }
    }
    """
    try:
        # 检查群组是否存在
        try:
            group = CollaborativeCalendarGroup.objects.get(share_group_id=share_group_id)
        except CollaborativeCalendarGroup.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '群组不存在'
            }, status=404)
        
        # 检查是否是群主
        if group.owner != request.user:
            return JsonResponse({
                'status': 'error',
                'message': '只有群主可以修改群组信息'
            }, status=403)
        
        # 解析请求数据
        data = request.validated_data
        
        logger.info(f"收到的更新数据: {data}")
        logger.info(f"更新前 - 名称: {group.share_group_name}, 颜色: {group.share_group_color}, 描述: {group.share_group_description}")
        
        # 更新群组信息
        if 'share_group_name' in data:
            new_name = data['share_group_name'].strip()
            if new_name:
                group.share_group_name = new_name
                logger.info(f"更新名称为: {new_name}")
        
        if 'share_group_color' in data:
            group.share_group_color = data['share_group_color']
            logger.info(f"更新颜色为: {data['share_group_color']}")
        
        if 'share_group_description' in data:
            group.share_group_description = data['share_group_description']
            logger.info(f"更新描述为: {data['share_group_description']}")
        
        group.save()
        
        logger.info(f"保存后 - 名称: {group.share_group_name}, 颜色: {group.share_group_color}, 描述: {group.share_group_description}")
        logger.info(f"用户 {request.user.username} 更新了群组 {share_group_id} 的信息")
        
        return JsonResponse({
            'status': 'success',
            'message': '群组信息已更新',
            'group': {
                'share_group_id': group.share_group_id,
                'share_group_name': group.share_group_name,
                'share_group_color': group.share_group_color,
                'share_group_description': group.share_group_description,
                'updated_at': group.updated_at.isoformat() if hasattr(group, 'updated_at') else None
            }
        })
        
    except Exception as e:
        logger.error(f"更新群组信息失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'更新群组信息失败: {str(e)}'
        }, status=500)


def sync_group_calendar_data(share_group_ids: List[str], trigger_user=None):
    """
    同步群组日历数据（核心函数）
    
    遍历群组的所有成员，汇总他们分享到该群组的日程
    
    参数:
        share_group_ids: 需要同步的群组ID列表
        trigger_user: 触发同步的用户（可选，用于日志记录）
    """
    from django.http import HttpRequest
    
    try:
        for group_id in share_group_ids:
            logger.info(f"开始同步群组 {group_id} 的日历数据...")
            
            # 获取群组
            try:
                group = CollaborativeCalendarGroup.objects.get(share_group_id=group_id)
            except CollaborativeCalendarGroup.DoesNotExist:
                logger.warning(f"群组 {group_id} 不存在，跳过同步")
                continue
            
            # 获取群组所有成员
            memberships = GroupMembership.objects.filter(share_group=group).select_related('user')
            
            # 汇总所有成员的共享日程
            all_shared_events = []
            
            for membership in memberships:
                user = membership.user
                
                # 创建一个临时的 request 对象用于 UserData.get_or_initialize
                class MockRequest:
                    def __init__(self, user):
                        self.user = user
                        self.is_authenticated = True
                
                mock_request = MockRequest(user)
                
                # 获取用户的 events 数据
                try:
                    user_events_data, created, result = UserData.get_or_initialize(
                        mock_request, 
                        new_key="events", 
                        data=[]
                    )
                    
                    if user_events_data is None:
                        logger.warning(f"无法获取用户 {user.username} 的 events 数据")
                        continue
                    
                    events = user_events_data.get_value() or []
                    if not isinstance(events, list):
                        events = []
                    
                    # 筛选分享到该群组的日程
                    shared_events = [
                        e for e in events 
                        if group_id in e.get('shared_to_groups', [])
                    ]
                    
                    logger.info(f"用户 {user.username} 分享了 {len(shared_events)} 个日程到群组 {group_id}")
                    
                    # 添加 owner 信息、成员颜色和只读标记
                    for event in shared_events:
                        event_copy = event.copy()
                        event_copy['owner_id'] = user.id
                        event_copy['owner_name'] = user.username
                        event_copy['owner_color'] = membership.member_color  # 新增：成员颜色
                        event_copy['is_readonly'] = True
                        event_copy['shared_at'] = datetime.datetime.now().isoformat()
                        all_shared_events.append(event_copy)
                        
                except Exception as e:
                    logger.error(f"处理用户 {user.username} 的日程时出错: {str(e)}")
                    continue
            
            # 保存到群组数据库，递增版本号
            group_data, created = GroupCalendarData.objects.get_or_create(
                share_group=group,
                defaults={'events_data': [], 'version': 0}
            )
            
            group_data.events_data = all_shared_events
            group_data.version += 1
            group_data.save()
            
            trigger_info = f" (由 {trigger_user.username} 触发)" if trigger_user else ""
            logger.info(
                f"群组 {group_id} 同步完成{trigger_info}: "
                f"汇总了 {len(all_shared_events)} 个事件，版本号 {group_data.version}"
            )
            
    except Exception as e:
        logger.error(f"同步群组日历数据失败: {str(e)}")
        raise


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@validate_body({
    'member_color': {'type': str, 'required': True, 'comment': '新的成员颜色'},
})
def update_member_color(request, share_group_id):
    """
    更新成员在群组中的个人颜色
    
    PUT /api/share-groups/{share_group_id}/update-member-color/
    Request:
    {
        "member_color": "#ff5733"
    }
    
    Response:
    {
        "status": "success",
        "message": "成员颜色已更新",
        "member_color": "#ff5733"
    }
    """
    try:
        # 获取群组
        try:
            group = CollaborativeCalendarGroup.objects.get(share_group_id=share_group_id)
        except CollaborativeCalendarGroup.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '群组不存在'
            }, status=404)
        
        # 获取当前用户的成员关系
        try:
            membership = GroupMembership.objects.get(share_group=group, user=request.user)
        except GroupMembership.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': '您不是该群组成员'
            }, status=403)
        
        # 获取请求数据
        data = request.validated_data
        member_color = data.get('member_color', '#3498db')
        
        # 验证颜色格式（简单验证）
        if not member_color.startswith('#') or len(member_color) not in [4, 7]:
            return JsonResponse({
                'status': 'error',
                'message': '无效的颜色格式，请使用 #RGB 或 #RRGGBB 格式'
            }, status=400)
        
        # 更新成员颜色
        membership.member_color = member_color
        membership.save()
        
        # 触发群组数据同步（更新所有事件的 owner_color）
        sync_group_calendar_data([share_group_id], request.user)
        
        logger.info(f"用户 {request.user.username} 更新了在群组 {share_group_id} 中的颜色为 {member_color}")
        
        return JsonResponse({
            'status': 'success',
            'message': '成员颜色已更新',
            'member_color': member_color
        })
        
    except Exception as e:
        logger.error(f"更新成员颜色失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'更新成员颜色失败: {str(e)}'
        }, status=500)
