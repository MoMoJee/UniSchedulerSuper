"""
Provider-safe tool name mapping.

Internal tool names may include MCP service names such as ``12306-mcp``.  Some
providers accept those, others reject them.  The mapper keeps a reversible map
for the active tool set and only changes names when required.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Dict, Iterable, List, Tuple

SAFE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
STRICT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class ProviderNameMapper:
    def __init__(self, tool_name_style: str = "openai-compatible"):
        self.tool_name_style = tool_name_style or "openai-compatible"
        self.provider_to_internal: Dict[str, str] = {}
        self.internal_to_provider: Dict[str, str] = {}

    @property
    def _pattern(self):
        return STRICT_RE if self.tool_name_style == "strict-alnum-underscore" else SAFE_RE

    def _sanitize_base(self, internal_name: str) -> str:
        name = internal_name or "tool"
        if self.tool_name_style == "strict-alnum-underscore":
            name = re.sub(r"[^A-Za-z0-9_]", "_", name)
        else:
            name = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        if not re.match(r"^[A-Za-z_]", name):
            name = f"tool_{name}"
        return name

    def to_provider_tool_name(self, internal_name: str) -> str:
        if internal_name in self.internal_to_provider:
            return self.internal_to_provider[internal_name]

        candidate = self._sanitize_base(internal_name)
        if len(candidate) > 64:
            digest = hashlib.sha1(internal_name.encode("utf-8")).hexdigest()[:8]
            candidate = f"{candidate[:55]}_{digest}"

        if not self._pattern.match(candidate):
            digest = hashlib.sha1(internal_name.encode("utf-8")).hexdigest()[:8]
            candidate = f"tool_{digest}"

        original_candidate = candidate
        counter = 2
        while candidate in self.provider_to_internal and self.provider_to_internal[candidate] != internal_name:
            suffix = f"_{counter}"
            candidate = f"{original_candidate[:64 - len(suffix)]}{suffix}"
            counter += 1

        self.internal_to_provider[internal_name] = candidate
        self.provider_to_internal[candidate] = internal_name
        return candidate

    def to_internal_tool_name(self, provider_name: str) -> str:
        return self.provider_to_internal.get(provider_name, provider_name)

    def build_for_names(self, internal_names: Iterable[str]) -> "ProviderNameMapper":
        for name in internal_names:
            self.to_provider_tool_name(name)
        return self

    def to_dict(self) -> Dict[str, Dict[str, str]]:
        return {
            "internal_to_provider": dict(self.internal_to_provider),
            "provider_to_internal": dict(self.provider_to_internal),
        }


def clone_tool_with_provider_name(tool, provider_name: str):
    if getattr(tool, "name", None) == provider_name:
        return tool

    for method_name in ("model_copy", "copy"):
        method = getattr(tool, method_name, None)
        if callable(method):
            try:
                return method(update={"name": provider_name})
            except Exception:
                pass

    cloned = copy.copy(tool)
    try:
        cloned.name = provider_name
        return cloned
    except Exception:
        return tool


def map_tools_for_provider(tools: List, mapper: ProviderNameMapper) -> Tuple[List, Dict[str, str]]:
    provider_tools = []
    for tool in tools:
        internal_name = getattr(tool, "name", "")
        provider_name = mapper.to_provider_tool_name(internal_name)
        provider_tools.append(clone_tool_with_provider_name(tool, provider_name))
    return provider_tools, mapper.to_dict()["provider_to_internal"]
