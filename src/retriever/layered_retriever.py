"""
Retriever Layer - Layered Retriever

支持按Layer过滤：financial / legal / governance / market / all
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from ..embedding.engine import EmbeddingEngine
from ..vector.store import VectorStore
from .config import LAYER_KEYWORDS, RetrieverConfig
from .models import SearchResult


class LayeredRetriever:
    SUMMARY_SECTIONS = {"\u6982\u8981", "summary"}
    SUMMARY_TEXT_BOOST = 0.04
    KEYWORD_COVERAGE_BOOST = 1.0
    QUERY_STOPWORDS = {"风险", "風險"}
    TRADITIONAL_TO_SIMPLIFIED = str.maketrans({
        "項": "项", "應": "应", "賬": "账", "虧": "亏", "損": "损",
        "務": "务", "約": "约", "額": "额", "發": "发", "現": "现",
        "資": "资", "證": "证", "質": "质", "遲": "迟", "賠": "赔",
        "償": "偿", "營": "营", "業": "业", "財": "财", "實": "实",
        "際": "际", "間": "间", "預": "预", "與": "与", "關": "关",
        "聯": "联", "風": "风", "險": "险", "數": "数", "減": "减",
        "經": "经", "濟": "济", "狀": "状", "況": "况", "響": "响",
        "結": "结", "萬": "万", "變": "变", "價": "价", "無": "无",
        "為": "为", "後": "后", "訴": "诉", "訟": "讼", "採": "采",
        "購": "购", "總": "总", "佔": "占", "會": "会", "計": "计",
        "師": "师", "報": "报", "產": "产", "戶": "户",
    })

    """分层检索器"""

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_engine: EmbeddingEngine,
        config: RetrieverConfig = None,
        chunk_dir: str = "data/chunks",
    ):
        self.vector_store = vector_store
        self.embedding_engine = embedding_engine
        self.config = config or RetrieverConfig()
        self.chunk_dir = Path(chunk_dir)
        self._chunk_cache: Dict[str, Dict[str, dict]] = {}

    def search(
        self,
        query: str,
        layer: str = "all",
        top_k: Optional[int] = None,
        metadata_filters: Optional[Dict[str, str]] = None,
    ) -> List[SearchResult]:
        """
        检索

        Args:
            query: 查询文本
            layer: 检索层 (financial/legal/governance/market/all)
            top_k: 返回数量

        Returns:
            List[SearchResult]: 检索结果
        """
        top_k = top_k or self.config.top_k

        # 1. 向量检索（多取一些用于过滤）
        fetch_k = self.vector_store.get_stats().get("total_vectors", top_k) if metadata_filters else (
            top_k * 5 if layer != "all" else top_k * 2
        )
        query_embedding = self.embedding_engine.embed_text(query)
        raw_results = self.vector_store.search(query_embedding, top_k=fetch_k)
        if metadata_filters:
            raw_results = [r for r in raw_results if self._matches_metadata_filters(r, metadata_filters)]

        # 2. 转换为SearchResult
        results = []
        for r in raw_results:
            chunk = self._get_chunk(r.get("document_id", ""), r.get("chunk_id", ""))
            text = self._get_chunk_text(r, chunk)
            metadata = dict(r.get("metadata", {}))
            if chunk:
                metadata["evidence_ids"] = chunk.get("evidence_ids", [])

            result = SearchResult(
                chunk_id=r.get("chunk_id", ""),
                evidence_ids=metadata.get("evidence_ids", []),
                document_id=r.get("document_id", ""),
                company=r.get("company", ""),
                pages=r.get("pages", []),
                section_path=r.get("section_path", []),
                block_type=r.get("block_type", ""),
                score=r.get("score", 0.0),
                text=text,
                metadata=metadata,
            )
            results.append(result)

        # 非all层默认排除图片，避免logo/装饰图污染文本风险检索。
        if layer != "all":
            results = [r for r in results if r.block_type != "image"]

        # 3. Layer过滤
        if self.config.enable_layer_filter and layer != "all":
            results = self._filter_by_layer(results, layer)

        # 4. 分数过滤
        results = [r for r in results if r.score >= self.config.min_score]

        # 5. 截断
        results = self._boost_keyword_coverage(query, results)
        results = self._boost_summary_text(results)
        results = results[:top_k]

        logger.info(f"检索完成: query='{query}', layer={layer}, results={len(results)}")
        return results

    def _matches_metadata_filters(self, raw_result: dict, filters: Dict[str, str]) -> bool:
        document_id = raw_result.get("document_id", "")
        company = raw_result.get("company", "")
        metadata = raw_result.get("metadata", {})

        expected_document_id = filters.get("document_id")
        if expected_document_id and document_id != expected_document_id:
            return False

        expected_company = filters.get("company")
        if expected_company and expected_company not in company and company not in expected_company:
            return False

        expected_year = filters.get("year")
        if expected_year:
            year = str(metadata.get("year") or document_id.split("_", 1)[0])
            if year != str(expected_year):
                return False

        return True

    def _boost_keyword_coverage(
        self,
        query: str,
        results: List[SearchResult],
    ) -> List[SearchResult]:
        terms = self._query_terms(query, results)
        if not terms:
            return results

        boosted = []
        for index, result in enumerate(results):
            haystack = self._normalize_query_text(
                " ".join(result.section_path) + " " + (result.text or "")
            )
            coverage = sum(1 for term in terms if term in haystack) / len(terms)
            if coverage:
                result.score += self.KEYWORD_COVERAGE_BOOST * coverage
            boosted.append((result.score, -index, result))

        boosted.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [result for _, _, result in boosted]

    def _query_terms(self, query: str, results: List[SearchResult]) -> List[str]:
        companies = {
            self._normalize_query_text(result.company)
            for result in results
            if result.company
        }
        terms = []
        for term in re.split(r"\s+", query.strip()):
            normalized = self._normalize_query_text(term)
            if len(normalized) < 2 or normalized in self.QUERY_STOPWORDS:
                continue
            if any(normalized in company or company in normalized for company in companies):
                continue
            terms.append(normalized)
        return list(dict.fromkeys(terms))

    def _normalize_query_text(self, text: str) -> str:
        return str(text).translate(self.TRADITIONAL_TO_SIMPLIFIED).lower()

    def _boost_summary_text(self, results: List[SearchResult]) -> List[SearchResult]:
        boosted = []
        for index, result in enumerate(results):
            score = result.score
            if result.block_type == "text" and self._is_summary_section(result.section_path):
                score += self.SUMMARY_TEXT_BOOST
                result.score = score
            boosted.append((score, -index, result))

        boosted.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [result for _, _, result in boosted]

    def _is_summary_section(self, section_path: List[str]) -> bool:
        for section in section_path:
            normalized = "".join(str(section).split()).lower()
            if normalized in self.SUMMARY_SECTIONS:
                return True
        return False

    def _filter_by_layer(
        self,
        results: List[SearchResult],
        layer: str,
    ) -> List[SearchResult]:
        """按Layer过滤"""
        keywords = LAYER_KEYWORDS.get(layer, [])
        if not keywords:
            logger.warning(f"未知Layer: {layer}, 返回全部结果")
            return results

        filtered = []
        for result in results:
            section_text = " ".join(result.section_path)
            text = result.text or ""
            combined = section_text + " " + text

            if any(kw in combined for kw in keywords):
                filtered.append(result)

        if len(filtered) < 3:
            logger.info(f"Layer '{layer}' 过滤后结果不足，返回非图片原始结果")
            return results

        return filtered

    def _get_chunk(self, document_id: str, chunk_id: str) -> dict:
        """从chunks.json回查chunk详情"""
        if not document_id or not chunk_id:
            return {}

        if document_id not in self._chunk_cache:
            chunks_path = self.chunk_dir / document_id / "chunks.json"
            if not chunks_path.exists():
                self._chunk_cache[document_id] = {}
            else:
                with open(chunks_path, "r", encoding="utf-8") as f:
                    chunks = json.load(f)
                self._chunk_cache[document_id] = {
                    chunk.get("chunk_id", ""): chunk for chunk in chunks
                }

        return self._chunk_cache[document_id].get(chunk_id, {})

    def _get_chunk_text(self, raw_result: dict, chunk: dict) -> str:
        """从chunk详情或metadata获取检索展示文本"""
        if chunk:
            block_type = chunk.get("block_type", "")
            if block_type == "text":
                return chunk.get("text", "")
            if block_type == "table":
                return chunk.get("table_description", "")
            if block_type == "image":
                return chunk.get("image_description", "") or chunk.get("image_caption", "")

        metadata = raw_result.get("metadata", {})
        return metadata.get("text_preview", "")
