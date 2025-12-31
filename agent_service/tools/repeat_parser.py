"""
重复规则解析器
将简化的重复描述转换为标准 RRule 格式
"""
import re
from typing import Optional


class RepeatParser:
    """
    简化重复描述 → RRule 转换器
    
    支持的简化格式:
    - "每天" → FREQ=DAILY
    - "每周" → FREQ=WEEKLY
    - "每周一三五" → FREQ=WEEKLY;BYDAY=MO,WE,FR
    - "每月" → FREQ=MONTHLY
    - "每月15号" → FREQ=MONTHLY;BYMONTHDAY=15
    - "每年" → FREQ=YEARLY
    - "工作日" → FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
    - "周末" → FREQ=WEEKLY;BYDAY=SA,SU
    - "每周，共4次" → FREQ=WEEKLY;COUNT=4
    """
    
    # 简单模式映射
    SIMPLE_PATTERNS = {
        "每天": "FREQ=DAILY",
        "每日": "FREQ=DAILY",
        "daily": "FREQ=DAILY",
        "每周": "FREQ=WEEKLY",
        "每星期": "FREQ=WEEKLY",
        "weekly": "FREQ=WEEKLY",
        "每月": "FREQ=MONTHLY",
        "monthly": "FREQ=MONTHLY",
        "每年": "FREQ=YEARLY",
        "yearly": "FREQ=YEARLY",
        "工作日": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        "周末": "FREQ=WEEKLY;BYDAY=SA,SU",
        "weekends": "FREQ=WEEKLY;BYDAY=SA,SU",
    }
    
    # 星期映射
    WEEKDAY_MAP = {
        "周一": "MO", "星期一": "MO", "monday": "MO", "mon": "MO", "一": "MO",
        "周二": "TU", "星期二": "TU", "tuesday": "TU", "tue": "TU", "二": "TU",
        "周三": "WE", "星期三": "WE", "wednesday": "WE", "wed": "WE", "三": "WE",
        "周四": "TH", "星期四": "TH", "thursday": "TH", "thu": "TH", "四": "TH",
        "周五": "FR", "星期五": "FR", "friday": "FR", "fri": "FR", "五": "FR",
        "周六": "SA", "星期六": "SA", "saturday": "SA", "sat": "SA", "六": "SA",
        "周日": "SU", "星期日": "SU", "sunday": "SU", "sun": "SU", "日": "SU",
        "周天": "SU", "星期天": "SU", "天": "SU",
    }
    
    @classmethod
    def parse(cls, repeat_str: str) -> str:
        """
        将简化描述转为 RRule
        
        Args:
            repeat_str: 简化的重复描述
        
        Returns:
            标准 RRule 字符串，无法解析则返回原字符串
        
        Examples:
            - "每天" → "FREQ=DAILY"
            - "每周一三五" → "FREQ=WEEKLY;BYDAY=MO,WE,FR"
            - "每月15号" → "FREQ=MONTHLY;BYMONTHDAY=15"
            - "每周，共4次" → "FREQ=WEEKLY;COUNT=4"
        """
        if not repeat_str:
            return ""
        
        repeat_str = repeat_str.strip().lower()
        
        # 如果已经是 RRule 格式，直接返回
        if 'freq=' in repeat_str.upper():
            return repeat_str.upper()
        
        # 1. 检查简单模式
        for pattern, rrule in cls.SIMPLE_PATTERNS.items():
            if repeat_str == pattern.lower():
                return rrule
        
        # 2. 解析次数限制 "共X次"
        count = None
        count_match = re.search(r'共\s*(\d+)\s*次', repeat_str)
        if count_match:
            count = count_match.group(1)
            # 移除次数部分以便继续解析
            repeat_str = re.sub(r'[,，]?\s*共\s*\d+\s*次', '', repeat_str).strip()
        
        # 3. 解析结束日期 "到X"
        until = None
        until_match = re.search(r'到\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})', repeat_str)
        if until_match:
            until_date = until_match.group(1).replace('/', '-')
            until = until_date.replace('-', '') + 'T235959Z'
            repeat_str = re.sub(r'[,，]?\s*到\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}', '', repeat_str).strip()
        
        base_rrule = None
        
        # 4. 再次检查简单模式（去除修饰后）
        for pattern, rrule in cls.SIMPLE_PATTERNS.items():
            if pattern.lower() in repeat_str:
                base_rrule = rrule
                break
        
        # 5. 解析"每周X"模式
        if "每周" in repeat_str or "每星期" in repeat_str:
            # 提取星期几
            byday = []
            for day_name, day_code in cls.WEEKDAY_MAP.items():
                if day_name in repeat_str:
                    if day_code not in byday:
                        byday.append(day_code)
            
            if byday:
                base_rrule = f"FREQ=WEEKLY;BYDAY={','.join(byday)}"
            elif not base_rrule:
                base_rrule = "FREQ=WEEKLY"
        
        # 6. 解析"每月X号"模式
        month_day_match = re.search(r'每月\s*(\d+)\s*[号日]', repeat_str)
        if month_day_match:
            day = month_day_match.group(1)
            base_rrule = f"FREQ=MONTHLY;BYMONTHDAY={day}"
        
        # 7. 解析"每X天"模式
        interval_day_match = re.search(r'每\s*(\d+)\s*天', repeat_str)
        if interval_day_match:
            interval = interval_day_match.group(1)
            if interval == '1':
                base_rrule = "FREQ=DAILY"
            else:
                base_rrule = f"FREQ=DAILY;INTERVAL={interval}"
        
        # 8. 解析"每X周"模式
        interval_week_match = re.search(r'每\s*(\d+)\s*周', repeat_str)
        if interval_week_match:
            interval = interval_week_match.group(1)
            if interval == '1':
                if not base_rrule:
                    base_rrule = "FREQ=WEEKLY"
            else:
                base_rrule = f"FREQ=WEEKLY;INTERVAL={interval}"
        
        # 如果没有解析出 base_rrule，返回原字符串
        if not base_rrule:
            return repeat_str
        
        # 添加 COUNT 或 UNTIL
        if count:
            base_rrule += f";COUNT={count}"
        elif until:
            base_rrule += f";UNTIL={until}"
        
        return base_rrule
    
    @classmethod
    def to_human_readable(cls, rrule: str) -> str:
        """
        将 RRule 转为人类可读的描述
        
        Args:
            rrule: RRule 字符串
        
        Returns:
            人类可读的描述
        """
        if not rrule:
            return "不重复"
        
        rrule = rrule.upper()
        parts = []
        
        # 解析 FREQ
        if 'FREQ=DAILY' in rrule:
            parts.append("每天")
        elif 'FREQ=WEEKLY' in rrule:
            parts.append("每周")
        elif 'FREQ=MONTHLY' in rrule:
            parts.append("每月")
        elif 'FREQ=YEARLY' in rrule:
            parts.append("每年")
        
        # 解析 INTERVAL
        interval_match = re.search(r'INTERVAL=(\d+)', rrule)
        if interval_match and interval_match.group(1) != '1':
            interval = interval_match.group(1)
            if 'FREQ=DAILY' in rrule:
                parts[-1] = f"每{interval}天"
            elif 'FREQ=WEEKLY' in rrule:
                parts[-1] = f"每{interval}周"
            elif 'FREQ=MONTHLY' in rrule:
                parts[-1] = f"每{interval}月"
        
        # 解析 BYDAY
        byday_match = re.search(r'BYDAY=([A-Z,]+)', rrule)
        if byday_match:
            days = byday_match.group(1).split(',')
            day_names = []
            reverse_map = {v: k for k, v in cls.WEEKDAY_MAP.items() if len(k) == 2}
            for day in days:
                if day in reverse_map:
                    day_names.append(reverse_map[day])
            if day_names:
                parts.append(''.join(day_names))
        
        # 解析 BYMONTHDAY
        bymonthday_match = re.search(r'BYMONTHDAY=(\d+)', rrule)
        if bymonthday_match:
            parts.append(f"{bymonthday_match.group(1)}号")
        
        # 解析 COUNT
        count_match = re.search(r'COUNT=(\d+)', rrule)
        if count_match:
            parts.append(f"共{count_match.group(1)}次")
        
        # 解析 UNTIL
        until_match = re.search(r'UNTIL=(\d{8})', rrule)
        if until_match:
            date_str = until_match.group(1)
            formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            parts.append(f"到{formatted}")
        
        return ''.join(parts) if parts else rrule
