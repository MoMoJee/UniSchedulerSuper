"""Content-addressed static URLs for long-lived immutable browser caching."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static


register = template.Library()


@lru_cache(maxsize=256)
def _digest(path: str, mtime_ns: int, size: int) -> str:
    del mtime_ns, size  # They intentionally form part of the cache key.
    hasher = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(128 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


@register.simple_tag
def static_version(asset_path: str) -> str:
    """Append a digest that changes automatically whenever asset bytes change."""
    resolved = finders.find(asset_path)
    if isinstance(resolved, (list, tuple)):
        resolved = resolved[0] if resolved else None
    if not resolved:
        return static(asset_path)
    file_path = Path(resolved)
    stat = file_path.stat()
    return f'{static(asset_path)}?v={_digest(str(file_path), stat.st_mtime_ns, stat.st_size)}'
