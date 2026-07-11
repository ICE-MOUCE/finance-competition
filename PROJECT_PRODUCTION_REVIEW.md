# IPO-Risk-Agent Production Readiness Review

> Review date: 2026-07-11
>
> Scope: read-only review of the executable pipeline, local artifacts, tests, and Streamlit applications. No production code was modified.

## Executive conclusion

The project has a working RAG MVP, but is **not production-ready** for parsing all pages of 568 Hong Kong IPO prospectuses. The intended full-pipeline entry point calls MinerU without page-range arguments, so its default parsing behavior is full-PDF. However, the repository also retains an executable 200-400-page, three-sample pipeline, and the stored artifacts demonstrate only limited-scale validation:

- `data/raw/` contains 568 PDFs.
- `data/processed/` contains 4 document directories; `data/precision_chunks/` contains 3 documents.
- The latest full-pipeline result processed 3 documents, not 568.
- The current vector index contains 2,448 vectors from 6 documents.
- Three documents have only 41-74 KB of Evidence JSON, consistent with the historical partial-page validation output; they must not be treated as full-prospectus artifacts.

The main blockers are end-to-end scale validation, resumable/versioned processing, batching in the actual full-pipeline path, failure isolation, and operational observability.

## Evidence examined

- `scripts/run_full_pipeline.py`
- `scripts/parse_precision_sections.py`
- `scripts/reparse_for_precision.py`
- `src/evidence/`, `src/chunk/`, `src/embedding/`, `src/vector/`
- `scripts/build_vectors.py`
- `app/app.py`, `app/rag_console.py`
- Current local data artifacts, reports, and tests

## 1. Parser and MinerU pipeline

### Findings

| Classification | Location | Finding | Production implication |
|---|---|---|---|
| MUST MODIFY | `scripts/parse_precision_sections.py:3,24-48,53-67,85-106` | An executable precision parser hardcodes three samples and pages `200-400`, passing MinerU `-s` and `-e`. | It can be run accidentally and produces incomplete source data that is indistinguishable by the downstream Evidence/Chunk interfaces. Remove it from the production execution surface, or make its experimental-only status and output isolation unambiguous. |
| MUST MODIFY | `scripts/reparse_for_precision.py:39-58,118-200` | A second executable script hardcodes the same three samples and writes separate `*_v2` data. | This preserves a sample-only workflow beside the production path and adds ambiguity over which artifacts are authoritative. Archive or explicitly isolate it from operational commands. |
| MUST MODIFY | `scripts/run_full_pipeline.py:181` | Each MinerU invocation has one fixed 600-second timeout. | Full IPO PDFs can exceed this limit. A timeout currently records failure and moves on, with no retry policy, timeout classification, or retained command diagnostics. |
| MUST MODIFY | `scripts/run_full_pipeline.py:40-47,55-78` | PDF discovery is limited to six hardcoded year-folder names. Those names currently total 568 PDFs. | It meets today's folder convention but is not robust to a new year, corrected directory name, or a different source layout. Production discovery should be data-driven and report expected versus discovered counts. |
| SUGGEST MODIFY | `scripts/run_full_pipeline.py:319-323` | `--start` and `--limit` slice the document list. | This is appropriate for controlled batches and resumption, not a page-range restriction. Record the selected document IDs in every run manifest so a partial run cannot be mistaken for a full run. |
| NO CHANGE | `scripts/run_full_pipeline.py:160-176` | The default MinerU command supplies no `-s` or `-e` page arguments. | This is the correct default for whole-PDF parsing. |
| NO CHANGE | `src/evidence/parser.py:104-134` | MinerU `content_list.json` is iterated without a page range or sample filter. | It will consume every block present in a valid full-PDF MinerU result. |

### Answer to the MinerU default question

Yes. The default production entry point, `run_full_pipeline.py`, requests the entire PDF from MinerU. The partial-page behavior exists only in `parse_precision_sections.py`; nevertheless, because that script is runnable and creates downstream-like artifacts, it is a production-readiness risk until isolated.

## 2. Evidence Builder

| Classification | Location | Finding | Production implication |
|---|---|---|---|
| MUST MODIFY | `src/evidence/builder.py:44-92,101-154` and `src/evidence/parser.py:104-134` | A full `content_list.json`, all `RawBlock` objects, and all Evidence objects are materialized in memory before saving. | There is no configured evidence cap, which is good for completeness, but no memory budget or streaming path for long prospectuses. Capacity must be measured on representative worst-case files before 568-document execution. |
| MUST MODIFY | `src/evidence/store.py:16-34` | Every accessed document is cached as an in-memory `evidence_id -> evidence` map with no cache bound or invalidation. | A long-lived Streamlit process that accesses many full prospectuses can retain all Evidence payloads indefinitely. Add bounded caching or explicit eviction, plus artifact-version invalidation. |
| SUGGEST MODIFY | `src/evidence/builder.py` document save path | Evidence artifacts have no visible input fingerprint, parser configuration fingerprint, page-count verification, or completion marker. | Existing partial artifacts are reused by `run_full_pipeline.py:357-364` as if they were complete. A manifest must distinguish complete full-PDF output from partial/failed output. |
| NO CHANGE | `src/evidence/builder.py:101-154` | The builder loops over every eligible raw block and has no fixed Evidence-number limit. | The core Evidence construction logic itself does not assume pages 200-400. |

## 3. Chunk pipeline

| Classification | Location | Finding | Production implication |
|---|---|---|
| SUGGEST MODIFY | `src/chunk/builder.py:42-144` | All Evidence for a document are separated into lists, sorted, and accumulated in memory before chunks are returned. | There is no 200-400 page assumption, but peak memory grows with the complete document. Validate the largest prospectus and define memory ceilings. |
| SUGGEST MODIFY | `src/chunk/store.py:30-42` | All chunks are serialized as one `chunks.json` file per document. | This is simple and adequate for MVP scale, but reprocessing and loading large files will become expensive. A manifest and per-document completion status are more urgent than changing the interface. |
| NO CHANGE | `src/chunk/builder.py:75-144,178-282` | Text is sorted by page; tables and images are processed across the supplied Evidence list with no page upper bound. | Chunk creation is structurally compatible with a whole PDF. |

## 4. Embedding pipeline

| Classification | Location | Finding | Production implication |
|---|---|---|
| MUST MODIFY | `scripts/run_full_pipeline.py:236-290`, especially `:273` | The actual full-pipeline route calls `engine.embed_text()` once per chunk. | Hundreds of thousands of chunks would create excessive model-call overhead and make a 568-document run impractically slow. The existing batch API is not used here. |
| MUST MODIFY | `scripts/run_full_pipeline.py:241-290` | It retains all `VectorDocument` instances for a document before adding them to FAISS. | Peak memory grows with all chunks in the document. Use bounded batches and persist/report progress at batch granularity. |
| SUGGEST MODIFY | `src/embedding/engine.py:55-75` | `embed_batch()` supports configured batching, but its batch size and device behavior are not accompanied by capacity tests, OOM handling, or retry/downsizing logic. | The primitive exists; production needs empirically selected settings and failure recovery. |
| NO CHANGE | `scripts/build_vectors.py:101-141` | The standalone vector build path already uses `embed_batch()`. | This is the correct reuse target for the full-pipeline implementation. |

## 5. Vector Store

| Classification | Location | Finding | Production implication |
|---|---|---|
| MUST MODIFY | `src/vector/store.py:26-29,139-177` | FAISS uses `IndexFlatIP` and loads the entire index plus all document metadata JSON into memory. | Exact flat search is acceptable for MVP quality work but has linear query cost and in-memory metadata growth. It has not been capacity-tested for the anticipated corpus size. |
| MUST MODIFY | `scripts/run_full_pipeline.py:406-410` plus `src/vector/store.py:60-88` | The pipeline re-embeds every reused chunk, then relies on `chunk_id` de-duplication to discard existing vectors. | Re-runs waste embedding time. More importantly, a changed chunk with the same ID cannot replace its stale vector. Incremental updates require source/artifact fingerprints and explicit upsert/rebuild semantics. |
| MUST MODIFY | `src/vector/store.py:121-135` | FAISS index replacement and `documents.json` replacement are separate operations. | A crash between them can leave index and metadata out of sync; loading has no count/integrity check. Use a transactional generation directory or validate and recover on load. |
| SUGGEST MODIFY | `scripts/build_vectors.py:49-57,73-79` | The default is a full rebuild; `--append` exists and duplicate chunk IDs are skipped. | This gives a basic append mechanism, but it lacks run manifests, deletion handling, versioned updates, and verification that all 568 expected documents are present. |
| NO CHANGE | `src/vector/store.py:64-88` | Chunk ID de-duplication prevents duplicate vectors during an append run. | This is useful baseline protection, but it is not sufficient incremental-update semantics. |

## 6. Streamlit

| Classification | Location | Finding | Production implication |
|---|---|---|
| SUGGEST MODIFY | `app/app.py:391-408`, `app/rag_console.py:65-79` | Both apps load the full vector store as a cached resource; `rag_console.py` caches a recursive scan of all PDF files. | Neither app is hardcoded to exactly three samples, and both can address a larger index. They need startup-health checks, index generation/version display, corpus coverage display, and bounded Evidence caching before production use. |
| SUGGEST MODIFY | `app/app.py:466-527`, `app/rag_console.py:82-87,301-353` | Gold evaluation is driven by small local annotation sets. | It is useful for Retriever regression checks but does not validate 568-document ingestion completeness or full-page citation correctness. |
| NO CHANGE | `app/rag_console.py:100-111,228-235` | PDF lookup scans candidates dynamically and opens source PDFs by path. | There is no three-sample UI hardcode in the current applications. |

## Test and operational gaps

### MUST MODIFY

1. Add an end-to-end acceptance run for a representative full prospectus, verifying: PDF page count equals parsed page coverage, Evidence/Chunk counts, page 0 and final page presence, citations, vectors, and restart behavior.
2. Add a 568-document run manifest that records every document ID, source checksum, source page count, parser version/configuration, stage status, attempts, elapsed time, output counts, and failure reason.
3. Add automated checks that reject partial-page artifacts from the production `data/evidence`, `data/chunks`, and vector index unless explicitly marked experimental.
4. Add capacity benchmarks for the largest PDFs and a corpus-scale estimate: wall time, CPU/GPU, peak RAM/VRAM, disk, vector count, index size, and query latency.
5. Add integrity checks between `faiss.index`, `documents.json`, chunk artifacts, and Evidence artifacts.

### SUGGEST MODIFY

1. Separate experimental data roots from production artifacts more strongly than naming conventions alone.
2. Add retries with backoff and diagnostic capture for MinerU failures; avoid one fixed timeout policy for all document sizes.
3. Add structured logs and a machine-readable dashboard/report for completion rate, page coverage, failures, and resource use.
4. Define data retention and artifact cleanup rules before full-scale parsing, since full MinerU output, images, Evidence, Chunks, and vectors can consume substantial disk.
5. Expand tests beyond Retriever/Gold unit and smoke checks. Current tests do not exercise MinerU, a complete Evidence/Chunk run, the full pipeline, 568-document discovery, or restart/update behavior.

## Current production gap

The architecture is directionally sound: default MinerU invocation is full-PDF, Evidence and Chunk logic do not impose a 200-400-page range, batch embedding already exists, and VectorStore has basic duplicate protection. The missing work is operational correctness at corpus scale.

Before claiming production readiness, the project must demonstrate one full-page end-to-end run, then a resumable and observable 568-document run with strict page-completeness and artifact-integrity gates. It also needs batched embedding in the real pipeline, reliable incremental/update semantics, bounded memory behavior, and performance evidence for the expected corpus size. The current 2,448-vector, 6-document index and 3-document full-pipeline report are useful MVP evidence, not production evidence.
