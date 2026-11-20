# Replacement-agent prompt observations

Started: 2026-11-20T09:30:31.456658+00:00. Data backend: **bigquery**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T09:30:31.456658+00:00",
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
    "rankings"
  ],
  "maximum_turns": 1,
  "storage": "TemporaryDirectory per run; no user library reads/imports/mutations",
  "finished_at": "2026-11-20T09:31:26.297771+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| rankings / 1 | approved | 54.828 | 7 | 2 | approve |

## rankings

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026.

Observed tool calls: describe_data → query_data → query_data → search_golden → read_golden.

Runtime status: `approved`. Elapsed: 54.828 seconds.

**Full published answer**

The top five Calvin Klein products in Q1 2026 (January 1 through March 31, 2026 UTC) ranked separately by total revenue and distinct customers are shown below [E1]. Qualifying sales exclude cancelled and returned purchases at both the item and order level; currency is unstated in the data. Ties are broken by product ID.

### Top Products by Revenue

| Rank | Product | Revenue | Distinct Customers |
|:---|:---|---:|---:|
| 1 | Calvin Klein Mens 2 Button Solid Black Wool Suit | 259.99 | 1 |
| 2 | Calvin Klein Mens Navy Blue Pindot Slim Fit Wool Suit | 259.99 | 1 |
| 3 | Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater | 236.00 | 2 |
| 4 | Calvin Klein Sportswear Men's Melton Wool Basic Peacoat | 228.00 | 1 |
| 5 | Calvin Klein Men's Wool Car Coat With Bib | 216.00 | 2 |

*Note: Ranks 1 and 2 tied on revenue at 259.99 and are ordered by product ID.*

---

### Top Products by Distinct Customers

| Rank | Product | Distinct Customers | Revenue |
|:---|:---|---:|---:|
| 1 | Calvin Klein Women's 2 Pocket Collar Blouse | 3 | 208.50 |
| 2 | Calvin Klein Women's Solid Skirtini | 3 | 162.00 |
| 3 | Calvin Klein Women's MSY Crew Neck Roll Sleeve | 2 | 139.00 |
| 4 | Calvin Klein Three Quarter Sleeve Dress | 2 | 133.20 |
| 5 | Calvin Klein Women's Naked Glamour Bikini | 2 | 40.00 |

*Note: Sixteen products tied with 2 distinct customers; product ID is used as the stable tie-breaker [E2]. If ties among those with 2 customers were instead broken by highest revenue, the 3rd through 5th positions would be Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater (236.00), Calvin Klein Men's Wool Car Coat With Bib (216.00), and Calvin Klein Sportswear Men's Pindot Bowery Pant (159.00).*

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [rankings-1.json](rankings-1.json).

**Manual assessment**

Reviewed by the coding assistant against captured evidence. Correct exact five products in each ranking, stable product-ID tie-breaking and values matching independent public reference queries. It generated fresh SQL, inspected tie context and optionally read a Golden method. Presentation still includes more tie commentary than necessary. Observed latency 54.828 seconds exceeds the 10-30 second simple-question target, while remaining within the bounded turn deadline.

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; report creation and saving share one conversation. No real user reports are read or modified.
