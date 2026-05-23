"""
Materialize canonical LangGraph messages into provider-ready outbound messages.

Checkpoint history should stay canonical and easy to reason about.  Right before
calling the LLM, this module adapts images, OCR fallback text, and provider name
fields for the currently selected model.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agent_service.provider_profiles import ProviderProfile
from agent_service.tool_name_mapper import ProviderNameMapper


ATTACHMENT_CONTEXT_PREFIXES = (
    "【附件内容】",
    "【最新消息附件内容】",
    "【历史消息附件内容】",
)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(content) if content else ""


def _is_attachment_context_message(message: BaseMessage) -> bool:
    if not isinstance(message, SystemMessage):
        return False
    content = message.content if isinstance(message.content, str) else ""
    return content.startswith(ATTACHMENT_CONTEXT_PREFIXES)


def _is_runtime_context_message(message: BaseMessage) -> bool:
    if not isinstance(message, SystemMessage):
        return False
    content = message.content if isinstance(message.content, str) else ""
    return (
        content.startswith("[Runtime Context]")
        or content.startswith("【本轮运行时上下文】")
        or content.startswith("銆愭湰杞繍琛屾椂涓婁笅鏂囥€")
    )


def _fold_legacy_context_messages(messages: List[BaseMessage]) -> List[BaseMessage]:
    result: List[BaseMessage] = []
    pending_runtime = ""
    pending_attachment = ""

    for msg in messages:
        if _is_runtime_context_message(msg):
            pending_runtime = _message_text(msg.content)
            continue
        if _is_attachment_context_message(msg):
            pending_attachment = _message_text(msg.content)
            continue

        if isinstance(msg, HumanMessage) and (pending_runtime or pending_attachment):
            kwargs = dict(getattr(msg, "additional_kwargs", None) or {})
            if pending_runtime and not kwargs.get("runtime_context"):
                kwargs["runtime_context"] = pending_runtime
            if pending_attachment and not kwargs.get("attachments_context"):
                kwargs["attachments_context"] = pending_attachment
            result.append(HumanMessage(content=msg.content, additional_kwargs=kwargs))
            pending_runtime = ""
            pending_attachment = ""
            continue

        if pending_runtime:
            result.append(SystemMessage(content=pending_runtime))
            pending_runtime = ""
        if pending_attachment:
            result.append(SystemMessage(content=pending_attachment))
            pending_attachment = ""
        result.append(msg)

    if pending_runtime:
        result.append(SystemMessage(content=pending_runtime))
    if pending_attachment:
        result.append(SystemMessage(content=pending_attachment))
    return result


def ensure_legacy_attachment_context_messages(messages: Iterable[BaseMessage]) -> List[BaseMessage]:
    """
    Normalize old checkpoint context messages into HumanMessage kwargs.

    Current turns keep runtime and attachment context in HumanMessage metadata
    and prefix it only in the provider-bound outbound copy. Older checkpoints
    may contain runtime/attachment SystemMessage entries; fold them into the
    following HumanMessage so they no longer participate in provider system
    prompt serialization.
    """
    return _fold_legacy_context_messages(list(messages))


class OutboundMessageMaterializer:
    def __init__(self, provider_profile: ProviderProfile, user, name_mapper: ProviderNameMapper | None = None):
        self.profile = provider_profile
        self.user = user
        self.name_mapper = name_mapper or ProviderNameMapper(provider_profile.tool_name_style)
        self.stats: Dict[str, int] = {
            "human_messages_materialized": 0,
            "image_blocks": 0,
            "ocr_images": 0,
            "legacy_attachment_context_messages": 0,
        }

    def materialize(self, messages: Iterable[BaseMessage]) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        source = list(messages)
        prepared = ensure_legacy_attachment_context_messages(source)
        self.stats["legacy_attachment_context_messages"] = len(prepared) - len(source)

        output: List[BaseMessage] = []
        for msg in prepared:
            if isinstance(msg, HumanMessage):
                output.append(self._materialize_human(msg))
            elif isinstance(msg, ToolMessage):
                output.append(self._materialize_tool(msg))
            elif isinstance(msg, AIMessage):
                output.append(self._materialize_ai(msg))
            else:
                output.append(msg)
        return output, {
            "provider_profile": self.profile.to_dict(),
            "name_mapping": self.name_mapper.to_dict(),
            "stats": dict(self.stats),
        }

    def _attachment_ids(self, msg: HumanMessage) -> List[int]:
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        attachment_ids = kwargs.get("attachment_ids") or []
        if not attachment_ids:
            metadata = kwargs.get("attachments_metadata") or []
            attachment_ids = [m.get("sa_id") for m in metadata if isinstance(m, dict) and m.get("sa_id")]
        return [int(v) for v in attachment_ids if v]

    def _materialize_human(self, msg: HumanMessage) -> HumanMessage:
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        attachment_ids = self._attachment_ids(msg)
        if not attachment_ids:
            if not self.profile.supports_vision and isinstance(msg.content, list):
                content = self._strip_image_blocks(msg.content)
                content = self._prefix_human_context(content, kwargs)
                return HumanMessage(content=content, additional_kwargs=msg.additional_kwargs)
            content = self._prefix_human_context(msg.content, kwargs)
            if content == msg.content:
                return msg
            return HumanMessage(content=content, additional_kwargs=msg.additional_kwargs)

        from agent_service.attachment_handler import AttachmentHandler

        content = AttachmentHandler.materialize_message_content_for_profile(
            original_content=msg.content,
            attachment_ids=attachment_ids,
            user=self.user,
            provider_profile=self.profile,
        )
        if isinstance(content, list):
            self.stats["image_blocks"] += sum(1 for b in content if isinstance(b, dict) and b.get("type") in {"image_url", "image"})
        elif isinstance(content, str):
            self.stats["ocr_images"] += content.count("[图片 ")
        content = self._prefix_human_context(content, kwargs)
        self.stats["human_messages_materialized"] += 1
        return HumanMessage(content=content, additional_kwargs=msg.additional_kwargs)

    def _prefix_human_context(self, content: Any, kwargs: Dict[str, Any]) -> Any:
        runtime_context = kwargs.get("runtime_context") or ""
        attachments_context = kwargs.get("attachments_context") or ""
        prefix_parts = []
        if runtime_context:
            prefix_parts.append(str(runtime_context))
        if attachments_context:
            prefix_parts.append(
                f"[Attachment Context]\n{attachments_context}"
            )
        if not prefix_parts:
            return content

        prefix = "\n\n".join(prefix_parts)
        if isinstance(content, list):
            return [{"type": "text", "text": prefix}] + content
        return f"{prefix}\n\n[User Message]\n{_message_text(content)}"

    def _strip_image_blocks(self, content: Any) -> str:
        text_parts = []
        image_count = 0
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") in {"image_url", "image"}:
                        image_count += 1
                elif isinstance(block, str):
                    text_parts.append(block)
        else:
            text_parts.append(_message_text(content))
        if image_count:
            text_parts.append(f"[此消息包含 {image_count} 张图片，当前模型不支持图片识别，且未找到附件记录用于 OCR]")
        return "\n".join(p for p in text_parts if p)

    def _materialize_tool(self, msg: ToolMessage) -> ToolMessage:
        internal_name = getattr(msg, "name", "") or ""
        provider_name = self.name_mapper.to_provider_tool_name(internal_name) if internal_name else None
        return ToolMessage(
            content=msg.content,
            tool_call_id=msg.tool_call_id,
            name=provider_name,
            additional_kwargs=getattr(msg, "additional_kwargs", None) or {},
        )

    def _materialize_ai(self, msg: AIMessage) -> AIMessage:
        tool_calls = []
        changed = False
        for call in getattr(msg, "tool_calls", None) or []:
            if not isinstance(call, dict):
                tool_calls.append(call)
                continue
            new_call = dict(call)
            name = new_call.get("name")
            if name:
                provider_name = self.name_mapper.to_provider_tool_name(name)
                if provider_name != name:
                    new_call["name"] = provider_name
                    changed = True
            tool_calls.append(new_call)

        if not changed:
            return msg

        return AIMessage(
            content=msg.content,
            additional_kwargs=getattr(msg, "additional_kwargs", None) or {},
            response_metadata=getattr(msg, "response_metadata", None) or {},
            tool_calls=tool_calls,
        )
