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
