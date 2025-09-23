
# Create your views here.
import datetime
from typing import List
import uuid
import markdown
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

from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import logout
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from .forms import RegisterForm
from .models import UserData

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

# 导入 events 相关视图函数  
from .views_events import (
    get_events_impl,
    create_event_impl,
    delete_event_impl,
    update_events_impl
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
    """获取events数据 - 委托给views_events中的实现"""
    return get_events_impl(request)




@login_required
@csrf_exempt
def update_events(request):
    """更新事件 - 委托给views_events中的实现"""
    return update_events_impl(request)



@login_required
@csrf_exempt
def create_event(request):
    """创建新事件 - 委托给views_events中的实现"""
    return create_event_impl(request)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


@csrf_exempt
@login_required
def delete_event(request):
    """删除事件 - 委托给views_events中的实现"""
    return delete_event_impl(request)

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

def get_reminders(request):
    """获取所有提醒 - 重定向到新的模块"""
    return get_reminders_impl(request)

def create_reminder(request):
    """创建新提醒 - 重定向到新的模块"""
    return create_reminder_impl(request)

def update_reminder(request):
    """更新提醒 - 重定向到新的模块"""
    return update_reminder_impl(request)


def update_reminder_status(request):
    """更新提醒状态 - 重定向到新的模块"""
    return update_reminder_status_impl(request)


def bulk_edit_reminders(request):
    """批量编辑重复提醒 - 重定向到新的模块"""
    return bulk_edit_reminders_impl(request)


@csrf_exempt
def convert_recurring_to_single(request):
    """将重复提醒转换为单次提醒 - 重定向到新的模块"""
    return convert_recurring_to_single_impl(request)


def maintain_reminders(request):
    """维护提醒实例 - 重定向到新的模块"""
    return maintain_reminders_impl(request)


def delete_reminder(request):
    """删除提醒 - 重定向到新的模块"""
    return delete_reminder_impl(request)


@csrf_exempt
def snooze_reminder(request):
    """延迟提醒 - 重定向到新的模块"""
    return snooze_reminder_impl(request)


@csrf_exempt
def dismiss_reminder(request):
    """忽略/关闭提醒 - 重定向到新的模块"""
    return dismiss_reminder_impl(request)


@csrf_exempt
def complete_reminder(request):
    """完成提醒 - 重定向到新的模块"""
    return complete_reminder_impl(request)


def get_pending_reminders(request):
    """获取待触发的提醒 - 重定向到新的模块"""
    return get_pending_reminders_impl(request)


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


@csrf_exempt
def mark_notification_sent(request):
    """标记通知已发送（占位函数）"""
    if request.method == 'POST':
        # 简单的占位实现，直接返回成功
        # TODO: 将来可以在这里记录通知发送历史
        return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


