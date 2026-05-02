import {
  pgTable,
  uuid,
  varchar,
  text,
  jsonb,
  boolean,
  timestamp,
  unique,
} from "drizzle-orm/pg-core";
import { clients } from "./clients";

/**
 * Loop 9 Phase 9.3 — per-tenant LLM configuration keyed on a string
 * `role`. The IWO2 lineage's "global LlmSettings + per-sub-agent
 * override" pattern reshapes to a multi-tenant table where each row
 * is one (client, role) binding. Resolution at call time:
 *
 *   prompt_profile.llm_*  (when set, highest priority)
 *   ↓ falls through to
 *   llm_configs (client_id, agent_role)              ← this table
 *   ↓ falls through to
 *   llm_configs (client_id, "aiden_tier_1")          ← tenant default
 *   ↓ falls through to
 *   429 / no_llm_configured                          ← fail-closed
 *
 * Raw API keys are NEVER stored here. `credential_ref` follows the
 * same `credential_ref:env:NAME` discipline as `adapter_credentials`
 * (IWO3_LOOP_8_3_CODEX_DECISIONS §Q2).
 *
 * Provider values mirror IWO2's lineup (`server/llm-client.ts`):
 *   "groq", "openrouter", "openai", "anthropic"
 * Phase 9.3 ships with `groq` + `openrouter` enabled. Anthropic stays
 * as a known value for forward-compat without a Phase 9.3 client.
 */
export const llmConfigs = pgTable(
  "llm_configs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    clientId: uuid("client_id")
      .notNull()
      .references(() => clients.id, { onDelete: "cascade" }),
    /**
     * Free-form role key. Convention:
     *   "aiden_tier_1"         tenant Aiden default (mandatory; this row
     *                          is the fallback every other resolution
     *                          eventually hits)
     *   "pm_tier_15"           Tier 1.5 PM coordinator
     *   "mark_tier_2"          Tier 2 sub-agent named Mark (content)
     *   "tom_tier_2"           Tier 2 sub-agent (Tom, decks)
     *   "hank_tier_2"          Tier 2 sub-agent (Hank, web builds)
     *   "paul_tier_2"          Tier 2 sub-agent (Paul, deployment)
     */
    agentRole: varchar("agent_role", { length: 64 }).notNull(),
    /**
     * Pre-Beta β.1 — sub-agent metadata model v1.
     * Browser-facing display name (defaults to a humanised form of
     * `agent_role` at insert time when omitted by the operator).
     */
    displayName: varchar("display_name", { length: 160 }).notNull(),
    /** Optional one-paragraph description shown in the operator console. */
    description: text("description"),
    provider: varchar("provider", { length: 32 }).notNull(),
    model: varchar("model", { length: 128 }).notNull(),
    /** Override default provider base URL (e.g. self-hosted vLLM). */
    baseUrl: varchar("base_url", { length: 256 }),
    credentialRef: varchar("credential_ref", { length: 256 }).notNull(),
    systemPrompt: text("system_prompt"),
    /** Provider-specific knobs: temperature, max_tokens, top_p, ... */
    options: jsonb("options"),
    /**
     * Loop Eta — per-row metadata. First consumer:
     *   metadata.prompt_provenance ∈
     *     'extracted_from_iwo2_live' | 'extracted_from_iwo2_static' |
     *     'authored_parity_approximation' | 'authored_net_new'
     * carries IWO2-parity provenance per IWO3_LOOP_ETA_SCOPE_PROPOSAL §1.
     */
    metadata: jsonb("metadata"),
    enabled: boolean("enabled").notNull().default(true),
    notes: text("notes"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (t) => ({
    uniqClientRole: unique("llm_configs_client_role_uniq").on(
      t.clientId,
      t.agentRole
    ),
  })
);

export type LlmConfig = typeof llmConfigs.$inferSelect;
export type NewLlmConfig = typeof llmConfigs.$inferInsert;
