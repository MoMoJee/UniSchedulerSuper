from file_service.models import UserFile


class FileSearchEngine:
    """基础文本检索引擎"""

    @staticmethod
    def search(user, query: str, limit: int = 10,
               category: str = None, folder_id: int = None) -> list:
        """
        在用户云盘文件中搜索相关内容。

        评分策略（加权叠加）：
        1. 精确短语匹配      +10 分
        2. 所有关键词 AND 命中  +5 分
        3. 单个关键词命中      +1 分/个
        4. 文件名命中          +3 分

        返回: [{file: UserFile, score: int, snippet: str}, ...]
        """
        qs = UserFile.objects.filter(user=user, is_deleted=False)
        qs = qs.exclude(search_text='')

        if category:
            qs = qs.filter(category=category)
        if folder_id:
            qs = qs.filter(folder_id=folder_id)

        keywords = query.split()
        if not keywords:
            return []

        results = []
        q_lower = query.lower()

        for uf in qs.iterator():
            text = uf.search_text.lower()
            filename = uf.filename.lower()
            score = 0

            # 精确短语匹配
            if q_lower in text:
                score += 10

            # 文件名包含查询词
            if q_lower in filename:
                score += 3

            # 所有关键词命中
            hits = [kw.lower() for kw in keywords if kw.lower() in text]
            if len(hits) == len(keywords):
                score += 5

            # 单个关键词计分
            score += len(hits)

            if score > 0:
                snippet = FileSearchEngine._extract_snippet(text, keywords)
                results.append({
                    'file': uf,
                    'score': score,
                    'snippet': snippet,
                })

        results.sort(key=lambda x: -x['score'])
        return results[:limit]

    @staticmethod
    def _extract_snippet(text: str, keywords: list, context_chars: int = 120) -> str:
        """从文本中提取包含关键词的上下文片段。"""
        text_lower = text.lower()
        best_pos = -1

        for kw in keywords:
            pos = text_lower.find(kw.lower())
            if pos >= 0:
                best_pos = pos
                break

        if best_pos < 0:
            return text[:context_chars * 2] + '...' if len(text) > context_chars * 2 else text

        start = max(0, best_pos - context_chars)
        end = min(len(text), best_pos + context_chars)
        snippet = text[start:end]

        if start > 0:
            snippet = '...' + snippet
        if end < len(text):
            snippet = snippet + '...'

        return snippet
