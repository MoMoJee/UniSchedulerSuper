"""
Provider profile helpers for outbound LLM request compatibility.

The project mostly talks to OpenAI-compatible endpoints, but providers still
vary in usage metadata, thinking parameters, image blocks, and accepted JSON
names.  This module centralizes those decisions so agent_graph.py does not need
provider-specific branches scattered through the prompt construction flow.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from logger import logger


DEFAULT_PROVIDER_STYLES: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "request": {"message_format": "openai-chat", "image_block": "none", "tool_name": "openai-compatible"},
        "thinking": {
            "mode_param": "deepseek",
            "enabled_extra_body": {"thinking": {"type": "enabled"}},
            "disabled_extra_body": {"thinking": {"type": "disabled"}},
            "enabled_extra_kwargs": {"reasoning_effort": "high"},
        },
        "usage": {
            "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
            "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
            "cache_hit_input_tokens": ["usage.prompt_cache_hit_tokens", "usage.prompt_tokens_details.cached_tokens"],
            "cache_miss_input_tokens": ["usage.prompt_cache_miss_tokens"],
            "reasoning_tokens": ["usage.completion_tokens_details.reasoning_tokens"],
        },
        "billing": {
            "input_cache_miss_price_key": "cost_per_1k_input_cache_miss",
            "input_cache_hit_price_key": "cost_per_1k_input_cache_hit",
            "output_price_key": "cost_per_1k_output",
        },
    },
    "kimi": {
        "request": {"message_format": "openai-chat", "image_block": "openai-image-url", "tool_name": "openai-compatible"},
        "thinking": {
            "mode_param": "kimi-k2",
            "enabled_extra_body": {"thinking": {"type": "enabled", "keep": "all"}},
            "disabled_extra_body": {"thinking": {"type": "disabled", "keep": "all"}},
            "enabled_defaults": {"temperature": 1.0, "min_max_tokens": 16000},
        },
        "usage": {
            "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
            "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
            "cache_hit_input_tokens": ["usage.cached_tokens"],
            "cache_miss_input_tokens": ["derived.input_minus_cache_hit"],
            "reasoning_tokens": [],
        },
        "billing": {
            "input_cache_miss_price_key": "cost_per_1k_input_cache_miss",
            "input_cache_hit_price_key": "cost_per_1k_input_cache_hit",
            "output_price_key": "cost_per_1k_output",
        },
    },
    "openai-compatible": {
        "request": {"message_format": "openai-chat", "image_block": "openai-image-url", "tool_name": "openai-compatible"},
        "thinking": {"mode_param": "none"},
        "usage": {
            "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
            "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
            "cache_hit_input_tokens": [],
            "cache_miss_input_tokens": ["derived.input_when_no_cache"],
            "reasoning_tokens": [],
        },
        "billing": {},
    },
}


@dataclass(frozen=True)
class ProviderProfile:
    style_name: str = "openai-compatible"
    style_config: Dict[str, Any] = field(default_factory=dict)
    request_config: Dict[str, Any] = field(default_factory=dict)
    thinking: Dict[str, Any] = field(default_factory=dict)
    usage_paths: Dict[str, Any] = field(default_factory=dict)
    billing_keys: Dict[str, Any] = field(default_factory=dict)
    provider_style: str = "openai-compatible"
    cache_usage_style: str = "none"
    cache_source: str = "none"
    thinking_param_style: str = "none"
    message_format_style: str = "openai-chat"
    image_block_style: str = "none"
    tool_name_style: str = "openai-compatible"
    supports_vision: bool = False
    supports_multimodal: bool = False
    model_id: str = ""
    model_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def infer_provider_style(provider: str, model_name: str = "") -> str:
    value = f"{provider or ''} {model_name or ''}".lower()
    if "deepseek" in value:
        return "deepseek"
    if "moonshot" in value or "kimi" in value:
        return "kimi"
    if "anthropic" in value or "claude" in value:
        return "anthropic-compatible"
    if "openai" in value or "gpt" in value:
        return "openai-compatible"
    return "openai-compatible"


def default_cache_usage_style(provider_style: str) -> str:
    if provider_style == "deepseek":
        return "deepseek"
    if provider_style == "kimi":
        return "kimi"
    return "none"


def default_image_block_style(provider_style: str, supports_vision: bool) -> str:
    if not supports_vision:
        return "none"
    if provider_style == "anthropic-compatible":
        return "anthropic-image-source"
    return "openai-image-url"


def default_tool_name_style(provider_style: str) -> str:
    if provider_style in {"deepseek", "kimi", "openai-compatible"}:
        return "openai-compatible"
    return "strict-alnum-underscore"


def _load_provider_style(style_name: str) -> Dict[str, Any]:
    try:
        from config.api_keys_manager import APIKeyManager

        configured_style = APIKeyManager.get_provider_style(style_name)
        if configured_style:
            return deepcopy(configured_style)
    except Exception as e:
        logger.warning(f"[ProviderStyle] 读取 provider_styles 失败，使用内置回退: style={style_name}, error={e}")

    fallback = DEFAULT_PROVIDER_STYLES.get(style_name)
    if fallback:
        logger.warning(f"[ProviderStyle] style={style_name} 未在 provider_styles 中配置，使用内置兼容定义")
        return deepcopy(fallback)

    logger.warning(f"[ProviderStyle] 未识别 style={style_name}，回退 openai-compatible")
    return deepcopy(DEFAULT_PROVIDER_STYLES["openai-compatible"])


def resolve_provider_style(model_config: Optional[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    cfg = model_config or {}
    provider = cfg.get("provider", "")
    model_name = cfg.get("model_name") or cfg.get("model") or cfg.get("name", "")

    explicit_style = cfg.get("style")
    if explicit_style:
        style_name = str(explicit_style)
        return style_name, _load_provider_style(style_name)

    legacy_fields = [
        "provider_style",
        "cache_usage_style",
        "thinking_param_style",
        "message_format_style",
        "image_block_style",
        "tool_name_style",
    ]
    legacy_used = [field_name for field_name in legacy_fields if cfg.get(field_name)]
    if legacy_used:
        style_name = cfg.get("provider_style") or infer_provider_style(provider, model_name)
        logger.warning(f"[ProviderStyle] 模型使用旧 style 字段，按兼容路径解析: style={style_name}, fields={legacy_used}")
        return style_name, _load_provider_style(style_name)

    style_name = infer_provider_style(provider, model_name)
    logger.warning(f"[ProviderStyle] 模型未配置 style，按 provider/model_name 推断: style={style_name}")
    return style_name, _load_provider_style(style_name)


def build_provider_profile(
    model_id: str,
    model_config: Optional[Dict[str, Any]],
) -> ProviderProfile:
    cfg = model_config or {}
    provider = cfg.get("provider", "")
    model_name = cfg.get("model_name") or cfg.get("model") or cfg.get("name", "")
    style_name, style_config = resolve_provider_style(cfg)
    request_config = deepcopy(style_config.get("request", {}))
    thinking_config = deepcopy(style_config.get("thinking", {}))
    usage_paths = deepcopy(style_config.get("usage", {}))
    billing_keys = deepcopy(style_config.get("billing", {}))
    provider_style = cfg.get("provider_style") or style_config.get("provider_style") or style_name
    thinking_style = cfg.get("thinking_param_style") or thinking_config.get("mode_param", "none")
    supports_vision = bool(cfg.get("supports_vision", False))
    supports_multimodal = bool(cfg.get("supports_multimodal", supports_vision))
    cache_usage_style = cfg.get("cache_usage_style") or style_config.get("cache_usage_style") or default_cache_usage_style(provider_style)

    return ProviderProfile(
        style_name=style_name,
        style_config=style_config,
        request_config=request_config,
        thinking=thinking_config,
        usage_paths=usage_paths,
        billing_keys=billing_keys,
        provider_style=provider_style,
        cache_usage_style=cache_usage_style,
        cache_source=cache_usage_style,
        thinking_param_style=thinking_style,
        message_format_style=cfg.get("message_format_style") or request_config.get("message_format", "openai-chat"),
        image_block_style=cfg.get("image_block_style") or request_config.get("image_block") or default_image_block_style(provider_style, supports_vision),
        tool_name_style=cfg.get("tool_name_style") or request_config.get("tool_name") or default_tool_name_style(provider_style),
        supports_vision=supports_vision,
        supports_multimodal=supports_multimodal,
        model_id=model_id,
        model_name=model_name,
    )
