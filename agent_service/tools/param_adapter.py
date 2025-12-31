"""
参数适配器
处理 UNSET 哨兵值和不同类型的参数映射
"""
from typing import Any, Dict


class UNSET:
    """
    表示参数未设置（区别于 None 或空字符串）
    
    使用场景：
    - UNSET_VALUE: 参数未传递，保持原值
    - None: 明确传递 None，可能表示清空
    - "": 明确传递空字符串，表示清空
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __repr__(self):
        return "UNSET"
    
    def __bool__(self):
        return False


# 全局单例
UNSET_VALUE = UNSET()


def is_set(value: Any) -> bool:
    """检查值是否已设置（非 UNSET）"""
    return not isinstance(value, UNSET)


class ParamAdapter:
    """
    参数适配器 - 将统一参数转换为各类型特定参数
    
    解决问题：
    - Event, To do, Reminder 三种类型的参数名称和规则不同
    - 统一工具需要接受所有可能的参数
    - 调用服务层时需要过滤出各类型支持的参数
    """
    
    # 各类型支持的参数映射
    PARAM_CONFIG = {
        "event": {
            # 通用字段
            "title": "title",
            "description": "description",
            "importance": "importance",
            "urgency": "urgency",
            # 时间字段
            "start": "start",
            "end": "end",
            "ddl": "ddl",
            # 分类字段
            "group_id": "groupID",  # 注意：服务层使用 groupID
            # 重复规则
            "rrule": "rrule",
            "_clear_rrule": "_clear_rrule",
            # 特殊字段
            "shared_to_groups": "shared_to_groups",
            "update_scope": "update_scope",
        },
        "todo": {
            # 通用字段
            "title": "title",
            "description": "description",
            "importance": "importance",
            "urgency": "urgency",
            "status": "status",
            # 时间字段
            "due_date": "due_date",
            "estimated_duration": "estimated_duration",
            # 分类字段
            "group_id": "groupID",
        },
        "reminder": {
            # 通用字段
            "title": "title",
            "content": "content",
            "priority": "priority",
            "status": "status",
            # 时间字段
            "trigger_time": "trigger_time",
            # 重复规则
            "rrule": "rrule",
            "_clear_rrule": "_clear_rrule",
        }
    }
    
    @classmethod
    def adapt_params(cls, item_type: str, **kwargs) -> Dict[str, Any]:
        """
        转换统一参数为特定类型的参数
        
        Args:
            item_type: "event" | "to do" | "reminder"
            **kwargs: 统一的参数字典
        
        Returns:
            适配后的参数字典（只包含该类型支持的且已设置的参数）
        """
        if item_type not in cls.PARAM_CONFIG:
            raise ValueError(f"不支持的类型: {item_type}")
        
        param_mapping = cls.PARAM_CONFIG[item_type]
        adapted = {}
        
        for unified_name, service_name in param_mapping.items():
            if unified_name in kwargs:
                value = kwargs[unified_name]
                # 只有非 UNSET 的值才会被传递
                if is_set(value):
                    adapted[service_name] = value
        
        return adapted
    
    @classmethod
    def get_supported_params(cls, item_type: str) -> list:
        """获取指定类型支持的参数列表"""
        if item_type not in cls.PARAM_CONFIG:
            return []
        return list(cls.PARAM_CONFIG[item_type].keys())
    
    @classmethod
    def adapt_for_create(cls, item_type: str, **kwargs) -> Dict[str, Any]:
        """
        适配创建操作的参数
        创建时某些字段是必需的，需要特殊处理
        """
        adapted = cls.adapt_params(item_type, **kwargs)
        
        # 创建时的默认值
        if item_type == "event":
            if "description" not in adapted:
                adapted["description"] = ""
            if "importance" not in adapted:
                adapted["importance"] = ""
            if "urgency" not in adapted:
                adapted["urgency"] = ""
            if "groupID" not in adapted:
                adapted["groupID"] = ""
            if "rrule" not in adapted:
                adapted["rrule"] = ""
        
        elif item_type == "todo":
            if "description" not in adapted:
                adapted["description"] = ""
            if "due_date" not in adapted:
                adapted["due_date"] = ""
            if "estimated_duration" not in adapted:
                adapted["estimated_duration"] = ""
            if "importance" not in adapted:
                adapted["importance"] = ""
            if "urgency" not in adapted:
                adapted["urgency"] = ""
            if "groupID" not in adapted:
                adapted["groupID"] = ""
        
        elif item_type == "reminder":
            if "content" not in adapted:
                adapted["content"] = ""
            if "priority" not in adapted:
                adapted["priority"] = "normal"
            if "rrule" not in adapted:
                adapted["rrule"] = ""
        
        return adapted
