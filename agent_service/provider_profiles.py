"""
Provider profile helpers for outbound LLM request compatibility.

The project mostly talks to OpenAI-compatible endpoints, but providers still
vary in usage metadata, thinking parameters, image blocks, and accepted JSON
names.  This module centralizes those decisions so agent_graph.py does not need
provider-specific branches scattered through the prompt construction flow.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ProviderProfile:
    provider_style: str = "openai-compatible"
    cache_usage_style: str = "none"
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


def build_provider_profile(
    model_id: str,
    model_config: Optional[Dict[str, Any]],
) -> ProviderProfile:
    cfg = model_config or {}
    provider = cfg.get("provider", "")
    model_name = cfg.get("model_name") or cfg.get("model") or cfg.get("name", "")
    provider_style = (
        cfg.get("provider_style")
        or infer_provider_style(provider, model_name)
    )
    thinking_style = cfg.get("thinking_param_style", "none")
    supports_vision = bool(cfg.get("supports_vision", False))
    supports_multimodal = bool(cfg.get("supports_multimodal", supports_vision))

    return ProviderProfile(
        provider_style=provider_style,
        cache_usage_style=cfg.get("cache_usage_style") or default_cache_usage_style(provider_style),
        thinking_param_style=thinking_style,
        message_format_style=cfg.get("message_format_style", "openai-chat"),
        image_block_style=cfg.get("image_block_style") or default_image_block_style(provider_style, supports_vision),
        tool_name_style=cfg.get("tool_name_style") or default_tool_name_style(provider_style),
        supports_vision=supports_vision,
        supports_multimodal=supports_multimodal,
        model_id=model_id,
        model_name=model_name,
    )
