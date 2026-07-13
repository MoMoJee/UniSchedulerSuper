import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from core.templatetags.static_version import _digest, static_version


class StaticVersionTagTests(SimpleTestCase):
    def test_version_is_derived_from_content_and_changes_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / 'asset.js'
            asset.write_text('first', encoding='utf-8')
            with patch('core.templatetags.static_version.finders.find', return_value=str(asset)):
                first = static_version('js/asset.js')
                asset.write_text('second', encoding='utf-8')
                os.utime(asset, None)
                second = static_version('js/asset.js')
        self.assertNotEqual(first, second)
        self.assertRegex(first, r'/static/js/asset\.js\?v=[0-9a-f]{16}$')
        self.assertRegex(second, r'/static/js/asset\.js\?v=[0-9a-f]{16}$')
        _digest.cache_clear()

    def test_home_template_has_no_manual_static_version_numbers(self):
        template_path = Path(__file__).resolve().parents[1] / 'templates' / 'home.html'
        source = template_path.read_text(encoding='utf-8')
        self.assertNotRegex(source, r"\{% static '[^']+' %\}\?v=")
        self.assertIn("{% static_version 'js/planner-v2-client.js' %}", source)
