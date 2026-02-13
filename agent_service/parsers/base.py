"""
解析器基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseParser(ABC):
    """解析器基类"""
    
    @abstractmethod
    def can_parse(self, mime_type: str) -> bool:
        """
        判断是否能解析该 MIME 类型
        
        Args:
            mime_type: MIME 类型
            
        Returns:
            是否支持解析
        """
        pass
    
    @abstractmethod
    def parse(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """
        解析文件
        
        Args:
            file_path: 文件绝对路径
            **kwargs: 额外参数
            
        Returns:
            {
                "success": bool,
                "text": str,           # 提取的文本
                "base64": str,         # Base64 编码（仅图片）
                "metadata": dict,      # 元信息
                "error": str           # 错误信息（如果失败）
            }
        """
        pass
    
    def generate_thumbnail(self, file_path: str, output_path: str, 
                          size: tuple = (200, 200)) -> bool:
        """
        生成缩略图（可选实现）
        
        Args:
            file_path: 原文件路径
            output_path: 输出路径
            size: 缩略图尺寸 (width, height)
            
        Returns:
            是否成功生成
        """
        return False
