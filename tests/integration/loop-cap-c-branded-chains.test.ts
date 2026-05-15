/**
 * Loop CAP-C Φ.4 — branded chain template seed coverage.
 *
 * Asserts the eight branded chain templates were seeded for both
 * tenants (Klear active + FF mirror skeleton) per
 * IWO3_ORCHESTRATION_CAP_OUTPUT_SURFACES_v0.3.0 §Φ.4:
 *
 *   1. cap_branded_pptx        — Mark → Tom → Darla → Paul
 *   2. cap_branded_pdf         — Mark → Tom → Darla → Paul
 *   3. cap_branded_html        — Mark → Hank → Darla → Paul (self-contained)
 *   4. cap_branded_html_stitch — Mark → Hank (Stitch) → Darla → Paul
 *   5. cap_branded_html_figma  — Mark → Hank (Figma) → Darla → Paul
 *   6. cap_branded_html_21st   — Mark → Hank (21st-Magic) → Darla → Paul
 *   7. cap_branded_docx        — Mark → SOP Master → Darla → Paul
 *   8. cap_branded_md          — Mark → SOP Master → Darla → Paul
 *
 * Coverage:
 *   - 16 workflows (8 per tenant) under `cap_branded_*` keys
 *   - 16 workflow_templates (one v1 per chain) with category="branded_chain"
 *   - 64 workflow_template_steps (4 per chain) in correct order
 *   - Sub-agent assignments match chain spec
 *   - config jsonb carries outputKind, designInputSource, requiresBrandQa,
 *     and a deferredPhases list documenting what is NOT yet executable
 *     (Φ.5 Paul LLM, Φ.6 Darla gate, Φ.7 registry, Φ.8 Aiden, Φ.9 adapters)
 *   - Klear `requires_brand_qa=true`; FF mirror `requires_brand_qa=false`
 *     (FF skeleton, per CAP-A Q-PG-7 lock)
 *   - All chain step assignedSubAgentKey values are aliases that
 *     `tier_2_subagents._normalise_role` already accepts (Eta phase 1.1)
 */

import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001";
const FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002";

const CHAIN_KEYS = [
  "cap_branded_pptx",
  "cap_branded_pdf",
  "cap_branded_html",
  "cap_branded_html_stitch",
  "cap_branded_html_figma",
  "cap_branded_html_21st",
  "cap_branded_docx",
  "cap_branded_md",
] as const;

const EXPECTED_STEP_KEYS = ["content_brief", "render", "brand_qa", "deliver"] as const;

// chainKey → expected (renderRole, outputKind, designInputSource)
const CHAIN_RENDER_SPEC: Record<string, [string, string, string | null]> = {
  cap_branded_pptx:        ["tom_tier_2",        "pptx", null],
  cap_branded_pdf:         ["tom_tier_2",        "pdf",  null],
  cap_branded_html:        ["hank_tier_2",       "html", null],
  cap_branded_html_stitch: ["hank_tier_2",       "html", "stitch"],
  cap_branded_html_figma:  ["hank_tier_2",       "html", "figma"],
  cap_branded_html_21st:   ["hank_tier_2",       "html", "twentyfirst"],
  cap_branded_docx:        ["sop_master_tier_2", "docx", null],
  cap_branded_md:          ["sop_master_tier_2", "md",   null],
};

describeIwo3("Loop CAP-C Φ.4 — branded chain template seed", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("16 branded chain workflows seeded (8 per tenant)", async () => {
    const { rows } = await pool.query<{ client_id: string; key: string }>(
      `SELECT client_id::text, key
       FROM workflows
       WHERE key LIKE 'cap_branded_%'
       ORDER BY client_id, key`
    );
    expect(rows).toHaveLength(16);
    const klear = rows.filter((r) => r.client_id === KLEAR_CLIENT);
    const ffai = rows.filter((r) => r.client_id === FFAI_CLIENT);
    expect(klear).toHaveLength(8);
    expect(ffai).toHaveLength(8);
    expect(klear.map((r) => r.key).sort()).toEqual([...CHAIN_KEYS].sort());
    expect(ffai.map((r) => r.key).sort()).toEqual([...CHAIN_KEYS].sort());
  });

  it("16 branded chain templates seeded with category=branded_chain + v1 + published", async () => {
    const { rows } = await pool.query<{
      version: string;
      status: string;
      config: any;
      key: string;
      client_id: string;
    }>(
      `SELECT wt.version, wt.status::text, wt.config, w.key, w.client_id::text
       FROM workflow_templates wt
       JOIN workflows w ON w.id = wt.workflow_id
       WHERE w.key LIKE 'cap_branded_%'
       ORDER BY w.client_id, w.key`
    );
    expect(rows).toHaveLength(16);
    for (const r of rows) {
      expect(r.version).toBe("1");
      expect(r.status).toBe("published");
      const config = typeof r.config === "string" ? JSON.parse(r.config) : r.config;
      expect(config.category).toBe("branded_chain");
      expect(config.chainKey).toBe(r.key);
      expect(config.contentBriefSubAgent).toBe("mark_tier_2");
      expect(config.brandQaSubAgent).toBe("darla_tier_2");
      expect(config.deliverySubAgent).toBe("paul_tier_2");
      // Render sub-agent matches chain spec
      const [expectedRender, expectedKind, expectedDesign] =
        CHAIN_RENDER_SPEC[r.key];
      expect(config.renderSubAgent).toBe(expectedRender);
      expect(config.outputKind).toBe(expectedKind);
      expect(config.designInputSource ?? null).toBe(expectedDesign);
      // Documented deferred phases — at minimum Φ.5/Φ.6/Φ.7/Φ.8/Φ.9
      expect(Array.isArray(config.deferredPhases)).toBe(true);
      expect(config.deferredPhases).toEqual(
        expect.arrayContaining([
          "paul_full_llm_phi5",
          "darla_gate_mode_phi6",
          "output_surface_registry_phi7",
          "aiden_branded_intent_phi8",
          "render_adapter_phi9",
        ])
      );
      // Klear gets brand QA required; FF mirror skeleton skips
      const expectedQa = r.client_id === KLEAR_CLIENT;
      expect(config.requiresBrandQa).toBe(expectedQa);
    }
  });

  it("64 branded chain steps seeded (4 per chain × 16 chains)", async () => {
    const { rows } = await pool.query<{ n: number }>(
      `SELECT count(*)::int AS n
       FROM workflow_template_steps wts
       JOIN workflow_templates wt ON wt.id = wts.template_id
       JOIN workflows w ON w.id = wt.workflow_id
       WHERE w.key LIKE 'cap_branded_%'`
    );
    expect(rows[0].n).toBe(64);
  });

  it("each branded chain has exactly 4 steps in canonical order: content_brief → render → brand_qa → deliver", async () => {
    const { rows } = await pool.query<{
      chain_key: string;
      client_id: string;
      step_keys: string[];
      step_orders: number[];
    }>(
      `SELECT w.key AS chain_key,
              w.client_id::text AS client_id,
              array_agg(wts.step_key ORDER BY wts.step_order) AS step_keys,
              array_agg(wts.step_order ORDER BY wts.step_order) AS step_orders
       FROM workflow_template_steps wts
       JOIN workflow_templates wt ON wt.id = wts.template_id
       JOIN workflows w ON w.id = wt.workflow_id
       WHERE w.key LIKE 'cap_branded_%'
       GROUP BY w.key, w.client_id
       ORDER BY w.client_id, w.key`
    );
    expect(rows).toHaveLength(16);
    for (const r of rows) {
      expect(r.step_keys).toEqual([...EXPECTED_STEP_KEYS]);
      expect(r.step_orders).toEqual([1, 2, 3, 4]);
    }
  });

  it("step assigned_sub_agent_key values match chain spec for both tenants", async () => {
    const { rows } = await pool.query<{
      chain_key: string;
      step_key: string;
      assigned: string;
    }>(
      `SELECT w.key AS chain_key, wts.step_key, wts.assigned_sub_agent_key AS assigned
       FROM workflow_template_steps wts
       JOIN workflow_templates wt ON wt.id = wts.template_id
       JOIN workflows w ON w.id = wt.workflow_id
       WHERE w.key LIKE 'cap_branded_%'`
    );
    for (const r of rows) {
      const [expectedRender] = CHAIN_RENDER_SPEC[r.chain_key];
      switch (r.step_key) {
        case "content_brief":
          expect(r.assigned).toBe("mark_tier_2");
          break;
        case "render":
          expect(r.assigned).toBe(expectedRender);
          break;
        case "brand_qa":
          expect(r.assigned).toBe("darla_tier_2");
          break;
        case "deliver":
          expect(r.assigned).toBe("paul_tier_2");
          break;
        default:
          throw new Error(`unexpected step_key: ${r.step_key}`);
      }
    }
  });

  it("all chain step assigned_sub_agent_key values are llm_configs.agent_role values (or aliases) accepted by Tier-2 routing", async () => {
    // The Eta phase 1.1 corrective pass extended `_normalise_role` to
    // accept these exact `*_tier_2` keys plus shortname aliases. Lock
    // here that every assignment in a branded chain points at a real
    // sub-agent role.
    const { rows } = await pool.query<{ assigned: string; n: number }>(
      `SELECT wts.assigned_sub_agent_key AS assigned, count(*)::int AS n
       FROM workflow_template_steps wts
       JOIN workflow_templates wt ON wt.id = wts.template_id
       JOIN workflows w ON w.id = wt.workflow_id
       WHERE w.key LIKE 'cap_branded_%'
       GROUP BY wts.assigned_sub_agent_key
       ORDER BY assigned`
    );
    const assigned = new Set(rows.map((r) => r.assigned));
    expect(assigned).toEqual(
      new Set([
        "mark_tier_2",
        "tom_tier_2",
        "hank_tier_2",
        "sop_master_tier_2",
        "darla_tier_2",
        "paul_tier_2",
      ])
    );
  });

  it("design-input-source HTML chains carry the correct designInputSource on every step's promptRef", async () => {
    const { rows } = await pool.query<{
      chain_key: string;
      step_key: string;
      prompt_ref: any;
    }>(
      `SELECT w.key AS chain_key, wts.step_key, wts.prompt_ref
       FROM workflow_template_steps wts
       JOIN workflow_templates wt ON wt.id = wts.template_id
       JOIN workflows w ON w.id = wt.workflow_id
       WHERE w.key IN ('cap_branded_html_stitch', 'cap_branded_html_figma', 'cap_branded_html_21st')`
    );
    expect(rows.length).toBe(24); // 3 chains × 4 steps × 2 tenants = 24
    for (const r of rows) {
      const ref = typeof r.prompt_ref === "string" ? JSON.parse(r.prompt_ref) : r.prompt_ref;
      const [, , expectedDesign] = CHAIN_RENDER_SPEC[r.chain_key];
      expect(ref.designInputSource).toBe(expectedDesign);
    }
  });
});
