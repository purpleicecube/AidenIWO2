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
