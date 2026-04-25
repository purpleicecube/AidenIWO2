# LOOP_11_RECORD — Beta gates (planned)

Status: **Stub** (planned, not started).
Predecessor: `LOOP_10_RECORD.md`.

## Goal

Promote IWO3 from Alpha-grade (operator-only, dev bearer auth) to Beta-grade (small-pilot, signed-token auth, hardened ops).

## Acceptance criteria (draft)

1. Production auth — replace `X-IWO3-User` + `X-IWO3-Client` with a signed-token provider; keep dev bearer behind an env flag for local development only.
2. Webhook-based channel inbound — Telegram + Slack via FastAPI webhook routes; long-polling demoted to a fallback for offline environments.
3. Per-tenant LLM token ceiling overrides — column on `clients` + browser UI in Aiden Settings.
4. Telegram offset persistence — move `_next_offset` into per-tenant DB storage (channel_identities `last_offset` column) so worker restarts are idempotent without replaying history.
5. `/health/channels` and `/health/llm` routes that surface token resolution + provider health to the browser.
6. Beta-tier Risk Register v0.3.0.

## Likely artifacts

- ADR-026 (production auth + signed tokens).
- ADR-027 (webhook channel ingress).
- ADR-028 (per-tenant overrides for runtime constants).
- New routes: `/auth/sign_in`, `/webhook/telegram/<token>`, `/health/channels`.

## Notes

This stub exists per Stage A § G4 to anchor the Beta scope conversation. The Beta cut may break into multiple loops (Loop 11, Loop 11.5) depending on operator feedback after Alpha F2 verification.
