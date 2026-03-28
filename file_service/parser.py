import re

from agent_service.parsers import parser_factory

# 需要预解析的 MIME 类型
DOCUMENT_MIMES = {
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}


def should_preparse(mime_type: str) -> bool:
    """判断该类型是否需要预解析"""
    return mime_type in DOCUMENT_MIMES


def preparse_document(user_file) -> None:
    """
    对文档类文件执行预解析，将结果写入 UserFile。

    流程：
    1. 调用 parser_factory 获取解析器（BaiduDocumentParser 优先 → 本地 fallback）
    2. 解析成功 → 写入 parsed_markdown, search_text, text_preview
    3. 解析失败 → 记录 parse_error，状态设为 failed
    """
    from django.utils import timezone

    user_file.parse_status = 'processing'
    user_file.save(update_fields=['parse_status'])

    parser = parser_factory.get_parser(user_file.mime_type)
    if not parser:
        user_file.parse_status = 'failed'
        user_file.parse_error = f'无可用解析器: {user_file.mime_type}'
        user_file.save(update_fields=['parse_status', 'parse_error'])
        return

    try:
        result = parser.parse(
            user_file.original_file.path,
            mime_type=user_file.mime_type
        )
    except Exception as e:
        user_file.parse_status = 'failed'
        user_file.parse_error = str(e)
        user_file.save(update_fields=['parse_status', 'parse_error'])
        return

    if result.get('success'):
        markdown_text = result.get('text', '')
        plain_text = _strip_markdown(markdown_text)

        user_file.parsed_markdown = markdown_text
        user_file.search_text = plain_text
        user_file.text_preview = plain_text[:500]
        user_file.parse_status = 'completed'
        user_file.parse_source = result.get('source', 'local_fallback')
        user_file.parse_error = ''
        user_file.parsed_at = timezone.now()
    else:
        user_file.parse_status = 'failed'
        user_file.parse_error = result.get('error', '解析失败')

    user_file.save(update_fields=[
        'parsed_markdown', 'search_text', 'text_preview',
        'parse_status', 'parse_source', 'parse_error', 'parsed_at'
    ])


def _strip_markdown(text: str) -> str:
    """去除 Markdown 格式标记，保留纯文本（用于检索索引）"""
    # 去掉标题标记
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 去掉粗体/斜体
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    # 去掉链接 [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 去掉图片 ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    # 去掉表格分隔线
    text = re.sub(r'\|[\s\-:]+\|', '', text)
    # 去掉行首 | 和行尾 |
    text = re.sub(r'^\||\|$', '', text, flags=re.MULTILINE)
    # 去掉代码块标记
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # 压缩多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
