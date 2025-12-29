"""
views_import_events.py
课表导入功能 - 从教务系统获取课表并解析为带 RRule 的日程

功能：
1. 从学校教务系统获取本学期/历年课表数据（新API）
2. 解析课程信息（课程名、教室、教师、时间）
3. 按课程ID+时间段分组，构建 RRule 重复规则
4. 调用 EventService 创建带 RRule 的日程

API 设计：
- GET /api/import/semesters/     获取可用学期列表
- POST /api/import/fetch/        获取指定学期的课表
- POST /api/import/confirm/      确认导入选中的课程
"""

import json
import datetime
import re
import requests
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from logger import logger


# ==========================================
# 教务系统配置
# ==========================================

JWXS_BASE_URL = "https://jwxs.muc.edu.cn"
JWXS_SCHEDULE_API = "/student/courseSelect/thisSemesterCurriculum/ajaxStudentSchedule/callback"
JWXS_INDEX_PAGE = "/student/courseSelect/thisSemesterCurriculum/index"


# ==========================================
# 工具函数
# ==========================================

def parse_time_str(time_str: str) -> str:
    """
    将时间字符串 "0800" 转换为 "08:00" 格式
    """
    if len(time_str) == 4:
        return f"{time_str[:2]}:{time_str[2:]}"
    return time_str


def build_time_table(jcsjbs: list) -> dict:
    """
    构建节次时间映射表
    
    Args:
        jcsjbs: 节次时间表列表
    
    Returns:
        {节次: {"start": "08:00", "end": "08:45"}, ...}
    """
    time_table = {}
    for item in jcsjbs:
        jc = int(item["jc"])
        time_table[jc] = {
            "start": parse_time_str(item["kssj"]),
            "end": parse_time_str(item["jssj"])
        }
    return time_table


def parse_class_week(class_week: str) -> list:
    """
    解析周次掩码，返回有课的周次列表
    
    Args:
        class_week: 24位字符串，如 "111111111111111111000000"
    
    Returns:
        有课的周次列表，如 [1, 2, 3, ..., 18]
    """
    weeks = []
    for i, char in enumerate(class_week):
        if char == "1":
            weeks.append(i + 1)
    return weeks


def get_weekday_code(day: int) -> str:
    """
    获取 RRule 星期代码 (1-7 -> MO-SU)
    """
    weekday_map = {
        1: 'MO',
        2: 'TU',
        3: 'WE',
        4: 'TH',
        5: 'FR',
        6: 'SA',
        7: 'SU'
    }
    return weekday_map.get(day, 'MO')


def get_weekday_chinese(day: int) -> str:
    """获取星期几的中文名称"""
    weekdays = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return weekdays[day] if 1 <= day <= 7 else f"第{day}天"


def calculate_first_class_date(semester_code: str, weekday: int, weeks: list) -> Optional[datetime.date]:
    """
    计算课程第一次上课的日期
    
    Args:
        semester_code: 学期代码，如 "2025-2026-2-1"
        weekday: 星期几 (1-7)
        weeks: 有课的周次列表
    
    Returns:
        第一次上课的日期
    """
    if not weeks:
        return None
    
    # 解析学期代码，推算学期开始日期
    # 格式: "年份-年份-学期-1"
    # 假设：第一学期从9月第一个周一开始，第二学期从2月下旬开始
    parts = semester_code.split('-')
    if len(parts) < 3:
        return None
    
    start_year = int(parts[0])
    semester = int(parts[2])
    
    if semester == 1:
        # 第一学期：假设从9月1日所在周的周一开始
        sept_1 = datetime.date(start_year, 9, 1)
        days_since_monday = (sept_1.weekday())  # Monday=0
        semester_start = sept_1 - datetime.timedelta(days=days_since_monday)
    else:
        # 第二学期：假设从2月24日所在周的周一开始
        end_year = int(parts[1])
        feb_24 = datetime.date(end_year, 2, 24)
        days_since_monday = (feb_24.weekday())
        semester_start = feb_24 - datetime.timedelta(days=days_since_monday)
    
    # 计算第一次上课的日期
    first_week = min(weeks)
    # 从学期开始日期算起，加上 (first_week - 1) 周 + (weekday - 1) 天
    first_date = semester_start + datetime.timedelta(weeks=first_week - 1, days=weekday - 1)
    
    return first_date


def infer_rrule_from_weeks(weeks: list, weekday: int) -> Tuple[str, str]:
    """
    从周次列表推断 RRule 规则
    
    Args:
        weeks: 有课的周次列表，如 [1, 2, 3, ..., 18]
        weekday: 星期几 (1-7)
    
    Returns:
        (rrule_string, rrule_text) 元组
    """
    if not weeks:
        return "", "无重复"
    
    count = len(weeks)
    weekday_code = get_weekday_code(weekday)
    weekday_cn = get_weekday_chinese(weekday)
    
    if count == 1:
        return "", "单次"
    
    # 分析周次间隔
    intervals = []
    sorted_weeks = sorted(weeks)
    for i in range(1, len(sorted_weeks)):
        intervals.append(sorted_weeks[i] - sorted_weeks[i-1])
    
    if not intervals:
        return "", "单次"
    
    # 统计最常见的间隔
    interval_counts = defaultdict(int)
    for interval in intervals:
        interval_counts[interval] += 1
    
    most_common_interval = max(interval_counts, key=interval_counts.get)
    
    # 根据间隔推断频率
    if most_common_interval == 1:
        # 连续周次 -> 每周重复
        rrule = f"FREQ=WEEKLY;BYDAY={weekday_code};COUNT={count}"
        rrule_text = f"每{weekday_cn}，共{count}次"
    elif most_common_interval == 2:
        # 隔周
        rrule = f"FREQ=WEEKLY;INTERVAL=2;BYDAY={weekday_code};COUNT={count}"
        rrule_text = f"每两周{weekday_cn}，共{count}次"
    else:
        # 其他间隔
        rrule = f"FREQ=WEEKLY;INTERVAL={most_common_interval};BYDAY={weekday_code};COUNT={count}"
        rrule_text = f"每{most_common_interval}周{weekday_cn}，共{count}次"
    
    return rrule, rrule_text


def build_description(location: str, teacher: str, properties: str = "", unit: float = 0) -> str:
    """
    构建日程描述
    """
    parts = []
    if location:
        parts.append(f"📍 教室: {location}")
    if teacher:
        parts.append(f"👨‍🏫 教师: {teacher}")
    if properties:
        parts.append(f"📚 类型: {properties}")
    if unit:
        parts.append(f"📊 学分: {unit}")
    return '\n'.join(parts)


# ==========================================
# 教务系统 API 调用
# ==========================================

def fetch_schedule_from_jwxs(cookie: str, plan_code: str) -> Tuple[bool, Any]:
    """
    从教务系统获取指定学期的课表数据
    
    Args:
        cookie: 教务系统 Cookie
        plan_code: 学期代码，如 "2025-2026-1-1"
    
    Returns:
        (success, data_or_error) 元组
    """
    url = f"{JWXS_BASE_URL}{JWXS_SCHEDULE_API}"
    
    headers = {
        "Cookie": cookie,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": JWXS_BASE_URL,
        "Referer": f"{JWXS_BASE_URL}{JWXS_INDEX_PAGE}",
    }
    
    # 请求体格式: "&planCode=xxx"
    data = f"&planCode={plan_code}"
    
    try:
        response = requests.post(url, headers=headers, data=data, timeout=30)
        
        if response.status_code != 200:
            return False, f"请求失败，状态码: {response.status_code}"
        
        # 检查是否被重定向到登录页面
        if "login" in response.url.lower() or "登录" in response.text[:500]:
            return False, "Cookie已过期或无效，请重新登录获取Cookie"
        
        try:
            return True, response.json()
        except json.JSONDecodeError:
            return False, "响应不是有效的JSON格式"
        
    except requests.Timeout:
        return False, "请求超时，请检查网络连接"
    except requests.RequestException as e:
        return False, f"网络请求错误: {str(e)}"
    except Exception as e:
        return False, f"未知错误: {str(e)}"


def parse_jwxs_courses(data: dict, semester_code: str) -> List[Dict[str, Any]]:
    """
    解析教务系统返回的课表数据
    
    Args:
        data: 教务系统返回的原始数据
        semester_code: 学期代码
    
    Returns:
        解析后的课程列表
    """
    courses = []
    
    # 构建节次时间表
    time_table = build_time_table(data.get("jcsjbs", []))
    
    if not time_table:
        logger.warning("未找到节次时间表 (jcsjbs)")
        return courses
    
    # 解析选课信息
    xkxx_list = data.get("xkxx", [])
    if not xkxx_list:
        logger.warning("未找到选课信息 (xkxx)")
        return courses
    
    # xkxx 是一个包含一个字典的列表
    xkxx = xkxx_list[0] if xkxx_list else {}
    
    for course_id, course_info in xkxx.items():
        course_name = course_info.get("courseName", "未知课程")
        teacher = course_info.get("attendClassTeacher", "").strip().rstrip('*').strip()
        properties = course_info.get("coursePropertiesName", "")
        unit = course_info.get("unit", 0)
        
        # 遍历上课时间地点列表（同一课程可能有多个时间段）
        time_place_list = course_info.get("timeAndPlaceList", [])
        
        for tp_index, tp in enumerate(time_place_list):
            class_day = tp.get("classDay", 0)  # 星期几 (1-7)
            class_session = tp.get("classSessions", 0)  # 第几节开始
            continuing_session = tp.get("continuingSession", 1)  # 连续几节
            class_week = tp.get("classWeek", "")  # 周次掩码
            campus = tp.get("campusName", "")
            building = tp.get("teachingBuildingName", "")
            classroom = tp.get("classroomName", "")
            week_desc = tp.get("weekDescription", "")
            
            # 计算开始和结束时间
            start_session = class_session
            end_session = class_session + continuing_session - 1
            
            start_time = time_table.get(start_session, {}).get("start", "08:00")
            end_time = time_table.get(end_session, {}).get("end", "09:35")
            
            # 解析有课的周次
            weeks = parse_class_week(class_week)
            
            if not weeks:
                continue
            
            # 计算第一次上课的日期
            first_date = calculate_first_class_date(semester_code, class_day, weeks)
            if not first_date:
                continue
            
            # 构建开始和结束日期时间
            first_start = f"{first_date.isoformat()}T{start_time}:00"
            first_end = f"{first_date.isoformat()}T{end_time}:00"
            
            # 推断 RRule
            rrule, rrule_text = infer_rrule_from_weeks(weeks, class_day)
            
            # 构建位置字符串
            location = f"{campus}{building}{classroom}"
            
            # 构建课程对象
            course = {
                'course_id': f"{course_id}_{tp_index}",
                'original_id': course_id,
                'name': course_name,
                'teacher': teacher,
                'properties': properties,
                'unit': unit,
                'weekday': class_day,
                'weekday_name': get_weekday_chinese(class_day),
                'start_session': start_session,
                'end_session': end_session,
                'start_time': start_time,
                'end_time': end_time,
                'time_slot': f"{start_time}-{end_time}",
                'weeks': weeks,
                'week_count': len(weeks),
                'week_description': week_desc,
                'location': location,
                'campus': campus,
                'classroom': classroom,
                'first_start': first_start,
                'first_end': first_end,
                'rrule': rrule,
                'rrule_text': rrule_text,
                'description': build_description(location, teacher, properties, unit),
                'selected': True,  # 默认选中
            }
            courses.append(course)
    
    # 按星期几和开始时间排序
    courses.sort(key=lambda x: (x.get('weekday', 0), x.get('start_time', '')))
    
    return courses


# ==========================================
# API 视图
# ==========================================

@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_semesters(request):
    """
    获取可用学期列表
    
    GET /api/import/semesters/
    
    响应:
        {
            "status": "success",
            "semesters": [
                {"code": "2025-2026-2-1", "name": "2025-2026学年第二学期", "current": false},
                {"code": "2025-2026-1-1", "name": "2025-2026学年第一学期", "current": true},
                ...
            ],
            "current_semester": "2025-2026-1-1"
        }
    """
    # 动态生成学期列表（基于当前日期）
    now = datetime.datetime.now()
    current_year = now.year
    current_month = now.month
    
    semesters = []
    
    # 判断当前是哪个学期
    # 9-1月: 第一学期, 2-8月: 第二学期
    if current_month >= 9 or current_month == 1:
        # 第一学期
        if current_month == 1:
            current_start_year = current_year - 1
        else:
            current_start_year = current_year
        current_semester = f"{current_start_year}-{current_start_year+1}-1-1"
    else:
        # 第二学期
        current_start_year = current_year - 1
        current_semester = f"{current_start_year}-{current_start_year+1}-2-1"
    
    # 生成学期列表：下一学期 + 当前学期 + 过去2个学期
    semester_list = []
    
    if current_month >= 9 or current_month == 1:
        # 当前是第一学期，生成：下学期(第二学期) + 当前(第一学期) + 过去2个学期
        semester_list = [
            (current_start_year, 2),      # 下学期：2025-2026-2
            (current_start_year, 1),      # 当前：2025-2026-1
            (current_start_year - 1, 2),  # 上上学期：2024-2025-2
            (current_start_year - 1, 1),  # 更早：2024-2025-1
        ]
    else:
        # 当前是第二学期，生成：下学期(下学年第一学期) + 当前(第二学期) + 过去2个学期
        semester_list = [
            (current_start_year + 1, 1),  # 下学期：下学年第一学期
            (current_start_year, 2),      # 当前：第二学期
            (current_start_year, 1),      # 上学期：第一学期
            (current_start_year - 1, 2),  # 更早：上学年第二学期
        ]
    
    for year, sem in semester_list:
        code = f"{year}-{year+1}-{sem}-1"
        name = f"{year}-{year+1}学年第{'一' if sem == 1 else '二'}学期"
        is_current = (code == current_semester)
        
        semesters.append({
            "code": code,
            "name": name + (" (当前)" if is_current else ""),
            "current": is_current
        })
    
    return JsonResponse({
        'status': 'success',
        'semesters': semesters,
        'current_semester': current_semester
    })


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def fetch_courses(request):
    """
    获取指定学期的课表
    
    POST /api/import/fetch/
    
    请求:
        {
            "cookie": "JSESSIONID=xxxx; ...",
            "semester": "2025-2026-1-1"  // 可选，默认当前学期
        }
        
    响应:
        {
            "status": "success",
            "semester": {"code": "...", "name": "..."},
            "courses": [...],
            "total_courses": 8
        }
    """
    try:
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        cookie = data.get('cookie', '')
        semester_code = data.get('semester', '')
        
        if not cookie:
            return JsonResponse({
                'status': 'error',
                'message': '请提供教务系统 Cookie'
            }, status=400)
        
        # 如果未指定学期，获取当前学期
        if not semester_code:
            now = datetime.datetime.now()
            current_year = now.year
            current_month = now.month
            
            if current_month >= 9 or current_month == 1:
                if current_month == 1:
                    current_start_year = current_year - 1
                else:
                    current_start_year = current_year
                semester_code = f"{current_start_year}-{current_start_year+1}-1-1"
            else:
                current_start_year = current_year - 1
                semester_code = f"{current_start_year}-{current_start_year+1}-2-1"
        
        # 从教务系统获取数据
        success, result = fetch_schedule_from_jwxs(cookie, semester_code)
        
        if not success:
            return JsonResponse({
                'status': 'error',
                'message': result
            }, status=400)
        
        # 解析课程
        courses = parse_jwxs_courses(result, semester_code)
        
        if not courses:
            return JsonResponse({
                'status': 'error',
                'message': '未获取到课程数据，可能该学期没有选课记录'
            }, status=400)
        
        # 生成学期名称
        parts = semester_code.split('-')
        semester_name = f"{parts[0]}-{parts[1]}学年第{'一' if parts[2] == '1' else '二'}学期"
        
        return JsonResponse({
            'status': 'success',
            'semester': {
                'code': semester_code,
                'name': semester_name
            },
            'courses': courses,
            'total_courses': len(courses)
        })
        
    except Exception as e:
        logger.error(f"获取课表失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'服务器错误: {str(e)}'
        }, status=500)


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_import(request):
    """
    确认导入选中的课程
    
    POST /api/import/confirm/
    
    请求:
        {
            "courses": [
                {
                    "name": "课程名",
                    "first_start": "2025-09-02T08:00:00",
                    "first_end": "2025-09-02T09:35:00",
                    "description": "📍 教室: xxx\n👨‍🏫 教师: xxx",
                    "rrule": "FREQ=WEEKLY;BYDAY=TU;COUNT=18",
                    "groupID": "group-id"
                },
                ...
            ]
        }
        
    响应:
        {
            "status": "success",
            "imported_count": 8,
            "message": "成功导入 8 门课程"
        }
    """
    try:
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        courses = data.get('courses', [])
        
        if not courses:
            return JsonResponse({
                'status': 'error',
                'message': '没有要导入的课程'
            }, status=400)
        
        from core.services.event_service import EventService
        
        imported_count = 0
        errors = []
        
        for course in courses:
            try:
                event = EventService.create_event(
                    user=request.user,
                    title=course.get('name', course.get('title', '')),
                    start=course.get('first_start', course.get('start', '')),
                    end=course.get('first_end', course.get('end', '')),
                    description=course.get('description', ''),
                    importance=course.get('importance', ''),
                    urgency=course.get('urgency', ''),
                    groupID=course.get('groupID', ''),
                    rrule=course.get('rrule', '')
                )
                imported_count += 1
                
            except Exception as e:
                error_msg = f"导入 '{course.get('name', '未知课程')}' 失败: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        if imported_count > 0:
            message = f"成功导入 {imported_count} 门课程"
            if errors:
                message += f"，{len(errors)} 门失败"
            
            return JsonResponse({
                'status': 'success',
                'imported_count': imported_count,
                'message': message,
                'errors': errors if errors else None
            })
        else:
            return JsonResponse({
                'status': 'error',
                'message': '所有课程导入失败',
                'errors': errors
            }, status=400)
        
    except Exception as e:
        logger.error(f"确认导入失败: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'服务器错误: {str(e)}'
        }, status=500)


# ==========================================
# 兼容旧接口（保留用于过渡）
# ==========================================

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def fetch_and_parse_courses(request):
    """
    [兼容旧接口] 获取并解析课表 API
    重定向到新的 fetch_courses 接口
    """
    return fetch_courses(request)


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_import_courses(request):
    """
    [兼容旧接口] 确认导入课程 API
    重定向到新的 confirm_import 接口
    """
    return confirm_import(request)
