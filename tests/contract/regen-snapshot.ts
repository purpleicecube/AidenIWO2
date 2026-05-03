/**
 * Regenerate the contract-enums snapshot fixture from the live DB +
 * the in-tree audit-events vocabulary. Used after migrations or audit
 * vocabulary changes — the resulting JSON is the canonical "frozen"
 * shape that `tests/contract/contract-enums.test.ts` asserts against
 * in CI.
 *
 * Usage:
 *   IWO3_DATABASE_URL=postgresql://iwo3:iwo3@localhost:5434/aiden_iwo3 \
 *     npx tsx tests/contract/regen-snapshot.ts
 *
 * Output: writes tests/fixtures/contract-enums.snapshot.json with
 * 2-space pretty-printed JSON + trailing newline.
 */

import { Pool } from "pg";
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { buildContractSnapshot } from "./_snapshot-helpers";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const SNAPSHOT_PATH = resolve(
  __dirname,
  "../fixtures/contract-enums.snapshot.json"
);

async function main(): Promise<void> {
  const url = process.env.IWO3_DATABASE_URL;
  if (!url) {
    console.error("IWO3_DATABASE_URL is required");
    process.exit(1);
  }
  const pool = new Pool({ connectionString: url });
  try {
    const snap = await buildContractSnapshot(pool);
    writeFileSync(SNAPSHOT_PATH, JSON.stringify(snap, null, 2) + "\n");
    console.log(`[regen-snapshot] Wrote ${SNAPSHOT_PATH}`);
    console.log(
      `[regen-snapshot] enums=${Object.keys(snap.dbEnums).length} ` +
        `auditEvents.all=${snap.auditEvents.all.length} ` +
        `permissionKeys=${snap.permissionKeys.length}`
    );
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
