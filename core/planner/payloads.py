"""日历事件扩展 Payload 的注册表、结构校验与基础 JSON Schema 校验。

本模块只负责“存储前的基础检查”，不理解任何注册方的业务字段；未知注册名
与未知格式一律透传保留，避免扩展数据破坏核心日历模型。
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from django.conf import settings

SCHEMA_DIR = Path(__file__).resolve().with_name('payload_schemas')

# 注册名建议使用域名倒序形式，例如 org.uss.scheduler。
_KEY_PATTERN = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$')
_FORMAT_PATTERN = re.compile(r'^[a-z][a-z0-9.+-]{0,31}$')
_ENTRY_FIELDS = frozenset({'format', 'data', 'version'})

_LIMIT_DEFAULTS = {
    'PLANNER_EVENT_PAYLOAD_MAX_KEYS': 16,
    'PLANNER_EVENT_PAYLOAD_MAX_TOTAL_BYTES': 64 * 1024,
    'PLANNER_EVENT_PAYLOAD_MAX_ENTRY_BYTES': 32 * 1024,
    'PLANNER_EVENT_PAYLOAD_MAX_KEY_LENGTH': 128,
}


class PayloadValidationError(ValueError):
    """可映射为 v2 422 的 Payload 基础校验错误。"""

    def __init__(self, message: str, *, code: str = 'invalid_payload'):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PayloadRegistration:
    """统一注册名表中的一条登记。"""

    key: str
    owner: str
    description: str
    formats: tuple[str, ...] = ('json',)
    schema_filename: str | None = None
    schema_version: int = 1

    @property
    def schema(self) -> Mapping[str, Any] | None:
        return _load_schema(self.schema_filename) if self.schema_filename else None


@lru_cache(maxsize=None)
def _load_schema(filename: str) -> Mapping[str, Any]:
    """按文件加载 JSON Schema；文件缺失属于部署错误，直接暴露给开发者。"""
    path = SCHEMA_DIR / filename
    try:
        with path.open('r', encoding='utf-8') as handle:
            schema = json.load(handle)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f'Payload schema 无法加载: {path}') from exc
    if not isinstance(schema, Mapping):
        raise RuntimeError(f'Payload schema 必须是 JSON object: {path}')
    return schema


# 统一注册名表。新增注册方时必须同时补充 schema 文件与
# docs/日历事件Payload机制.md 的登记表，并走代码评审。
_PAYLOAD_REGISTRATIONS: dict[str, PayloadRegistration] = {
    registration.key: registration
    for registration in (
        PayloadRegistration(
            key='org.uss.scheduler',
            owner='UniSchedulerSuper',
            description='USS 保留的日程扩展负载，首期要求 data 为 JSON object。',
            formats=('json',),
            schema_filename='org.uss.scheduler.json',
            schema_version=1,
        ),
    )
}


def get_payload_registration(key: str) -> PayloadRegistration | None:
    """返回注册信息；未知注册名返回 None，由调用方透传保留。"""
    return _PAYLOAD_REGISTRATIONS.get(key)


def list_payload_registrations() -> tuple[PayloadRegistration, ...]:
    """按注册名排序返回全部登记，供文档/测试和后续管理接口复用。"""
    return tuple(_PAYLOAD_REGISTRATIONS[key] for key in sorted(_PAYLOAD_REGISTRATIONS))


def normalize_event_payload(raw: Any) -> dict[str, Any]:
    """校验并归一化事件 payload；未知 Key/格式保留，不做业务解释。"""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise PayloadValidationError('payload 必须是 JSON object', code='invalid_payload')

    max_keys = _int_setting('PLANNER_EVENT_PAYLOAD_MAX_KEYS')
    max_total_bytes = _int_setting('PLANNER_EVENT_PAYLOAD_MAX_TOTAL_BYTES')
    max_entry_bytes = _int_setting('PLANNER_EVENT_PAYLOAD_MAX_ENTRY_BYTES')
    max_key_length = _int_setting('PLANNER_EVENT_PAYLOAD_MAX_KEY_LENGTH')

    if len(raw) > max_keys:
        raise PayloadValidationError(
            f'payload 最多允许 {max_keys} 个注册名', code='payload_too_large'
        )

    normalized: dict[str, Any] = {}
    for key, entry in raw.items():
        if not isinstance(key, str):
            raise PayloadValidationError('payload 的 Key 必须是字符串', code='payload_key_invalid')
        if not key or len(key) > max_key_length or not _KEY_PATTERN.fullmatch(key):
            raise PayloadValidationError(
                f'payload Key 格式无效或超过 {max_key_length} 字符: {key[:64]!r}',
                code='payload_key_invalid',
            )
        normalized[key] = _normalize_entry(key, entry, max_entry_bytes=max_entry_bytes)

    total_bytes = _json_size_bytes(normalized)
    if total_bytes > max_total_bytes:
        raise PayloadValidationError(
            f'payload 总大小 {total_bytes} 字节超过限制 {max_total_bytes} 字节',
            code='payload_too_large',
        )
    return normalized


def _normalize_entry(key: str, entry: Any, *, max_entry_bytes: int) -> dict[str, Any]:
    if not isinstance(entry, Mapping):
        raise PayloadValidationError(
            f'payload[{key}] 必须是包含 format/data 的 JSON object', code='payload_entry_invalid'
        )
    extra = set(entry) - _ENTRY_FIELDS
    if extra:
        raise PayloadValidationError(
            f'payload[{key}] 包含不支持的字段: {", ".join(sorted(map(str, extra)))}',
            code='payload_entry_invalid',
        )

    raw_format = entry.get('format')
    if not isinstance(raw_format, str) or not raw_format.strip():
        raise PayloadValidationError(
            f'payload[{key}].format 必须是非空字符串', code='payload_entry_invalid'
        )
    payload_format = raw_format.strip().lower()
    if not _FORMAT_PATTERN.fullmatch(payload_format):
        raise PayloadValidationError(
            f'payload[{key}].format 格式无效: {raw_format[:32]!r}', code='payload_entry_invalid'
        )
    if 'data' not in entry:
        raise PayloadValidationError(
            f'payload[{key}] 缺少 data', code='payload_entry_invalid'
        )

    try:
        data = copy.deepcopy(entry['data'])
    except RecursionError as exc:
        raise PayloadValidationError(
            f'payload[{key}].data 嵌套层级过深', code='invalid_payload_data'
        ) from exc
    result: dict[str, Any] = {
        'format': payload_format,
        'data': data,
    }
    if 'version' in entry:
        version = entry['version']
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise PayloadValidationError(
                f'payload[{key}].version 必须是正整数', code='payload_entry_invalid'
            )
        result['version'] = version

    entry_bytes = _json_size_bytes(result)
    if entry_bytes > max_entry_bytes:
        raise PayloadValidationError(
            f'payload[{key}] 大小 {entry_bytes} 字节超过限制 {max_entry_bytes} 字节',
            code='payload_too_large',
        )

    registration = get_payload_registration(key)
    # 只对“已注册且声明支持 json”的 Key 执行 schema 校验；未知格式透传。
    if registration is not None and payload_format in registration.formats:
        schema = registration.schema
        if schema is not None:
            errors = validate_json_schema(result['data'], schema)
            if errors:
                preview = '; '.join(errors[:3])
                remainder = '' if len(errors) <= 3 else f'（共 {len(errors)} 项）'
                raise PayloadValidationError(
                    f'payload[{key}] 不符合注册 schema: {preview}{remainder}',
                    code='payload_schema_violation',
                )
    return result


def _int_setting(name: str) -> int:
    default = _LIMIT_DEFAULTS[name]
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def _json_size_bytes(value: Any) -> int:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(',', ':'), allow_nan=False
        ).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise PayloadValidationError('payload 必须是合法 JSON 数据', code='invalid_payload_data') from exc
    return len(encoded)


def validate_json_schema(value: Any, schema: Mapping[str, Any]) -> list[str]:
    """校验 JSON Schema 的受支持子集，返回可读错误列表。

    支持 type/properties/required/additionalProperties/items、enum/const、
    allOf/anyOf/oneOf/not、字符串与数值边界、数组/对象数量约束，以及本地
    ``#/$defs``、``#/definitions`` 引用。``format`` 关键字仅作为文档，不执行
    日期/邮箱等语义校验，避免引入额外依赖。
    """
    errors: list[str] = []
    _validate_schema(value, schema, path='$', root=schema, errors=errors, depth=0)
    return errors


def _validate_schema(
    value: Any,
    schema: Any,
    *,
    path: str,
    root: Mapping[str, Any],
    errors: list[str],
    depth: int,
) -> None:
    if depth > 64:
        errors.append(f'{path}: schema 引用层级过深')
        return
    if schema is True or schema is None:
        return
    if schema is False:
        errors.append(f'{path}: 不允许任何值')
        return
    if not isinstance(schema, Mapping):
        errors.append(f'{path}: schema 节点必须是 object 或 boolean')
        return

    if '$ref' in schema:
        resolved = _resolve_local_ref(root, str(schema['$ref']))
        if resolved is None:
            errors.append(f'{path}: 无法解析 schema 引用 {schema["$ref"]}')
        else:
            _validate_schema(value, resolved, path=path, root=root, errors=errors, depth=depth + 1)
        return

    expected_types = schema.get('type')
    if expected_types is not None and not _matches_type(value, expected_types):
        errors.append(
            f'{path}: 类型应为 {_format_types(expected_types)}，实际为 {_json_type_name(value)}'
        )
        return

    if 'enum' in schema and not any(_json_equal(value, item) for item in schema['enum']):
        errors.append(f'{path}: 值不在 enum 允许范围内')
    if 'const' in schema and not _json_equal(value, schema['const']):
        errors.append(f'{path}: 值必须等于 const')

    for sub_schema in schema.get('allOf', ()) or ():
        _validate_schema(value, sub_schema, path=path, root=root, errors=errors, depth=depth + 1)
    if 'anyOf' in schema:
        branches = schema.get('anyOf') or ()
        branch_errors = [
            _collect_errors(value, item, path=path, root=root, depth=depth + 1)
            for item in branches
        ]
        if branches and all(item for item in branch_errors):
            errors.append(f'{path}: anyOf 至少需要一个分支通过')
    if 'oneOf' in schema:
        branches = schema.get('oneOf') or ()
        passed = [
            not _collect_errors(value, item, path=path, root=root, depth=depth + 1)
            for item in branches
        ]
        if len([item for item in passed if item]) != 1:
            errors.append(f'{path}: oneOf 必须且只能有一个分支通过')
    if 'not' in schema:
        if not _collect_errors(value, schema['not'], path=path, root=root, depth=depth + 1):
            errors.append(f'{path}: 值不能匹配 not schema')

    if isinstance(value, Mapping):
        _validate_object(value, schema, path=path, root=root, errors=errors, depth=depth)
    elif isinstance(value, list):
        _validate_array(value, schema, path=path, root=root, errors=errors, depth=depth)
    elif isinstance(value, str):
        _validate_string(value, schema, path=path, errors=errors)
    elif _is_number(value):
        _validate_number(value, schema, path=path, errors=errors)


def _validate_object(
    value: Mapping[Any, Any],
    schema: Mapping[str, Any],
    *,
    path: str,
    root: Mapping[str, Any],
    errors: list[str],
    depth: int,
) -> None:
    properties = schema.get('properties') or {}
    required = schema.get('required') or ()
    pattern_properties = schema.get('patternProperties') or {}
    for name in required:
        if name not in value:
            errors.append(f'{path}: 缺少必填字段 {name}')
    if 'minProperties' in schema and len(value) < int(schema['minProperties']):
        errors.append(f'{path}: 字段数量少于 {schema["minProperties"]}')
    if 'maxProperties' in schema and len(value) > int(schema['maxProperties']):
        errors.append(f'{path}: 字段数量多于 {schema["maxProperties"]}')
    for name, item in value.items():
        child_path = f'{path}.{name}'
        if name in properties:
            _validate_schema(item, properties[name], path=child_path, root=root, errors=errors, depth=depth + 1)
            continue
        matched_pattern = False
        for pattern, pattern_schema in pattern_properties.items():
            if _safe_search(pattern, str(name)):
                matched_pattern = True
                _validate_schema(
                    item, pattern_schema, path=child_path, root=root, errors=errors, depth=depth + 1
                )
        if matched_pattern:
            continue
        if 'additionalProperties' in schema:
            additional = schema['additionalProperties']
            if additional is False:
                errors.append(f'{path}: 不允许额外字段 {name}')
            elif additional is not True:
                _validate_schema(
                    item, additional, path=child_path, root=root, errors=errors, depth=depth + 1
                )


def _validate_array(
    value: list[Any],
    schema: Mapping[str, Any],
    *,
    path: str,
    root: Mapping[str, Any],
    errors: list[str],
    depth: int,
) -> None:
    if 'minItems' in schema and len(value) < int(schema['minItems']):
        errors.append(f'{path}: 元素数量少于 {schema["minItems"]}')
    if 'maxItems' in schema and len(value) > int(schema['maxItems']):
        errors.append(f'{path}: 元素数量多于 {schema["maxItems"]}')
    if schema.get('uniqueItems') is True:
        seen: list[Any] = []
        for index, item in enumerate(value):
            if any(_json_equal(item, other) for other in seen):
                errors.append(f'{path}[{index}]: 数组元素必须唯一')
            else:
                seen.append(item)
    items = schema.get('items')
    if items is not None:
        for index, item in enumerate(value):
            _validate_schema(
                item, items, path=f'{path}[{index}]', root=root, errors=errors, depth=depth + 1
            )


def _validate_string(value: str, schema: Mapping[str, Any], *, path: str, errors: list[str]) -> None:
    if 'minLength' in schema and len(value) < int(schema['minLength']):
        errors.append(f'{path}: 长度少于 {schema["minLength"]}')
    if 'maxLength' in schema and len(value) > int(schema['maxLength']):
        errors.append(f'{path}: 长度多于 {schema["maxLength"]}')
    if 'pattern' in schema and not _safe_search(str(schema['pattern']), value):
        errors.append(f'{path}: 不匹配 pattern {schema["pattern"]}')


def _validate_number(value: int | float, schema: Mapping[str, Any], *, path: str, errors: list[str]) -> None:
    if 'minimum' in schema and value < schema['minimum']:
        errors.append(f'{path}: 小于 minimum {schema["minimum"]}')
    if 'maximum' in schema and value > schema['maximum']:
        errors.append(f'{path}: 大于 maximum {schema["maximum"]}')
    if 'exclusiveMinimum' in schema and value <= schema['exclusiveMinimum']:
        errors.append(f'{path}: 必须大于 {schema["exclusiveMinimum"]}')
    if 'exclusiveMaximum' in schema and value >= schema['exclusiveMaximum']:
        errors.append(f'{path}: 必须小于 {schema["exclusiveMaximum"]}')


def _collect_errors(
    value: Any,
    schema: Any,
    *,
    path: str,
    root: Mapping[str, Any],
    depth: int,
) -> list[str]:
    nested: list[str] = []
    _validate_schema(value, schema, path=path, root=root, errors=nested, depth=depth)
    return nested


def _resolve_local_ref(root: Mapping[str, Any], reference: str) -> Any:
    if reference in {'#', ''}:
        return root
    if not reference.startswith('#/'):
        return None
    current: Any = root
    for raw_part in reference[2:].split('/'):
        part = raw_part.replace('~1', '/').replace('~0', '~')
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _safe_search(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _matches_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, str):
        expected = [expected]
    if not isinstance(expected, (list, tuple)):
        return True
    return any(_matches_single_type(value, item) for item in expected)


def _matches_single_type(value: Any, expected: Any) -> bool:
    if expected == 'object':
        return isinstance(value, Mapping)
    if expected == 'array':
        return isinstance(value, list)
    if expected == 'string':
        return isinstance(value, str)
    if expected == 'number':
        return _is_number(value)
    if expected == 'integer':
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer()
        )
    if expected == 'boolean':
        return isinstance(value, bool)
    if expected == 'null':
        return value is None
    return True


def _format_types(expected: Any) -> str:
    return '/'.join(str(item) for item in expected) if isinstance(expected, (list, tuple)) else str(expected)


def _json_type_name(value: Any) -> str:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, Mapping):
        return 'object'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    return type(value).__name__


def _json_equal(left: Any, right: Any) -> bool:
    """按 JSON 语义比较，避免 Python 把 True 与 1 视为相等。"""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if _is_number(left) or _is_number(right):
        return _is_number(left) and _is_number(right) and left == right
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right
