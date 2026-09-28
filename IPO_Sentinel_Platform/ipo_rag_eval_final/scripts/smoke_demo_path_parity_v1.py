"""Smoke: default vs hge path for 3 Human4 cases (document constrained, top_k parity)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.evidence import EvidenceStore
from src.retriever import LayeredRetriever, build_retriever_config
from src.vector import VectorStore
from src.api.schemas import SearchRequest
from src.api.service import RuntimeBundle, search as api_search


TARGET_IDS = [
    "manual_new_董飞飞_cat_own_010",
    "manual_new_董飞飞_seed_bus_001",
    "manual_new_田歌_cat_fin_010",
]


def load_demo():
    spec = importlib.util.spec_from_file_location("demo_app_smoke", ROOT / "app" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def build_runtime() -> RuntimeBundle:
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(ROOT / "data" / "vectors"), dimension=engine.dimension)
    retriever = LayeredRetriever(store, engine, build_retriever_config(profile="default"))
    evidence_store = EvidenceStore(str(ROOT / "data" / "evidence"))
    stats = store.get_stats() if hasattr(store, "get_stats") else {}
    docs = getattr(store, "documents", None) or []
    return RuntimeBundle(
        embedding_engine=engine,
        vector_store=store,
        retriever=retriever,
        evidence_store=evidence_store,
        version="thin-rag-api-v1",
        model_loaded=True,
        vector_count=int(stats.get("total_vectors") or len(docs)),
    )


def run_one(demo, runtime: RuntimeBundle, case: dict, profile: str, selected_top_k: int = 5) -> dict:
    effective = demo.effective_demo_top_k(profile, selected_top_k)
    req = SearchRequest(
        query=case["question"],
        top_k=effective,
        document_id=case.get("document_id"),
        company=case.get("company"),
        enable_claim_analysis=False,
        enable_followup=False,
        ranking_profile=profile,
    )
    resp = api_search(runtime, req)
    payload = resp.model_dump() if hasattr(resp, "model_dump") else resp.dict()
    items = list(payload.get("results") or [])[:effective]
    flags = demo.topn_gold_aligned_flags(case, items, n=3)
    top = items[0] if items else {}
    page_status = demo.page_overlap_status(top, case) if top else "n/a"
    return {
        "id": case.get("id"),
        "profile": payload.get("ranking_profile") or profile,
        "selected_top_k": selected_top_k,
        "effective_top_k": effective,
        "document_id": case.get("document_id"),
        "document_constrained": bool(case.get("document_id")),
        "n_results": len(items),
        "top1_gold_aligned": flags["top1"],
        "top3_gold_aligned": flags["top3"],
        "top1_hit_keywords": demo.hit_keywords_for_result(top, case),
        "top1_page_status": page_status,
        "top1_interpretation": demo.content_page_interpretation(flags["top1"], page_status),
        "top1_preview": str(top.get("preview") or top.get("text") or "")[:180],
        "top1_pages": top.get("pages"),
    }


def main() -> None:
    demo = load_demo()
    raw_cases = json.loads((ROOT / "evaluation" / "benchmark" / "manual_human4_v1.json").read_text(encoding="utf-8"))
    cases = [demo.normalize_manual_case(c) for c in raw_cases]
    by_id = {c["id"]: c for c in cases}
    runtime = build_runtime()
    rows = []
    for cid in TARGET_IDS:
        case = by_id[cid]
        default_row = run_one(demo, runtime, case, "default", selected_top_k=5)
        hge_row = run_one(demo, runtime, case, "hge", selected_top_k=5)
        rows.append({"id": cid, "default": default_row, "hge": hge_row})
        print("====", cid)
        print(
            " default",
            default_row["profile"],
            "k",
            default_row["effective_top_k"],
            "top1/top3",
            default_row["top1_gold_aligned"],
            default_row["top3_gold_aligned"],
        )
        print("  preview", default_row["top1_preview"][:100])
        print(
            " hge    ",
            hge_row["profile"],
            "k",
            hge_row["effective_top_k"],
            "top1/top3",
            hge_row["top1_gold_aligned"],
            hge_row["top3_gold_aligned"],
        )
        print("  preview", hge_row["top1_preview"][:100])
        print(
            "  hits",
            hge_row["top1_hit_keywords"],
            "page",
            hge_row["top1_page_status"],
            hge_row["top1_interpretation"],
        )
        assert case.get("document_id"), f"missing document_id after normalize: {cid}"
        assert hge_row["profile"] == "hge"
        assert hge_row["effective_top_k"] == 10
        assert hge_row["document_constrained"] is True
        assert default_row["effective_top_k"] == 5
        # HGE should be at least as good on Top3 content alignment for these demo anchors.
        assert hge_row["top3_gold_aligned"] is True

    out = {
        "task": "demo_path_parity_v1_smoke",
        "note": "selected_top_k=5 on purpose; hge must floor to 10 and return profile=hge",
        "rows": rows,
    }
    out_path = ROOT / "evaluation" / "benchmark" / "demo_path_parity_v1_smoke.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out_path)


if __name__ == "__main__":
    main()
