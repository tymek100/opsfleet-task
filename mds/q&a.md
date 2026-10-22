# Client questions and answers

Consolidated requirements log based on the replies supplied in chat. Questions are reproduced from our drafts or lightly normalized; answers are faithful summaries, not verbatim quotations. Original client replies are preserved in [Slack context](task/slack_context.md). Unanswered proposals are explicitly separated from confirmed requirements. No new questions have been sent by the assistant.

## Answered questions

### 1. Development and review credentials

**Question:** Should I use my own Google Cloud project and Gemini API key, or will you provide a project and credentials?

**Answer:** Use your own GCP project and Gemini API key for development and testing. Reviewers will use their own credentials. The application must run on another machine with externally supplied credentials, with clear setup instructions. Harry also stated that Google's free BigQuery processing allowance should be sufficient; this is a recorded client statement, not an independently verified pricing guarantee.

**Implementation consequence:** External project/key configuration, Google application credentials, no committed secrets or hardcoded personal project IDs.

### 2. Product access and demo identities

**Question:** What determines which products a user may analyze—product IDs, brands, or categories? Are two locally configured demo users with different permissions sufficient?

**Answer:** Access is brand-based. Managers may analyze only their assigned brands; the CEO may analyze all brands. The mapping is absent from the dataset, so we may choose a local configuration or access table. Two demo users with different brand permissions are sufficient.

**Implementation consequence:** Enforce trusted manager-to-brand mappings in the query layer. CEO analytics access does not bypass privacy or report ownership.

### 3. Customer privacy and rankings

**Question:** For “top customers,” may we show anonymous customer IDs and spending, or must all customer analysis be aggregated? Can state-level demographics be displayed?

**Answer:** Never expose names, emails, addresses, postal codes, or exact coordinates in output or to the LLM. Internal `user_id` values or stable pseudonyms, such as salted hashes, are allowed for rankings and multi-turn follow-ups. State-level demographics are allowed only in aggregates, not tied to identifiable individuals.

**Implementation consequence:** Exclude prohibited fields before model calls. Keep customer rankings separate from model-visible geographic aggregates. A minimum cohort size has not been specified.

### 4. Revenue and churn definitions

**Question:** How should revenue treat cancelled and returned orders, and how is churn defined? If definitions are open, may we document defaults and clarify ambiguous requests?

**Answer:** There are no fixed company-wide definitions. Document sensible defaults, state the definition used in each answer, and allow user overrides. Examples suggested by the client: revenue excludes cancelled and returned orders; churn means no purchase in the last 90 days. Clarifying ambiguous requests is appropriate.

**Implementation consequence:** Treat these as initial defaults, not immutable company policy. Define qualifying purchases, order/item status handling, churn denominator, and as-of date explicitly. Metric overrides cannot change authorization.

### 5. Report deletion and matching

**Question:** Is an exact preview followed by explicit confirmation sufficient? Should deletion be permanent or recoverable? How should “reports mentioning Client X” be interpreted?

**Answer:** Show the exact matching reports and require explicit confirmation. Deletion is permanent: hard delete, no recovery. “Client X” can mean any named entity in a report, such as a brand or category, because TheLook has no B2B clients.

**Implementation consequence:** Use an owner-scoped, single-use confirmation bound to the previewed report set. Literal versus semantic matching was not explicitly settled; case-insensitive literal entity matching is our proposed default, with the preview determining what is deleted.

### 6. Golden Knowledge prototype scope

**Question:** Are the four listed prototype requirements mandatory while Golden Knowledge can be covered in the production design, or is working retrieval also expected?

**Answer:** Golden Knowledge is primarily a design requirement. Define the Trio format—Question → SQL Query → Analyst Report—and seed a small sample set. Explain in the HLD how it would be populated and queried over time. A working retrieval demo is welcome but not required.

**Implementation consequence:** Include illustrative seed examples and the production ingestion/retrieval design. Treat runtime retrieval as optional, after mandatory prototype behavior works.

### 7. Golden Knowledge source availability

**Question:** Is there an existing Golden Knowledge bucket or sample analyst trios we should use, or should we create illustrative examples?

**Answer:** There is no existing bucket or sample collection available. It is theoretical. Create the format and a few illustrative examples ourselves. The follow-up reiterated that production population/retrieval must be explained and working prototype retrieval is optional.

**Implementation consequence:** Label seeds as illustrative; do not imply that they were supplied or approved by company analysts.

### 8. Demo priorities

**Question:** Which two or three executive questions would best demonstrate a successful solution?

**Answer:** Prioritize:

- “List the top 10 best sellers by revenue and by number of customers.”
- “Why did our churn rate spike last month?”
- “Create a report for Q1 including insights and action items for Q2.”

The client referenced an FAQ with additional examples and invited Roi Hezkiyahu to add scenarios. The FAQ itself has not been supplied here.

**Implementation consequence:** Demonstrate rankings, multi-step investigation, and report generation. Clarify the year or period when needed, and verify a claimed spike before explaining it.

### 9. Expectations for “why” questions

**Question:** Is a breakdown of measurable drivers with clearly labelled hypotheses sufficient, given that transaction data does not establish definitive causes?

**Answer:** Harry endorsed that approach: explain patterns transparently, using framing such as “data suggests X, which may be influenced by Y.” Roi was invited to confirm that it meets the assessment bar.

**Status:** Accepted working approach; additional confirmation from Roi has not been supplied.

### 10. Brand scope for customer metrics

**Question:** If a customer buys from several brands, should a manager's spend and churn calculations use only their authorized brands?

**Answer:** Yes. Both spend and churn must be calculated using only the manager's authorized brands.

**Implementation consequence:** Restrict purchase history before calculating customer metrics, rather than calculating across all brands and filtering afterward.

### 11. Reporting periods

**Question:** May we use UTC and calendar quarters by default and clarify missing time periods when they materially affect the answer?

**Answer:** Yes to UTC, calendar quarters, and clarification when the time period materially affects the answer.

**Implementation consequence:** Record period boundaries and timezone in analysis evidence and report definitions.

### 12. Saving and report privacy

**Question:** Should reports be saved only on explicit request? Are reports private to the creator, including from the CEO?

**Answer:** Save only when explicitly requested. Reports are private to their creator. The CEO's broader permissions apply to analytics, not other users' saved reports.

**Implementation consequence:** Separate generating a report from persisting it. Enforce ownership on report reads, searches, and deletion as well as creation.

### 13. Production scale, latency, cost, and location

**Question:** What user count, concurrency, response time, and cost budget should the HLD target? Are there preferred regions or data-residency requirements?

**Answer:**

| Requirement | Client target |
|---|---|
| Active managers | Roughly 100 per day |
| Questions | About 10 per manager per day |
| Saved reports | About 1 per manager per day |
| Data growth | About 1 million new rows per day |
| Concurrency | A few users active simultaneously |
| Simple-answer latency | 10–30 seconds |
| Long-report latency | 1–2 minutes |
| Question budget | USD 1, easily configurable |
| Region / data residency | No specific requirements |

**Implementation consequence:** Plan for roughly 1,000 questions and 100 reports daily. These are design targets, not measured prototype results. Our initial interpretation is a per-question variable model/query budget; clarify accounting only if it affects the design.

### 14. Golden Knowledge review and persona publishing

**Question:** Who should approve Golden examples and report-tone changes? Is a simple editor/reviewer workflow suitable?

**Answer:** Non-technical users must be able to edit tone/persona without code edits or redeployment. Changes must pass an automated quality gate before going live; no manual approval step is required. A simple editor/reviewer workflow is appropriate for Golden Knowledge. Roi may refine its specifics.

**Implementation consequence:** Keep the workflows separate: automatic gated publication for persona changes, human review for Golden examples. Persona edits cannot alter security rules or metric calculations. Specific editor/reviewer identities remain open.

### 15. Retention

**Question:** How long should conversations and diagnostic/audit records be retained? How should permanent report deletion interact with audit logs and backups?

**Answer:** Chat history: 90 days. Saved reports: retained until the user hard-deletes them, with no recovery window. Audit logs: one year.

**Implementation consequence:** Keep report content out of audit records and expire chats independently of saved reports. The client did not specify retention for detailed diagnostic payloads or physical backup deletion mechanics; those remain design details to resolve.

### 16. Existing data and analysis scheduling

**Question:** How fresh should production data be—daily, hourly, or near real time?

**Answer (Roi, 22 October 2026):** Analyze existing data ad hoc on demand; no cron-based analysis.

**Implementation consequence:** Remove the proposed daily transaction-ingestion pipeline and scheduled analysis from scope. Execute queries when users request analysis. Disclose the queried period and available data timestamp without promising upstream freshness. Golden Knowledge review/indexing and retention are separate concerns.

### 17. Brand access revocation

**Question:** If a manager loses access to a brand, should previous reports and chat history containing that brand become inaccessible?

**Answer (Roi, 22 October 2026):** Keep this out of scope; no need to handle it for the assignment.

**Implementation consequence:** Remove revocation workflows, historical-content reauthorization, and revocation-specific tests from the plan. Keep required brand checks for queries and owner checks for reports. Do not infer new offboarding or account-deletion requirements from Roi's rationale.

## Remaining questions

These are proposed follow-ups, not questions confirmed as sent. None blocks starting the prototype. Ask in a short batch or when the decision becomes relevant; do not reopen the requirements already answered above.

### Useful next questions

Priority for the next client message: the FAQ and deadline. Roi has answered the freshness and access-change questions; do not resend them. Other items can use documented assumptions unless a concrete blocker appears.

1. **FAQ and submission:** Could you share the FAQ referenced in the demo guidance, and confirm the submission deadline and preferred submission process? The original draft asked about the deadline/progress format, but no answer was supplied. We already know submission requires a public GitHub repository.
2. **Production identity:** Which SSO/identity provider and source of manager-to-brand assignments should the design integrate with? **Proposed assumption:** generic OIDC plus an administrator-managed entitlement table; local demo identities remain accepted.
3. **Small geographic groups:** Is there a minimum customer count for state-level aggregates? **Proposed assumption:** suppress groups with fewer than five distinct customers and avoid exposing individual-to-state associations; five is our proposal, not a confirmed requirement.
4. **Deleted report copies:** Should permanent report deletion also remove copies from chat history, caches, and exports, and what purge delay is acceptable for backups? **Proposed assumption:** remove application-managed content copies and prevent resurrection after restore; document backup expiration separately. We are clarifying the extent of deletion, not requesting a recovery window.
5. **Diagnostic access:** Who may view sanitized conversation/tool traces, and should those payloads expire after 90 days while content-free audit events remain for one year? **Proposed assumption:** restricted operations access, with detailed payloads retained no longer than chat history.

### Later refinements, if relevant

- **Golden Knowledge ownership:** Which role authors and reviews examples, and what checks define acceptance? The editor/reviewer pattern is accepted; actual roles and criteria remain open for Roi's input.
- **Preference learning:** May inferred formatting preferences be applied automatically, or should users confirm them? **Proposed assumption:** explicit preferences apply immediately; inferred preferences can be inspected, corrected, and reset.
- **Evaluation feedback:** Can Roi review a few sample answers and confirm the proposed “why” analysis meets the bar? We can proceed with Harry's endorsement while awaiting any refinements.
- **LLM data policy:** Beyond the confirmed ban on PII, are there additional production restrictions on sending authorized business aggregates to the selected model service? **Proposed assumption:** only minimized, authorized evidence is sent.
- **Budget accounting:** If needed, confirm whether USD 1 covers variable model and BigQuery query charges or also allocated infrastructure costs. **Proposed assumption:** enforce model/query costs per question and report fixed hosting/storage separately.

## Implementation choices we can own

The client permits documented assumptions. We do not need to ask them to select libraries or resolve every engineering detail. Current proposals include case-insensitive literal entity matching, explicit revenue/status and churn-denominator definitions, bounded retries, typed tools, and a single-use deletion token. Record the final choices in the technical explanation and revise them if later client guidance requires it.
