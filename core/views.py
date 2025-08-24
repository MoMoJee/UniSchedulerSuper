
# Create your views here.
import datetime
from typing import List
import json
import uuid
import markdown
import logging
import requests
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
    if request:
        return IntegratedReminderManager(request=request)
    else:
        return IntegratedReminderManager()

from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import logout
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest

from .forms import RegisterForm
from .models import UserData

logger = logging.getLogger("logger")

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

# TODO 加一个用户偏好设置，包括:
#  1. 是否默认加DDL
#  2. AI选取

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
    user_preference_data, created, result = UserData().get_or_initialize(request=request, new_key="user_preference",
                                                                         data={
                                                                             "week_number_start": {"month": 2, "day": 24},  # TODO 这个以后要让用户可以自己修改
                                                                             "auto_ddl": True     # 设置起始日期为 2 月 24 日
                                                                         })
    # TODO 新加一个用户 config ，存储新手教程类和“不再提示”这种配置
    # TODO 还可以加一个，比如上一次创建的日程是什么日程组，下一次默认这个


    user_preference = user_preference_data.get_value(check=False)  # TODO 这里不能 check 由于检查函数的问题，布尔值检查会对 False 直接返回 假
    user_preference_data.set_value(user_preference)
    # 很显然，如果你执行了检查，那么请把检查结果保存

    week_number_start = user_preference["week_number_start"]
    start_date = datetime.date(datetime.date.today().year, week_number_start["month"], week_number_start["day"])
    # 计算当前日期与起始日期之间的天数差
    delta = datetime.date.today() - start_date
    # 计算是第几周（假设每周7天）
    week_number = delta.days // 7 + 1

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
        "currentWeek": week_number,
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

    return render(request, 'core/home_new.html', context)


@login_required
@csrf_exempt
def change_view(request):
    if request.method == 'POST':
        try:
            # 获取或创建用户设置数据
            user_data, created, result = UserData().get_or_initialize(request=request, new_key="user_interface_settings", )
            
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
# TODO 把AI设置集成进这个数据
@login_required
@csrf_exempt
def user_settings(request):
    if request.method == 'GET':
        try:
            # 尝试获取新的界面设置
            user_data, created, result = UserData().get_or_initialize(request=request, new_key="user_interface_settings")
            if user_data and hasattr(user_data, 'get_value'):
                interface_settings = user_data.get_value()
                if interface_settings:
                    return JsonResponse(interface_settings, status=200)
            
            # 如果没有新设置，返回空对象，让前端使用默认值
            return JsonResponse({}, status=200)
            
        except Exception as e:
            # 如果出错，返回空对象
            return JsonResponse({}, status=200)

    return JsonResponse({'status': 'error', 'message': '只支持GET请求'}, status=405)



@login_required
def get_events(request):
    if request.method == 'GET':
        # 自动新建一个日程

        # 获取当前时间
        now = datetime.datetime.now()
        # 找到最近的整点
        next_hour = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
        # 计算一天之后的时间
        one_day_later = next_hour + datetime.timedelta(hours=1)
        # 格式化为指定的格式
        next_hour_formatted = next_hour.strftime("%Y-%m-%dT%H:%M:%S")
        one_day_later_formatted = one_day_later.strftime("%Y-%m-%dT%H:%M:%S")

        user_data: 'UserData'
        # 当没有读取到events的值（即新用户）的时候，自动新建一个任务
        user_data, created, result = UserData.get_or_initialize(request=request, new_key="events", data=[
            {
                "id": '1',
                "title": "让我们开始吧！",
                "start": next_hour_formatted,
                "end": one_day_later_formatted,
                "backgroundColor": "red",
                "description": "花一小时时间，学习如何使用我们的计划工具！",
                "importance": "important",
                "urgency": "urgent",
                "groupID": "1",
                "ddl": "",
                "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ])

        # 获取用户的所有日程组
        user_data_groups, created = UserData.objects.get_or_create(user=request.user, key="events_groups", defaults={"value": json.dumps([
            {
                "id": '1',
                "name": "学习如何使用日程组！",
                "description": "进阶工具：日程组，继续学习如何使用我们的计划工具！",
                "color": "red"
            }
        ])})

        events_groups = json.loads(user_data_groups.value)

        events = user_data.get_value(check=True)  # 设为 True ，每次服务器修改都能让用户端实时更新
        user_data.set_value(events)
        if not events:
            events = []
        # 返回事件和日程组数据
        if not events_groups:
            events_groups = []

            # 返回事件和日程组数据
        return JsonResponse({"events": events, "events_groups": events_groups})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)




@csrf_exempt
@login_required # 如果前端和后端不在同一域，可能需要禁用 CSRF 保护
def update_events(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        event_id = data.get('eventId')
        new_start = data.get('newStart')
        new_end = data.get('newEnd')
        title = data.get('title')
        description = data.get('description')
        importance = data.get('importance')
        urgency = data.get('urgency')
        group_id = data.get('groupID', '')  # 默认为空字符串
        ddl = data.get('ddl')
        last_modified = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")




        # 获取当前用户的 UserData 对象

        user_data, created, result = UserData.get_or_initialize(
            request=request,
            new_key="events",
        )

        # 获取存储的 events 数据
        events = user_data.get_value(check=True)
        events = convert_time_format(events)

        user_temp_events_data: 'UserData'
        user_temp_events_data, created, result = UserData.get_or_initialize(
            request=request,
            new_key="planner",
            data={
                "dialogue": [],
                "temp_events": [],
                "ai_planning_time": {}
                }
        )

        planner_data = user_temp_events_data.get_value()

        temp_events = planner_data["temp_events"]

        # 查找需要更新的事件
        for event in events:
            if event['id'] == event_id:
                event['start'] = new_start
                event['end'] = new_end
                event['title'] = title
                event['description'] = description
                event['importance'] = importance
                event['urgency'] = urgency
                event['groupID'] = group_id
                event['ddl'] = ddl
                event['last_modified'] = last_modified
                # 将更新后的数据保存回数据库
                user_data.set_value(events)
                # 返回响应
                return JsonResponse({'status': 'success'})

                # 查找temp需要更新的事件，这里做的逻辑是在临时事件未保存时只是在临时数据那里修改
                # TODO 后面可能加入更高级的算法，让用户改过的数据不被AI动（PS：我懒得改了）

        for event in temp_events:
            if event['id'] == event_id:
                event['start'] = new_start
                event['end'] = new_end
                event['title'] = title
                event['description'] = description
                event['importance'] = importance
                event['urgency'] = urgency
                event['groupID'] = group_id
                event['ddl'] = ddl
                event['last_modified'] = last_modified
                # 将更新后的数据保存回数据库
                planner_data["temp_events"] = temp_events
                user_temp_events_data.set_value(planner_data)
                # 返回响应
                return JsonResponse({'status': 'success'})


    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)



def convert_time_format(events):
    """
    解析事件列表，将UTC时间转换为本地时间（减去8小时）。
    :param events: 事件列表，每个事件是一个字典，包含时间信息。
    :return: 转换后的时间列表。
    """
    for event in events:
        # 检查 'start' 和 'end' 时间是否为 UTC 时间（以 'Z' 结尾）
        for key in ['start', 'end']:
            if event[key].endswith('Z'):
                # 转换为 datetime 对象并减去8小时
                utc_time = datetime.datetime.fromisoformat(event[key].replace('Z', '+00:00'))
                local_time = utc_time - timedelta(hours=-8)
                # 格式化为本地时间格式
                event[key] = local_time.strftime('%Y-%m-%dT%H:%M')
    return events


@login_required
@csrf_exempt
def create_event(request):
    # todo 加一个批量生产重复日程，我觉得可以作为一种日程组？或者给加一个重复日程加个标签？
    if request.method == 'POST':
        user_events_data, created, result = UserData.get_or_initialize(request, new_key="events")
        events = user_events_data.get_value()
        user_preference_data, created, result = UserData.get_or_initialize(request, new_key="user_preference")
        user_preference = user_preference_data.get_value()

        data = json.loads(request.body)
        title = data.get('title')
        start = data.get('start')
        end = data.get('end')
        description = data.get('description')
        importance = data.get('importance')
        urgency = data.get('urgency')
        group_id = data.get('groupId')

        # 不需要修复时区问题，前端传过来的已经是正确的时间
        # start = add_8_hours_to_time_string(start)
        # end = add_8_hours_to_time_string(end)

        if user_preference["auto_ddl"]:
            ddl = data.get('ddl')
            # if ddl:
            #     ddl = add_8_hours_to_time_string(ddl)
        else:
            ddl = ""

        new_event = {
            "id": str(uuid.uuid4()),
            "title": title,
            "start": start,
            "end": end,
            "description": description,
            "importance": importance,
            "urgency": urgency,
            "groupID": group_id,
            "ddl": ddl,
            "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        events.append(new_event)
        user_events_data.set_value(events)

        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


@csrf_exempt
@login_required
def delete_event(request):
    if request.method == 'POST':
        # 解析 JSON 数据
        try:
            data = json.loads(request.body)
            event_id = data.get('eventId')
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)

        if event_id is None:
            return JsonResponse({'status': 'error', 'message': 'eventId is missing'}, status=400)

        user_data, created = UserData.objects.get_or_create(
            user=request.user,
            key="events",
            defaults={"value": json.dumps([])}
        )
        events = json.loads(user_data.value)

        user_temp_events_data, created = UserData.objects.get_or_create(user=request.user, key="planner")
        planner_data = user_temp_events_data.get_value()
        temp_events = planner_data["temp_events"]



        # 删除指定的事件
        events = [event for event in events if event['id'] != event_id]
        temp_events = [event for event in temp_events if event['id'] != event_id]
        # 将更新后的数据保存回数据库
        # TODO 同上，这里可能也要做类似的逻辑让AI不改
        planner_data["temp_events"] = temp_events
        user_temp_events_data.value = json.dumps(planner_data)
        user_temp_events_data.save()

        user_data.value = json.dumps(events)
        user_data.save()

        return JsonResponse({'status': 'success'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

@login_required
@csrf_exempt
def create_events_group(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        group_name = data.get('name')
        group_description = data.get('description')
        group_color = data.get('color')

        user_data_groups, created = UserData.objects.get_or_create(user=request.user, key="events_groups", defaults={"value": json.dumps([])})
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



@login_required
@csrf_exempt
def update_event_group(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        group_id = data.get('groupID')
        title = data.get('title')
        description = data.get('description')
        color = data.get('color')
        user_data, created = UserData.objects.get_or_create(user=request.user, key="events_groups")
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



@login_required
@csrf_exempt
def delete_event_groups(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        group_ids = data.get('groupIds', [])
        delete_events = data.get('deleteEvents', False)

        user_data, created = UserData.objects.get_or_create(user=request.user, key="events_groups")
        events_groups = json.loads(user_data.value)

        user_data_events, created = UserData.objects.get_or_create(user=request.user, key="events")
        events = json.loads(user_data_events.value)

        # 删除日程组
        events_groups = [group for group in events_groups if group['id'] not in group_ids]

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

@login_required
@csrf_exempt
def import_events(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        cookie = data.get('cookie')
        group_id = data.get('groupId')

        if not cookie or not group_id:
            return JsonResponse({'status': 'error', 'message': 'Missing cookie or group ID'}, status=400)

        # 从指定网站获取日程数据（示例逻辑）
        try:
            # 假设从某个网站获取日程数据
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




def transform_json_data(json_str):
    """
    将输入的 JSON 字符串转换为指定格式。

    参数:
        json_str (str): 原始 JSON 字符串。

    返回:
        str: 转换后的 JSON 字符串。
    """
    try:
        # 解析原始 JSON 数据
        data = json.loads(json_str)

        # 转换每个字典
        transformed_data = []
        for item in data:
            # 确保时间字符串包含秒部分
            start_time = item["start"]
            end_time = item["end"]

            if len(start_time.split(":")) == 2:  # 如果只有小时和分钟
                start_time += ":00"
            if len(end_time.split(":")) == 2:  # 如果只有小时和分钟
                end_time += ":00"

            transformed_item = {
                "id": str(uuid.uuid4()),
                "title": item["title"],
                "start": datetime.datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").isoformat().replace("+00:00", "Z"),
                "end": datetime.datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").isoformat().replace("+00:00", "Z"),
                "description": item.get("showmsg", ""),  # 如果 showmsg 不存在，则为空字符串
                "importance": "",
                "urgency": "",
                "groupID": "",
                "ddl": "",
                "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            transformed_data.append(transformed_item)

        # 将结果转换为 JSON 字符串
        return json.dumps(transformed_data, ensure_ascii=False, indent=4)

    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {e}")
        return None
    except Exception as e:
        print(f"转换错误: {e}")
        return None

def get_response_data(cookie):
    cookie = cookie.strip()  # 去除首尾空格
    cookie = cookie.replace(' ', '')  # 去除中间的空格

# 目标 URL
    url = "https://jwxs.muc.edu.cn/main/queryMyProctorFull"

    # 请求头（根据浏览器提供的信息）
    headers = {
        "Cookie": cookie,
        "Referer": "https://jwxs.muc.edu.cn/index",
    }

    # POST 请求的表单数据（根据实际需要填写）
    response_data = {
        "flag": "1"  # 示例数据，根据实际需求调整
    }

    # 发送 POST 请求
    response = requests.post(url, headers=headers, data=response_data)

    # 检查响应
    if response.status_code == 200:
        print("请求成功！")
    else:
        print(f"请求失败，状态码：{response.status_code}")
        print("响应内容：")
        print(response.text)  # 打印错误信息

    if response.status_code == 200:
        response_data = json.loads(response.text)["data"]


    result = transform_json_data(response_data)

    return result

@login_required
def outport_calendar(request):
    return render(request, 'outport_calendar.html')


from django.shortcuts import redirect
from django.http import HttpResponse
from icalendar import Calendar, Event

@login_required
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

def get_resources(request):
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


def friendly_link(request):
    return render(request, 'memory.html')


# ========== Reminder 相关 API ==========

@csrf_exempt
def get_reminders(request):
    """获取所有提醒"""
    if request.method == 'GET':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        # 自动检查并生成缺失的重复提醒实例
        new_instances_generated = auto_generate_missing_instances(reminders)
        
        if new_instances_generated > 0:
            # 如果生成了新实例，保存更新后的数据
            user_reminders_data.set_value(reminders)
            print(f"DEBUG: Auto-generated {new_instances_generated} new reminder instances")
        
        # 返回提醒数据
        return JsonResponse({'reminders': reminders})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def auto_generate_missing_instances(reminders):
    """自动生成缺失的重复提醒实例
    
    Args:
        reminders: 提醒列表，会被直接修改
    
    Returns:
        int: 生成的新实例数量
    """
    new_instances_count = 0
    now = datetime.datetime.now()
    
    # 获取所有重复系列
    recurring_series = {}
    for reminder in reminders:
        series_id = reminder.get('series_id')
        rrule = reminder.get('rrule')
        
        if series_id and rrule and 'FREQ=' in rrule and not reminder.get('is_detached', False):
            # 只处理没有截止时间的重复提醒（无UNTIL的）
            if 'UNTIL=' not in rrule:
                if series_id not in recurring_series:
                    recurring_series[series_id] = {
                        'reminders': [],
                        'rrule': rrule,
                        'base_reminder': reminder
                    }
                recurring_series[series_id]['reminders'].append(reminder)
    
    # 检查每个系列是否需要生成新实例
    for series_id, series_data in recurring_series.items():
        series_reminders = series_data['reminders']
        rrule = series_data['rrule']
        base_reminder = series_data['base_reminder']
        
        # 找到最晚的提醒时间
        latest_time = None
        for reminder in series_reminders:
            trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
            if latest_time is None or trigger_time > latest_time:
                latest_time = trigger_time
        
        if latest_time:
            # 如果最晚的提醒时间距离现在少于30天，生成新实例
            days_ahead = (latest_time - now).days
            if days_ahead < 30:
                print(f"DEBUG: Series {series_id} (no UNTIL) needs new instances, latest is {days_ahead} days ahead")
                
                # 生成新实例，从最晚时间之后开始
                new_instances = generate_reminder_instances(base_reminder, 90, 10)
                
                # 过滤掉已经存在的实例
                existing_times = {r['trigger_time'] for r in series_reminders}
                truly_new_instances = []
                
                for instance in new_instances:
                    if instance['trigger_time'] not in existing_times:
                        truly_new_instances.append(instance)
                
                if truly_new_instances:
                    reminders.extend(truly_new_instances)
                    new_instances_count += len(truly_new_instances)
                    print(f"DEBUG: Added {len(truly_new_instances)} new instances for unlimited series {series_id}")
            else:
                print(f"DEBUG: Series {series_id} (no UNTIL) is good, latest is {days_ahead} days ahead")
    
    return new_instances_count


@csrf_exempt
def create_reminder(request):
    """创建新提醒 - 使用新的 RRule 引擎"""
    if request.method == 'POST':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        data = json.loads(request.body)
        title = data.get('title')
        content = data.get('content', '')
        trigger_time = data.get('trigger_time')
        priority = data.get('priority', 'medium')
        rrule = data.get('rrule', '')
        
        # 验证必填字段
        if not title or not trigger_time:
            return JsonResponse({'status': 'error', 'message': '标题和触发时间是必填项'}, status=400)
        
        # 准备提醒数据
        reminder_data = {
            "title": title,
            "content": content,
            "trigger_time": trigger_time,
            "priority": priority,
            "status": "active",
            "snooze_until": "",
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_modified": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            # 确保 reminders 是列表
            if not isinstance(reminders, list):
                reminders = []
            
            if rrule and 'FREQ=' in rrule:
                # 创建重复提醒
                print(f"DEBUG: Creating recurring reminder with rrule: {rrule}")
                reminder_mgr = get_reminder_manager(request)
                recurring_reminder = reminder_mgr.create_recurring_reminder(reminder_data, rrule)
                reminders.append(recurring_reminder)
                
                # 处理数据生成实例
                updated_reminders = reminder_mgr.process_reminder_data(reminders)
                user_reminders_data.set_value(updated_reminders)
                
                return JsonResponse({
                    'status': 'success', 
                    'message': f'重复提醒已创建，系列ID: {recurring_reminder["series_id"]}'
                })
            else:
                # 创建单个提醒
                reminder_data.update({
                    'id': str(uuid.uuid4()),
                    'series_id': None,
                    'rrule': '',
                    'is_recurring': False,
                    'is_main_reminder': False,
                    'is_detached': False
                })
                reminders.append(reminder_data)
                user_reminders_data.set_value(reminders)
                
                return JsonResponse({'status': 'success', 'message': '提醒已创建'})
                
        except Exception as e:
            print(f"ERROR in create_reminder: {e}")
            return JsonResponse({'status': 'error', 'message': f'创建提醒失败: {str(e)}'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def generate_reminder_instances(base_reminder, days_ahead=90, min_instances=10):
    """生成重复提醒的实例
    
    Args:
        base_reminder: 基础提醒数据
        days_ahead: 向前生成的天数（默认90天）
        min_instances: 最少生成的实例数量（默认10个）
    """
    instances = []
    if not base_reminder.get('rrule') or 'FREQ=' not in base_reminder.get('rrule', ''):
        return instances
    
    try:
        from datetime import datetime, timedelta
        import re
        
        rrule = base_reminder['rrule']
        start_time = datetime.fromisoformat(base_reminder['trigger_time'])
        
        # 解析UNTIL限制
        until_time = None
        if 'UNTIL=' in rrule:
            until_match = re.search(r'UNTIL=([^;]+)', rrule)
            if until_match:
                until_str = until_match.group(1)
                print(f"DEBUG: Parsing UNTIL string: '{until_str}' from rrule: '{rrule}'")
                try:
                    if until_str.endswith('Z'):
                        # UTC格式：20250830T000000Z
                        if 'T' in until_str and len(until_str) == 16:
                            # 格式：20250830T000000Z -> 2025-08-30T00:00:00
                            until_formatted = (until_str[:4] + '-' + until_str[4:6] + '-' + until_str[6:8] + 
                                             'T' + until_str[9:11] + ':' + until_str[11:13] + ':' + until_str[13:15])
                            until_time = datetime.fromisoformat(until_formatted)
                        else:
                            until_time = datetime.fromisoformat(until_str.replace('Z', ''))
                    elif 'T' in until_str and len(until_str) == 15:
                        # 本地时间格式（无Z后缀）：20250830T000000 -> 2025-08-30T00:00:00
                        until_formatted = (until_str[:4] + '-' + until_str[4:6] + '-' + until_str[6:8] + 
                                         'T' + until_str[9:11] + ':' + until_str[11:13] + ':' + until_str[13:15])
                        until_time = datetime.fromisoformat(until_formatted)
                        print(f"DEBUG: Formatted UNTIL string '{until_str}' -> '{until_formatted}' -> {until_time}")
                    else:
                        # 其他格式，直接解析
                        until_time = datetime.fromisoformat(until_str)
                    print(f"DEBUG: Parsed UNTIL time: {until_time}")
                except Exception as e:
                    print(f"DEBUG: Failed to parse UNTIL {until_str}: {e}")
        
        # 动态计算结束时间，确保生成足够的实例
        end_time = start_time + timedelta(days=days_ahead)
        
        # 如果有UNTIL限制，使用更早的时间
        if until_time:
            end_time = min(end_time, until_time)
            print(f"DEBUG: Using UNTIL limited end_time: {end_time}")
        
        # 对于较长周期的重复，扩展生成范围
        if 'FREQ=MONTHLY' in rrule:
            interval = 1
            if 'INTERVAL=' in rrule:
                interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                if interval_match:
                    interval = int(interval_match.group(1))
            
            # 对于月重复，确保至少覆盖min_instances个周期
            min_months = max(12, interval * min_instances)
            end_time = max(end_time, start_time + timedelta(days=min_months * 32))
        
        elif 'FREQ=YEARLY' in rrule:
            # 对于年重复，至少生成5年
            end_time = max(end_time, start_time + timedelta(days=365 * 5))
        
        # 简单的重复规则解析（支持DAILY, WEEKLY, MONTHLY）
        if 'FREQ=DAILY' in rrule:
            interval = 1
            if 'INTERVAL=' in rrule:
                interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                if interval_match:
                    interval = int(interval_match.group(1))
            
            current_time = start_time + timedelta(days=interval)
            while current_time <= end_time and len(instances) < max(min_instances * 3, 90):  # 确保生成足够实例
                instance = base_reminder.copy()
                instance['id'] = str(uuid.uuid4())
                instance['trigger_time'] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                instance['original_trigger_time'] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                instances.append(instance)
                current_time += timedelta(days=interval)
                
        elif 'FREQ=WEEKLY' in rrule:
            interval = 1
            if 'INTERVAL=' in rrule:
                interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                if interval_match:
                    interval = int(interval_match.group(1))
            
            # 处理BYDAY规则
            weekdays = []
            if 'BYDAY=' in rrule:
                byday_match = re.search(r'BYDAY=([A-Z,]+)', rrule)
                if byday_match:
                    weekday_str = byday_match.group(1)
                    weekday_mapping = {
                        'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 
                        'FR': 4, 'SA': 5, 'SU': 6
                    }
                    weekdays = [weekday_mapping[day] for day in weekday_str.split(',') if day in weekday_mapping]
            
            if weekdays:
                # 有指定星期几，按星期几重复
                current_date = start_time.date()
                count = 0
                while count < max(min_instances * 2, 50):  # 确保生成足够实例
                    current_date += timedelta(days=1)
                    if current_date.weekday() in weekdays:
                        # 检查是否符合间隔要求
                        week_diff = (current_date - start_time.date()).days // 7
                        if week_diff % interval == 0:
                            instance_time = datetime.combine(current_date, start_time.time())
                            if instance_time > end_time:
                                break
                            
                            instance = base_reminder.copy()
                            instance['id'] = str(uuid.uuid4())
                            instance['trigger_time'] = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                            instance['original_trigger_time'] = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                            instances.append(instance)
                            count += 1
            else:
                # 没有指定星期几，简单按周重复
                current_time = start_time + timedelta(weeks=interval)
                while current_time <= end_time and len(instances) < max(min_instances, 20):  # 确保生成足够实例
                    instance = base_reminder.copy()
                    instance['id'] = str(uuid.uuid4())
                    instance['trigger_time'] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                    instance['original_trigger_time'] = current_time.strftime("%Y-%m-%dT%H:%M:%S")
                    instances.append(instance)
                    current_time += timedelta(weeks=interval)
                
        elif 'FREQ=MONTHLY' in rrule:
            interval = 1
            if 'INTERVAL=' in rrule:
                interval_match = re.search(r'INTERVAL=(\d+)', rrule)
                if interval_match:
                    interval = int(interval_match.group(1))
            
            if 'BYMONTHDAY=' in rrule:
                # 按月的日期重复（如每月15日）
                monthday_match = re.search(r'BYMONTHDAY=(-?\d+)', rrule)
                if monthday_match:
                    monthday = int(monthday_match.group(1))
                    current_date = start_time.date()
                    max_months = max(min_instances, 24)  # 确保生成足够实例，最多24个月
                    for i in range(1, max_months + 1):
                        # 计算下一个月
                        if current_date.month + i * interval <= 12:
                            next_month = current_date.month + i * interval
                            next_year = current_date.year
                        else:
                            next_month = (current_date.month + i * interval - 1) % 12 + 1
                            next_year = current_date.year + (current_date.month + i * interval - 1) // 12
                        
                        try:
                            if monthday == -1:
                                # 月末
                                from calendar import monthrange
                                last_day = monthrange(next_year, next_month)[1]
                                next_date = datetime(next_year, next_month, last_day, start_time.hour, start_time.minute)
                            else:
                                next_date = datetime(next_year, next_month, monthday, start_time.hour, start_time.minute)
                            
                            if next_date > end_time:
                                break
                                
                            instance = base_reminder.copy()
                            instance['id'] = str(uuid.uuid4())
                            instance['trigger_time'] = next_date.strftime("%Y-%m-%dT%H:%M:%S")
                            instance['original_trigger_time'] = next_date.strftime("%Y-%m-%dT%H:%M:%S")
                            instances.append(instance)
                        except ValueError:
                            # 处理无效日期（如2月30日）
                            continue
                            
            elif 'BYDAY=' in rrule:
                # 按月的星期重复（如每月第2个星期一）
                byday_match = re.search(r'BYDAY=(-?\d+)([A-Z]{2})', rrule)
                if byday_match:
                    week_num = int(byday_match.group(1))
                    weekday_str = byday_match.group(2)
                    weekday_mapping = {
                        'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 
                        'FR': 4, 'SA': 5, 'SU': 6
                    }
                    target_weekday = weekday_mapping.get(weekday_str)
                    
                    if target_weekday is not None:
                        current_date = start_time.date()
                        max_months = max(min_instances, 24)  # 确保生成足够实例，最多24个月
                        for i in range(1, max_months + 1):
                            # 计算下一个月
                            if current_date.month + i * interval <= 12:
                                next_month = current_date.month + i * interval
                                next_year = current_date.year
                            else:
                                next_month = (current_date.month + i * interval - 1) % 12 + 1
                                next_year = current_date.year + (current_date.month + i * interval - 1) // 12
                            
                            # 找到该月的第N个星期X
                            first_day = datetime(next_year, next_month, 1)
                            first_weekday = first_day.weekday()
                            
                            if week_num > 0:
                                # 正数：第N个星期X
                                days_to_add = (target_weekday - first_weekday) % 7 + (week_num - 1) * 7
                                target_date = first_day + timedelta(days=days_to_add)
                            else:
                                # 负数：倒数第N个星期X
                                from calendar import monthrange
                                last_day = monthrange(next_year, next_month)[1]
                                last_date = datetime(next_year, next_month, last_day)
                                last_weekday = last_date.weekday()
                                days_to_subtract = (last_weekday - target_weekday) % 7 + (abs(week_num) - 1) * 7
                                target_date = last_date - timedelta(days=days_to_subtract)
                            
                            # 检查日期是否在当月
                            if target_date.month == next_month:
                                instance_time = datetime.combine(target_date.date(), start_time.time())
                                if instance_time > end_time:
                                    break
                                    
                                instance = base_reminder.copy()
                                instance['id'] = str(uuid.uuid4())
                                instance['trigger_time'] = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                                instance['original_trigger_time'] = instance_time.strftime("%Y-%m-%dT%H:%M:%S")
                                instances.append(instance)
            else:
                # 简单的每隔x个月重复
                current_date = start_time.date()
                max_months = max(min_instances, 24)  # 确保生成足够实例，最多24个月
                for i in range(1, max_months + 1):
                    # 计算下一个月
                    if current_date.month + i * interval <= 12:
                        next_month = current_date.month + i * interval
                        next_year = current_date.year
                    else:
                        next_month = (current_date.month + i * interval - 1) % 12 + 1
                        next_year = current_date.year + (current_date.month + i * interval - 1) // 12
                    
                    try:
                        next_date = datetime(next_year, next_month, current_date.day, start_time.hour, start_time.minute)
                        if next_date > end_time:
                            break
                            
                        instance = base_reminder.copy()
                        instance['id'] = str(uuid.uuid4())
                        instance['trigger_time'] = next_date.strftime("%Y-%m-%dT%H:%M:%S")
                        instance['original_trigger_time'] = next_date.strftime("%Y-%m-%dT%H:%M:%S")
                        instances.append(instance)
                        
                        # 如果已经生成了足够的实例，可以退出
                        if len(instances) >= min_instances:
                            break
                    except ValueError:
                        # 处理无效日期（如月底日期）
                        continue
                
        # 可以添加更多重复规则支持
        
    except Exception as e:
        print(f"Error generating reminder instances: {e}")
    
    return instances


@csrf_exempt
def update_reminder(request):
    """更新提醒 - 使用新的RRule引擎"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            reminder_id = data.get('id')
            
            if not reminder_id:
                return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
            
            # 检查是否包含重复规则变化
            rrule_change_scope = data.get('rrule_change_scope')
            create_new_series = data.get('create_new_series', False)
            
            if rrule_change_scope or create_new_series:
                # 使用批量编辑功能处理重复规则变化
                
                # 映射前端scope到后端scope
                scope_mapping = {
                    'this_only': 'single',
                    'from_this': 'future', 
                    'all': 'all'
                }
                
                edit_scope = scope_mapping.get(rrule_change_scope, 'single')
                
                # 获取用户数据
                user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
                
                # 初始化集成管理器
                manager = IntegratedReminderManager(request)
                
                # 获取提醒列表
                reminders = user_reminders_data.get_value()
                
                # 查找目标提醒
                target_reminder = None
                for reminder in reminders:
                    if reminder['id'] == reminder_id:
                        target_reminder = reminder
                        break
                
                if not target_reminder:
                    return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
                
                # 根据编辑范围执行不同操作
                if edit_scope == 'single':
                    # 仅此提醒：直接更新当前提醒
                    if 'title' in data:
                        target_reminder['title'] = data['title']
                    if 'content' in data:
                        target_reminder['content'] = data['content']
                    if 'trigger_time' in data:
                        target_reminder['trigger_time'] = data['trigger_time']
                    if 'priority' in data:
                        target_reminder['priority'] = data['priority']
                    if 'rrule' in data:
                        target_reminder['rrule'] = data['rrule']
                    
                    target_reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 如果有系列ID，标记为分离
                    if target_reminder.get('series_id'):
                        target_reminder['is_detached'] = True
                        target_reminder['detach_reason'] = 'edited_single'
                    
                elif edit_scope in ['future', 'all']:
                    # 未来提醒或所有提醒：使用修改重复规则方法
                    series_id = target_reminder.get('series_id')
                    if series_id and data.get('rrule'):
                        try:
                            from_date = datetime.datetime.fromisoformat(target_reminder['trigger_time'])
                            new_rrule = data.get('rrule')
                            
                            # 应用更新到目标提醒
                            if 'title' in data:
                                target_reminder['title'] = data['title']
                            if 'content' in data:
                                target_reminder['content'] = data['content']
                            if 'trigger_time' in data:
                                target_reminder['trigger_time'] = data['trigger_time']
                                from_date = datetime.datetime.fromisoformat(data['trigger_time'])
                            if 'priority' in data:
                                target_reminder['priority'] = data['priority']
                            
                            # 调用修改重复规则方法
                            updated_reminders = manager.modify_recurring_rule(
                                reminders, series_id, from_date, new_rrule, edit_scope
                            )
                            
                            user_reminders_data.set_value(updated_reminders)
                            return JsonResponse({'status': 'success'})
                            
                        except Exception as e:
                            logger.error(f"Error modifying recurring rule: {e}")
                            return JsonResponse({'status': 'error', 'message': f'修改重复规则时出错: {str(e)}'}, status=500)
                    else:
                        # 没有系列ID或rrule，按单个提醒处理
                        if 'title' in data:
                            target_reminder['title'] = data['title']
                        if 'content' in data:
                            target_reminder['content'] = data['content']
                        if 'trigger_time' in data:
                            target_reminder['trigger_time'] = data['trigger_time']
                        if 'priority' in data:
                            target_reminder['priority'] = data['priority']
                        if 'rrule' in data:
                            target_reminder['rrule'] = data['rrule']
                        
                        target_reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                user_reminders_data.set_value(reminders)
                return JsonResponse({'status': 'success'})
            
            else:
                # 简单更新，直接修改提醒数据
                user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
                reminders = user_reminders_data.get_value()
                
                for reminder in reminders:
                    if reminder['id'] == reminder_id:
                        # 更新字段
                        if 'title' in data:
                            reminder['title'] = data['title']
                        if 'content' in data:
                            reminder['content'] = data['content']
                        if 'trigger_time' in data:
                            reminder['trigger_time'] = data['trigger_time']
                        if 'priority' in data:
                            reminder['priority'] = data['priority']
                        if 'status' in data:
                            reminder['status'] = data['status']
                        
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        user_reminders_data.set_value(reminders)
                        return JsonResponse({'status': 'success'})
                
                return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
                
        except Exception as e:
            logger.error(f"Error updating reminder: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


def analyze_rrule_change(original_rrule, new_rrule):
    """分析重复规则变化类型"""
    if original_rrule == new_rrule:
        return 'no_change'
    elif not original_rrule and new_rrule:
        return 'single_to_recurring'
    elif original_rrule and not new_rrule:
        return 'recurring_to_single'
    elif original_rrule and new_rrule and original_rrule != new_rrule:
        return 'recurring_rule_change'
    else:
        return 'no_change'


def simple_update_reminder(reminder, data):
    """简单更新提醒，不涉及重复规则变化"""
    reminder['title'] = data.get('title', reminder['title'])
    reminder['content'] = data.get('content', reminder['content'])
    reminder['trigger_time'] = data.get('trigger_time', reminder['trigger_time'])
    reminder['priority'] = data.get('priority', reminder['priority'])
    reminder['status'] = data.get('status', reminder['status'])
    reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def handle_single_to_recurring(reminder, data, reminders):
    """处理单个提醒变为重复提醒"""
    # 更新当前提醒
    simple_update_reminder(reminder, data)
    reminder['rrule'] = data.get('rrule')
    
    # 生成series_id
    if not reminder.get('series_id'):
        reminder['series_id'] = str(uuid.uuid4())
    
    # 生成重复实例
    new_rrule = data.get('rrule')
    if new_rrule and HAS_DATEUTIL:
        try:
            # 解析触发时间，确保是naive时间（无时区信息）
            trigger_time_str = reminder['trigger_time']
            if trigger_time_str:
                if trigger_time_str.endswith('Z'):
                    start_time = parse(trigger_time_str)
                    if start_time.tzinfo is not None:
                        start_time = start_time.replace(tzinfo=None)
                else:
                    # 直接使用datetime.fromisoformat避免自动添加时区
                    try:
                        start_time = datetime.datetime.fromisoformat(trigger_time_str)
                    except:
                        start_time = parse(trigger_time_str)
                        if start_time.tzinfo is not None:
                            start_time = start_time.replace(tzinfo=None)
                
                # 处理RRULE - 确保UNTIL时间格式与start_time一致（都是naive时间）
                processed_rrule = new_rrule
                if 'UNTIL=' in new_rrule:
                    import re
                    until_match = re.search(r'UNTIL=([^;]+)', new_rrule)
                    if until_match:
                        until_str = until_match.group(1)
                        if until_str.endswith('Z'):
                            try:
                                # 移除Z后缀，保持naive时间格式
                                until_naive = until_str.rstrip('Z')
                                processed_rrule = new_rrule.replace(until_str, until_naive)
                            except:
                                # 如果解析失败，保持原样
                                pass
                
                # 检查第一个实例是否符合重复规则
                should_include_first = True
                try:
                    rrule = rrulestr(processed_rrule, dtstart=start_time)
                    # 检查开始时间是否在重复规则中
                    next_occurrence = rrule.after(start_time - datetime.timedelta(seconds=1))
                    if next_occurrence and next_occurrence.replace(second=0, microsecond=0) != start_time.replace(second=0, microsecond=0):
                        should_include_first = False
                        print(f"Initial time {start_time} doesn't match the recurrence rule, will skip it")
                except Exception as e:
                    print(f"Error checking initial time match: {e}")
                
                # 如果初始时间不符合重复规则，更新为第一个符合的时间
                if not should_include_first:
                    try:
                        rrule = rrulestr(processed_rrule, dtstart=start_time)
                        first_occurrence = rrule.after(start_time - datetime.timedelta(seconds=1))
                        if first_occurrence:
                            reminder['trigger_time'] = first_occurrence.strftime('%Y-%m-%dT%H:%M')
                            reminder['original_trigger_time'] = first_occurrence.strftime('%Y-%m-%dT%H:%M:%S')
                            start_time = first_occurrence
                    except Exception as e:
                        print(f"Error adjusting initial time: {e}")
                
                # 生成重复实例
                try:
                    rrule = rrulestr(processed_rrule, dtstart=start_time)
                    end_date = start_time + datetime.timedelta(days=180)
                    instances = list(rrule.between(start_time + datetime.timedelta(seconds=1), end_date, inc=True))
                    
                    # 为每个实例创建提醒
                    for instance_time in instances:
                        new_reminder = {
                            'id': str(uuid.uuid4()),
                            'series_id': reminder['series_id'],
                            'title': reminder['title'],
                            'content': reminder['content'],
                            'trigger_time': instance_time.strftime('%Y-%m-%dT%H:%M'),
                            'original_trigger_time': instance_time.strftime('%Y-%m-%dT%H:%M:%S'),
                            'priority': reminder['priority'],
                            'rrule': new_rrule,
                            'original_rrule': new_rrule,
                            'status': 'active',
                            'is_detached': False,
                            'detach_reason': '',
                            'snooze_until': '',
                            'series_metadata': {
                                'title': reminder['title'],
                                'content': reminder['content'],
                                'priority': reminder['priority']
                            },
                            'created_at': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            'last_modified': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        reminders.append(new_reminder)
                        
                    print(f"Generated {len(instances)} recurring instances for converted reminder")
                    
                except Exception as e:
                    print(f"Error generating recurring instances: {e}")
                    
        except Exception as e:
            print(f"Error parsing trigger time for recurring conversion: {e}")
    
    # 确保原提醒有完整的字段
    if not reminder.get('original_trigger_time'):
        reminder['original_trigger_time'] = reminder['trigger_time'] + ':00' if len(reminder['trigger_time']) == 16 else reminder['trigger_time']
    if not reminder.get('series_metadata'):
        reminder['series_metadata'] = {
            'title': reminder['title'],
            'content': reminder['content'],
            'priority': reminder['priority']
        }


def handle_recurring_to_single(reminder, data):
    """处理重复提醒变为单个提醒"""
    # 分离当前提醒
    reminder['is_detached'] = True
    reminder['detach_reason'] = 'converted_to_single'
    reminder['rrule'] = None  # 清空重复规则
    
    # 更新其他字段
    simple_update_reminder(reminder, data)


def handle_recurring_rule_change(reminder, data, reminders, scope, reminder_id):
    """处理重复规则改变"""
    if scope == 'this_only':
        # 仅影响当前提醒：分离当前提醒
        reminder['is_detached'] = True
        reminder['detach_reason'] = 'rule_change_this_only'
        simple_update_reminder(reminder, data)
        reminder['rrule'] = data.get('rrule')
        
    elif scope == 'all':
        # 影响整个系列：更新所有相同series_id的提醒
        series_id = reminder.get('series_id')
        if series_id:
            for r in reminders:
                if r.get('series_id') == series_id and not r.get('is_detached'):
                    # 保持时间相对关系，只更新重复规则和其他字段
                    r['rrule'] = data.get('rrule')
                    if 'title' in data:
                        r['title'] = data['title']
                    if 'content' in data:
                        r['content'] = data['content']
                    if 'priority' in data:
                        r['priority'] = data['priority']
                    r['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
    elif scope in ['from_this', 'from_time']:
        # 从当前或指定时间开始影响
        series_id = reminder.get('series_id')
        cutoff_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
        
        if series_id:
            for r in reminders:
                if (r.get('series_id') == series_id and 
                    not r.get('is_detached') and
                    datetime.datetime.fromisoformat(r['trigger_time']) >= cutoff_time):
                    
                    r['rrule'] = data.get('rrule')
                    if 'title' in data:
                        r['title'] = data['title']
                    if 'content' in data:
                        r['content'] = data['content']
                    if 'priority' in data:
                        r['priority'] = data['priority']
                    r['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@csrf_exempt
def update_reminder_status(request):
    """更新提醒状态（完成/忽略/延后/激活）"""
    if request.method == 'POST':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        data = json.loads(request.body)
        reminder_id = data.get('id')
        new_status = data.get('status')  # active/completed/dismissed/snoozed_15m/snoozed_1h/snoozed_1d
        snooze_until = data.get('snooze_until', '')
        
        if not reminder_id or not new_status:
            return JsonResponse({'status': 'error', 'message': '提醒ID和状态是必填项'}, status=400)
        
        # 查找要更新的提醒
        reminder_found = False
        for reminder in reminders:
            if reminder['id'] == reminder_id:
                reminder['status'] = new_status
                reminder['snooze_until'] = snooze_until
                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # 如果是取消延后或激活，清空延后时间
                if new_status == 'active':
                    reminder['snooze_until'] = ''
                
                reminder_found = True
                break
        
        if not reminder_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def bulk_edit_reminders(request):
    """批量编辑重复提醒"""
    if request.method == 'POST':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        
        if user_reminders_data is None:
            return JsonResponse({'status': 'error', 'message': result.get('message', '获取用户数据失败')}, status=400)
        
        try:
            reminders = user_reminders_data.get_value()
            if not isinstance(reminders, list):
                reminders = []
        except:
            reminders = []
        
        data = json.loads(request.body)
        logger.debug(f"{data=}")

        reminder_id = data.get('reminder_id')
        operation = data.get('operation', 'edit')  # edit, delete
        edit_scope = data.get('edit_scope', 'single')  # single, all, future, from_time
        from_time = data.get('from_time')  # 当 edit_scope 为 from_time 时必需
        series_id = data.get('series_id')
        
        # 调整scope映射
        scope_mapping = {
            'this_only': 'single',
            'all': 'all', 
            'from_this': 'future',
            'from_time': 'from_time'
        }
        edit_scope = scope_mapping.get(edit_scope, edit_scope)
        
        # 获取更新数据
        updates = {
            'title': data.get('title'),
            'content': data.get('content'),  # 前端发送的是content，不是description
            'description': data.get('description'),  # 保留兼容性
            'priority': data.get('priority'),  # 添加missing的priority字段
            'importance': data.get('importance'),
            'urgency': data.get('urgency'),
            'trigger_time': data.get('trigger_time'),
            'rrule': data.get('rrule'),
            'reminder_mode': data.get('reminder_mode'),
        }
        # 过滤掉None值
        updates = {k: v for k, v in updates.items() if v is not None}
        
        logger.info(f"Received updates: {updates}")
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        if edit_scope == 'from_time' and not from_time:
            return JsonResponse({'status': 'error', 'message': '当编辑范围为"从指定时间"时，必须提供起始时间'}, status=400)
        
        # 使用新的引擎处理
        try:
            if operation == 'delete':
                if edit_scope == 'single':
                    # 删除单个实例
                    reminder_mgr = get_reminder_manager(request)
                    updated_reminders = reminder_mgr.delete_reminder_instance(
                        reminders, reminder_id, series_id or ''
                    )
                    # 处理重复提醒数据以防止自动补回
                    final_reminders = reminder_mgr.process_reminder_data(updated_reminders)
                    user_reminders_data.set_value(final_reminders)
                    return JsonResponse({'status': 'success'})
                    
                elif edit_scope in ['all', 'future', 'from_time']:
                    # 删除整个系列或从某时间开始删除
                    reminder_mgr = get_reminder_manager(request)
                    
                    if edit_scope == 'all':
                        # 删除整个系列
                        updated_reminders = []
                        for reminder in reminders:
                            if reminder.get('series_id') != series_id:
                                updated_reminders.append(reminder)
                        
                        # 完全删除系列
                        if series_id:
                            reminder_mgr.rrule_engine.delete_series(series_id)
                            logger.info(f"Completely deleted series {series_id}")
                        
                        # 处理重复提醒数据以防止自动补回
                        final_reminders = reminder_mgr.process_reminder_data(updated_reminders)
                        user_reminders_data.set_value(final_reminders)
                        return JsonResponse({'status': 'success'})
                        
                    elif edit_scope in ['future', 'from_time']:
                        # 删除此及之后（使用截断方法）
                        if edit_scope == 'from_time' and from_time:
                            # 如果指定了from_time，找到对应的提醒
                            target_reminder_id = None
                            target_time = datetime.datetime.fromisoformat(from_time)
                            for reminder in reminders:
                                if (reminder.get('series_id') == series_id and 
                                    reminder.get('trigger_time')):
                                    try:
                                        reminder_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                                        if abs((reminder_time - target_time).total_seconds()) < 60:  # 允许1分钟误差
                                            target_reminder_id = reminder['id']
                                            break
                                    except:
                                        continue
                            
                            if not target_reminder_id:
                                return JsonResponse({'status': 'error', 'message': '找不到指定时间的提醒'}, status=400)
                                
                            reminder_id = target_reminder_id
                        
                        # 使用新的截断方法，它会同时更新RRule引擎和提醒数据
                        logger.info(f"使用新的截断方法，它会同时更新RRule引擎和提醒数据")
                        updated_reminders = reminder_mgr.delete_reminder_this_and_after(
                            reminders, reminder_id, series_id or ''
                        )
                        
                        # 处理重复提醒数据以防止自动补回
                        final_reminders = reminder_mgr.process_reminder_data(updated_reminders)
                        user_reminders_data.set_value(final_reminders)
                        return JsonResponse({'status': 'success'})
                    
            elif operation == 'edit':
                if edit_scope == 'single':
                    # 编辑单个提醒
                    for reminder in reminders:
                        if reminder['id'] == reminder_id:
                            reminder.update(updates)
                            reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            break
                    user_reminders_data.set_value(reminders)
                    return JsonResponse({'status': 'success'})
                    
                elif edit_scope in ['all', 'future', 'from_time']:
                    # 批量编辑 - 使用新的modify_recurring_rule方法
                    reminder_mgr = get_reminder_manager(request)
                    
                    # 确定修改的起始时间
                    cutoff_time = None
                    if from_time:
                        try:
                            cutoff_time = datetime.datetime.fromisoformat(from_time)
                        except:
                            cutoff_time = datetime.datetime.now()
                    elif edit_scope == 'future':
                        current_reminder = next((r for r in reminders if r.get('id') == reminder_id), None)
                        if current_reminder:
                            try:
                                cutoff_time = datetime.datetime.fromisoformat(current_reminder.get('trigger_time', ''))
                            except:
                                cutoff_time = datetime.datetime.now()
                        else:
                            cutoff_time = datetime.datetime.now()
                    
                    if edit_scope == 'all':
                        # 修改整个系列 - 简单更新所有相关提醒
                        updated_count = 0
                        for reminder in reminders:
                            if reminder.get('series_id') == series_id or reminder.get('id') == reminder_id:
                                # 只更新非时间字段，保持原有的trigger_time
                                update_data = {k: v for k, v in updates.items() if k not in ['trigger_time']}
                                reminder.update(update_data)
                                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                updated_count += 1
                        
                        user_reminders_data.set_value(reminders)
                        return JsonResponse({'status': 'success', 'updated_count': updated_count})
                        
                    elif edit_scope in ['future', 'from_time']:
                        # 从指定时间开始修改
                        if cutoff_time is None:
                            return JsonResponse({'status': 'error', 'message': '无法确定修改的起始时间'}, status=400)
                        
                        if 'rrule' in updates:
                            # 检查RRule是否真的发生了变化
                            new_rrule = updates.get('rrule')
                            if not new_rrule:
                                return JsonResponse({'status': 'error', 'message': 'RRule是必填项'}, status=400)
                            
                            # 找到当前序列的原始RRule进行比较
                            original_rrule = None
                            for reminder in reminders:
                                if (reminder.get('series_id') == series_id and 
                                    reminder.get('rrule')):
                                    original_rrule = reminder.get('rrule')
                                    break
                            
                            # 如果RRule没有变化，按非RRule修改处理
                            if original_rrule and original_rrule == new_rrule:
                                logger.info(f"RRule unchanged for series {series_id}, treating as non-RRule modification")
                                logger.info(f"Original updates dict before filtering: {updates}")
                                
                                updated_count = 0
                                for reminder in reminders:
                                    if (reminder.get('series_id') == series_id and 
                                        reminder.get('trigger_time')):
                                        try:
                                            trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                                            if trigger_time >= cutoff_time:
                                                # 对于非RRule修改，允许更新trigger_time，但不允许修改rrule
                                                update_data = {k: v for k, v in updates.items() if k not in ['rrule']}
                                                logger.info(f"After filtering out rrule: {update_data}")
                                                logger.info(f"Updating reminder {reminder.get('id', 'unknown')} with data: {update_data}")
                                                reminder.update(update_data)
                                                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                                updated_count += 1
                                        except:
                                            pass
                                
                                user_reminders_data.set_value(reminders)
                                return JsonResponse({'status': 'success', 'updated_count': updated_count})
                            
                            # RRule确实发生了变化 - 需要创建新序列
                            logger.info(f"Modifying recurring rule from {cutoff_time} for series {series_id}")
                            
                            # 检查是否有新的trigger_time，如果有，使用它作为新系列的起始时间
                            new_start_time = cutoff_time
                            if 'trigger_time' in updates:
                                try:
                                    requested_time = datetime.datetime.fromisoformat(updates['trigger_time'])
                                    # 使用用户指定的新时间作为起始时间
                                    new_start_time = requested_time
                                    logger.info(f"Using requested trigger_time {requested_time} as new series start time")
                                except:
                                    logger.warning(f"Invalid trigger_time format: {updates.get('trigger_time')}, using cutoff_time")
                            
                            # 调用modify_recurring_rule方法，传递额外的更新参数和新的起始时间
                            # 如果用户提供了新的trigger_time，将其包含在additional_updates中
                            other_updates = {k: v for k, v in updates.items() if k not in ['rrule']}
                            updated_reminders = reminder_mgr.modify_recurring_rule(
                                reminders, series_id, new_start_time, new_rrule, 
                                scope='from_this', additional_updates=other_updates
                            )
                            
                            # 处理重复提醒数据以确保实例足够
                            final_reminders = reminder_mgr.process_reminder_data(updated_reminders)
                            user_reminders_data.set_value(final_reminders)
                            
                            logger.info(f"Successfully modified recurring rule for series {series_id}")
                            return JsonResponse({'status': 'success'})
                        
                        else:
                            # 只修改其他字段，不涉及RRule - 直接更新
                            logger.info(f"Modifying non-RRule fields from {cutoff_time} for series {series_id}")
                            
                            updated_count = 0
                            for reminder in reminders:
                                if (reminder.get('series_id') == series_id and 
                                    reminder.get('trigger_time')):
                                    try:
                                        trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                                        if trigger_time >= cutoff_time:
                                            # 对于非RRule修改，允许更新所有字段包括trigger_time
                                            update_data = updates.copy()
                                            reminder.update(update_data)
                                            reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            updated_count += 1
                                    except:
                                        pass
                            
                            user_reminders_data.set_value(reminders)
                            return JsonResponse({'status': 'success', 'updated_count': updated_count})
                        
                    else:
                        # 其他情况的批量编辑（不涉及RRule修改）
                        updated_count = 0
                        for reminder in reminders:
                            should_update = False
                            if reminder.get('series_id') == series_id or reminder.get('id') == reminder_id:
                                if edit_scope == 'all':
                                    should_update = True
                                elif cutoff_time and reminder.get('trigger_time'):
                                    try:
                                        trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'])
                                        if trigger_time >= cutoff_time:
                                            should_update = True
                                    except:
                                        pass
                            
                            if should_update:
                                # 只更新非时间字段，保持原有的trigger_time
                                update_data = {k: v for k, v in updates.items() if k not in ['trigger_time']}
                                reminder.update(update_data)
                                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                updated_count += 1
                        
                        user_reminders_data.set_value(reminders)
                        return JsonResponse({'status': 'success', 'updated_count': updated_count})
            
            return JsonResponse({'status': 'error', 'message': '无效的操作或范围'}, status=400)
                
        except Exception as e:
            logger.error(f"批量编辑提醒失败: {str(e)}")
            return JsonResponse({'status': 'error', 'message': f'操作失败: {str(e)}'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def maintain_reminders(request):
    """维护提醒实例 - 定期调用以确保重复提醒的实例足够"""
    if request.method == 'POST':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        # 确保 reminders 是列表
        if not isinstance(reminders, list):
            reminders = []
        
        try:
            # 使用新引擎处理提醒数据
            reminder_mgr = get_reminder_manager(request)
            updated_reminders = reminder_mgr.process_reminder_data(reminders)
            
            # 保存更新后的数据
            user_reminders_data.set_value(updated_reminders)
            
            added_count = len(updated_reminders) - len(reminders)
            
            return JsonResponse({
                'status': 'success',
                'original_count': len(reminders),
                'updated_count': len(updated_reminders),
                'added_instances': added_count
            })
            
        except Exception as e:
            logger.error(f"维护提醒失败: {str(e)}")
            return JsonResponse({'status': 'error', 'message': f'维护失败: {str(e)}'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def delete_reminder(request):
    """删除提醒"""
    if request.method == 'POST':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        data = json.loads(request.body)
        reminder_id = data.get('id')
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        # 查找并删除提醒
        original_length = len(reminders)
        reminders[:] = [reminder for reminder in reminders if reminder['id'] != reminder_id]
        
        if len(reminders) == original_length:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def snooze_reminder(request):
    """延迟提醒"""
    if request.method == 'POST':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        data = json.loads(request.body)
        reminder_id = data.get('id')
        snooze_minutes = data.get('snooze_minutes', 10)  # 默认延迟10分钟
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        # 查找要延迟的提醒
        reminder_found = False
        for reminder in reminders:
            if reminder['id'] == reminder_id:
                # 计算新的触发时间
                current_trigger = datetime.datetime.fromisoformat(reminder['trigger_time'].replace('Z', '+00:00'))
                new_trigger = current_trigger + timedelta(minutes=snooze_minutes)
                reminder['trigger_time'] = new_trigger.strftime("%Y-%m-%dT%H:%M:%S")
                reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                reminder_found = True
                break
        
        if not reminder_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def dismiss_reminder(request):
    """忽略/关闭提醒"""
    if request.method == 'POST':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        data = json.loads(request.body)
        reminder_id = data.get('id')
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        # 查找要忽略的提醒
        reminder_found = False
        for reminder in reminders:
            if reminder['id'] == reminder_id:
                # 检查是否有重复规则（简单检查是否包含FREQ）
                if reminder.get('rrule') and 'FREQ=' in reminder.get('rrule', ''):
                    # 有重复规则，简单地加一天作为下一次提醒
                    try:
                        current_trigger = datetime.datetime.fromisoformat(reminder['trigger_time'])
                        next_trigger = current_trigger + timedelta(days=1)
                        reminder['trigger_time'] = next_trigger.strftime("%Y-%m-%dT%H:%M:%S")
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        # 解析失败，直接标记为已忽略
                        reminder['status'] = 'dismissed'
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # 没有重复规则，直接标记为已忽略
                    reminder['status'] = 'dismissed'
                    reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                reminder_found = True
                break
        
        if not reminder_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def complete_reminder(request):
    """完成提醒"""
    if request.method == 'POST':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        data = json.loads(request.body)
        reminder_id = data.get('id')
        
        if not reminder_id:
            return JsonResponse({'status': 'error', 'message': '提醒ID是必填项'}, status=400)
        
        # 查找要完成的提醒
        reminder_found = False
        for reminder in reminders:
            if reminder['id'] == reminder_id:
                # 检查是否有重复规则（简单检查是否包含FREQ）
                if reminder.get('rrule') and 'FREQ=' in reminder.get('rrule', ''):
                    # 有重复规则，简单地加一天作为下一次提醒
                    try:
                        current_trigger = datetime.datetime.fromisoformat(reminder['trigger_time'])
                        next_trigger = current_trigger + timedelta(days=1)
                        reminder['trigger_time'] = next_trigger.strftime("%Y-%m-%dT%H:%M:%S")
                        reminder['status'] = 'active'  # 保持活跃状态
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        # 解析失败，直接标记为已完成
                        reminder['status'] = 'completed'
                        reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # 没有重复规则，直接标记为已完成
                    reminder['status'] = 'completed'
                    reminder['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                reminder_found = True
                break
        
        if not reminder_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的提醒'}, status=404)
        
        user_reminders_data.set_value(reminders)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def get_pending_reminders(request):
    """获取待触发的提醒（用于通知检查）"""
    if request.method == 'GET':
        user_reminders_data, created, result = UserData.get_or_initialize(request, new_key="reminders")
        reminders = user_reminders_data.get_value()
        
        current_time = datetime.datetime.now()
        pending_reminders = []
        
        for reminder in reminders:
            if reminder['status'] != 'active':
                continue
                
            trigger_time = datetime.datetime.fromisoformat(reminder['trigger_time'].replace('Z', '+00:00'))
            
            # 检查是否应该触发（允许1分钟的误差）
            if trigger_time <= current_time + timedelta(minutes=1):
                pending_reminders.append(reminder)
        
        return JsonResponse({'pending_reminders': pending_reminders})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


# ========== Todo 相关 API ==========

@csrf_exempt
def get_todos(request):
    """获取所有待办事项"""
    if request.method == 'GET':
        user_todos_data, created, result = UserData.get_or_initialize(request, new_key="todos")
        todos = user_todos_data.get_value()
        
        return JsonResponse({'todos': todos})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def create_todo(request):
    """创建新待办事项"""
    if request.method == 'POST':
        user_todos_data, created, result = UserData.get_or_initialize(request, new_key="todos")
        todos = user_todos_data.get_value()
        
        data = json.loads(request.body)
        title = data.get('title')
        description = data.get('description', '')
        due_date = data.get('due_date', '')
        estimated_duration = data.get('estimated_duration', 0)
        importance = data.get('importance', 'medium')
        urgency = data.get('urgency', 'normal')
        group_id = data.get('groupID', '')
        
        # 验证必填字段
        if not title:
            return JsonResponse({'status': 'error', 'message': '标题是必填项'}, status=400)
        
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


@csrf_exempt
def update_todo(request):
    """更新待办事项"""
    if request.method == 'POST':
        user_todos_data, created, result = UserData.get_or_initialize(request, new_key="todos")
        todos = user_todos_data.get_value()
        
        data = json.loads(request.body)
        todo_id = data.get('id')
        
        if not todo_id:
            return JsonResponse({'status': 'error', 'message': '待办事项ID是必填项'}, status=400)
        
        # 查找要更新的待办事项
        todo_found = False
        for todo in todos:
            if todo['id'] == todo_id:
                # 更新字段
                todo['title'] = data.get('title', todo['title'])
                todo['description'] = data.get('description', todo['description'])
                todo['due_date'] = data.get('due_date', todo['due_date'])
                todo['estimated_duration'] = data.get('estimated_duration', todo['estimated_duration'])
                todo['importance'] = data.get('importance', todo['importance'])
                todo['urgency'] = data.get('urgency', todo['urgency'])
                todo['groupID'] = data.get('groupID', todo['groupID'])
                todo['status'] = data.get('status', todo['status'])
                todo['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                todo_found = True
                break
        
        if not todo_found:
            return JsonResponse({'status': 'error', 'message': '未找到指定的待办事项'}, status=404)
        
        user_todos_data.set_value(todos)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def delete_todo(request):
    """删除待办事项"""
    if request.method == 'POST':
        user_todos_data, created, result = UserData.get_or_initialize(request, new_key="todos")
        todos = user_todos_data.get_value()
        
        data = json.loads(request.body)
        todo_id = data.get('id')
        
        if not todo_id:
            return JsonResponse({'status': 'error', 'message': '待办事项ID是必填项'}, status=400)
        
        # 查找并删除待办事项
        original_length = len(todos)
        todos[:] = [todo for todo in todos if todo['id'] != todo_id]
        
        if len(todos) == original_length:
            return JsonResponse({'status': 'error', 'message': '未找到指定的待办事项'}, status=404)
        
        user_todos_data.set_value(todos)
        
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@csrf_exempt
def convert_todo_to_event(request):
    """将待办事项转换为日程事件"""
    if request.method == 'POST':
        user_todos_data, created, result = UserData.get_or_initialize(request, new_key="todos")
        todos = user_todos_data.get_value()
        
        user_events_data, created, result = UserData.get_or_initialize(request, new_key="events")
        events = user_events_data.get_value()
        
        data = json.loads(request.body)
        todo_id = data.get('id')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        
        if not todo_id or not start_time or not end_time:
            return JsonResponse({'status': 'error', 'message': '待办事项ID和时间是必填项'}, status=400)
        
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


