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
