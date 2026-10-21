---
name: interview-delivery
description: Prepare this assignment's HLD, technical explanation, requirement mapping, reviewer setup, demo, or interview defense. Use for submission and design work, not to inflate routine implementation with extra process.
---

# Deliver an interview-ready retail assistant

Read the [assignment](../../../mds/task/assignment.md), relevant [client Q&A](../../../mds/q&a.md), and current implementation. Use [the architecture proposal](../../../mds/architecture_proposal.md) and [research plan](../../../mds/1-percent.md) as planning inputs. Distinguish confirmed client requirements, proposals, implemented behavior, and observed evidence.

## Optimize for the hiring decision

Make business understanding, ownership, tradeoffs, and reproducibility visible. Explain why the design fits roughly 1,000 questions/day and a few concurrent users. Prefer a small system the candidate can defend. Do not claim a guaranteed percentile, fabricate framework experience, or embellish test results. Keep total effort honest; optional retrieval does not outrank mandatory behavior.

Map each of the eight requirements to working code/tests or explicit design-only coverage. Working scope includes analysis/follow-ups/reports, a CLI, privacy/access, strict destructive confirmation, bounded recovery, and observability. Define and seed Golden trios; live retrieval remains optional. Production persona management and learning need a credible design, not an unsolicited full UI implementation.

## Produce a concrete HLD

Name services, storage, communication protocols, execution identity, and trust boundaries. Cover request flow, ingestion/freshness, query and privacy enforcement, long jobs, error/degraded behavior, deployment configuration, retention, and monitoring. Resolve public-data prototype versus private-data production honestly; a shared service account does not automatically enforce end-user row access.

Use the confirmed targets and retention rules from Q&A without duplicating stale numbers across documents. Distinguish fixed infrastructure cost from configurable per-question variable cost, and cite dated official pricing when making estimates. Explain cache scope/version keys and safe behavior after entitlement changes. Persona changes use an automated quality gate with no manual approval; Golden examples use editor/reviewer approval.

For each important tradeoff, state the chosen approach, reason, limitation, and what evidence or scale would justify changing it. Keep diagrams consistent with the explanation. No service should exist in the diagram solely to make it look production-ready.

## Make review easy

Provide tested setup with external credentials, a secret-free configuration example, dependency pinning, actual demo identities, offline tests, and explicitly labelled live checks. Verify Python application credentials separately from CLI login. Use the repository's real commands; do not publish imagined setup steps as working instructions.

Prepare a short demo around the client's priorities: separate top-seller rankings, brand-scoped churn investigation, and Q1 report/Q2 actions. Include a follow-up, an access denial, explicit save, deletion preview/cancel/confirm, and a labelled controlled failure. Show definitions, evidence, and an actual test summary. Support the candidate in explaining the SQL, constraints, one tradeoff, and remaining gaps.

Before submission, check docs against code and remove contradictory claims from the main reviewer path. Check tracked files without printing secret values; exclude credentials, local databases, and sensitive logs. Public GitHub publishing, messaging the client, and deployment require authorization from the user; this skill alone does not authorize them.
