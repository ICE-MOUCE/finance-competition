# RAG Gold Validation Report

> Generated at: 2026-07-10T22:22:16.205993

## Conclusion

- Top5 exact evidence recall: 75.00%
- Top10 exact evidence recall: 75.00%
- Top5 page recall: 75.00%
- Top10 page recall: 75.00%
- Risk element extraction accuracy: N/A at current stage because no Risk Agent/extractor exists.

Current RAG result reflects the latest Retriever experiment recorded in docs/experiments/EXPERIMENT_LOG.md.

## Gold Set

- Gold file: `evaluation\gold\gold_risk_annotations_strict_v2.json`
- Cases: 12
- Company: 德合集團
- Coverage: contract_asset_recoverability, cost_estimation_overrun, covid_project_award_and_receivable, covid_site_interruption, insurance_coverage_gap, performance_bond_liquidity, revenue_non_recurring_projects, subcontractor_performance, supplier_material_defect, supplier_subcontractor_disruption, variation_order_cost_recovery, variation_order_margin_volatility

## Case Results

| ID | Risk type | Top5 exact | Top10 exact | Top5 page | Top10 page |
|---|---|---:|---:|---:|---:|
| `strict_001` | revenue_non_recurring_projects | True | True | True | True |
| `strict_002` | performance_bond_liquidity | True | True | True | True |
| `strict_003` | covid_project_award_and_receivable | False | False | False | False |
| `strict_004` | covid_site_interruption | True | True | True | True |
| `strict_005` | supplier_subcontractor_disruption | True | True | True | True |
| `strict_006` | variation_order_margin_volatility | True | True | True | True |
| `strict_007` | variation_order_cost_recovery | True | True | True | True |
| `strict_008` | contract_asset_recoverability | True | True | True | True |
| `strict_009` | cost_estimation_overrun | False | False | False | False |
| `strict_010` | subcontractor_performance | True | True | True | True |
| `strict_011` | supplier_material_defect | False | False | False | False |
| `strict_012` | insurance_coverage_gap | True | True | True | True |

## Failed Top5 Exact Cases

- `strict_003` covid_project_award_and_receivable: expected ['ev_2020_00368_德合集團_p44_txt006']
- `strict_009` cost_estimation_overrun: expected ['ev_2020_00368_德合集團_p47_txt009']
- `strict_011` supplier_material_defect: expected ['ev_2020_00368_德合集團_p49_txt007']

## Interpretation

- The current Retriever can often find the right page or nearby chunk, but Top5 exact Evidence ID recall is not stable enough for the competition threshold.
- A document/company filter is needed; without it, same-risk evidence from other prospectuses can outrank the target document.
- The extraction accuracy metric should be evaluated only after a risk extraction module exists.