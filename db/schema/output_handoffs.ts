import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  timestamp,
  integer,
  pgEnum,
  index,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { users } from "./users";
import { workOrders } from "./work_orders";
import { workflows } from "./workflows";
import { executionCycles } from "./execution_cycles";
import { outputPackages } from "./output_packages";
import { adapterCatalog } from "./adapter_catalog";
import { templateProfiles } from "./template_profiles";

export const outputHandoffStatusEnum = pgEnum("output_handoff_status", [
  "queued",
  "submitted",
  "accepted",
  "completed",
  "failed",
  "cancelled",
]);

/**
 * Candidate-review minimal shape (hybrid decision per
 * IWO3_LOOP_3_APPROVAL_DECISIONS §Q5).
 *
 * `not_candidate` = standard non-candidate handoff.
 * `candidate` = one of N candidates produced for operator review.
 * `selected` = the candidate the operator picked.
 * `rejected` = candidate the operator rejected.
 * `finalized` = selected candidate after any downstream finalization.
 *
 * Loop 6 adds the operator-facing request-more / reject-all / cancel
 * behavior on top of these fields.
 */
export const outputHandoffCandidateStatusEnum = pgEnum(
  "output_handoff_candidate_status",
  ["not_candidate", "candidate", "selected", "rejected", "finalized"]
);

/**
 * OutputHandoff — 13-field provenance record per CODEX §5 plus the
 * Phase 3.2 candidate-review minimal shape per approval memo §Q5.
 *
 * Every adapter invocation writes one row. The 13 provenance fields
 * ensure any future audit ("how did this artifact get delivered?") can
 * be answered without reconstructing state from adapter logs.
 *
 *   client_id, deployment_id, work_order_id, workflow_id,
 *   execution_cycle_id, output_package_id, adapter_id,
 *   template_profile_id, external_destination, external_reference,
 *   status, handoff_payload_ref, result_payload_ref, correlation_id
 */
export const outputHandoffs = pgTable(
  "output_handoffs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "restrict" }),
    deploymentId: uuid("deployment_id"),
    workOrderId: uuid("work_order_id").references(() => workOrders.id, {
      onDelete: "set null",
    }),
    workflowId: uuid("workflow_id").references(() => workflows.id, {
      onDelete: "set null",
    }),
    executionCycleId: uuid("execution_cycle_id").references(
      () => executionCycles.id,
      { onDelete: "set null" }
    ),
    outputPackageId: uuid("output_package_id").references(
      () => outputPackages.id,
      { onDelete: "set null" }
    ),
    adapterCatalogId: uuid("adapter_catalog_id").references(
      () => adapterCatalog.id,
      { onDelete: "set null" }
    ),
    templateProfileId: uuid("template_profile_id").references(
      () => templateProfiles.id,
      { onDelete: "set null" }
    ),
    externalDestination: varchar("external_destination", { length: 256 }),
    externalReference: varchar("external_reference", { length: 256 }),
    status: outputHandoffStatusEnum("status").notNull().default("queued"),
    handoffPayloadRef: varchar("handoff_payload_ref", { length: 1024 }),
    resultPayloadRef: varchar("result_payload_ref", { length: 1024 }),
    correlationId: varchar("correlation_id", { length: 128 }),
    // Candidate-review minimal shape (hybrid per §Q5)
    candidateGroupId: uuid("candidate_group_id"),
    candidateStatus: outputHandoffCandidateStatusEnum("candidate_status")
      .notNull()
      .default("not_candidate"),
    selectedAt: timestamp("selected_at", { withTimezone: true }),
    selectedByUserId: uuid("selected_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    // Loop 9 Phase 9.4 — async polling state.
    // WO stays in `processing` while the adapter is legitimately
    // rendering. These columns track per-handoff poll cadence so the
    // watchdog can distinguish "healthy long render" from "stale poll"
    // (Darrel §Q3 disambiguation + IWO3_LOOP_9_SCOPE_PROPOSAL §3.4).
    //
    //   last_poll_status  "pending" | "running" | "completed" | "failed"
    //                     (null before first poll)
    //   last_poll_at      timestamp of most recent poll
    //   poll_count        monotonic counter; 0 before first poll
    lastPollStatus: varchar("last_poll_status", { length: 32 }),
    lastPollAt: timestamp("last_poll_at", { withTimezone: true }),
    pollCount: integer("poll_count").notNull().default(0),
    metadata: jsonb("metadata"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    idxClientStatusCreated: index("output_handoffs_client_status_created_idx").on(
      t.clientId,
      t.status,
      t.createdAt
    ),
    idxCandidateGroup: index("output_handoffs_candidate_group_idx").on(
      t.candidateGroupId
    ),
  })
);

export type OutputHandoff = typeof outputHandoffs.$inferSelect;
export type NewOutputHandoff = typeof outputHandoffs.$inferInsert;
