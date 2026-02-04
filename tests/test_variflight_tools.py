"""
VariFlight 工具测试脚本

运行方式：
    python -m agent_service.tools.test_variflight_tools
"""

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UniSchedulerSuper.settings')

import django
django.setup()

from datetime import datetime, timedelta
from agent_service.tools.variflight_tools import (
    query_flight_by_number,
    query_flights_by_route,
    query_flight_itineraries,
    query_flight_transfer,
    is_variflight_available,
    VariFlightMCPClient
)


def test_variflight_availability():
    """测试 VariFlight 服务是否可用"""
    print("=" * 60)
    print("测试 1: 检查 VariFlight 服务可用性")
    print("=" * 60)
    
    available = is_variflight_available()
    print(f"VariFlight 服务可用: {available}")
    
    if available:
        config = VariFlightMCPClient.get_config()
        print(f"MCP URL: {config.get('mcp_url', 'N/A')}")
        print(f"传输方式: {config.get('transport', 'N/A')}")
    
    return available


def test_flight_by_number():
    """测试航班号查询"""
    print("\n" + "=" * 60)
    print("测试 2: 根据航班号查询航班动态")
    print("=" * 60)
    
    # 使用明天的日期
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"查询: CA1523, 日期: {tomorrow}")
    result = query_flight_by_number.invoke({
        "flight_number": "CA1523",
        "date": tomorrow
    })
    print(f"\n结果:\n{result}")


def test_flights_by_route():
    """测试航线查询"""
    print("\n" + "=" * 60)
    print("测试 3: 查询两城市间航班")
    print("=" * 60)
    
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"查询: 北京(BJS) -> 上海(SHA), 日期: {tomorrow}")
    print("筛选: 上午航班(08:00-12:00), 最多5条")
    
    result = query_flights_by_route.invoke({
        "dep_city": "BJS",
        "arr_city": "SHA",
        "date": tomorrow,
        "time_range": "08:00-12:00",
        "max_results": 5
    })
    print(f"\n结果:\n{result}")


def test_flight_itineraries():
    """测试航班行程价格查询"""
    print("\n" + "=" * 60)
    print("测试 4: 查询航班行程价格")
    print("=" * 60)
    
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"查询: 北京(BJS) -> 上海(SHA), 日期: {tomorrow}")
    
    result = query_flight_itineraries.invoke({
        "dep_city": "BJS",
        "arr_city": "SHA",
        "date": tomorrow
    })
    print(f"\n结果:\n{result}")


def test_flight_transfer():
    """测试中转方案查询"""
    print("\n" + "=" * 60)
    print("测试 5: 查询航班中转方案")
    print("=" * 60)
    
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"查询: 喀什(KHG) -> 东京(TYO), 日期: {tomorrow}")
    
    result = query_flight_transfer.invoke({
        "dep_city": "KHG",
        "arr_city": "TYO",
        "date": tomorrow
    })
    print(f"\n结果:\n{result}")


def main():
    print("VariFlight 航班查询工具测试")
    print("=" * 60)
    
    # 测试服务可用性
    if not test_variflight_availability():
        print("\n❌ VariFlight 服务不可用，请检查配置")
        return
    
    print("\n✅ VariFlight 服务配置正确")
    
    # 依次测试各工具
    try:
        test_flight_by_number()
    except Exception as e:
        print(f"❌ 航班号查询测试失败: {e}")
    
    try:
        test_flights_by_route()
    except Exception as e:
        print(f"❌ 航线查询测试失败: {e}")
    
    try:
        test_flight_itineraries()
    except Exception as e:
        print(f"❌ 行程价格查询测试失败: {e}")
    
    try:
        test_flight_transfer()
    except Exception as e:
        print(f"❌ 中转方案查询测试失败: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
