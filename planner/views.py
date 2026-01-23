from core.models import UserData
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI
import json
import uuid

from planner.LLMFunctions import find_or_create_preset, update_preset_with_dialogue
from utils.utils import list_to_str

from logger import logger
# Create your views here.

def planner_index(request):
    # TODO 很不规范地执行一下数据初始化
    user_planner_data, created = UserData.objects.get_or_create(
        user=request.user,
        key="planner",
        defaults={"value": json.dumps({
            "dialogue": [],
            "temp_events": [],
            "ai_planning_time": {}
        })}
    )
    return render(request, 'planner_index.html')

# AI建议修改的代码
@csrf_exempt
@login_required
def ai_suggestions(request):
    # TODO 做一个历史聊天记录，uid 存
    # TODO 做成一个 tool call，调用日程生成
    if request.method == 'GET':
        # 获取用户的所有事件
        user_events_data, created = UserData.objects.get_or_create(user=request.user, key="events")
        events = json.loads(user_events_data.value)
        all_events = json.loads(user_events_data.value)
        # 遍历列表中的每个字典，移除 "groupID" 字段，节省tokens
        for event in events:
            event.pop("groupID", None)  # 如果 "groupID" 不存在，不会报错
        events = convert_time_format(events)

        # 获取规划时间范围
        user_data_planner, created = UserData.objects.get_or_create(
            user=request.user,
            key="planner",
        )


        planner_data = json.loads(user_data_planner.value)
        time_range = planner_data["ai_planning_time"]

        # 筛选在时间范围内的事件
        filtered_events = []
        if 'start' in time_range and 'end' in time_range:
            time_range_start = datetime.fromisoformat(time_range['start'])
            time_range_end = datetime.fromisoformat(time_range['end'])

            for event in events:
                event_start = datetime.fromisoformat(event['start'])
                event_end = datetime.fromisoformat(event['end'])

                # 检查事件是否完全在时间范围内
                if time_range_start <= event_start and event_end <= time_range_end:
                    filtered_events.append(event)

        if not filtered_events:
            # 修复BUG 没有指定待时间段时返回错误
            return JsonResponse({"events": [], "suggestions": "请先框选要安排的时间段，并确保其中有已安排的日程哦~"})





        json_file_path = "default_files/events.json"  # 替换为你的 JSON 文件路径
        # 读取 JSON 文件
        with open(json_file_path, 'r', encoding='utf-8') as file:
            dialogues = json.load(file)
            for dialogue in dialogues:
                dialogue["content"] = str(dialogue["content"])



        dialogues.append({"role": "user", "content": str(filtered_events)})

        with open("default_files/AI_setting.json", 'r', encoding='utf-8') as file:
            ai_settings = json.load(file)



        user_setting_data, created = UserData.objects.get_or_create(user=request.user, key="setting", defaults={"value": json.dumps({"AI_setting_code": 4})})

        # 从统一配置获取默认 AI 设置
        from config.api_keys_manager import APIKeyManager
        _moonshot_config = APIKeyManager.get_llm_config('moonshot')
        ai_setting = {
            "url": _moonshot_config.get('base_url', 'https://api.moonshot.cn/v1') if _moonshot_config else 'https://api.moonshot.cn/v1',
            "model": "kimi-latest",
            "api": _moonshot_config.get('api_key', '') if _moonshot_config else '',
            "name": "kimi-latest",
            "temperature": 0.3,
            "code": 3
        }

        for ai_setting in ai_settings:
            if ai_setting["code"] == json.loads(user_setting_data.value)["AI_setting_code"]:
                break

        reply = ai_reply(dialogues, ai_setting)["response"]

        schedule_list, suggestion = parse_json_to_list_and_string(reply)
        dialogues.append({"role": "assistant", "content": reply})

        logger.debug(f'AI建议了：{suggestion}')
        logger.debug(f'AI计划了：{schedule_list}')


        try:
            final_suggestion = suggestion["我的建议"]
        except:
            final_suggestion = "AI什么也没说"


        # 遍历所有原始事件，更新时间或保留原始时间
        updated_events = []
        for original_event in all_events:
            matched = False
            for ai_event in schedule_list:
                if ai_event.get("id") == original_event.get("id"):
                    # 如果 AI 修改了这个事件，更新时间
                    updated_events.append({
                        "eventId": original_event["id"],
                        "newStart": ai_event["start"],
                        "newEnd": ai_event["end"]
                    })
                    # 更新 temp_events
                    planner_data["temp_events"].append({
                        "id": original_event["id"],
                        "title": original_event["title"],
                        "start": ai_event["start"],
                        "end": ai_event["end"],
                        "description": original_event["description"],
                        "importance": original_event["importance"],
                        "urgency": original_event["urgency"],
                        "groupID": original_event["groupID"],  # 存储 groupId
                        "ddl": original_event["ddl"],
                        "last_modified": original_event["last_modified"],
                    })
                    all_events = [item for item in all_events if item["id"] != original_event["id"]]
                    matched = True
                    break
            if not matched:
                # 如果 AI 没有修改这个事件，保留原始时间
                updated_events.append({
                    "eventId": original_event["id"],
                    "newStart": original_event["start"],
                    "newEnd": original_event["end"],
                })


            user_events_data.value = json.dumps(all_events)
            user_events_data.save()


            user_data_planner.value = json.dumps(planner_data)
            user_data_planner.save()

        return JsonResponse({"events": updated_events, "suggestions": final_suggestion})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

from datetime import timezone
# AI生成日程的代码
@csrf_exempt
@login_required
def ai_create(request):
    if request.method == 'POST':

        # 输入接收
        data = json.loads(request.body)
        user_input = data.get('input')

        group_id = data.get('group_id')

        user_planner_data, created, result = UserData.get_or_initialize(request=request, new_key="planner", data={
                "dialogue": [],
                "temp_events": [],
                "ai_planning_time": {}
            })


        # 这里其实重复获取了，后面又导入了一次，但我懒得改
        user_events_data, created, result = UserData.get_or_initialize(request=request, new_key="events")
        events = user_events_data.get_value()

        user_preference_data, created, result = UserData.get_or_initialize(request, new_key="user_preference")
        user_preference = user_preference_data.get_value()

        planner_data = user_planner_data.get_value()

        ai_planning_time = planner_data['ai_planning_time']
        dialogue_before = planner_data['dialogue']
        temp_events_before = planner_data['temp_events']

        user_planner_data.set_value({
                "dialogue":
                    dialogue_before + [{
                "role": "user",
                "content": str(user_input)
            }],
                "temp_events": temp_events_before,
                "ai_planning_time": ai_planning_time
        })
        # 修复当AI出错时，用户发的文本不被保存的问题

        # 筛选在时间范围内的事件
        filtered_events = []

        none_ai_planning_time_remind = ""  # 用来提示AI规划使用时没有指定时间

        if 'start' in ai_planning_time and 'end' in ai_planning_time:
            time_range_start = datetime.fromisoformat(ai_planning_time['start']).replace(tzinfo=timezone.utc)
            time_range_end = datetime.fromisoformat(ai_planning_time['end']).replace(tzinfo=timezone.utc)

            for event in events:
                event_start = (datetime.fromisoformat(event['start'])).replace(tzinfo=timezone.utc)
                event_end = datetime.fromisoformat(event['end']).replace(tzinfo=timezone.utc)

                # 检查事件是否完全在时间范围内
                if time_range_start <= event_start and event_end <= time_range_end:
                    filtered_events.append(event)
        else:
            none_ai_planning_time_remind = "您没有通过拖动选定的方式指定要提交给AI作为参考的时间段，这会导致AI无法正确绕开您的已有日程。\n"

        for event in filtered_events:
            event.pop("groupID", None)  # 如果 "groupID" 不存在，不会报错
            event.pop("id", None)  # 如果 "groupID" 不存在，不会报错
            event.pop("groupID", None)  # 如果 "groupID" 不存在，不会报错


        # AI设置
        json_file_path = "default_files/planner.json"  # 替换为你的 JSON 文件路径
        with open(json_file_path, 'r', encoding='utf-8') as file:
            dialogues:list = json.load(file)
            for dialogue in dialogues:
                dialogue["content"] = str(dialogue["content"])
            system_prompt = dialogues.copy()  #  用于后续重审 system_prompt

        with open("default_files/AI_setting.json", 'r', encoding='utf-8') as file:
            ai_settings = json.load(file)

        user_data, created = UserData.objects.get_or_create(user=request.user, key="setting", defaults={"value": json.dumps({"AI_setting_code": 4})})
        # TODO 这儿不是正确的调用方式，只是考虑到 AI 的 tool call 是直接 copy 的 moonshot，懒得改

        for ai_setting in ai_settings:
            if ai_setting["code"] == json.loads(user_data.value)["AI_setting_code"]:
                break
        else:
            logger.warning(f"AI设置代码 {json.loads(user_data.value)['AI_setting_code']} 不存在")
            return JsonResponse({'status': 'error', 'message': f"AI设置代码 {json.loads(user_data.value)['AI_setting_code']} 不存在"}, status=400)



        current_time = datetime.now()
        # 将当前时间格式化为字符串，格式为：年-月-日 时:分:秒
        time_str = current_time.strftime("%Y:%m:%d:%H:%M %A")


        preset_result, status = find_or_create_preset(prompt_scene_presets=user_preference["prompt_scene_presets"],
                                              _dialogue=dialogue_before + [{"role": "user","content": str(user_input)}],  # 这里去掉了属于这个场景
                                              user_ai_settings={"AI_setting_code": ai_setting["code"]})  # TODO 显而易见这里不该这么写，但能跑

        if status == "new_preset":
            user_preference["prompt_scene_presets"].append(preset_result)
            # TODO 还差一个 user_preference 的更新机制


        preset_result_str = (
            f"在场景【{preset_result['prompt_scene']}】相关的日程生成时，请注意：\n"
            f"我期望实现：{list_to_str(preset_result['need'])}\n"
            f"你不可以做的有：{list_to_str(preset_result['do_not'])}\n"
            f"其他补充信息：{list_to_str(preset_result['other_info'])}"
        )

        dialogues += dialogue_before
        dialogues.append({"role": "system", "content": f"我已经确定了如下日程，你在安排日程时，应该注意两个原则：\n1. 如果我要求你生成的日程与我已经规划的日程有明确关联，或有时间/空间连续性，那么你就依附于我已有的日程生成新日程\n2. 如果我要求你生成的日程与我已经规划的日程没有关联，那么你不能让我要求你生成的新日程干扰我原有的日程：{str(filtered_events)}"})
        dialogues.append({"role": "user", "content": f"{time_str}  {str(user_input)}"})
        dialogues.append({"role": "user", "content": f"{time_str} {preset_result_str}"})
        dialogues.append({"role": "system", "content": "再次重申："})
        dialogues = dialogues + system_prompt

        print(dialogues)

        # 解析AI回复
        # reply = ai_reply(dialogues, ai_setting)["response"]

        for ai_setting in ai_settings:
            if ai_setting["code"] == 3:  # TODO 这里强制设定了AI设置代码为 kimi，因为我用了 kimi 的联网搜索工具
                break

        reply = web_search_ai_reply(dialogues, ai_setting)
        # TODO 这里是联网搜索的版本，可用但有点烧钱，可以考虑本地搜索引擎。同时这里的各种逻辑还是有点问题，毕竟直接换的，也不支持别的模型。此外我会添加一个联网搜索按钮



        created_events, suggestion = parse_json_to_list_and_string(reply)



        try:
            final_suggestion = suggestion["我的建议"]
        except:
            final_suggestion = reply

        # 数据库保存AI的回复

        # 更新 dialogue
        planner_data["dialogue"] += [{
                "role": "user",
                "content": str(user_input)
            },
            {
                "role": "assistant",
                "content": reply
            }
        ]


        formated_created_events = []
        for created_event in created_events:
            formated_created_events.append({
                "id": str(uuid.uuid4()),
                "title": created_event["title"],
                "start": created_event["start"],
                "end": created_event["end"],
                "description": created_event["description"],
                "importance": created_event["importance"],
                "urgency": created_event["urgency"],
                "groupID": str(group_id),  # 存储 groupId
                "ddl": "",
                "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        # 更新 temp_events
        planner_data["temp_events"] = formated_created_events

        user_planner_data.set_value(planner_data)
        user_preference_data.set_value(user_preference)

        return JsonResponse({"suggestions": [f'注意，{none_ai_planning_time_remind}, {final_suggestion}' if none_ai_planning_time_remind else final_suggestion], "events": created_events})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

# AI生成的对话框
@csrf_exempt
@login_required
def get_previous_dialogue(request):
    if request.method == 'GET':
        # 导入历史记录
        user_data, created = UserData.objects.get_or_create(
            user=request.user,
            key="planner",
            defaults={"value": json.dumps({
                "dialogue": [],
                "temp_events": []
            })}
        )
        planner_data = json.loads(user_data.value)
        previous_dialogue = planner_data["dialogue"]
        temp_events = planner_data["temp_events"]

        formated_dialogue = []
        for message in previous_dialogue:
            if message["role"] == "user":
                formated_dialogue.append({"user": message["content"]})
            elif message["role"] == "assistant":
                formated_dialogue.append({"ai": (json.loads(message["content"]))["suggestion"]["我的建议"]})
            else:
                continue


        return JsonResponse({"dialogue": formated_dialogue, "tempEvents": temp_events})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


# 这里写的是把AI生成的临时日程合并到主数据的代码
@csrf_exempt
@login_required
def merge_temp_events(request):
    if request.method == 'POST':
        try:

            data = json.loads(request.body)
            action = data.get('action', 'save_and_end')  # 默认为 save_and_end

            user_planner_data, created, result = UserData.get_or_initialize(request, new_key="planner", data={
                    "dialogue": [],
                    "temp_events": []
                })

            user_events_data, created, result = UserData.get_or_initialize(request, new_key="events")

            user_preference_data, created, result = UserData.get_or_initialize(request, new_key="user_preference")
            user_preference = user_preference_data.get_value()


            planner_data = user_planner_data.get_value()
            temp_events = planner_data["temp_events"]
            dialogue = planner_data["dialogue"]
            ai_planning_time = planner_data["ai_planning_time"]

            events = user_events_data.get_value()
            user_events_data.set_value(events)

            # TODO 再加一个 取消之前的所有，新开一个聊天。这个同样也要作用于 ai_suggestions

            # 根据 action 执行不同的操作
            if action == 'merge_only':
                # 仅合并日程，保留会话
                events = user_events_data.get_value()
                events += temp_events
                user_events_data.set_value(events)

                dialogue.append(
                    {"role": "system",
                     "content": "用户对之前生成的日程已经满意，除非用户有要求，否则不需要再生成与之前的要求对应的日程，只关注之后的需求即可",
                     }
                )
                # 用户点那个“仅合并日程”，一般是为了开始生成新的，对之前生成的已经满意了

                user_planner_data.set_value({
                    "dialogue": dialogue,
                    "temp_events": [],
                    "ai_planning_time": ai_planning_time
                })
            elif action == 'keep_both':
                # 保留日程和会话
                # TODO 可以在这里添加其他操作，比如标记日程为草稿等

                pass
            elif action == 'save_and_end':
                # 结束对话并保存，和原来一样
                events = user_events_data.get_value()
                events += temp_events
                user_events_data.set_value(events)

                user_planner_data.set_value({
                    "dialogue": [],
                    "temp_events": [],
                    "ai_planning_time": {}
                })

                # TODO 下面粗略地实现更新用户的 prompt_scene_presets 的功能
                # TODO 这里的匹配感觉优点太模糊，我刚才试了一下，让安排考试复习日程，但是给我匹配到之前写的根据每日日程课程安排做作业了
                new_prompt_scene_presets = update_preset_with_dialogue(
                    prompt_scene_presets=user_preference["prompt_scene_presets"],
                    _dialogue=dialogue,
                    user_ai_settings={"AI_setting_code": 2})

                if new_prompt_scene_presets:
                    user_preference["prompt_scene_presets"] = new_prompt_scene_presets
                    user_preference_data.set_value(user_preference)

            else:
                return JsonResponse({'status': 'error', 'message': 'Invalid action'}, status=400)


            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)



# 用来标记一段时间，存入用户数据库，给AI规划用
@login_required
@csrf_exempt
def add_to_ai_planning_time(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            start_time = data.get('start')
            end_time = data.get('end')

            if not start_time or not end_time:
                return JsonResponse({'status': 'error', 'message': 'Missing start or end time'}, status=400)


            # 处理 start 时间
            try:
                start_time = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                for i in range(3):
                    start_time = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S")

                try:
                    date_obj = datetime.strptime(start_time, "%Y-%m-%d")
                    start_time = date_obj.replace(hour=0, minute=0, second=0)
                except (ValueError, TypeError):
                    start_time = None

            # 处理 end 时间
            try:
                end_time = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                try:
                    date_obj = datetime.strptime(end_time, "%Y-%m-%d")
                    end_time = date_obj.replace(hour=23, minute=59, second=59)
                except (ValueError, TypeError):
                    end_time = None

            user_data, created = UserData.objects.get_or_create(
                user=request.user,
                key="planner",
            )

            planner_data = json.loads(user_data.value)
            planner_data['ai_planning_time'] = {
                'start': str(start_time),
                'end': str(end_time)
            }

            user_data.value = json.dumps(planner_data)
            user_data.save()

            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


# 批量删除日程
@login_required
@csrf_exempt
def delete_events_in_range(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            start_time = data.get('start')
            end_time = data.get('end')

            if not start_time or not end_time:
                return JsonResponse({'status': 'error', 'message': 'Missing start or end time'}, status=400)

            user_data, created = UserData.objects.get_or_create(
                user=request.user,
                key="events",
                defaults={"value": json.dumps([])}
            )
            events = json.loads(user_data.value)

            # 过滤出完全在指定时间范围内的事件
            events_to_keep = [
                event for event in events
                if not (event['start'] >= start_time and event['end'] <= end_time)
            ]

            user_data.value = json.dumps(events_to_keep)
            user_data.save()

            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)





# AI回复的代码，AI_suggestion用的
def ai_reply(dialogues, ai_setting):
    try:
        client = OpenAI(
            api_key=ai_setting["api"],
            base_url=ai_setting["url"]
        )

        # 调用Kimi API进行聊天
        completion = client.chat.completions.create(
            model=ai_setting["model"],  # 你可以根据需要选择不同的模型规格
            messages=dialogues,
            temperature=ai_setting["temperature"],
            response_format={"type": "json_object"}, # <-- 使用 response_format 参数指定输出格式为 json_object
            max_tokens=16*1024
            # TODO 这里，我改以什么方式，更好地规划输出长度呢（而且DS的好像不让输出这么多）
            # TODO 需要加错误处理函数。
        )
        prompt_tokens = completion.usage.prompt_tokens
        completion_tokens = completion.usage.completion_tokens
        # 返回Kimi的回复
        return {"response": completion.choices[0].message.content, "consumption": prompt_tokens + completion_tokens}

    except Exception as e:
        print(e)
        return 0



from typing import *
# search 工具的具体实现，这里我们只需要返回参数即可
# TODO 正如上述，这里要改成自己的逻辑
def search_impl(arguments: Dict[str, Any]) -> Any:
    """
    在使用 Moonshot AI 提供的 search 工具的场合，只需要原封不动返回 arguments 即可，
    不需要额外的处理逻辑。

    但如果你想使用其他模型，并保留联网搜索的功能，那你只需要修改这里的实现（例如调用搜索
    和获取网页内容等），函数签名不变，依然是 work 的。

    这最大程度保证了兼容性，允许你在不同的模型间切换，并且不需要对代码有破坏性的修改。
    """
    return arguments


def web_chat(messages, ai_setting):

    client = OpenAI(
        api_key=ai_setting["api"],
        base_url=ai_setting["url"]
    )

    completion = client.chat.completions.create(
        model="kimi-latest",
        messages=messages,
        temperature=ai_setting["temperature"],
        response_format={"type": "json_object"}, # <-- 使用 response_format 参数指定输出格式为 json_object
        max_tokens=16*1024,
        tools=[{"type": "builtin_function", "function": {"name": "$web_search"}}]
        # TODO 这里到时候要和上面AI_reply集成，不然每次改特性都要改俩
    )
    usage = completion.usage
    choice = completion.choices[0]

    # =========================================================================
    # 通过判断 finish_reason = stop，我们将完成联网搜索流程后，消耗的 Tokens 打印出来
    if choice.finish_reason == "stop":
        logger.debug("=================联网搜索功能启用=================")
        logger.debug(f"chat_prompt_tokens:          {usage.prompt_tokens}")
        logger.debug(f"chat_completion_tokens:      {usage.completion_tokens}")
        logger.debug(f"chat_total_tokens:           {usage.total_tokens}")
        logger.debug("===============================================")
    # =========================================================================

    return choice


def web_search_ai_reply(messages, ai_setting):

    finish_reason = None
    while finish_reason is None or finish_reason == "tool_calls":
        choice = web_chat(messages, ai_setting)
        finish_reason = choice.finish_reason
        if finish_reason == "tool_calls":  # <-- 判断当前返回内容是否包含 tool_calls
            messages.append(choice.message)  # <-- 我们将 Kimi 大模型返回给我们的 assistant 消息也添加到上下文中，以便于下次请求时 Kimi 大模型能理解我们的诉求
            for tool_call in choice.message.tool_calls:  # <-- tool_calls 可能是多个，因此我们使用循环逐个执行
                tool_call_name = tool_call.function.name
                tool_call_arguments = json.loads(tool_call.function.arguments)  # <-- arguments 是序列化后的 JSON Object，我们需要使用 json.loads 反序列化一下
                if tool_call_name == "$web_search":
                    tool_result = search_impl(tool_call_arguments)
                else:
                    tool_result = f"Error: unable to find tool by name '{tool_call_name}'"

                # 使用函数执行结果构造一个 role=tool 的 message，以此来向模型展示工具调用的结果；
                # 注意，我们需要在 message 中提供 tool_call_id 和 name 字段，以便 Kimi 大模型
                # 能正确匹配到对应的 tool_call。
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call_name,
                    "content": json.dumps(tool_result),  # <-- 我们约定使用字符串格式向 Kimi 大模型提交工具调用结果，因此在这里使用 json.dumps 将执行结果序列化成字符串
                })
    return choice.message.content






@login_required
def get_temp_long_events(request):
    if request.method == 'GET':

        # user_events_data, created = UserData.objects.get_or_create(user=request.user, key="events")
        # user_temp_events_data, created = UserData.objects.get_or_create(user=request.user, key="planner", defaults=
        # {"value": json.dumps()})

        user_events_data, created, result = UserData.get_or_initialize(request=request, new_key="events")
        user_temp_events_data: 'UserData'
        user_temp_events_data, created, result =UserData.get_or_initialize(request=request, new_key="planner", data={
            "dialogue": [],
            "temp_events": [],
            "ai_planning_time": {}
        })

        planner_data = user_temp_events_data.get_value(check=False)

        temp_events = planner_data["temp_events"]
        events = user_events_data.get_value()

        temp_events = [{**temp_event, "title": temp_event["title"] + "(temp)"} for temp_event in temp_events]

        all_events = temp_events + events


        # 获取用户的所有日程组
        user_data_groups, created = UserData.objects.get_or_create(user=request.user, key="events_groups")
        events_groups = json.loads(user_data_groups.value)

        if not all_events:
            all_events = []
        # 返回事件和日程组数据
        if not events_groups:
            events_groups = []

            # 返回事件和日程组数据
        return JsonResponse({"events": all_events, "events_groups": events_groups, "ai_planning_time": planner_data["ai_planning_time"]})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)



from datetime import datetime, timedelta

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
                utc_time = datetime.fromisoformat(event[key].replace('Z', '+00:00'))
                local_time = utc_time - timedelta(hours=-8)
                # 格式化为本地时间格式
                event[key] = local_time.strftime('%Y-%m-%dT%H:%M')
    return events


def parse_json_to_list_and_string(json_str):
    """
    将 JSON 格式的字符串转换为一个列表和一个字符串。
    :param json_str: JSON 格式的字符串
    :return: 一个包含日程项的列表和一个建议字符串
    """
    try:
        # 解析 JSON 字符串为字典
        data = json.loads(json_str)

        # 提取日程项
        schedule_list = [item for key, item in data.items() if key.isdigit()]

        # 提取建议部分
        suggestion = data.get("suggestion", "")

        return schedule_list, suggestion
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析错误: {e}")
        return None, None



