# Replacement-agent prompt observations

Started: 2026-11-20T12:56:39.701494+00:00. Data backend: **bigquery**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T12:56:39.701494+00:00",
  "backend": "bigquery",
  "user": "alice",
  "scope": "Calvin Klein",
  "settings": {
    "gemini_model": "gemini-3.8-flash",
    "thinking_level": "low",
    "review_thinking_level": "medium",
    "backend": "bigquery",
    "golden_bootstrap": true,
    "turn_timeout_seconds": 120.0,
    "question_budget_usd": 1.0,
    "max_model_calls": 12,
    "max_tool_calls": 24,
    "max_queries": 8,
    "max_query_bytes": 100000000,
    "max_output_tokens": 4096,
    "review_output_tokens": 2048,
    "max_answer_reviews": 3,
    "max_context_bytes": 150000,
    "max_review_bytes": 60000,
    "review_reserve_seconds": 30.0,
    "input_usd_per_million": 2.0,
    "output_usd_per_million": 12.0,
    "bigquery_usd_per_tib": 6.25,
    "model_min_interval_seconds": 0.0
  },
  "packages": {
    "google-adk": "2.12.0",
    "google-genai": "2.32.0",
    "sqlglot": "30.24.0",
    "duckdb": "2.0.0"
  },
  "fixture_sha256": null,
  "independent_fixture_oracle_active": false,
  "golden_corpus_sha256": "c376f96dadf11329e0a71ac58ed3966661165e24d8fed2ca0b5075b5dd7c5720",
  "evaluation_type": "real-model smoke observations; manual quality review pending",
  "selected_cases": [
    "ranking_followup"
  ],
  "maximum_turns": 2,
  "storage": "TemporaryDirectory per run; no user library reads/imports/mutations",
  "finished_at": "2026-11-20T12:57:19.034380+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| ranking_followup / 1 | approved | 20.629 | 4 | 1 | approve |
| ranking_followup / 2 | approved | 18.692 | 3 | 0 | approve |

## ranking_followup

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026. Use two compact tables.

Observed tool calls: describe_data → query_data.

Runtime status: `approved`. Elapsed: 20.629 seconds.

**Full published answer**

The tables below show Calvin Klein's top five products by qualifying revenue and by distinct purchasing customers for Q1 2026 (2026-01-01 to 2026-03-31 UTC). Qualifying sales exclude cancelled and returned items. Ties are ordered deterministically by product ID.

### Top 5 Products by Revenue (Q1 2026)

| Rank | Product Name | Revenue | Distinct Customers |
| :---: | :--- | :---: | :---: |
| 1 | Calvin Klein Mens 2 Button Solid Black Wool Suit | 259.99 | 1 |
| 2 | Calvin Klein Mens Navy Blue Pindot Slim Fit Wool Suit | 259.99 | 1 |
| 3 | Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater | 236.00 | 2 |
| 4 | Calvin Klein Sportswear Men's Melton Wool Basic Peacoat | 228.00 | 1 |
| 5 | Calvin Klein Men's Wool Car Coat With Bib | 216.00 | 2 |

### Top 5 Products by Distinct Customers (Q1 2026)

| Rank | Product Name | Distinct Customers | Revenue |
| :---: | :--- | :---: | :---: |
| 1 | Calvin Klein Women's 2 Pocket Collar Blouse | 3 | 208.50 |
| 2 | Calvin Klein Women's Solid Skirtini | 3 | 162.00 |
| 3 | Calvin Klein Women's MSY Crew Neck Roll Sleeve | 2 | 139.00 |
| 4 | Calvin Klein Three Quarter Sleeve Dress | 2 | 133.20 |
| 5 | Calvin Klein Women's Naked Glamour Bikini | 2 | 40.00 |

*(Note: In the warehouse dataset, currency units are not specified.)*

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [ranking_followup-1.json](ranking_followup-1.json).

### Turn 2

**Prompt**

Which products appear in both rankings? Explain what this suggests about revenue versus customer reach in one short paragraph, without a table.

Observed tool calls: read_result.

Runtime status: `approved`. Elapsed: 18.692 seconds.

**Full published answer**

None of the products appear in both rankings: the top five revenue generators and top five products by customer count share zero overlap [E1]. This separation illustrates that in Q1 2026, top-line revenue and customer reach were driven by different dynamics: highest-revenue items generated between 216.00 and 259.99 from only 1 to 2 customers each (high revenue per customer, ranging from 108.00 to 259.99), whereas the widest-reach items attracted 2 to 3 customers each but yielded lower total revenue (40.00 to 208.50, or 20.00 to 69.50 per customer) [E1]. Because unit sales and individual price points are not measured here, whether this divergence stems from higher individual retail prices or multiple units purchased per buyer remains an unverified possibility.

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.
- `no_markdown_table`: **matched**. Checks the explicit no-table request only; paragraph quality needs review.

Raw result, SQL/evidence, review events and report snapshots: [ranking_followup-2.json](ranking_followup-2.json).

**Manual assessment**

The five rows per ranking and product-ID tie-break match the captured SQL/results. The SQL uses the full Q1 half-open interval; the printed March 31 endpoint is ordinary calendar-day shorthand. The follow-up correctly finds no overlap and reports revenue-per-customer ranges of 108.00–259.99 and 20.00–69.50, independently recomputed from captured evidence. It explicitly says unit sales/prices are unmeasured and the explanation is unverified, correcting the core unsupported-inference defect. It reused evidence without a new query and honored the one-paragraph/no-table request. Remaining limitations: dense prose, vague causal-sounding “driven by different dynamics,” and “retail prices” instead of the more precise realized selling prices. This is one successful grounding replay, not a general reliability result. See [the earlier failed replay](../ranking-grounding-01/observations.md).

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; turns within a case share its context. No real user reports are read or modified.
