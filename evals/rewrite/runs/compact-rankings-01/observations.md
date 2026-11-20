# Replacement-agent prompt observations

Started: 2026-11-20T14:37:55.377500+00:00. Data backend: **bigquery**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T14:37:55.377500+00:00",
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
    "compact_rankings"
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
        "version": "3",
        "sha256": "d22cb3992ac18621478c04e2784c3f6b35e3a5e903e2f2a67803cb7ba511da82"
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
        "version": "2",
        "sha256": "5b69641f73fbeb71c155890e746c3b930e9b07990d77672d1a13020f97185dfb"
      }
    ]
  },
  "maximum_turns": 1,
  "storage": "TemporaryDirectory per run; no user library reads/imports/mutations",
  "finished_at": "2026-11-20T14:38:21.845692+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| compact_rankings / 1 | approved | 26.423 | 5 | 2 | approve |

## compact_rankings

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026. Use two compact tables.

Observed tool calls: load_skill → describe_data → query_data → query_data.

Runtime status: `approved`. Elapsed: 26.423 seconds.

**Full published answer**

Here are Calvin Klein's top five products by revenue and distinct customers for Q1 2026 (2026-01-01 to 2026-04-01 UTC).

### Top Products by Revenue

| Rank | Product Name | Revenue |
| :--- | :--- | :--- |
| 1 | Calvin Klein Mens 2 Button Solid Black Wool Suit | 259.99 |
| 2 | Calvin Klein Mens Navy Blue Pindot Slim Fit Wool Suit | 259.99 |
| 3 | Calvin Klein Sportswear Men's Double Breasted Cardigan Sweater | 236.00 |
| 4 | Calvin Klein Sportswear Men's Melton Wool Basic Peacoat | 228.00 |
| 5 | Calvin Klein Men's Wool Car Coat With Bib | 216.00 |

### Top Products by Distinct Customers

| Rank | Product Name | Distinct Customers |
| :--- | :--- | :--- |
| 1 | Calvin Klein Women's 2 Pocket Collar Blouse | 3 |
| 2 | Calvin Klein Women's Solid Skirtini | 3 |
| 3 | Calvin Klein Women's MSY Crew Neck Roll Sleeve | 2 |
| 4 | Calvin Klein Three Quarter Sleeve Dress | 2 |
| 5 | Calvin Klein Women's Naked Glamour Bikini | 2 |

*Note: Based on qualifying sales items (excluding cancelled and returned orders/items); currency is unstated. Ties are broken deterministically by ascending product ID (ranks 3–5 in customer reach tie with 13 other products having 2 distinct customers).*

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [compact_rankings-1.json](compact_rankings-1.json).

**Manual assessment**

The agent loaded product-ranking-analysis version 3, and the evaluator used analytical-review version 2. Two tables each contain five rows and only rank, product name and the requested metric. Product IDs remain in the supporting query evidence but are omitted from the published columns. Scope appears once, and a shared note replaces the long scope/methodology block. Values and ordering agree with E1. The note's 13 other tied products is consistent with E2's 16 total cutoff ties minus the three displayed selections, although that parenthesis is still more detail than necessary. No report mutation occurred. See the [actual terminal rendering](terminal-preview.txt) and [presentation follow-up assessment](../../../../docs/runtime-skills-test-observations.md#compact-ranking-presentation-follow-up). This single trial does not guarantee identical future wording.

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; turns within a case share its context. No real user reports are read or modified.
