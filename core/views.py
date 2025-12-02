
# Create your views here.
import datetime
from typing import List
import uuid
import markdown
from datetime import timedelta

try:
    from dateutil.rrule import rrulestr
    from dateutil.parser import parse
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False

# 导入我们的新引擎
from integrated_reminder_manager import IntegratedReminderManager

# 提醒管理器工厂函数
def get_reminder_manager(request):
    """获取用户专属的提醒管理器实例"""
    if not request:
        raise ValueError("Request is required for IntegratedReminderManager")
    return IntegratedReminderManager(request=request)

from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .forms import RegisterForm

from logger import logger

# 导入 reminder 相关视图函数
from .views_reminder import (
    get_reminders as get_reminders_impl, 
    create_reminder as create_reminder_impl,
    update_reminder as update_reminder_impl,
    update_reminder_status as update_reminder_status_impl,
    delete_reminder as delete_reminder_impl,
    maintain_reminders as maintain_reminders_impl,
    get_pending_reminders as get_pending_reminders_impl,
    bulk_edit_reminders as bulk_edit_reminders_impl,
    convert_recurring_to_single_impl,
    snooze_reminder_impl,
    dismiss_reminder_impl,
    complete_reminder_impl
)

# 导入参数验证装饰器
from core.utils.validators import validate_body

# 导入 events 相关视图函数  
from .views_events import (
    get_events_impl,
    create_event_impl,
    # delete_event_impl,
    update_events_impl,
    get_django_request  # 添加这个辅助函数
)

# 索引页
def index(request):
    return render(request, 'index.html')

# 关于我们
def about(request):

    # 获取 README.md 文件的路径
    # base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # readme_path = os.path.join(base_dir, '/core/static/about.md')
    readme_path = 'core/static/about.md'

    # 读取 README.md 文件内容
    with open(readme_path, 'r', encoding='utf-8') as file:
        readme_content = file.read()

    # 将 Markdown 转换为 HTML
    html_content = markdown.markdown(readme_content)

    # 将 HTML 内容传递到模板
    return render(request, 'about.html', {'readme_content': html_content})

# 注册界面
def user_register(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()  # 创建用户
            login(request, user)  # 自动登录新注册的用户

            # 这里可以用新的函数，为用户初始化数据表，实现网页功能
            return redirect('home')  # 重定向到首页
    else:
        form = RegisterForm()
    return render(request, 'user_register.html', {'form': form})

# 登录页面
def user_login(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('home')  # 重定向到首页
    else:
        form = AuthenticationForm()
    return render(request, 'user_login.html', {'form': form})

# 找回密码页面
def password_reset_page(request):
    return render(request, 'password_reset.html')

# TODO 所有交互函数的参数有效性验证都是一坨狗屎，且就算传入了错误的参数（名），也很大概率是不会返回任何错误，只是直接不执行。
#  浏览器端其实没啥问题，但是这对于 API 端来说极大增加了排错工程量

# 测试
@login_required
def contact(request):
    return render(request, 'contact.html')

# 退出登录
@login_required
def user_logout(request):
    logout(request)
    return redirect('/')


@login_required
def help_page(request):
    """帮助文档页面"""
    return render(request, 'help.html')


@login_required
def user_data(request):
    user_data = UserData.objects.filter(user=request.user)
    return render(request, 'user_data.html', {'user_data': user_data})

def get_user_preferences(request):
    user_preference_data, created, result = UserData().get_or_initialize(request=request, new_key="user_preference")
    # TODO 写完这个用于使用 POST 方式获取 user_preferences 的函数。然后还要再写一个界面用来修改和保存
    return


@login_required
def home(request):
    user_preference_data :'UserData'
    user_preference_data, created, result = UserData.get_or_initialize(request=request, new_key="user_preference")
    # TODO 新加一个用户 config ，存储新手教程类和“不再提示”这种配置
    # TODO 还可以加一个，比如上一次创建的日程是什么日程组，下一次默认这个


    user_preference = user_preference_data.get_value(check=False)  # TODO 这里不能 check 由于检查函数的问题，布尔值检查会对 False 直接返回 假
    user_preference_data.set_value(user_preference)
    # 很显然，如果你执行了检查，那么请把检查结果保存

    # 周数计算已迁移到前端JavaScript - 2025-11-02
    # 前端会根据用户设置的week_number_start自动计算并显示

    # 获取事件组数据
    user_data_groups, created = UserData.objects.get_or_create(
        user=request.user, 
        key="events_groups", 
        defaults={"value": json.dumps([
            {"id": "1", "name": "工作", "color": "#3498db"},
            {"id": "2", "name": "学习", "color": "#2ecc71"},
            {"id": "3", "name": "生活", "color": "#e74c3c"},
            {"id": "4", "name": "其他", "color": "#95a5a6"}
        ])}
    )
    events_groups = json.loads(user_data_groups.value)

    # 创建一个上下文字典
    context = {
        "datetime": datetime.datetime.now(),
        'user': request.user,  # 传递用户对象，方便在模板中使用 {{ request.user.username }}
        'events_groups': json.dumps(events_groups)  # 传递事件组数据到前端
    }
    # 初始化 user_planner_data
    user_planner_data, created, result = UserData.get_or_initialize(
        request=request,
        new_key="planner",
        data={
            "dialogue": [],
            "temp_events": [],
            "ai_planning_time": {}
        }
    )

    # 初始化 rrule_series_storage 。否则直接创建的时候不知道为啥会创建两个 rrule_series_storage，找半天找不到错在哪儿
    rrule_series_storage, created, result = UserData.get_or_initialize(request, new_key="rrule_series_storage")

    return render(request, 'home_new.html', context)


@login_required
@csrf_exempt
def change_view(request):
    if request.method == 'POST':
        try:
            # 获取或创建用户设置数据
            user_data, created, result = UserData.get_or_initialize(request=request, new_key="user_interface_settings", )
            
            # 解析请求数据
            request_data = json.loads(request.body)
            
            # 直接保存完整的界面设置，不再使用时间转换
            user_data.set_value(request_data, check=False)
            
            return JsonResponse({'status': 'success', 'message': '设置已保存'}, status=200)
            
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': '无效的JSON数据'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'保存设置失败: {str(e)}'}, status=500)

    return JsonResponse({'status': 'error', 'message': '只支持POST请求'}, status=405)


def user_preferences(request):
    if request.method == 'GET':
        # 获取用户的偏好数据
        user_preference_data, created, result = UserData.get_or_initialize(request, new_key="user_preference")
        user_preference = user_preference_data.get_value()

        # 将 week_number_start 转换为日期格式
        if 'week_number_start' in user_preference and isinstance(user_preference['week_number_start'], dict):
            try:
                # 提取 month 和 day
                month = user_preference['week_number_start'].get('month')
                day = user_preference['week_number_start'].get('day')

                # 假设年份为当前年份
                current_year = datetime.date.today().year

                # 将字符串解析为日期对象
                week_number_start_date = datetime.date(current_year, month, day)
                user_preference['week_number_start'] = week_number_start_date

            except (TypeError, ValueError, KeyError):
                # 如果数据无效，设置为 None
                user_preference['week_number_start'] = None

        # 渲染页面并传递数据
        return render(request, 'user_preferences.html', {'user_preference': user_preference})

    else:
        # 保存用户提交的偏好数据
        updated_preference = request.POST.get('preferences')

        try:
            updated_preference_dict = json.loads(updated_preference)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data.'}, status=400)

        new_week_number_start = updated_preference_dict["week_number_start"]
        new_week_number_start = datetime.datetime.strptime(new_week_number_start, "%Y-%m-%d")
        new_week_number_start = {"month": new_week_number_start.month, "day": new_week_number_start.day}
        updated_preference_dict["week_number_start"] = new_week_number_start

        # updated_preference_dict["auto_ddl"] = 1 if updated_preference_dict["auto_ddl"] else 0


        # 获取或初始化用户偏好数据
        user_preference_data, created, result = UserData.get_or_initialize(request, new_key="user_preference")

        # 设置并保存新的偏好数据
        user_preference_data.set_value(updated_preference_dict,check=True)


        return JsonResponse({'status': 'success', 'message': 'Preferences saved successfully.'})


# 用来把ISO转化成北京时间，蠢蛋AI怎么写了这么多行
def add_8_hours_to_time_data(data):
    """
    输入一个包含时间数据的字典，将其中的 start 和 end 时间加 8 小时，返回修改后的字典。

    参数:
    data (dict): 输入的字典，格式如：{
        'now_view': {
            'viewType': 'dayGridMonth',
            'start': '2025-02-22T16:00:00.000Z',
            'end': '2025-04-05T16:00:00.000Z'
        }
    }

    返回:
    dict: 修改后的时间数据字典
    """
    # 定义一个内部函数，用于处理单个时间字符串
    def process_time(time_str):
        # 去掉时间字符串中的 'Z'，并解析为 datetime 对象
        time_str = time_str.replace('Z', '')
        time_obj = datetime.datetime.fromisoformat(time_str)

        # 加 8 小时
        new_time_obj = time_obj + timedelta(hours=8)

        # 转换回 ISO 8601 格式的字符串
        return new_time_obj.isoformat() + 'Z'


    # 检查输入字典是否包含必要的字段
    if 'now_view' in data and 'start' in data['now_view'] and 'end' in data['now_view']:
        # 获取原始时间数据
        start_time = data['now_view']['start']
        end_time = data['now_view']['end']

        # 更新时间数据


def add_8_hours_to_time_string(time_str):
    """
    将时间字符串加8小时（用于修复时区问题）
    """
    if not time_str:
        return time_str
    
    try:
        # 解析时间字符串
        if time_str.endswith('Z'):
            time_str = time_str[:-1]
        elif '+' in time_str:
            time_str = time_str.split('+')[0]
        
        time_obj = datetime.datetime.fromisoformat(time_str)
        # 加 8 小时
        new_time_obj = time_obj + timedelta(hours=8)
        # 返回 ISO 格式
        return new_time_obj.isoformat()
    except Exception as e:
        logger.error(f"时区转换错误: {e}, 时间字符串: {time_str}")
        return time_str
        data['now_view']['start'] = process_time(start_time)
        data['now_view']['end'] = process_time(end_time)

    else:
        raise ValueError("输入的字典格式不正确，缺少必要的字段")

    return data



# 发送用户设置
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def user_settings(request):
    """用户设置API - 处理获取和保存用户偏好设置"""
    if request.method == 'GET':
        try:
            # 获取用户偏好设置
            user_preference_data, created, result = UserData.get_or_initialize(
                request=request, 
                new_key="user_preference"
            )
            
            if user_preference_data and hasattr(user_preference_data, 'get_value'):
                preferences = user_preference_data.get_value()
                if preferences:
                    # 数据迁移：如果只有旧的week_number_start但没有week_number_periods,自动迁移
                    if ('week_number_start' in preferences and 
                        preferences.get('week_number_start') and 
                        not preferences.get('week_number_periods')):
                        old_start = preferences['week_number_start']
                        preferences['week_number_periods'] = [{
                            'name': '默认学期',
                            'month': old_start.get('month', 2),
                            'day': old_start.get('day', 24)
                        }]
                        # 保存迁移后的数据
                        user_preference_data.set_value(preferences)
                    
                    # 确保show_week_number字段存在
                    if 'show_week_number' not in preferences:
                        preferences['show_week_number'] = True
                    
                    return JsonResponse(preferences, status=200)
            
            # 返回默认值
            return JsonResponse({
                'week_number_start': {'month': 2, 'day': 24},
                'week_number_periods': [{'name': '默认学期', 'month': 2, 'day': 24}],
                'show_week_number': True,
                'auto_ddl': True,
                'default_event_duration': 60,
                'work_hours_start': '09:00',
                'work_hours_end': '18:00',
                'show_weekends': True,
                'week_starts_on': 1,
                'calendar_view_default': 'dayGridMonth',
                'theme': 'light',
                'show_completed_events': True,
                'event_color_by': 'default',
                'reminder_enabled': True,
                'default_reminder_time': 15,
                'reminder_sound': True,
                'ai_enabled': True,
                'ai_auto_suggest': False,
            }, status=200)
            
        except Exception as e:
            return JsonResponse({
                'status': 'error', 
                'message': f'获取设置失败: {str(e)}'
            }, status=500)
    
    elif request.method == 'POST':
        try:
            # 解析请求数据 - 使用 request.data 兼容 DRF
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            # 获取当前设置
            user_preference_data, created, result = UserData.get_or_initialize(
                request=request, 
                new_key="user_preference"
            )
            
            if not user_preference_data or not hasattr(user_preference_data, 'set_value'):
                return JsonResponse({
                    'status': 'error',
                    'message': '无法获取用户设置数据'
                }, status=500)
            
            # 更新设置（使用 DATA_SCHEMA 验证）
            user_preference_data.set_value(data, check=True)
            
            return JsonResponse({
                'status': 'success',
                'message': '设置已保存'
            }, status=200)
            
        except json.JSONDecodeError:
            return JsonResponse({
                'status': 'error',
                'message': '无效的JSON数据'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'保存设置失败: {str(e)}'
            }, status=500)
    
    return JsonResponse({
        'status': 'error', 
        'message': '只支持GET和POST请求'
    }, status=405)

# TODO 在编辑日程的 RRule规则时，events_rrule_series 貌似并不会跟着变，然而暂时没有造成出错

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_events(request):
    """获取events数据 - 委托给views_events中的实现"""
    return get_events_impl(request)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_events(request):
    """更新事件 - 委托给views_events中的实现"""
    return update_events_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_event(request):
    """创建新事件 - 委托给views_events中的实现"""
    return create_event_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_event(request):
    """删除事件 - 委托给views_events中的实现"""
    return ValueError("delete_event  方法已弃用")
    return delete_event_impl(request)

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'name': {'type': str, 'required': True, 'comment': '日程组名称'},
    'description': {'type': str, 'required': False, 'comment': '日程组描述'},
    'color': {'type': str, 'required': True, 'comment': '日程组颜色'},
})
def create_events_group(request):
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        # 使用 validate_body 处理后的数据
        data = request.validated_data
        group_name = data.get('name')
        group_description = data.get('description')
        group_color = data.get('color')

        user_data_groups, created = UserData.objects.get_or_create(user=django_request.user, key="events_groups", defaults={"value": json.dumps([])})
        events_groups = json.loads(user_data_groups.value)

        new_group = {
            "id": str(uuid.uuid4()),
            "name": group_name,
            "description": group_description,
            "color": group_color
        }
        events_groups.append(new_group)
        user_data_groups.value = json.dumps(events_groups)
        user_data_groups.save()

        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)



@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'groupID': {'type': str, 'required': True, 'comment': '日程组ID'},
    'title': {'type': str, 'required': False, 'comment': '新名称'},
    'description': {'type': str, 'required': False, 'comment': '新描述'},
    'color': {'type': str, 'required': False, 'comment': '新颜色'},
})
def update_event_group(request):
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        # 使用 validate_body 处理后的数据
        data = request.validated_data
        group_id = data.get('groupID')
        title = data.get('title')
        description = data.get('description')
        color = data.get('color')
        user_data, created = UserData.objects.get_or_create(user=django_request.user, key="events_groups")
        events_groups = json.loads(user_data.value)

        for group in events_groups:
            if group['id'] == group_id:
                group['name'] = title
                group['description'] = description
                group['color'] = color
                break

        user_data.value = json.dumps(events_groups)
        user_data.save()

        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)



@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'groupIds': {'type': list, 'required': True, 'comment': '要删除的日程组ID列表'},
    'deleteEvents': {'type': bool, 'required': False, 'default': False, 'comment': '是否同时删除组内日程'},
})
def delete_event_groups(request):
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        # 使用 validate_body 处理后的数据
        data = request.validated_data
        group_ids = data.get('groupIds', [])
        delete_events = data.get('deleteEvents', False)

        user_data, created = UserData.objects.get_or_create(user=django_request.user, key="events_groups")
        events_groups = json.loads(user_data.value)

        user_data_events, created = UserData.objects.get_or_create(user=django_request.user, key="events")
        events = json.loads(user_data_events.value)

        # 删除日程组
        events_groups = [group for group in events_groups if group['id'] not in group_ids]  # TODO 这样操作会导致 API 调用的时候，发来了错误的（实际不存在于数据库中的）ID，但仍旧返回 success 的错误

        # 如果需要删除日程组下的所有日程
        if delete_events:
            events = [event for event in events if event['groupID'] not in group_ids]

        # 更新数据库
        user_data.value = json.dumps(events_groups)
        user_data.save()

        user_data_events.value = json.dumps(events)
        user_data_events.save()

        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


import json
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from .models import UserData

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_events(request):
    if request.method == 'POST':
        # 使用 request.data 兼容 DRF Request
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        cookie = data.get('cookie')
        group_id = data.get('groupId')

        if not cookie or not group_id:
            return JsonResponse({'status': 'error', 'message': 'Missing cookie or group ID'}, status=400)

        # 从指定网站获取日程数据（示例逻辑）
        try:
            # 从MUC教务系统网站获取日程数据
            from core.views_import_events import get_response_data
            imported_events = json.loads(get_response_data(cookie))  # 自定义函数，从网站获取数据
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

        # 获取用户的所有日程组
        user_data_groups, created = UserData.objects.get_or_create(user=request.user, key="events_groups")
        events_groups = json.loads(user_data_groups.value)

        # 获取用户的所有事件
        user_data_events, created = UserData.objects.get_or_create(user=request.user, key="events")
        events = json.loads(user_data_events.value)

        # 将新获取的日程数据导入到指定的日程组
        for event in imported_events:
            event['groupID'] = group_id

        events += imported_events

        # 更新数据库
        user_data_events.set_value(events, check=True)

        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

@login_required
def outport_calendar(request):
    return render(request, 'outport_calendar.html')


from django.shortcuts import redirect
from django.http import HttpResponse
from icalendar import Calendar, Event

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_outport_calendar(request):
    # 创建日历对象
    # 获取用户数据中的 outport_calendar_data 和 events
    outport_calendar_data: 'UserData'
    outport_calendar_data, created, result = UserData.get_or_initialize(
        request,
        new_key="outport_calendar_data",
        data={"sent_events_uuid": ["0"], "last_sent_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    )
    outport_calendar_values = outport_calendar_data.get_value()
    sent_events_uuid_before = outport_calendar_values["sent_events_uuid"]
    last_sent_time = outport_calendar_values["last_sent_time"]
    last_sent_time = datetime.datetime.fromisoformat(last_sent_time)

    events_data, created, result = UserData.get_or_initialize(request, new_key="events")
    all_events = events_data.get_value()
    all_events_uuid = [one_event["id"] for one_event in all_events]

    # 获取前端发来的模式参数，默认为 "new"
    mode = request.GET.get('mode', 'new')  # "new" 表示只发送新增日程，"all" 表示发送所有日程
    user_choice = request.GET.get("user_choice")

    if mode == "new":
        # 模式一：只发送新增日程
        sent_events_uuid_new = []
        # 检查是否有日程的 last_modified 时间早于上一次发送时间
        modified_events = []

        for event in all_events:
            last_modified = datetime.datetime.fromisoformat(event.get("last_modified", ""))
            if (last_modified > last_sent_time) and (event["id"] in sent_events_uuid_before):
                modified_events.append(event)

        # 如果有修改过的日程，提示用户选择处理方式
        if modified_events:
            # 提示用户
            # TODO 新增日程为空时的检查回复

            if user_choice == "1":
                sent_events_uuid_new += [event["id"] for event in modified_events]
                # 包含这些日程
            elif user_choice == "2":
                # 忽略
                pass
            else:
                return HttpResponseBadRequest("无效的用户选择。有效的选项为 '1', '2', 或 '3'。")

        # 把新增的日程全部加入
        for one_event_uuid in all_events_uuid:
            if one_event_uuid not in sent_events_uuid_before:
                sent_events_uuid_new.append(one_event_uuid)

        cal = create_calendar(all_events_uuid=sent_events_uuid_new, all_events=all_events)
        
        # 删除 sent_events_uuid 中已经不存在于 events 中的 uuid（即已经被删除的日程）
        sent_events_uuid_new += [
            uid for uid in sent_events_uuid_before if uid in all_events_uuid
        ]
        outport_calendar_values["sent_events_uuid"] = sent_events_uuid_new
    elif mode == "all":
        # 模式二：发送所有日程
        sent_events_uuid_new = all_events_uuid
        cal = create_calendar(all_events_uuid=sent_events_uuid_new, all_events=all_events)

        # 更新 sent_events_uuid 为当前所有日程的 uuid
        outport_calendar_values["sent_events_uuid"] = sent_events_uuid_new
        
    else:
        return HttpResponseBadRequest("无效的导出模式。有效的模式为 'new' 或 'all'。")

    # 保存更新后的 outport_calendar_values
    outport_calendar_values["last_sent_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    outport_calendar_data.set_value(outport_calendar_values)

    # 返回日历响应
    response = HttpResponse(cal.to_ical(), content_type='text/calendar')
    response['Content-Disposition'] = 'attachment; filename=calendar.ics'
    return response

def check_modified_events(request):
    # 其实我觉得这个函数完全可以集成在 get_outport_calendar 里面，但是 AI 写都写了那就算了
    # TODO 以后要加上选择某些日程组导出
    mode = request.GET.get("mode")
    modified_events = []
    outport_calendar_data: 'UserData'
    outport_calendar_data, created, result = UserData.get_or_initialize(
        request,
        new_key="outport_calendar_data",
        data={"sent_events_uuid": ["0"], "last_sent_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    )
    outport_calendar_values = outport_calendar_data.get_value()
    sent_events_uuid_before = outport_calendar_values["sent_events_uuid"]
    last_sent_time = outport_calendar_values["last_sent_time"]
    last_sent_time = datetime.datetime.fromisoformat(last_sent_time)

    events_data, created, result = UserData.get_or_initialize(request, new_key="events")
    all_events = events_data.get_value()

    if mode == "new":
        for event in all_events:
            last_modified = datetime.datetime.fromisoformat(event.get("last_modified", ""))
            if (last_modified > last_sent_time) and (event["id"] in sent_events_uuid_before):
                modified_events.append({"description": event["description"], "title": event["title"]})

    return JsonResponse({"modified_events": modified_events})


def create_calendar(all_events_uuid: List[str], all_events: List[dict])->'Calendar':
    cal = Calendar()
    cal.add('prodid', '//My Calendar//mxm.dk//')
    cal.add('version', '2.0')
    
    for one_event in all_events:
        # 检查事件ID是否存在于all_events_uuid列表中
        if one_event['id'] in all_events_uuid:
            event = Event()
            event.add('summary', one_event['title'])
            # 将 start 和 end 转换为 datetime 对象
            start_time = datetime.datetime.fromisoformat(one_event['start'])
            end_time = datetime.datetime.fromisoformat(one_event['end'])
            event.add('dtstart', start_time)
            event.add('dtend', end_time)
            event.add('description', one_event['description'])
            cal.add_component(event)
    return cal

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_resources(request):
    """
    测试用
    :param request:
    :return:
    """
    user_data, created = UserData.objects.get_or_create(user=request.user, key="resources", defaults={"value": json.dumps([
        { "id": "a", "title": "Auditorium A", "occupancy": 40 },
        { "id": "b", "title": "Auditorium B", "occupancy": 40, "eventColor": "green" },
        { "id": "c", "title": "Auditorium C", "occupancy": 40, "eventColor": "orange" },
        { "id": "d", "title": "Auditorium D", "occupancy": 40, "children": [
            { "id": "d1", "title": "Room D1", "occupancy": 10 },
            { "id": "d2", "title": "Room D2", "occupancy": 10 }
        ] }
    ])})
    resources = user_data.get_value()
    return JsonResponse(resources, safe=False)

# ========== Reminder 相关 API ==========

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_reminders(request):
    """获取所有提醒 - 重定向到新的模块"""
    return get_reminders_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_reminder(request):
    """创建新提醒 - 重定向到新的模块"""
    return create_reminder_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_reminder(request):
    """更新提醒 - 重定向到新的模块"""
    return update_reminder_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_reminder_status(request):
    """更新提醒状态 - 重定向到新的模块"""
    return update_reminder_status_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_edit_reminders(request):
    """批量编辑重复提醒 - 重定向到新的模块"""
    return bulk_edit_reminders_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def convert_recurring_to_single(request):
    """将重复提醒转换为单次提醒 - 重定向到新的模块"""
    return convert_recurring_to_single_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def maintain_reminders(request):
    """维护提醒实例 - 重定向到新的模块"""
    return maintain_reminders_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_reminder(request):
    """删除提醒 - 重定向到新的模块"""
    return delete_reminder_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def snooze_reminder(request):
    """延迟提醒 - 重定向到新的模块"""
    return snooze_reminder_impl(request)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def dismiss_reminder(request):
    """忽略/关闭提醒 - 重定向到新的模块"""
    return dismiss_reminder_impl(request)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_reminder(request):
    """完成提醒 - 重定向到新的模块"""
    return complete_reminder_impl(request)


def get_pending_reminders(request):
    """获取待触发的提醒 - 重定向到新的模块"""
    return get_pending_reminders_impl(request)


# ========== TO-DO 相关 API ==========

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_todos(request):
    """获取所有待办事项"""
    if request.method == 'GET':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_todos_data, created, result = UserData.get_or_initialize(django_request, new_key="todos")
        todos = user_todos_data.get_value()
        
        return JsonResponse({'todos': todos})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'title': {'type': str, 'required': True, 'comment': '待办事项标题'},
    'description': {'type': str, 'synonyms': ['context', 'details', 'content'], 'alias': 'context', 'comment': '详细描述'},
    'due_date': {'type': str, 'default': '', 'comment': '截止日期，格式：YYYY-MM-DD'},
    'estimated_duration': {'type': (str, int), 'default': '', 'comment': '预计耗时（分钟）'},
    'importance': {'type': str, 'default': '', 'choices': ['important', 'not-important', ''], 'comment': '重要性'},
    'urgency': {'type': str, 'default': '', 'choices': ['urgent', 'not-urgent', ''], 'comment': '紧急程度'},
    'groupID': {'type': str, 'default': '', 'comment': '关联的日程组ID'}
})
def create_todo(request):
    """创建新待办事项"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_todos_data, created, result = UserData.get_or_initialize(django_request, new_key="todos")
        todos = user_todos_data.get_value()
        
        # 使用验证后的数据
        data = request.validated_data
        logger.debug(f"1108 {data}")
        
        title = data.get('title')
        description = data.get('description')
        due_date = data.get('due_date')
        estimated_duration = data.get('estimated_duration')
        importance = data.get('importance')
        urgency = data.get('urgency')
        group_id = data.get('groupID')
        
        new_todo = {
            "id": str(uuid.uuid4()),
            "title": title,
            "description": description,
            "due_date": due_date,
            "estimated_duration": estimated_duration,
            "importance": importance,
            "urgency": urgency,
            "groupID": group_id,
            "status": "pending",
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        todos.append(new_todo)
        user_todos_data.set_value(todos)
        
        return JsonResponse({'status': 'success', 'todo': new_todo})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'id': {'type': str, 'required': True, 'comment': '待办事项ID'},
    'title': {'type': str, 'comment': '标题'},
    'description': {'type': str, 'synonyms': ['context', 'details', 'content'], 'alias': 'context', 'comment': '详细描述'},
    'due_date': {'type': str, 'comment': '截止日期,格式：YYYY-MM-DD'},
    'estimated_duration': {'type': (str, int), 'default': '', 'comment': '预计耗时'},
    'importance': {'type': str, 'default': '', 'choices': ['important', 'not-important', ''], 'comment': '重要性'},
    'urgency': {'type': str, 'default': '', 'choices': ['urgent', 'not-urgent', ''], 'comment': '紧急程度'},
    'groupID': {'type': str, 'comment': '关联日程组ID'},
    'status': {'type': str, 'choices': ['pending', 'completed', 'converted'], 'comment': '状态'}
})
def update_todo(request):
    """更新待办事项"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_todos_data, created, result = UserData.get_or_initialize(django_request, new_key="todos")
        todos = user_todos_data.get_value()
        
        # 使用验证后的数据
        data = request.validated_data
        todo_id = data.get('id')
        
        # 查找要更新的待办事项
        todo_found = False
        for todo in todos:
            if todo['id'] == todo_id:
                # 更新字段 - 仅更新请求中提供的字段
                if 'title' in data:
                    todo['title'] = data['title']
                if 'description' in data:
                    todo['description'] = data['description']
                if 'due_date' in data:
                    todo['due_date'] = data['due_date']
                if 'estimated_duration' in data:
                    todo['estimated_duration'] = data['estimated_duration']
                if 'importance' in data:
                    todo['importance'] = data['importance']
                if 'urgency' in data:
                    todo['urgency'] = data['urgency']
                if 'groupID' in data:
                    todo['groupID'] = data['groupID']
                if 'status' in data:
                    todo['status'] = data['status']
                
                todo['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                todo_found = True
                break
        
        if not todo_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的待办事项'}, status=404)
        
        user_todos_data.set_value(todos)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'id': {'type': str, 'required': True, 'comment': '待办事项ID'}
})
def delete_todo(request):
    """删除待办事项"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_todos_data, created, result = UserData.get_or_initialize(django_request, new_key="todos")
        todos = user_todos_data.get_value()
        
        # 使用验证后的数据
        data = request.validated_data
        todo_id = data.get('id')
        
        # 查找并删除待办事项
        original_length = len(todos)
        todos[:] = [todo for todo in todos if todo['id'] != todo_id]
        
        if len(todos) == original_length:
            return JsonResponse({'status': 'error', 'message': '未找到指定的待办事项'}, status=404)
        
        user_todos_data.set_value(todos)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@validate_body({
    'id': {'type': str, 'required': True, 'comment': '待办事项ID'},
    'start_time': {'type': str, 'required': True, 'comment': '日程开始时间，格式：YYYY-MM-DDTHH:MM:SS'},
    'end_time': {'type': str, 'required': True, 'comment': '日程结束时间，格式：YYYY-MM-DDTHH:MM:SS'}
})
def convert_todo_to_event(request):
    """将待办事项转换为日程事件"""
    if request.method == 'POST':
        # 获取原生 Django request
        django_request = get_django_request(request)
        
        user_todos_data, created, result = UserData.get_or_initialize(django_request, new_key="todos")
        todos = user_todos_data.get_value()
        
        user_events_data, created, result = UserData.get_or_initialize(django_request, new_key="events")
        events = user_events_data.get_value()
        
        # 使用 request.validated_data
        data = request.validated_data
        todo_id = data.get('id')
        start_time = data.get('start_time')
        end_time = data.get('end_time')

        # 查找待办事项
        todo_found = None
        for todo in todos:
            if todo['id'] == todo_id:
                todo_found = todo
                break
        
        if not todo_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的待办事项'}, status=404)
        
        # 创建新事件
        new_event = {
            "id": str(uuid.uuid4()),
            "title": todo_found['title'],
            "start": start_time,
            "end": end_time,
            "description": todo_found['description'],
            "importance": todo_found['importance'],
            "urgency": todo_found['urgency'],
            "groupID": todo_found['groupID'],
            "ddl": todo_found.get('due_date', ''),
            "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "converted_from_todo": todo_id
        }
        
        events.append(new_event)
        user_events_data.set_value(events)
        
        # 标记待办事项为已转换
        todo_found['status'] = 'converted'
        todo_found['converted_to_event'] = new_event['id']
        todo_found['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_todos_data.set_value(todos)
        
        return JsonResponse({'status': 'success', 'event': new_event})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def mark_notification_sent(request):
    """标记通知已发送（占位函数）"""
    if request.method == 'POST':
        # 简单的占位实现，直接返回成功
        # TODO: 将来可以在这里记录通知发送历史
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def three_body(request):
    return render(request, 'three_body.html')

def animation(request):
    return render(request, 'animation.html')

def friendly_link(request):
    return render(request, 'memory.html')


# ===== 用户账户管理 API =====

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_username(request):
    """
    修改用户名
    POST /api/user/change-username/
    Body: {
        "new_username": "新用户名",
        "password": "当前密码（用于验证）"
    }
    """
    try:
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        new_username = data.get('new_username', '').strip()
        password = data.get('password', '')
        
        if not new_username:
            return Response(
                {'error': '新用户名不能为空'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not password:
            return Response(
                {'error': '请输入当前密码以验证身份'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 验证当前密码
        if not request.user.check_password(password):
            return Response(
                {'error': '当前密码错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # 检查新用户名是否已存在
        from django.contrib.auth.models import User
        if User.objects.filter(username=new_username).exclude(id=request.user.id).exists():
            return Response(
                {'error': '该用户名已被使用'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 保存旧用户名用于日志
        old_username = request.user.username
        
        # 修改用户名
        request.user.username = new_username
        request.user.save()
        
        logger.info(f"User {old_username} changed username to {new_username}")
        
        return Response({
            'message': '用户名修改成功',
            'new_username': new_username
        })
        
    except Exception as e:
        logger.error(f"Change username error: {str(e)}")
        return Response(
            {'error': f'修改用户名失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """
    修改密码
    POST /api/user/change-password/
    Body: {
        "old_password": "当前密码",
        "new_password": "新密码",
        "confirm_password": "确认新密码"
    }
    """
    try:
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')
        
        if not old_password:
            return Response(
                {'error': '请输入当前密码'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not new_password:
            return Response(
                {'error': '请输入新密码'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if new_password != confirm_password:
            return Response(
                {'error': '两次输入的新密码不一致'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 验证当前密码
        if not request.user.check_password(old_password):
            return Response(
                {'error': '当前密码错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # 使用 Django 的密码验证器检查新密码强度
        # 这包括：最小长度、不能与用户信息太相似、不能是常见密码、不能全是数字
        try:
            validate_password(new_password, user=request.user)
        except ValidationError as e:
            # 返回所有验证错误信息
            error_messages = list(e.messages)
            return Response(
                {'error': '密码不符合要求：' + '；'.join(error_messages)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 修改密码
        request.user.set_password(new_password)
        request.user.save()
        
        logger.info(f"User {request.user.username} changed password")
        
        # 重要：修改密码后需要更新 session，否则用户会被登出
        update_session_auth_hash(request, request.user)
        
        return Response({
            'message': '密码修改成功'
        })
        
    except Exception as e:
        logger.error(f"Change password error: {str(e)}")
        return Response(
            {'error': f'修改密码失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ===== 找回密码功能 =====

@api_view(['POST'])
@permission_classes([])  # 允许未认证用户访问
def request_password_reset(request):
    """
    请求密码重置验证码
    POST /api/password-reset/request/
    Body: {
        "email": "用户邮箱"
    }
    """
    try:
        from .models import PasswordResetCode
        from django.contrib.auth.models import User
        
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        email = data.get('email', '').strip()
        
        if not email:
            return Response(
                {'error': '请输入邮箱地址'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 查找用户（如果有多个用户使用同一邮箱，使用最新注册的）
        try:
            user = User.objects.filter(email=email).order_by('-date_joined').first()
            if not user:
                raise User.DoesNotExist
        except User.DoesNotExist:
            # 为了安全，即使邮箱不存在也返回成功消息
            return Response({
                'message': '如果该邮箱已注册，验证码将发送到您的邮箱',
                'email': email
            })
        
        # 生成验证码
        reset_code = PasswordResetCode.generate_code(user)
        
        # TODO: 这里应该发送邮件，但目前先在响应中返回验证码（仅用于开发测试）
        # 在生产环境中，应该通过邮件发送验证码，而不是直接返回
        logger.info(f"Password reset code for {email}: {reset_code.code}")
        
        return Response({
            'message': '验证码已生成，请查看服务器日志（生产环境将发送到邮箱）',
            'email': email,
            'code': reset_code.code,  # 仅用于开发测试，生产环境应删除此行
            'expires_in': '15分钟'
        })
        
    except Exception as e:
        logger.error(f"Request password reset error: {str(e)}")
        return Response(
            {'error': f'请求失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([])  # 允许未认证用户访问
def verify_reset_code(request):
    """
    验证重置验证码
    POST /api/password-reset/verify/
    Body: {
        "email": "用户邮箱",
        "code": "验证码"
    }
    """
    try:
        from .models import PasswordResetCode
        
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        email = data.get('email', '').strip()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return Response(
                {'error': '请输入邮箱和验证码'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 验证验证码
        is_valid, user, reset_code_obj = PasswordResetCode.verify_code(email, code)
        
        if not is_valid:
            return Response(
                {'error': '验证码无效或已过期'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({
            'message': '验证码正确',
            'email': email
        })
        
    except Exception as e:
        logger.error(f"Verify reset code error: {str(e)}")
        return Response(
            {'error': f'验证失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([])  # 允许未认证用户访问
def reset_password(request):
    """
    重置密码
    POST /api/password-reset/reset/
    Body: {
        "email": "用户邮箱",
        "code": "验证码",
        "new_password": "新密码",
        "confirm_password": "确认新密码"
    }
    """
    try:
        from .models import PasswordResetCode
        from django.contrib.auth.models import User
        
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        email = data.get('email', '').strip()
        code = data.get('code', '').strip()
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')
        
        if not email or not code:
            return Response(
                {'error': '请输入邮箱和验证码'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not new_password:
            return Response(
                {'error': '请输入新密码'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if new_password != confirm_password:
            return Response(
                {'error': '两次输入的密码不一致'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 验证验证码
        is_valid, user, reset_code_obj = PasswordResetCode.verify_code(email, code)
        
        if not is_valid:
            return Response(
                {'error': '验证码无效或已过期'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 使用 Django 的密码验证器检查新密码强度
        try:
            validate_password(new_password, user=user)
        except ValidationError as e:
            error_messages = list(e.messages)
            return Response(
                {'error': '密码不符合要求：' + '；'.join(error_messages)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 重置密码
        user.set_password(new_password)
        user.save()
        
        # 标记验证码为已使用
        reset_code_obj.is_used = True
        reset_code_obj.save()
        
        logger.info(f"User {user.username} reset password via email {email}")
        
        return Response({
            'message': '密码重置成功，请使用新密码登录'
        })
        
    except Exception as e:
        logger.error(f"Reset password error: {str(e)}")
        return Response(
            {'error': f'重置密码失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ===== 基于 Token 的密码重置功能 =====

@api_view(['POST'])
@permission_classes([])  # 允许未认证用户访问
def reset_password_with_token(request):
    """
    使用用户名和 API Token 重置密码
    POST /api/password-reset/token/
    Body: {
        "username": "用户名",
        "token": "API Token",
        "new_password": "新密码",
        "confirm_password": "确认新密码"
    }
    """
    try:
        from rest_framework.authtoken.models import Token
        from django.contrib.auth.models import User
        
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        username = data.get('username', '').strip()
        token_key = data.get('token', '').strip()
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')
        
        if not username or not token_key:
            return Response(
                {'error': '请输入用户名和 Token'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not new_password:
            return Response(
                {'error': '请输入新密码'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if new_password != confirm_password:
            return Response(
                {'error': '两次输入的密码不一致'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 验证用户名和 Token 是否匹配
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response(
                {'error': '用户名或 Token 错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # 验证 Token
        try:
            token = Token.objects.get(key=token_key)
            if token.user != user:
                return Response(
                    {'error': '用户名或 Token 错误'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
        except Token.DoesNotExist:
            return Response(
                {'error': '用户名或 Token 错误（Token 可能已被删除）'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # 使用 Django 的密码验证器检查新密码强度
        try:
            validate_password(new_password, user=user)
        except ValidationError as e:
            error_messages = list(e.messages)
            return Response(
                {'error': '密码不符合要求：' + '；'.join(error_messages)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 重置密码
        user.set_password(new_password)
        user.save()
        
        logger.info(f"User {user.username} reset password using API Token")
        
        return Response({
            'message': '密码重置成功，请使用新密码登录'
        })
        
    except Exception as e:
        logger.error(f"Reset password with token error: {str(e)}")
        return Response(
            {'error': f'重置密码失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


