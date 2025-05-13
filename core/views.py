
# Create your views here.
import datetime
from typing import List

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from .forms import RegisterForm
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import logout
from django.shortcuts import render
import uuid
import markdown
from datetime import timedelta
from django.contrib.auth.decorators import login_required
import requests

import logging
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

    # 创建一个上下文字典
    context = {
        "datetime": datetime.datetime.now(),
        "currentWeek": week_number,
        'user': request.user  # 传递用户对象，方便在模板中使用 {{ request.user.username }}
    }
    return render(request, 'home.html', context)


@login_required
@csrf_exempt
def change_view(request):
    if request.method == 'POST':
        user_data, created, result = UserData().get_or_initialize(request=request, new_key="user_settings")
        # user_data, created = UserData.objects.get_or_create(user=request.user, key="user_settings",
        #                                                     defaults={"value": json.dumps([])})
        # user_data.init_key(request, new_key="user_settings")

        user_settings = user_data.get_value()
        now_view = {"now_view": json.loads(request.body)}
        now_view = add_8_hours_to_time_data(now_view)
        # TODO 这里有个BUG，月视图下刷新，总是会向早一个月，不知怎么解决。当然可以在这里打补丁处理月视图，但感觉还是应该摸清楚具体

        user_settings.append(now_view)

        while len(user_settings) >= 10:
            del user_settings[0]

        user_data.set_value(user_settings)

        return JsonResponse({'status': 'success', 'message': 'Success request'}, status=200)

    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


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
        user_preference_data.set_value(updated_preference_dict)


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
        user_data, created = UserData.objects.get_or_create(user=request.user, key="user_settings", defaults={"value": json.dumps([])})
        user_settings = user_data.get_value()
        # 这里，我们选择返回数据库中（经过处理后的）最新的日程
        # TODO 对于新注册的用户，这里会因为没有收集到足够的setting数据而报错索引溢出。但是可以不管

        return JsonResponse({'status': 'success', 'message': user_settings[-2]}, status=200)

    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)



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

        user_temp_events_data, created, result = UserData.get_or_initialize(
            request=request,
            new_key="planner"
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

        if user_preference["auto_ddl"]:
            ddl = data.get('ddl')
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


