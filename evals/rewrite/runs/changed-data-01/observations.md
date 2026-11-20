# Replacement-agent prompt observations

Started: 2026-11-20T09:17:51.893368+00:00. Data backend: **fixture**. Model: **gemini-3.8-flash**. Identity: **alice** (Calvin Klein).

These are real model smoke trials. Runtime approval and numeric-token presence are observations, not a quality score. The full answers and evidence need the manual review recorded below. This is not a held-out benchmark or a production reliability estimate.

Golden bootstrap enabled: `True`. Enabled bootstrap examples are synthetic, unapproved demonstration methods. Report storage is temporary and isolated from the user's library.

## Run configuration

```json
{
  "started_at": "2026-11-20T09:17:51.893368+00:00",
  "backend": "fixture",
  "user": "alice",
  "scope": "Calvin Klein",
  "settings": {
    "gemini_model": "gemini-3.8-flash",
    "thinking_level": "low",
    "backend": "fixture",
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
  "fixture_sha256": "ad080ec239342e8ce698a7f1cc3910c6bb85642ded1943291593c16b3c23902c",
  "independent_fixture_oracle_active": false,
  "golden_corpus_sha256": "c376f96dadf11329e0a71ac58ed3966661165e24d8fed2ca0b5075b5dd7c5720",
  "evaluation_type": "real-model smoke observations; manual quality review pending",
  "selected_cases": [
    "rankings",
    "golden_method"
  ],
  "maximum_turns": 2,
  "storage": "TemporaryDirectory per run; no user library reads/imports/mutations",
  "finished_at": "2026-11-20T09:18:27.677847+00:00",
  "runtime_incomplete_or_failed_turns": 0
}
```

## Observed turns

| Case / turn | Runtime status | Seconds | Model calls | Queries | Reviews |
| --- | --- | ---: | ---: | ---: | --- |
| rankings / 1 | approved | 14.985 | 4 | 1 | approve |
| golden_method / 1 | approved | 20.773 | 5 | 1 | approve |

## rankings

### Turn 1

**Prompt**

Show our top five products by revenue and, separately, by distinct customers in Q1 2026.

Observed tool calls: describe_data → query_data.

Runtime status: `approved`. Elapsed: 14.985 seconds.

**Full published answer**

### Calvin Klein Top Products: Q1 2026 (Jan 1, 2026 – Mar 31, 2026 UTC)

During Q1 2026, Calvin Klein recorded qualifying sales across two distinct products. Both products are ranked below by revenue and by distinct customer count [E1].

*Scope & Metric Caveat: Qualifying sales exclude cancelled and returned items and orders. Revenue is calculated as the sum of `sale_price`.*

---

#### 1. Top Products by Revenue

| Rank | Product ID | Product Name | Revenue | Distinct Customers |
| :--- | :--- | :--- | :--- | :--- |
| 1 | 1 | Alpha jeans | 575.00 | 1 |
| 2 | 3 | Alpha top | 210.00 | 4 |

---

#### 2. Top Products by Distinct Customers

| Rank | Product ID | Product Name | Distinct Customers | Revenue |
| :--- | :--- | :--- | :--- | :--- |
| 1 | 3 | Alpha top | 4 | 210.00 |
| 2 | 1 | Alpha jeans | 1 | 575.00 |

*(Note: Only two products had qualifying sales during this period.)*

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.

Raw result, SQL/evidence, review events and report snapshots: [rankings-1.json](rankings-1.json).

**Manual assessment**

Reviewed by the coding assistant against captured SQL/results and the independent fixture facts. Correct adaptation to changed fixture: Alpha jeans leads revenue at 575.00 while Alpha top leads distinct customers at 4. The original Golden ordering is not copied. The output still includes unnecessary columns and repeated disclosure.


## golden_method

### Turn 1

**Prompt**

Consult a relevant Golden example, then calculate our Q1 2026 repeat-customer share from current authorized data. Explain the result briefly.

Observed tool calls: search_golden → describe_data → read_golden → query_data.

Runtime status: `approved`. Elapsed: 20.773 seconds.

**Full published answer**

Following the analytical method from the Golden example (`repeat_customer_share`), repeat-customer share is measured by evaluating distinct qualifying orders per customer within the observation window.

### Calvin Klein — Q1 2026 Repeat-Customer Share

* **Total Customers (Q1 2026):** 5
* **Repeat Customers (>1 Order in Q1):** 2
* **Repeat-Customer Share:** **40.0%** [E1]

### Explanation & Scope Caveats
* **Window & Scope:** Covers qualifying purchases between `2026-01-01 00:00:00 UTC` and `2026-04-01 00:00:00 UTC` under brand scope **Calvin Klein**.
* **Order Definition:** Qualifying sales exclude items and orders marked as `Cancelled` or `Returned`. Multiple items within the same order ID count as a single order.
* **Interpretation:** This metric reflects within-quarter repeat purchasing behavior (customers placing 2 or more distinct qualifying orders in Q1 2026), rather than a lifetime retention or multi-quarter cohort repeat rate.

**Narrow automated observations**

- `reviewed_answer_present`: **matched**. Runtime approval observed; this alone does not establish correctness or readability.
- `retrieval_and_fresh_query_observed`: **matched**. This prompt explicitly requests a Golden method. Tool presence does not prove that its adaptation is correct.

Raw result, SQL/evidence, review events and report snapshots: [golden_method-1.json](golden_method-1.json).

**Manual assessment**

Reviewed by the coding assistant against captured SQL/results and the independent fixture facts. Correct fresh value: 2 repeat customers / 5 customers = 40%, differing from the retrieved seed answer of 20%. Trace records repeat_customer_share revision 1 and a fresh query. Briefness still needs improvement.

## Limits of this run

- The listed prompts are smoke/regression cases, including prompts related to retrieval seeds; they do not measure held-out generalization.
- Numeric-token checks can miss incorrect attribution, wrong denominators and fabricated explanations. Independent expected facts and actual query evidence are included for manual review.
- Fixture trials use a real model but synthetic local data. BigQuery trials use real warehouse data and do not apply the frozen-fixture oracle.
- Reserved USD is conservative admission accounting, not an invoice estimate. Model usage is recorded separately.
- Each unrelated case starts a new analyst conversation; report creation and saving share one conversation. No real user reports are read or modified.
