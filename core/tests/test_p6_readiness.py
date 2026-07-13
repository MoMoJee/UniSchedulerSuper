import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from core.models import UserData


class P6ReadinessCommandTests(TestCase):
    def test_audit_is_read_only_and_does_not_emit_legacy_body(self):
        user = User.objects.create_user('p6-empty')
        UserData.objects.create(user=user, key='ui_settings', value='TOP-SECRET-BODY')
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'readiness.json'
            before = UserData.objects.count()
            call_command('audit_planner_p6_readiness', output=str(output), strict=True, stdout=StringIO())
            report_text = output.read_text(encoding='utf-8')
            report = json.loads(report_text)
        self.assertEqual(UserData.objects.count(), before)
        self.assertTrue(report['read_only_verified'])
        self.assertEqual(report['classification_summary']['verified_clean'], 1)
        self.assertNotIn('TOP-SECRET-BODY', report_text)
