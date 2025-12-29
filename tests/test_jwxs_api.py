#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
教务系统课表API测试脚本

测试从 jwxs.muc.edu.cn 获取课表数据的功能。
需要提供有效的Cookie来进行认证。

数据结构说明：
- jcsjbs: 节次时间表，定义每节课的开始/结束时间
  - jc: 第n节
  - kssj: 开始时间 (如 "0800" 表示 08:00)
  - jssj: 结束时间 (如 "0845" 表示 08:45)
  
- xkxx: 选课信息，包含课程详情
  - courseName: 课程名称
  - attendClassTeacher: 授课教师
  - timeAndPlaceList: 上课时间地点列表
    - classDay: 星期几 (1-7)
    - classSessions: 第几节开始
    - continuingSession: 持续几节
    - classWeek: 周次掩码 (24位，1表示有课)
    - campusName: 校区名称
    - classroomName: 教室名称
    - weekDescription: 周次描述 (如 "1-18周")
"""

import requests
import json
from datetime import datetime, timedelta


# 教务系统配置
BASE_URL = "https://jwxs.muc.edu.cn"
API_ENDPOINT = "/student/courseSelect/thisSemesterCurriculum/ajaxStudentSchedule/callback"

# 可用的学期代码
SEMESTER_OPTIONS = {
    "2025-2026-2-1": "2025-2026学年第二学期",
    "2025-2026-1-1": "2025-2026学年第一学期(当前)",
    "2024-2025-2-1": "2024-2025学年第二学期",
    "2024-2025-1-1": "2024-2025学年第一学期",
}


def fetch_schedule(cookie: str, plan_code: str = "2025-2026-1-1") -> dict:
    """
    从教务系统获取课表数据
    
    Args:
        cookie: 教务系统登录后的Cookie字符串
        plan_code: 学期代码，如 "2025-2026-1-1"
    
    Returns:
        包含课表数据的字典
    """
    url = f"{BASE_URL}{API_ENDPOINT}"
    
    headers = {
        "Cookie": cookie,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/student/courseSelect/thisSemesterCurriculum/index",
    }
    
    # 注意：请求体格式是 "&planCode=xxx"，带有前导 &
    data = f"&planCode={plan_code}"
    
    print(f"正在请求: {url}")
    print(f"学期: {SEMESTER_OPTIONS.get(plan_code, plan_code)}")
    
    response = requests.post(
        url,
        headers=headers,
        data=data,
        timeout=30
    )
    
    print(f"响应状态码: {response.status_code}")
    
    if response.status_code != 200:
        raise Exception(f"请求失败，状态码: {response.status_code}")
    
    # 检查是否被重定向到登录页面
    if "login" in response.url.lower() or "登录" in response.text[:500]:
        raise Exception("Cookie已过期或无效，请重新登录获取Cookie")
    
    try:
        return response.json()
    except json.JSONDecodeError:
        print(f"响应内容前500字符: {response.text[:500]}")
        raise Exception("响应不是有效的JSON格式")


def parse_time(time_str: str) -> str:
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
            "start": parse_time(item["kssj"]),
            "end": parse_time(item["jssj"])
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
            weeks.append(i + 1)  # 周次从1开始
    return weeks


def get_weekday_name(day: int) -> str:
    """获取星期几的中文名称"""
    weekdays = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return weekdays[day] if 1 <= day <= 7 else f"第{day}天"


def parse_courses(data: dict) -> list:
    """
    解析课表数据，提取课程信息
    
    Args:
        data: 教务系统返回的原始数据
    
    Returns:
        解析后的课程列表
    """
    courses = []
    
    # 构建节次时间表
    time_table = build_time_table(data.get("jcsjbs", []))
    print(f"\n节次时间表:")
    for jc, times in time_table.items():
        print(f"  第{jc}节: {times['start']} - {times['end']}")
    
    # 解析选课信息
    xkxx_list = data.get("xkxx", [])
    if not xkxx_list:
        print("警告: 没有找到选课信息 (xkxx)")
        return courses
    
    # xkxx 是一个包含一个字典的列表
    xkxx = xkxx_list[0] if xkxx_list else {}
    
    for course_id, course_info in xkxx.items():
        course_name = course_info.get("courseName", "未知课程")
        teacher = course_info.get("attendClassTeacher", "").strip()
        properties = course_info.get("coursePropertiesName", "")
        unit = course_info.get("unit", 0)
        
        # 遍历上课时间地点列表
        time_place_list = course_info.get("timeAndPlaceList", [])
        
        for tp in time_place_list:
            class_day = tp.get("classDay", 0)  # 星期几
            class_session = tp.get("classSessions", 0)  # 第几节开始
            continuing_session = tp.get("continuingSession", 1)  # 持续几节
            class_week = tp.get("classWeek", "")  # 周次掩码
            campus = tp.get("campusName", "")
            building = tp.get("teachingBuildingName", "")
            classroom = tp.get("classroomName", "")
            week_desc = tp.get("weekDescription", "")
            
            # 计算开始和结束时间
            start_session = class_session
            end_session = class_session + continuing_session - 1
            
            start_time = time_table.get(start_session, {}).get("start", "??:??")
            end_time = time_table.get(end_session, {}).get("end", "??:??")
            
            # 解析有课的周次
            weeks = parse_class_week(class_week)
            
            course = {
                "id": course_id,
                "name": course_name,
                "teacher": teacher,
                "properties": properties,
                "unit": unit,
                "weekday": class_day,
                "weekday_name": get_weekday_name(class_day),
                "start_session": start_session,
                "end_session": end_session,
                "start_time": start_time,
                "end_time": end_time,
                "weeks": weeks,
                "week_description": week_desc,
                "location": f"{campus}{building}{classroom}",
                "campus": campus,
                "classroom": classroom,
            }
            courses.append(course)
    
    return courses


def print_courses(courses: list):
    """打印课程列表"""
    print(f"\n{'='*60}")
    print(f"共找到 {len(courses)} 门课程的上课时间安排")
    print(f"{'='*60}")
    
    for i, course in enumerate(courses, 1):
        print(f"\n[{i}] {course['name']}")
        print(f"    教师: {course['teacher']}")
        print(f"    类型: {course['properties']} | 学分: {course['unit']}")
        print(f"    时间: {course['weekday_name']} 第{course['start_session']}-{course['end_session']}节 ({course['start_time']}-{course['end_time']})")
        print(f"    周次: {course['week_description']} (共{len(course['weeks'])}周)")
        print(f"    地点: {course['location']}")


def main():
    """主函数 - 测试获取课表"""
    print("=" * 60)
    print("教务系统课表API测试")
    print("=" * 60)
    
    # 提示输入Cookie
    print("\n请在浏览器中登录教务系统 (jwxs.muc.edu.cn)")
    print("然后按 F12 打开开发者工具 -> Network/网络 -> 刷新页面")
    print("点击任意请求 -> Headers/标头 -> 找到 Cookie 并复制")
    print("-" * 60)
    
    cookie = input("请粘贴Cookie (或按回车使用测试数据): ").strip()
    
    if not cookie:
        # 使用本地测试数据
        print("\n使用本地测试数据...")
        try:
            with open("core/scratch_响应.json", "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            # 尝试其他路径
            try:
                with open("../core/scratch_响应.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                print("错误: 找不到测试数据文件 core/scratch_响应.json")
                return
    else:
        # 选择学期
        print("\n可用学期:")
        for code, name in SEMESTER_OPTIONS.items():
            print(f"  {code}: {name}")
        
        plan_code = input("\n请输入学期代码 (默认 2025-2026-1-1): ").strip()
        if not plan_code:
            plan_code = "2025-2026-1-1"
        
        try:
            data = fetch_schedule(cookie, plan_code)
            
            # 保存响应数据供调试
            with open("tests/jwxs_response.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("响应数据已保存到 tests/jwxs_response.json")
        except Exception as e:
            print(f"\n错误: {e}")
            return
    
    # 解析课程
    courses = parse_courses(data)
    
    # 打印结果
    print_courses(courses)
    
    # 保存解析结果
    output_file = "tests/parsed_courses.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(courses, f, ensure_ascii=False, indent=2)
    print(f"\n解析结果已保存到 {output_file}")


if __name__ == "__main__":
    main()
