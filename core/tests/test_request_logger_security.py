from django.test import RequestFactory, SimpleTestCase

from core.middleware.request_logger import _sanitized_path


class RequestLoggerSecurityTests(SimpleTestCase):
    def test_sensitive_query_values_are_redacted(self):
        request = RequestFactory().get(
            "/api/calendar/feed/",
            {"token": "secret-token", "type": "all", "tag": ["a", "b"]},
        )
        path = _sanitized_path(request)
        self.assertNotIn("secret-token", path)
        self.assertIn("token=%5BREDACTED%5D", path)
        self.assertIn("type=all", path)
        self.assertEqual(path.count("tag="), 2)

