# Replacement-agent prompt observations

Started: 2026-11-20T13:11:24.934017+00:00. Data backend: **bigquery**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T13:11:24.934017+00:00",
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
        "version": "2",
        "sha256": "663bd2ef145ed41c07b0aca4f69e687eae761f88e859b2c83faedc6c129f1bf5"
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
  "finished_at": "2026-11-20T13:12:25.530439+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| ranking_followup / 1 | approved | 31.327 | 5 | 2 | approve |
| ranking_followup / 2 | approved | 29.232 | 6 | 1 | approve |

## ranking_followup

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026. Use two compact tables.

Observed tool calls: load_skill → describe_data → query_data → query_data.

Runtime status: `approved`. Elapsed: 31.327 seconds.

**Full published answer**

### Top 5 Products by Revenue (Q1 2026)

| Rank | Product ID | Product Name | Revenue |
| :---: | :---: | :--- | :---: |
| 1 | 20041 | Calvin Klein Mens 2 Button Solid Black Wool Suit | 259.99 |
| 2 | 20235 | Calvin Klein Mens Navy Blue Pindot Slim Fit Wool Suit | 259.99 |
| 3 | 19152 | Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater | 236.00 |
| 4 | 23837 | Calvin Klein Sportswear Men's Melton Wool Basic Peacoat | 228.00 |
| 5 | 23740 | Calvin Klein Men's Wool Car Coat With Bib | 216.00 |

### Top 5 Products by Distinct Customers (Q1 2026)

| Rank | Product ID | Product Name | Distinct Customers |
| :---: | :---: | :--- | :---: |
| 1 | 29 | Calvin Klein Women's 2 Pocket Collar Blouse | 3 |
| 2 | 13390 | Calvin Klein Women's Solid Skirtini | 3 |
| 3 | 2 | Calvin Klein Women's MSY Crew Neck Roll Sleeve | 2 |
| 4 | 3927 | Calvin Klein Three Quarter Sleeve Dress | 2 |
| 5 | 10809 | Calvin Klein Women's Naked Glamour Bikini | 2 |

---

**Scope and Notes:**
* **Period & Population:** Qualifying Calvin Klein item purchases between January 1, 2026, and March 31, 2026 (excluding cancelled and returned items; currency is unspecified).
* **Tie-Breakers:** In both rankings, ties are ordered by ascending product ID. In the customer ranking, exactly 2 products reached 3 distinct customers, while 16 products tied at 2 distinct customers. Ranks 3 through 5 represent the first three tied products under this deterministic tie-break rule.

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [ranking_followup-1.json](ranking_followup-1.json).

### Turn 2

**Prompt**

Which products appear in both rankings? Explain what this suggests about revenue versus customer reach in one short paragraph, without a table.

Observed tool calls: load_skill → analyze_results → read_result → query_data.

Runtime status: `approved`. Elapsed: 29.232 seconds.

**Full published answer**

**None of the products appear in both rankings.** This complete lack of overlap indicates that top revenue in Q1 2026 is driven by higher-priced items sold in very low quantities (such as suits and outerwear priced between 108 and 259.99 with only 1 to 2 buyers), whereas top customer reach is led by lower-priced apparel and swimwear (such as blouses and bikinis priced between 20 and 69.50 with 2 to 3 buyers). Consequently, broad customer reach does not translate directly into top revenue rankings in this period, as unit price disparity outweighs modest differences in customer volume.

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.
- `no_markdown_table`: **matched**. Checks the explicit no-table request only; paragraph quality needs review.

Raw result, SQL/evidence, review events and report snapshots: [ranking_followup-2.json](ranking_followup-2.json).

**Manual assessment**

The model independently loaded product-ranking-analysis version 2 in both turns. Initial lists each contain five products, use the stated product-ID ties and have four columns; the unsupported Complete-only wording and unsolicited overlap section are gone. Notes remain verbose. The follow-up locally checked the intersection, then queried actual quantities and average realized prices for the ten selected products before explaining their difference. E3 is empty; E5 supports the reported unit/price ranges, with each average checked as revenue divided by units. This corrects the original missing-evidence problem through autonomous investigation. “Driven by” and “outweighs” remain stronger wording than necessary for a descriptive selected-product comparison. Runtime approval is not a general correctness guarantee. See [the focused report](../../../../docs/runtime-skills-test-observations.md).

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; turns within a case share its context. No real user reports are read or modified.
