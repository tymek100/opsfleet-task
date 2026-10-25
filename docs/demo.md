# Reviewer demo and interview notes

Start `uv run --locked retail-agent chat --user alice`. The banner labels authentication as simulated and shows Calvin Klein scope.

1. Ask “List the top 10 best sellers by revenue and by number of customers for Q1 2026.” Inspect two separate rankings, default definitions, scope and query evidence. Explain why distinct customers and mixed-brand orders matter.
2. Follow up: “For that same quarter, show total revenue and a monthly breakdown.” Confirm the period remains Q1 2026.
3. Ask “Why did our churn rate spike last month? Verify whether it actually increased.” Inspect numerator/denominator at the two as-of dates. The answer should reject a false premise if the share fell. Explain why transaction data does not establish causality.
4. Ask “Create a report for Q1 2026 including insights and actions for Q2.” Check action items, proposed success measures, and caveats. Use `/reports` to prove generation did not save anything. Then `/save Q1 review`.
5. Use `/delete Q1`, inspect exact IDs/titles, then `/cancel`. The report remains. Preview again and type `/confirm TOKEN`; the report is removed, chat context cleared and replay rejected.
6. Ask for Levi's data while Alice. The compiler rejects that brand. In a separate Bob/CEO session, demonstrate different analytics permissions and private report libraries.
7. Run the focused fault tests: `uv run pytest tests/test_bigquery.py tests/test_model_retry.py tests/test_budget_privacy.py -q`. These are **synthetic injected failures**, not staged live incidents. Explain byte rejection, same-job recovery, bounded retries and safe errors.

Assess answers against the visible evidence, not fluency alone. The public dataset changes and model execution paths vary; avoid memorizing a fixed output. If the provider is unavailable, show honest failure handling plus the offline tests. Do not present fixture answers as live queries.

Be ready to explain:

- Why the model selects a constrained analysis plan rather than executing arbitrary SQL.
- Where identity comes from and how mixed-brand customer history is scoped.
- Why state cohorts and customer rankings use separate query paths.
- What confirmation binds to, and why a new matching report is not included.
- The difference between reserved budget and measured billed cost.
- The HLD's Golden retrieval, persona publication and learning lifecycle.
- Your first-project ADK experience and what you would validate before production.
- Main limitations: demo auth, imperfect free-text DLP/narrative validation, no distributed production services, no statistical reliability claim from a small live sample.

See the [recorded report from the current runtime](examples/current-report.md) for a real example, including its scope, provenance and limitations.
