# Replacement-agent prompt observations

Started: 2026-11-20T00:22:01.071675+00:00. Data backend: **bigquery**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T00:22:01.071675+00:00",
  "backend": "bigquery",
  "user": "alice",
  "scope": "Calvin Klein",
  "settings": {
    "gemini_model": "gemini-3.8-flash",
    "thinking_level": "low",
    "backend": "bigquery",
    "golden_bootstrap": true,
    "turn_timeout_seconds": 120.0,
    "question_budget_usd": 1.0,
    "max_model_calls": 8,
    "max_tool_calls": 24,
    "max_queries": 8,
    "max_query_bytes": 100000000,
    "max_output_tokens": 4096,
    "review_output_tokens": 2048,
    "max_answer_reviews": 3,
    "max_context_bytes": 150000,
    "max_review_bytes": 60000,
    "review_reserve_seconds": 12.0,
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
    "rankings",
    "prose_aov"
  ],
  "maximum_turns": 2,
  "storage": "TemporaryDirectory per run; no user library reads/imports/mutations",
  "finished_at": "2026-11-20T00:22:37.995712+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| rankings / 1 | approved | 25.000 | 5 | 2 | approve |
| prose_aov / 1 | approved | 11.905 | 4 | 1 | approve |

## rankings

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026.

Observed tool calls: describe_data → query_data → query_data.

Runtime status: `approved`. Elapsed: 25.000 seconds.

**Full published answer**

Here are the top five Calvin Klein products in Q1 2026 (January 1, 2026 to March 31, 2026 UTC), ranked separately by revenue and by distinct customers.

### Top 5 Products by Revenue (Q1 2026)

| Rank | Product ID | Product Name | Category | Revenue | Distinct Customers | Distinct Orders | Units Sold |
|:---|:---|:---|:---|---:|---:|---:|---:|
| 1 | 24019 | Calvin Klein Men's Fashion Coat | Outerwear & Coats | 398.00 | 2 | 2 | 2 |
| 2 | 8253 | Calvin Klein Women's Faux Fur Trim Down Walker | Outerwear & Coats | 389.97 | 3 | 3 | 3 |
| 3 | 8583 | Calvin Klein Women's Lux Patent Trim Coat | Outerwear & Coats | 375.00 | 3 | 3 | 3 |
| 4 | 23826 | Calvin Klein Men's Slim Fit Coat | Outerwear & Coats | 350.00 | 2 | 2 | 2 |
| 5 | 3284 | Calvin Klein Women's Chiffon Dress | Dresses | 256.00 | 2 | 2 | 2 |

---

### Top 5 Products by Distinct Customers (Q1 2026)

| Rank | Product ID | Product Name | Category | Distinct Customers | Revenue | Distinct Orders | Units Sold |
|:---|:---|:---|:---|---:|---:|---:|---:|
| 1 | 25376 | Calvin Klein Men's Basic Brief 3-Pack | Underwear | 6 | 217.98 | 6 | 6 |
| 2 | 8253 | Calvin Klein Women's Faux Fur Trim Down Walker | Outerwear & Coats | 3 | 389.97 | 3 | 3 |
| 3 | 8583 | Calvin Klein Women's Lux Patent Trim Coat | Outerwear & Coats | 3 | 375.00 | 3 | 3 |
| 4 | 25440 | Calvin Klein Men's Steel Micro Boxer Brief | Underwear | 3 | 84.00 | 3 | 3 |
| 5 | 26316 | Calvin Klein Men's Micro Modal Essentials Trunk | Underwear | 3 | 84.00 | 3 | 3 |

*Note: There are exactly five products with 3 or more distinct customers in Q1 2026; products tied at 3 customers are ordered by revenue. Figures reflect qualifying purchases (excluding cancelled and returned orders/items).*

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [rankings-1.json](rankings-1.json).

**Manual assessment**

Reviewed by the coding assistant against captured SQL/results and the independent fixture facts. Correct complete top-five lists. Revenue leader: product 24019, 398.00. Customer leader: product 25376, 6 distinct customers. The two populations differ correctly. Values match returned evidence and the original reported example. Presentation still has too many unrequested columns; this is not an ideal CLI answer.


## prose_aov

### Turn 1

**Prompt**

What was our average order value in Q1 2026? Answer in one short paragraph without a table.

Observed tool calls: describe_data → query_data.

Runtime status: `approved`. Elapsed: 11.905 seconds.

**Full published answer**

In Q1 2026 (January 1 through March 31, 2026, UTC), Calvin Klein's average order value (AOV) was 63.57, generated from a total qualifying revenue of 11,125.18 across 175 distinct orders (and 175 unique customers). Qualifying sales reflect item purchases excluding cancelled and returned items at both the order and item level; currency is not specified in the reporting system.

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.
- `no_markdown_table`: **matched**. Checks the explicit no-table request only; paragraph quality needs review.

Raw result, SQL/evidence, review events and report snapshots: [prose_aov-1.json](prose_aov-1.json).

**Manual assessment**

Reviewed by the coding assistant against captured SQL/results and the independent fixture facts. Correct 11,125.180055618286 / 175 = 63.57245746067592, presented as 63.57. One paragraph and no table. Brand/status/period scope is supported by the generated SQL. This is a live public-sample-data observation, not a production estimate.

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; report creation and saving share one conversation. No real user reports are read or modified.
