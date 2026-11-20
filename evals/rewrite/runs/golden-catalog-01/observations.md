# Replacement-agent prompt observations

Started: 2026-11-20T23:29:46.020487+00:00. Data backend: **fixture**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T23:29:46.020487+00:00",
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
    "review_overhead_bytes": 12000,
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
  "evaluation_type": "real-model smoke observation; Codex inspection completed",
  "selected_cases": [
    "golden_method"
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
  "finished_at": "2026-11-20T23:30:05.729307+00:00",
  "runtime_incomplete_or_failed_turns": 0,
  "retrieval_change": "list_golden catalog browsing and analyst-selected read_golden; no keyword filter or relevance ranking"
}
```

## Observed turns

Model USD uses reported token usage at configured rates. Held USD covers outstanding or unknown model attempts and conservative query reservations. Both are per prompt, not per conversation.

| Case / turn | Runtime status | Seconds | Model calls | Queries | Model USD | Held USD | Reviews |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| golden_method / 1 | approved | 19.667 | 5 | 1 | 0.065886 | 0.000568 | approve |

## golden_method

Independent expected facts for the frozen Calvin Klein fixture:

```json
{
  "customers": 5,
  "repeat_customers": 1,
  "repeat_percent": 20.0
}
```

### Turn 1

**Prompt**

Consult a relevant Golden example, then calculate our Q1 2026 repeat-customer share from current authorized data. Explain the result briefly.

Observed tool calls: load_skill → list_golden → read_golden → describe_data → query_data.

Runtime status: `approved`. Elapsed: 19.667 seconds.

**Full published answer**

Following the methodology in Golden example `repeat_customer_share`, the repeat-customer share is calculated by determining the number of distinct qualifying orders placed by each customer within the period.

### Q1 2026 Repeat-Customer Share

* **Total Active Customers:** 5
* **Repeat Customers (>1 order in Q1 2026):** 1
* **Repeat-Customer Share:** **20.00%** [E1]

### Explanation
* **Metric Definition:** Repeat-customer share here measures the percentage of distinct customers who placed two or more separate qualifying orders between 2026-01-01 00:00:00 UTC and 2026-04-01 00:00:00 UTC [E1].
* **Order vs. Item Level:** Purchasing multiple items within a single order counts as one order, not a repeat purchase.
* **Scope & Status Caveats:** Analysis is restricted to authorized Calvin Klein transactions and excludes cancelled or returned orders and items. This reflects an intra-quarter repeat purchase behavior rather than a lifetime customer retention rate.

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.
- `retrieval_and_fresh_query_observed`: **matched**. This prompt explicitly requests a Golden method. Tool presence does not prove that its adaptation is correct.
- `fixture_number_presence_smoke`: **matched**. Expected numeric tokens [20.0] occur in the answer. This is a weak smoke check, not a semantic numerical grade; inspect the independently enumerated facts and evidence.

Raw result, SQL/evidence, review events and report snapshots: [golden_method-1.json](golden_method-1.json).

**Manual assessment**

Pending: inspect correctness, completeness, presentation, evaluator behavior and tool adaptation. Record failures and changes before calling this case successful.

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- USD accounting separates reported model usage priced at configured rates from outstanding conservative reservations; neither is a verified provider invoice. Query reservations remain conservative.
- Each unrelated case starts a new analyst conversation; turns within a case share its context. No real user reports are read or modified.
