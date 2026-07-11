# IPO-Risk-Agent Corpus Capacity Plan

> Planning date: 2026-07-11
>
> Scope: planning only. No source code, pipeline configuration, or data artifact was changed.

## Executive recommendation

Plan the first production corpus build for **about 2.3 million Evidence records, 0.47 million Chunks, and 0.33-0.47 million vectors**, with **150 GB of free working disk as the minimum and 250 GB recommended**. Run sequentially by year and in small document batches, with a manifest as the source of truth for resumption. Do not start a 568-document run until the Production Readiness Review blockers are addressed, particularly page-completeness validation, batch embedding in the real pipeline, and reliable resumability.

The estimates below are intentionally ranges. Current data mixes complete-document artifacts with historical 200-400 page samples, so a single exact extrapolation would be misleading.

## 1. Baseline and estimation method

### Measured local facts

| Item | Measured value | Source |
|---|---:|---|
| Raw PDFs | 568 | `data/raw/` scan |
| Raw PDF capacity | 7.24 GiB | `data/raw/` scan |
| Average raw PDF size | 13.06 MiB | `data/raw/` scan |
| Latest full-pipeline run | 3 PDFs, 12,129 Evidence, 2,481 Chunks, 1,761 newly added vectors | `data/pipeline_results.json` |
| Existing vector index | 2,448 vectors, 512 dimensions, 4.78 MiB FAISS | `data/pipeline_results.json` |
| Current FAISS storage | about 2,049 bytes/vector | 4.78 MiB / 2,448 vectors; close to 512 x float32 plus index overhead |
| Current vector metadata storage | must be treated as variable | `documents.json` includes text preview and Evidence IDs, so its size depends on chunk length and Evidence fan-out |
| Parser throughput used for planning | CPU about 5 pages/s; GPU about 20 pages/s | existing MinerU validation report; this is not yet a corpus benchmark |
| Embedding configuration | BGE-small-zh-v1.5, 512 dimensions, batch size 32, default CPU | `src/embedding/config.py` |

### Why three scenarios are used

The stored complete-document run reports an average of 4,043 Evidence and 827 Chunks per document. The repository also contains deliberately partial 200-400 page outputs, which are much smaller and must not be included in a whole-corpus average. No authoritative page-count manifest for all 568 PDFs exists yet.

Use these planning scenarios until a representative full-PDF benchmark produces actual page counts:

| Scenario | Average pages/PDF | Corpus pages | Evidence/page | Chunk/page | Rationale |
|---|---:|---:|---:|---:|---|
| Low | 350 | 198,800 | 7 | 1.3 | Shorter prospectuses and lower layout density |
| Planning baseline | 500 | 284,000 | 8 | 1.65 | Near the observed complete-run density, rounded conservatively |
| High | 650 | 369,200 | 9 | 2.0 | Long reports, annexes, dense tables, and image-heavy pages |

Formulas:

```text
corpus_pages = 568 x average_pages_per_pdf
evidence = corpus_pages x evidence_per_page
chunks = corpus_pages x chunks_per_page
vectors = chunks x vectorization_rate
```

For vectors, use a 70%-100% range. The current full pipeline skipped chunks with no embedding text, while the standalone builder converts almost every text/table chunk and can include image chunks. The final vector count depends on the production policy for images and empty table descriptions.

## 2. Expected Evidence, Chunk, and vector counts

| Scenario | Evidence | Chunks | Vectors at 70% | Vectors at 100% |
|---|---:|---:|---:|---:|
| Low | 1.39 million | 258,440 | 181,000 | 258,000 |
| Planning baseline | 2.27 million | 468,600 | 328,000 | 469,000 |
| High | 3.32 million | 738,400 | 517,000 | 738,000 |

**Capacity reservation:** size FAISS and metadata for 0.75 million vectors, even though the planning baseline is approximately 0.47 million. This protects against long-document and table/image density variance.

## 3. MinerU parsing time

`run_full_pipeline.py` invokes MinerU once per PDF with no `-s` or `-e` arguments, so the planning model assumes complete PDFs. It currently applies a 600-second timeout per file; that timeout is a known production blocker and is not a realistic upper bound for the schedule.

### Pure parser compute estimate

| Scenario | Pages | CPU at 5 pages/s | GPU at 20 pages/s |
|---|---:|---:|---:|
| Low | 198,800 | 11.0 h | 2.8 h |
| Planning baseline | 284,000 | 15.8 h | 3.9 h |
| High | 369,200 | 20.5 h | 5.1 h |

### Operational schedule estimate

Allow additional time for model loading, PDF/image I/O, retries, slow documents, JSON serialization, and checkpointing:

| Execution mode | Planning baseline elapsed time | Recommended reservation |
|---|---:|---:|
| CPU, sequential | 24-32 h | 2 calendar days |
| GPU, one worker | 6-10 h | 1 calendar day |
| GPU, two independent workers with separate output roots | 3-6 h | only after isolated-batch validation |

The CPU/GPU figures are extrapolations from a prior validation report, not measured end-to-end results on the 568-PDF corpus. A 10-document pilot containing short, median, and longest PDFs must replace these assumptions before committing a final schedule.

## 4. Batch embedding time

The desired production mode is batch embedding, because `EmbeddingEngine.embed_batch()` accepts batch size 32. The current `run_full_pipeline.py` incorrectly uses `embed_text()` per chunk; the estimates below apply only after the actual run path uses batching.

The local standalone builder embedded 649 vectors in 10.36 seconds on CPU, approximately 63 vectors/s on one observed document. That result includes small-run effects and should not be used as an optimistic corpus guarantee.

| Scenario | Vectors | CPU planning rate 50-80 vectors/s | GPU planning rate 800-2,000 vectors/s |
|---|---:|---:|---:|
| Low | 181k-258k | 0.6-1.4 h | 2-6 min raw compute |
| Planning baseline | 328k-469k | 1.1-2.6 h | 3-10 min raw compute |
| High | 517k-738k | 1.8-4.1 h | 5-16 min raw compute |

Reserve **4-8 hours on CPU** and **1-2 hours on GPU** for the baseline stage when including chunk-file reads, Python object creation, FAISS insertion, JSON writing, and validation. GPU embedding is not expected to be the end-to-end bottleneck; MinerU and artifact I/O dominate.

## 5. Artifact size and disk planning

### VectorStore sizing

FAISS `IndexFlatIP` stores 512 float32 values per vector:

```text
512 x 4 bytes = 2,048 bytes/vector
```

| Scenario | Vector count | FAISS index | `documents.json` | Vector store total |
|---|---:|---:|---:|---:|
| Low | 181k-258k | 0.35-0.50 GiB | 0.4-1.0 GiB | 0.8-1.5 GiB |
| Planning baseline | 328k-469k | 0.63-0.90 GiB | 0.7-1.8 GiB | 1.4-2.8 GiB |
| High | 517k-738k | 0.99-1.41 GiB | 1.1-2.9 GiB | 2.1-4.4 GiB |

`documents.json` is a larger uncertainty than FAISS because the current schema stores up to 500 characters of text preview and a list of Evidence IDs for every vector. The table uses roughly 2-4 KiB/vector for planning; measure it after the 10-document pilot.

### Evidence and Chunk artifacts

The current complete Evidence files are approximately 4-6 MiB per prospectus, and complete Chunk files approximately 1.7-3.6 MiB per prospectus. Those figures include verbose JSON formatting and are more useful than partial sample files.

| Artifact | Low | Planning baseline | High | Planning assumption |
|---|---:|---:|---:|---|
| Evidence JSON | 2.3 GiB | 3.5 GiB | 5.3 GiB | 1.0 / 1.6 / 2.4 MiB per 100k Evidence, plus metadata; reserve more for tables/images |
| Chunk JSON and indexes | 1.2 GiB | 2.0 GiB | 3.2 GiB | 2.5-4.5 KiB/chunk including Evidence IDs and text/table payload |

The Evidence numbers are conservative planning allocations. The actual current per-document full Evidence artifacts imply a baseline nearer 2.5-3.5 GiB if all documents resemble the observed large reports; table-rich documents may be higher.

### MinerU output and total disk

MinerU preserves multiple intermediate representations, annotated PDFs, Markdown, JSON, and extracted images. Current local `data/processed/` output is 278 MiB for four document directories, while `data/precision_chunks/` is 208 MiB for three partial-page documents. These are insufficiently clean to derive one exact multiplier, so reserve a wide range.

| Area | Low | Planning baseline | High | Notes |
|---|---:|---:|---:|---|
| Raw PDFs | 7.24 GiB | 7.24 GiB | 7.24 GiB | already present |
| MinerU outputs | 35 GiB | 60 GiB | 100 GiB | includes original/layout/span PDFs, JSON, Markdown, images |
| Evidence | 2.3 GiB | 3.5 GiB | 5.3 GiB | JSON output |
| Chunks | 1.2 GiB | 2.0 GiB | 3.2 GiB | JSON plus per-document indexes |
| VectorStore | 0.8 GiB | 2.0 GiB | 4.4 GiB | FAISS plus metadata/report files |
| Logs, manifests, temporary files | 5 GiB | 10 GiB | 20 GiB | includes save-time duplicate files and diagnostics |
| **Total retained corpus** | **52 GiB** | **85 GiB** | **140 GiB** | includes raw PDFs |
| **Free working space required** | **100 GiB** | **150 GiB** | **250 GiB** | accommodates temporary writes, retries, and safety margin |

Do not plan from the 7.24 GiB raw-PDF size alone. MinerU annotated PDFs and extracted images are the dominant storage uncertainty.

## 6. RAM and VRAM requirements

### Build host

| Resource | Minimum | Recommended | Reason |
|---|---:|---:|---|
| System RAM, CPU-only | 32 GiB | 64 GiB | MinerU, full per-document Evidence/Chunk materialization, JSON serialization, FAISS and OS file cache |
| System RAM, GPU build | 32 GiB | 64 GiB | GPU reduces parser/embedding compute, not Python/JSON artifact memory |
| GPU VRAM for MinerU + embedding | 12 GiB | 16-24 GiB | permits practical MinerU operation and conservative embedding batches; validate on the selected model/GPU |
| Embedding-only GPU VRAM | 6 GiB | 8 GiB | BGE-small with batch 32 is modest; this does not cover MinerU concurrently |
| Persistent Streamlit/retrieval RAM | 8 GiB | 16 GiB | FAISS index, `documents.json` objects, bounded Evidence cache, model, application |

Do not run MinerU and GPU embedding concurrently on one GPU until measured VRAM headroom is known. The safest first build uses one stage at a time: parse/Evidence/Chunk, then batch embed/index.

## 7. Primary bottlenecks

1. **MinerU full-PDF parsing and artifact I/O**: it has the largest wall-clock time and produces the largest uncertain disk footprint.
2. **Current full-pipeline single-item embedding**: `run_full_pipeline.py` calls `embed_text()` once per chunk. At 0.3-0.7 million chunks this is unacceptable; it must be replaced by the existing batch path before production.
3. **Artifact completeness and restart correctness**: current reuse checks only detect file existence. They cannot distinguish full-page, partial-page, stale, or interrupted artifacts.
4. **FAISS flat-index query growth**: `IndexFlatIP` is likely still feasible at the planning baseline, but query cost grows linearly and must be benchmarked at the final vector count.
5. **Unbounded Evidence cache in Streamlit**: not a batch-build blocker, but it can turn corpus-wide interactive use into a RAM leak.

## 8. Recommended full-corpus execution strategy

### Partitioning

Use **year as the top-level batch boundary**, then process documents sequentially within each year:

| Batch | PDFs |
|---|---:|
| 2020 | 138 |
| 2021 | 88 |
| 2022 | 87 |
| 2023 | 63 |
| 2024 | 73 |
| 2025 | 116 |

Within a year, use batches of **10 PDFs for the first pilot**, then **25 PDFs** after the acceptance checks pass. One process should own one output root at a time. Do not have multiple processes write to the same `data/vectors/`, Evidence, Chunk, or MinerU output directories.

### Stage separation

Recommended sequence:

1. Pilot: 10 full PDFs spanning short, median, long, and table-heavy documents.
2. Parse one year to MinerU + Evidence + Chunk artifacts; verify page coverage and completion manifest.
3. Build vectors from completed Chunk artifacts in batch mode into a new index generation.
4. Run integrity, retrieval, and sample citation checks.
5. Promote that year only after checks pass; continue to the next year.

This strategy isolates failures, avoids redoing expensive parsing when indexing changes, and lets capacity forecasts be corrected after the first year.

## 9. Required checkpoint and resume design

This is a design target, not implemented by the current scripts.

### Per-document manifest record

Each document needs one durable record containing:

```json
{
  "document_id": "2021_01024_company",
  "source_path": "data/raw/...pdf",
  "source_sha256": "...",
  "source_page_count": 0,
  "parser_version": "MinerU version",
  "parser_config": {"full_pdf": true},
  "stages": {
    "mineru": {"status": "complete", "page_min": 0, "page_max": 0, "output_hash": "..."},
    "evidence": {"status": "complete", "count": 0, "output_hash": "..."},
    "chunk": {"status": "complete", "count": 0, "output_hash": "..."},
    "embedding": {"status": "complete", "vector_count": 0, "index_generation": "..."}
  },
  "attempts": 1,
  "last_error": null,
  "updated_at": "ISO-8601"
}
```

### Resume rules

- Resume only a stage whose prior stage has matching source/configuration fingerprints and passed page-completeness checks.
- Treat a file merely existing as **not complete** unless its manifest says complete and counts/hashes match.
- On failure, preserve MinerU stderr/stdout, elapsed time, host resource snapshot, and failing page/document context.
- Write index output to a new generation directory. Promote it only after `faiss.index` count equals `documents.json` count and all completed document vector counts reconcile.
- Never append concurrently. Use one writer per index generation.
- Keep a failed-document queue and re-run it after the year batch, not immediately in an unbounded retry loop.

## 10. Recommended formal-run commands

These are target operational commands **after** the required production changes are implemented. They are not a claim that the current scripts provide full checkpoint safety.

```powershell
# Preflight: run a 10-document representative full-PDF pilot and inspect its manifest.
python scripts/run_full_pipeline.py --start 0 --limit 10 --rebuild-vectors

# Production phase 1: process a controlled document batch after page-completeness checks pass.
python scripts/run_full_pipeline.py --start 0 --limit 25 --skip-mineru

# Production phase 2: rebuild a versioned index from completed Chunk artifacts using batch embedding.
python scripts/build_vectors.py --chunk-dir data/chunks --vector-dir data/vectors_generation_YYYY --text-only
```

For the current codebase, `--start`/`--limit` operate on the combined scan order, not an explicit year parameter. Do not use the commands above unattended across 568 documents until manifests, page coverage gates, batched embedding in the full path, and transactional index generations exist.

## Exit criteria for a capacity-approved corpus run

1. Ten-document pilot has measured page counts, Evidence/Chunk/vector densities, disk multiplier, CPU/GPU time, and peak RAM/VRAM.
2. Every completed document proves page 0 through final PDF page coverage, or records an intentional documented exception.
3. Every corpus stage has a resumable manifest and deterministic output fingerprint.
4. A full-year run stays within the allocated RAM, VRAM, disk, and time budget.
5. The final index passes vector/document-count reconciliation and representative retrieval/citation checks.
