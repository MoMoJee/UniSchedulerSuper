"""报告 Planner 相关模块绕过 legacy repository 的 UserData 调用。"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


PATTERNS = {
    'userdata_objects': re.compile(r'\bUserData\.objects\b'),
    'get_or_initialize': re.compile(r'\b(?:UserData\.)?get_or_initialize\s*\('),
    'set_value': re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\.set_value\s*\('),
}
SCANNED_DIRECTORIES = ('core', 'agent_service', 'caldav_service')
WHITELISTED_PATHS = {
    'core/planner/legacy.py',
    'core/management/commands/audit_planner_legacy.py',
    'core/management/commands/resolve_planner_legacy_duplicates.py',
    'core/models.py',
}


class Command(BaseCommand):
    help = '列出 Planner 相关代码中直接访问 UserData 的位置；默认只读输出 JSON。'

    def add_arguments(self, parser):
        parser.add_argument('--output', help='可选 JSON 输出路径。')

    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR)
        findings = []
        for directory in SCANNED_DIRECTORIES:
            for path in sorted((root / directory).rglob('*.py')):
                relative_path = path.relative_to(root).as_posix()
                if '/migrations/' in relative_path or '/tests/' in relative_path or relative_path.endswith('/__pycache__'):
                    continue
                for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
                    matches = [name for name, pattern in PATTERNS.items() if pattern.search(line)]
                    if matches:
                        findings.append(
                            {
                                'file': relative_path,
                                'line': number,
                                'patterns': matches,
                                'whitelisted': relative_path in WHITELISTED_PATHS,
                            }
                        )

        report = {
            'summary': {
                'finding_count': len(findings),
                'non_whitelisted_count': sum(not item['whitelisted'] for item in findings),
            },
            'findings': findings,
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if options.get('output'):
            path = Path(options['output'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + '\n', encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'调用面报告已写入: {path}'))
            return
        self.stdout.write(serialized)
