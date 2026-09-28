"""Retriever Layer - Layered Retriever."""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from ..embedding.engine import EmbeddingEngine
from ..vector.store import VectorStore
from .company_routing import CompanyRouter, RouteDecision, build_document_row_id_map
from .config import LAYER_KEYWORDS, RetrieverConfig
from .evidence_sufficiency import rerank_by_sufficiency
from .ipo_specific_rerank import rerank_ipo_specific
from .answer_excerpt_rerank import rerank_answer_excerpt
from .evidence_role import rerank_evidence_role
from .related_party_quant import (
    build_related_party_quant_queries,
    is_related_party_dependence_query,
    merge_complementary_results,
    related_party_quant_signal,
    rerank_related_party_quant,
)
from .models import SearchResult
from .query_intent import build_intent_queries, merge_multiquery_results, section_hard_prior_score
from .term_normalization import (
    TERM_ALIASES,
    expand_query_with_aliases,
    infer_section_families,
    normalize_text,
    section_family_match,
    term_matches,
)


class LayeredRetriever:
    SUMMARY_SECTIONS = {"\u6982\u8981", "summary"}
    SUMMARY_TEXT_BOOST = 0.04
    KEYWORD_COVERAGE_BOOST = 1.0
    TABLE_FACT_BOOST = 0.6
    QUANT_INTENT_BOOST = 0.35
    SECTION_AWARE_BOOST = 0.08
    QUERY_STOPWORDS = {"\u98ce\u9669", "\u98a8\u96aa"}
    QUANT_INTENT_TERMS = {
        "占比", "百分比", "比例", "集中度", "依赖", "依賴",
        "重大依赖", "收入贡献", "收益贡献", "销售额", "金额",
        "关联方", "關聯方", "客户集中", "供應商集中", "供应商集中",
    }
    TABLE_FACT_TERMS = {
        "\u4eba\u6c11\u5e01", "\u767e\u4e07", "\u4ebf\u5143", "\u6e2f\u5143", "\u6536\u5165",
        "\u6536\u76ca", "\u5360\u6bd4", "\u5173\u8054\u65b9", "\u72ec\u7acb\u5ba2\u6237",
        "\u5ba2\u6237", "\u4f9b\u5e94\u5546", "\u91c7\u8d2d", "\u9500\u552e", "\u6240\u5f97\u6b3e\u9879\u51c0\u989d",
    }
    TRADITIONAL_TO_SIMPLIFIED = str.maketrans({
        "\u9805": "\u9879", "\u61c9": "\u5e94", "\u8cec": "\u8d26", "\u8667": "\u4e8f", "\u640d": "\u635f",
        "\u52d9": "\u52a1", "\u7d04": "\u7ea6", "\u984d": "\u989d", "\u767c": "\u53d1", "\u73fe": "\u73b0",
        "\u8cc7": "\u8d44", "\u8b49": "\u8bc1", "\u8cea": "\u8d28", "\u9072": "\u8fdf", "\u8ce0": "\u8d54",
        "\u511f": "\u507f", "\u71df": "\u8425", "\u696d": "\u4e1a", "\u8ca1": "\u8d22", "\u5be6": "\u5b9e",
        "\u969b": "\u9645", "\u9593": "\u95f4", "\u9810": "\u9884", "\u8207": "\u4e0e", "\u95dc": "\u5173",
        "\u806f": "\u8054", "\u98a8": "\u98ce", "\u96aa": "\u9669", "\u6578": "\u6570", "\u6e1b": "\u51cf",
        "\u7d93": "\u7ecf", "\u6fdf": "\u6d4e", "\u72c0": "\u72b6", "\u6cc1": "\u51b5", "\u97ff": "\u54cd",
        "\u7d50": "\u7ed3", "\u842c": "\u4e07", "\u8b8a": "\u53d8", "\u50f9": "\u4ef7", "\u7121": "\u65e0",
        "\u70ba": "\u4e3a", "\u5f8c": "\u540e", "\u8a34": "\u8bc9", "\u8a1f": "\u8bbc", "\u63a1": "\u91c7",
        "\u8cfc": "\u8d2d", "\u7e3d": "\u603b", "\u4f54": "\u5360", "\u6703": "\u4f1a", "\u8a08": "\u8ba1",
        "\u5e2b": "\u5e08", "\u5831": "\u62a5", "\u7522": "\u4ea7", "\u6236": "\u6237", "\u9ede": "\u70b9",
        "\u8edf": "\u8f6f", "\u83ef": "\u534e", "\u570b": "\u56fd", "\u96fb": "\u7535", "\u8eca": "\u8f66",
    })

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
        self._company_router: Optional[CompanyRouter] = None
        self._document_row_ids: Dict[str, List[int]] = {}
        self._routing_cache_signature: Optional[Tuple[int, int]] = None

    def search(
        self,
        query: str,
        layer: str = "all",
        top_k: Optional[int] = None,
        metadata_filters: Optional[Dict[str, str]] = None,
    ) -> List[SearchResult]:
        """Search vector candidates and apply layered Retriever post-processing."""
        top_k = top_k or self.config.top_k

        query_embedding = self.embedding_engine.embed_text(query)
        route = self._resolve_route(query, metadata_filters)
        pool_mult = max(int(self.config.candidate_pool_multiplier or 1), 1)
        # Answer-excerpt rerank needs a modestly wider candidate pool so concrete
        # disclosure facts can outrank nearby boilerplate; final returned top_k is unchanged.
        if getattr(self.config, "enable_answer_excerpt_rerank", False):
            pool_mult = max(pool_mult, 5)
        # Business consequence-chain intents often rank outside the default dense head.
        # When multiquery/excerpt flags are on, widen pool only for those intents.
        if self.config.enable_intent_multiquery or getattr(self.config, "enable_answer_excerpt_rerank", False):
            try:
                from .query_intent import infer_query_intent

                _intent = infer_query_intent(query)
            except Exception:
                _intent = "generic_other"
            if _intent in {"customer_credit_deterioration", "competitive_pricing_pressure", "customer_concentration", "working_capital_mechanism"}:
                pool_mult = max(pool_mult, 10)
            if getattr(self.config, "enable_related_party_quant_complement", False) and is_related_party_dependence_query(query):
                pool_mult = max(pool_mult, 12)
        candidate_top_k = max(top_k, top_k * pool_mult)
        raw_results, routing_metadata = self._search_raw_candidates(
            query_embedding,
            candidate_top_k,
            layer,
            route,
            metadata_filters,
        )
        if self.config.enable_intent_multiquery:
            aux_queries = build_intent_queries(query, self.config.max_intent_aux_queries)
            aux_runs = []
            for aux_query in aux_queries:
                aux_embedding = self.embedding_engine.embed_text(aux_query)
                aux_raw, _ = self._search_raw_candidates(
                    aux_embedding,
                    candidate_top_k,
                    layer,
                    route,
                    metadata_filters,
                )
                aux_runs.append(aux_raw)
            if aux_runs:
                raw_results = merge_multiquery_results(raw_results, aux_runs)
            routing_metadata["intent_aux_queries"] = aux_queries
            routing_metadata["intent_multiquery_enabled"] = True
        else:
            routing_metadata["intent_multiquery_enabled"] = False

        results = []
        for r in raw_results:
            chunk = self._get_chunk(r.get("document_id", ""), r.get("chunk_id", ""))
            text = self._get_chunk_text(r, chunk)
            metadata = dict(r.get("metadata", {}))
            metadata.update(routing_metadata)
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

        if layer != "all":
            results = [r for r in results if r.block_type != "image"]

        if self.config.enable_layer_filter and layer != "all":
            results = self._filter_by_layer(results, layer)

        results = [r for r in results if r.score >= self.config.min_score]

        # Related-party quant complement (flagged): pull same-doc table/quant rows
        # that dense head often ranks outside top50 for narrative-heavy queries.
        if getattr(self.config, "enable_related_party_quant_complement", False) and is_related_party_dependence_query(query):
            complement_queries = build_related_party_quant_queries(query, max_queries=2)
            complement_results = []
            for cq in complement_queries:
                cq_emb = self.embedding_engine.embed_text(cq)
                raw_comp, _ = self._search_raw_candidates(
                    cq_emb,
                    max(candidate_top_k, top_k * 15),
                    layer,
                    route,
                    metadata_filters,
                )
                for r in raw_comp:
                    chunk = self._get_chunk(r.get("document_id", ""), r.get("chunk_id", ""))
                    text_c = self._get_chunk_text(r, chunk)
                    metadata = dict(r.get("metadata", {}))
                    metadata.update(routing_metadata)
                    metadata["related_party_quant_complement"] = True
                    if chunk:
                        metadata["evidence_ids"] = chunk.get("evidence_ids", [])
                    sr = SearchResult(
                        chunk_id=r.get("chunk_id", ""),
                        evidence_ids=metadata.get("evidence_ids", []),
                        document_id=r.get("document_id", ""),
                        company=r.get("company", ""),
                        pages=r.get("pages", []),
                        section_path=r.get("section_path", []),
                        block_type=r.get("block_type", ""),
                        score=float(r.get("score", 0.0) or 0.0),
                        text=text_c,
                        metadata=metadata,
                    )
                    if related_party_quant_signal(sr) >= 0.25 or sr.block_type == "table":
                        complement_results.append(sr)
            if complement_results:
                results = merge_complementary_results(
                    results,
                    complement_results,
                    top_k=max(len(results) + len(complement_results), top_k * 3),
                )
                routing_metadata["related_party_quant_complement_enabled"] = True
                routing_metadata["related_party_quant_complement_queries"] = complement_queries
            results = rerank_related_party_quant(query, results)

        results = self._boost_keyword_coverage(query, results)
        results = self._boost_table_fact_coverage(query, results)
        results = self._boost_quantitative_intent(query, results)
        results = self._boost_section_aware(query, results)
        results = self._boost_summary_text(results)
        results = results[:candidate_top_k]
        if self.config.enable_section_hard_prior:
            results = self._boost_section_hard_prior(query, results)
        if self.config.enable_ipo_specific_rerank:
            results = rerank_ipo_specific(query, results)
        if getattr(self.config, "enable_answer_excerpt_rerank", False):
            results = rerank_answer_excerpt(query, results)
        if getattr(self.config, "enable_evidence_role_rerank", False):
            results = rerank_evidence_role(query, results)
        if self.config.enable_sufficiency_rerank:
            results = rerank_by_sufficiency(query, results)
        # Final related-party quant pass after other rerankers, so table share rows
        # are not re-buried by generic excerpt/role preferences.
        if getattr(self.config, "enable_related_party_quant_complement", False) and is_related_party_dependence_query(query):
            results = rerank_related_party_quant(query, results)
        results = results[:top_k]

        logger.info(f"Search complete: query='{query}', layer={layer}, results={len(results)}")
        return results

    def _resolve_route(
        self,
        query: str,
        metadata_filters: Optional[Dict[str, str]],
    ) -> RouteDecision:
        self._refresh_routing_catalog()
        if not self._company_router:
            return RouteDecision("no_match", "global_fallback")
        return self._company_router.resolve(query, metadata_filters)

    def _refresh_routing_catalog(self) -> None:
        stats = self.vector_store.get_stats()
        signature = (len(self.vector_store.documents), int(stats.get("total_vectors", 0) or 0))
        if signature == self._routing_cache_signature:
            return
        self._company_router = CompanyRouter(self.vector_store.documents)
        self._document_row_ids = build_document_row_id_map(self.vector_store.documents)
        self._routing_cache_signature = signature

    def _search_raw_candidates(
        self,
        query_embedding: List[float],
        top_k: int,
        layer: str,
        route: RouteDecision,
        metadata_filters: Optional[Dict[str, str]],
    ) -> Tuple[List[dict], Dict[str, object]]:
        routing_metadata: Dict[str, object] = {
            "routing_status": route.status,
            "routing_source": route.source,
            "routing_document_id": route.document_id,
        }

        if route.status == "matched" and route.document_id:
            row_ids = self._document_row_ids.get(route.document_id, [])
            raw_results = self.vector_store.search_by_row_ids(query_embedding, row_ids, top_k=len(row_ids))
            # Document-id routing already scopes the corpus. Re-applying a strict
            # company-name filter here is unsafe for HK prospectuses because the
            # same issuer may appear as short/long or traditional/simplified names.
            if metadata_filters:
                scoped = dict(metadata_filters)
                if scoped.get("document_id") or route.document_id:
                    scoped.pop("company", None)
                    scoped.setdefault("document_id", route.document_id)
                raw_results = [r for r in raw_results if self._matches_metadata_filters(r, scoped)]
            routing_metadata["routing_candidate_count"] = len(row_ids)
            routing_metadata["routing_used_row_id_subset"] = True
            routing_metadata["routing_calls_top_k_total_vectors"] = False
            return raw_results, routing_metadata

        fetch_k = top_k * 5 if layer != "all" else top_k * 2
        raw_results = self.vector_store.search(query_embedding, top_k=fetch_k)
        if metadata_filters and not any(key in metadata_filters for key in ("document_id", "company")):
            raw_results = [r for r in raw_results if self._matches_metadata_filters(r, metadata_filters)]
        routing_metadata["routing_source"] = "global_fallback"
        routing_metadata["routing_candidate_count"] = min(fetch_k, self.vector_store.get_stats().get("total_vectors", fetch_k))
        routing_metadata["routing_used_row_id_subset"] = False
        routing_metadata["routing_calls_top_k_total_vectors"] = False
        return raw_results, routing_metadata

    def _matches_metadata_filters(self, raw_result: dict, filters: Dict[str, str]) -> bool:
        document_id = raw_result.get("document_id", "")
        company = raw_result.get("company", "")
        metadata = raw_result.get("metadata", {})

        expected_document_id = filters.get("document_id")
        if expected_document_id and document_id != expected_document_id:
            return False

        expected_company = filters.get("company")
        if expected_company:
            actual_company = self._normalize_query_text(company)
            wanted_company = self._normalize_query_text(expected_company)
            # Accept short-name / legal-name variants after normalization.
            company_ok = (
                (wanted_company and actual_company and (
                    wanted_company in actual_company
                    or actual_company in wanted_company
                    or wanted_company[:4] == actual_company[:4]
                ))
            )
            if not company_ok:
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
            haystack = " ".join(result.section_path) + " " + (result.text or "")
            coverage = sum(1 for term in terms if term_matches(haystack, term)) / len(terms)
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
        expanded = expand_query_with_aliases(query)
        query_norm = self._normalize_query_text(query)
        terms = []

        def _accept(term: str) -> None:
            normalized = self._normalize_query_text(term)
            if len(normalized) < 2 or normalized in self.QUERY_STOPWORDS:
                return
            if any(normalized in company or company in normalized for company in companies):
                return
            terms.append(normalized)

        # Prefer multi-character tokens from whitespace split on expanded aliases.
        for term in re.split(r"\s+", expanded.strip()):
            _accept(term)
        # Also keep original whitespace terms from the raw query.
        for term in re.split(r"\s+", query.strip()):
            _accept(term)
        # Continuous Chinese queries rarely have spaces; harvest known risk aliases.
        for canonical, aliases in TERM_ALIASES.items():
            if self._normalize_query_text(canonical) in query_norm or any(
                self._normalize_query_text(alias) in query_norm for alias in aliases
            ):
                _accept(canonical)
                for alias in aliases:
                    _accept(alias)
        return list(dict.fromkeys(terms))

    def _normalize_query_text(self, text: str) -> str:
        return normalize_text(text)

    def _boost_table_fact_coverage(
        self,
        query: str,
        results: List[SearchResult],
    ) -> List[SearchResult]:
        numeric_terms = self._query_numeric_fact_terms(query)
        semantic_terms = self._query_table_semantic_terms(query)
        if not numeric_terms or not semantic_terms:
            return results

        boosted = []
        for index, result in enumerate(results):
            haystack = self._normalize_query_text(
                " ".join(result.section_path) + " " + (result.text or "")
            )
            numeric_hits = sum(1 for term in numeric_terms if term in haystack)
            semantic_hits = sum(1 for term in semantic_terms if term in haystack)
            if numeric_hits and semantic_hits:
                numeric_coverage = numeric_hits / len(numeric_terms)
                semantic_coverage = semantic_hits / len(semantic_terms)
                result.score += self.TABLE_FACT_BOOST * min(numeric_coverage, semantic_coverage)
            boosted.append((result.score, -index, result))

        boosted.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [result for _, _, result in boosted]

    def _query_numeric_fact_terms(self, query: str) -> List[str]:
        normalized = self._normalize_query_text(query)
        terms = []
        for term in re.findall(r"\d+(?:\.\d+)?%?", normalized):
            terms.append(term.rstrip("%"))
        for term in re.findall(r"\b20\d{2}\b", normalized):
            terms.append(term)
        return list(dict.fromkeys(term for term in terms if term))

    def _query_table_semantic_terms(self, query: str) -> List[str]:
        normalized = self._normalize_query_text(query)
        terms = [
            self._normalize_query_text(term)
            for term in self.TABLE_FACT_TERMS
            if self._normalize_query_text(term) in normalized
        ]
        return list(dict.fromkeys(terms))


    def _query_has_quantitative_intent(self, query: str) -> bool:
        """True when user asks for ratios/amounts/concentration, even without numbers."""
        normalized = self._normalize_query_text(query)
        if not normalized:
            return False
        for term in self.QUANT_INTENT_TERMS:
            if self._normalize_query_text(term) in normalized:
                return True
        # Common NL question patterns.
        patterns = ("有多严重", "是否严重", "具体占比", "具体金额", "给出占比", "给出金额")
        return any(self._normalize_query_text(p) in normalized for p in patterns)

    def _result_quantitative_signal(self, result: SearchResult) -> float:
        """0-1 signal for concentration/related-party quantitative evidence."""
        haystack_raw = " ".join(result.section_path) + " " + (result.text or "")
        haystack = self._normalize_query_text(haystack_raw)
        if not haystack:
            return 0.0

        noise_markers = ("企业所得税", "企業所得稅", "优惠税率", "優惠稅率", "增值税", "增值稅")
        core_markers = (
            "客户", "客戶", "关联方", "關聯方", "供应商", "供應商",
            "五大客户", "五大客戶", "收入占比", "收益占比", "总收益", "總收益",
        )
        has_core = any(self._normalize_query_text(m) in haystack for m in core_markers)
        if any(self._normalize_query_text(m) in haystack for m in noise_markers) and not has_core:
            return 0.0

        pcts = re.findall(r"\d+(?:\.\d+)?%", haystack_raw)
        bare_ratios = re.findall(r"\d{1,2}\.\d", haystack_raw)
        semantic_terms = [
            "客户", "客戶", "关联方", "關聯方", "收益", "收入", "占比", "百分比",
            "集中", "依赖", "依賴", "供应商", "供應商", "五大客户", "五大客戶",
            "总收益", "總收益", "销售", "銷售",
        ]
        semantic_hits = sum(
            1 for term in semantic_terms if self._normalize_query_text(term) in haystack
        )
        if not pcts and not (bare_ratios and semantic_hits >= 2):
            return 0.0
        if semantic_hits <= 0:
            return 0.0
        table_like = ("表格" in haystack_raw) or (result.block_type == "table") or ("|" in haystack_raw)
        score = 0.0
        score += min(len(pcts), 4) * 0.18
        score += min(semantic_hits, 4) * 0.12
        if table_like:
            score += 0.15
        if (("客户a" in haystack) or ("客户 a" in haystack) or ("關聯方" in haystack_raw) or ("关联方" in haystack)) and len(pcts) >= 2:
            score += 0.25
        if ("总收益" in haystack) or ("總收益" in haystack) or ("收入占比" in haystack) or ("收益占比" in haystack):
            score += 0.1
        return max(0.0, min(score, 1.0))

    def _boost_quantitative_intent(
        self,
        query: str,
        results: List[SearchResult],
    ) -> List[SearchResult]:
        """Promote quantitative concentration evidence for NL ratio/dependency questions."""
        if not results or not self._query_has_quantitative_intent(query):
            return results

        boosted = []
        for index, result in enumerate(results):
            signal = self._result_quantitative_signal(result)
            if signal:
                result.score += self.QUANT_INTENT_BOOST * signal
            boosted.append((result.score, -index, result))
        boosted.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [result for _, _, result in boosted]

    def _boost_section_aware(
        self,
        query: str,
        results: List[SearchResult],
    ) -> List[SearchResult]:
        """Small boost for candidates whose section family matches query intent."""
        families = infer_section_families(query)
        if not families or not results:
            return results

        query_norm = normalize_text(query)
        support_triggers = [
            "净亏损", "净负债", "经营活动所用现金", "许可证", "诉讼",
            "所得款项", "募资", "董事确认", "隐私", "数据", "仲裁",
        ]
        active_triggers = [
            trigger for trigger in support_triggers
            if normalize_text(trigger) in query_norm
        ]

        boosted = []
        for index, result in enumerate(results):
            score = result.score
            if section_family_match(result.section_path, families):
                score += self.SECTION_AWARE_BOOST
                if active_triggers:
                    haystack = " ".join(result.section_path) + " " + (result.text or "")
                    if any(term_matches(haystack, trigger) for trigger in active_triggers):
                        score += self.SECTION_AWARE_BOOST * 0.25
                result.score = score
            boosted.append((score, -index, result))

        boosted.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [result for _, _, result in boosted]

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

    def _boost_section_hard_prior(
        self,
        query: str,
        results: List[SearchResult],
    ) -> List[SearchResult]:
        boosted = []
        for index, result in enumerate(results):
            delta = section_hard_prior_score(query, result.section_path, result.text or "")
            if delta:
                result.score += delta
                metadata = dict(result.metadata or {})
                metadata["section_hard_prior"] = round(delta, 4)
                result.metadata = metadata
            boosted.append((result.score, -index, result))
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
        keywords = LAYER_KEYWORDS.get(layer, [])
        if not keywords:
            logger.warning(f"Unknown layer: {layer}; returning all results")
            return results

        filtered = []
        for result in results:
            section_text = " ".join(result.section_path)
            text = result.text or ""
            combined = section_text + " " + text

            if any(kw in combined for kw in keywords):
                filtered.append(result)

        if len(filtered) < 3:
            logger.info(f"Layer '{layer}' produced too few results; returning original non-image results")
            return results

        return filtered

    def _get_chunk(self, document_id: str, chunk_id: str) -> dict:
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
