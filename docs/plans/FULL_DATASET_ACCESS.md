> Historical plan or validation record. The current implementation is documented in [architecture.md](../architecture.md); ADK, A2A and Phoenix instructions below are superseded.

# Full dataset access

Updated: 2026-11-25.

## Behavior

Remove demo-user selection and assigned-brand restrictions. Retail, inventory and distribution can query all brands through their existing read-only tools; the coordinator requests that evidence through specialist delegation. New questions use all brands unless the user explicitly names a brand or continues a filtered question. SQL and delegated questions carry that analytical filter.

Service authentication, tool boundaries, privacy controls, execution budgets and reviewed completion remain enabled. New sessions use `workspace` for storage ownership. Existing report ownership, old conversations, captures and Phoenix history are preserved without reassignment or merging. The `workspace-all-brands-v1` source profile and fresh GUI session prevent reuse of old implicit-brand conversation context; former Docker profiles remain intact. The local CLI no longer accepts `--user`; legacy import only copies records owned by `workspace`.

## Checklist

- [x] Remove the demo-user catalog and CLI user options.
- [x] Use all-brand runtime warehouses.
- [x] Update prompts to distinguish requested brand filters from access permissions.
- [x] Configure the GUI and A2A client for the local workspace access token.
- [x] Preserve report ownership isolation and historical data.
- [x] Migrate retail scenarios to explicit requested-brand references and multi-agent scenarios to all brands.
- [x] Update current commands and mark historical persona-based documentation as superseded.
- [x] Complete the full offline test suite, lint and type checks.
- [x] Rebuild the local stack and verify agent cards, health and GUI behavior.

## Evaluation status

The 20 retail conversations retain explicit brand requests where required by their task; the state-summary case uses all brands. The three specialist/coordinator suites contain 60 conversations over all-brand data. New references use the same population as each prompt. These migrated suites have not been run and graded live. Earlier evaluation scores remain historical evidence for their original configuration.

The older controlled pilot can use explicit reference filters while agents retain all-brand access. Tests must verify both all-brand answers and user-requested filtered answers, rather than simulate access through personas.

## Verification

Runtime coverage includes all four agent types, cross-brand visibility, explicit SQL brand filters, and preservation of report ownership when legacy internal context is supplied. Verification completed:

- Full offline suite: 527 passed, 5 live/Phoenix cases deselected; two dependency warnings.
- Ruff lint/format and Pyright pass.
- Rebuilt all four agents and the GUI on BigQuery. All health endpoints and Agent Cards respond; workspace Bearer authentication is advertised.
- The GUI establishes a fresh workspace session and automatically connects to the coordinator.
- One live coordinator request compared Calvin Klein and Levi's qualifying revenue in Q1 2026. Delegation completed with an approved answer and `scope: all brands`, using the workspace Bearer credential. Recorded accounted usage was $0.114148 against a $1.50 ceiling; this is application accounting, not a provider invoice.
- Smoke evidence: `.artifacts/agents/workspace-smoke.json`. This checks access and delegation, not a full evaluation-suite quality score.
