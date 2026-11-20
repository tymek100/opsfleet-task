# Replacement-agent prompt observations

Started: 2026-11-20T12:54:58.289768+00:00. Data backend: **bigquery**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T12:54:58.289768+00:00",
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
  "finished_at": "2026-11-20T12:55:34.923974+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| ranking_followup / 1 | approved | 22.748 | 4 | 1 | approve |
| ranking_followup / 2 | approved | 13.868 | 3 | 0 | approve |

## ranking_followup

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026. Use two compact tables.

Observed tool calls: describe_data → query_data.

Runtime status: `approved`. Elapsed: 22.748 seconds.

**Full published answer**

Here are Calvin Klein's top five products by revenue and by distinct customers for Q1 2026 (January 1, 2026, to April 1, 2026 UTC). Figures are based on qualifying sales, which exclude cancelled and returned items. Ties are ordered deterministically by product ID.

### Top 5 Products by Revenue

| Rank | Product Name | Revenue | Distinct Customers |
| :---: | :--- | :---: | :---: |
| 1 | Calvin Klein Mens 2 Button Solid Black Wool Suit | 259.99 | 1 |
| 2 | Calvin Klein Mens Navy Blue Pindot Slim Fit Wool Suit | 259.99 | 1 |
| 3 | Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater | 236.00 | 2 |
| 4 | Calvin Klein Sportswear Men's Melton Wool Basic Peacoat | 228.00 | 1 |
| 5 | Calvin Klein Men's Wool Car Coat With Bib | 216.00 | 2 |

---

### Top 5 Products by Distinct Customers

| Rank | Product Name | Distinct Customers | Revenue |
| :---: | :--- | :---: | :---: |
| 1 | Calvin Klein Women's 2 Pocket Collar Blouse | 3 | 208.50 |
| 2 | Calvin Klein Women's Solid Skirtini | 3 | 162.00 |
| 3 | Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater | 2 | 236.00 |
| 4 | Calvin Klein Men's Wool Car Coat With Bib | 2 | 216.00 |
| 5 | Calvin Klein Sportswear Men's Pindot Bowery Pant | 2 | 159.00 |

*(Note: In the customer ranking, items with the same number of customers are secondary-ranked by revenue [E1].)*

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [ranking_followup-1.json](ranking_followup-1.json).

### Turn 2

**Prompt**

Which products appear in both rankings? Explain what this suggests about revenue versus customer reach in one short paragraph, without a table.

Observed tool calls: read_result.

Runtime status: `approved`. Elapsed: 13.868 seconds.

**Full published answer**

Two products appear in both top-five rankings for Q1 2026: the **Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater** (revenue rank 3 with 236.00; customer rank 3 with 2 customers) and the **Calvin Klein Men's Wool Car Coat With Bib** (revenue rank 5 with 216.00; customer rank 4 with 2 customers) [E1]. This limited overlap illustrates that top revenue and broad customer reach do not necessarily align in this catalog: higher-priced outerwear and suits can lead total revenue on single-customer purchases (such as the wool suits generating 259.99 from 1 customer each), whereas lower-priced apparel items can attract the largest customer bases (up to 3 customers) without reaching the top revenue tiers, though the overall customer volumes across all top items remain very modest.

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [ranking_followup-2.json](ranking_followup-2.json).

**Manual assessment**

The requested five rows per list and the two overlapping product IDs match the captured SQL/results. This run used revenue as a secondary customer-ranking tie-break, which explains the different overlap from the user's product-ID selection. Its preface described the tie-break incompletely, although the customer-table footnote disclosed it. **The follow-up still failed grounding:** it described higher/lower-priced products without unit-price or quantity evidence, and the evaluator falsely approved it. This failed first prompt revision is retained. The subsequent strengthened guidance and replay are documented in [the focused report](../../../../docs/ranking-grounding-observations.md).

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; report creation and saving share one conversation. No real user reports are read or modified.
