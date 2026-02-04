"""
重复规则解析器
将简化的重复描述转换为标准 RRule 格式
"""
import re
from typing import Optional, Tuple


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
    
    # 中文数字映射
    CHINESE_NUM_MAP = {
        '零': 0, '〇': 0,
        '一': 1, '壹': 1,
        '二': 2, '贰': 2, '两': 2, '俩': 2,
        '三': 3, '叁': 3,
        '四': 4, '肆': 4,
        '五': 5, '伍': 5,
        '六': 6, '陆': 6,
        '七': 7, '柒': 7,
        '八': 8, '捌': 8,
        '九': 9, '玖': 9,
        '十': 10, '拾': 10,
    }
    
    @classmethod
    def _chinese_to_int(cls, chinese_str: str) -> Optional[int]:
        """
        将中文数字转换为整数
        
        支持格式:
        - 单字: "一" -> 1, "两" -> 2
        - 十位: "十" -> 10, "十一" -> 11, "二十" -> 20, "二十一" -> 21
        """
        if not chinese_str:
            return None
        
        chinese_str = chinese_str.strip()
        
        # 如果已经是阿拉伯数字，直接返回
        if chinese_str.isdigit():
            return int(chinese_str)
        
        # 单字映射
        if len(chinese_str) == 1 and chinese_str in cls.CHINESE_NUM_MAP:
            return cls.CHINESE_NUM_MAP[chinese_str]
        
        # 处理包含"十"的情况
        if '十' in chinese_str or '拾' in chinese_str:
            ten_char = '十' if '十' in chinese_str else '拾'
            parts = chinese_str.split(ten_char)
            
            if len(parts) == 2:
                before, after = parts
                
                # "十X" -> 10 + X
                if before == '':
                    tens = 10
                else:
                    tens = cls.CHINESE_NUM_MAP.get(before, 0) * 10
                
                # "X十" -> X * 10
                if after == '':
                    units = 0
                else:
                    units = cls.CHINESE_NUM_MAP.get(after, 0)
                
                return tens + units
        
        # 尝试逐字转换（如 "二三" -> 不支持，但可以处理单字）
        if len(chinese_str) == 1:
            return cls.CHINESE_NUM_MAP.get(chinese_str)
        
        return None
    
    @classmethod
    def _normalize_chinese_numbers(cls, text: str) -> str:
        """
        将文本中的中文数字转换为阿拉伯数字
        
        主要处理间隔表达式中的中文数字，如:
        - "每两天" -> "每2天"
        - "每三周" -> "每3周"
        - "每隔两天" -> "每隔2天"
        - "每十天" -> "每10天"
        - "每二十一天" -> "每21天"
        """
        # 匹配 "每(隔)?中文数字+单位" 的模式
        # 中文数字可以是: 单字(一二三...)、十位(十、十一、二十、二十一...)
        pattern = r'每(\s*隔\s*)?([零一二三四五六七八九十两俩壹贰叁肆伍陆柒捌玖拾]+)\s*(天|日|周|星期|月|年)'
        
        def replace_func(match):
            gap = match.group(1) or ''  # "隔" 部分
            chinese_num = match.group(2)  # 中文数字
            unit = match.group(3)  # 单位
            
            # 转换中文数字
            num = cls._chinese_to_int(chinese_num)
            if num is not None:
                return f'每{gap}{num}{unit}'
            else:
                # 无法转换，保持原样
                return match.group(0)
        
        return re.sub(pattern, replace_func, text)
    
    @classmethod
    def parse(cls, repeat_str: str) -> str:
        """
        将简化描述转为 RRule
        
        Args:
            repeat_str: 简化的重复描述
        
        Returns:
            标准 RRule 字符串，无法解析则返回原字符串
        
        支持的格式:
            基础格式:
            - "每天" / "每日" / "daily" → FREQ=DAILY
            - "每周" / "weekly" → FREQ=WEEKLY
            - "每月" / "monthly" → FREQ=MONTHLY
            - "每年" / "yearly" → FREQ=YEARLY
            - "工作日" / "weekdays" → FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
            - "周末" / "weekends" → FREQ=WEEKLY;BYDAY=SA,SU
            
            带间隔:
            - "每2天" / "每隔2天" → FREQ=DAILY;INTERVAL=2
            - "每3周" / "每隔3周" → FREQ=WEEKLY;INTERVAL=3
            
            指定星期:
            - "每周一三五" → FREQ=WEEKLY;BYDAY=MO,WE,FR
            - "每2周一三五" → FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR
            
            指定日期:
            - "每月15号" → FREQ=MONTHLY;BYMONTHDAY=15
            
            次数/结束限制:
            - "每天，共10次" → FREQ=DAILY;COUNT=10
            - "每天;COUNT=10" → FREQ=DAILY;COUNT=10
            - "每周，到2026-01-01" → FREQ=WEEKLY;UNTIL=20260101T235959Z
            - "每周;UNTIL=20260101" → FREQ=WEEKLY;UNTIL=20260101
        """
        if not repeat_str:
            return ""
        
        original_str = repeat_str.strip()
        
        # ===== 预处理：将中文数字转换为阿拉伯数字 =====
        original_str = cls._normalize_chinese_numbers(original_str)
        
        repeat_str = original_str.lower()
        
        # 如果已经是完整的 RRule 格式（包含 FREQ=），直接返回大写版本
        if 'freq=' in repeat_str:
            return original_str.upper()
        
        # ===== 第一阶段：提取修饰符（COUNT, UNTIL）=====
        count = None
        until = None
        
        # 提取 RRule 风格: ;COUNT=X
        count_rrule_match = re.search(r';?\s*count\s*=\s*(\d+)', repeat_str, re.IGNORECASE)
        if count_rrule_match:
            count = count_rrule_match.group(1)
            repeat_str = re.sub(r';?\s*count\s*=\s*\d+', '', repeat_str, flags=re.IGNORECASE).strip()
        
        # 提取 RRule 风格: ;UNTIL=X
        until_rrule_match = re.search(r';?\s*until\s*=\s*(\d+T?\d*Z?)', repeat_str, re.IGNORECASE)
        if until_rrule_match:
            until = until_rrule_match.group(1)
            repeat_str = re.sub(r';?\s*until\s*=\s*\d+T?\d*Z?', '', repeat_str, flags=re.IGNORECASE).strip()
        
        # 提取中文格式: 共X次
        if not count:
            count_match = re.search(r'共\s*(\d+)\s*次', repeat_str)
            if count_match:
                count = count_match.group(1)
                repeat_str = re.sub(r'[,，]?\s*共\s*\d+\s*次', '', repeat_str).strip()
        
        # 提取中文格式: 到YYYY-MM-DD
        if not until:
            until_match = re.search(r'到\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})', repeat_str)
            if until_match:
                until_date = until_match.group(1).replace('/', '-')
                until = until_date.replace('-', '') + 'T235959Z'
                repeat_str = re.sub(r'[,，]?\s*到\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}', '', repeat_str).strip()
        
        # 清理分号
        repeat_str = repeat_str.strip(';').strip()
        
        # ===== 第二阶段：解析频率和参数 =====
        freq = None
        interval = None
        byday = []
        bymonthday = None
        
        # 1. 检查简单模式（精确匹配）
        for pattern, rrule in cls.SIMPLE_PATTERNS.items():
            if repeat_str == pattern.lower():
                return cls._build_rrule(rrule, count, until)
        
        # 2. 提取间隔数字: "每X天/周/月" 或 "每隔X天/周/月"
        interval_match = re.search(r'每\s*(?:隔\s*)?(\d+)\s*(天|日|周|星期|月|年)', repeat_str)
        if interval_match:
            interval = interval_match.group(1)
            unit = interval_match.group(2)
            
            if unit in ('天', '日'):
                freq = 'DAILY'
            elif unit in ('周', '星期'):
                freq = 'WEEKLY'
            elif unit == '月':
                freq = 'MONTHLY'
            elif unit == '年':
                freq = 'YEARLY'
            
            if interval == '1':
                interval = None  # 间隔为1时不需要 INTERVAL
        
        # 3. 如果没有匹配到间隔，检查基础频率
        if not freq:
            if '每天' in repeat_str or '每日' in repeat_str or 'daily' in repeat_str:
                freq = 'DAILY'
            elif '每周' in repeat_str or '每星期' in repeat_str or 'weekly' in repeat_str:
                freq = 'WEEKLY'
            elif '每月' in repeat_str or 'monthly' in repeat_str:
                freq = 'MONTHLY'
            elif '每年' in repeat_str or 'yearly' in repeat_str:
                freq = 'YEARLY'
            elif '工作日' in repeat_str or 'weekdays' in repeat_str:
                freq = 'WEEKLY'
                byday = ['MO', 'TU', 'WE', 'TH', 'FR']
            elif '周末' in repeat_str or 'weekends' in repeat_str:
                freq = 'WEEKLY'
                byday = ['SA', 'SU']
        
        # 4. 提取星期几（适用于 WEEKLY）
        if freq == 'WEEKLY' and not byday:
            for day_name, day_code in cls.WEEKDAY_MAP.items():
                if day_name in repeat_str and day_code not in byday:
                    byday.append(day_code)
        
        # 5. 提取每月几号
        month_day_match = re.search(r'(\d+)\s*[号日]', repeat_str)
        if month_day_match and (freq == 'MONTHLY' or '每月' in repeat_str):
            bymonthday = month_day_match.group(1)
            if not freq:
                freq = 'MONTHLY'
        
        # ===== 第三阶段：构建 RRule =====
        if not freq:
            # 无法解析，返回原字符串
            return original_str
        
        parts = [f'FREQ={freq}']
        
        if interval:
            parts.append(f'INTERVAL={interval}')
        
        if byday:
            # 保持星期的顺序
            ordered_days = []
            day_order = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
            for d in day_order:
                if d in byday:
                    ordered_days.append(d)
            parts.append(f'BYDAY={",".join(ordered_days)}')
        
        if bymonthday:
            parts.append(f'BYMONTHDAY={bymonthday}')
        
        if count:
            parts.append(f'COUNT={count}')
        elif until:
            parts.append(f'UNTIL={until}')
        
        return ';'.join(parts)
    
    @classmethod
    def _build_rrule(cls, base_rrule: str, count: str = None, until: str = None) -> str:
        """构建带 COUNT/UNTIL 的 RRule"""
        if count:
            return f"{base_rrule};COUNT={count}"
        elif until:
            return f"{base_rrule};UNTIL={until}"
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
