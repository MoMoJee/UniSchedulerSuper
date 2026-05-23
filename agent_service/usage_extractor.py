"""
Normalize token, cache, and reasoning usage metadata from provider responses.
"""
from __future__ import annotations

from typing import Any, Dict


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    result: Dict[str, Any] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
    ):
        if hasattr(value, key):
            result[key] = getattr(value, key)
    return result


def _usage_from_response(response: Any) -> Dict[str, Any]:
    usage: Dict[str, Any] = {}

    usage_metadata = _as_dict(getattr(response, "usage_metadata", None))
    if usage_metadata:
        usage.update(usage_metadata)

    metadata = _as_dict(getattr(response, "response_metadata", None))
    if metadata:
        raw_usage = (
            metadata.get("token_usage")
            or metadata.get("usage")
            or metadata.get("usage_metadata")
            or {}
        )
        if isinstance(raw_usage, dict):
            usage.update(raw_usage)

    return usage


def extract_llm_usage(response: Any, cache_usage_style: str = "none") -> Dict[str, Any]:
    usage = _usage_from_response(response)

    input_tokens = (
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or 0
    )
    output_tokens = (
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or 0
    )
    total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens if input_tokens or output_tokens else 0)

    cache_hit = 0
    cache_miss = 0
    reasoning_tokens = 0
    cache_source = "none"

    style = cache_usage_style or "none"
    if style == "deepseek":
        cache_hit = usage.get("prompt_cache_hit_tokens", 0) or 0
        cache_miss = usage.get("prompt_cache_miss_tokens", 0) or 0
        details = usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict) and not cache_hit:
            cache_hit = details.get("cached_tokens", 0) or 0
        completion_details = usage.get("completion_tokens_details") or {}
        if isinstance(completion_details, dict):
            reasoning_tokens = completion_details.get("reasoning_tokens", 0) or 0
        cache_source = "deepseek"
    elif style == "kimi":
        cache_hit = usage.get("cached_tokens", 0) or 0
        cache_miss = max(int(input_tokens or 0) - int(cache_hit or 0), 0) if input_tokens else 0
        cache_source = "kimi"

    cached_tokens = cache_hit
    cache_hit_ratio = (float(cache_hit) / float(input_tokens)) if input_tokens else 0.0
    source = "actual" if input_tokens or output_tokens else "estimated"

    return {
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "cached_tokens": int(cached_tokens or 0),
        "cache_hit_tokens": int(cache_hit or 0),
        "cache_miss_tokens": int(cache_miss or 0),
        "cache_hit_ratio": cache_hit_ratio,
        "reasoning_tokens": int(reasoning_tokens or 0),
        "cache_source": cache_source,
        "source": source,
        "raw_usage": usage,
    }
