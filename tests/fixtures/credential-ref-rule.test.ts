import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";

const CREDENTIAL_FIELD = /^(credential|token|api[_-]?key|apikey|secret|password|bearer|access[_-]?key|accesskey|private[_-]?key|privatekey|auth)$/i;

function listJsonFiles(root: string): string[] {
  const out: string[] = [];
  function walk(dir: string) {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      const st = statSync(full);
      if (st.isDirectory()) walk(full);
      else if (/\.json$/i.test(entry)) out.push(full);
    }
  }
  walk(root);
  return out;
}

function scan(value: unknown, path: string, violations: string[]): void {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (CREDENTIAL_FIELD.test(k)) {
        if (v === null) continue;
        if (typeof v === "string" && v.startsWith("credential_ref:")) continue;
        violations.push(`${path}::${k} = ${JSON.stringify(v)}`);
      } else {
        scan(v, `${path}.${k}`, violations);
      }
    }
  } else if (Array.isArray(value)) {
    value.forEach((item, i) => scan(item, `${path}[${i}]`, violations));
  }
}

describe("Loop 1 — credential_ref fixture rule", () => {
  const repoRoot = resolve(__dirname, "..", "..");
  const roots = [
    resolve(repoRoot, "db/seeds"),
    resolve(repoRoot, "db/fixtures"),
    resolve(repoRoot, "tests/fixtures"),
  ];

  it("every credential-shaped field in JSON fixtures is credential_ref: or null", () => {
    const violations: string[] = [];
    for (const root of roots) {
      if (!existsSync(root)) continue;
      for (const f of listJsonFiles(root)) {
        const raw = readFileSync(f, "utf-8").trim();
        if (!raw) continue;
        let parsed: unknown;
        try {
          parsed = JSON.parse(raw);
        } catch {
          continue;
        }
        scan(parsed, f, violations);
      }
    }
    expect(violations).toEqual([]);
  });
});
