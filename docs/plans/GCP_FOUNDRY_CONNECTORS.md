# Google inference and Foundry observability

- [x] Restore the existing Google key without exposing its value.
- [x] Verify official support for external-agent OpenTelemetry and dataset evaluations.
- [x] Separate Google model clients from Azure project and model authentication.
- [x] Export explicit sanitized spans to Azure Monitor; preserve graph ancestry and token accounting.
- [x] Publish independent references, generated answers and precomputed grades to Foundry.
- [x] Update CLI, Docker, GUI links and setup documentation.
- [x] Run offline regression tests; make no paid model calls.
- [x] Verify the live project connection after the correct Microsoft Entra login is available.

Google remains the inference and independent judge provider. BigQuery retains ADC.
Foundry receives traces and evaluation artifacts. Publishing precomputed checks does
not invoke an Azure judge or reinterpret unresolved checks as failed answers.
The application token budget remains separate from Azure telemetry/storage charges.

Verification: 527 offline Python tests, 6 frontend tests and 4 browser tests passed;
Pyright reports no errors. A real metadata-only span exported successfully. A
scripted Foundry evaluation completed with 1 passed check and no errors; its
temporary datasets and evaluation were removed afterward. No paid Gemini calls
were made. This verifies connectivity and contracts, not new model quality.

The local Docker app was rebuilt and remains healthy at localhost:8080. Google
model settings and existing conversations are preserved. The application has not
been deployed to Azure; only telemetry and evaluation use the configured project.
