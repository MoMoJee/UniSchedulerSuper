"""
Normalize token, cache, and reasoning usage metadata from provider responses.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from logger import logger


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


def _get_path(container: Dict[str, Any], path: str) -> Any:
    current: Any = container
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _first_path_value(container: Dict[str, Any], paths: Iterable[str]) -> tuple[Any, str]:
    for path in paths or []:
        if path.startswith("derived."):
            continue
        value = _get_path(container, path)
        if value is not None:
            return value, path
    return None, ""


def _legacy_usage_paths(cache_usage_style: str) -> Dict[str, Any]:
    if cache_usage_style == "deepseek":
        return {
            "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
            "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
            "cache_hit_input_tokens": ["usage.prompt_cache_hit_tokens", "usage.prompt_tokens_details.cached_tokens"],
            "cache_miss_input_tokens": ["usage.prompt_cache_miss_tokens"],
            "reasoning_tokens": ["usage.completion_tokens_details.reasoning_tokens"],
        }
    if cache_usage_style == "kimi":
        return {
            "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
            "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
            "cache_hit_input_tokens": ["usage.cached_tokens"],
            "cache_miss_input_tokens": ["derived.input_minus_cache_hit"],
            "reasoning_tokens": [],
        }
    return {
        "input_tokens": ["usage.input_tokens", "usage.prompt_tokens"],
        "output_tokens": ["usage.output_tokens", "usage.completion_tokens"],
        "cache_hit_input_tokens": [],
        "cache_miss_input_tokens": ["derived.input_when_no_cache"],
        "reasoning_tokens": [],
    }


def extract_llm_usage(
    response: Any,
    cache_usage_style: str = "none",
    *,
    provider_profile: Optional[Any] = None,
    usage_paths: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    usage = _usage_from_response(response)
    style_name = getattr(provider_profile, "style_name", "") or cache_usage_style or "none"
    resolved_paths = usage_paths or getattr(provider_profile, "usage_paths", None) or _legacy_usage_paths(cache_usage_style)
    usage_container = {"usage": usage}

    input_tokens, input_path = _first_path_value(usage_container, resolved_paths.get("input_tokens", []))
    output_tokens, output_path = _first_path_value(usage_container, resolved_paths.get("output_tokens", []))
    input_tokens = input_tokens or 0
    output_tokens = output_tokens or 0
    total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens if input_tokens or output_tokens else 0)

    cache_hit, cache_hit_path = _first_path_value(usage_container, resolved_paths.get("cache_hit_input_tokens", []))
    cache_miss, cache_miss_path = _first_path_value(usage_container, resolved_paths.get("cache_miss_input_tokens", []))
    reasoning_tokens, reasoning_path = _first_path_value(usage_container, resolved_paths.get("reasoning_tokens", []))

    if cache_hit is None:
        for alias in ("cache_hit_tokens", "cached_tokens"):
            if alias in usage:
                cache_hit = usage.get(alias, 0)
                cache_hit_path = f"usage.{alias}"
                logger.warning(f"[Usage抽取] 使用兼容 cache hit 字段: style={style_name}, field={alias}")
                break
    if cache_miss is None and "cache_miss_tokens" in usage:
        cache_miss = usage.get("cache_miss_tokens", 0)
        cache_miss_path = "usage.cache_miss_tokens"
        logger.warning(f"[Usage抽取] 使用兼容 cache miss 字段: style={style_name}, field=cache_miss_tokens")

    cache_hit = int(cache_hit or 0)
    cache_miss_paths = resolved_paths.get("cache_miss_input_tokens", [])
    if cache_miss is None and "derived.input_minus_cache_hit" in cache_miss_paths:
        cache_miss = max(int(input_tokens or 0) - cache_hit, 0)
        cache_miss_path = "derived.input_minus_cache_hit"
    elif cache_miss is None and "derived.input_when_no_cache" in cache_miss_paths:
        cache_miss = int(input_tokens or 0)
        cache_miss_path = "derived.input_when_no_cache"
        if input_tokens:
            logger.warning(f"[Usage抽取] provider 未返回 cache 字段，按全量输入未命中计费: style={style_name}")
    elif cache_miss is None:
        cache_miss = max(int(input_tokens or 0) - cache_hit, 0)
        cache_miss_path = "derived.input_minus_cache_hit_fallback"
        if input_tokens:
            logger.warning(f"[Usage抽取] cache miss 字段缺失，使用 input-cache_hit 估算: style={style_name}")

    cached_tokens = cache_hit
    cache_hit_ratio = (float(cache_hit) / float(input_tokens)) if input_tokens else 0.0
    source = "actual" if input_tokens or output_tokens else "estimated"
    cache_source = getattr(provider_profile, "cache_source", "") or cache_usage_style or "none"

    logger.debug(
        f"[Usage抽取] style={style_name}, keys={list(usage.keys())}, "
        f"input={input_tokens}({input_path}), hit={cache_hit}({cache_hit_path}), "
        f"miss={cache_miss}({cache_miss_path}), out={output_tokens}({output_path}), reasoning={reasoning_tokens}({reasoning_path})"
    )

    return {
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "input_cache_hit_tokens": int(cache_hit or 0),
        "input_cache_miss_tokens": int(cache_miss or 0),
        "billable_input_cache_hit_tokens": int(cache_hit or 0),
        "billable_input_cache_miss_tokens": int(cache_miss or 0),
        "billable_output_tokens": int(output_tokens or 0),
        "cached_tokens": int(cached_tokens or 0),
        "cache_hit_tokens": int(cache_hit or 0),
        "cache_miss_tokens": int(cache_miss or 0),
        "cache_hit_ratio": cache_hit_ratio,
        "reasoning_tokens": int(reasoning_tokens or 0),
        "cache_source": cache_source,
        "provider_style": style_name,
        "source": source,
        "raw_usage": usage,
    }
