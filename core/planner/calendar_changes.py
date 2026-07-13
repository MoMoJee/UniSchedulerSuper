"""CalDAV collection 单调版本与 tombstone 的唯一写入器。"""

from __future__ import annotations

from uuid import uuid4

from core.models import CalendarChange, CalendarCollectionVersion


class CalendarCollectionChangeWriter:
    COLLECTION_TYPE = 'caldav'

    @classmethod
    def record(
        cls, user, *, collection_id: str, resource_type: str,
        resource_public_id: str, action: str, etag: str,
    ) -> CalendarChange:
        collection, _ = CalendarCollectionVersion.objects.select_for_update().get_or_create(
            user=user, collection_type=cls.COLLECTION_TYPE, collection_id=collection_id
        )
        collection.version += 1
        collection.sync_token = str(uuid4())
        collection.save(update_fields={'version', 'sync_token', 'updated_at'})
        return CalendarChange.objects.create(
            collection=collection, token=collection.version, resource_type=resource_type,
            resource_public_id=resource_public_id, action=action, etag=etag,
        )
