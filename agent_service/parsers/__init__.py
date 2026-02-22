"""
附件解析器系统

提供统一的文件解析接口，支持：
- 图片解析 (OCR + Base64)
- 百度云智能文档解析（PDF/Word/Excel → Markdown，云端优先）
- PDF / Word / Excel 本地解析（pdfplumber / python-docx / openpyxl，云端失败时降级）
- 音频解析（语音转文字，百度云 VOP → faster-whisper 本地兜底）
- 内部元素解析 (events/todos/reminders/workflows)
"""

from .base import BaseParser
from .image_parser import ImageParser
from .document_parser import BaiduDocumentParser, PDFParser, WordParser, ExcelParser
from .audio_parser import AudioParser
from .internal_parser import InternalElementParser


class ParserFactory:
    """解析器工厂 - 根据文件类型选择合适的解析器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._parsers = [
                ImageParser(),
                # 文档类：BaiduDocumentParser 在 can_parse() 中检查云端是否启用
                # 启用时接管 PDF/Word/Excel 并内置云→本地降级
                # 未启用时 can_parse() 返回 False，退后由各本地解析器接管
                BaiduDocumentParser(),
                PDFParser(),
                WordParser(),
                ExcelParser(),
                # 音频类：统一由 AudioParser 负责（云端+本地降级）
                AudioParser(),
            ]
            cls._instance._internal_parser = InternalElementParser()
        return cls._instance
    
    def get_parser(self, mime_type: str):
        """根据 MIME 类型获取合适的解析器"""
        for parser in self._parsers:
            if parser.can_parse(mime_type):
                return parser
        return None
    
    def get_internal_parser(self) -> InternalElementParser:
        """获取内部元素解析器"""
        return self._internal_parser


# 全局单例
parser_factory = ParserFactory()

__all__ = [
    'BaseParser',
    'ImageParser',
    'BaiduDocumentParser',
    'PDFParser',
    'WordParser',
    'ExcelParser',
    'AudioParser',
    'InternalElementParser',
    'ParserFactory',
    'parser_factory',
]
