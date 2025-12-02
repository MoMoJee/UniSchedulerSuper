import json
import logging
import difflib
from functools import wraps
from django.http import JsonResponse
from rest_framework.request import Request as DRFRequest

from logger import logger

def validate_body(schema, strict=True):
    """
    请求体参数验证装饰器。
    用于验证 JSON 请求体中的参数，支持类型检查、必填检查、默认值、枚举值检查、别名映射以及智能错误提示。

    :param schema: 验证规则字典。
        Key 是后端视图函数中使用的变量名。
        Value 是一个配置字典，支持以下字段：
        - 'type': (type) 期望的数据类型，如 str, int, list, dict 等。
        - 'required': (bool) 是否必填。默认为 False。
        - 'default': (any) 默认值。当 required=False 且前端未传该参数时使用。
        - 'choices': (list) 枚举值列表。限制参数值必须在此列表中。
          示例: 'choices': ['pending', 'done']
        - 'alias': (str) 前端参数别名。允许前端传递与后端变量名不同的参数名。
          示例: 后端用 'group_id'，前端传 'groupID'，则配置 'alias': 'groupID'。
          验证器会自动从请求中读取 'groupID' 的值并赋给 'group_id'。
        - 'synonyms': (list) 同义词/近义词列表。用于在严格模式下提供更智能的错误提示。
          示例: 'synonyms': ['context', 'detail']。如果前端误传了 'context'，会提示是否想用该字段。

    :param strict: (bool) 是否开启严格模式，默认 True。
        开启后，如果请求体中包含了 schema 中未定义（且不是 alias）的参数，API 将返回 400 错误。
        错误信息会包含智能拼写建议（基于 synonyms 和字段名相似度）。
    """
    readable_schema = {}
    for field, rules in schema.items():
        field_desc = {}
        t = rules.get('type')
        if t:
            if isinstance(t, tuple):
                field_desc['type'] = ' | '.join([x.__name__ for x in t])
            elif isinstance(t, type):
                field_desc['type'] = t.__name__
            else:
                field_desc['type'] = str(t)
        
        if rules.get('required'):
            field_desc['required'] = True
        else:
            field_desc['required'] = False
            if 'default' in rules:
                field_desc['default'] = rules['default']
        
        if 'choices' in rules:
            field_desc['choices'] = rules['choices']
            
        if 'comment' in rules:
            field_desc['comment'] = rules['comment']
            
        if 'alias' in rules:
            field_desc['alias'] = rules['alias']
            display_key = f"{field} (alias: {rules['alias']})"
        else:
            display_key = field
            
        readable_schema[display_key] = field_desc

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # 辅助函数：生成包含 schema 的错误响应
            def make_error_response(msg):
                return JsonResponse({
                    'status': 'error',
                    'message': msg,
                    'expected_schema': readable_schema
                }, status=400, json_dumps_params={'ensure_ascii': False})

            # 1. 获取请求数据
            data = {}
            try:
                # 兼容 DRF Request 和原生 Django Request
                if hasattr(request, 'data') and isinstance(request.data, dict) and request.data:
                    data = request.data
                elif request.body:
                    data = json.loads(request.body)
            except json.JSONDecodeError:
                return make_error_response('Invalid JSON format')
            except Exception as e:
                logger.error(f"Data parsing error: {e}")
                return make_error_response('Data parsing error')

            # 2. 严格模式检查：检查是否存在未定义的参数
            if strict:
                # 获取所有允许的输入字段名 (包括 schema keys 和 alias)
                allowed_fields = set()
                for field, rules in schema.items():
                    allowed_fields.add(field)
                    if 'alias' in rules:
                        allowed_fields.add(rules['alias'])
                
                unknown_fields = set(data.keys()) - allowed_fields
                
                if unknown_fields:
                    error_msgs = []
                    for unknown in unknown_fields:
                        msg = f"参数 '{unknown}' 是多余的"
                        suggestion = None

                        # 策略 A: 检查是否命中某个字段定义的同义词 (synonyms)
                        # 优先检查精确匹配同义词，再检查模糊匹配同义词
                        for field, rules in schema.items():
                            synonyms = rules.get('synonyms', [])
                            if not synonyms:
                                continue
                            
                            # A1. 精确匹配同义词
                            if unknown in synonyms:
                                suggestion = field
                                break
                            
                            # A2. 模糊匹配同义词
                            # 如果 unknown 拼写错误，但接近某个同义词 (例如 'contxt' 接近 'context')
                            if difflib.get_close_matches(unknown, synonyms, n=1, cutoff=0.7):
                                suggestion = field
                                break
                        
                        # 策略 B: 如果没有命中同义词，检查是否模糊匹配标准字段名 (原有逻辑)
                        if not suggestion:
                            matches = difflib.get_close_matches(unknown, list(allowed_fields), n=1, cutoff=0.6)
                            if matches:
                                suggestion = matches[0]
                        
                        if suggestion:
                            msg += f"，您是否想用 '{suggestion}'?"
                        error_msgs.append(msg)
                    
                    return make_error_response('; '.join(error_msgs))

            validated_data = {}
            errors = []

            # 3. 根据 schema 验证数据
            for field, rules in schema.items():
                # 处理别名（例如前端传 groupID，后端想用 group_id）
                # 优先尝试获取 alias 指定的参数名，如果未传则尝试获取原始参数名
                alias = rules.get('alias')
                value = None
                input_field_used = field

                if alias and alias in data:
                    value = data[alias]
                    input_field_used = alias
                elif field in data:
                    value = data[field]
                    input_field_used = field
                
                # 检查必填
                if rules.get('required', False) and value is None:
                    # 如果值为空字符串且不允许为空，也算缺失（视具体业务而定，这里暂定 None 为缺失）
                    # 如果需要严格检查空字符串，可以加 if value in [None, '']:
                    # 报错时优先提示 alias (如果存在)
                    display_name = alias if alias else field
                    errors.append(f"缺少必填参数: {display_name}")
                    continue

                # 设置默认值
                if value is None:
                    if 'default' in rules:
                        value = rules['default']
                    else:
                        # 非必填且无默认值，跳过后续检查
                        continue

                # 检查类型
                expected_type = rules.get('type')
                if expected_type:
                    # 特殊处理：如果期望是 float 但传入了 int，通常是可以接受的
                    if expected_type == float and isinstance(value, int):
                        value = float(value)
                    elif not isinstance(value, expected_type):
                        errors.append(f"参数 {input_field_used} 类型错误，应为 {expected_type.__name__}")
                        continue

                # 检查枚举值
                choices = rules.get('choices')
                if choices and value not in choices:
                    errors.append(f"参数 {input_field_used} 的值无效，可选值: {choices}")
                    continue

                # 将清洗后的数据存入 validated_data
                # 使用 schema 定义的 key，而不是 alias
                validated_data[field] = value

            if errors:
                return make_error_response('; '.join(errors))

            # 3. 将验证后的数据注入 request 对象，方便视图函数直接使用
            # 避免视图函数再次解析 json
            request.validated_data = validated_data
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
