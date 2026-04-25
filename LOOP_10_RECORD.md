# LOOP_10_RECORD — Sandbox PPTX/PDF + adapter symmetry (planned)

Status: **Stub** (planned, not started).
Predecessor: MegaLoop Alpha (`MEGALOOP_ALPHA_RECORD_v0.1.0.md`).

## Goal

Bring Sandbox PPTX + Sandbox PDF up to the same posture Gamma has at the end of Alpha:
- Live dual-gate (env flag + first-invocation confirmation), async polling, watchdog.
- Tenant-scoped output_packages + output_handoffs writes (already true; no schema change).
- Operator console parity (Sandbox tab moves from placeholder to live).

## Acceptance criteria (draft)

1. `sandbox_pptx` and `sandbox_pdf` adapters declare `envFlagName` and `isLive=true`.
2. `dispatch_gating` permits + blocks under the same Loop 9 dual-gate logic.
3. Operator can run a Sandbox render end-to-end through Submit Order and watch it complete via async polling.
4. Telegram `/status` works on a Sandbox-fulfilled WO.
5. Risk Register R-021..R-024 review for Loop 10 retirements.

## Likely artifacts

- `db/migrations/0012_loop_10_sandbox_credentials.sql` (if the sandbox needs new credential rows; otherwise reuse `adapter_credentials`).
- ADR-025 (Sandbox PPTX/PDF live activation, paralleling ADR-020 for Gamma).
- New tests under `apps/api-fastapi/tests/test_sandbox_*` and `tests/integration/sandbox-*`.

## Out-of-scope for Loop 10

- Slack adapter (deferred to Loop 11 / Beta).
- Webhook delivery for channels (deferred to Loop 11 / Beta).
- Streaming LLM responses.

## Notes

This stub exists per Stage A § G4 to anchor the next loop's scope conversation. CODEX is expected to review and lock the actual scope before Loop 10 starts.
