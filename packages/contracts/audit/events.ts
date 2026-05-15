/**
 * Loop 2 audit event vocabulary.
 *
 * Policy (IWO3_LOOP_2_APPROVAL_DECISIONS §Q4):
 *   - Loop 2 registers only the event names Loop 2 itself triggers.
 *   - Loop 3+ adds its own event names additively.
 *   - No preloaded vocabulary for future loops.
 *
 * Consumers (Loop 2 writers):
 *   - prompt-profile CRUD / publish / deprecate
 *   - prompt-resolver override application (Loop 2 Phase 2)
 *   - repository / data-source binding CRUD + credential rotation
 *   - artifact upload / delete
 *
 * Every privileged action must write a row into `action_audit_log`
 * using one of these event names; tests assert no free-form actions
 * slip through.
 */

export const AUDIT_EVENTS = {
  // Prompt profile lifecycle
  PROMPT_PROFILE_CREATED: "prompt_profile.created",
  PROMPT_PROFILE_VERSION_CREATED: "prompt_profile_version.created",
  PROMPT_PROFILE_VERSION_PUBLISHED: "prompt_profile_version.published",
  PROMPT_PROFILE_VERSION_DEPRECATED: "prompt_profile_version.deprecated",

  // Prompt override (Loop 2 Phase 2 wires this via the resolver)
  PROMPT_OVERRIDE_APPLIED: "prompt_override.applied",

  // Repository binding lifecycle
  REPOSITORY_BINDING_CREATED: "repository_binding.created",
  REPOSITORY_BINDING_CREDENTIAL_ROTATED: "repository_binding.credential_rotated",
  REPOSITORY_BINDING_REVOKED: "repository_binding.revoked",

  // Data source binding lifecycle
  DATA_SOURCE_BINDING_CREATED: "data_source_binding.created",
  DATA_SOURCE_BINDING_REVOKED: "data_source_binding.revoked",

  // Artifact lifecycle
  ARTIFACT_UPLOADED: "artifact.uploaded",
  ARTIFACT_DELETED: "artifact.deleted",

  // Loop 3 Phase 1 — WO / WF / execution cycle lifecycle.
  // Locked at phase start per IWO3_LOOP_3_APPROVAL_DECISIONS §Q6.
  // Phase 3.2/3.3/3.4 extend this record additively.
  WORK_ORDER_CREATED: "work_order.created",
  WORK_ORDER_UPDATED: "work_order.updated",
  WORK_ORDER_ARCHIVED: "work_order.archived",
  WORKFLOW_CREATED: "workflow.created",
  WORKFLOW_UPDATED: "workflow.updated",
  WORKFLOW_ARCHIVED: "workflow.archived",
  WORKFLOW_TEMPLATE_CREATED: "workflow_template.created",
  WORKFLOW_TEMPLATE_PUBLISHED: "workflow_template.published",
  WORKFLOW_TEMPLATE_DEPRECATED: "workflow_template.deprecated",
  WORKFLOW_EXECUTION_STARTED: "workflow_execution.started",
  WORKFLOW_EXECUTION_COMPLETED: "workflow_execution.completed",
  WORKFLOW_STEP_RUN_COMPLETED: "workflow_step_run.completed",
  EXECUTION_CYCLE_STARTED: "execution_cycle.started",

  // Loop 3 Phase 2 — output packages + adapter registry + handoff +
  // candidate-review minimal lifecycle.
  // Locked at phase start per IWO3_LOOP_3_APPROVAL_DECISIONS §Q6.
  OUTPUT_PACKAGE_CREATED: "output_package.created",
  OUTPUT_PACKAGE_VALIDATED: "output_package.validated",
  OUTPUT_PACKAGE_SUBMITTED: "output_package.submitted",
  OUTPUT_PACKAGE_REJECTED: "output_package.rejected",
  OUTPUT_HANDOFF_CREATED: "output_handoff.created",
  OUTPUT_HANDOFF_SUBMITTED: "output_handoff.submitted",
  OUTPUT_HANDOFF_COMPLETED: "output_handoff.completed",
  OUTPUT_HANDOFF_FAILED: "output_handoff.failed",
  OUTPUT_CANDIDATE_SELECTED: "output_candidate.selected",
  OUTPUT_CANDIDATE_REJECTED: "output_candidate.rejected",
  ADAPTER_CONFIG_CREATED: "adapter_config.created",
  ADAPTER_CONFIG_UPDATED: "adapter_config.updated",
  ADAPTER_CONFIG_ENABLED: "adapter_config.enabled",
  ADAPTER_CONFIG_DISABLED: "adapter_config.disabled",
  ADAPTER_CREDENTIAL_ROTATED: "adapter_credential.rotated",
  ADAPTER_CREDENTIAL_REVOKED: "adapter_credential.revoked",
  ADAPTER_POLICY_CREATED: "adapter_policy.created",
  ADAPTER_POLICY_UPDATED: "adapter_policy.updated",

  // Loop 3 Phase 4 — adapter dispatch lifecycle (registry + test-double
  // Gamma demonstrator). Locked at phase start per
  // IWO3_LOOP_3_APPROVAL_DECISIONS §Q6.
  ADAPTER_DISPATCH_INITIATED: "adapter_dispatch.initiated",
  ADAPTER_DISPATCH_POLICY_REJECTED: "adapter_dispatch.policy_rejected",
  ADAPTER_DISPATCH_APPROVAL_REQUIRED: "adapter_dispatch.approval_required",
  ADAPTER_DISPATCH_PACKAGE_INVALID: "adapter_dispatch.package_invalid",
  ADAPTER_DISPATCH_SUBMITTED: "adapter_dispatch.submitted",
  ADAPTER_DISPATCH_COMPLETED: "adapter_dispatch.completed",
  ADAPTER_DISPATCH_FAILED: "adapter_dispatch.failed",

  // Loop 4 Phase 1 — permission vocabulary + role mapping + grant
  // lifecycle. Locked at phase start per IWO3_LOOP_4_APPROVAL_DECISIONS
  // §Q1 (`lock_upfront`). Phase 4.2 adds authz decision events; Phase
  // 4.3 adds RLS-related events; Phase 4.4 adds no new events.
  PERMISSION_CREATED: "permission.created",
  ROLE_PERMISSION_GRANTED: "role_permission.granted",
  ROLE_PERMISSION_REVOKED: "role_permission.revoked",
  PERMISSION_GRANT_CREATED: "permission_grant.created",
  PERMISSION_GRANT_REVOKED: "permission_grant.revoked",

  // Loop 4 Phase 2 — authorization check outcomes. `authz.granted` is
  // deliberately NOT emitted (see require_permission.ts comment): every
  // allowed call is followed by a typed mutation audit row; doubling up
  // would bloat the log without adding forensic value.
  AUTHZ_DENIED: "authz.denied",

  // Loop 6 Phase 1 — WO/WF lifecycle transition vocabulary. 12 events
  // locked upfront per §Q1 precedent from Loop 4. Every state-machine
  // transition (see packages/contracts/wo-wf/state_machines.ts) emits
  // exactly one of these events; the transition helper (Phase 6.2)
  // attaches {from, to, machine, reason?} metadata.
  WORK_ORDER_TRANSITIONED: "work_order.transitioned",
  WORK_ORDER_REOPENED: "work_order.reopened",
  WORK_ORDER_CANCELLED: "work_order.cancelled",
  WORK_ORDER_BLOCKED: "work_order.blocked",
  WORK_ORDER_UNBLOCKED: "work_order.unblocked",
  WORK_ORDER_WATCHDOG_EXPIRED: "work_order.watchdog_expired",
  WORKFLOW_TRANSITIONED: "workflow.transitioned",
  WORKFLOW_PAUSED: "workflow.paused",
  WORKFLOW_RESUMED: "workflow.resumed",
  WORKFLOW_EXECUTION_TRANSITIONED: "workflow_execution.transitioned",
  WORKFLOW_EXECUTION_CANCELLED: "workflow_execution.cancelled",
  WORKFLOW_STEP_RUN_TRANSITIONED: "workflow_step_run.transitioned",

  // Loop 9 Phase 9.1 — credential + gating foundation. Four events locked
  // at phase start per IWO3_LOOP_8_3_CODEX_DECISIONS §Q1 (dual gate) + §Q2
  // (env-injected credentials). `adapter_credential.rotated` already exists
  // as a Loop 3 Phase 2 event; Phase 9.1 adds the pre-dispatch gating
  // events + the first-invocation confirmation event.
  ADAPTER_CREDENTIAL_FIRST_INVOCATION_CONFIRMED:
    "adapter_credential.first_invocation_confirmed",
  ADAPTER_DISPATCH_LIVE_DISABLED: "adapter_dispatch.live_disabled",
  ADAPTER_DISPATCH_CREDENTIAL_MISSING: "adapter_dispatch.credential_missing",
  ADAPTER_DISPATCH_FIRST_INVOCATION_PENDING:
    "adapter_dispatch.first_invocation_pending",

  // Loop 9 Phase 9.2 — live Gamma submit-time outcomes. Two events
  // distinguish submit-time auth / quota failures from the pre-dispatch
  // gate events above. `credential_invalid` = Gamma rejected the key
  // at the HTTP layer (401/403), separate from `credential_missing`
  // (no adapter_credentials row existed at all).
  ADAPTER_DISPATCH_CREDENTIAL_INVALID:
    "adapter_dispatch.credential_invalid",
  ADAPTER_DISPATCH_RATE_LIMITED: "adapter_dispatch.rate_limited",

  // Loop 9 Phase 9.3 — LLM Foundation. Three events: invocation
  // success/failure + provider connection-test result. Per CODEX
  // guidance, llmProvider + llmModel travel in metadata so audit
  // forensics can replay which model produced which content.
  LLM_INVOKED: "llm.invoked",
  LLM_FAILED: "llm.failed",
  LLM_PROVIDER_CONNECTION_TESTED: "llm_provider.connection_tested",

  // Loop 9 Phase 9.4 — async polling. Poll-state events are distinct
  // from submit-time events: a healthy long render emits many
  // `polling` rows before a terminal `completed`. Watchdog firing
  // on stale poll is its own event so forensics can separate
  // "adapter-side failure" from "our timeout policy tripped".
  ADAPTER_DISPATCH_POLLING: "adapter_dispatch.polling",
  ADAPTER_DISPATCH_WATCHDOG_EXPIRED_STALE_POLL:
    "adapter_dispatch.watchdog_expired_stale_poll",

  // MegaLoop Alpha α.2 — LLM runtime. Token-budget circuit breaker
  // fires per Stage A §A7 (per-call 8192 default, per-WO 50K ceiling).
  // Companion events `llm.invoked` + `llm.failed` already exist from
  // Loop 9 Phase 9.3.
  LLM_BUDGET_EXCEEDED: "llm.budget_exceeded",

  // MegaLoop Alpha α.5 — channel layer. Eight events covering inbound
  // + outbound message lifecycle + identity binding via /start auth
  // code (Stage A §B5/§B6/§B7).
  CHANNEL_AUTH_CODE_ISSUED: "channel_auth_code.issued",
  CHANNEL_IDENTITY_BOUND: "channel_identity.bound",
  CHANNEL_IDENTITY_REVOKED: "channel_identity.revoked",
  CHANNEL_MESSAGE_RECEIVED: "channel_message.received",
  CHANNEL_MESSAGE_PROCESSED: "channel_message.processed",
  CHANNEL_MESSAGE_FAILED: "channel_message.failed",
  CHANNEL_MESSAGE_SEND_QUEUED: "channel_message.send_queued",
  CHANNEL_MESSAGE_SENT: "channel_message.sent",

  // Pre-Beta β.2 — LLM config CRUD. Operator-initiated mutations to
  // `llm_configs` rows. Created/updated/disabled distinguish so audit
  // forensics can separate provider/model swaps from enabled-toggle
  // events without parsing metadata diffs.
  LLM_CONFIG_CREATED: "llm_config.created",
  LLM_CONFIG_UPDATED: "llm_config.updated",
  LLM_CONFIG_DISABLED: "llm_config.disabled",

  // Pre-Beta Loop δ — Workspace mutations (folders + files). 9 events
  // locked at plan time per architect decision (5). file.saved_from_output
  // is the audit anchor for the auto-routing path that writes outputs
  // into the tenant `Outputs/` folder on produce_output_package.
  WORKSPACE_FOLDER_CREATED: "folder.created",
  WORKSPACE_FOLDER_RENAMED: "folder.renamed",
  WORKSPACE_FOLDER_MOVED: "folder.moved",
  WORKSPACE_FOLDER_DELETED: "folder.deleted",
  WORKSPACE_FILE_CREATED: "file.created",
  WORKSPACE_FILE_RENAMED: "file.renamed",
  WORKSPACE_FILE_MOVED: "file.moved",
  WORKSPACE_FILE_DELETED: "file.deleted",
  WORKSPACE_FILE_SAVED_FROM_OUTPUT: "file.saved_from_output",

  // MegaLoop Beta-1 ε — Production-posture vocabulary lock.
  // Auth, credential encryption, chat-session continuity, webhook ingress.
  // Locked here in ε.1 so later phases can emit without re-snapshotting.
  AUTH_SESSION_STARTED: "auth.session_started",
  AUTH_SESSION_REFRESHED: "auth.session_refreshed",
  AUTH_SESSION_ENDED: "auth.session_ended",
  AUTH_LOGIN_FAILED: "auth.login_failed",
  CREDENTIAL_ENCRYPTED: "credential.encrypted",
  CREDENTIAL_ROTATED: "credential.rotated",
  CHAT_SESSION_UPDATED: "chat_session.updated",
  WEBHOOK_RECEIVED: "webhook.received",
  WEBHOOK_SIGNATURE_INVALID: "webhook.signature_invalid",

  // MegaLoop Beta-1.5 phase 2 — UI-tail completion. One new event for
  // tenant-settings mutation (Q1 ceiling editor); the encryption-at-rest
  // path reuses CREDENTIAL_ENCRYPTED above (locked in ε.1 anticipating
  // this phase).
  CLIENT_SETTINGS_UPDATED: "client.settings_updated",

  // Beta-2 phase 0.1 — operator-driven output requests. Emitted by
  // POST /work_orders when requested_outputs is non-null on create
  // (Q6=A locked: jsonb on work_orders). The tier_1_5 event lands on
  // workflow instantiation when the PM honors the operator's choice.
  WORK_ORDER_REQUESTED_OUTPUTS_SET: "work_order.requested_outputs_set",
  TIER_1_5_REQUESTED_OUTPUT_HONORED: "tier_1_5.requested_output_honored",

  // Loop Xi — operator recovery loop (reopen + edit + redispatch). The
  // `reopened` event is already locked above (work_order.reopened);
  // these two extend the vocabulary for inline edits via
  // `PUT /work_orders/{id}` and explicit operator-triggered
  // re-dispatch via `POST /work_orders/{id}/redispatch`.
  // `work_order.edited` covers partial-field updates (title /
  // description / type / priority / requested_outputs.template_profile_id);
  // distinct from the existing `work_order.updated` which historically
  // carried status mutations from the transition helper. The new event
  // keeps inline-edit forensics separable from transition forensics.
  WORK_ORDER_EDITED:        "work_order.edited",
  WORK_ORDER_REDISPATCHED:  "work_order.redispatched",

  // Aiden Evaluator Parity Loop (2026-05-11) — explicit operator-accept
  // semantic. The React evaluator UI surfaces "Accept deliverable" as a
  // first-class action; rather than hide it inside a generic
  // `work_order.transitioned`, this event captures the operator's
  // deliberate accept-with-rationale forensically separable from the
  // routine transition vocabulary. Carried by POST
  // /work_orders/{id}/accept (Loop Xi-era recovery path
  // companion). Metadata: from_status, reason (operator rationale).
  WORK_ORDER_ACCEPTED:      "work_order.accepted",

  // Beta-2 phase 0.2 — auto-dispatch worker. Q1=B locked: worker is the
  // sole canonical authority for moving a `pending` WO into `processing`.
  // The worker writes one of these per WO it picks up per tick.
  WORK_ORDER_AUTO_DISPATCH_ATTEMPTED: "work_order.auto_dispatch_attempted",
  WORK_ORDER_AUTO_DISPATCH_SUCCEEDED: "work_order.auto_dispatch_succeeded",
  WORK_ORDER_AUTO_DISPATCH_FAILED: "work_order.auto_dispatch_failed",

  // Beta-2 phase 0.3 — universal llm_configs management surface.
  // Phase 1: load + tri-state mutate + version on every change.
  // Phase 2: history list + rollback. Phase 3: bulk_apply. Phase 4: real preview.
  LLM_CONFIG_PROMPT_READ:    "llm_config.prompt_read",      // GET /llm/configs/{id}/prompt
  LLM_CONFIG_VERSIONED:      "llm_config.versioned",        // every mutation that snapshots a row
  LLM_CONFIG_ROLLED_BACK:    "llm_config.rolled_back",      // rollback action
  LLM_CONFIG_BULK_APPLIED:   "llm_config.bulk_applied",     // batch apply summary (Phase 3)
  LLM_CONFIG_PREVIEWED:      "llm_config.previewed",        // in-memory candidate-prompt invoke (Phase 4)

  // Beta-2 phase 0.4.1 backfill — Aiden Tier 1 tool-call execution. These
  // events were emitted in code (apps/api-fastapi/runtime/aiden_tools.py
  // execute_tool) since 2026-05-01 but never registered in the vocabulary.
  // Loop Eta phase 0 lock catches them up alongside the new Tier 2 events
  // so the full Aiden + sub-agent tool surface is honest in audit.
  AIDEN_TOOL_CALLED: "aiden.tool_called",
  AIDEN_TOOL_FAILED: "aiden.tool_failed",

  // Loop Eta phase 0 — tool catalog lifecycle.
  TOOL_CATALOG_REGISTERED: "tool_catalog.registered",
  TOOL_CATALOG_UPDATED:    "tool_catalog.updated",
  TOOL_CATALOG_DISABLED:   "tool_catalog.disabled",

  // Loop Eta phase 0 — sub-agent tool assignment lifecycle.
  SUB_AGENT_TOOL_GRANTED:  "sub_agent.tool_granted",
  SUB_AGENT_TOOL_REVOKED:  "sub_agent.tool_revoked",

  // Loop Eta phase 0 — Tier 2 tool-call -> execute -> re-invoke loop.
  // Distinct from aiden.tool_* (Tier 1 introspection) so audit forensics
  // can separate orchestrator tool use from sub-agent tool use without
  // parsing metadata.
  SUB_AGENT_TOOL_CALLED:        "sub_agent.tool_called",
  SUB_AGENT_TOOL_FAILED:        "sub_agent.tool_failed",
  SUB_AGENT_TOOL_UNAUTHORIZED:  "sub_agent.tool_unauthorized",
  SUB_AGENT_TOOL_CAP_REACHED:   "sub_agent.tool_cap_reached",

  // Loop Eta phase 0 — MCP session lifecycle. Stitch is the first MCP
  // server but the events are MCP-generic.
  MCP_SESSION_OPENED:    "mcp.session_opened",
  MCP_SESSION_CLOSED:    "mcp.session_closed",
  MCP_CONNECTION_TESTED: "mcp.connection_tested",

  // MegaLoop Theta — Tools Locker write-side events. The `*.updated`
  // and `*.disabled` events from Loop Eta still apply for catalog
  // edits via PUT and the soft-disable toggle; these are the new
  // create/delete/import/test_mcp lifecycle pieces.
  TOOL_CATALOG_CREATED:        "tool_catalog.created",
  TOOL_CATALOG_DELETED:        "tool_catalog.deleted",
  TOOL_CATALOG_SKILL_IMPORTED: "tool_catalog.skill_imported",
  TOOL_CATALOG_MCP_TESTED:     "tool_catalog.mcp_tested",

  // Loop Iota — Memory V1 retrofit. Locked at scope authoring per
  // IWO3_LOOP_IOTA_SCOPE_PROPOSAL §AC + audit vocabulary table.
  // memory.applied — bundle assembled and injected into Tier 1 LLM call
  // memory.bypassed — env or per-tenant kill switch tripped (or empty intake)
  // memory.budget_truncated — at least one source kind dropped to fit budget
  // memory.source_rejected — firewall Layer 4 caught a tenant/owner mismatch.
  //   This is the smoke alarm — should never fire in normal operation
  //   (M-009 in scope risk register; ops runbook treats any non-zero
  //   count as P0).
  MEMORY_APPLIED:          "memory.applied",
  MEMORY_BYPASSED:         "memory.bypassed",
  MEMORY_BUDGET_TRUNCATED: "memory.budget_truncated",
  MEMORY_SOURCE_REJECTED:  "memory.source_rejected",

  // Loop Kappa — Memory V1.5 canonical facts CRUD lifecycle.
  // canonical_facts.created  — POST /canonical_facts succeeds
  // canonical_facts.updated  — PATCH /canonical_facts/{id} succeeds
  // canonical_facts.deleted  — DELETE /canonical_facts/{id} (soft-delete) succeeds
  CANONICAL_FACTS_CREATED: "canonical_facts.created",
  CANONICAL_FACTS_UPDATED: "canonical_facts.updated",
  CANONICAL_FACTS_DELETED: "canonical_facts.deleted",

  // Loop CAP-A Φ.1 — per-tenant brand profile lifecycle.
  // client.brand_profile_created          — first row insert for a tenant
  // client.brand_profile_updated          — any field changed (revision bumps in same tx)
  // client.brand_profile_revision_bumped  — explicit revision-only bump (e.g. cache invalidation)
  CLIENT_BRAND_PROFILE_CREATED:         "client.brand_profile_created",
  CLIENT_BRAND_PROFILE_UPDATED:         "client.brand_profile_updated",
  CLIENT_BRAND_PROFILE_REVISION_BUMPED: "client.brand_profile_revision_bumped",

  // Loop CAP-D Φ.5 — Paul intelligent delivery decision lifecycle.
  // Paul wraps the mechanical adapter call: picks template variant
  // from `client_brand_profiles.template_handles_json[output_kind]`,
  // chooses primary adapter vs fallback chain, applies candidate-
  // review policy, recovers from adapter failure.
  PAUL_DELIVERY_DECIDED:        "paul.delivery_decided",
  PAUL_TEMPLATE_VARIANT_CHOSEN: "paul.template_variant_chosen",
  PAUL_CANDIDATE_SELECTED:      "paul.candidate_selected",
  PAUL_FALLBACK_ADAPTER_INVOKED: "paul.fallback_adapter_invoked",

  // Loop CAP-D Φ.6 — Darla brand QA gate verdicts. Three verdicts
  // (pass | needs_revision | block) map to three distinct events so
  // operators can filter audit history by verdict without parsing
  // metadata. `block` halts publish + opens a revision execution_cycle.
  DARLA_QA_PASSED:          "darla.qa_passed",
  DARLA_QA_NEEDS_REVISION:  "darla.qa_needs_revision",
  DARLA_QA_BLOCKED:         "darla.qa_blocked",
} as const;

export type AuditEvent = (typeof AUDIT_EVENTS)[keyof typeof AUDIT_EVENTS];

export const LOOP_2_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.PROMPT_PROFILE_CREATED,
  AUDIT_EVENTS.PROMPT_PROFILE_VERSION_CREATED,
  AUDIT_EVENTS.PROMPT_PROFILE_VERSION_PUBLISHED,
  AUDIT_EVENTS.PROMPT_PROFILE_VERSION_DEPRECATED,
  AUDIT_EVENTS.PROMPT_OVERRIDE_APPLIED,
  AUDIT_EVENTS.REPOSITORY_BINDING_CREATED,
  AUDIT_EVENTS.REPOSITORY_BINDING_CREDENTIAL_ROTATED,
  AUDIT_EVENTS.REPOSITORY_BINDING_REVOKED,
  AUDIT_EVENTS.DATA_SOURCE_BINDING_CREATED,
  AUDIT_EVENTS.DATA_SOURCE_BINDING_REVOKED,
  AUDIT_EVENTS.ARTIFACT_UPLOADED,
  AUDIT_EVENTS.ARTIFACT_DELETED,
];

export const LOOP_3_PHASE_1_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.WORK_ORDER_CREATED,
  AUDIT_EVENTS.WORK_ORDER_UPDATED,
  AUDIT_EVENTS.WORK_ORDER_ARCHIVED,
  AUDIT_EVENTS.WORKFLOW_CREATED,
  AUDIT_EVENTS.WORKFLOW_UPDATED,
  AUDIT_EVENTS.WORKFLOW_ARCHIVED,
  AUDIT_EVENTS.WORKFLOW_TEMPLATE_CREATED,
  AUDIT_EVENTS.WORKFLOW_TEMPLATE_PUBLISHED,
  AUDIT_EVENTS.WORKFLOW_TEMPLATE_DEPRECATED,
  AUDIT_EVENTS.WORKFLOW_EXECUTION_STARTED,
  AUDIT_EVENTS.WORKFLOW_EXECUTION_COMPLETED,
  AUDIT_EVENTS.WORKFLOW_STEP_RUN_COMPLETED,
  AUDIT_EVENTS.EXECUTION_CYCLE_STARTED,
];

export const LOOP_3_PHASE_4_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.ADAPTER_DISPATCH_INITIATED,
  AUDIT_EVENTS.ADAPTER_DISPATCH_POLICY_REJECTED,
  AUDIT_EVENTS.ADAPTER_DISPATCH_APPROVAL_REQUIRED,
  AUDIT_EVENTS.ADAPTER_DISPATCH_PACKAGE_INVALID,
  AUDIT_EVENTS.ADAPTER_DISPATCH_SUBMITTED,
  AUDIT_EVENTS.ADAPTER_DISPATCH_COMPLETED,
  AUDIT_EVENTS.ADAPTER_DISPATCH_FAILED,
];

export const LOOP_3_PHASE_2_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.OUTPUT_PACKAGE_CREATED,
  AUDIT_EVENTS.OUTPUT_PACKAGE_VALIDATED,
  AUDIT_EVENTS.OUTPUT_PACKAGE_SUBMITTED,
  AUDIT_EVENTS.OUTPUT_PACKAGE_REJECTED,
  AUDIT_EVENTS.OUTPUT_HANDOFF_CREATED,
  AUDIT_EVENTS.OUTPUT_HANDOFF_SUBMITTED,
  AUDIT_EVENTS.OUTPUT_HANDOFF_COMPLETED,
  AUDIT_EVENTS.OUTPUT_HANDOFF_FAILED,
  AUDIT_EVENTS.OUTPUT_CANDIDATE_SELECTED,
  AUDIT_EVENTS.OUTPUT_CANDIDATE_REJECTED,
  AUDIT_EVENTS.ADAPTER_CONFIG_CREATED,
  AUDIT_EVENTS.ADAPTER_CONFIG_UPDATED,
  AUDIT_EVENTS.ADAPTER_CONFIG_ENABLED,
  AUDIT_EVENTS.ADAPTER_CONFIG_DISABLED,
  AUDIT_EVENTS.ADAPTER_CREDENTIAL_ROTATED,
  AUDIT_EVENTS.ADAPTER_CREDENTIAL_REVOKED,
  AUDIT_EVENTS.ADAPTER_POLICY_CREATED,
  AUDIT_EVENTS.ADAPTER_POLICY_UPDATED,
];

export const LOOP_4_PHASE_1_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.PERMISSION_CREATED,
  AUDIT_EVENTS.ROLE_PERMISSION_GRANTED,
  AUDIT_EVENTS.ROLE_PERMISSION_REVOKED,
  AUDIT_EVENTS.PERMISSION_GRANT_CREATED,
  AUDIT_EVENTS.PERMISSION_GRANT_REVOKED,
];

export const LOOP_4_PHASE_2_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.AUTHZ_DENIED,
];

export const LOOP_6_PHASE_1_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.WORK_ORDER_TRANSITIONED,
  AUDIT_EVENTS.WORK_ORDER_REOPENED,
  AUDIT_EVENTS.WORK_ORDER_CANCELLED,
  AUDIT_EVENTS.WORK_ORDER_BLOCKED,
  AUDIT_EVENTS.WORK_ORDER_UNBLOCKED,
  AUDIT_EVENTS.WORK_ORDER_WATCHDOG_EXPIRED,
  AUDIT_EVENTS.WORKFLOW_TRANSITIONED,
  AUDIT_EVENTS.WORKFLOW_PAUSED,
  AUDIT_EVENTS.WORKFLOW_RESUMED,
  AUDIT_EVENTS.WORKFLOW_EXECUTION_TRANSITIONED,
  AUDIT_EVENTS.WORKFLOW_EXECUTION_CANCELLED,
  AUDIT_EVENTS.WORKFLOW_STEP_RUN_TRANSITIONED,
];

export const LOOP_9_PHASE_1_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.ADAPTER_CREDENTIAL_FIRST_INVOCATION_CONFIRMED,
  AUDIT_EVENTS.ADAPTER_DISPATCH_LIVE_DISABLED,
  AUDIT_EVENTS.ADAPTER_DISPATCH_CREDENTIAL_MISSING,
  AUDIT_EVENTS.ADAPTER_DISPATCH_FIRST_INVOCATION_PENDING,
];

export const LOOP_9_PHASE_2_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.ADAPTER_DISPATCH_CREDENTIAL_INVALID,
  AUDIT_EVENTS.ADAPTER_DISPATCH_RATE_LIMITED,
];

export const LOOP_9_PHASE_3_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.LLM_INVOKED,
  AUDIT_EVENTS.LLM_FAILED,
  AUDIT_EVENTS.LLM_PROVIDER_CONNECTION_TESTED,
];

export const LOOP_9_PHASE_4_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.ADAPTER_DISPATCH_POLLING,
  AUDIT_EVENTS.ADAPTER_DISPATCH_WATCHDOG_EXPIRED_STALE_POLL,
];

export const ALPHA_PHASE_A2_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.LLM_BUDGET_EXCEEDED,
];

export const ALPHA_PHASE_A5_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.CHANNEL_AUTH_CODE_ISSUED,
  AUDIT_EVENTS.CHANNEL_IDENTITY_BOUND,
  AUDIT_EVENTS.CHANNEL_IDENTITY_REVOKED,
  AUDIT_EVENTS.CHANNEL_MESSAGE_RECEIVED,
  AUDIT_EVENTS.CHANNEL_MESSAGE_PROCESSED,
  AUDIT_EVENTS.CHANNEL_MESSAGE_FAILED,
  AUDIT_EVENTS.CHANNEL_MESSAGE_SEND_QUEUED,
  AUDIT_EVENTS.CHANNEL_MESSAGE_SENT,
];

export const PRE_BETA_PHASE_2_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.LLM_CONFIG_CREATED,
  AUDIT_EVENTS.LLM_CONFIG_UPDATED,
  AUDIT_EVENTS.LLM_CONFIG_DISABLED,
];

export const PRE_BETA_PHASE_DELTA_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.WORKSPACE_FOLDER_CREATED,
  AUDIT_EVENTS.WORKSPACE_FOLDER_RENAMED,
  AUDIT_EVENTS.WORKSPACE_FOLDER_MOVED,
  AUDIT_EVENTS.WORKSPACE_FOLDER_DELETED,
  AUDIT_EVENTS.WORKSPACE_FILE_CREATED,
  AUDIT_EVENTS.WORKSPACE_FILE_RENAMED,
  AUDIT_EVENTS.WORKSPACE_FILE_MOVED,
  AUDIT_EVENTS.WORKSPACE_FILE_DELETED,
  AUDIT_EVENTS.WORKSPACE_FILE_SAVED_FROM_OUTPUT,
];

export const BETA_PHASE_1_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.AUTH_SESSION_STARTED,
  AUDIT_EVENTS.AUTH_SESSION_REFRESHED,
  AUDIT_EVENTS.AUTH_SESSION_ENDED,
  AUDIT_EVENTS.AUTH_LOGIN_FAILED,
  AUDIT_EVENTS.CREDENTIAL_ENCRYPTED,
  AUDIT_EVENTS.CREDENTIAL_ROTATED,
  AUDIT_EVENTS.CHAT_SESSION_UPDATED,
  AUDIT_EVENTS.WEBHOOK_RECEIVED,
  AUDIT_EVENTS.WEBHOOK_SIGNATURE_INVALID,
];

export const BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.CLIENT_SETTINGS_UPDATED,
];

export const BETA_2_PHASE_0_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.WORK_ORDER_REQUESTED_OUTPUTS_SET,
  AUDIT_EVENTS.TIER_1_5_REQUESTED_OUTPUT_HONORED,
  AUDIT_EVENTS.WORK_ORDER_AUTO_DISPATCH_ATTEMPTED,
  AUDIT_EVENTS.WORK_ORDER_AUTO_DISPATCH_SUCCEEDED,
  AUDIT_EVENTS.WORK_ORDER_AUTO_DISPATCH_FAILED,
];

export const BETA_2_PHASE_0_3_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.LLM_CONFIG_PROMPT_READ,
  AUDIT_EVENTS.LLM_CONFIG_VERSIONED,
  AUDIT_EVENTS.LLM_CONFIG_ROLLED_BACK,
  AUDIT_EVENTS.LLM_CONFIG_BULK_APPLIED,
  AUDIT_EVENTS.LLM_CONFIG_PREVIEWED,
];

// Beta-2 phase 0.4.1 — backfill of Aiden Tier 1 tool-call events that
// the runtime has been emitting since 2026-05-01 without a vocabulary lock.
export const BETA_2_PHASE_0_4_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.AIDEN_TOOL_CALLED,
  AUDIT_EVENTS.AIDEN_TOOL_FAILED,
];

// Loop Eta phase 0 — tool catalog, sub-agent tool assignment, Tier 2 tool
// execution, MCP session lifecycle. Twelve events locked at phase start
// per IWO3_LOOP_ETA_SCOPE_PROPOSAL §7.
export const LOOP_ETA_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.TOOL_CATALOG_REGISTERED,
  AUDIT_EVENTS.TOOL_CATALOG_UPDATED,
  AUDIT_EVENTS.TOOL_CATALOG_DISABLED,
  AUDIT_EVENTS.SUB_AGENT_TOOL_GRANTED,
  AUDIT_EVENTS.SUB_AGENT_TOOL_REVOKED,
  AUDIT_EVENTS.SUB_AGENT_TOOL_CALLED,
  AUDIT_EVENTS.SUB_AGENT_TOOL_FAILED,
  AUDIT_EVENTS.SUB_AGENT_TOOL_UNAUTHORIZED,
  AUDIT_EVENTS.SUB_AGENT_TOOL_CAP_REACHED,
  AUDIT_EVENTS.MCP_SESSION_OPENED,
  AUDIT_EVENTS.MCP_SESSION_CLOSED,
  AUDIT_EVENTS.MCP_CONNECTION_TESTED,
];

// MegaLoop Theta — Tools Locker write-side. Operator CRUD on the global
// catalog plus filesystem skill import + ad-hoc MCP test. The Loop Eta
// `tool_catalog.updated` and `tool_catalog.disabled` events still apply
// for PUT edits and the enabled-toggle path; these four are the
// genuinely new lifecycle pieces.
export const LOOP_THETA_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.TOOL_CATALOG_CREATED,
  AUDIT_EVENTS.TOOL_CATALOG_DELETED,
  AUDIT_EVENTS.TOOL_CATALOG_SKILL_IMPORTED,
  AUDIT_EVENTS.TOOL_CATALOG_MCP_TESTED,
];

// Loop Iota — Memory V1 retrofit. Four events locked at scope authoring
// per IWO3_LOOP_IOTA_SCOPE_PROPOSAL_v0.1.0.md §"Audit vocabulary".
//
// `memory.applied` is the success path emitted exactly once per chat
// HTTP request (acceptance criterion #17 — tool-call re-invokes do NOT
// re-run the assembler). The other three are exception paths:
//   bypassed → kill switch / no sources / very short intake
//   budget_truncated → at least one source kind dropped to fit 2K tokens
//   source_rejected → firewall caught a tenant/owner mismatch; SHOULD
//                     NEVER FIRE in production. M-009 watchlist item.
export const LOOP_IOTA_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.MEMORY_APPLIED,
  AUDIT_EVENTS.MEMORY_BYPASSED,
  AUDIT_EVENTS.MEMORY_BUDGET_TRUNCATED,
  AUDIT_EVENTS.MEMORY_SOURCE_REJECTED,
];

// Loop Kappa — Memory V1.5 operational maturity. Three events for
// canonical_facts CRUD lifecycle (D-K2 hybrid table-driven path).
// `delete` is soft-delete (is_active=false) — preserves audit lineage.
export const LOOP_KAPPA_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.CANONICAL_FACTS_CREATED,
  AUDIT_EVENTS.CANONICAL_FACTS_UPDATED,
  AUDIT_EVENTS.CANONICAL_FACTS_DELETED,
];

// Loop Xi — operator recovery loop (reopen + edit + redispatch). Skips
// Nu (reserved for V3.5 KG augmentation per memory roadmap). The
// canonical reopen event `work_order.reopened` lives in the WO
// transition vocabulary above; this loop adds two new events for the
// inline-edit and redispatch operator surfaces.
export const LOOP_XI_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.WORK_ORDER_EDITED,
  AUDIT_EVENTS.WORK_ORDER_REDISPATCHED,
];

// Aiden Evaluator Parity Loop (2026-05-11) — explicit operator-accept
// route + unified evaluator_summary read endpoint. Only `accepted`
// adds to the audit vocabulary; the read endpoint emits nothing.
export const LOOP_AEP_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.WORK_ORDER_ACCEPTED,
];

// Loop CAP-A Φ.1 — per-tenant brand profile lifecycle. Three events
// for the create / update / revision-bump cycle. CRUD endpoints land
// in a later CAP loop (Φ.5 / Φ.6 may surface read; explicit operator
// CRUD is a follow-on UI loop). These event names are locked here so
// downstream code can emit them without per-loop vocabulary churn.
export const LOOP_CAP_A_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.CLIENT_BRAND_PROFILE_CREATED,
  AUDIT_EVENTS.CLIENT_BRAND_PROFILE_UPDATED,
  AUDIT_EVENTS.CLIENT_BRAND_PROFILE_REVISION_BUMPED,
];

// Loop CAP-D Φ.5 — Paul intelligent delivery audit vocabulary.
// One `paul.delivery_decided` per chain `deliver` step + per direct
// dispatch path that routes through Paul. The other three are
// branch-specific: variant_chosen when multi-template tenants
// disambiguate; candidate_selected when policy=candidate_review;
// fallback_adapter_invoked when primary adapter fails or is gated
// by missing credentials.
export const LOOP_CAP_D_PHI5_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.PAUL_DELIVERY_DECIDED,
  AUDIT_EVENTS.PAUL_TEMPLATE_VARIANT_CHOSEN,
  AUDIT_EVENTS.PAUL_CANDIDATE_SELECTED,
  AUDIT_EVENTS.PAUL_FALLBACK_ADAPTER_INVOKED,
];

// Loop CAP-D Φ.6 — Darla brand QA gate audit vocabulary. Three
// distinct events (one per verdict) so operators can filter audit
// history by verdict without parsing metadata. `block` halts publish
// and opens a revision execution_cycle.
export const LOOP_CAP_D_PHI6_AUDIT_EVENTS: readonly AuditEvent[] = [
  AUDIT_EVENTS.DARLA_QA_PASSED,
  AUDIT_EVENTS.DARLA_QA_NEEDS_REVISION,
  AUDIT_EVENTS.DARLA_QA_BLOCKED,
];

// Loop Eta phase 0 — prompt provenance vocabulary. One value per llm_configs
// row, persisted in `metadata.prompt_provenance` jsonb field. Carried in
// `llm_config_versions.change_reason` on the v1 snapshot for forensic
// reconstruction. Locked here so contract tests can assert the four-value
// vocabulary upfront without relying on row inspection.
export const LOOP_ETA_PROMPT_PROVENANCE = {
  EXTRACTED_FROM_IWO2_LIVE: "extracted_from_iwo2_live",
  EXTRACTED_FROM_IWO2_STATIC: "extracted_from_iwo2_static",
  AUTHORED_PARITY_APPROXIMATION: "authored_parity_approximation",
  AUTHORED_NET_NEW: "authored_net_new",
} as const;

export type LoopEtaPromptProvenance =
  (typeof LOOP_ETA_PROMPT_PROVENANCE)[keyof typeof LOOP_ETA_PROMPT_PROVENANCE];
