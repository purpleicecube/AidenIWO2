import {
  pgTable,
  uuid,
  varchar,
  jsonb,
  text,
  timestamp,
  pgEnum,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";
import { adapterCatalog } from "./adapter_catalog";
import { users } from "./users";

export const adapterCredentialStatusEnum = pgEnum(
  "adapter_credential_status",
  ["active", "rotation_due", "revoked", "expired"]
);

/**
 * Per-tenant, per-adapter credential reference. NEVER stores raw secret
 * material. `credential_ref` points at a secret-manager entry (e.g.
 * `credential_ref:env:GAMMA_API_KEY_KLEAR`) or a `credential_ref:dev-local-*`
 * placeholder in dev. Rotation cadence is tracked by `rotation_due_at`
 * (next scheduled) and `rotated_at` (last completed).
 *
 * Loop 9 Phase 9.1 additions (dual first-live-invocation gate, per
 * IWO3_LOOP_8_3_CODEX_DECISIONS §Q1):
 *   - `first_invocation_confirmed_at` — operator-supplied timestamp that
 *     unlocks live dispatch for this credential. Nullable by design;
 *     `NULL` blocks `dispatch_gating.decideLiveGate` with
 *     `first_invocation_pending`.
 *   - `first_invocation_confirmed_by_user_id` — which admin confirmed.
 *   - `rotated_at` — last rotation timestamp (distinct from
 *     `rotation_due_at`, which is the next scheduled deadline).
 *   - `notes` — free-form operator notes. Not a secret store.
 */
export const adapterCredentials = pgTable("adapter_credentials", {
  id: uuid("id").primaryKey().defaultRandom(),
  clientId: uuid("client_id")
    .notNull()
    .references(() => clients.id, { onDelete: "restrict" }),
  adapterCatalogId: uuid("adapter_catalog_id")
    .notNull()
    .references(() => adapterCatalog.id, { onDelete: "restrict" }),
  credentialRef: varchar("credential_ref", { length: 256 }).notNull(),
  scope: jsonb("scope"),
  rotationDueAt: timestamp("rotation_due_at", { withTimezone: true }),
  status: adapterCredentialStatusEnum("status").notNull().default("active"),
  metadata: jsonb("metadata"),
  firstInvocationConfirmedAt: timestamp("first_invocation_confirmed_at", {
    withTimezone: true,
  }),
  firstInvocationConfirmedByUserId: uuid(
    "first_invocation_confirmed_by_user_id"
  ).references(() => users.id, { onDelete: "set null" }),
  rotatedAt: timestamp("rotated_at", { withTimezone: true }),
  notes: text("notes"),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type AdapterCredential = typeof adapterCredentials.$inferSelect;
export type NewAdapterCredential = typeof adapterCredentials.$inferInsert;
