from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.template import Context, Template, TemplateSyntaxError
from django.test import Client, TestCase, override_settings

from core.templatetags import frontend_assets


class ReactFrontendShellTests(TestCase):
    def setUp(self):
        self.user = self._create_user('react-shell-user')

    def _create_user(self, username: str):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(username=username, password='safe-test-password')

    @override_settings(FRONTEND_MODE='react', VITE_DEV_SERVER_URL='http://127.0.0.1:5173')
    def test_react_home_requires_login_and_emits_safe_bootstrap(self):
        redirect = self.client.get('/home/')
        self.assertEqual(redirect.status_code, 302)
        self.assertIn('/user_login', redirect['Location'])

        self.client.force_login(self.user)
        response = self.client.get('/home/')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home_react.html')
        self.assertContains(response, 'id="root"')
        self.assertContains(response, 'id="frontend-bootstrap"')
        self.assertContains(response, 'http://127.0.0.1:5173/@vite/client')
        self.assertContains(response, 'http://127.0.0.1:5173/src/main.tsx')
        self.assertNotContains(response, 'js/planner-v2-client.js')
        self.assertNotContains(response, 'js/event-manager.js')

    @override_settings(FRONTEND_MODE='legacy')
    def test_legacy_mode_keeps_existing_home_template(self):
        self.client.force_login(self.user)
        response = self.client.get('/home/')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')
        self.assertContains(response, 'js/planner-v2-client.js')

    @override_settings(FRONTEND_MODE='react', VITE_DEV_SERVER_URL='http://127.0.0.1:5173')
    def test_react_home_supports_direct_spa_routes_but_legacy_does_not(self):
        self.client.force_login(self.user)
        react_response = self.client.get('/home/todos/')

        self.assertEqual(react_response.status_code, 200)
        self.assertTemplateUsed(react_response, 'home_react.html')

        with self.settings(FRONTEND_MODE='legacy'):
            legacy_response = self.client.get('/home/todos/')
        self.assertEqual(legacy_response.status_code, 404)

    @override_settings(FRONTEND_MODE='react', VITE_DEV_SERVER_URL='http://127.0.0.1:5173')
    def test_react_shell_issues_csrf_cookie_for_same_origin_writes(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        home = csrf_client.get('/home/')
        csrf_token = csrf_client.cookies['csrftoken'].value

        self.assertEqual(home.status_code, 200)
        self.assertContains(home, '"csrfToken"')

        rejected = csrf_client.post(
            '/api/user/change-username/',
            data=json.dumps({'new_username': 'csrf-shell-user', 'password': 'safe-test-password'}),
            content_type='application/json',
        )
        self.assertEqual(rejected.status_code, 403)

        accepted = csrf_client.post(
            '/api/user/change-username/',
            data=json.dumps({'new_username': 'csrf-shell-user', 'password': 'safe-test-password'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(accepted.status_code, 200)

    @patch('core.templatetags.frontend_assets.static')
    def test_production_manifest_renders_hashed_css_and_module(self, mock_static):
        mock_static.side_effect = lambda path: f'/static/{path}'
        with TemporaryDirectory() as directory:
            manifest_path = Path(directory) / 'manifest.json'
            manifest_path.write_text(
                json.dumps({
                    'index.html': {
                        'file': 'assets/main-123.js',
                        'css': ['assets/main-456.css'],
                    }
                }),
                encoding='utf-8',
            )
            frontend_assets._load_manifest.cache_clear()
            with patch('core.templatetags.frontend_assets.finders.find', return_value=str(manifest_path)):
                rendered = Template(
                    '{% load frontend_assets %}{% vite_entry "index.html" %}'
                ).render(Context())

        frontend_assets._load_manifest.cache_clear()
        self.assertIn('/static/react/assets/main-456.css', rendered)
        self.assertIn('/static/react/assets/main-123.js', rendered)

    def test_missing_production_manifest_fails_closed(self):
        frontend_assets._load_manifest.cache_clear()
        with patch('core.templatetags.frontend_assets.finders.find', return_value=None):
            with self.assertRaises(TemplateSyntaxError):
                Template('{% load frontend_assets %}{% vite_entry "index.html" %}').render(Context())
        frontend_assets._load_manifest.cache_clear()
