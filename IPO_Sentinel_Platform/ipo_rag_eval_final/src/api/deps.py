"""Runtime dependency wiring for Thin RAG API V1."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from src.api.service import RuntimeBundle, build_runtime

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def get_runtime() -> RuntimeBundle:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    vector_dir = os.environ.get("IPO_VECTOR_DIR", str(ROOT / "data" / "vectors"))
    chunk_dir = os.environ.get("IPO_CHUNK_DIR", str(ROOT / "data" / "chunks"))
    evidence_dir = os.environ.get("IPO_EVIDENCE_DIR", str(ROOT / "data" / "evidence"))
    return build_runtime(
        vector_dir=vector_dir,
        chunk_dir=chunk_dir,
        evidence_dir=evidence_dir,
    )


def clear_runtime_cache() -> None:
    get_runtime.cache_clear()
