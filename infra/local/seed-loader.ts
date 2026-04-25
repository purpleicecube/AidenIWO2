/**
 * Loads durable seed data into IWO3.
 *
 * Loop 1 (foundation): clients, users, client_memberships, template_profiles.
 * Loop 2 (multi-client data): prompt_profiles, prompt_profile_versions,
 *          repository_bindings, data_source_bindings, artifacts.
 *
 * Idempotent via ON CONFLICT DO UPDATE. Deterministic: UUIDs are fixed in the
 * seed JSON, so re-running produces the same database state.
 *
 * Writes a receipt to infra/local/last-seed.json.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Pool, type PoolClient } from "pg";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = resolve(__dirname, "..", "..");

function loadJson<T>(relpath: string): T {
  const p = resolve(REPO_ROOT, relpath);
  const raw = readFileSync(p, "utf-8");
  return JSON.parse(raw) as T;
}

// ──────────────────────────────────────────────────────────────────────────
// Loop 1 — foundation shapes
// ──────────────────────────────────────────────────────────────────────────

interface SeedClient {
  id: string;
  designation: string;
  displayName: string;
  deploymentMode: string;
  status: string;
}

interface SeedUser {
  id: string;
  email: string;
  displayName: string;
  status: string;
}

interface SeedMembership {
  clientId: string;
  userId: string;
  role: string;
  status: string;
}

interface SeedTemplateProfile {
  id: string;
  clientId: string;
  profileKey: string;
  outputKind: string;
  engine: string;
  externalRef: string | null;
  fidelityRequired: boolean;
  fallbackPolicy: string;
  contentContract: unknown;
  status: string;
}

// ──────────────────────────────────────────────────────────────────────────
// Loop 2 — multi-client data shapes
// ──────────────────────────────────────────────────────────────────────────

interface SeedPromptProfile {
  id: string;
  clientId: string;
  profileKey: string;
  displayName: string;
  scope: string;
  status: string;
}

interface SeedPromptProfileVersion {
  id: string;
  profileId: string;
  version: string;
  basePrompt: string;
  constraints: unknown;
  authoredByUserId: string;
  status: string;
  publishedAt: string | null;
}

interface SeedRepositoryBinding {
  id: string;
  clientId: string;
  bindingKey: string;
  connectorType: string;
  scope: unknown;
  credentialRef: string | null;
  allowedLocations: unknown;
  freshnessPolicy: unknown;
  status: string;
}

interface SeedDataSourceBinding {
  id: string;
  clientId: string;
  bindingKey: string;
  connectorType: string;
  scope: unknown;
  credentialRef: string | null;
  allowedLocations: unknown;
  freshnessPolicy: unknown;
  status: string;
}

interface SeedArtifact {
  id: string;
  clientId: string;
  sourceType: string;
  contentClass: string;
  mimeType: string | null;
  filename: string | null;
  storageRef: string;
  extractedText: string | null;
  metadata: unknown;
  createdByUserId: string;
}

// ──────────────────────────────────────────────────────────────────────────
// Loop 3 Phase 1 — WO / WF / execution_cycles shapes
// ──────────────────────────────────────────────────────────────────────────

interface SeedWorkOrder {
  id: string;
  clientId: string;
  title: string;
  description: string | null;
  type: string;
  priority: string;
  status: string;
  submittedByUserId: string | null;
  correlationId: string | null;
  gccMemory: unknown;
  deferredUntil: string | null;
  deferredReason: string | null;
}

interface SeedWorkflow {
  id: string;
  clientId: string;
  key: string;
  displayName: string;
  description: string | null;
  status: string;
}

interface SeedWorkflowTemplate {
  id: string;
  workflowId: string;
  version: string;
  description: string | null;
  config: unknown;
  status: string;
  publishedAt: string | null;
}

interface SeedWorkflowTemplateStep {
  id: string;
  templateId: string;
  stepKey: string;
  stepOrder: number;
  displayName: string;
  assignedSubAgentKey: string | null;
  promptRef: unknown;
  retryPolicy: unknown;
  timeoutMs: number | null;
  toolIds: unknown;
}

// ──────────────────────────────────────────────────────────────────────────
// Loop 3 Phase 2 — adapter registry shapes
// ──────────────────────────────────────────────────────────────────────────

interface SeedAdapterCatalog {
  id: string;
  adapterKey: string;
  displayName: string;
  category: string;
  description: string | null;
  contractVersion: string;
  status: string;
}

interface SeedAdapterAction {
  id: string;
  adapterCatalogId: string;
  actionKey: string;
  displayName: string;
  description: string | null;
  requiresOutputPackage: boolean;
}

interface SeedClientAdapterConfig {
  id: string;
  clientId: string;
  adapterCatalogId: string;
  enabled: boolean;
  credentialRef: string | null;
  config: unknown;
  status: string;
}

interface SeedAdapterActionPolicy {
  id: string;
  clientId: string;
  adapterCatalogId: string;
  actionKey: string;
  mode: string;
  reason: string | null;
  metadata: unknown;
}

// ──────────────────────────────────────────────────────────────────────────
// Loop 4 Phase 1 — RBAC vocabulary + role defaults shapes
// ──────────────────────────────────────────────────────────────────────────

interface SeedPermission {
  id: string;
  permissionKey: string;
  displayName: string;
  description: string | null;
  scope: string;
}

interface SeedRolePermission {
  role: string;
  permissionKey: string;
}

// ──────────────────────────────────────────────────────────────────────────
// Upsert helpers — Loop 1
// ──────────────────────────────────────────────────────────────────────────

async function upsertClients(c: PoolClient, rows: SeedClient[]): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO clients (id, designation, display_name, deployment_mode, status)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (id) DO UPDATE SET
         designation = EXCLUDED.designation,
         display_name = EXCLUDED.display_name,
         deployment_mode = EXCLUDED.deployment_mode,
         status = EXCLUDED.status,
         updated_at = now()`,
      [r.id, r.designation, r.displayName, r.deploymentMode, r.status]
    );
  }
}

async function upsertUsers(c: PoolClient, rows: SeedUser[]): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO users (id, email, display_name, status)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (id) DO UPDATE SET
         email = EXCLUDED.email,
         display_name = EXCLUDED.display_name,
         status = EXCLUDED.status,
         updated_at = now()`,
      [r.id, r.email, r.displayName, r.status]
    );
  }
}

async function upsertMemberships(
  c: PoolClient,
  rows: SeedMembership[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO client_memberships (client_id, user_id, role, status)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT ON CONSTRAINT client_memberships_client_user_uniq DO UPDATE SET
         role = EXCLUDED.role,
         status = EXCLUDED.status,
         updated_at = now()`,
      [r.clientId, r.userId, r.role, r.status]
    );
  }
}

async function upsertTemplateProfiles(
  c: PoolClient,
  rows: SeedTemplateProfile[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO template_profiles
         (id, client_id, profile_key, output_kind, engine, external_ref,
          fidelity_required, fallback_policy, content_contract, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
       ON CONFLICT (id) DO UPDATE SET
         profile_key = EXCLUDED.profile_key,
         output_kind = EXCLUDED.output_kind,
         engine = EXCLUDED.engine,
         external_ref = EXCLUDED.external_ref,
         fidelity_required = EXCLUDED.fidelity_required,
         fallback_policy = EXCLUDED.fallback_policy,
         content_contract = EXCLUDED.content_contract,
         status = EXCLUDED.status,
         updated_at = now()`,
      [
        r.id,
        r.clientId,
        r.profileKey,
        r.outputKind,
        r.engine,
        r.externalRef,
        r.fidelityRequired,
        r.fallbackPolicy,
        JSON.stringify(r.contentContract ?? null),
        r.status,
      ]
    );
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Upsert helpers — Loop 2
// ──────────────────────────────────────────────────────────────────────────

async function upsertPromptProfiles(
  c: PoolClient,
  rows: SeedPromptProfile[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO prompt_profiles
         (id, client_id, profile_key, display_name, scope, status)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (id) DO UPDATE SET
         profile_key = EXCLUDED.profile_key,
         display_name = EXCLUDED.display_name,
         scope = EXCLUDED.scope,
         status = EXCLUDED.status,
         updated_at = now()`,
      [r.id, r.clientId, r.profileKey, r.displayName, r.scope, r.status]
    );
  }
}

async function upsertPromptProfileVersions(
  c: PoolClient,
  rows: SeedPromptProfileVersion[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO prompt_profile_versions
         (id, profile_id, version, base_prompt, constraints,
          authored_by_user_id, status, published_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       ON CONFLICT (id) DO UPDATE SET
         version = EXCLUDED.version,
         base_prompt = EXCLUDED.base_prompt,
         constraints = EXCLUDED.constraints,
         authored_by_user_id = EXCLUDED.authored_by_user_id,
         status = EXCLUDED.status,
         published_at = EXCLUDED.published_at`,
      [
        r.id,
        r.profileId,
        r.version,
        r.basePrompt,
        JSON.stringify(r.constraints ?? null),
        r.authoredByUserId,
        r.status,
        r.publishedAt,
      ]
    );
  }
}

async function upsertRepositoryBindings(
  c: PoolClient,
  rows: SeedRepositoryBinding[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO repository_bindings
         (id, client_id, binding_key, connector_type, scope, credential_ref,
          allowed_locations, freshness_policy, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       ON CONFLICT (id) DO UPDATE SET
         binding_key = EXCLUDED.binding_key,
         connector_type = EXCLUDED.connector_type,
         scope = EXCLUDED.scope,
         credential_ref = EXCLUDED.credential_ref,
         allowed_locations = EXCLUDED.allowed_locations,
         freshness_policy = EXCLUDED.freshness_policy,
         status = EXCLUDED.status,
         updated_at = now()`,
      [
        r.id,
        r.clientId,
        r.bindingKey,
        r.connectorType,
        JSON.stringify(r.scope ?? null),
        r.credentialRef,
        JSON.stringify(r.allowedLocations ?? null),
        JSON.stringify(r.freshnessPolicy ?? null),
        r.status,
      ]
    );
  }
}

async function upsertDataSourceBindings(
  c: PoolClient,
  rows: SeedDataSourceBinding[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO data_source_bindings
         (id, client_id, binding_key, connector_type, scope, credential_ref,
          allowed_locations, freshness_policy, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       ON CONFLICT (id) DO UPDATE SET
         binding_key = EXCLUDED.binding_key,
         connector_type = EXCLUDED.connector_type,
         scope = EXCLUDED.scope,
         credential_ref = EXCLUDED.credential_ref,
         allowed_locations = EXCLUDED.allowed_locations,
         freshness_policy = EXCLUDED.freshness_policy,
         status = EXCLUDED.status,
         updated_at = now()`,
      [
        r.id,
        r.clientId,
        r.bindingKey,
        r.connectorType,
        JSON.stringify(r.scope ?? null),
        r.credentialRef,
        JSON.stringify(r.allowedLocations ?? null),
        JSON.stringify(r.freshnessPolicy ?? null),
        r.status,
      ]
    );
  }
}

async function upsertArtifacts(
  c: PoolClient,
  rows: SeedArtifact[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO artifacts
         (id, client_id, source_type, content_class, mime_type, filename,
          storage_ref, extracted_text, metadata, created_by_user_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
       ON CONFLICT (id) DO UPDATE SET
         source_type = EXCLUDED.source_type,
         content_class = EXCLUDED.content_class,
         mime_type = EXCLUDED.mime_type,
         filename = EXCLUDED.filename,
         storage_ref = EXCLUDED.storage_ref,
         extracted_text = EXCLUDED.extracted_text,
         metadata = EXCLUDED.metadata,
         created_by_user_id = EXCLUDED.created_by_user_id,
         updated_at = now()`,
      [
        r.id,
        r.clientId,
        r.sourceType,
        r.contentClass,
        r.mimeType,
        r.filename,
        r.storageRef,
        r.extractedText,
        JSON.stringify(r.metadata ?? null),
        r.createdByUserId,
      ]
    );
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Upsert helpers — Loop 3 Phase 1
// ──────────────────────────────────────────────────────────────────────────

async function upsertWorkOrders(
  c: PoolClient,
  rows: SeedWorkOrder[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO work_orders
         (id, client_id, title, description, type, priority, status,
          submitted_by_user_id, correlation_id, gcc_memory,
          deferred_until, deferred_reason)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
       ON CONFLICT (id) DO UPDATE SET
         title = EXCLUDED.title,
         description = EXCLUDED.description,
         type = EXCLUDED.type,
         priority = EXCLUDED.priority,
         status = EXCLUDED.status,
         submitted_by_user_id = EXCLUDED.submitted_by_user_id,
         correlation_id = EXCLUDED.correlation_id,
         gcc_memory = EXCLUDED.gcc_memory,
         deferred_until = EXCLUDED.deferred_until,
         deferred_reason = EXCLUDED.deferred_reason,
         updated_at = now()`,
      [
        r.id,
        r.clientId,
        r.title,
        r.description,
        r.type,
        r.priority,
        r.status,
        r.submittedByUserId,
        r.correlationId,
        JSON.stringify(r.gccMemory ?? null),
        r.deferredUntil,
        r.deferredReason,
      ]
    );
  }
}

async function upsertWorkflows(
  c: PoolClient,
  rows: SeedWorkflow[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO workflows (id, client_id, key, display_name, description, status)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (id) DO UPDATE SET
         key = EXCLUDED.key,
         display_name = EXCLUDED.display_name,
         description = EXCLUDED.description,
         status = EXCLUDED.status,
         updated_at = now()`,
      [r.id, r.clientId, r.key, r.displayName, r.description, r.status]
    );
  }
}

async function upsertWorkflowTemplates(
  c: PoolClient,
  rows: SeedWorkflowTemplate[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO workflow_templates
         (id, workflow_id, version, description, config, status, published_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (id) DO UPDATE SET
         version = EXCLUDED.version,
         description = EXCLUDED.description,
         config = EXCLUDED.config,
         status = EXCLUDED.status,
         published_at = EXCLUDED.published_at`,
      [
        r.id,
        r.workflowId,
        r.version,
        r.description,
        JSON.stringify(r.config ?? null),
        r.status,
        r.publishedAt,
      ]
    );
  }
}

async function upsertWorkflowTemplateSteps(
  c: PoolClient,
  rows: SeedWorkflowTemplateStep[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO workflow_template_steps
         (id, template_id, step_key, step_order, display_name,
          assigned_sub_agent_key, prompt_ref, retry_policy, timeout_ms, tool_ids)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
       ON CONFLICT (id) DO UPDATE SET
         step_key = EXCLUDED.step_key,
         step_order = EXCLUDED.step_order,
         display_name = EXCLUDED.display_name,
         assigned_sub_agent_key = EXCLUDED.assigned_sub_agent_key,
         prompt_ref = EXCLUDED.prompt_ref,
         retry_policy = EXCLUDED.retry_policy,
         timeout_ms = EXCLUDED.timeout_ms,
         tool_ids = EXCLUDED.tool_ids`,
      [
        r.id,
        r.templateId,
        r.stepKey,
        r.stepOrder,
        r.displayName,
        r.assignedSubAgentKey,
        JSON.stringify(r.promptRef ?? null),
        JSON.stringify(r.retryPolicy ?? null),
        r.timeoutMs,
        JSON.stringify(r.toolIds ?? null),
      ]
    );
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Upsert helpers — Loop 3 Phase 2
// ──────────────────────────────────────────────────────────────────────────

async function upsertAdapterCatalog(
  c: PoolClient,
  rows: SeedAdapterCatalog[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO adapter_catalog
         (id, adapter_key, display_name, category, description,
          contract_version, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (id) DO UPDATE SET
         adapter_key = EXCLUDED.adapter_key,
         display_name = EXCLUDED.display_name,
         category = EXCLUDED.category,
         description = EXCLUDED.description,
         contract_version = EXCLUDED.contract_version,
         status = EXCLUDED.status,
         updated_at = now()`,
      [
        r.id,
        r.adapterKey,
        r.displayName,
        r.category,
        r.description,
        r.contractVersion,
        r.status,
      ]
    );
  }
}

async function upsertAdapterActions(
  c: PoolClient,
  rows: SeedAdapterAction[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO adapter_actions
         (id, adapter_catalog_id, action_key, display_name, description,
          requires_output_package)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (id) DO UPDATE SET
         adapter_catalog_id = EXCLUDED.adapter_catalog_id,
         action_key = EXCLUDED.action_key,
         display_name = EXCLUDED.display_name,
         description = EXCLUDED.description,
         requires_output_package = EXCLUDED.requires_output_package,
         updated_at = now()`,
      [
        r.id,
        r.adapterCatalogId,
        r.actionKey,
        r.displayName,
        r.description,
        r.requiresOutputPackage,
      ]
    );
  }
}

async function upsertClientAdapterConfigs(
  c: PoolClient,
  rows: SeedClientAdapterConfig[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO client_adapter_configs
         (id, client_id, adapter_catalog_id, enabled, credential_ref,
          config, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (id) DO UPDATE SET
         client_id = EXCLUDED.client_id,
         adapter_catalog_id = EXCLUDED.adapter_catalog_id,
         enabled = EXCLUDED.enabled,
         credential_ref = EXCLUDED.credential_ref,
         config = EXCLUDED.config,
         status = EXCLUDED.status,
         updated_at = now()`,
      [
        r.id,
        r.clientId,
        r.adapterCatalogId,
        r.enabled,
        r.credentialRef,
        JSON.stringify(r.config ?? null),
        r.status,
      ]
    );
  }
}

async function upsertAdapterActionPolicies(
  c: PoolClient,
  rows: SeedAdapterActionPolicy[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO adapter_action_policies
         (id, client_id, adapter_catalog_id, action_key, mode, reason,
          metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (id) DO UPDATE SET
         client_id = EXCLUDED.client_id,
         adapter_catalog_id = EXCLUDED.adapter_catalog_id,
         action_key = EXCLUDED.action_key,
         mode = EXCLUDED.mode,
         reason = EXCLUDED.reason,
         metadata = EXCLUDED.metadata,
         updated_at = now()`,
      [
        r.id,
        r.clientId,
        r.adapterCatalogId,
        r.actionKey,
        r.mode,
        r.reason,
        JSON.stringify(r.metadata ?? null),
      ]
    );
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Upsert helpers — Loop 4 Phase 1
// ──────────────────────────────────────────────────────────────────────────

async function upsertPermissions(
  c: PoolClient,
  rows: SeedPermission[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO permissions
         (id, permission_key, display_name, description, scope)
       VALUES ($1, $2, $3, $4, $5::permission_scope)
       ON CONFLICT (id) DO UPDATE SET
         permission_key = EXCLUDED.permission_key,
         display_name = EXCLUDED.display_name,
         description = EXCLUDED.description,
         scope = EXCLUDED.scope,
         updated_at = now()`,
      [r.id, r.permissionKey, r.displayName, r.description, r.scope]
    );
  }
}

async function upsertRolePermissions(
  c: PoolClient,
  rows: SeedRolePermission[]
): Promise<void> {
  // Resolve permission_key → permission_id via JOIN. Idempotent on the
  // (role, permission_id) unique index.
  for (const r of rows) {
    await c.query(
      `INSERT INTO role_permissions (role, permission_id)
       SELECT $1::membership_role, p.id
       FROM permissions p
       WHERE p.permission_key = $2
       ON CONFLICT ON CONSTRAINT role_permissions_role_permission_uniq
       DO UPDATE SET updated_at = now()`,
      [r.role, r.permissionKey]
    );
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Upsert helpers — Loop 9 Phase 9.3
// ──────────────────────────────────────────────────────────────────────────

/**
 * Pre-Beta Loop δ.1 — seed each tenant's workspace root + Outputs/.
 * The migration writes the rows on upgrade, but on a fresh
 * reset-then-seed install the migration runs before clients exist,
 * so we re-run the same idempotent INSERTs after clients/users land.
 *
 * Both rows are owned by the tenant's first agent_system user
 * (worker-style); ON CONFLICT on the sibling-name UNIQUE keeps it
 * idempotent across re-seeds.
 */
async function upsertWorkspaceRoots(c: PoolClient): Promise<void> {
  await c.query(`
    INSERT INTO workspace_folders (id, client_id, parent_folder_id, name, created_by_user_id)
    SELECT
      gen_random_uuid(),
      cl.id,
      NULL,
      '/',
      (SELECT u.id FROM users u
         JOIN client_memberships m ON m.user_id = u.id
                                  AND m.client_id = cl.id
                                  AND m.role = 'agent_system'
                                  AND m.status = 'active'
                                  AND u.status = 'active'
        ORDER BY u.created_at ASC
        LIMIT 1)
    FROM clients cl
    WHERE cl.status = 'active'::client_status
      AND EXISTS (SELECT 1 FROM users u
                    JOIN client_memberships m ON m.user_id = u.id
                                             AND m.client_id = cl.id
                                             AND m.role = 'agent_system'
                                             AND m.status = 'active')
    ON CONFLICT ON CONSTRAINT workspace_folders_sibling_name_uniq DO NOTHING
  `);
  await c.query(`
    INSERT INTO workspace_folders (id, client_id, parent_folder_id, name, created_by_user_id)
    SELECT gen_random_uuid(), cl.id, root.id, 'Outputs', root.created_by_user_id
    FROM clients cl
    JOIN workspace_folders root ON root.client_id = cl.id
                              AND root.parent_folder_id IS NULL
                              AND root.name = '/'
                              AND root.deleted_at IS NULL
    WHERE cl.status = 'active'::client_status
    ON CONFLICT ON CONSTRAINT workspace_folders_sibling_name_uniq DO NOTHING
  `);
}


/**
 * Pre-Beta β.1 — humanise an agent_role into a display_name when the
 * seed JSON doesn't carry one. Matches the backfill in migration
 * 0012_pre_beta_phase_1_llm_configs_metadata.sql so DBs reset from
 * scratch land in the same shape as DBs migrated forward.
 */
function defaultDisplayName(agentRole: string): string {
  const lookup: Record<string, string> = {
    aiden_tier_1: "Aiden (Tier 1)",
    pm_tier_15: "PM (Tier 1.5)",
    mark_tier_2: "Mark (Tier 2 — content)",
    tom_tier_2: "Tom (Tier 2 — decks)",
    hank_tier_2: "Hank (Tier 2 — web)",
    paul_tier_2: "Paul (Tier 2 — deployment)",
  };
  if (lookup[agentRole]) return lookup[agentRole];
  return agentRole
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}


interface SeedLlmConfig {
  id: string;
  clientId: string;
  agentRole: string;
  /**
   * Pre-Beta β.1 — sub-agent metadata model v1 fields.
   * `displayName` is NOT NULL on the table; the seed loader derives a
   * humanised default from `agentRole` if the JSON omits it (mirrors
   * the migration 0012 backfill so old seed files keep loading).
   */
  displayName?: string;
  description?: string | null;
  provider: string;
  model: string;
  baseUrl: string | null;
  credentialRef: string;
  systemPrompt: string | null;
  options: unknown | null;
  enabled: boolean;
  notes: string | null;
}

async function upsertLlmConfigs(
  c: PoolClient,
  rows: SeedLlmConfig[]
): Promise<void> {
  for (const r of rows) {
    await c.query(
      `INSERT INTO llm_configs
         (id, client_id, agent_role, display_name, description,
          provider, model, base_url, credential_ref, system_prompt,
          options, enabled, notes)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13)
       ON CONFLICT (id) DO UPDATE SET
         client_id = EXCLUDED.client_id,
         agent_role = EXCLUDED.agent_role,
         display_name = EXCLUDED.display_name,
         description = EXCLUDED.description,
         provider = EXCLUDED.provider,
         model = EXCLUDED.model,
         base_url = EXCLUDED.base_url,
         credential_ref = EXCLUDED.credential_ref,
         system_prompt = EXCLUDED.system_prompt,
         options = EXCLUDED.options,
         enabled = EXCLUDED.enabled,
         notes = EXCLUDED.notes,
         updated_at = now()`,
      [
        r.id,
        r.clientId,
        r.agentRole,
        r.displayName ?? defaultDisplayName(r.agentRole),
        r.description ?? null,
        r.provider,
        r.model,
        r.baseUrl,
        r.credentialRef,
        r.systemPrompt,
        JSON.stringify(r.options ?? null),
        r.enabled,
        r.notes,
      ]
    );
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Entry
// ──────────────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const url = process.env.IWO3_DATABASE_URL;
  if (!url) throw new Error("IWO3_DATABASE_URL is required");

  // Loop 1
  const clients = loadJson<SeedClient[]>("db/seeds/clients.json");
  const users = loadJson<SeedUser[]>("db/seeds/users.json");
  const memberships = loadJson<SeedMembership[]>(
    "db/seeds/client_memberships.json"
  );
  const templates = loadJson<SeedTemplateProfile[]>(
    "db/seeds/template_profiles.json"
  );

  // Loop 2
  const promptProfiles = loadJson<SeedPromptProfile[]>(
    "db/seeds/prompt_profiles.json"
  );
  const promptProfileVersions = loadJson<SeedPromptProfileVersion[]>(
    "db/seeds/prompt_profile_versions.json"
  );
  const repositoryBindings = loadJson<SeedRepositoryBinding[]>(
    "db/seeds/repository_bindings.json"
  );
  const dataSourceBindings = loadJson<SeedDataSourceBinding[]>(
    "db/seeds/data_source_bindings.json"
  );
  const artifacts = loadJson<SeedArtifact[]>("db/seeds/artifacts.json");

  // Loop 3 Phase 1
  const workOrders = loadJson<SeedWorkOrder[]>("db/seeds/work_orders.json");
  const workflows = loadJson<SeedWorkflow[]>("db/seeds/workflows.json");
  const workflowTemplates = loadJson<SeedWorkflowTemplate[]>(
    "db/seeds/workflow_templates.json"
  );
  const workflowTemplateSteps = loadJson<SeedWorkflowTemplateStep[]>(
    "db/seeds/workflow_template_steps.json"
  );

  // Loop 3 Phase 2
  const adapterCatalogRows = loadJson<SeedAdapterCatalog[]>(
    "db/seeds/adapter_catalog.json"
  );
  const adapterActionsRows = loadJson<SeedAdapterAction[]>(
    "db/seeds/adapter_actions.json"
  );
  const clientAdapterConfigsRows = loadJson<SeedClientAdapterConfig[]>(
    "db/seeds/client_adapter_configs.json"
  );
  const adapterActionPoliciesRows = loadJson<SeedAdapterActionPolicy[]>(
    "db/seeds/adapter_action_policies.json"
  );

  // Loop 4 Phase 1
  const permissionsRows = loadJson<SeedPermission[]>(
    "db/seeds/permissions.json"
  );
  const rolePermissionsRows = loadJson<SeedRolePermission[]>(
    "db/seeds/role_permissions.json"
  );

  // Loop 9 Phase 9.3
  const llmConfigsRows = loadJson<SeedLlmConfig[]>(
    "db/seeds/llm_configs.json"
  );

  const pool = new Pool({ connectionString: url });
  const c = await pool.connect();
  try {
    await c.query("BEGIN");
    // FK dependency order
    await upsertClients(c, clients);
    await upsertUsers(c, users);
    await upsertMemberships(c, memberships);
    await upsertTemplateProfiles(c, templates);
    await upsertPromptProfiles(c, promptProfiles);
    await upsertPromptProfileVersions(c, promptProfileVersions);
    await upsertRepositoryBindings(c, repositoryBindings);
    await upsertDataSourceBindings(c, dataSourceBindings);
    await upsertArtifacts(c, artifacts);
    await upsertWorkOrders(c, workOrders);
    await upsertWorkflows(c, workflows);
    await upsertWorkflowTemplates(c, workflowTemplates);
    await upsertWorkflowTemplateSteps(c, workflowTemplateSteps);
    await upsertAdapterCatalog(c, adapterCatalogRows);
    await upsertAdapterActions(c, adapterActionsRows);
    await upsertClientAdapterConfigs(c, clientAdapterConfigsRows);
    await upsertAdapterActionPolicies(c, adapterActionPoliciesRows);
    await upsertPermissions(c, permissionsRows);
    await upsertRolePermissions(c, rolePermissionsRows);
    await upsertLlmConfigs(c, llmConfigsRows);
    await upsertWorkspaceRoots(c);
    await c.query("COMMIT");

    const receipt = {
      seededAt: new Date().toISOString(),
      counts: {
        clients: clients.length,
        users: users.length,
        client_memberships: memberships.length,
        template_profiles: templates.length,
        prompt_profiles: promptProfiles.length,
        prompt_profile_versions: promptProfileVersions.length,
        repository_bindings: repositoryBindings.length,
        data_source_bindings: dataSourceBindings.length,
        artifacts: artifacts.length,
        work_orders: workOrders.length,
        workflows: workflows.length,
        workflow_templates: workflowTemplates.length,
        workflow_template_steps: workflowTemplateSteps.length,
        adapter_catalog: adapterCatalogRows.length,
        adapter_actions: adapterActionsRows.length,
        client_adapter_configs: clientAdapterConfigsRows.length,
        adapter_action_policies: adapterActionPoliciesRows.length,
        permissions: permissionsRows.length,
        role_permissions: rolePermissionsRows.length,
        llm_configs: llmConfigsRows.length,
      },
      sources: {
        clients: "db/seeds/clients.json",
        users: "db/seeds/users.json",
        client_memberships: "db/seeds/client_memberships.json",
        template_profiles: "db/seeds/template_profiles.json",
        prompt_profiles: "db/seeds/prompt_profiles.json",
        prompt_profile_versions: "db/seeds/prompt_profile_versions.json",
        repository_bindings: "db/seeds/repository_bindings.json",
        data_source_bindings: "db/seeds/data_source_bindings.json",
        artifacts: "db/seeds/artifacts.json",
        work_orders: "db/seeds/work_orders.json",
        workflows: "db/seeds/workflows.json",
        workflow_templates: "db/seeds/workflow_templates.json",
        workflow_template_steps: "db/seeds/workflow_template_steps.json",
        adapter_catalog: "db/seeds/adapter_catalog.json",
        adapter_actions: "db/seeds/adapter_actions.json",
        client_adapter_configs: "db/seeds/client_adapter_configs.json",
        adapter_action_policies: "db/seeds/adapter_action_policies.json",
        permissions: "db/seeds/permissions.json",
        role_permissions: "db/seeds/role_permissions.json",
        llm_configs: "db/seeds/llm_configs.json",
      },
    };
    writeFileSync(
      resolve(REPO_ROOT, "infra/local/last-seed.json"),
      JSON.stringify(receipt, null, 2)
    );
    console.log("[seed-loader]", receipt);
  } catch (err) {
    await c.query("ROLLBACK");
    throw err;
  } finally {
    c.release();
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
