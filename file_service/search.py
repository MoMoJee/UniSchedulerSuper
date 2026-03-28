from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from file_service.models import UserFile


class FileSearchEngine:
    """基础文本检索引擎"""

    @staticmethod
    def search(user, query: str, limit: int = 10,
               category: Optional[str] = None, folder_id: Optional[int] = None) -> list:
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


class RAGSearchProvider(ABC):
    """
    RAG 检索提供者抽象接口。
    所有实现必须提供文档索引、语义检索、文档删除三个核心能力。
    """

    @abstractmethod
    def index_document(self, doc_id: str, text: str,
                       metadata: Optional[Dict] = None) -> bool:
        pass

    @abstractmethod
    def search(self, query: str, user_id: int,
               top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def delete_document(self, doc_id: str) -> bool:
        pass

    def batch_index(self, documents: List[Dict]) -> Dict[str, bool]:
        results = {}
        for doc in documents:
            results[doc['doc_id']] = self.index_document(
                doc['doc_id'], doc['text'], doc.get('metadata')
            )
        return results


class LocalTextSearchProvider(RAGSearchProvider):
    """
    本地文本检索实现（当前默认）。
    index_document / delete_document 为空操作（不需要显式索引，直接查库）。
    search 委托给 FileSearchEngine。
    """

    def index_document(self, doc_id, text, metadata=None):
        return True

    def search(self, query, user_id, top_k=5, filters=None):
        from django.contrib.auth.models import User
        user = User.objects.get(id=user_id)
        results = FileSearchEngine.search(
            user=user, query=query, limit=top_k,
            category=filters.get('category') if filters else None,
            folder_id=filters.get('folder_id') if filters else None,
        )
        return [{
            'doc_id': str(r['file'].id),
            'score': r['score'],
            'chunk_text': r['snippet'],
            'metadata': {
                'filename': r['file'].filename,
                'category': r['file'].category,
            }
        } for r in results]

    def delete_document(self, doc_id):
        return True


class AliyunKnowledgeBaseProvider(RAGSearchProvider):
    """
    阿里云百炼知识库服务（后期接入）。
    此类暂为占位，所有方法抛出 NotImplementedError。
    """

    def index_document(self, doc_id, text, metadata=None):
        raise NotImplementedError("阿里云知识库尚未接入")

    def search(self, query, user_id, top_k=5, filters=None):
        raise NotImplementedError("阿里云知识库尚未接入")

    def delete_document(self, doc_id):
        raise NotImplementedError("阿里云知识库尚未接入")


def get_search_provider() -> RAGSearchProvider:
    """
    获取当前激活的检索提供者。
    可通过 settings.FILE_SERVICE_RAG_PROVIDER 配置：
    - 'local'（默认）
    - 'aliyun'
    """
    from django.conf import settings
    provider_name = getattr(settings, 'FILE_SERVICE_RAG_PROVIDER', 'local')
    if provider_name == 'aliyun':
        return AliyunKnowledgeBaseProvider()
    return LocalTextSearchProvider()
