# IWO3 Risk Register v0.2.2

Date: 2026-04-25
Predecessor: v0.2.1 (Pre-Beta β.7).
Closeout: Alpha Closeout Gap-Push γ.7.

This bump records the operator-trust risks that γ closure resolved and
the Alpha-walkthrough residuals that are now intentionally documented
rather than open.

## Active risks (carried forward, unchanged unless noted)

### R-021 [S1] (carried) Per-WO LLM token ceiling enforced only at call-time
Unchanged. Beta-track.

### R-022 [S2] (carried) Telegram offset persistence is in-process
Unchanged. Beta-track.

### R-023 [S2] (carried) Auth-code consume runs on bypass connection
Unchanged.

### R-024 [S2] (carried) Telegram bot token loss → outbound stall
Unchanged.

### R-025 [S2] (carried) Workflow launch from chat is deferred to Beta
Unchanged.

### R-028 [S3] (carried) Dev bearer auth in production for Alpha
Unchanged.

### R-029 [S2] (carried) `system:admin` is the only RBAC gate on llm_config CRUD
Unchanged.

### R-030 [S3] (carried) `display_name` backfill is heuristic
Unchanged.

### R-031 [S3] (carried) "New Sub-Agent" form has no template / persona library
Unchanged.

## New (γ-introduced) risks

### R-032 [S3] (NEW) Chat context is in-process Streamlit session state
The γ.1/γ.2 follow-up resolver and idempotency guard both depend on
`st.session_state["iwo3_chat_context"]` and `iwo3_chat_promoted`. A
browser refresh or tab close clears the context — operators cannot
ask "where is the output" of work created in a previous session.

**Mitigation:** Output Packages page now sorts latest-first with
work-order title chips, so "where is the output" answers visually
even when the chat context is gone. Beta is the right place to add
durable per-operator chat history (and the IWO2 vision of a richer
Workspace).

### R-033 [S3] (NEW) Idempotency guard is client-side, not server-side
The chat promote-action guard prevents duplicate WOs only within a
single Streamlit session. A second tab or a different operator could
still trigger a duplicate. The backend's `correlation_id` is set per
button-click-id (`chat:{idx}-{create|run}`) so it's at least traceable,
but there is no UNIQUE constraint preventing a duplicate WO insert.

**Mitigation:** The realistic blast radius is small — chat-driven WOs
are operator-initiated, not automated. Beta can add a UNIQUE on
`(client_id, correlation_id)` for chat-prefixed correlations if this
becomes a real problem.

## Retired (resolved by γ closure)

### R-old-5 [retired] Post-run path leaves operator with opaque UUIDs
Resolved by γ.1 — Open WO / Open Output Package / Open Audit Log
buttons render on every promote-status message; deep-links via
`st.session_state` route to the focused row.

### R-old-6 [retired] Follow-up prompts burn tokens classifying "where is the output"
Resolved by γ.2 — `_maybe_followup_reply` short-circuits before any
`/aiden/chat` call.

### R-old-7 [retired] Output discovery requires reading raw UUID lists
Resolved by γ.3 — Output Packages page sorts latest-first, surfaces
work-order title chips, accepts focus-from-chat.

### R-old-8 [retired] WO detail is dense but not interpretable at a glance
Resolved by γ.4 — Aiden decision card + state-chip emoji at the top
of the Lifecycle tab; expander header carries the same chip.

### R-old-9 [retired] Workspace is a dead placeholder during Alpha walkthrough
Resolved by γ.5 — real recent-activity dashboard with metric cards
and deep-links.

### R-old-10 [retired] FastAPI restart was sticky / unstable
Resolved by γ.6 — `scripts/iwo3.sh up\|down\|status\|restart` is the
single boring entry point; env layering verified.

## Process notes

The register is reviewed at every loop closeout. v0.3.0 expected at the
end of MegaLoop Beta and will retire R-021, R-024, R-028 if Beta lands
per-tenant overrides + production auth + `/health/channels`.
