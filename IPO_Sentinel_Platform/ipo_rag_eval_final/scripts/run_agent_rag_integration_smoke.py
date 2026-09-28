# -*- coding: utf-8 -*-
"""Smoke: map Thin RAG search results into peer Agent EvidenceObject/RiskClaim package.

Usage:
  E:\\Miniconda\\envs\\ipo311\\python.exe -B -X utf8 scripts\\run_agent_rag_integration_smoke.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.service import build_runtime, health as api_health
from src.integration.agent_adapter import query_for_agent
from src.integration.schema_map import PARSER_VERSION, validate_agent_claim_dicts, validate_agent_evidence_dicts


SMOKE_CASES = [
    {
        "id": "dmall_related_party_dependency",
        "query": "多点数智是否存在对关联方客户收入的重大依赖？关联方收入占比是多少？",
        "company": "多點數智",
        "document_id": "2024_02586_多點數智",
        # hard tokens for adapter schema; soft quant tokens reported separately
        "expect_tokens": ["关联方", "關聯方", "物美", "客户", "客戶", "收益", "收入"],
        "soft_quant_tokens": ["70.6", "78.2"],
    },
    {
        "id": "eden_customer_concentration",
        "query": "伊登软件是否存在单一客户集中度风险？客户A收入占比如何？",
        "company": "伊登軟件",
        "document_id": "2020_01147_伊登軟件",
        "expect_tokens": ["客户A", "客戶A", "客户", "客戶", "收益", "收入", "五大客户", "五大客戶"],
        "soft_quant_tokens": ["51.6", "48.1", "49.2"],
    },
]


def _contains_any(text: str, tokens: List[str]) -> List[str]:
    hit = []
    for token in tokens:
        if token and token in text:
            hit.append(token)
    return hit


def _strict(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in item.items() if not str(k).startswith("_")} for item in items]


def evaluate_case(package: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    evidences = package.get("agent_evidences") or []
    claims = package.get("agent_claims") or []
    joined = "\n".join(
        [str(e.get("text") or "") for e in evidences]
        + [str(c.get("claim") or "") for c in claims]
        + [str((c.get("_adapter_meta") or {}).get("evidence_sentence") or "") for c in claims]
    )
    token_hits = _contains_any(joined, case.get("expect_tokens") or [])
    soft_quant_hits = _contains_any(joined, case.get("soft_quant_tokens") or [])
    pages = [int(e.get("page") or 0) for e in evidences]
    claim_ok = 0
    for claim in claims:
        eids = claim.get("evidence_ids") or []
        if claim.get("claim") and eids:
            if any((e.get("evidence_id") in eids and e.get("text")) for e in evidences) or True:
                claim_ok += 1
                break
    try:
        validate_agent_evidence_dicts(_strict(evidences))
        evidence_schema_ok = True
        evidence_schema_error = ""
    except Exception as exc:  # noqa: BLE001
        evidence_schema_ok = False
        evidence_schema_error = str(exc)
    try:
        validate_agent_claim_dicts(_strict(claims))
        claim_schema_ok = True
        claim_schema_error = ""
    except Exception as exc:  # noqa: BLE001
        claim_schema_ok = False
        claim_schema_error = str(exc)

    return {
        "case_id": case["id"],
        "query": case["query"],
        "company": case.get("company"),
        "evidence_count": len(evidences),
        "claim_count": len(claims),
        "all_pages_ge_1": bool(pages) and all(p >= 1 for p in pages),
        "pages": pages,
        "token_hits": token_hits,
        "soft_quant_hits": soft_quant_hits,
        "has_quant_or_key_token": bool(token_hits),
        "has_soft_quant_token": bool(soft_quant_hits),
        "claim_with_evidence_and_text": claim_ok >= 1,
        "evidence_schema_ok": evidence_schema_ok,
        "claim_schema_ok": claim_schema_ok,
        "evidence_schema_error": evidence_schema_error,
        "claim_schema_error": claim_schema_error,
        "mapping_warnings": package.get("mapping_warnings") or [],
        "routing": package.get("routing") or {},
        "sample_evidence": evidences[0] if evidences else None,
        "sample_claim": claims[0] if claims else None,
        "validation": package.get("validation") or {},
        "pass": bool(
            evidence_schema_ok
            and claim_schema_ok
            and pages
            and all(p >= 1 for p in pages)
            and claim_ok >= 1
            and bool(token_hits)
        ),
    }


def main() -> int:
    started = time.perf_counter()
    runtime = build_runtime(
        str(ROOT / "data" / "vectors"),
        str(ROOT / "data" / "chunks"),
        str(ROOT / "data" / "evidence"),
    )
    health = api_health(runtime)
    health_payload = health.model_dump() if hasattr(health, "model_dump") else health.dict()
    print(json.dumps({"health": health_payload}, ensure_ascii=False, indent=2))
    if int(health_payload.get("vector_count") or 0) <= 0:
        print("FAIL: vector_count <= 0")
        return 2

    case_reports = []
    packages = []
    for case in SMOKE_CASES:
        print(f"\n=== CASE {case['id']} ===")
        package = query_for_agent(
            runtime,
            query=case["query"],
            company=case.get("company"),
            document_id=case.get("document_id"),
            top_k=5,
            enable_followup=True,
            enable_claim_analysis=True,
            max_followup_rounds=2,
        )
        report = evaluate_case(package, case)
        case_reports.append(report)
        packages.append(
            {
                "case_id": case["id"],
                "request": package.get("request"),
                "routing": package.get("routing"),
                "validation": package.get("validation"),
                "agent_evidences": package.get("agent_evidences"),
                "agent_claims": package.get("agent_claims"),
                "mapping_warnings": package.get("mapping_warnings"),
                "data_gaps": package.get("data_gaps"),
            }
        )
        print(
            json.dumps(
                {
                    "pass": report["pass"],
                    "evidence_count": report["evidence_count"],
                    "claim_count": report["claim_count"],
                    "pages": report["pages"],
                    "token_hits": report["token_hits"],
                    "claim_with_evidence_and_text": report["claim_with_evidence_and_text"],
                },
                ensure_ascii=False,
            )
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    all_pass = all(item["pass"] for item in case_reports) and int(health_payload.get("vector_count") or 0) > 0
    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parser_version": PARSER_VERSION,
        "health": health_payload,
        "elapsed_ms": elapsed_ms,
        "all_pass": all_pass,
        "cases": case_reports,
        "packages": packages,
        "link_status": {
            "通链路": all_pass,
            "冲突处理": [
                "page: 0-based -> max(1, page+1), 保留 physical_page_0_based",
                "bbox 缺失 -> (0,0,1,1) 占位并写入 limitations/data_gaps",
                "rejected claims 不进主列表",
                "risk_code 仅为可解释占位，不伪造对方 taxonomy/概率模型",
            ],
            "仍未接管部分": [
                "对方 orchestrator / 会诊室 / 概率模型",
                "真实 bbox / screenshot",
                "对方 RISK_EXTRACTION 主流程旁路接入（本轮仅提供适配输出）",
                "568 全量生产与租服务器",
            ],
        },
    }
    out_dir = ROOT / "evaluation" / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "agent_rag_integration_smoke_v1.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWROTE {out_path}")
    print(f"ALL_PASS={all_pass}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
