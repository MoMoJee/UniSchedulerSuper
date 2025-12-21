
import json
import sys
import os
from django.conf import settings
from django.http import HttpRequest, JsonResponse

# Configure minimal Django settings
if not settings.configured:
    settings.configure(DEFAULT_CHARSET='utf-8')

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils.validators import validate_body

def test_schema_in_error_response():
    print("Testing schema in error response...")
    
    # Define a schema
    schema = {
        'name': {'type': str, 'required': True},
        'age': {'type': int, 'default': 18}
    }

    # Create a dummy view decorated with validate_body
    @validate_body(schema)
    def dummy_view(request):
        return JsonResponse({'status': 'ok'})

    # Create a request with invalid data (missing required field 'name', wrong type for age)
    request = HttpRequest()
    request.method = 'POST'
    # 'age' is string, should be int -> triggers validation error
    request._body = json.dumps({'age': 'not_an_int'}).encode('utf-8') 
    request.content_type = 'application/json'

    # Call the view
    response = dummy_view(request)

    # Check response status
    if response.status_code != 400:
        print(f"FAILED: Expected status 400, got {response.status_code}")
        return

    # Parse response content
    content = json.loads(response.content.decode('utf-8'))
    print(f"Response content: {json.dumps(content, ensure_ascii=False, indent=2)}")

    # Check if 'expected_schema' is in the response
    if 'expected_schema' not in content:
        print("FAILED: 'expected_schema' not found in response")
        return
    
    # Check schema content
    expected_schema = content['expected_schema']
    
    if expected_schema['name']['type'] != 'str':
        print("FAILED: name type mismatch")
        return
        
    if expected_schema['age']['default'] != 18:
        print("FAILED: age default mismatch")
        return

    print("SUCCESS: expected_schema is present and correct.")

if __name__ == "__main__":
    test_schema_in_error_response()
