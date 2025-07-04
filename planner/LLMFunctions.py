import logging
import json
from utils.utils import user_prefer_ai_setting, events_to_natural_language_helper
from datetime import datetime

logger = logging.getLogger("logger")

"""
1. 查询已有偏好库中有无相适的
"""


def find_or_create_preset(prompt_scene_presets: list, _dialogue: list, user_ai_settings: dict) -> tuple[dict, str]:
    """
    从 prompt_scene_presets 中查找是否有和 user_prompt 语义相符的场景字典。
    如果有，返回该字典。
    如果没有，基于prompt整理一个结构一致的字典（内容允许为空），但返回None。
    这个函数用于在用户给出的prompt信息不足时候，通过查询用户的 prompt_scene_presets 信息，从过往聊天记录，补充信息。

    :param user_ai_settings: 数据库查找返回的用户AI选择
    :param prompt_scene_presets: 已有的场景预设列表
    :param _dialogue: 用户对日程规划工具生成的某个场景下的日程的互动和反馈

    :return: 匹配到的已有的场景字典，如果没有匹配到，返回根据场景新建的一个字典
    """
    # 1. 遍历已有场景，调用语义匹配（可使用LLM ToolCall功能/本地向量库等）

    for preset in prompt_scene_presets:
        is_match = toolcall_semantic_match(_dialogue=_dialogue,
                                           preset_scene_prompt=preset["prompt_scene"],
                                           user_ai_settings=user_ai_settings)
        if is_match:
            # TODO 这里应该升级一下逻辑，匹配上了还得继续往后匹配，然后多返回几个让用户选定要哪一个
            return preset, "is_match"
    # 没匹配到，返回一个新创建的
    new_preset = toolcall_dialogue_struct_new_preset(_dialogue=_dialogue, user_ai_settings=user_ai_settings)
    print(new_preset)
    # TODO 这里应该增加与 update_preset_with_dialogue 函数的交互，比如给这段对话打个标签之类的
    return new_preset, "new_preset"


def update_preset_with_dialogue(prompt_scene_presets: list, _dialogue: list, user_ai_settings: dict)->list:
    """
    根据用户聊天记录自动增删改场景 preset，实现对 prompt_scene_presets 的细致修正或新建。
    由于这个步骤相对耗时长，因此不在用户正常聊天过程中调用，而是静默使用。（或者做异步什么的？）
    因此这导致，为了确定用户这是对哪一个场景的增删改，需要重新获取整个聊天记录（如果在聊天过程中调用的话就不用了），判定。

    :param user_ai_settings: 数据库查找返回的用户AI选择
    :param prompt_scene_presets: 已有的场景预设列表
    :param _dialogue: 用户对日程规划工具生成的某个场景下的日程的互动和反馈

    :return: 更新后的场景预设列表
    """
    # 1. 首先判断用户主要意图的场景
    # 遍历当前preset，看哪项与反馈Prompt最近似
    match_idx = None
    for idx, preset in enumerate(prompt_scene_presets):
        if toolcall_semantic_match(_dialogue=_dialogue,
                                   preset_scene_prompt=preset["prompt_scene"],
                                   user_ai_settings=user_ai_settings):
            match_idx = idx
            break

    # 2. 如果匹配到了旧场景，用LLM抽取“如何修改”preset
    if match_idx is not None:
        print(f"匹配到旧场景：{prompt_scene_presets[match_idx]["prompt_scene"]}")
        preset = prompt_scene_presets[match_idx]
        # 用LLM理解“feedback如何修改preset”
        new_preset = toolcall_dialogue_modify_preset(_dialogue=_dialogue, original_preset=preset,
                                                     user_ai_settings=user_ai_settings)
        # 覆盖原preset
        prompt_scene_presets[match_idx] = new_preset
        # TODO 若是新生成，可否加一个函数来保存此处结果呢
        return prompt_scene_presets

    # 3. 否则新建一个场景，fields由LLM根据feedback结构化输出
    #（用LLM来结构化抽取：prompt_scene, need, do_not, other_info）
    print("匹配到新场景")
    new_preset = toolcall_dialogue_struct_new_preset(_dialogue=_dialogue, user_ai_settings=user_ai_settings)
    prompt_scene_presets.append(new_preset)
    return prompt_scene_presets


# 根据用户反馈，对现有场景 preset 的 need/do_not/other_info 字段增删改
def toolcall_dialogue_modify_preset(_dialogue: list, original_preset: dict, user_ai_settings: dict):
    """
    用大模型实现“根据用户反馈，对现有场景preset的need/do_not/other_info字段增删改”的能力。
    返回一个全新的dict（场景名与原保持一致，仅内容项被智能增删改）

    :param user_ai_settings: 数据库查找返回的用户AI选择
    :param _dialogue: 用户对日程规划工具生成的某个场景下的日程的互动和反馈
    :param original_preset: 上一步 update_preset_with_dialogue 函数中，查找到的原有场景的 preset


    :return: 全新的dict（场景名与原保持一致，仅内容项被智能增删改）
    """
    tools = [{
        "type": "function",
        "function": {
            "name": "feedback_modify_preset",
            "description": "依据用户聊天记录，对比原场景 preset 的内容，对 need, do_not, other_info 字段的列表进行增加/删减/修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt_scene": {"type": "string", "description": "原场景名，你不要改动"},
                    "need": {"type": "array", "items": {"type": "string"}},
                    "do_not": {"type": "array", "items": {"type": "string"}},
                    "other_info": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["prompt_scene", "need", "do_not", "other_info"]
            }
        }
    }]
    user_prompts = [sentence['content'] if sentence['role'] == 'user' else "" for sentence in _dialogue]
    user_prompts = [prompt for prompt in user_prompts if prompt]
    user_prompts_str = "\n".join(user_prompts)
    messages = [
        {"role": "system",
         "content": (
             "你是用户日程生成偏好设定助手。给定原有场景 preset（json形式），以及用户聊天记录（内含用户不满意的地方与新诉求），请结合两者，对原本这个场景下的 preset 的 need/do_not/other_info 三组内容做【合理的增删改】，生成最终新preset。"
             "尤其要注意：如果用户的喜好变了，请彻底替换相关字段，而非简单添加。")},
        {"role": "user",
         "content": f"【用户聊天记录】：{user_prompts_str}\n【原场景 preset】:\n{json.dumps(original_preset, ensure_ascii=False)}"}
    ]

    completion = user_prefer_ai_setting(user_ai_settings=user_ai_settings, messages=messages, tools=tools,
                                        scene="toolcall_dialogue_modify_preset")
    arguments = completion.choices[0].message.tool_calls[0].function.arguments
    result = json.loads(arguments)
    return result


# 用户反馈代表全新场景时，自动用LLM结构化生成 preset
def toolcall_dialogue_struct_new_preset(_dialogue: list, user_ai_settings: dict):
    """
    用户反馈代表全新场景时，自动用LLM结构化生成 preset
    :param user_ai_settings: 数据库查找返回的用户AI选择
    :param _dialogue: 用户对日程规划工具生成的某个场景下的日程的互动记录，记得把那些来自于别的模型的杂七杂八的 system prompt 去掉

    :return: 全新的 preset 的 dict
    """
    tools = [{
        "type": "function",
        "function": {
            "name": "build_struct_preset",
            "description": "将用户自由反馈转为结构化的preset（场景名 prompt_scene + 用户需要的 need + 用户不喜欢的 do_not + 用户的其他信息 other_info）",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt_scene": {"type": "string"},
                    "need": {"type": "array", "items": {"type": "string"}},
                    "do_not": {"type": "array", "items": {"type": "string"}},
                    "other_info": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["prompt_scene", "need", "do_not", "other_info"]
            }
        }
    }]

    # 这里导入已有的聊天记录，更有助于判断，尤其是那些场景关键词在前面几句，修改意见在后面的场景
    messages = [
        {"role": "system",
         "content": "输入是用户对【一个日程规划工具】生成的某个场景下的日程的互动和反馈，请将其转为 preset 结构（场景名+用户需要的+用户不喜欢的+用户的其他信息），成为对用户偏好的一个画像，json输出。"},
    ]
    messages += _dialogue
    completion = user_prefer_ai_setting(user_ai_settings=user_ai_settings, messages=messages, tools=tools,
                                        scene="toolcall_dialogue_struct_new_preset")
    print(f"{completion=}")
    arguments = completion.choices[0].message.tool_calls[0].function.arguments
    result = json.loads(arguments)
    return result


# 基于核心意图判断两个提示词是否属于同一语义场景
def toolcall_semantic_match(_dialogue: list, preset_scene_prompt: str, user_ai_settings: dict, max_retry_times=3):
    """
    基于核心意图判断两个提示词是否属于同一语义场景。该函数使用AI驱动的语义匹配系统,
    并且在JSON解码错误时最多重试 max_retry_times 次。

    :param user_ai_settings: 数据库查找返回的用户AI选择
    :param _dialogue: 用户对日程规划工具生成的某个场景下的日程的互动和反馈
    :type _dialogue: list
    :param preset_scene_prompt: 包含预定义场景的语句
    :type preset_scene_prompt: str
    :param max_retry_times: JSON解码重试次数的最大值，默认0
    :type max_retry_times: int
    :return: 布尔值,表示两个提示词是否属于同一场景
    :rtype: bool
    """
    function_definitions = {
        "name": "semantic_scene_match",
        "description": "判断两个prompt是否属于同一情景，返回布尔值。",
        "parameters": {
            "type": "object",
            "properties": {
                "is_match": {
                    "type": "boolean",
                    "description": "两个prompt是否语义上属于同一情境"
                }
            }
        }
    }
    tools = [
        {
            "type": "function",
            "function": function_definitions
        }
    ]

    user_prompts = [sentence['content'] if sentence['role'] == 'user' else "" for sentence in _dialogue]
    user_prompts = [prompt for prompt in user_prompts if prompt]
    user_prompts_str = "\n".join(user_prompts)

    messages = [
        {"role": "system",
         "content": "你是一个智能场景匹配助手。请判断以下两个prompt内容是否描述的是同一个场景，只需关注场景核心意图是否一致。"},
        {"role": "user", "content": f"用户新需求内容：\n{user_prompts_str}\n已有预设场景内容：\n{preset_scene_prompt}"}
    ]

    completion = user_prefer_ai_setting(user_ai_settings=user_ai_settings, messages=messages, tools=tools,
                                        scene="toolcall_semantic_match")
    arguments = completion.choices[0].message.tool_calls[0].function.arguments
    try:
        result = json.loads(arguments)
        return result["is_match"]
    except json.JSONDecodeError:
        if max_retry_times > 0:
            logger.error(f"JSONDecodeError: 对 {arguments=} 的解析失败！开始倒数第{max_retry_times}次重试！")
            max_retry_times -= 1
            return toolcall_semantic_match(_dialogue=_dialogue, preset_scene_prompt=preset_scene_prompt,
                                           user_ai_settings=user_ai_settings, max_retry_times=max_retry_times)
        else:
            logger.error(f"JSONDecodeError: 在上述重试后对 {arguments=} 的解析仍失败！详细信息："
                         f"\n{completion.choices[0].message=}"
                         f"\n{_dialogue=}"
                         f"\n{preset_scene_prompt=}"
                         )
            return False


# TODO 以天为单位检查日程冲突的函数（没写好）
def toolcall_schedule_conflict_check(existing_events: list, new_events: list, user_dialogue: list, scene_preset: dict,
                                     user_ai_settings: dict, max_retry_times=3):
    """
    以天为单位检查日程冲突的函数。

    :param existing_events: 当天已有日程列表
    :param new_events: 当天新规划的待检查日程（包含跨天日程）
    :param user_dialogue: 用户本轮对话中的输入
    :param scene_preset: 本轮对话对应场景收集的历史提示词
    :param user_ai_settings: 数据库查找返回的用户AI选择
    :param max_retry_times: JSON解码重试次数的最大值，默认3
    :return: dict，包含是否冲突、冲突的日程序号和冲突原因
    """

    # 构建ToolCall工具定义
    tools = [{
        "type": "function",
        "function": {
            "name": "check_schedule_conflict",
            "description": "根据用户对话内容、场景偏好设置、已有日程，判断新规划的日程是否存在冲突。",
            "parameters": {
                "type": "object",
                "properties": {
                    "has_conflict": {
                        "type": "boolean",
                        "description": "判断是否存在日程冲突，需要考虑时间重叠、用户偏好违反、用户对话中的调整需求等因素"
                    },
                    "conflicted_events": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "event_id": {"type": "string", "description": "冲突的待规划日程ID或序号"},
                                "conflict_reason": {"type": "string", "description": "该日程的具体冲突原因"}
                            }
                        },
                        "description": "冲突的待规划日程列表，每项包含日程ID/序号和冲突原因"
                    }
                },
                "required": ["has_conflict", "conflicted_events"]
            }
        }
    }]

    # 提取用户对话内容
    user_prompts = [sentence['content'] if sentence['role'] == 'user' else "" for sentence in user_dialogue]
    user_prompts = [prompt for prompt in user_prompts if prompt]
    user_prompts_str = "\n".join(user_prompts)

    # 构建场景偏好描述
    scene_description = ""
    if scene_preset:
        scene_description = (
            f"场景：{scene_preset.get('prompt_scene', '未知场景')}\n"
            f"用户需要：{list_to_str(scene_preset.get('need', []))}\n"
            f"用户不喜欢：{list_to_str(scene_preset.get('do_not', []))}\n"
            f"其他信息：{list_to_str(scene_preset.get('other_info', []))}"
        )

    # 构建消息
    messages = [
        {"role": "system",
         "content": (
             "你是一个智能日程冲突检查助手。请根据用户的对话内容、场景偏好设置、已有日程和新规划日程，"
             "判断是否存在冲突。冲突包括但不限于：时间重叠、违反用户偏好设置、与场景需求不符等。"
             "如果发现冲突，请准确识别冲突的日程ID（从日程描述中的ID信息获取），并详细说明冲突原因。"
         )},
        {"role": "user",
         "content": (
             f"【用户对话内容】：\n{user_prompts_str}\n\n"
             f"【场景偏好设置】：\n{scene_description}\n\n"
             f"【当天已有日程】：\n{events_to_natural_language_helper(existing_events)}\n\n"
             f"【当天新规划日程】：\n{events_to_natural_language_helper(new_events)}\n\n"
             f"请检查新规划日程是否与已有日程冲突，是否违反用户偏好设置。"
             f"如果有冲突，请在conflicted_events中列出每个冲突日程的ID和具体原因。"
         )}
    ]

    completion = user_prefer_ai_setting(
        user_ai_settings=user_ai_settings,
        messages=messages,
        tools=tools,
        scene="toolcall_schedule_conflict_check"
    )
    arguments = completion.choices[0].message.tool_calls[0].function.arguments
    
    try:

        result = json.loads(arguments)

        # 记录冲突详情用于调试
        if result.get("has_conflict", False):
            logger.info(f"检测到日程冲突: {result.get('conflicted_events', [])}")

        return {
            "has_conflict": result.get("has_conflict", False),
            "conflicted_events": result.get("conflicted_events", [])
        }

    except json.JSONDecodeError:
        if max_retry_times > 0:
            logger.error(f"JSONDecodeError: 对 {arguments=} 的解析失败！开始倒数第{max_retry_times}次重试！")
            max_retry_times -= 1
            return toolcall_schedule_conflict_check(
                existing_events=existing_events,
                new_events=new_events,
                user_dialogue=user_dialogue,
                scene_preset=scene_preset,
                user_ai_settings=user_ai_settings,
                max_retry_times=max_retry_times
            )
        else:
            logger.error(
                f"JSONDecodeError: 在上述重试后对 {arguments=} 的解析仍失败！详细信息："
                f"\n{completion.choices[0].message=}"
                f"\n{existing_events=}"
                f"\n{new_events=}"
                f"\n{user_dialogue=}"
                f"\n{scene_preset=}"
            )
            return {"has_conflict": False, "conflicted_events": []}
    except Exception as e:
        logger.error(f"日程冲突检查时发生未知错误: {e}")
        return {"has_conflict": False, "conflicted_events": []}

def list_to_str(lst):
    """将列表转成顿号分隔的自然中文字符串"""
    if not lst:
        return "无"
    return '、'.join(str(x) for x in lst)


if __name__ == '__main__':
    user_preference = {
        "prompt_scene_presets": [
            {"prompt_scene": "根据课程安排日程",
             "need": ["给每堂理工科课程分别安排预习时间，复习时间和课后作业时间",
                      "可以在其他方便摸鱼的水课期间安排日程",
                      "可以在下午和晚上安排日程"
                      ],
             "do_not": ["在理工科课程上课时安排日程",
                        "在早上安排日程",
                        "占用吃饭时间",
                        "占用睡觉时间",
                        ],
             "other_info": ["我大约在12:30-14:00吃饭和午睡",
                            "大学物理和高等数学课程的预习、复习时间相对其他课程更长"
                            ]
             },
            {"prompt_scene": "骑车",
             "need": ["查询天气信息并提供相关建议",
                      "查询路况和交通信息",
                      "选定目的地"
                      ],
             "do_not": ["在下雨天安排骑车日程",
                        "在早上安排日程",
                        "占用吃饭时间",
                        "占用睡觉时间"
                        ],
             "other_info": ["我现居住在北京丰台", ]
             },
            {"prompt_scene": "旅游",
             "need": ["购买船票"],
             "do_not": ["花很多钱"],
             "other_info": ["用户很穷"]
             },
        ]
    }

    dialogue = [
        {"role": "user",
         "content": "我明天要去北京玩儿，帮我安排日程"},
        {"role": "assistant", "content": f"我帮你安排了明天从上海去北京的机票和游玩路线"},
        {"role": "user",
         "content": "我住在杭州，不是上海。", },
        {"role": "assistant", "content": f"我帮你安排了明天从杭州去北京的机票和游玩路线"},
        {"role": "user",
         "content": "我喜欢坐高铁，不要坐飞机", },
        {"role": "assistant", "content": f"好的，我帮你安排了明天从杭州去北京的高铁车票（二等座599元）和游玩路线"},
        {"role": "user",
         "content": "我很有钱，给我安排一等座，不要二等座，尽管多花钱。然后你给的出发时间太早了，我起不来床，把出发时间弄晚一些，比如中午十二点", }
    ]

    preset_result = find_or_create_preset(prompt_scene_presets=user_preference["prompt_scene_presets"],
                                          _dialogue=dialogue,
                                          user_ai_settings={"AI_setting_code": 2})

    preset_result_str = (
        f"在场景【{preset_result['prompt_scene']}】相关的日程生成时，请注意：\n"
        f"我期望实现：{list_to_str(preset_result['need'])}\n"
        f"你不可以做的有：{list_to_str(preset_result['do_not'])}\n"
        f"其他补充信息：{list_to_str(preset_result['other_info'])}"
    )

    print(preset_result_str)

    new_prompt_scene_presets = update_preset_with_dialogue(prompt_scene_presets=user_preference["prompt_scene_presets"],
                                                           _dialogue=dialogue,
                                                           user_ai_settings={"AI_setting_code": 2})
    print(new_prompt_scene_presets)

