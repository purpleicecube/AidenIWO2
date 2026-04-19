/**
 * Loop 3 Phase 3 — DigiFLOW intake contract (TypeScript canonical).
 *
 * Per IWO3_LOOP_3_APPROVAL_DECISIONS §Q4 (`contract_only`): this ships the
 * type + validator only. The FastAPI endpoint that consumes these packets
 * opens in Loop 7. The Python mirror at `apps/api-fastapi/digiflow/intake.py`
 * reproduces every field and every validation rule; the parity contract test
 * (`tests/contract/digiflow-routing-parity.test.ts`) enforces the match.
 *
 * Field shape is the CODEX response-packet §2 DigiFlowIntakePacket design.
 * Nothing here is adapter-specific; routing decisions (WO vs WF) live in
 * `./routing.ts`.
 */

import { z } from "zod";

// ──────────────────────────────────────────────────────────────────────
// Subschemas
// ──────────────────────────────────────────────────────────────────────

export const DigiFlowIntakeRequesterSchema = z.object({
  kind: z.enum(["user", "service"]),
  id: z.string().optional(),
  email: z.string().email().optional(),
  display_name: z.string().optional(),
});

const credentialRefOrNull = z
  .union([z.string().startsWith("credential_ref:"), z.null()])
  .describe(
    "credential-shaped values MUST be a `credential_ref:` placeholder or null"
  );

export const DigiFlowIntakeAssetSchema = z.object({
  id: z.string(),
  name: z.string().optional(),
  source_ref: z.string().optional(),
  credential_ref: credentialRefOrNull.optional(),
  metadata: z.record(z.unknown()).optional(),
});

export const DigiFlowIntakeRecurrenceKindEnum = z.enum([
  "once",
  "daily",
  "weekly",
  "monthly",
  "quarterly",
  "custom",
]);

export const DigiFlowIntakeRecurrenceSchema = z
  .object({
    kind: DigiFlowIntakeRecurrenceKindEnum,
    frequency: z.string().optional(),
    until: z.string().datetime().optional(),
  })
  .refine(
    (r) => r.kind !== "custom" || (r.frequency && r.frequency.length > 0),
    {
      message:
        "recurrence.frequency is required when recurrence.kind = 'custom'",
    }
  );

export const DigiFlowDesiredOutputSchema = z.object({
  output_kind: z.string().min(1),
  template_profile_key: z.string().optional(),
  destination_adapter_key: z.string().optional(),
  metadata: z.record(z.unknown()).optional(),
});

// ──────────────────────────────────────────────────────────────────────
// Packet
// ──────────────────────────────────────────────────────────────────────

export const DigiFlowIntakePacketSchema = z
  .object({
    id: z.string().min(1),
    schema_version: z.literal("v0"),
    source_system: z.literal("digiflow"),
    source_ref: z.string().optional(),
    client_designation: z.string().optional(),
    client_id: z.string().uuid().optional(),
    requester: DigiFlowIntakeRequesterSchema,
    intake_type: z.string().default("content"),
    requested_execution_mode: z
      .enum(["wo", "wf", "auto"])
      .default("auto"),
    title: z.string().min(1),
    objective: z.string().min(1),
    business_context: z.string().optional(),
    campaign_or_project_goal: z.string().optional(),
    audience: z.string().optional(),
    offer_or_message_strategy: z.string().optional(),
    desired_outputs: z.array(DigiFlowDesiredOutputSchema).min(1),
    destination_preferences: z.array(z.string()).optional(),
    assets: z.array(DigiFlowIntakeAssetSchema).optional(),
    constraints: z.record(z.unknown()).optional(),
    compliance_notes: z.string().optional(),
    due_at: z.string().datetime().optional(),
    recurrence: DigiFlowIntakeRecurrenceSchema.optional(),
    approval_preferences: z.record(z.unknown()).optional(),
    priority: z.enum(["low", "medium", "high", "critical"]).default("medium"),
    correlation_id: z.string().optional(),
  })
  .refine((p) => !!p.client_designation || !!p.client_id, {
    message: "either client_designation or client_id must be present",
  });

export type DigiFlowIntakePacket = z.infer<typeof DigiFlowIntakePacketSchema>;

// ──────────────────────────────────────────────────────────────────────
// Validator
// ──────────────────────────────────────────────────────────────────────

export type ValidateResult =
  | { valid: true; packet: DigiFlowIntakePacket }
  | { valid: false; errors: string[] };

export function validateIntakePacket(raw: unknown): ValidateResult {
  const result = DigiFlowIntakePacketSchema.safeParse(raw);
  if (result.success) {
    return { valid: true, packet: result.data };
  }
  return {
    valid: false,
    errors: result.error.issues.map((i) => {
      const path = i.path.length > 0 ? i.path.join(".") : "<root>";
      return `${path}: ${i.message}`;
    }),
  };
}
