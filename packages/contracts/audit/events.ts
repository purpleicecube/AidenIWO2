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
} as const;

export type AuditEvent = (typeof AUDIT_EVENTS)[keyof typeof AUDIT_EVENTS];

export const LOOP_2_AUDIT_EVENTS: readonly AuditEvent[] = Object.values(
  AUDIT_EVENTS
);
