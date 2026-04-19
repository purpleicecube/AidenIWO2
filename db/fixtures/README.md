# IWO3 Fixture Catalog

Authoritative spec: `/home/virgina/VS_PDOE/WS024_IWO3[Branch]/05_Artifacts/IWO3_FIXTURE_CATALOG_PROPOSAL_v0.1.0.md` (internal v0.1.1).

## Taxonomy

```text
db/fixtures/
  clients/            Tenant fixtures — Klear.ai, FreedomForge.AI, synthetic isolation tenant
  work-orders/        WO happy-path, stuck, reopen/retry, candidate selection
  workflows/          WF happy-path, recovery, DigiFLOW intake, email campaign
  intake/             DigiFlowIntakePacket fixtures
  output-packages/    OutputPackage envelopes + kind-specific payloads
  adapters/           Adapter configs (Gamma, Drive, email, CRM stub, Figma stub,
                      Claude Design stub, Stitch)
  render/             Render fidelity evidence, route-selection decision records
  channel/            Telegram inbox/outbox, Slack-ready contract tests
  tenant-isolation/   Cross-tenant negative tests
  performance/        Load fixtures (100 WOs, 10k audit rows, etc.)
  assets/             Small bundled assets referenced by fixtures
```

## Invariants (enforced by tests + gitleaks)

1. **Two-tenant coverage.** Every domain fixture ships a Klear.ai variant and a FreedomForge.AI variant.
2. **Credential_ref rule.** Any credential-shaped field must contain `credential_ref:…` or `null`. See `tests/fixtures/credential-ref-rule.test.ts`.
3. **Deterministic UUIDs.** Fixture records use stable IDs (see `db/seeds/*.json` for the pattern).
4. **No live IWO2 data.** IWO2 examples used as regression fixtures are anonymized per the fixture catalog proposal §11.

## Loop coverage (from fixture catalog §13)

- Loop 1: durable rows in `db/seeds/*.json` (clients, users, memberships, template profiles, manifest). No WO/WF fixtures yet.
- Loop 2: prompt profiles + repository bindings; tenant-isolation tests green.
- Loop 3: output-package + adapter + WO happy/stuck/reopen/retry + candidate selection.
- Loop 4: channel identities + audit-log coverage.
- Loop 6: lifecycle + terminal-transition fixtures.
- Loop 9: channel inbox/outbox + Slack-ready contract test.
- Loop 10: sandbox render fidelity + Gamma fidelity evidence.
- Loop 11: diagnosis codes with operator-action metadata.
