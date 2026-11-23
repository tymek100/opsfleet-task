# Local Phoenix

The main instance at [localhost:6006](http://127.0.0.1:6006) is reserved for the authored
20-conversation evaluation. It contains one dataset, named historical experiments, one shared
trace project, and the repository prompt library.
Phoenix also retains an empty system project named `default`, which its API does not allow deleting.

Pinned versions: Phoenix 22.0.1, client 3.7.0, OTel 0.16.0, exporter 1.42.1, Google ADK
instrumentor 1.1.9, and ADK 2.12.0.

## Main workspace

Keep Docker running and execute:

```bash
uv run --locked --group evaluation retail-eval run-conversations \
  --max-cost-usd 6 --deadline-seconds 3600
```

The CLI connects to Phoenix or starts the pinned Compose service if the default endpoint is
unavailable. Independent reference capture, four-prompt synchronization, and trace setup happen
before inference. Experiment and trace links are printed at startup; answers and automatic
grades are published after each conversation. The dataset retains reference versions and old
experiments. See [evaluation](../../docs/evaluation.md) for grading semantics.

`retail-eval publish-conversations` republishes the preserved history without model calls.
It validates original capture/review files and requires their original traces to remain available.
Neither command creates per-run trace projects or hash-named datasets.

Manual service management:

```bash
docker compose -f infra/phoenix/compose.yaml up -d
docker compose -f infra/phoenix/compose.yaml down
```

The named volume preserves SQLite data across `down`; `down -v` deletes it. The service binds
only to loopback, with authentication disabled. Telemetry, external-resource fetches, and
automatic model-price updates are disabled. A custom `--phoenix-url` must already be available.
The CLI does not start the Docker daemon.

Enable trace streaming for completed spans; refresh experiments for externally published answers
and scores. These views do not stream individual answer tokens. Original trace/span IDs survive
consolidation. Experiment names use ASCII separators because Phoenix 22's JSON download places
the name in a Latin-1 HTTP header.

## Disposable test instance

Fixture evaluations and collector tests must use a separate endpoint. They reject port 6006,
and the SDK pytest auto-publication plugin is disabled to avoid test datasets appearing in the
main workspace.

```bash
docker run -d --rm --name retail-phoenix-tests \
  -p 127.0.0.1:6007:6006 \
  -e PHOENIX_ENABLE_AUTH=false \
  -e PHOENIX_TELEMETRY_ENABLED=false \
  -e PHOENIX_ALLOW_EXTERNAL_RESOURCES=false \
  -e PHOENIX_DISABLE_MODEL_COST_AUTO_UPDATE=true \
  arizephoenix/phoenix:22.0.1

# Wait until http://127.0.0.1:6007 loads, then:
PHOENIX_TEST_ENDPOINT=http://127.0.0.1:6007 \
  uv run --locked --group evaluation pytest tests/integration -m phoenix

uv run --locked --group evaluation retail-eval run \
  --suite smoke --phoenix-url http://127.0.0.1:6007 \
  --max-cost-usd 5 --deadline-seconds 900 --allow-unreviewed

docker stop retail-phoenix-tests
```

Collector tests use scripted models and no paid inference. The fixture evaluation calls Gemini.
The disposable container has no persistent volume; stopping it removes its test data.
Without `PHOENIX_TEST_ENDPOINT`, tests marked `phoenix` are skipped even when explicitly selected.

## Tracing and prompts

Normal chat tracing remains opt-in with `retail-agent chat --user alice --phoenix`.
It creates application traces separately from evaluation; using it on port 6006 will intentionally
add an application project. Normal traces contain metadata only; explicit evaluation capture can
include sanitized prompts, results, and answers.

All exported spans pass an allowlist. Raw automatic ADK payloads, credentials, hidden thoughts,
and deletion confirmation tokens are excluded. Export failure does not alter application answers;
shutdown has a bounded wait. Only provider-attempt spans retain token usage to avoid double counting.

The tracing API is `configure_tracing(endpoint, project=..., mode="metadata"|"synthetic")`.
Close the returned session in `finally`. Collector ingestion is asynchronous.

`retail-eval sync-prompts` publishes four definitions without inference. Conversation runs sync
analyst/reviewer; fixture runs sync all four to their separate instance. Unchanged versions are
reused. Git remains authoritative, and synchronization never copies model credentials into Phoenix.
[Prompt versions](../../docs/evaluation.md#prompt-versions-in-phoenix) describes Playground and
execution attribution.

The workspace cleanup backup is retained under `.artifacts/phoenix/backups/`, together with
the pre-cleanup inventory, database checksum, and deletion receipt. These files are Git-ignored.
The original 130 traces (2,684 spans) were imported from that backup and checked against their
IDs, parents, timestamps, attributes, events, and statuses. Phoenix 22's transfer API left
session ownership attached to source projects, making subsequent project deletion unsafe.
The publisher therefore does not transfer traces; new runs export directly to the shared project.
`trace-restoration.json` records verification of the recovered originals.

References: [self-hosting](https://arize.com/docs/phoenix/self-hosting/deploying-phoenix),
[configuration](https://github.com/Arize-ai/phoenix/blob/main/src/phoenix/config.py),
[ADK instrumentation](https://github.com/Arize-ai/openinference/tree/main/python/instrumentation/openinference-instrumentation-google-adk).
