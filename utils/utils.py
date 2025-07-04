"""显然"""
import json
from datetime import datetime
from pathlib import Path
from openai import OpenAI
import logging
logger = logging.getLogger("logger")


def user_prefer_ai_setting(user_ai_settings: dict, messages: list, tools: list[dict]=None, ai_settings_file_path: str = r"default_files/AI_setting.json", scene: str = "default") -> 'OpenAI.completions':

    """
    一个大模型接口通用函数

    :param user_ai_settings: 用户数据库中存储的 AI 偏好。期望的格式：{"场景": 场景代码}， 若查找不到匹配场景或没有传入，默认为 default
    :param messages: 大模型聊天记录。
    :param tools: 大模型需要用到的工具
    :param ai_settings_file_path: 项目根目录下的 AI_setting 文件路径
    :param scene: 调用这个 AI 时的原因场景，比如是时间规划，还是场景匹配。。。
    :return: 大模型返回的 completions
    """

    # 类型检查
    if not (isinstance(messages, list) and all(isinstance(m, dict) for m in messages)):
        logger.error(f"messages 参数类型非法，应该是 list[dict]，实际为：{type(messages)}, 内容：{messages}")
        raise ValueError(f"messages 参数类型非法，应该是 list[dict]，实际为：{type(messages)}, 内容：{messages}")


    # 保证从项目根目录查找，无论你在哪运行脚本
    core_dir = Path(__file__).parent  # D:\PROJECTS\UniSchedulerSuper\utils
    project_root = core_dir.parent  # D:\PROJECTS\UniSchedulerSuper
    settings_path = project_root / ai_settings_file_path
    settings_path = settings_path.resolve()

    with open(settings_path, 'r', encoding='utf-8') as file:
        ai_settings = json.load(file)

    # TODO 这里应该有一套根据用户的 user_ai_settings 设定的，不同需求下，使用哪一个模型的设定。
    #  但我现在还没改 user_ai_settings 的格式，暂且只能指定一个 AI。因此这里直接匹配用户的 AI 的 code 和文件中写的即可。

    ai_setting_for_llm = {
        "url": "<url>",
        "model": "<model>",
        "api": "<api-key>",
        "name": "<nick-name>",
        "temperature": 0,
        "code": 0
    }

    for ai_setting in ai_settings:
        if ai_setting["code"] == user_ai_settings["AI_setting_code"]:
            ai_setting_for_llm = ai_setting
            break

    try:
        client = OpenAI(
            api_key=ai_setting_for_llm["api"],
            base_url=ai_setting_for_llm["url"]
        )

        # 调用API进行聊天
        if tools:
            completion = client.chat.completions.create(
                model=ai_setting_for_llm["model"],  # 你可以根据需要选择不同的模型规格
                messages=messages,
                temperature=ai_setting_for_llm["temperature"],
                max_tokens=8*1024,
                tools=tools
                # TODO 这里，我改以什么方式，更好地规划输出长度呢（而且DS的好像不让输出这么多）
                # TODO 需要加错误处理函数。
            )
        else:
            completion = client.chat.completions.create(
                model=ai_setting_for_llm["model"],  # 你可以根据需要选择不同的模型规格
                messages=messages,
                temperature=ai_setting_for_llm["temperature"],
                max_tokens=8*1024,
            )
        prompt_tokens = completion.usage.prompt_tokens
        completion_tokens = completion.usage.completion_tokens
        # TODO 这里的计费逻辑。。。以后再说
        # 返回 LLM 的回复
        return completion

    except Exception as e:
        print(e)
        logger.error(f"{e}")
        return None


# TODO 将日程信息转为自然语言 （没写好）
def events_to_natural_language_helper(events: list) -> str:
    """
    辅助函数：将结构化的日程数据转换为自然语言描述

    :param events: 日程事件列表
    :return: 自然语言描述的日程字符串
    """
    if not events:
        return "无日程安排"

    def parse_datetime(time_str):
        """解析时间字符串，支持多种格式"""
        if not time_str or time_str == '未知时间':
            return None

        # 移除末尾的.000Z
        time_str = str(time_str).replace('.000Z', '').replace('Z', '')

        try:
            # 尝试解析ISO格式
            if 'T' in time_str:
                return datetime.fromisoformat(time_str)
            else:
                # 尝试其他可能的格式
                return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except:
            return None

    def format_datetime_natural(dt):
        """将datetime对象转换为自然语言格式"""
        if not dt:
            return "未知时间"
        return f"{dt.year}年{dt.month}月{dt.day}日{dt.hour}点{dt.minute:02d}分"

    def get_importance_text(importance):
        """转换重要性为中文描述"""
        importance_map = {
            'important': '很重要',
            'not-important': '不重要',
            '': '重要性未知'
        }
        return importance_map.get(importance, importance if importance else '重要性未知')

    def get_urgency_text(urgency):
        """转换紧急性为中文描述"""
        urgency_map = {
            'urgent': '很紧急',
            'not-urgent': '不紧急',
            '': '紧急性未知'
        }
        return urgency_map.get(urgency, urgency if urgency else '紧急性未知')

    event_descriptions = []
    for i, event in enumerate(events, 1):
        # 获取基本信息
        event_id = event.get('id', f'event_{i}')
        title = event.get('title', '未知事项')
        description = event.get('description', '无详细信息')
        importance = event.get('importance', '')
        urgency = event.get('urgency', '')

        # 解析时间
        start_dt = parse_datetime(event.get('start'))
        end_dt = parse_datetime(event.get('end'))

        # 构建时间描述
        if start_dt and end_dt:
            start_date = f"{start_dt.year}年{start_dt.month}月{start_dt.day}日"
            end_date = f"{end_dt.year}年{end_dt.month}月{end_dt.day}日"

            if start_dt.date() == end_dt.date():
                # 同一天
                time_desc = f"{start_date}{start_dt.hour}点{start_dt.minute:02d}分到{end_dt.hour}点{end_dt.minute:02d}分"
            else:
                # 跨天
                time_desc = f"{start_date}{start_dt.hour}点{start_dt.minute:02d}分到{end_date}{end_dt.hour}点{end_dt.minute:02d}分"
        else:
            time_desc = "时间未知"

        # 构建完整描述
        event_desc = (
            f"第{i}个日程（ID:{event_id}）：用户在{time_desc}安排了{title}日程，"
            f"详细信息：{description}。这个日程{get_importance_text(importance)}，{get_urgency_text(urgency)}。"
        )

        event_descriptions.append(event_desc)

    return '\n'.join(event_descriptions)


def list_to_str(lst:list)->str:
    """将列表转成顿号分隔的自然中文字符串"""
    if not lst:
        return "无"
    return '、'.join(str(x) for x in lst)