# Domain grounding candidate

Status: candidate prompts and skills were prepared separately from the frozen baseline and then exercised in focused run `a2a-20261124T195511Z-d0f6edc6`. No baseline regrade or replacement was performed. The inventory subset's manual comparison is recorded in `CANDIDATE_INVENTORY_REVIEW.md`; it retains remaining failures rather than claiming universal improvement.

## Runtime candidate

Inventory and distribution prompts load their respective analysis skills. Skill version 1.1 adds precise interpretation rules for modeled versus physical inventory, unknown cost, incomplete history, cutoff-filtered membership versus record visibility, creation/sale timestamps, and unsupported operational explanations. Distribution additionally checks global totals including Unknown, catalog versus stocked products, and recognized facilities versus raw center IDs. Rules constrain evidence interpretation rather than route business questions or prescribe answer text.

Both skills distinguish strict and inclusive elapsed-age boundaries and separately handle explicitly requested complete-day metrics. Distribution limits capability claims to enabled Maps tools and returned evidence, rather than all Google Maps products.

After the focused run, host-only skill version 1.2 was prepared for a final targeted rerun. Inventory explicitly preserves equality in repeated stock definitions, rejects choosing either historical alternative from absent snapshot rows, and avoids assigning ingestion or completion milestones to timestamp columns. Distribution requires exact raw-ID versus recognized-directory population labels, including optional prose metrics. These later edits were not present in run `a2a-20261124T195511Z-d0f6edc6`; its results remain associated with the earlier image versions.

The changes address the observed failures documented in `INVENTORY_REVIEW.md` and `DISTRIBUTION_REVIEW.md`. A generic caveat cannot justify a stronger unsupported assertion elsewhere in an answer.

## Isolated judge controls

`calibration_candidate.py` reads immutable answers, questions, evidence and references from baseline `a2a-20261124T191812Z-f59d6715`. It deep-copies references, adds candidate semantic criteria and derives optional population totals from frozen raw rows. It does not edit the global judge prompt, import into the baseline runner, publish to Phoenix or change original grades.

Each control pairs an observed incorrect answer with a minimally repaired version. The question, evidence, prior conversation and reference are identical; only answer prose changes. The expected labels are retained by the harness and are not supplied to the judge. Additional totals are optional-claim checks, not required answer content.

The independent bindings distinguish 32 global modeled units, 26 at recognized centers, six with Unknown attribution, six stocked products, seven catalog products, four recognized facilities and five distinct non-null recorded center IDs. The extra ID is unmatched `999`, not an identified fifth facility.

| Control | Source | Incorrect assertion under test |
|---|---|---|
| Unknown cost direction | Inventory 05/2 | Missing costs necessarily cause understatement when set to zero. |
| Snapshot versus complete history | Inventory 09/2 | No available rows proves the product was never stocked or depleted. |
| Global total and stock rule | Distribution 02/1 | Global stock is 26 and inventory membership uses qualifying sales. |
| Stocked versus catalog products | Distribution 04/2 | Six stocked products are all six catalog products. |
| Recorded IDs versus facilities | Distribution 14/1 | Five recorded non-null center IDs identify five distribution centers. |
| Modeled versus actual holdings | Inventory 07/2 | Modeled historical stock proves inventory actually held. |
| Aging versus flow and cause | Distribution 10/2 | Age measures turnover or establishes overstocking/obsolescence. |
| Stock definition with correct totals | Distribution 02/2 | Correct numeric results excuse a definition based on qualifying sales. |

### First candidate: broad criteria

Artifact directory: `.artifacts/multi-agent/calibration-candidate-20261124T193608Z-4fe7f247`.

Five pairs, ten actual judge calls: **one of five incorrect answers rejected; all five repaired answers accepted**. Six of ten expected outcomes matched. Accounted model cost: **$0.532782**; elapsed time: **105.3 seconds**.

The judge detected the global total error but missed certainty about missing cost, historical overreach, catalog population drift and the extra facility. It classified the cost-direction assertion as non-factual advice and accepted generic caveats despite the incorrect supporting clauses. This candidate is insufficient. Its exact module, references, calls, responses and grades remain in the artifact directory.

### Second candidate: atomic criteria

Artifact directory: `.artifacts/multi-agent/calibration-candidate-20261124T194004Z-7efd3b0f`.

Seven pairs, fourteen actual judge calls: **six of seven incorrect answers rejected; all seven repaired answers accepted**. Thirteen of fourteen expected outcomes matched. Accounted cost: **$0.853750**; elapsed time: **158.9 seconds**. No global judge prompt was changed.

The remaining false acceptance was "inventory actually held" in inventory 07/2, despite the distinction between modeled records and physical holdings. Distribution 02/1 failed for its incorrect total, but its separate stock-definition criterion incorrectly passed. Overall answer detection therefore did not establish detection of every defect in that answer.

### Final targeted candidate

Artifact directory: `.artifacts/multi-agent/calibration-candidate-20261124T194502Z-32590725`.

Two focused pairs, four actual judge calls: **both incorrect answers rejected and both repairs accepted**. The physical-boundary criterion explicitly rejected the actual-holdings assertion; the stock-membership criterion rejected the qualifying-sales definition in distribution 02/2 despite its correct totals. Accounted cost: **$0.308340**; elapsed time: **50.1 seconds**.

The final criteria are extracted into `semantic_contracts.py`, which contains no case IDs or answer templates. The production oracle can reuse its compact raw-row totals and criteria after the frozen baseline has finished. Earlier candidate results remain unchanged. Subtotal across these first three candidate runs: **28 model calls, $1.694872 accounted cost**.

### Full eight-pair check of the final criteria

Artifact directory: `.artifacts/multi-agent/calibration-candidate-20261124T194718Z-6d9e5420`.

Sixteen actual calls: **seven of eight incorrect answers rejected; seven of eight repairs accepted**, with no execution errors. Fourteen of sixteen expected outcomes matched. Accounted cost: **$1.031266**; elapsed time: **205.8 seconds**. The criteria and model settings were unchanged from the final targeted check.

Two limitations appeared. The unknown-cost direction claim was accepted again, demonstrating judgment variability. The repaired global-total answer was incorrectly rejected: the judge's findings referred to the original 26-unit total and qualifying-sales wording, although its resolved current-answer spans contained the repaired 32-unit total and correct sold_at definition. Original draft/reviewer/finish records were present in the broad observation context, creating an additional grading target. This is a wrong-target evaluation failure, not an incorrect repaired answer. The unchanged full execution remains useful for trajectory assessment, but answer grading should receive tool evidence, authorized prior answers and the selected final answer rather than unrelated draft/review events.

No result above is erased or relabeled as passing.

### Full eight-pair check with isolated answer context

Artifact directory: `.artifacts/multi-agent/calibration-candidate-20261124T195511Z-9bee4402`.

The exact same final criteria and eight pairs were evaluated after the grading harness filtered out draft, reviewer, finish-answer and final-turn events from answer-evaluation context. Tool observations, authorized prior answers and selected evidence remain available; trajectory assessment retains the complete execution. The run also records the partition-grading and reference-context modules, which were integrated before this rerun, so it is a versioned harness comparison rather than a claim that every change was independently ablated.

Sixteen actual calls: **all eight incorrect answers rejected and all eight repairs accepted**, with no execution errors. Accounted cost: **$0.652934**; elapsed time: **185.7 seconds**. Sources and hashes for `grading.py`, `partitions.py`, `reference_context.py` and `semantic_contracts.py` are saved beside the captured requests and results.

Total across the five candidate-control runs: **60 model calls, $3.379072 accounted cost**. The final 16/16 result demonstrates discrimination on these selected development examples, not human-calibrated reliability, repeatability across repeated trials or absence of unseen failures. The separate focused inventory run still contains manually detected semantic failures; see `CANDIDATE_INVENTORY_REVIEW.md`.

## Run and interpretation

Prepare local control artifacts without model calls:

```bash
uv run --group evaluation python -m evaluation.multi_agent.calibration_candidate --prepare-only
```

Run the actual judge with a separate budget:

```bash
uv run --group evaluation python -m evaluation.multi_agent.calibration_candidate \
  --baseline .artifacts/multi-agent/a2a-20261124T191812Z-f59d6715 \
  --max-cost-usd 2 --deadline-seconds 600
```

Controls require the named local baseline artifacts and configured Gemini credentials. Each invocation creates a separate directory and saves its source version. Missing judgments remain errors rather than inferred passes. Seven offline tests cover scope, cutoff, distinct counting, population separation, reference isolation, unchanged evidence and invalid budgets.

Use `--only modeled-not-actual-holdings,stock-rule-with-correct-totals` for the final focused pairs. This is an explicit subset, not a replacement for the earlier full paired run.

These are assistant-authored development controls built from observed failures, not human calibration or a sealed holdout. Passing them does not establish a general hallucination rate or prove that changed agent prompts now succeed. Cutoff-versus-visibility and null-sale-versus-shipment rules are present but do not yet have direct paired controls in this module.
