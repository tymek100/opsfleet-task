# Replacement-agent prompt observations

Started: 2026-11-20T14:37:55.377880+00:00. Data backend: **fixture**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T14:37:55.377880+00:00",
  "backend": "fixture",
  "user": "alice",
  "scope": "Calvin Klein",
  "settings": {
    "gemini_model": "gemini-3.8-flash",
    "thinking_level": "low",
    "review_thinking_level": "medium",
    "backend": "fixture",
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
  "fixture_sha256": "b9d69b87067b2fa0ea3332ad6775a52b435537f58af001c69f1ae4043425aa55",
  "independent_fixture_oracle_active": true,
  "golden_corpus_sha256": "c376f96dadf11329e0a71ac58ed3966661165e24d8fed2ca0b5075b5dd7c5720",
  "evaluation_type": "real-model smoke observations; manual quality review pending",
  "selected_cases": [
    "rankings_with_details"
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
  "finished_at": "2026-11-20T14:38:29.157862+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| rankings_with_details / 1 | approved | 33.735 | 6 | 3 | approve |

## rankings_with_details

Independent expected facts for the frozen Calvin Klein fixture:

```json
{
  "revenue_ranking": [
    [
      "Alpha top",
      200.0
    ],
    [
      "Alpha jeans",
      175.0
    ]
  ],
  "distinct_customer_ranking": [
    [
      "Alpha top",
      4
    ],
    [
      "Alpha jeans",
      1
    ]
  ],
  "sold_products": 2,
  "interpretation": "Only two products qualify; a correct top five must disclose the short list."
}
```

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026. Include product IDs in both tables and explain the sales exclusions and tie-breaking.

Observed tool calls: load_skill → describe_data → query_data → query_data → query_data.

Runtime status: `approved`. Elapsed: 33.735 seconds.

**Full published answer**

### Calvin Klein Product Rankings (Q1 2026: 2026-01-01 to 2026-03-31 UTC)

During Q1 2026, only two Calvin Klein products recorded qualifying sales, so both qualify as the available top products [E1, E2].

#### Top Products by Revenue

| Rank | Product ID | Product Name | Revenue |
| :--- | :--- | :--- | :--- |
| 1 | 3 | Alpha top | 200.00 |
| 2 | 1 | Alpha jeans | 175.00 |

#### Top Products by Distinct Customers

| Rank | Product ID | Product Name | Distinct Customers |
| :--- | :--- | :--- | :--- |
| 1 | 3 | Alpha top | 4 |
| 2 | 1 | Alpha jeans | 1 |

---

### Sales Exclusions and Tie-Breaking

- **Sales Exclusions**: Figures are drawn from qualifying retail sales, which exclude any records where `item_status` or `order_status` is `Cancelled` or `Returned` (in Q1 2026, 3 transaction items were excluded under these criteria) [E1, E3]. Revenue reflects the sum of qualifying item sale prices (unspecified currency), and customer reach reflects distinct purchasing customer IDs [E1].
- **Tie-Breaking**: Rankings are ordered descending by the primary metric (revenue or distinct customer count), with ties broken deterministically by ascending `product_id`. For this period, the values were strictly distinct, so no tie-breaker was required to determine the rankings [E1]. Fewer than five products qualified in Q1 2026 [E2].

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [rankings_with_details-1.json](rankings_with_details-1.json).

**Manual assessment**

The explicit request for IDs and methods overrides the compact defaults: both tables retain product IDs and the answer explains sales exclusions and tie-breaking. Alpha top (ID 3) and Alpha jeans (ID 1) have the independently enumerated revenue/customer values, and the answer discloses that only two products qualify. E3 supports the three excluded item rows across returned/cancelled order/item combinations. Both loaded skill versions match the compact trial (ranking 3, reviewer 2); no report mutation occurred. See the [compact-ranking replay](../compact-rankings-01/observations.md). This is a synthetic-data control with a real model, not a live warehouse benchmark.

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; turns within a case share its context. No real user reports are read or modified.
