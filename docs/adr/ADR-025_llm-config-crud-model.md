# ADR-025 — LLM config CRUD model

Date: 2026-04-24
Status: Accepted (Pre-Beta β.2)
Predecessors: ADR-014 (RBAC), ADR-021 (LLM runtime).
Companions: `IWO3_PRE_BETA_GAP_CLOSURE_PLAN_v0.1.0.md` § β.2.

## Context

Alpha shipped `/llm/configs` as a read-only list and `/llm/test` as a connection probe. Operators could see the configured tenant LLM stack but couldn't change provider, model, base URL, system prompt, or enabled state without editing the database directly. The directive's acceptance criterion #6 requires browser-side edit + truthful credential state without leaking raw secrets.

## Decision

### 1. CRUD shape on the existing route prefix

Extend `/llm/configs` rather than introduce a `/sub_agents/*` parallel surface. The DB row is already keyed on `(client_id, agent_role)`; introducing a second table would force every CRUD path to keep two records in sync.

```
GET    /llm/configs              list (sanitised, never includes raw secrets)
POST   /llm/configs              create  (admin)
PATCH  /llm/configs/{id}         partial update  (admin)
DELETE /llm/configs/{id}         soft delete (enabled=false) by default;
                                 ?hard=true removes the row.
```

### 2. Authorization

All write paths require `system:admin`. The choice mirrors `POST /llm/test`: changing the provider, model, or system prompt has the same audit posture as exercising it. Operator + reviewer roles continue to read.

We did not introduce a new permission key (e.g. `llm_config:update`) because the per-table CRUD vocabulary in IWO3 is intentionally sparse. Adding one would force a 4-key add (create / read / update / delete), bumping the permission cardinality by 4 and the role-permission seed by ~12 rows for marginal value. Beta may revisit.

### 3. Audit emissions

Three events distinguish lifecycle states:

- `llm_config.created` on POST.
- `llm_config.updated` on PATCH that changes any field except a pure enabled→false toggle.
- `llm_config.disabled` on PATCH that sets enabled=false (and on DELETE, soft or hard).

This keeps "who turned it off" queryable without parsing metadata diffs and matches the existing `output_package.*` lifecycle vocabulary pattern.

### 4. Truthful credential state

The list/get response carries a credential-state chip:

```
{
  "credential_state": "set" | "missing" | "malformed",
  "env_var_name": "GROQ_API_KEY" | null
}
```

`set` resolves the env var without reading its value. `missing` means the ref parsed but the env is empty. `malformed` covers refs that don't match `credential_ref:env:NAME`. The raw secret never leaves the FastAPI process.

### 5. Soft-delete is the default

`DELETE /llm/configs/{id}` defaults to `enabled=false` because removing the `aiden_tier_1` row would break Tier 1 fallback for every downstream call in that tenant. Operators must explicitly opt into a hard delete via `?hard=true`. Both paths emit `llm_config.disabled`; the metadata distinguishes via `hardDelete: bool`.

### 6. Validation surface

Server-side validation:

- `agent_role` must match `^[a-z][a-z0-9_]{1,62}$` (matches lint pattern in role-permission tests).
- `credential_ref` must match `^credential_ref:env:[A-Za-z0-9_]+$`.
- `provider` must be in the `known_providers()` set (`{groq, openrouter, openai, anthropic}`).
- Pydantic max_length on every text field bounds the request body.

## Consequences

- Operators can swap providers, change models, edit system prompts, and toggle agents from the browser without touching SQL.
- Adding a new sub-agent is a one-form interaction, not a seed JSON edit + container restart.
- The audit log gives architecture review the diff trail for free.
- Hard-deleting `aiden_tier_1` is still possible (with `?hard=true`) and remains the operator's choice.

## Out-of-scope (deferred)

- Paste-direct API key input (Beta — would require encrypted-at-rest credentials per ADR-024 deferred list).
- Per-field RBAC (e.g. allow operators to edit `enabled` but not `provider`). Beta if operator feedback warrants it.
- Tool ACL editing per agent — IWO3 has no tool registry yet.
- "New Sub-Agent" template wizard pre-populated with persona prompts. Beta UX polish.
