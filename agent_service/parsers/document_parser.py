"""
文档解析器

支持：
- PDF (pdfplumber)
- Word (python-docx)
- Excel (openpyxl)

所有解析器优雅降级：如果依赖库未安装，返回友好提示而不是崩溃。
"""
from typing import Dict, Any

from .base import BaseParser
from logger import logger


def _table_to_markdown(table_data) -> str:
    """将二维数组转换为 Markdown 表格"""
    if not table_data or len(table_data) == 0:
        return ""
    
    lines = []
    header = table_data[0]
    col_count = len(header)
    
    lines.append('| ' + ' | '.join(str(cell or '') for cell in header) + ' |')
    lines.append('| ' + ' | '.join(['---'] * col_count) + ' |')
    
    for row in table_data[1:]:
        # 补齐列数
        padded = list(row) + [''] * (col_count - len(row))
        lines.append('| ' + ' | '.join(str(cell or '') for cell in padded[:col_count]) + ' |')
    
    return '\n'.join(lines)


class PDFParser(BaseParser):
    """PDF 解析器"""
    
    def can_parse(self, mime_type: str) -> bool:
        return mime_type == 'application/pdf'
    
    def parse(self, file_path: str, **kwargs) -> Dict[str, Any]:
        try:
            import pdfplumber
        except ImportError:
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": "需要安装 pdfplumber 库: pip install pdfplumber"
            }
        
        try:
            text_content = []
            metadata = {"pages": 0, "has_tables": False}
            
            with pdfplumber.open(file_path) as pdf:
                metadata["pages"] = len(pdf.pages)
                
                for i, page in enumerate(pdf.pages):
                    page_texts = []
                    
                    # 提取文字
                    page_text = page.extract_text()
                    if page_text:
                        page_texts.append(page_text)
                    
                    # 提取表格
                    tables = page.extract_tables()
                    if tables:
                        metadata["has_tables"] = True
                        for table in tables:
                            if table:
                                table_md = _table_to_markdown(table)
                                if table_md:
                                    page_texts.append(table_md)
                    
                    if page_texts:
                        text_content.append(f"--- 第 {i+1} 页 ---\n" + '\n\n'.join(page_texts))
            
            full_text = '\n\n'.join(text_content)
            
            return {
                "success": True,
                "text": full_text or "[PDF 无可提取的文本内容]",
                "metadata": metadata,
                "error": ""
            }
            
        except Exception as e:
            logger.error(f"PDF 解析失败 {file_path}: {e}")
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": str(e)
            }


class WordParser(BaseParser):
    """Word 文档解析器"""
    
    SUPPORTED_MIMES = {
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/msword',
    }
    
    def can_parse(self, mime_type: str) -> bool:
        return mime_type in self.SUPPORTED_MIMES
    
    def parse(self, file_path: str, **kwargs) -> Dict[str, Any]:
        try:
            from docx import Document
        except ImportError:
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": "需要安装 python-docx 库: pip install python-docx"
            }
        
        try:
            doc = Document(file_path)
            
            # 提取段落
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            
            # 提取表格
            tables_text = []
            for table in doc.tables:
                table_data = []
                for row in table.rows:
                    row_data = [cell.text for cell in row.cells]
                    table_data.append(row_data)
                if table_data:
                    tables_text.append(_table_to_markdown(table_data))
            
            full_text = '\n\n'.join(paragraphs + tables_text)
            
            metadata = {
                "paragraphs": len(paragraphs),
                "tables": len(doc.tables),
            }
            
            return {
                "success": True,
                "text": full_text or "[Word 文档无内容]",
                "metadata": metadata,
                "error": ""
            }
            
        except Exception as e:
            logger.error(f"Word 解析失败 {file_path}: {e}")
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": str(e)
            }


class ExcelParser(BaseParser):
    """Excel 表格解析器"""
    
    SUPPORTED_MIMES = {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel',
    }
    
    def can_parse(self, mime_type: str) -> bool:
        return mime_type in self.SUPPORTED_MIMES
    
    def parse(self, file_path: str, **kwargs) -> Dict[str, Any]:
        try:
            import openpyxl
        except ImportError:
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": "需要安装 openpyxl 库: pip install openpyxl"
            }
        
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheets_text = []
            
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                
                data = []
                for row in ws.iter_rows(values_only=True):
                    if any(cell is not None for cell in row):
                        data.append([
                            str(cell) if cell is not None else '' 
                            for cell in row
                        ])
                
                if data:
                    sheet_md = f"### Sheet: {sheet_name}\n\n"
                    sheet_md += _table_to_markdown(data)
                    sheets_text.append(sheet_md)
            
            full_text = '\n\n'.join(sheets_text)
            
            metadata = {
                "sheets": len(wb.sheetnames),
                "sheet_names": wb.sheetnames,
            }
            
            return {
                "success": True,
                "text": full_text or "[Excel 文件无数据]",
                "metadata": metadata,
                "error": ""
            }
            
        except Exception as e:
            logger.error(f"Excel 解析失败 {file_path}: {e}")
            return {
                "success": False,
                "text": "",
                "metadata": {},
                "error": str(e)
            }
