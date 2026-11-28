> Historical plan or validation record. The current implementation is documented in [architecture.md](../architecture.md); ADK, A2A and Phoenix instructions below are superseded.

# Authored conversation evaluation validation

Status: implemented and integrated with the local Phoenix workspace on 2026-11-22.
Successful real-model evaluation remains unverified because Gemini rejected generation with
HTTP 402 `RESOURCE_EXHAUSTED`: the project's prepayment credits were depleted.

## Implemented behavior

`retail-eval run-conversations` captures independent source rows, computes references, runs
initial questions and follow-ups, grades answers and trajectory, and publishes incrementally.
Agent queries and reference queries read the same timestamped BigQuery table versions.
Expected facts remain outside analyst context. Follow-up references bind to the actual initial
selection, including valid ranking ties. Output wording and formatting remain the agent's choice.

The existing **Retail agent — 20 conversations** dataset now has 40 reference specifications:
two per example, with expected facts, behavioral criteria, conditional selection rules, and
source provenance. Example IDs and historical dataset versions remain intact. The six original
experiments and their assistant reviews were preserved. New automatic grades are labeled separately.

## Verification

| Check | Result |
|---|---|
| Offline tests | 334 passed; four opt-in collector tests excluded |
| Disposable Phoenix integration tests | Four passed, using scripted providers and real ADK/tools/capture/publication |
| Type and style checks | Pyright, Ruff lint, and formatting passed |
| Existing controlled dataset validation | 43 cases, nine fixtures, 40 judge controls valid |
| Main Phoenix dataset | 20 stable examples, both reference turns present, old version readable |
| Independent BigQuery capture | 4,781 transaction rows, 756 catalog rows, seven privacy-filtered state groups |
| Real application SQL vs. independent references | Qualifying Calvin Klein Q1 revenue 9,379.950008392334 and 162 orders matched within numerical tolerance |

The controlled integration deliberately lets the runtime reviewer approve a wrong, unsupported
answer. Independent grading rejects it and publishes FAIL. Other tests cover tied selections,
follow-up membership, reference tampering, hidden expected values, unavailable judges, timestamp
pinning, and provider failure without additional judge calls.

## Live attempt and limits

Run: `.artifacts/manual/manual-recheck-20261122T224704Z-371b3f35`.
Reference timestamp: `2026-11-22T22:46:49.306728+00:00`.
Selected scenarios: `manual-01`, `manual-03`, and `manual-15`, with both turns each.
Limit: $3 and 900 seconds. The dataset, source reads, trace export, and experiment publication
succeeded. Gemini returned provider errors before any answer or agent query was produced.
A minimal diagnostic request confirmed HTTP 402 and depleted prepaid credits.

The attempted run exited 2 with unresolved checks; it is not an assessment of model answer
quality. Its original diagnostic grades remain visible. Subsequently, unavailable-provider
handling was tightened: absent answers are unresolved execution errors, and the grader does
not spend additional model calls on their trajectories. This path passed an offline regression test.
The run's $0.9597 accounted amount includes conservative reservations for requests without
usage metadata; it is not a statement of billed Gemini spend.

No complete 40-answer automatic pass rate or live judge reliability is claimed. Human reference
review and judge calibration remain pending. After restoring Gemini credits, run the command
in [evaluation.md](../evaluation.md#run-the-20-conversations).

Before the dataset update, a consistent SQLite backup was saved to
`.artifacts/phoenix/backups/20261122T224633Z/phoenix.sqlite`
(SHA-256 `4b639210040c8a72752cd2a87cc075bba9d57e866ba272c566080878b792b3be`).
The independent source files, query receipts, automatic results, and verification receipt remain
under the run directory. Collector tests used a disposable instance on port 6007.
