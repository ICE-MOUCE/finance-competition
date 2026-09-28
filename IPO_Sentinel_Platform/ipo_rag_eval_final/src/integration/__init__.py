# -*- coding: utf-8 -*-
"""Integration package for RAG x Agent adapter."""
from src.integration.agent_adapter import map_search_response_to_agent, query_for_agent
from src.integration.schema_map import EvidenceObject, RiskClaim, PARSER_VERSION

__all__ = [
    "EvidenceObject",
    "RiskClaim",
    "PARSER_VERSION",
    "map_search_response_to_agent",
    "query_for_agent",
]
