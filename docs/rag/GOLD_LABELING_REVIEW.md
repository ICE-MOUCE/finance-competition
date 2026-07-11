# Gold Labeling Review

This document explains the current Gold labels in plain language and defines the stricter alternative set used for robustness checks.

## How To Read Gold Evaluation

`Gold` means manually labeled evidence. Each case asks whether the Retriever returns the exact evidence paragraph that a human marked as supporting the risk.

`Top5 Recall` means: among all Gold questions, how many have the expected evidence ID inside the first 5 returned chunks.

`Top10 Recall` means the same check inside the first 10 returned chunks.

The score is not answer quality. It only checks whether the Retriever can find the right source paragraph. Risk extraction accuracy should be measured later after a Risk Agent or extractor exists.

## Strict Labeling Rules

Use a paragraph as Gold evidence only when it passes all checks:

- It states the risk fact, not just a generic topic.
- It contains the risk consequence or a direct risk heading.
- It belongs to the target company and document.
- It has a stable `evidence_id` and page number.
- It is not selected merely because the current Retriever already finds it.

Do not count a paragraph when:

- It is only a table of contents or cross-reference.
- It mentions the same keyword but not the risk.
- It is a broad summary and a more precise risk paragraph exists.
- It supports a different risk than the label.

## Original Baseline Set

File: `evaluation/gold/gold_risk_annotations.json`

This set has 9 cases. It focuses on the first validation target and covers core IPO risk elements.

| ID | Label | Why It Counts | Common Mistake |
|---|---|---|---|
| `gold_001` | `customer_concentration` | The evidence gives largest-customer and five-largest-customer revenue proportions. | Do not mark any paragraph mentioning customers; it must show concentration or risk. |
| `gold_002` | `supplier_concentration` | The evidence gives largest-supplier and five-largest-supplier purchase proportions. | Supplier names alone are insufficient. |
| `gold_003` | `cash_flow_pressure` | The evidence explains early project cash outflow and customer payment timing pressure. | General cash balance text is not enough. |
| `gold_004` | `operating_cash_outflow` | The evidence states operating cash outflow of about HK$58.3 million. | Do not replace it with generic liquidity risk. |
| `gold_005` | `litigation` | The evidence describes ongoing litigation and the dispute background. | A legal section heading alone is not evidence. |
| `gold_006` | `license_qualification` | The evidence says the business requires qualifications and registration. | Ordinary compliance boilerplate is too broad. |
| `gold_007` | `loss` | The evidence describes increased net loss for the recent four-month period. | Revenue decrease alone is not the same as loss. |
| `gold_008` | `gross_margin` | The evidence gives gross profit/gross margin information for profitability quality. | A revenue table without margin is not enough. |
| `gold_009` | `debt_ratio` | The evidence defines gearing ratio and debt components. | Bank borrowing alone is narrower than the label. |

Why the baseline often shows `88.89%`: it has 9 cases, and only `gold_001` misses in Top5. `8 / 9 = 88.89%`.

## Strict Robustness v2 Set

File: `evaluation/gold/gold_risk_annotations_strict_v2.json`

This set deliberately uses different labels from the baseline. It tests whether the Retriever can handle finer risk categories instead of only the first 9 examples.

| ID | Label | Expected Evidence | Why It Counts |
|---|---|---|---|
| `strict_001` | `revenue_non_recurring_projects` | `ev_2020_00368_德合集團_p17_txt010` | It links project-count decline to the non-recurring nature of projects and names the risk factor. |
| `strict_002` | `performance_bond_liquidity` | `ev_2020_00368_德合集團_p44_txt004` | It states pledged cash deposits for performance bonds may harm liquidity. |
| `strict_003` | `covid_project_award_and_receivable` | `ev_2020_00368_德合集團_p44_txt006` | It connects COVID-19 to fewer/delayed projects, customer payment risk, impairment losses, and financial impact. |
| `strict_004` | `covid_site_interruption` | `ev_2020_00368_德合集團_p44_txt007` | It explains site suspension, labor shortage, delay, compensation, and adverse business impact. |
| `strict_005` | `supplier_subcontractor_disruption` | `ev_2020_00368_德合集團_p45_txt002` | It covers supplier/subcontractor inability to provide materials, labor, products, or services. |
| `strict_006` | `variation_order_margin_volatility` | `ev_2020_00368_德合集團_p45_txt005` | It directly says variation-order volume/timing may cause revenue and gross margin decline. |
| `strict_007` | `variation_order_cost_recovery` | `ev_2020_00368_德合集團_p46_txt003` | It cites a completed project loss caused by unrecovered variation-order costs. |
| `strict_008` | `contract_asset_recoverability` | `ev_2020_00368_德合集團_p47_txt004` | It states contract assets may not be billed or fully recovered on schedule. |
| `strict_009` | `cost_estimation_overrun` | `ev_2020_00368_德合集團_p47_txt009` | It describes actual time/cost exceeding estimates and lists causes. |
| `strict_010` | `subcontractor_performance` | `ev_2020_00368_德合集團_p49_txt003` | It states subcontractor non-performance, substandard work, and delay risks. |
| `strict_011` | `supplier_material_defect` | `ev_2020_00368_德合集團_p49_txt007` | It states shortages, delivery delay, and defective materials may prevent timely project completion. |
| `strict_012` | `insurance_coverage_gap` | `ev_2020_00368_德合集團_p53_txt002` | It states current insurance may not cover all potential risks and losses. |

## Why This Is Stricter

The v2 set avoids broad summary paragraphs when a precise risk-factor paragraph exists. For example, `ev_2020_00368_德合集團_p22_txt013` lists many risks in the summary, but it is not used as expected evidence because it is too broad.

The v2 set also separates similar-looking risks:

- `variation_order_margin_volatility` is about margin/revenue volatility.
- `variation_order_cost_recovery` is about failing to recover costs and recording losses.
- `covid_project_award_and_receivable` is about project awards and receivables.
- `covid_site_interruption` is about site shutdown and operational interruption.
- `supplier_subcontractor_disruption` is about supply/service interruption.

These distinctions make the test harder and more useful for robustness.

## Frontend Use

```powershell
streamlit run app/rag_console.py
```

Use `Original baseline (9)` to reproduce the old 88.89% result.

Use `Strict robustness v2 (12)` to check whether the system still finds evidence for different risk labels.

## Current Validation Results

Run date: 2026-07-10

| Gold Set | Cases | Top5 Exact Evidence Recall | Top10 Exact Evidence Recall | Interpretation |
|---|---:|---:|---:|---|
| Original baseline | 9 | 88.89% | 100.00% | Passes the 85% Top5 evidence recall target on the original set. |
| Strict robustness v2 | 12 | 75.00% | 75.00% | Does not pass the 85% target under stricter, more fine-grained labels. |

Strict v2 failed cases:

- `strict_003` `covid_project_award_and_receivable`: expected `ev_2020_00368_德合集團_p44_txt006`
- `strict_009` `cost_estimation_overrun`: expected `ev_2020_00368_德合集團_p47_txt009`
- `strict_011` `supplier_material_defect`: expected `ev_2020_00368_德合集團_p49_txt007`

Conclusion: the current Retriever is good enough for the original baseline demonstration, but the stricter robustness check exposes remaining retrieval gaps. Do not change Gold labels to improve the score; improve Retriever behavior only after reviewing the failed cases.

## Frontend Entry

For the main demo page:

```powershell
streamlit run app.py
```

In the `Gold 评测` section, choose:

- `原始Gold样本（9条）` to reproduce the 88.89% baseline result.
- `严格鲁棒性样本v2（12条）` to run the stricter robustness result.
