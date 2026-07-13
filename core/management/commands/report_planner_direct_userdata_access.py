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
    'core/management/commands/audit_planner_ical_identity.py',
    # P5/P6 release smoke deliberately seeds an isolated legacy row so it can
    # prove that normalized CalDAV writes leave the legacy checksum untouched.
    # It is an offline verification command, never a runtime Planner path.
    'core/management/commands/run_p5_caldav_smoke.py',
    'core/management/commands/audit_planner_p6_readiness.py',
    'core/management/commands/audit_legacy_planner_archive.py',
    'core/management/commands/verify_no_legacy_planner_write.py',
    'core/management/commands/verify_planner_release.py',
    # Imported only by P6 release commands to classify/archive source rows.
    'core/planner/p6.py',
    'core/management/commands/resolve_planner_legacy_duplicates.py',
    'core/models.py',
}
# 这些模块只保存 Agent 配置、用量或用户偏好，并不读写 Planner 实体。
# 它们保留在报告中，避免扫描范围被静默缩小；但不作为 P1-B 的 Planner
# 旁路门禁。
NON_PLANNER_PATHS = {
    'agent_service/context_optimizer.py',
    'agent_service/views_config_api.py',
    'core/services/event_service.py',
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
                source = path.read_text(encoding='utf-8')
                uses_compat_adapter = 'core.planner.legacy import PlannerUserDataCompat as UserData' in source
                for number, line in enumerate(source.splitlines(), start=1):
                    matches = [name for name, pattern in PATTERNS.items() if pattern.search(line)]
                    if matches:
                        via_compat_adapter = uses_compat_adapter
                        out_of_planner_scope = relative_path in NON_PLANNER_PATHS
                        findings.append(
                            {
                                'file': relative_path,
                                'line': number,
                                'patterns': matches,
                                'whitelisted': relative_path in WHITELISTED_PATHS or via_compat_adapter,
                                'via_compat_adapter': via_compat_adapter,
                                'out_of_planner_scope': out_of_planner_scope,
                            }
                        )

        report = {
            'summary': {
                'finding_count': len(findings),
                'non_whitelisted_count': sum(not item['whitelisted'] for item in findings),
                'out_of_planner_scope_count': sum(item['out_of_planner_scope'] for item in findings),
                'planner_bypass_count': sum(
                    not item['whitelisted'] and not item['out_of_planner_scope']
                    for item in findings
                ),
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
