/**
 * Loads Loop 1 durable seed data into IWO3.
 *
 * Sources (relative to repo root):
 *   db/seeds/clients.json
 *   db/seeds/users.json
 *   db/seeds/client_memberships.json
 *   db/seeds/template_profiles.json
 *
 * Idempotent via ON CONFLICT DO UPDATE. Deterministic: UUIDs are fixed in the
 * seed JSON, so re-running produces the same database state.
 *
 * Writes a receipt to infra/local/last-seed.json.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { Pool, type PoolClient } from "pg";

const REPO_ROOT = resolve(__dirname, "..", "..");

function loadJson<T>(relpath: string): T {
  const p = resolve(REPO_ROOT, relpath);
  const raw = readFileSync(p, "utf-8");
  return JSON.parse(raw) as T;
}

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

async function main(): Promise<void> {
  const url = process.env.IWO3_DATABASE_URL;
  if (!url) throw new Error("IWO3_DATABASE_URL is required");

  const clients = loadJson<SeedClient[]>("db/seeds/clients.json");
  const users = loadJson<SeedUser[]>("db/seeds/users.json");
  const memberships = loadJson<SeedMembership[]>(
    "db/seeds/client_memberships.json"
  );
  const templates = loadJson<SeedTemplateProfile[]>(
    "db/seeds/template_profiles.json"
  );

  const pool = new Pool({ connectionString: url });
  const c = await pool.connect();
  try {
    await c.query("BEGIN");
    await upsertClients(c, clients);
    await upsertUsers(c, users);
    await upsertMemberships(c, memberships);
    await upsertTemplateProfiles(c, templates);
    await c.query("COMMIT");

    const receipt = {
      seededAt: new Date().toISOString(),
      counts: {
        clients: clients.length,
        users: users.length,
        client_memberships: memberships.length,
        template_profiles: templates.length,
      },
      sources: {
        clients: "db/seeds/clients.json",
        users: "db/seeds/users.json",
        client_memberships: "db/seeds/client_memberships.json",
        template_profiles: "db/seeds/template_profiles.json",
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
