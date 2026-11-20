# From-scratch rewrite: implementation and test observations

Date: 20 November 2026. These are development smoke trials and regression checks, not a held-out benchmark or a production reliability claim.

Follow-up work: [ranking interpretation guidance and regression observations](ranking-grounding-observations.md) records four additional live conversation turns, four focused evaluator calibration calls, and the remaining limits after a user-reported unsupported explanation. Counts below describe the original rewrite trials.

The subsequent [runtime-skills refactor](runtime-skills-test-observations.md) records 158 passing offline tests, package verification, five more live conversation turns and four reviewer calibration calls. Its detailed methods now live in the skill library.

## Implemented application

The replacement is installed from `src/retail_agent/`. It has one Google ADK analyst loop, ordinary LLM-authored Markdown, model-selected tables, working Golden search/read, scoped SQL, local result transformations, evaluated completion, owner-private reports, explicit saving and trusted deletion confirmation. The old implementation and its tests are preserved under `legacy/runtime-2026-11-20/` and are outside the active package.

The tests use the installed `google-adk 2.12.0`, `google-genai 2.32.0`, `sqlglot 30.24.0`, `duckdb 2.0.0`, and `gemini-3.8-flash`. Initial live trials used low thinking for both analyst and evaluator. The final evaluator configuration and its calibration are recorded below. User report databases and credentials were not modified; every live runner uses a temporary report library.

## Problems found and corrected during implementation

1. **Reviewer-request serialization:** a Pydantic response-schema class could not be JSON-serialized for budget accounting. Real Gemini tool-call history also includes binary thought signatures, which scripted content did not initially cover. Accounting now handles both shapes without mutating the provider request; a regression test uses the real SDK types.
2. **Gemini schema compatibility:** the provider rejected `additional_properties` in the SDK's `response_schema` conversion. The reviewer now uses supported `response_json_schema` configuration and validates the returned JSON locally. The first two live attempts failed safely; their JSON captures are retained.
3. **Quarterly distinct-customer total:** the model summed monthly distinct counts 1 + 2 + 3 into an incorrect quarter total of 6; the fixture's correct union count is 5. The evaluator falsely approved it. The regression replay catches the nonadditive-total problem; the first rerun omitted that invalid total.
4. **Temporal eligibility explanation:** an answer correctly found no May-to-June inactivity spike, but incorrectly inferred that no purchases means no customers could become eligible. Eligibility changes as customers age. The first evaluator approved the false explanation, and its initial calibration still missed it. The fresh-answer rerun corrected the explanation.
5. **Unsupported currency:** a later monthly answer introduced dollar signs while also saying currency was unspecified. This was another false approval, retained as a calibration case.
6. **Saving versus deletion confirmation:** an early save acknowledgment invented an additional user-confirmation step even though the report had been saved. The application mutation itself was correct and idempotent. Updated instructions distinguish explicit saving from confirmed deletion; the next trial removed the false confirmation requirement. A further wording refinement removes staging/review jargon from the user-facing acknowledgment.
7. **Boundaries and responsiveness:** tests exposed reviewer-envelope/time/tool-slot reservations, context JSON overhead and artifact-purpose screening before storage. These were fixed. Query retries preserve a job ID within a turn; a new turn obtains a fresh ID. Native ADK cancellation was tested with a blocked model call and a subsequent successful turn.

These findings are why an `approved` runtime status is not used as the quality score.

## Initial real-model fixture trials

[Full answers, SQL and observations](../evals/rewrite/runs/fixture-smoke-01/observations.md). The frozen fixture has Q1 Calvin Klein revenue 375, six orders, seven items and five distinct customers. Only two products have qualifying sales. Expected facts were enumerated independently of the generated SQL.

| Prompt | Seconds | Independent observation |
| --- | ---: | --- |
| Separate top-five rankings | 18.248 | Correct two-product shortfall and separate rankings; unnecessarily wide tables |
| Average order value, one paragraph, no table | 9.971 | Correct 62.50 = 375 / 6; honored the format |
| Monthly revenue table | 11.830 | Revenue correct; added quarterly distinct-customer total incorrect |
| Revenue per active selling day | 16.679 | Correct new metric: Tops 200 / 2 = 100; no question-specific tool/route was added |
| Alleged inactivity spike | 23.883 | Correct 5/5 at both month-ends; incorrect added eligibility explanation |
| Empty April acquisition cohort | 19.879 | Correctly undefined, not zero percent; too verbose |
| Golden-assisted repeat share | 14.672 | Searched/read a method, queried fresh evidence, correctly returned 1/5 = 20%; too verbose |
| Generate short report without saving | 24.666 | Supported core calculations; library remained empty; report longer than requested |
| Save that exact report | 6.034 | Exactly one byte-identical report saved; acknowledgment invented extra confirmation |

All nine turns were runtime-approved. Independent inspection found three substantive answer defects and additional presentation weaknesses. Treating nine approvals as nine successful answers would be misleading.

## Public BigQuery trials

[Full answers and evidence](../evals/rewrite/runs/bigquery-smoke-01/observations.md).

The gateway was verified to compile only Google's public `bigquery-public-data.thelook_ecommerce` sample tables; no private warehouse source is available to the model. The configured project supplies billing/execution. An automatic approval review initially blocked the live command as potentially sensitive warehouse export; after inspecting and explaining the fixed public-source boundary, the same test command was approved.

- The original question, “Show our top five products by revenue and, separately, by distinct customers in Q1 2026,” completed in **25.000 seconds**. It returned all five rows in each ranking. Revenue leader: Calvin Klein Men's Fashion Coat, product 24019, **398.00**. Distinct-customer leader: Calvin Klein Men's Basic Brief 3-Pack, product 25376, **6 customers**. The two ranking populations differ correctly. The output still included more columns than necessary.
- The no-table AOV question completed in **11.905 seconds**. Its one-paragraph answer reported **63.57**, supported by **11,125.180055618286 / 175 distinct orders**. It did not append a raw evidence table or internal SQL policy.

These are observed public-sample results at execution time, not expected constants for future live data.

## Changed data and Golden reuse

[Changed fixture](../evals/rewrite/changed_fixture.sql) and [captured answers](../evals/rewrite/runs/changed-data-01/observations.md). This fixture is excluded from Golden retrieval. It changes one item price and adds a second purchase for another customer; independently expected Q1 totals are 785 revenue, seven orders, eight items and five customers.

- **Rankings, 14.985 seconds:** Alpha jeans leads revenue at **575.00**; Alpha top leads distinct customers at **4**. The model did not copy the original Golden ranking or restrict the customer ranking to the revenue winner.
- **Golden-assisted repeat share, 20.773 seconds:** the trace records `repeat_customer_share`, revision 1, followed by a fresh query. The answer reports **40% = 2/5**, while the retrieved example contains **20% = 1/5**. This is direct evidence of adapting a method to changed data, although it is only one trial.

The first trace version recorded tool names but not returned Golden IDs; later traces include ID/revision. Later captures also record prompt-file hashes. The earliest exploratory captures predate that provenance improvement, and writing instructions changed during development; they are not a frozen benchmark.

## Follow-up regressions

[Full regression answers](../evals/rewrite/runs/fixture-regressions-02/observations.md) retain both improvements and newly observed defects. The invalid quarter customer total and the temporal-eligibility explanation were corrected. The monthly answer's unsupported dollar signs became an additional failure case. Saving preserved exact content and no longer requested a second confirmation, but its acknowledgment still exposed internal staging/review details before the final wording refinement.

## Reviewer calibration and final checks

The initial [three-case calibration](../evals/rewrite/runs/reviewer-calibration-01.json) rejected the incorrect monthly total and approved the correct concise AOV control, but falsely approved the contradictory eligibility explanation. Expected outcomes and issue labels were not included in reviewer inputs. These are selected development cases, so they do not estimate general reliability.

The final reviewer produces five concise factual checks before its decision and uses a separately configurable **medium thinking** setting. Missing checks, failed checks or unresolved issues cannot accompany an approved decision. The [four-case calibration](../evals/rewrite/runs/reviewer-calibration-02.json) correctly rejected the bad distinct total and invented currency and approved the correct AOV control. It **still falsely approved the contradictory eligibility explanation**. Three matched decisions out of these four selected development cases are not a reliability estimate.

Final end-to-end observations:

| Case | Seconds | Observed result |
| --- | ---: | --- |
| [Monthly table](../evals/rewrite/runs/final-fixture-03/observations.md) | 15.493 | Correct values and percentage changes, focused two-column table, no fabricated currency |
| [Short report](../evals/rewrite/runs/final-fixture-03/observations.md) | 47.483 | Core totals correct; **remaining false approval** of a category/global denominator mix-up and unsupported operational interpretation |
| [Save previous report](../evals/rewrite/runs/final-fixture-03/observations.md) | 17.439 | Exact saved Markdown/evidence and one successful receipt; no extra confirmation; some staging jargon remains |
| [Ranking with boundary ties](../evals/rewrite/runs/final-bigquery-02/observations.md) | 38.387 | Supported values, but six customer products for a five-item request; corrected top-N instructions afterward |
| [Original ranking after tie clarification](../evals/rewrite/runs/ranking-ties-03/observations.md) | 54.828 | Exactly five products per ranking, stable product-ID ties, supported by [independent reference queries](../evals/rewrite/runs/public-ranking-reference.json); still more tie commentary than necessary |

The final short report incorrectly described 2,299 / 2,674 = 86% as a Jeans-category loss rate. Its denominator is the whole brand's gross value; Jeans gross is 2,474, giving approximately 92.93%. This remains a model/evaluator semantic failure. The evaluator also accepted weakly supported fit/fulfillment risk claims. The architecture is implemented, but these observations do **not** support claiming production-ready analytical accuracy.

The live public dataset returned different values in the later runs. Fresh independent queries agreed with the later result; the observations do not assume a cause for the source change. Latest revenue leaders were two suits at 259.989990234375 each; customer leaders had three distinct customers. Stable product-ID tie-breaking produced exactly five records in both requested lists.

There were **22 captured real-model smoke/regression turns across seven run directories**, plus three initial API-spike attempts (two safe failures and one completed answer), and seven isolated reviewer calibration calls. All 22 structured smoke turns reached runtime approval; the independent assessments above show why that is not 22 quality passes. Captures were made while improving the implementation and are development evidence, not a frozen holdout score.

Offline verification: **132 tests passed**, with **80% statement coverage** in the recorded run. [Full test output](../evals/rewrite/offline-checks.txt). Native ADK loop tests use scripted model responses; they test continuation, correction, exact finalization and boundaries, not genuine reasoning. Ruff check/format, Pyright, the installed CLI entry point and all **11 Golden examples / 14 reference queries / 23 selected facts** passed their checks. Two non-failing warnings came from a blocked urllib3 loopback capability probe and an ADK experimental-schema notice.

The final default allows **12 shared model calls**, retains the **USD 1 admission cap** and **120-second deadline**, and reserves **30 seconds** for completion review based on observed review durations. The stronger review and optional extra investigations increased latency: the latest ranking took 54.828 seconds, above the client's simple-answer target. No production percentile is inferred from these samples.

## Practical limits

The model chooses the investigation and presentation, so answer length and formatting vary. The first trials showed substantial verbosity despite correct facts. Runtime review can share the analyst's errors; deterministic access controls and numerical fixture assertions remain separate from LLM judgment. The 18 proposed acceptance specifications are not all executed holdout tests, and this small run establishes neither production latency percentiles nor perfect correctness.

The prototype uses simulated identities and local storage. Production authentication, authenticated Golden publication, nontechnical persona administration and inferred preference learning remain design-only. Common pasted-contact patterns are screened, but that is not comprehensive entity recognition; warehouse PII exclusion is structural. Imported legacy sources remain separate copies until the user explicitly manages that source archive.
