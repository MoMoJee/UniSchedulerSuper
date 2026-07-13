"""Retired Planner V1 HTTP contract.

P6 sealed the legacy Planner JSON archive.  Keeping the old URL patterns routed
to their historical views would make writes fail late (often as a 500 from the
database write guard).  This module turns those URLs into an explicit, stable
API tombstone without reading or writing Planner data.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


LEGACY_PLANNER_REPLACEMENTS = {
    "/get_calendar/events/": {"method": "GET", "path": "/api/v2/events/occurrences/", "note": "from 与 to 必填"},
    "/get_calendar/update_events/": {"method": "PATCH", "path": "/api/v2/events/{event_id}/"},
    "/events/create_event/": {"method": "POST", "path": "/api/v2/events/"},
    "/api/events/groups/": {"method": "GET", "path": "/api/v2/groups/"},
    "/get_calendar/create_events_group/": {"method": "POST", "path": "/api/v2/groups/"},
    "/get_calendar/update_events_group/": {"method": "PATCH", "path": "/api/v2/groups/{group_id}/"},
    "/get_calendar/delete_event_groups/": {"method": "DELETE", "path": "/api/v2/groups/{group_id}/"},
    "/api/events/bulk-edit/": {"method": "PATCH or DELETE", "path": "/api/v2/events/{event_id}/", "note": "使用 scope 与 occurrence_ref"},
    "/api/todos/": {"method": "GET or POST", "path": "/api/v2/todos/"},
    "/api/todos/create/": {"method": "POST", "path": "/api/v2/todos/"},
    "/api/todos/update/": {"method": "PATCH", "path": "/api/v2/todos/{todo_id}/"},
    "/api/todos/delete/": {"method": "DELETE", "path": "/api/v2/todos/{todo_id}/"},
    "/api/todos/convert/": {"method": "POST", "path": "/api/v2/todos/{todo_id}/convert/"},
    "/api/reminders/": {"method": "GET or POST", "path": "/api/v2/reminders/"},
    "/api/reminders/create/": {"method": "POST", "path": "/api/v2/reminders/"},
    "/api/reminders/update/": {"method": "PATCH", "path": "/api/v2/reminders/{reminder_id}/"},
    "/api/reminders/update-status/": {"method": "POST", "path": "/api/v2/reminders/occurrences/action/"},
    "/api/reminders/bulk-edit/": {"method": "PATCH or DELETE", "path": "/api/v2/reminders/{reminder_id}/", "note": "使用 scope 与 occurrence_ref"},
    "/api/reminders/convert-to-single/": {"method": "PATCH", "path": "/api/v2/reminders/{reminder_id}/", "note": "scope=all, recurrence=null"},
    "/api/reminders/delete/": {"method": "DELETE", "path": "/api/v2/reminders/{reminder_id}/"},
    "/api/reminders/snooze/": {"method": "POST", "path": "/api/v2/reminders/occurrences/action/", "note": "action=snooze"},
    "/api/reminders/dismiss/": {"method": "POST", "path": "/api/v2/reminders/occurrences/action/", "note": "action=dismiss"},
    "/api/reminders/complete/": {"method": "POST", "path": "/api/v2/reminders/occurrences/action/", "note": "action=complete"},
    "/api/reminders/pending/": {"method": "GET", "path": "/api/v2/reminders/", "note": "使用窗口查询并按状态处理"},
    "/api/reminders/maintain/": {"method": "none", "path": "", "note": "实例维护已由按窗口展开取代"},
    "/api/reminders/mark-sent/": {"method": "POST", "path": "/api/v2/reminders/occurrences/action/", "note": "action=mark_sent"},
}


@api_view(["GET", "POST", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def retired_planner_v1_api(request, **kwargs):
    """Return a deterministic tombstone for every retired Planner V1 URL."""
    path = request.path
    if "share_group_id" in kwargs:
        replacement = {
            "method": "GET",
            "path": f"/api/v2/share-groups/{kwargs['share_group_id']}/occurrences/",
            "note": "from 与 to 必填",
        }
    else:
        replacement = LEGACY_PLANNER_REPLACEMENTS.get(path, {"method": "", "path": ""})
    return Response(
        {
            "error": "Planner V1 API 已停用；legacy Planner 归档已封存且禁止读写。",
            "code": "planner_v1_api_retired",
            "requested_path": path,
            "replacement": replacement,
        },
        status=status.HTTP_410_GONE,
    )
