# RAG Gold Validation Report

> Generated at: 2026-07-10T23:16:01.708590

## Conclusion

- Top5 exact evidence recall: 100.00%
- Top10 exact evidence recall: 100.00%
- Top5 page recall: 100.00%
- Top10 page recall: 100.00%
- Risk element extraction accuracy: 100.00%
- Risk element extraction threshold: keyword coverage >= 75%
- Average risk keyword coverage: 95.56%

Current metrics are computed dynamically from Retriever results and the manually labeled Gold set.

## Gold Set

- Gold file: `evaluation\gold\gold_risk_annotations.json`
- Cases: 9
- Company: 德合集團
- Coverage: cash_flow_pressure, customer_concentration, debt_ratio, gross_margin, license_qualification, litigation, loss, operating_cash_outflow, supplier_concentration

## Case Results

| ID | Risk type | Top5 exact | Top10 exact | Top5 page | Top10 page | Risk extraction | Keyword coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| `gold_001` | customer_concentration | True | True | True | True | True | 100.00% |
| `gold_002` | supplier_concentration | True | True | True | True | True | 100.00% |
| `gold_003` | cash_flow_pressure | True | True | True | True | True | 80.00% |
| `gold_004` | operating_cash_outflow | True | True | True | True | True | 100.00% |
| `gold_005` | litigation | True | True | True | True | True | 100.00% |
| `gold_006` | license_qualification | True | True | True | True | True | 80.00% |
| `gold_007` | loss | True | True | True | True | True | 100.00% |
| `gold_008` | gross_margin | True | True | True | True | True | 100.00% |
| `gold_009` | debt_ratio | True | True | True | True | True | 100.00% |

## Failed Top5 Exact Cases


## Interpretation

- The current Retriever meets the 85% Top5 exact evidence recall target on this gold set.
- The current rule-based risk element extraction metric is above the 80% target on this gold set.
- This extraction metric checks whether returned evidence contains the manually labeled risk element keywords; it is not a chat Agent score.