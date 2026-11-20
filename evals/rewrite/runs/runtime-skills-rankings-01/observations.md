# Replacement-agent prompt observations

Started: 2026-11-20T13:09:06.585907+00:00. Data backend: **bigquery**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T13:09:06.585907+00:00",
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
  "runtime_skills": {
    "analyst": [
      {
        "name": "business-report-writing",
        "description": "Write concise business reports or executive summaries from analytical evidence, choosing useful presentation and measurable proposed actions without a fixed template.",
        "version": "1",
        "sha256": "260738557ddb01a814fd5b591b912c7171abf39aa03acca17d70b4e5c8b03b71"
      },
      {
        "name": "customer-retention",
        "description": "Analyze acquisition cohorts, repeat purchasing, retention, churn or inactivity. Use when customer history, time eligibility or cohort denominators determine the answer.",
        "version": "1",
        "sha256": "1accb5a99a51cd021c61352bc226eb5d2e1b1945f8335797f8c5c25d8077055e"
      },
      {
        "name": "period-comparison",
        "description": "Compare revenue or other metrics across months, quarters or other periods, including partial periods, percentage changes and zero baselines.",
        "version": "1",
        "sha256": "49b10351be16d647e5ac8b93ca6f6c18ca329e764eae4fde0784b091d2b1b3be"
      },
      {
        "name": "product-ranking-analysis",
        "description": "Compare product rankings, top-N selections, customer reach, ranking overlap and boundary ties. Use for interpreting leaders or follow-ups about products in earlier lists.",
        "version": "1",
        "sha256": "939d4b5d0a17ac7f30b2084d65f534b67234167dd5f09bb143548d4b010d6bc9"
      },
      {
        "name": "revenue-driver-analysis",
        "description": "Investigate why revenue differs or changes, including prices, quantities, customers, order patterns and revenue concentration. Use when an explanation needs more than ranking membership.",
        "version": "1",
        "sha256": "2b64b783bd7621c2bc7b7edde9b47fdb963931eeb3d88770b236566f9c175b23"
      }
    ],
    "reviewer": [
      {
        "name": "analytical-review",
        "description": "Review analytical answers for requested coverage, supported interpretations, metric validity, useful presentation and authorized operations. Supplied to the evaluator on every review.",
        "version": "1",
        "sha256": "25723ae360572065bca83c44216b7f621e45eb4cf876ac1ea0b26c8003157b2e"
      }
    ]
  },
  "maximum_turns": 2,
  "storage": "TemporaryDirectory per run; no user library reads/imports/mutations",
  "finished_at": "2026-11-20T13:10:12.661513+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| ranking_followup / 1 | approved | 45.001 | 7 | 2 | revise, approve |
| ranking_followup / 2 | approved | 21.036 | 4 | 0 | approve |

## ranking_followup

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026. Use two compact tables.

Observed tool calls: load_skill → describe_data → query_data → query_data.

Runtime status: `approved`. Elapsed: 45.001 seconds.

**Full published answer**

### Top 5 Products by Revenue (Q1 2026)

| Rank | Product ID | Product Name | Revenue | Distinct Customers | Items Sold |
|---|---|---|---|---|---|
| 1 | 20041 | Calvin Klein Mens 2 Button Solid Black Wool Suit | 259.99 | 1 | 1 |
| 2 | 20235 | Calvin Klein Mens Navy Blue Pindot Slim Fit Wool Suit | 259.99 | 1 | 1 |
| 3 | 19152 | Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater | 236.00 | 2 | 2 |
| 4 | 23837 | Calvin Klein Sportswear Men's Melton Wool Basic Peacoat | 228.00 | 1 | 1 |
| 5 | 23740 | Calvin Klein Men's Wool Car Coat With Bib | 216.00 | 2 | 2 |

*Note: Ranks 1 and 2 tied on revenue (259.99); ordered by ascending Product ID.*

---

### Top 5 Products by Distinct Customers (Q1 2026)

| Rank | Product ID | Product Name | Distinct Customers | Revenue | Items Sold |
|---|---|---|---|---|---|
| 1 | 29 | Calvin Klein Women's 2 Pocket Collar Blouse | 3 | 208.50 | 3 |
| 2 | 13390 | Calvin Klein Women's Solid Skirtini | 3 | 162.00 | 3 |
| 3 | 19152 | Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater | 2 | 236.00 | 2 |
| 4 | 23740 | Calvin Klein Men's Wool Car Coat With Bib | 2 | 216.00 | 2 |
| 5 | 22352 | Calvin Klein Sportswear Men's Pindot Bowery Pant | 2 | 159.00 | 2 |

*Note: Exactly 2 products reached 3 distinct customers in Q1 2026; 16 products tied at 2 distinct customers. Ranks 3 to 5 were ordered by total revenue descending, then ascending Product ID.*

---

### Scope & Methodology
- **Timeframe:** Q1 2026 (`2026-01-01 00:00:00 UTC` to `2026-04-01 00:00:00 UTC`).
- **Brand Scope:** Calvin Klein.
- **Population:** Qualifying completed sales (excluding cancelled and returned items and orders). Currency is unspecified in the source data.
- **Overlap:** Two products appear in both top-5 rankings: *Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater* (Product ID 19152) and *Calvin Klein Men's Wool Car Coat With Bib* (Product ID 23740).

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [ranking_followup-1.json](ranking_followup-1.json).

### Turn 2

**Prompt**

Which products appear in both rankings? Explain what this suggests about revenue versus customer reach in one short paragraph, without a table.

Observed tool calls: load_skill → read_result.

Runtime status: `approved`. Elapsed: 21.036 seconds.

**Full published answer**

Two products appear in both top-5 rankings for Q1 2026: **Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater** (Product ID 19152; revenue 236.00, 2 distinct customers) and **Calvin Klein Men's Wool Car Coat With Bib** (Product ID 23740; revenue 216.00, 2 distinct customers) [E1]. This overlap demonstrates that top revenue in this period was achieved through two distinct patterns: while the very highest revenue leaders (such as the two wool suits at 259.99 each) reached the top via single high-value transactions from a single customer, these two overlapping items generated comparable top-tier revenue by combining moderate transaction values with broader customer reach across multiple buyers [E1]. Customer reach alone did not guarantee the highest revenue—as seen with items reaching 3 customers but generating lower totals (162.00 to 208.50)—meaning both high unit value and multiple purchasing customers served as viable paths to top revenue performance [E1].

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.
- `no_markdown_table`: **matched**. Checks the explicit no-table request only; paragraph quality needs review.

Raw result, SQL/evidence, review events and report snapshots: [ranking_followup-2.json](ranking_followup-2.json).

**Manual assessment**

The agent independently selected product-ranking-analysis in both turns. Published values, actual selected lists and tie counts agree with captured evidence, but the initial six-column tables and extra methodology/overlap exceeded the compact request. “Qualifying completed sales” was misleading because the default relation is not Complete-only. The evaluator requested one grounding revision and then approved; the original draft and issue text are not persisted, so the specific repaired defect cannot be established from these metadata traces. The follow-up's unit-price comparison is supportable because E1 includes items_sold; it must not be confused with the earlier failure that had no unit measurements. Whole-order transaction values were not measured, so that wording is imprecise. See [the focused report](../../../../docs/runtime-skills-test-observations.md).

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; turns within a case share its context. No real user reports are read or modified.
