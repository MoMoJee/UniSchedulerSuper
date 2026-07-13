"""可信 Planner 调用上下文；协议入口构造，领域 payload 不得覆盖。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.contrib.auth.models import User


PlannerSource = Literal[
    "web_v2",
    "websocket_agent",
    "quick_action",
    "mcp_stdio",
    "mcp_http",
    "internal_attachment",
    "calendar_feed",
    "caldav",
]


@dataclass(frozen=True, slots=True)
class PlannerExecutionContext:
    user: User
    source: PlannerSource
    entrypoint: str
    session_id: str = ""
    tool_call_id: str = ""
    request_id: str = ""
    message_index: int | None = None
    rollback_window_id: str = ""
    reversible: bool = False

    def __post_init__(self) -> None:
        if not getattr(self.user, "is_authenticated", False):
            raise ValueError("Planner execution context 需要已认证用户")
        if self.reversible and self.source != "websocket_agent":
            raise ValueError("只有 WebSocket Agent 上下文可以声明聊天回滚")
        if self.reversible and (not self.session_id or not self.tool_call_id):
            raise ValueError("可回滚命令必须具有 session_id 与 tool_call_id")
        if self.message_index is not None and self.message_index < 0:
            raise ValueError("message_index 不能为负数")
