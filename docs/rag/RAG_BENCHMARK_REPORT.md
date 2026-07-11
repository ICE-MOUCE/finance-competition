# RAG Benchmark Report

> Generated: 2026-07-11T18:25:45.936698

## Scope

This benchmark evaluates retrieval grounding, not generated-answer accuracy. `gold_seed` cases have manually verified source labels; `catalog_document_label` cases verify the named local pilot document and retrieval terms but require later human section/page annotation.

## Summary

| Metric | Result |
|---|---:|
| Cases | 60 |
| Correct document hit rate | 81.67% (60 labeled) |
| Correct company hit rate | 81.67% (60 labeled) |
| Expected keyword coverage | 64.44% (60 labeled) |
| Expected section hit rate | 76.47% (17 labeled) |
| Page range hit rate | 47.06% (17 labeled) |
| Evidence completeness | 100.00% |
| Page reference rate | 100.00% |
| No-result rate | 0.00% |
| Low-confidence cases | 3 |
| Vector documents | 10992 |

## Label Coverage

- `catalog_document_label`: 43
- `gold_seed`: 17

## Failure Analysis

### Complete document misses

- `seed_fin_001` [financial_risk] doc=False keyword=0.5 section=True page=False
- `seed_fin_004` [financial_risk] doc=False keyword=1.0 section=True page=False
- `seed_bus_001` [business_risk] doc=False keyword=0.6667 section=True page=True
- `seed_bus_002` [business_risk] doc=False keyword=1.0 section=True page=True
- `seed_bus_005` [business_risk] doc=False keyword=0.6667 section=False page=False
- `cat_bus_009` [business_risk] doc=False keyword=0.3333 section=None page=None
- `cat_own_010` [ownership_risk] doc=False keyword=0.5 section=None page=None
- `cat_own_012` [ownership_risk] doc=False keyword=0.5 section=None page=None
- `seed_comp_001` [compliance_risk] doc=False keyword=0.3333 section=True page=True
- `cat_comp_006` [compliance_risk] doc=False keyword=1.0 section=None page=None
- `cat_ipo_005` [ipo_specific_risk] doc=False keyword=0.3333 section=None page=None

### Document hit but expected keyword miss

- `cat_ipo_002` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_004` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_009` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None

### Keyword hit but expected section miss

- `seed_fin_005` [financial_risk] doc=True keyword=0.6667 section=False page=False
- `seed_bus_003` [business_risk] doc=True keyword=0.3333 section=False page=False
- `seed_bus_004` [business_risk] doc=True keyword=0.3333 section=False page=False
- `seed_bus_005` [business_risk] doc=False keyword=0.6667 section=False page=False

### Missing or untrusted page references

- `seed_fin_001` [financial_risk] doc=False keyword=0.5 section=True page=False
- `seed_fin_004` [financial_risk] doc=False keyword=1.0 section=True page=False
- `seed_fin_005` [financial_risk] doc=True keyword=0.6667 section=False page=False
- `seed_fin_006` [financial_risk] doc=True keyword=0.3333 section=True page=False
- `seed_fin_009` [financial_risk] doc=True keyword=1.0 section=True page=False
- `seed_bus_003` [business_risk] doc=True keyword=0.3333 section=False page=False
- `seed_bus_004` [business_risk] doc=True keyword=0.3333 section=False page=False
- `seed_bus_005` [business_risk] doc=False keyword=0.6667 section=False page=False
- `seed_comp_002` [compliance_risk] doc=True keyword=0.6667 section=True page=False

### Table-answer cases

- `seed_fin_003` [financial_risk] doc=True keyword=1.0 section=True page=True
- `seed_fin_004` [financial_risk] doc=False keyword=1.0 section=True page=False
- `seed_fin_005` [financial_risk] doc=True keyword=0.6667 section=False page=False
- `cat_fin_011` [financial_risk] doc=True keyword=1.0 section=None page=None
- `seed_bus_001` [business_risk] doc=False keyword=0.6667 section=True page=True
- `seed_bus_002` [business_risk] doc=False keyword=1.0 section=True page=True
- `cat_bus_006` [business_risk] doc=True keyword=0.3333 section=None page=None
- `cat_own_002` [ownership_risk] doc=True keyword=0.5 section=None page=None
- `cat_own_008` [ownership_risk] doc=True keyword=1.0 section=None page=None
- `cat_ipo_001` [ipo_specific_risk] doc=True keyword=1.0 section=None page=None
- `cat_ipo_003` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_006` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_009` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_011` [ipo_specific_risk] doc=True keyword=0.6667 section=None page=None

### Low coverage in governance, compliance, or IPO-specific risk

- `cat_own_009` [ownership_risk] doc=True keyword=0.3333 section=None page=None
- `cat_own_011` [ownership_risk] doc=True keyword=0.3333 section=None page=None
- `seed_comp_001` [compliance_risk] doc=False keyword=0.3333 section=True page=True
- `cat_comp_007` [compliance_risk] doc=True keyword=0.3333 section=None page=None
- `cat_comp_012` [compliance_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_002` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_003` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_004` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_005` [ipo_specific_risk] doc=False keyword=0.3333 section=None page=None
- `cat_ipo_006` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_007` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_008` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_009` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_010` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None

## Decision Guidance

- Do not introduce Hybrid Retrieval from this v1 alone. First increase the `gold_seed` subset across companies and complete section/page labels for catalog cases.
- If the expanded gold subset shows document hits but keyword misses, test keyword filtering first. If document/keyword hits are good but ranking is poor, test reranking before BM25.
- BM25 is justified only when manually labeled failures show exact lexical terms are absent from vector TopK. Section filtering is justified only when section labels show recurring wrong-section hits.
- Do not start the 568-PDF production run or an RAG API based on this benchmark alone; use the Production Readiness Review gates and a representative full-PDF acceptance run.
- Table cases should be reviewed separately. Persistently low table coverage is evidence to improve table descriptions/chunks before changing retrieval architecture.