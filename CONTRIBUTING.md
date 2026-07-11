# Contributing

Keep changes small and easy to verify.

## Development Rules

- Do not change Retriever, Evidence, Embedding, or VectorStore behavior during cleanup-only work.
- Keep generated data out of Git.
- Put design and reports under `docs/`.
- Put reusable source code under `src/`.
- Put Streamlit demos and consoles under `app/`.
- Put smoke tests under `tests/`.

## Checks

Run the smallest relevant checks before handing off:

```powershell
python tests/test_gold_report_summary.py
python -c "from src.retriever import LayeredRetriever; from src.evidence import EvidenceStore; from src.vector import VectorStore"
```

Run full Retriever checks only when local model and vector data are available.

