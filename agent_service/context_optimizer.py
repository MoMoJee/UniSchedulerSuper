"""
Token 计算和上下文优化模块

功能:
1. Token 计算 (actual/tiktoken/estimate)
2. 工具输出压缩
3. 动态上下文构建

Author: Agent Service
Created: 2026-01-02
"""

import json
import logging
from typing import List, Optional, Dict, Any, Tuple
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage

from logger import logger


class TokenCalculator:
    """
    Token 计算器

    支持三种计算方式（按优先级）:
    1. actual: 从 LangGraph response_metadata 读取实际值
    2. tiktoken: 使用 tiktoken 库精确计算
    3. estimate: 粗略估算 (1 token ≈ 2.5 字符)
    """

    def __init__(self, method: str = "actual", model: str = "gpt-3.5-turbo"):
        """
        初始化 Token 计算器

        Args:
            method: 计算方式 ("actual", "tiktoken", "estimate")
            model: 模型名称 (用于 tiktoken)
        """
        self.method = method
        self.model = model
        self._tiktoken_encoder = None

    def _get_tiktoken_encoder(self):
        """懒加载 tiktoken encoder"""
        if self._tiktoken_encoder is None:
            try:
                import tiktoken
                try:
                    self._tiktoken_encoder = tiktoken.encoding_for_model(self.model)
                except KeyError:
                    # 如果模型不支持，使用 cl100k_base (GPT-4 系列)
                    self._tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
            except ImportError:
                logger.warning("tiktoken not installed, falling back to estimate method")
                self.method = "estimate"
                return None
        return self._tiktoken_encoder

    def calculate_text(self, text: str) -> int:
        """
        计算文本的 token 数

        Args:
            text: 要计算的文本

        Returns:
            token 数量
        """
        if not text:
            return 0

        if self.method == "tiktoken":
            encoder = self._get_tiktoken_encoder()
            if encoder:
                return len(encoder.encode(text))

        # 粗略估算: 1 token ≈ 2.5 字符 (中英混合)
        # 英文约 4 字符/token，中文约 1.5 字符/token
        return int(len(text) / 2.5)

    def calculate_message(self, message: BaseMessage) -> int:
        """
        计算单条消息的 token 数

        Args:
            message: LangChain 消息

        Returns:
            token 数量
        """
        content = message.content if isinstance(message.content, str) else str(message.content)
        tokens = self.calculate_text(content)

        # 消息元数据开销 (role, name 等)
        tokens += 4  # 每条消息大约 4 tokens 开销

        # 工具调用额外开销
        if isinstance(message, AIMessage) and message.tool_calls:
            for tool_call in message.tool_calls:
                tokens += self.calculate_text(tool_call.get("name", ""))
                tokens += self.calculate_text(json.dumps(tool_call.get("args", {}), ensure_ascii=False))

        return tokens

    def calculate_messages(self, messages: List[BaseMessage], usage: Optional[Dict] = None) -> int:
        """
        计算消息列表的 token 数

        Args:
            messages: 消息列表
            usage: LangGraph 返回的 usage 信息 (用于 actual 模式)

        Returns:
            token 数量
        """
        # 优先使用实际统计
        if self.method == "actual" and usage:
            prompt_tokens = usage.get('prompt_tokens', 0)
            if prompt_tokens > 0:
                return prompt_tokens

        # 累加计算
        total = 0
        for msg in messages:
            total += self.calculate_message(msg)

        # 对话格式开销
        total += 3  # 开始和结束标记

        return total

    def calculate_from_response_metadata(self, metadata: Dict) -> Dict[str, int]:
        """
        从 LangGraph 响应元数据中提取 token 使用信息

        Args:
            metadata: response_metadata

        Returns:
            {"prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ...}
        """
        usage = metadata.get('usage', {})
        return {
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'total_tokens': usage.get('total_tokens', 0),
        }


class ToolMessageCompressor:
    """
    工具消息压缩器

    功能:
    1. 检测工具输出是否超过阈值
    2. 智能压缩 JSON 格式的输出
    3. 保留关键信息（成功/失败、数量、首尾项）
    """

    def __init__(self, max_tokens: int = 200, exclude_tools: Optional[List[str]] = None):
        """
        初始化压缩器

        Args:
            max_tokens: 工具输出的最大 token 数
            exclude_tools: 不压缩的工具名称列表
        """
        self.max_tokens = max_tokens
        self.exclude_tools = exclude_tools or []

    def compress(self, message: ToolMessage, calculator: TokenCalculator) -> ToolMessage:
        """
        压缩工具消息

        Args:
            message: 原始工具消息
            calculator: Token 计算器

        Returns:
            压缩后的工具消息（或原消息如果不需要压缩）
        """
        tool_name = message.name if hasattr(message, 'name') else ""

        # 检查是否在排除列表中
        if tool_name in self.exclude_tools:
            return message

        content = message.content
        if not content:
            return message

        # 确保 content 是字符串
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)

        # 计算当前 token 数
        current_tokens = calculator.calculate_text(content)

        # 不需要压缩
        if current_tokens <= self.max_tokens:
            return message

        # 尝试压缩
        compressed_content = self._compress_content(content, tool_name or "", self.max_tokens, calculator)

        # 创建新的压缩消息
        return ToolMessage(
            content=compressed_content,
            tool_call_id=message.tool_call_id,
            name=tool_name,
            additional_kwargs={
                **message.additional_kwargs,
                'compressed': True,
                'original_tokens': current_tokens
            }
        )

    def _compress_content(
        self,
        content: str,
        tool_name: str,
        max_tokens: int,
        calculator: TokenCalculator
    ) -> str:
        """
        压缩工具输出内容

        压缩策略:
        1. 解析 JSON，提取关键信息
        2. 保留列表的首尾项
        3. 截断过长的字符串
        """
        # 尝试解析 JSON
        try:
            data = json.loads(content)
            return self._compress_json(data, tool_name, max_tokens, calculator)
        except json.JSONDecodeError:
            pass

        # 非 JSON，直接截断
        return self._truncate_text(content, max_tokens, calculator)

    def _compress_json(
        self,
        data: Any,
        tool_name: str,
        max_tokens: int,
        calculator: TokenCalculator
    ) -> str:
        """压缩 JSON 数据"""

        # 检测常见的搜索结果格式
        if isinstance(data, dict):
            # 格式 1: {"items": [...], "total": N}
            if 'items' in data and isinstance(data['items'], list):
                items = data['items']
                total = data.get('total', len(items))
                return self._compress_list_result(items, total, tool_name)

            # 格式 2: {"success": true, "data": [...]}
            if 'data' in data and isinstance(data['data'], list):
                items = data['data']
                success = data.get('success', True)
                return self._compress_list_result(items, len(items), tool_name, success)

            # 格式 3: {"events": [...]} 或 {"todos": [...]}
            for key in ['events', 'todos', 'reminders', 'results', 'groups']:
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    return self._compress_list_result(items, len(items), tool_name)

        # 格式 4: 直接是列表
        if isinstance(data, list):
            return self._compress_list_result(data, len(data), tool_name)

        # 其他 JSON，保留结构但截断值
        compressed = self._truncate_json_values(data, max_tokens, calculator)
        return json.dumps(compressed, ensure_ascii=False, indent=None)

    def _compress_list_result(
        self,
        items: List,
        total: int,
        tool_name: str,
        success: bool = True
    ) -> str:
        """压缩列表结果"""
        if not items:
            return json.dumps({
                "success": success,
                "message": f"查询成功，共 0 条结果",
                "items": []
            }, ensure_ascii=False)

        # 保留首尾各 2 项
        if len(items) <= 4:
            kept_items = items
        else:
            kept_items = items[:2] + [{"...": f"省略 {len(items) - 4} 条..."}] + items[-2:]

        # 简化每个项目
        simplified_items = []
        for item in kept_items:
            if isinstance(item, dict):
                # 保留关键字段
                key_fields = ['id', 'search_index', 'title', 'name', 'type', 'start', 'status']
                simplified = {k: v for k, v in item.items() if k in key_fields}
                if not simplified:
                    simplified = {k: str(v)[:50] for k, v in list(item.items())[:3]}
                simplified_items.append(simplified)
            else:
                simplified_items.append(item)

        return json.dumps({
            "success": success,
            "message": f"查询成功，共 {total} 条结果" + (f"（已压缩显示 {len(simplified_items)} 条）" if total > 4 else ""),
            "items": simplified_items
        }, ensure_ascii=False)

    def _truncate_text(self, text: str, max_tokens: int, calculator: TokenCalculator) -> str:
        """截断文本到指定 token 数"""
        # 估算每个 token 的字符数
        chars_per_token = 2.5
        max_chars = int(max_tokens * chars_per_token)

        if len(text) <= max_chars:
            return text

        # 保留开头和结尾
        half = max_chars // 2 - 20
        return text[:half] + f"\n...[已截断 {len(text) - max_chars} 字符]...\n" + text[-half:]

    def _truncate_json_values(
        self,
        data: Any,
        max_tokens: int,
        calculator: TokenCalculator,
        depth: int = 0
    ) -> Any:
        """递归截断 JSON 值"""
        if depth > 3:  # 最大递归深度
            return "..."

        if isinstance(data, str):
            if len(data) > 100:
                return data[:100] + "..."
            return data

        if isinstance(data, dict):
            return {k: self._truncate_json_values(v, max_tokens, calculator, depth + 1)
                    for k, v in list(data.items())[:10]}  # 最多保留 10 个 key

        if isinstance(data, list):
            if len(data) > 5:
                return [self._truncate_json_values(data[0], max_tokens, calculator, depth + 1),
                        {"...": f"省略 {len(data) - 2} 项"},
                        self._truncate_json_values(data[-1], max_tokens, calculator, depth + 1)]
            return [self._truncate_json_values(item, max_tokens, calculator, depth + 1)
                    for item in data]

        return data


# ===== 系统预置模型配置 =====

SYSTEM_MODELS = {
    'system_deepseek': {
        'name': 'DeepSeek Chat（系统提供）',
        'provider': 'system',
        'api_url': 'https://api.deepseek.com/v1/chat/completions',
        'api_key_env': 'DEEPSEEK_API_KEY',  # 从环境变量读取
        'context_window': 128000,
        'supports_tools': True,
        'cost_per_1k_input': 0.00014,  # 美元
        'cost_per_1k_output': 0.00028,
        'readonly': True,
    },
    # 可以添加更多系统预置模型
    # 'system_gpt4': {
    #     'name': 'GPT-4 Turbo（系统提供）',
    #     'provider': 'system',
    #     ...
    # },
}


def get_system_models() -> Dict[str, Dict]:
    """获取系统预置模型列表"""
    return SYSTEM_MODELS.copy()


def get_all_models(user) -> Dict[str, Dict]:
    """
    获取用户可用的所有模型（系统 + 自定义）

    Args:
        user: Django User 对象

    Returns:
        模型字典 {model_id: model_config}
    """
    from core.models import UserData
    from config.encryption import SecureKeyStorage

    # 系统模型
    all_models = get_system_models()

    # 用户自定义模型
    try:
        agent_config_data = UserData.objects.filter(user=user, key='agent_config').first()
        if agent_config_data:
            config = agent_config_data.get_value()
            # 解密配置中的 API 密钥
            config = SecureKeyStorage.decrypt_model_config(config, user.id)
            custom_models = config.get('custom_models', {})
            for model_id, model_config in custom_models.items():
                all_models[model_id] = {
                    **model_config,
                    'provider': 'custom',
                    'readonly': False,
                }
    except Exception as e:
        logger.warning(f"Failed to load custom models: {e}")

    return all_models


def get_current_model_config(user) -> Tuple[str, Dict]:
    """
    获取用户当前使用的模型配置

    Args:
        user: Django User 对象

    Returns:
        (model_id, model_config)
    """
    from core.models import UserData

    # 获取当前模型 ID
    current_model_id = 'system_deepseek'  # 默认

    try:
        agent_config_data = UserData.objects.filter(user=user, key='agent_config').first()
        if agent_config_data:
            config = agent_config_data.get_value()
            current_model_id = config.get('current_model_id', 'system_deepseek')
    except Exception as e:
        logger.warning(f"Failed to get current model id: {e}")

    # 获取模型配置
    all_models = get_all_models(user)
    model_config = all_models.get(current_model_id)

    # 如果模型不存在，回退到默认
    if not model_config:
        current_model_id = 'system_deepseek'
        model_config = SYSTEM_MODELS['system_deepseek']

    return current_model_id, model_config


def get_optimization_config(user) -> Dict:
    """
    获取用户的上下文优化配置

    Args:
        user: Django User 对象

    Returns:
        优化配置字典
    """
    from core.models import UserData

    # 默认配置
    default_config = {
        'enable_optimization': True,
        'target_usage_ratio': 0.6,
        'token_calculation_method': 'actual',
        'summary_token_ratio': 0.26,
        'recent_token_ratio': 0.65,
        'enable_summarization': True,
        'summary_trigger_ratio': 0.5,
        'min_messages_before_summary': 20,
        'compress_tool_output': True,
        'tool_output_max_tokens': 200,
        'target_summary_tokens': 2000,      # 目标总结 token 数
    }

    try:
        opt_config_data = UserData.objects.filter(user=user, key='agent_optimization_config').first()
        if opt_config_data:
            config = opt_config_data.get_value()
            merged = {**default_config, **config}
            logger.info(f"[优化配置] 用户配置: {config}")
            logger.info(f"[优化配置] 合并后: target_usage_ratio={merged.get('target_usage_ratio')}, summary_token_ratio={merged.get('summary_token_ratio')}")
            return merged
        else:
            logger.info(f"[优化配置] 用户无自定义配置，使用默认值")
    except Exception as e:
        logger.warning(f"Failed to get optimization config: {e}")

    return default_config


def update_token_usage(user, input_tokens: int, output_tokens: int, model_id: str, cost: float = 0) -> bool:
    """
    更新用户的 Token 使用统计

    Args:
        user: Django User 对象
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        model_id: 使用的模型 ID
        cost: 费用（美元）

    Returns:
        是否更新成功
    """
    from core.models import UserData
    from datetime import datetime

    try:
        # 获取或创建统计记录
        usage_data, created = UserData.objects.get_or_create(
            user=user,
            key='agent_token_usage',
            defaults={'value': '{}'}
        )

        stats = usage_data.get_value() if not created else {}

        # 更新累计统计
        stats['total_input_tokens'] = stats.get('total_input_tokens', 0) + input_tokens
        stats['total_output_tokens'] = stats.get('total_output_tokens', 0) + output_tokens
        stats['total_cost'] = stats.get('total_cost', 0) + cost
        stats['quota'] = stats.get('quota', 9999999)
        stats['last_updated'] = datetime.now().isoformat()

        # 更新每日统计
        today = datetime.now().strftime('%Y-%m-%d')
        daily_stats = stats.get('daily_stats', {})
        if today not in daily_stats:
            daily_stats[today] = {'input': 0, 'output': 0, 'cost': 0}
        daily_stats[today]['input'] += input_tokens
        daily_stats[today]['output'] += output_tokens
        daily_stats[today]['cost'] += cost
        stats['daily_stats'] = daily_stats

        # 更新模型统计
        model_stats = stats.get('model_stats', {})
        if model_id not in model_stats:
            model_stats[model_id] = {'input': 0, 'output': 0, 'cost': 0}
        model_stats[model_id]['input'] += input_tokens
        model_stats[model_id]['output'] += output_tokens
        model_stats[model_id]['cost'] += cost
        stats['model_stats'] = model_stats

        # 保存
        usage_data.set_value(stats)

        logger.debug(
            f"Token usage updated: user={user.username}, "
            f"input={input_tokens}, output={output_tokens}, cost=${cost:.4f}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to update token usage: {e}")
        return False


def get_token_usage_stats(user, period: str = 'all') -> Dict:
    """
    获取用户的 Token 使用统计

    Args:
        user: Django User 对象
        period: 时间段 ('all', 'today', 'week', 'month')

    Returns:
        统计数据字典
    """
    from core.models import UserData
    from datetime import datetime, timedelta

    try:
        usage_data = UserData.objects.filter(user=user, key='agent_token_usage').first()
        if not usage_data:
            return {
                'total_input_tokens': 0,
                'total_output_tokens': 0,
                'total_cost': 0,
                'quota': 9999999,
                'daily_stats': {},
                'model_stats': {},
            }

        stats = usage_data.get_value()

        if period == 'all':
            return stats

        # 计算时间范围
        today = datetime.now().date()
        daily_stats = stats.get('daily_stats', {})

        if period == 'today':
            date_key = today.strftime('%Y-%m-%d')
            day_data = daily_stats.get(date_key, {'input': 0, 'output': 0, 'cost': 0})
            return {
                'input_tokens': day_data.get('input', 0),
                'output_tokens': day_data.get('output', 0),
                'cost': day_data.get('cost', 0),
            }

        if period == 'week':
            result = {'input_tokens': 0, 'output_tokens': 0, 'cost': 0}
            for i in range(7):
                date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
                day_data = daily_stats.get(date, {})
                result['input_tokens'] += day_data.get('input', 0)
                result['output_tokens'] += day_data.get('output', 0)
                result['cost'] += day_data.get('cost', 0)
            return result

        return stats

    except Exception as e:
        logger.error(f"Failed to get token usage stats: {e}")
        return {}
