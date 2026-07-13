from unittest.mock import patch

from django.test import SimpleTestCase

from agent_service.tools.variflight_tools import (
    VariFlightMCPClient,
    parse_mcp_result,
    query_flight_by_number,
)


class VariFlightResultCompatibilityTests(SimpleTestCase):
    def setUp(self):
        self.payload = {
            'code': 200,
            'message': 'Success',
            'data': [{
                'FlightNo': 'CA1234',
                'FlightCompany': '中国国际航空',
                'FlightDep': '克拉玛依',
                'FlightArr': '北京',
                'FlightDepAirport': '克拉玛依古海',
                'FlightArrAirport': '北京首都',
                'FlightDeptimePlanDate': '2026-07-13 12:40:00',
                'FlightArrtimePlanDate': '2026-07-13 16:45:00',
                'FlightState': '到达',
            }],
        }

    def test_parses_langchain_mcp_text_content_block_list(self):
        result = [{'type': 'text', 'text': f'Flight details: {self.payload!r}', 'id': 'lc-test'}]
        self.assertEqual(parse_mcp_result(result), self.payload)

    def test_direct_provider_data_list_is_wrapped_as_success(self):
        data = [{'FlightNo': 'CA1234'}]
        self.assertEqual(parse_mcp_result(data), {'code': 200, 'data': data})

    def test_public_tool_formats_new_adapter_shape_instead_of_format_error(self):
        result = [{'type': 'text', 'text': f'Flight details: {self.payload!r}', 'id': 'lc-test'}]
        with patch.object(VariFlightMCPClient, 'invoke_tool', return_value=result):
            output = query_flight_by_number.func('CA1234', '2026-07-13')
        self.assertIn('CA1234', output)
        self.assertNotIn('返回格式异常', output)
