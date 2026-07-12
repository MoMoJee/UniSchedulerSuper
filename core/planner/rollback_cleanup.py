"""P4 legacy rollback 清理范围与业务投影校验。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

from core.planner.snapshots import MODEL_LABELS


NORMALIZED_REVERSION_LABELS = tuple(dict.fromkeys(MODEL_LABELS + (
    'core.EventGroup', 'core.CalendarCollectionVersion', 'core.CalendarChange',
    'core.ShareGroupCalendarVersion', 'core.PlannerChangeSet',
)))

BUSINESS_CHECKSUM_LABELS = tuple(dict.fromkeys(MODEL_LABELS + (
    'core.UserData', 'core.EventGroup', 'core.CalendarCollectionVersion',
    'core.CalendarChange', 'core.ShareGroupCalendarVersion',
    'core.PlannerLegacyIdMap', 'core.PlannerMigrationState',
    'core.PlannerMigrationIssue', 'core.PlannerCohortAssignment',
)))


def userdata_version_key(version) -> str | None:
    """从 reversion 序列化正文读取 UserData.key，不依赖当前行仍然存在。"""
    try:
        objects = json.loads(version.serialized_data or '[]')
        return objects[0]['fields'].get('key') if objects else None
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def database_path() -> Path:
    return Path(settings.DATABASES['default']['NAME'])


def database_sha256(path: Path | None = None) -> str:
    target = path or database_path()
    digest = hashlib.sha256()
    with target.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def business_projection() -> dict:
    projection = {}
    for label in BUSINESS_CHECKSUM_LABELS:
        model = apps.get_model(*label.split('.', 1))
        fields = [field.attname for field in model._meta.concrete_fields]
        rows = list(model._base_manager.order_by(model._meta.pk.attname).values(*fields))
        projection[label] = {'count': len(rows), 'rows': rows}
    return projection


def business_checksum() -> tuple[str, dict[str, int]]:
    projection = business_projection()
    raw = json.dumps(
        projection, cls=DjangoJSONEncoder, ensure_ascii=False,
        sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(raw).hexdigest(), {
        label: payload['count'] for label, payload in projection.items()
    }


def delete_ids(model, ids, *, chunk_size: int = 500) -> int:
    ids = list(ids)
    deleted = 0
    for offset in range(0, len(ids), chunk_size):
        count, _ = model._base_manager.filter(pk__in=ids[offset:offset + chunk_size]).delete()
        deleted += count
    return deleted


def affected_refs_from_payloads(*payloads: dict) -> list[dict[str, str]]:
    """从旧 ChangeSet payload 提取不含业务正文的最小实体引用。"""
    refs = set()
    type_fields = {
        'event': ('event_id', 'id'), 'series': ('series_id',),
        'todo': ('todo_id', 'id'), 'reminder': ('reminder_id', 'id'),
        'group': ('group_id', 'id'),
    }
    for payload in payloads:
        for key, value in (payload or {}).items():
            if not isinstance(value, dict) or key not in type_fields:
                continue
            for field in type_fields[key]:
                public_id = value.get(field)
                if public_id:
                    refs.add((key, str(public_id)))
                    break
    return [{'type': item_type, 'id': public_id} for item_type, public_id in sorted(refs)]
