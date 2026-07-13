"""Django template helpers for the hashed Vite frontend build."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.template import TemplateSyntaxError
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe


register = template.Library()


@lru_cache(maxsize=1)
def _load_manifest() -> dict[str, object]:
    """Load the Vite manifest from the staticfiles finder once per process."""
    manifest_path = finders.find('react/manifest.json')
    if isinstance(manifest_path, (list, tuple)):
        manifest_path = manifest_path[0] if manifest_path else None
    if not manifest_path:
        raise TemplateSyntaxError(
            '未找到 React Vite manifest。请先在 frontend/ 执行 npm run build 并运行 collectstatic。'
        )
    try:
        return json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateSyntaxError(f'无法读取 React Vite manifest：{exc}') from exc


@register.simple_tag
def vite_entry(entry: str = 'index.html') -> str:
    """Render development source tags or production manifest tags for an entry.

    Vite's production manifest uses ``index.html`` as the SPA entry, while the
    dev server needs the source module itself. Keeping that mapping here avoids
    leaking build-tool details into Django templates.
    """
    dev_server = settings.VITE_DEV_SERVER_URL
    if dev_server:
        return mark_safe(
            format_html('<script type="module" src="{}/@vite/client"></script>', dev_server)
            + format_html('<script type="module" src="{}/src/main.tsx"></script>', dev_server)
        )

    manifest = _load_manifest()
    record = manifest.get(entry)
    if not isinstance(record, dict) or not isinstance(record.get('file'), str):
        raise TemplateSyntaxError(f'React Vite manifest 缺少入口 {entry!r}。')

    tags = []
    for stylesheet in record.get('css', []):
        if isinstance(stylesheet, str):
            tags.append(format_html('<link rel="stylesheet" href="{}">', static(f'react/{stylesheet}')))
    tags.append(format_html('<script type="module" src="{}"></script>', static(f"react/{record['file']}")))
    return mark_safe(''.join(tags))
