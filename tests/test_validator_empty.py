
import unittest
import json
from django.http import HttpRequest, JsonResponse
from core.utils.validators import validate_body

# Mock Django Request
class MockRequest:
    def __init__(self, data):
        self.body = json.dumps(data).encode('utf-8')
        self.method = 'POST'

class TestValidatorEmpty(unittest.TestCase):
    def test_empty_string_allowed(self):
        schema = {
            'ddl': {'type': str, 'required': False}
        }
        
        @validate_body(schema)
        def view(request):
            return JsonResponse({'status': 'ok', 'data': request.validated_data})

        # Case 1: ddl is empty string
        req = MockRequest({'ddl': ''})
        response = view(req)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)['data']
        self.assertEqual(data['ddl'], '')

    def test_none_skipped(self):
        schema = {
            'ddl': {'type': str, 'required': False}
        }
        
        @validate_body(schema)
        def view(request):
            return JsonResponse({'status': 'ok', 'data': request.validated_data})

        # Case 2: ddl is null
        req = MockRequest({'ddl': None})
        response = view(req)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)['data']
        # ddl should be missing from validated_data
        self.assertNotIn('ddl', data)

    def test_choices_with_empty(self):
        schema = {
            'importance': {'type': str, 'choices': ['important', 'normal']}
        }
        
        @validate_body(schema)
        def view(request):
            return JsonResponse({'status': 'ok', 'data': request.validated_data})

        # Case 3: importance is empty string, but not in choices
        req = MockRequest({'importance': ''})
        response = view(req)
        self.assertEqual(response.status_code, 400) # Should fail

    def test_choices_including_empty(self):
        schema = {
            'importance': {'type': str, 'choices': ['important', 'normal', '']}
        }
        
        @validate_body(schema)
        def view(request):
            return JsonResponse({'status': 'ok', 'data': request.validated_data})

        # Case 4: importance is empty string, and IS in choices
        req = MockRequest({'importance': ''})
        response = view(req)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)['data']
        self.assertEqual(data['importance'], '')

if __name__ == '__main__':
    unittest.main()
