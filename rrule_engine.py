"""
RRule Engine - 通用重复规则引擎
支持复杂的重复规则管理，包括规则变更、例外处理、实例生成等
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import uuid

import json
import re

from logger import logger

try:
    from dateutil.rrule import rrulestr, rruleset, rrule
    DATEUTIL_AVAILABLE = True
except ImportError:
    print("Warning: python-dateutil not installed. RRule functionality will be limited.")
    DATEUTIL_AVAILABLE = False


class RRuleSegment:
    """RRule规则段 - 表示某个时间段内的重复规则"""
    
    def __init__(self, uid: str, sequence: int, rrule_str: str, 
                 dtstart: datetime, until: Optional[datetime] = None,
                 exdates: Optional[List[datetime]] = None, 
                 created_at: Optional[datetime] = None):
        self.uid = uid
        self.sequence = sequence
        self.rrule_str = rrule_str
        self.dtstart = dtstart
        self.until = until
        self.exdates = exdates or []
        self.created_at = created_at or datetime.now()
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，用于数据库存储"""
        return {
            'uid': self.uid,
            'sequence': self.sequence,
            'rrule_str': self.rrule_str,
            'dtstart': self.dtstart.isoformat(),
            'until': self.until.isoformat() if self.until else None,
            'exdates': [d.isoformat() for d in self.exdates],
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RRuleSegment':
        """从字典格式创建实例"""
        return cls(
            uid=data['uid'],
            sequence=data['sequence'],
            rrule_str=data['rrule_str'],
            dtstart=datetime.fromisoformat(data['dtstart']),
            until=datetime.fromisoformat(data['until']) if data['until'] else None,
            exdates=[datetime.fromisoformat(d) for d in data['exdates']],
            created_at=datetime.fromisoformat(data['created_at'])
        )


class RRuleSeries:
    """RRule系列 - 管理一个完整的重复任务生命周期"""
    
    def __init__(self, uid: Optional[str] = None):
        self.uid = uid or str(uuid.uuid4())
        self.segments: List[RRuleSegment] = []
        
    def add_segment(self, rrule_str: str, dtstart: datetime, 
                   until: Optional[datetime] = None) -> RRuleSegment:
        """添加新的规则段"""
        sequence = max([s.sequence for s in self.segments], default=0) + 1
        segment = RRuleSegment(
            uid=self.uid,
            sequence=sequence,
            rrule_str=rrule_str,
            dtstart=dtstart,
            until=until
        )
        self.segments.append(segment)
        return segment
    
    def add_exception(self, exception_date: datetime, segment_sequence: Optional[int] = None):
        """为指定规则段添加例外日期"""
        if segment_sequence is None:
            # 找到包含该日期的规则段
            target_segment = None
            for segment in sorted(self.segments, key=lambda s: s.sequence):
                if segment.dtstart <= exception_date:
                    if segment.until is None or exception_date <= segment.until:
                        target_segment = segment
                        break
            
            if target_segment:
                target_segment.exdates.append(exception_date)
        else:
            # 为指定序号的规则段添加例外
            for segment in self.segments:
                if segment.sequence == segment_sequence:
                    segment.exdates.append(exception_date)
                    break
    
    def modify_rule_from_date(self, from_date: datetime, new_rrule_str: str) -> RRuleSegment:
        """从指定日期开始修改规则（创建新规则段）"""
        # 1. 截断之前的规则段
        for segment in self.segments:
            if segment.dtstart <= from_date:
                if segment.until is None or segment.until > from_date:
                    # 需要截断这个规则段
                    segment.until = from_date - timedelta(days=1)
        
        # 2. 创建新规则段
        new_segment = self.add_segment(new_rrule_str, from_date)
        return new_segment
    
    def truncate_until(self, until_date: datetime):
        """截断系列到指定时间点（排除该时间点）"""
        # 截断时间设置为指定时间的前一秒，确保指定时间点也被排除
        actual_until = until_date - timedelta(seconds=1)
        
        for segment in self.segments:
            # 如果规则段的开始时间在截断时间之前
            if segment.dtstart < until_date:
                # 如果没有结束时间或结束时间在截断时间之后，则设置结束时间
                if segment.until is None or segment.until > actual_until:
                    segment.until = actual_until
            # 如果规则段的开始时间在截断时间之后，则移除该段
            # 注意：这里我们不直接移除，而是标记为需要移除
        
        # 移除开始时间在截断时间之后的规则段
        self.segments = [s for s in self.segments if s.dtstart < until_date]
    
    def generate_instances(self, start_date: Optional[datetime] = None, 
                          end_date: Optional[datetime] = None, 
                          max_count: int = 100) -> List[datetime]:
        """生成实际的重复实例"""
        if start_date is None:
            start_date = datetime.now()
        if end_date is None:
            end_date = start_date + timedelta(days=365)
            
        if not DATEUTIL_AVAILABLE:
            print("Warning: dateutil not available, cannot generate instances")
            return []
            
        rrset = rruleset()
        
        # 按序号排序处理所有规则段
        for segment in sorted(self.segments, key=lambda s: s.sequence):
            try:
                # 确保dtstart是naive datetime，避免时区问题
                dtstart = segment.dtstart
                if dtstart.tzinfo is not None:
                    dtstart = dtstart.replace(tzinfo=None)
                
                # 处理rrule中的UNTIL值，确保时区一致性
                processed_rrule = segment.rrule_str
                if 'UNTIL=' in segment.rrule_str:
                    import re
                    until_match = re.search(r'UNTIL=([^;]+)', segment.rrule_str)
                    if until_match:
                        until_str = until_match.group(1)
                        # 如果UNTIL是UTC格式（以Z结尾），转换为naive格式
                        if until_str.endswith('Z'):
                            until_naive = until_str[:-1]
                            processed_rrule = segment.rrule_str.replace(f'UNTIL={until_str}', f'UNTIL={until_naive}')
                
                # 构建完整的rrule字符串
                full_rrule = f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}\n"
                full_rrule += f"RRULE:{processed_rrule}"
                
                if segment.until:
                    # 确保UNTIL格式正确
                    if 'UNTIL=' not in processed_rrule:
                        until_str = segment.until.strftime('%Y%m%dT%H%M%S')
                        full_rrule = full_rrule.replace('RRULE:', f'RRULE:').replace(processed_rrule, f"{processed_rrule};UNTIL={until_str}")
                
                # 解析并添加到rruleset
                rule_obj = rrulestr(full_rrule, dtstart=dtstart)
                rrset.rrule(rule_obj)  # type: ignore
                
                # 添加例外日期
                for exdate in segment.exdates:
                    rrset.exdate(exdate)
                    
            except Exception as e:
                logger.warning(f"Warning: Failed to parse rrule segment {segment.sequence}: {e}, {self.segments=}")
                continue
        
        # 生成实例并过滤时间范围
        instances = []
        try:
            for dt in rrset:
                if dt > end_date:
                    break
                if dt >= start_date:
                    instances.append(dt)
                if len(instances) >= max_count:
                    break
        except Exception as e:
            print(f"Warning: Failed to generate instances: {e}")
            
        return instances
    
    def get_segments_data(self) -> List[Dict[str, Any]]:
        """获取所有规则段的数据，用于数据库存储"""
        return [segment.to_dict() for segment in self.segments]
    
    @classmethod
    def from_segments_data(cls, segments_data: List[Dict[str, Any]]) -> 'RRuleSeries':
        """从规则段数据重建系列"""
        if not segments_data:
            return cls()
            
        uid = segments_data[0]['uid']
        series = cls(uid)
        
        for data in segments_data:
            segment = RRuleSegment.from_dict(data)
            series.segments.append(segment)
            
        return series


class RRuleEngine:
    """RRule引擎 - 管理所有重复规则系列"""
    
    def __init__(self, storage_backend=None):
        """
        storage_backend: 存储后端，需要实现以下方法：
        - save_segments(uid, segments_data)
        - load_segments(uid)
        - delete_segments(uid)
        """
        self.storage = storage_backend
        self._cache: Dict[str, RRuleSeries] = {}
    
    def create_series(self, initial_rrule: str, dtstart: datetime, 
                     until: Optional[datetime] = None) -> str:
        """创建新的重复系列"""
        series = RRuleSeries()
        series.add_segment(initial_rrule, dtstart, until)
        
        # 保存到存储
        if self.storage:
            self.storage.save_segments(series.uid, series.get_segments_data())
        
        # 缓存
        self._cache[series.uid] = series
        
        return series.uid
    
    def get_series(self, uid: str) -> Optional[RRuleSeries]:
        """获取系列"""
        if uid in self._cache:
            return self._cache[uid]
        
        if self.storage:
            segments_data = self.storage.load_segments(uid)
            if segments_data:
                series = RRuleSeries.from_segments_data(segments_data)
                self._cache[uid] = series
                return series
        
        return None
    
    def delete_instance(self, uid: str, instance_date: datetime):
        """删除指定实例"""
        series = self.get_series(uid)
        if series:
            series.add_exception(instance_date)
            if self.storage:
                self.storage.save_segments(uid, series.get_segments_data())
    
    def modify_rule_from_date(self, uid: str, from_date: datetime, new_rrule: str):
        """从指定日期开始修改规则"""
        series = self.get_series(uid)
        if series:
            series.modify_rule_from_date(from_date, new_rrule)
            if self.storage:
                self.storage.save_segments(uid, series.get_segments_data())
    
    def generate_instances(self, uid: str, start_date: Optional[datetime] = None,
                          end_date: Optional[datetime] = None, max_count: int = 100) -> List[datetime]:
        """生成系列的实例"""
        series = self.get_series(uid)
        if series:
            return series.generate_instances(start_date, end_date, max_count)
        return []
    
    def delete_series(self, uid: str):
        """删除整个系列"""
        if self.storage:
            self.storage.delete_segments(uid)
        
        if uid in self._cache:
            del self._cache[uid]
    
    def truncate_series_until(self, uid: str, until_date: datetime):
        """截断系列到指定时间（使用UNTIL而不是EXDATE）"""
        series = self.get_series(uid)
        if series:
            series.truncate_until(until_date)
            if self.storage:
                self.storage.save_segments(uid, series.get_segments_data())
    



# Django存储后端示例
# class DjangoStorageBackend:
#     """Django存储后端实现"""
#
#     def __init__(self, model_class):
#         """
#         model_class: Django模型类，需要有以下字段：
#         - series_uid (CharField)
#         - segments_data (JSONField)
#         """
#         self.model_class = model_class
#
#     def save_segments(self, uid: str, segments_data: List[Dict[str, Any]]):
#         """保存规则段数据"""
#         obj, created = self.model_class.objects.get_or_create(
#             series_uid=uid,
#             defaults={'segments_data': segments_data}
#         )
#         if not created:
#             obj.segments_data = segments_data
#             obj.save()
#
#     def load_segments(self, uid: str) -> Optional[List[Dict[str, Any]]]:
#         """加载规则段数据"""
#         try:
#             obj = self.model_class.objects.get(series_uid=uid)
#             return obj.segments_data
#         except self.model_class.DoesNotExist:
#             return None
#
#     def delete_segments(self, uid: str):
#         """删除规则段数据"""
#         self.model_class.objects.filter(series_uid=uid).delete()


# 使用示例
if __name__ == "__main__":
    # 创建引擎
    engine = RRuleEngine()
    
    # 创建新系列：每天重复
    uid = engine.create_series("FREQ=DAILY", datetime(2025, 8, 24))
    print(f"Created series: {uid}")
    
    # 生成前10个实例
    instances = engine.generate_instances(uid, max_count=10)
    print("Initial instances:")
    for i, dt in enumerate(instances):
        print(f"  {i+1}. {dt.strftime('%Y-%m-%d %H:%M')}")
    
    # 删除8月26日的实例
    engine.delete_instance(uid, datetime(2025, 8, 26))
    print("\nAfter deleting 2025-08-26:")
    instances = engine.generate_instances(uid, max_count=10)
    for i, dt in enumerate(instances):
        print(f"  {i+1}. {dt.strftime('%Y-%m-%d %H:%M')}")
    
    # 从8月29日开始改为每两天重复
    engine.modify_rule_from_date(uid, datetime(2025, 8, 29), "FREQ=DAILY;INTERVAL=2")
    print("\nAfter changing rule from 2025-08-29 (every 2 days):")
    instances = engine.generate_instances(uid, max_count=15)
    for i, dt in enumerate(instances):
        print(f"  {i+1}. {dt.strftime('%Y-%m-%d %H:%M')}")
