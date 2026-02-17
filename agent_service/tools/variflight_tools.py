"""
VariFlight 飞常准航班查询工具封装

封装 VariFlight MCP 服务的工具，提供：
1. 航班实时动态查询 (searchFlightsByNumber) - 翻译优化
2. OD对航班查询 (searchFlightsByDepArr) - 翻译优化+筛选
3. 航班行程价格查询 (searchFlightItineraries) - 略微优化
4. 航班中转方案查询 (searchFlightTransferInfo) - 略微优化

禁用的工具（意义不大或已有替代）：
- getRealtimeLocationByAnum - 飞机实时定位
- getTodayDate - 获取当天日期
- getFutureWeatherByAirport - 机场未来天气
- flightHappinessIndex - 乘机舒适度
"""

import asyncio
import json
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Literal
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from logger import logger
from config.api_keys_manager import APIKeyManager

# ==================== MCP 客户端封装 ====================

class VariFlightMCPClient:
    """VariFlight MCP 客户端封装"""
    
    _instance = None
    _client = None
    _tools = None
    _lock = threading.Lock()
    
    @classmethod
    def get_config(cls) -> Optional[Dict[str, Any]]:
        """获取 VariFlight MCP 配置"""
        config = APIKeyManager.get_mcp_service_config('VariFlight')
        return config
    
    @classmethod
    async def _init_client(cls):
        """初始化 MCP 客户端（异步）"""
        if cls._client is not None:
            return cls._client
        
        config = cls.get_config()
        if not config:
            logger.warning("VariFlight MCP 服务未配置或未启用")
            return None
        
        mcp_url = config.get('mcp_url', '')
        api_key = config.get('api_key', '')
        transport = config.get('transport', 'streamable_http')
        
        if not mcp_url:
            logger.warning("VariFlight MCP URL 未配置")
            return None
        
        # 构建带 API Key 的 URL
        if api_key:
            if '?' in mcp_url:
                full_url = f"{mcp_url}&api_key={api_key}"
            else:
                full_url = f"{mcp_url}?api_key={api_key}"
        else:
            full_url = mcp_url
        
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            
            cls._client = MultiServerMCPClient({
                "variflight": {
                    "url": full_url,
                    "transport": transport
                }
            })
            
            # 获取工具
            cls._tools = await cls._client.get_tools()
            tool_names = [t.name for t in cls._tools]
            logger.info(f"✅ VariFlight MCP 客户端初始化成功，共 {len(cls._tools)} 个工具: {tool_names}")
            
            return cls._client
        except Exception as e:
            logger.error(f"❌ VariFlight MCP 客户端初始化失败: {e}")
            cls._client = None
            cls._tools = None
            return None
    
    @classmethod
    def _run_async(cls, coro):
        """在新线程中运行异步代码"""
        result = None
        exception = None
        
        def run():
            nonlocal result, exception
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(coro)
                finally:
                    loop.close()
            except Exception as e:
                exception = e
        
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=60)  # 60秒超时
        
        if exception:
            raise exception
        return result
    
    @classmethod
    def get_tool(cls, tool_name: str):
        """
        获取指定的 MCP 工具
        
        支持多种工具名称格式匹配：
        - 完整名称: mcp_variflight_searchFlightsByNumber
        - 简短名称: searchFlightsByNumber
        """
        with cls._lock:
            if cls._tools is None:
                cls._run_async(cls._init_client())
            
            if cls._tools is None:
                return None
            
            # 尝试精确匹配
            for tool in cls._tools:
                if tool.name == tool_name:
                    return tool
            
            # 尝试部分匹配（去除前缀）
            short_name = tool_name.replace("mcp_variflight_", "")
            for tool in cls._tools:
                # 检查工具名是否以 short_name 结尾
                if tool.name.endswith(short_name):
                    return tool
                # 检查工具名去除前缀后是否匹配
                tool_short = tool.name.replace("mcp_variflight_", "").replace("variflight_", "")
                if tool_short == short_name:
                    return tool
            
            logger.warning(f"[VariFlight] 未找到工具: {tool_name}, 可用工具: {[t.name for t in cls._tools]}")
            return None
    
    @classmethod
    def invoke_tool(cls, tool_name: str, args: dict) -> Any:
        """调用 MCP 工具（同步封装）"""
        tool = cls.get_tool(tool_name)
        if tool is None:
            raise ValueError(f"工具 {tool_name} 不可用")
        
        # 过滤掉 None 值的参数
        filtered_args = {k: v for k, v in args.items() if v is not None}
        
        # MCP 工具的 coroutine 是异步函数，需要用关键字参数调用
        if tool.coroutine:
            result = cls._run_async(tool.coroutine(**filtered_args))
        else:
            result = tool.invoke(filtered_args)
        
        # MCP 工具可能返回 tuple (result_string, artifact)，提取第一个元素
        if isinstance(result, tuple):
            result = result[0]
        
        return result


def parse_mcp_result(result: Any) -> dict:
    """
    解析 MCP 工具返回的结果
    
    MCP 工具返回格式可能是：
    1. 字典 {'code': 200, 'data': ...}
    2. 带前缀的字符串 "Flight search results: {'code': 200, ...}"
    3. JSON 字符串 '{"code": 200, ...}'
    
    Returns:
        解析后的字典，如果解析失败返回 {'error': '错误信息', 'raw': 原始内容}
    """
    import re
    
    if isinstance(result, dict):
        return result
    
    if not isinstance(result, str):
        return {'error': f'返回格式异常 (类型: {type(result).__name__})', 'raw': str(result)}
    
    # 尝试直接 JSON 解析
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        pass
    
    # 尝试提取 JSON 部分（处理 "Flight search results: {...}" 格式）
    # 查找第一个 { 和最后一个 }
    first_brace = result.find('{')
    last_brace = result.rfind('}')
    
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_str = result[first_brace:last_brace + 1]
        try:
            # Python dict 字符串格式转 JSON（单引号转双引号）
            # 注意：这是简化处理，可能不适用于所有情况
            parsed = eval(json_str)  # 安全风险较低，因为数据来自可信 MCP
            if isinstance(parsed, dict):
                return parsed
        except:
            pass
        
        try:
            return json.loads(json_str)
        except:
            pass
    
    # 解析失败，返回原始字符串作为 data
    return {'code': 200, 'data': result, 'raw_string': True}


# ==================== 字段翻译映射 ====================

FLIGHT_FIELD_TRANSLATIONS = {
    # 航班基本信息
    'FlightNo': '航班号',
    'FlightCompany': '航空公司',
    'FlightDepcode': '出发机场代码',
    'FlightArrcode': '到达机场代码',
    'FlightDep': '出发城市',
    'FlightArr': '到达城市',
    'FlightDepAirport': '出发机场',
    'FlightArrAirport': '到达机场',
    'FlightHTerminal': '出发航站楼',
    'FlightTerminal': '到达航站楼',
    
    # 时间信息
    'FlightDeptimePlanDate': '计划起飞时间',
    'FlightArrtimePlanDate': '计划到达时间',
    'FlightDeptimeDate': '实际起飞时间',
    'FlightArrtimeDate': '实际到达时间',
    'FlightDeptimeReadyDate': '预计起飞时间',
    'FlightArrtimeReadyDate': '预计到达时间',
    'FlightDuration': '飞行时长(分钟)',
    
    # 状态信息
    'FlightState': '航班状态',
    'DelayReason': '延误原因',
    
    # 机场服务信息
    'CheckinTable': '值机柜台',
    'BoardGate': '登机口',
    'BaggageID': '行李转盘',
    'CheckDoor': '安检口',
    'LastCheckinTime': '最晚值机时间',
    'EstimateBoardingStartTime': '预计登机开始时间',
    'EstimateBoardingEndTime': '预计登机结束时间',
    
    # 飞机信息
    'AircraftNumber': '飞机注册号',
    'ftype': '机型代码',
    'generic': '机型全称',
    'FlightYear': '机龄(年)',
    
    # 准点率
    'OntimeRate': '出发准点率',
    'ArrOntimeRate': '到达准点率',
    
    # 天气信息
    'DepWeather': '出发地天气',
    'ArrWeather': '到达地天气',
    
    # 其他
    'distance': '飞行距离(公里)',
    'bridge': '出发停靠',
    'arr_bridge': '到达停靠',
    'ShareFlightNo': '共享航班号',
    'StopCity': '经停城市',
    'StopAirportCode': '经停机场代码',
}

# 航班状态翻译
FLIGHT_STATE_TRANSLATIONS = {
    '计划': '计划中',
    '起飞': '已起飞',
    '到达': '已到达',
    '延误': '延误',
    '取消': '已取消',
    '提前取消': '提前取消',
    '备降': '备降',
    '返航': '返航',
}


def translate_flight_data(data: dict, include_fields: Optional[List[str]] = None) -> dict:
    """
    翻译航班数据字段
    
    Args:
        data: 原始航班数据
        include_fields: 要包含的字段列表（原始字段名），None 表示包含所有重要字段
    
    Returns:
        翻译后的数据
    """
    # 默认包含的重要字段
    if include_fields is None:
        include_fields = [
            'FlightNo', 'FlightCompany', 'FlightDep', 'FlightArr',
            'FlightDepAirport', 'FlightArrAirport', 'FlightHTerminal', 'FlightTerminal',
            'FlightDeptimePlanDate', 'FlightArrtimePlanDate',
            'FlightDeptimeDate', 'FlightArrtimeDate',
            'FlightState', 'DelayReason',
            'CheckinTable', 'BoardGate', 'BaggageID',
            'LastCheckinTime', 'EstimateBoardingStartTime',
            'ftype', 'generic', 'FlightYear',
            'OntimeRate', 'ArrOntimeRate',
            'FlightDuration', 'distance',
            'StopCity', 'ShareFlightNo'
        ]
    
    result = {}
    for field in include_fields:
        if field in data and data[field]:  # 只包含非空值
            translated_key = FLIGHT_FIELD_TRANSLATIONS.get(field, field)
            value = data[field]
            
            # 特殊处理航班状态
            if field == 'FlightState':
                value = FLIGHT_STATE_TRANSLATIONS.get(value, value)
            
            result[translated_key] = value
    
    return result


def format_flight_info(flight: dict) -> str:
    """将航班信息格式化为易读的字符串"""
    lines = []
    
    # 基本信息
    lines.append(f"【{flight.get('航班号', 'N/A')}】 {flight.get('航空公司', '')}")
    lines.append(f"  {flight.get('出发城市', '')}({flight.get('出发机场', '')}) → {flight.get('到达城市', '')}({flight.get('到达机场', '')})")
    
    # 时间信息
    plan_dep = flight.get('计划起飞时间', '')
    plan_arr = flight.get('计划到达时间', '')
    actual_dep = flight.get('实际起飞时间', '')
    actual_arr = flight.get('实际到达时间', '')
    
    if plan_dep:
        lines.append(f"  计划: {plan_dep} → {plan_arr}")
    if actual_dep:
        lines.append(f"  实际: {actual_dep} → {actual_arr}")
    
    # 状态
    state = flight.get('航班状态', '')
    delay_reason = flight.get('延误原因', '')
    if state:
        state_line = f"  状态: {state}"
        if delay_reason:
            state_line += f" ({delay_reason})"
        lines.append(state_line)
    
    # 航站楼/登机口
    dep_terminal = flight.get('出发航站楼', '')
    arr_terminal = flight.get('到达航站楼', '')
    gate = flight.get('登机口', '')
    if dep_terminal or gate:
        terminal_info = []
        if dep_terminal:
            terminal_info.append(f"出发{dep_terminal}")
        if arr_terminal:
            terminal_info.append(f"到达{arr_terminal}")
        if gate:
            terminal_info.append(f"登机口{gate}")
        lines.append(f"  {', '.join(terminal_info)}")
    
    # 准点率
    ontime = flight.get('出发准点率', '')
    if ontime:
        lines.append(f"  准点率: {ontime}")
    
    return '\n'.join(lines)


# ==================== 工具参数模型 ====================

class FlightByNumberInput(BaseModel):
    """航班号查询参数"""
    flight_number: str = Field(
        description="航班号，包含航空公司代码，如 CA1523、MU5100、CZ3969"
    )
    date: str = Field(
        description="航班日期，格式 YYYY-MM-DD，如 2026-01-31"
    )


class FlightByRouteInput(BaseModel):
    """航线查询参数（带筛选）"""
    dep_city: str = Field(
        description="出发城市三字码，如 BJS(北京)、SHA(上海)、CAN(广州)、SZX(深圳)"
    )
    arr_city: str = Field(
        description="到达城市三字码，如 BJS(北京)、SHA(上海)、CAN(广州)、SZX(深圳)"
    )
    date: str = Field(
        description="航班日期，格式 YYYY-MM-DD"
    )
    # 筛选参数
    airline: Optional[str] = Field(
        default=None,
        description="航空公司筛选，如 CA(国航)、MU(东航)、CZ(南航)、HU(海航)，不填则返回所有"
    )
    time_range: Optional[str] = Field(
        default=None,
        description="时间范围筛选，格式 HH:MM-HH:MM，如 08:00-12:00 表示只返回8点到12点起飞的航班"
    )
    status: Optional[str] = Field(
        default=None,
        description="航班状态筛选，可选值：计划/起飞/到达/延误/取消，不填则返回所有"
    )
    max_results: int = Field(
        default=10,
        description="最大返回数量，默认10条，最多50条"
    )


class FlightItineraryInput(BaseModel):
    """航班行程价格查询参数"""
    dep_city: str = Field(
        description="出发城市三字码，如 BJS(北京)、SHA(上海)、CAN(广州)"
    )
    arr_city: str = Field(
        description="到达城市三字码，如 BJS(北京)、SHA(上海)、CAN(广州)"
    )
    date: str = Field(
        description="出发日期，格式 YYYY-MM-DD"
    )


class FlightTransferInput(BaseModel):
    """航班中转方案查询参数"""
    dep_city: str = Field(
        description="出发城市三字码，如 BJS(北京)、SHA(上海)、CAN(广州)"
    )
    arr_city: str = Field(
        description="到达城市三字码，如 TYO(东京)、SEL(首尔)、SIN(新加坡)"
    )
    date: str = Field(
        description="出发日期，格式 YYYY-MM-DD"
    )


# ==================== 工具实现 ====================

@tool(args_schema=FlightByNumberInput)
def query_flight_by_number(flight_number: str, date: str) -> str:
    """
    查询航班实时动态
    
    根据航班号查询航班的详细信息，包括：
    - 起降时间（计划/实际）
    - 航班状态（计划/起飞/到达/延误/取消）
    - 值机柜台、登机口、行李转盘
    - 机型、机龄、准点率
    
    适用场景：
    - 查询具体航班的实时状态
    - 了解航班延误情况
    - 获取登机信息
    """
    try:
        # 调用 MCP 工具
        result = VariFlightMCPClient.invoke_tool(
            "mcp_variflight_searchFlightsByNumber",
            {
                "fnum": flight_number,
                "date": date,
                "dep": None,
                "arr": None
            }
        )
        
        # 解析结果
        result = parse_mcp_result(result)
        
        if 'error' in result:
            return f"查询失败：{result['error']}"
        
        if result.get('code') != 200:
            return f"查询失败：{result.get('message', '未知错误')}"
        
        data = result.get('data', [])
        
        # 处理 data 是错误对象的情况
        if isinstance(data, dict):
            if 'error' in data or 'error_code' in data:
                error_msg = data.get('error', data.get('message', '未知错误'))
                return f"未找到航班 {flight_number} 在 {date} 的信息：{error_msg}"
            data = [data]
        
        if not data or not isinstance(data, list):
            return f"未找到航班 {flight_number} 在 {date} 的信息"
        
        # 翻译并格式化每个航班
        formatted_flights = []
        for flight in data:
            if not isinstance(flight, dict):
                continue
            translated = translate_flight_data(flight)
            formatted_flights.append(format_flight_info(translated))
        
        return '\n\n'.join(formatted_flights)
        
    except Exception as e:
        logger.exception(f"[VariFlight] 查询航班动态失败: {e}")
        return f"查询失败：{str(e)}"


@tool(args_schema=FlightByRouteInput)
def query_flights_by_route(
    dep_city: str,
    arr_city: str,
    date: str,
    airline: Optional[str] = None,
    time_range: Optional[str] = None,
    status: Optional[str] = None,
    max_results: int = 10
) -> str:
    """
    查询两城市间的航班列表（带筛选）
    
    查询指定日期从出发城市到到达城市的所有航班，支持筛选：
    - 按航空公司筛选
    - 按起飞时间段筛选
    - 按航班状态筛选
    
    返回航班的简要信息列表，便于快速浏览比较。
    
    适用场景：
    - 查看某航线当天所有航班
    - 筛选特定时间段的航班
    - 查看特定航空公司的航班
    """
    try:
        # 调用 MCP 工具
        result = VariFlightMCPClient.invoke_tool(
            "mcp_variflight_searchFlightsByDepArr",
            {
                "date": date,
                "depcity": dep_city,
                "arrcity": arr_city,
                "dep": None,
                "arr": None
            }
        )
        
        # 解析结果
        result = parse_mcp_result(result)
        
        if 'error' in result:
            return f"查询失败：{result['error']}"
        
        if result.get('code') != 200:
            return f"查询失败：{result.get('message', '未知错误')}"
        
        data = result.get('data', [])
        
        # 处理 data 是错误对象的情况 {'error_code': 10, 'error': '暂无数据'}
        if isinstance(data, dict):
            if 'error' in data or 'error_code' in data:
                error_msg = data.get('error', data.get('message', '未知错误'))
                return f"未找到 {date} 从 {dep_city} 到 {arr_city} 的航班：{error_msg}"
            # 如果 data 是单个航班字典，转为列表
            data = [data]
        
        if not data or not isinstance(data, list):
            return f"未找到 {date} 从 {dep_city} 到 {arr_city} 的航班"
        
        # ========== 本地筛选 ==========
        filtered_flights = []
        
        for flight in data:
            # 跳过非字典类型
            if not isinstance(flight, dict):
                continue
            
            # 航空公司筛选
            if airline:
                flight_no = flight.get('FlightNo', '')
                if not flight_no.upper().startswith(airline.upper()):
                    continue
            
            # 时间范围筛选
            if time_range:
                try:
                    start_time, end_time = time_range.split('-')
                    dep_time = flight.get('FlightDeptimePlanDate', '')
                    if dep_time:
                        flight_hour_min = dep_time.split(' ')[1][:5] if ' ' in dep_time else dep_time[:5]
                        if not (start_time <= flight_hour_min <= end_time):
                            continue
                except:
                    pass  # 时间格式错误，跳过筛选
            
            # 状态筛选
            if status:
                flight_state = flight.get('FlightState', '')
                if status not in flight_state:
                    continue
            
            filtered_flights.append(flight)
        
        if not filtered_flights:
            filter_desc = []
            if airline:
                filter_desc.append(f"航司={airline}")
            if time_range:
                filter_desc.append(f"时间={time_range}")
            if status:
                filter_desc.append(f"状态={status}")
            return f"未找到符合条件的航班（筛选条件：{', '.join(filter_desc) if filter_desc else '无'}）"
        
        # 限制返回数量
        max_results = min(max_results, 50)
        total_count = len(filtered_flights)
        filtered_flights = filtered_flights[:max_results]
        
        # ========== 格式化输出 ==========
        output_lines = [f"共找到 {total_count} 个航班，显示前 {len(filtered_flights)} 个：\n"]
        
        for i, flight in enumerate(filtered_flights, 1):
            flight_no = flight.get('FlightNo', 'N/A')
            company = flight.get('FlightCompany', '')[:6]  # 截断航空公司名
            dep_airport = flight.get('FlightDepAirport', '')
            arr_airport = flight.get('FlightArrAirport', '')
            plan_dep = flight.get('FlightDeptimePlanDate', '').split(' ')[1][:5] if flight.get('FlightDeptimePlanDate') else ''
            plan_arr = flight.get('FlightArrtimePlanDate', '').split(' ')[1][:5] if flight.get('FlightArrtimePlanDate') else ''
            state = flight.get('FlightState', '计划')
            state = FLIGHT_STATE_TRANSLATIONS.get(state, state)
            dep_terminal = flight.get('FlightHTerminal', '')
            arr_terminal = flight.get('FlightTerminal', '')
            ontime = flight.get('OntimeRate', '')
            
            line = f"{i}. {flight_no} {company}"
            line += f"\n   {plan_dep}({dep_terminal or '-'}) → {plan_arr}({arr_terminal or '-'}) | {state}"
            if ontime:
                line += f" | 准点率{ontime}"
            output_lines.append(line)
        
        return '\n'.join(output_lines)
        
    except Exception as e:
        logger.exception(f"[VariFlight] 查询航线失败: {e}")
        return f"查询失败：{str(e)}"


@tool(args_schema=FlightItineraryInput)
def query_flight_itineraries(dep_city: str, arr_city: str, date: str) -> str:
    """
    查询航班行程和票价
    
    查询指定日期从出发城市到到达城市的航班行程方案，返回：
    - 航班数量和最低价
    - 最低价航班详情
    - 最短耗时航班详情
    - 推荐航班方案
    
    适用场景：
    - 比较不同航班的价格
    - 寻找最便宜或最快的航班
    - 规划出行预算
    """
    try:
        # 调用 MCP 工具
        result = VariFlightMCPClient.invoke_tool(
            "mcp_variflight_searchFlightItineraries",
            {
                "depCityCode": dep_city,
                "arrCityCode": arr_city,
                "depDate": date
            }
        )
        
        # 解析结果
        result = parse_mcp_result(result)
        
        if 'error' in result:
            return f"查询失败：{result['error']}"
        
        if result.get('code') != 200:
            return f"查询失败：{result.get('message', '未知错误')}"
        
        # data 字段已经是优化后的自然语言
        data = result.get('data', '')
        
        # 处理 data 是错误对象的情况
        if isinstance(data, dict):
            if 'error' in data or 'error_code' in data:
                error_msg = data.get('error', data.get('message', '未知错误'))
                return f"未找到 {date} 从 {dep_city} 到 {arr_city} 的航班行程：{error_msg}"
        
        if not data:
            return f"未找到 {date} 从 {dep_city} 到 {arr_city} 的航班行程"
        
        return str(data)
        
    except Exception as e:
        logger.exception(f"[VariFlight] 查询行程价格失败: {e}")
        return f"查询失败：{str(e)}"


@tool(args_schema=FlightTransferInput)
def query_flight_transfer(dep_city: str, arr_city: str, date: str) -> str:
    """
    查询航班中转方案
    
    查询需要中转的航班方案，适用于没有直飞航班的城市对。返回：
    - 可选中转方案数量和最低价
    - 最低价中转方案详情
    - 最短耗时中转方案详情
    - 其他推荐中转方案
    
    适用场景：
    - 查询国际航班中转方案
    - 查询偏远城市的中转方案
    - 比较不同中转方案的价格和时间
    """
    try:
        # 调用 MCP 工具
        result = VariFlightMCPClient.invoke_tool(
            "mcp_variflight_getFlightTransferInfo",
            {
                "depcity": dep_city,
                "arrcity": arr_city,
                "depdate": date
            }
        )
        
        # 解析结果
        result = parse_mcp_result(result)
        
        if 'error' in result:
            return f"查询失败：{result['error']}"
        
        if result.get('code') != 200:
            return f"查询失败：{result.get('message', '未知错误')}"
        
        # data 字段已经是优化后的自然语言
        data = result.get('data', '')
        
        # 处理 data 是错误对象的情况
        if isinstance(data, dict):
            if 'error' in data or 'error_code' in data:
                error_msg = data.get('error', data.get('message', '未知错误'))
                return f"未找到 {date} 从 {dep_city} 到 {arr_city} 的中转方案：{error_msg}"
        
        if not data:
            return f"未找到 {date} 从 {dep_city} 到 {arr_city} 的中转方案"
        
        return str(data)
        
    except Exception as e:
        logger.exception(f"[VariFlight] 查询中转方案失败: {e}")
        return f"查询失败：{str(e)}"


# ==================== 工具集合 ====================

# 导出的工具列表
VARIFLIGHT_TOOLS = [
    query_flight_by_number,
    query_flights_by_route,
    query_flight_itineraries,
    query_flight_transfer,
]

# 工具字典（供 ALL_TOOLS 使用）
VARIFLIGHT_TOOLS_MAP = {tool.name: tool for tool in VARIFLIGHT_TOOLS}

# 工具描述（供 TOOL_CATEGORIES 使用）
VARIFLIGHT_TOOL_DESCRIPTIONS = {
    "query_flight_by_number": "根据航班号查询实时动态（起降时间、状态、登机口等）",
    "query_flights_by_route": "查询两城市间航班列表，支持筛选航司/时间/状态",
    "query_flight_itineraries": "查询航班行程和票价，找最便宜或最快的航班",
    "query_flight_transfer": "查询航班中转方案，适用于无直飞的城市",
}


def is_variflight_available() -> bool:
    """检查 VariFlight 服务是否可用"""
    config = VariFlightMCPClient.get_config()
    return config is not None and config.get('enabled', False)
