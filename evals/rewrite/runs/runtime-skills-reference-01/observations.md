# Replacement-agent prompt observations

Started: 2026-11-20T13:09:06.995364+00:00. Data backend: **fixture**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `False`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T13:09:06.995364+00:00",
  "backend": "fixture",
  "user": "alice",
  "scope": "Calvin Klein",
  "settings": {
    "gemini_model": "gemini-3.8-flash",
    "thinking_level": "low",
    "review_thinking_level": "medium",
    "backend": "fixture",
    "golden_bootstrap": false,
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
    "skill_reference"
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
  "maximum_turns": 1,
  "storage": "TemporaryDirectory per run; no user library reads/imports/mutations",
  "finished_at": "2026-11-20T13:09:20.330024+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| skill_reference / 1 | approved | 13.307 | 4 | 0 | approve |

## skill_reference

Independent expected facts for the frozen Calvin Klein fixture:

```json
{
  "interpretation": "A method-only answer should distinguish realized unit selling prices from revenue per customer and quantity from distinct customers; it should not invent business facts."
}
```

### Turn 1

**Prompt**

Use the revenue-driver-analysis skill and its measurement guide to explain how you would distinguish selling-price and quantity effects in revenue changes. Answer in one short paragraph without querying or claiming current business figures.

Observed tool calls: load_skill → load_skill_resource.

Runtime status: `approved`. Elapsed: 13.307 seconds.

**Full published answer**

To distinguish selling-price and quantity effects in revenue changes, calculate realized unit selling prices (qualifying revenue divided by actual units sold) and total unit volumes across comparable periods at the appropriate product grain, rather than relying on catalogue retail prices, order counts, or distinct customer reach. You can then apply a standard price-volume decomposition to evaluate the arithmetic contribution of price changes versus unit volume changes, while accounting for product mix shifts that can alter aggregate average prices even when individual item prices remain unchanged.

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.
- `skill_and_reference_read_without_query`: **matched**. The explicitly requested skill/reference were read without a warehouse query; interpretation still needs manual review.

Raw result, SQL/evidence, review events and report snapshots: [skill_reference-1.json](skill_reference-1.json).

**Manual assessment**

The trace confirms revenue-driver-analysis and its measurement guide were loaded through separate tools. The answer correctly distinguishes realized unit prices, quantities, customer counts and mix effects, describes an arithmetic method without inventing a business result, and honors the single-paragraph request. Zero queries and no report changes occurred. This was an explicitly requested skill, so it tests loading and application rather than autonomous skill selection. See [the autonomous skill-selection replay](../runtime-skills-rankings-02/observations.md).

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; turns within a case share its context. No real user reports are read or modified.
