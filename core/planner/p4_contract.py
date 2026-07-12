"""P4 对外 Planner 调用面的冻结契约。

P4-0 只定义和审计契约，不改变任何业务路径。后续 P4-A~E 可以替换内部
实现，但不得静默删除或改名这些公共工具参数。
"""

PLANNER_TOOL_PARAMETER_CONTRACTS = {
    "search_items": (
        "config", "item_type", "keyword", "time_range", "status", "event_group",
        "share_groups", "share_groups_only", "limit",
    ),
    "create_item": (
        "config", "item_type", "title", "description", "start", "end", "event_group",
        "importance", "urgency", "shared_to_groups", "ddl", "due_date", "priority",
        "trigger_time", "content", "repeat",
    ),
    "update_item": (
        "config", "identifier", "item_type", "edit_scope", "from_time", "title",
        "description", "start", "end", "event_group", "importance", "urgency",
        "shared_to_groups", "ddl", "due_date", "priority", "status", "trigger_time",
        "content", "repeat", "clear_repeat",
    ),
    "delete_item": ("config", "identifier", "item_type", "delete_scope"),
    "get_event_groups": ("config",),
    "get_share_groups": ("config",),
    "complete_todo": ("config", "identifier"),
    "check_schedule_conflicts": (
        "config", "time_range", "include_share_groups", "analysis_focus",
    ),
}

MCP_TOOL_PARAMETER_CONTRACTS = {
    name: tuple(item for item in parameters if item != "config")
    for name, parameters in PLANNER_TOOL_PARAMETER_CONTRACTS.items()
}

ROLLBACK_ROUTE_CONTRACTS = (
    "rollback/preview/",
    "rollback/",
    "rollback/to-message/",
)

P4_ENTRYPOINT_INVENTORY = {
    "websocket_agent": "agent_service/tools/unified_planner_tools.py",
    "legacy_agent_tools": "agent_service/tools/planner_tools.py",
    "normalized_tool_adapter": "agent_service/tools/planner_application_adapter.py",
    "quick_action": "agent_service/quick_action_agent.py",
    "mcp_stdio_http": "mcp_server.py",
    "cache": "agent_service/tools/cache_manager.py",
    "identifier_resolver": "agent_service/tools/identifier_resolver.py",
    "conflict_analyzer": "agent_service/tools/conflict_analyzer.py",
    "event_groups": "agent_service/tools/event_group_service.py",
    "share_groups": "agent_service/tools/share_group_service.py",
    "internal_attachment": "agent_service/parsers/internal_parser.py",
    "agent_rollback_api": "agent_service/views_api.py",
    "legacy_rollback_api": "core/views_rollback.py",
}
