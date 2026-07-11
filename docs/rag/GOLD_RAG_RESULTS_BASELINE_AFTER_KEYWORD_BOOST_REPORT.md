# RAG Gold Validation Report

> Generated at: 2026-07-10T22:48:07.984020

## Conclusion

- Top5 exact evidence recall: 100.00%
- Top10 exact evidence recall: 100.00%
- Top5 page recall: 100.00%
- Top10 page recall: 100.00%
- Risk element extraction accuracy: N/A at current stage because no Risk Agent/extractor exists.

Current RAG result reflects the latest Retriever experiment recorded in docs/experiments/EXPERIMENT_LOG.md.

## Gold Set

- Gold file: `evaluation\gold\gold_risk_annotations.json`
- Cases: 9
- Company: 德合集團
- Coverage: cash_flow_pressure, customer_concentration, debt_ratio, gross_margin, license_qualification, litigation, loss, operating_cash_outflow, supplier_concentration

## Case Results

| ID | Risk type | Top5 exact | Top10 exact | Top5 page | Top10 page |
|---|---|---:|---:|---:|---:|
| `gold_001` | customer_concentration | True | True | True | True |
| `gold_002` | supplier_concentration | True | True | True | True |
| `gold_003` | cash_flow_pressure | True | True | True | True |
| `gold_004` | operating_cash_outflow | True | True | True | True |
| `gold_005` | litigation | True | True | True | True |
| `gold_006` | license_qualification | True | True | True | True |
| `gold_007` | loss | True | True | True | True |
| `gold_008` | gross_margin | True | True | True | True |
| `gold_009` | debt_ratio | True | True | True | True |

## Failed Top5 Exact Cases


## Interpretation

- The current Retriever meets the 85% Top5 exact evidence recall target on this gold set.
- Remaining failures should be reviewed before expanding the gold set, but no further experiment is run because the stop condition is met.
- The extraction accuracy metric should be evaluated only after a risk extraction module exists.