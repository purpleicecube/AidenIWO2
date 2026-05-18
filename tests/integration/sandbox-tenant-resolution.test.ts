/**
 * CODEX architect follow-up (2026-05-18) — multi-membership operator
 * regression for the sandbox cross-service tenant resolver.
 *
 * Background: the prior pattern (`getUserPrimaryClientId(userId)`
 * returning the first arbitrary `client_memberships` row) silently
 * picked the wrong tenant for operators with memberships in multiple
 * tenants. This test seeds an output_package + an artifact in Klear,
 * and a parallel pair in FFAI, then proves that `resolvePackageTenant`
 * + `resolveArtifactTenant` derive the tenant from the resource
 * (NOT from membership ordering) when called by the super-user who
 * holds owner roles in BOTH tenants.
 *
 * Seeds used:
 *   super@dev.local (00000000-0000-4000-8000-000099000001)
 *     ← owner of Klear (c001) AND FFAI (c002)
 *
 * Pre-fix expected failure: helpers would return whichever tenant
 * `LIMIT 1` returned, ignoring the resource's actual tenant.
 * Post-fix expected pass: helpers return the resource's tenant
 * regardless of which other tenants the actor belongs to.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { randomUUID } from "node:crypto";

import {
  resolveArtifactTenant,
  resolvePackageTenant,
} from "../../server/sandbox-crossservice";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR = "00000000-0000-4000-8000-00000000c001";
const FFAI = "00000000-0000-4000-8000-00000000c002";
const SUPER_USER = "00000000-0000-4000-8000-000099000001";
// Klear-only operator — owns Klear, has NO membership in FFAI.
const KLEAR_OWNER = "00000000-0000-4000-8000-000001000001";

describeIwo3(
  "Sandbox + Markdown Review Layer (CODEX follow-up 2026-05-18) — multi-membership tenant resolution",
  () => {
    const pool = new Pool({ connectionString: url });
    const klearPkgId = randomUUID();
    const ffaiPkgId = randomUUID();
    // Outputs root folders that already exist in seeds (Klear + FFAI
    // workspace_folders.is_root = true). Use the seeded Outputs folder.
    let klearOutputsFolderId: string;
    let ffaiOutputsFolderId: string;
    const klearArtId = randomUUID();
    const ffaiArtId = randomUUID();

    beforeAll(async () => {
      // Look up Outputs folder for each tenant.
      const klearFolder = await pool.query<{ id: string }>(
        `SELECT id::text AS id FROM workspace_folders
          WHERE client_id = $1::uuid AND name = 'Outputs' LIMIT 1`,
        [KLEAR],
      );
      const ffaiFolder = await pool.query<{ id: string }>(
        `SELECT id::text AS id FROM workspace_folders
          WHERE client_id = $1::uuid AND name = 'Outputs' LIMIT 1`,
        [FFAI],
      );
      klearOutputsFolderId = klearFolder.rows[0].id;
      ffaiOutputsFolderId = ffaiFolder.rows[0].id;

      // Seed one output_package per tenant.
      await pool.query(
        `INSERT INTO output_packages
           (id, client_id, output_kind, title, summary, status, priority, content_blocks)
         VALUES ($1::uuid, $2::uuid, 'gamma_pdf', $3, $4, 'draft', 'medium', $5::jsonb),
                ($6::uuid, $7::uuid, 'gamma_pdf', $8, $9, 'draft', 'medium', $5::jsonb)`,
        [
          klearPkgId,
          KLEAR,
          "Klear Test Package",
          "Klear summary",
          '{"content_markdown":"# Klear","summary":"Klear summary"}',
          ffaiPkgId,
          FFAI,
          "FFAI Test Package",
          "FFAI summary",
        ],
      );

      // Seed one artifact per tenant in their Outputs folder.
      await pool.query(
        `INSERT INTO artifacts
           (id, client_id, source_type, content_class, mime_type, filename,
            storage_ref, extracted_text, workspace_folder_id, created_by_user_id)
         VALUES ($1::uuid, $2::uuid, 'generated'::artifact_source_type,
                 'c1'::artifact_content_class, 'text/markdown', 'klear.md',
                 'inline://workspace', '# Klear content', $3::uuid, $4::uuid),
                ($5::uuid, $6::uuid, 'generated'::artifact_source_type,
                 'c1'::artifact_content_class, 'text/markdown', 'ffai.md',
                 'inline://workspace', '# FFAI content', $7::uuid, $8::uuid)`,
        [
          klearArtId,
          KLEAR,
          klearOutputsFolderId,
          SUPER_USER,
          ffaiArtId,
          FFAI,
          ffaiOutputsFolderId,
          SUPER_USER,
        ],
      );
    });

    afterAll(async () => {
      await pool.query(`DELETE FROM artifacts WHERE id IN ($1::uuid, $2::uuid)`, [
        klearArtId,
        ffaiArtId,
      ]);
      await pool.query(
        `DELETE FROM output_packages WHERE id IN ($1::uuid, $2::uuid)`,
        [klearPkgId, ffaiPkgId],
      );
      await pool.end();
    });

    it("resolvePackageTenant returns FFAI for an FFAI package, even when actor is super (multi-membership)", async () => {
      const result = await resolvePackageTenant(ffaiPkgId, SUPER_USER);
      expect("kind" in result, `expected success, got error: ${JSON.stringify(result)}`).toBe(false);
      if (!("kind" in result)) {
        expect(result.clientId).toBe(FFAI);
      }
    });

    it("resolvePackageTenant returns Klear for a Klear package, same multi-membership actor", async () => {
      const result = await resolvePackageTenant(klearPkgId, SUPER_USER);
      expect("kind" in result, `expected success, got error: ${JSON.stringify(result)}`).toBe(false);
      if (!("kind" in result)) {
        expect(result.clientId).toBe(KLEAR);
      }
    });

    it("resolvePackageTenant returns forbidden when actor has no membership in the package's tenant", async () => {
      // KLEAR_OWNER has Klear membership only. Asking for an FFAI
      // package must NOT return the FFAI client_id — it must 403.
      const result = await resolvePackageTenant(ffaiPkgId, KLEAR_OWNER);
      expect("kind" in result).toBe(true);
      if ("kind" in result) {
        expect(result.kind).toBe("forbidden");
        expect(result.status).toBe(403);
      }
    });

    it("resolveArtifactTenant returns FFAI for an FFAI artifact, multi-membership actor", async () => {
      const result = await resolveArtifactTenant(ffaiArtId, SUPER_USER);
      expect("kind" in result).toBe(false);
      if (!("kind" in result)) {
        expect(result.clientId).toBe(FFAI);
      }
    });

    it("resolveArtifactTenant returns Klear for a Klear artifact, same multi-membership actor", async () => {
      const result = await resolveArtifactTenant(klearArtId, SUPER_USER);
      expect("kind" in result).toBe(false);
      if (!("kind" in result)) {
        expect(result.clientId).toBe(KLEAR);
      }
    });

    it("resolveArtifactTenant returns forbidden when actor has no membership in the artifact's tenant", async () => {
      const result = await resolveArtifactTenant(ffaiArtId, KLEAR_OWNER);
      expect("kind" in result).toBe(true);
      if ("kind" in result) {
        expect(result.kind).toBe("forbidden");
      }
    });

    it("resolvePackageTenant returns not_found for an unknown package id (no membership leak)", async () => {
      const result = await resolvePackageTenant(randomUUID(), SUPER_USER);
      expect("kind" in result).toBe(true);
      if ("kind" in result) {
        expect(result.kind).toBe("not_found");
      }
    });
  },
);
