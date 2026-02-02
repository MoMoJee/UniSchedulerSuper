"""
时间范围解析器
支持预置快捷选项和标准日期格式
"""
from datetime import datetime, timedelta
from typing import Tuple, Optional
import re


class TimeRangeParser:
    """时间范围解析器"""
    
    @classmethod
    def parse(cls, time_range: str) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        解析时间范围
        
        Args:
            time_range: 时间范围字符串，支持:
                - 预置选项: today, yesterday, tomorrow, this_week, next_week, 
                           last_week, this_month, next_month, last_month
                - 单个日期: "2025-01-15"
                - 日期范围: "2025-01-15,2025-01-20" 或 "2025-01-15 ~ 2025-01-20"
        
        Returns:
            (start_time, end_time) 元组，解析失败返回 (None, None)
        """
        if not time_range:
            return (None, None)
        
        # 保留原始字符串用于日期解析，转小写用于预置选项匹配
        time_range_original = time_range.strip()
        time_range_lower = time_range_original.lower()
        
        # 检查预置选项
        preset_handlers = {
            'today': cls._today,
            '今天': cls._today,
            'yesterday': cls._yesterday,
            '昨天': cls._yesterday,
            'tomorrow': cls._tomorrow,
            '明天': cls._tomorrow,
            'this_week': lambda: cls._get_week_range(0),
            '本周': lambda: cls._get_week_range(0),
            'next_week': lambda: cls._get_week_range(1),
            '下周': lambda: cls._get_week_range(1),
            'last_week': lambda: cls._get_week_range(-1),
            '上周': lambda: cls._get_week_range(-1),
            'this_month': lambda: cls._get_month_range(0),
            '本月': lambda: cls._get_month_range(0),
            'next_month': lambda: cls._get_month_range(1),
            '下月': lambda: cls._get_month_range(1),
            '下个月': lambda: cls._get_month_range(1),
            'last_month': lambda: cls._get_month_range(-1),
            '上月': lambda: cls._get_month_range(-1),
            '上个月': lambda: cls._get_month_range(-1),
        }
        
        if time_range_lower in preset_handlers:
            return preset_handlers[time_range_lower]()
        
        # 检查是否是日期范围，支持多种分隔符: "," "~" " ~ " "到" " - "
        # 优先检查 ~ 分隔符（支持前后有空格）
        range_separators = [' ~ ', '~', ' - ', ',', '到']
        parts = None
        for sep in range_separators:
            if sep in time_range_original:
                parts = time_range_original.split(sep, 1)
                if len(parts) == 2:
                    break
        
        if parts and len(parts) == 2:
            try:
                start = cls._parse_date(parts[0].strip())
                end = cls._parse_date(parts[1].strip())
                if start and end:
                    return (
                        start.replace(hour=0, minute=0, second=0),
                        end.replace(hour=23, minute=59, second=59)
                    )
            except:
                pass
        
        # 单个日期
        try:
            date = cls._parse_date(time_range_original)
            if date:
                return (
                    date.replace(hour=0, minute=0, second=0),
                    date.replace(hour=23, minute=59, second=59)
                )
        except:
            pass
        
        return (None, None)
    
    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """解析日期字符串"""
        date_str = date_str.strip()
        
        # 尝试多种格式
        formats = [
            '%Y-%m-%d',
            '%Y/%m/%d',
            '%Y.%m.%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        return None
    
    @staticmethod
    def _today() -> Tuple[datetime, datetime]:
        """今天"""
        today = datetime.now()
        return (
            today.replace(hour=0, minute=0, second=0, microsecond=0),
            today.replace(hour=23, minute=59, second=59, microsecond=0)
        )
    
    @staticmethod
    def _yesterday() -> Tuple[datetime, datetime]:
        """昨天"""
        yesterday = datetime.now() - timedelta(days=1)
        return (
            yesterday.replace(hour=0, minute=0, second=0, microsecond=0),
            yesterday.replace(hour=23, minute=59, second=59, microsecond=0)
        )
    
    @staticmethod
    def _tomorrow() -> Tuple[datetime, datetime]:
        """明天"""
        tomorrow = datetime.now() + timedelta(days=1)
        return (
            tomorrow.replace(hour=0, minute=0, second=0, microsecond=0),
            tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)
        )
    
    @staticmethod
    def _get_week_range(offset: int) -> Tuple[datetime, datetime]:
        """
        获取周范围
        
        Args:
            offset: 0=本周, 1=下周, -1=上周
        """
        today = datetime.now()
        # 本周一 (weekday() 返回 0-6，0 是周一)
        start_of_week = today - timedelta(days=today.weekday())
        # 加上偏移
        start_of_week += timedelta(weeks=offset)
        end_of_week = start_of_week + timedelta(days=6)
        
        return (
            start_of_week.replace(hour=0, minute=0, second=0, microsecond=0),
            end_of_week.replace(hour=23, minute=59, second=59, microsecond=0)
        )
    
    @staticmethod
    def _get_month_range(offset: int) -> Tuple[datetime, datetime]:
        """
        获取月范围
        
        Args:
            offset: 0=本月, 1=下月, -1=上月
        """
        today = datetime.now()
        # 计算目标月份
        month = today.month + offset
        year = today.year
        
        while month > 12:
            month -= 12
            year += 1
        while month < 1:
            month += 12
            year -= 1
        
        # 月初
        start = datetime(year, month, 1)
        
        # 月末
        if month == 12:
            end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end = datetime(year, month + 1, 1) - timedelta(seconds=1)
        
        return (start, end)
    
    @classmethod
    def format_range(cls, start: datetime, end: datetime) -> str:
        """格式化时间范围为可读字符串"""
        if not start or not end:
            return "未知时间范围"
        
        if start.date() == end.date():
            return start.strftime("%Y-%m-%d")
        else:
            return f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}"
