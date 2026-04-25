# IWO3 Risk Register v0.2.3

Date: 2026-04-25
Predecessor: v0.2.2 (Alpha Closeout γ).
Closeout: Pre-Beta Product Surface Remediation Loop δ.8.

## Active risks (carried)

R-021..R-031 carried unchanged from v0.2.2. See `RISK_REGISTER_v0.2.2.md`.

## New (δ-introduced) risks

### R-034 [S2] (NEW) Drag-drop dependency requires PyPI install
The δ.4 Workspace UI imports `streamlit-sortables` to satisfy the architect's "drag-drop required" lock. The dep is in `pyproject.toml` but the offline sandbox could not run `uv sync` to install it. The UI code-paths handle both states; the operator must install the dep once on a network-connected host to flip the literal drag-drop on.

**Mitigation:** Fallback path is a fully-functional explicit "Move to…" UI; `_SORTABLES_AVAILABLE` flag in views/workspace.py drives the UI banner so operators always see which mode is active.

### R-035 [S3] (NEW) Workspace file content cannot be fetched in this loop
Files created via `/workspace/files` store content inline in `artifacts.extracted_text`, but no `GET /workspace/files/{id}/content` route exists yet. The Workspace UI displays file metadata + storage_ref but cannot render full content. `output_package://` referenced files render a "use Output Packages" pointer.

**Mitigation:** Outputs page (Output Packages) is the canonical surface for output content. Inline workspace-created files are mostly notes/scratch — full preview is Beta scope.

### R-036 [S3] (NEW) Workspace soft-deleted folders accumulate
Folder soft-delete sets `deleted_at` but leaves the row + all child folders + nested artifacts in place. Hard delete is operator-explicit (Beta scope). Pathological accumulation could grow the table.

**Mitigation:** Per-tenant table sizes are bounded by operator action volume; not a real Alpha concern. Beta adds a hard-delete admin action.

## Retired (resolved by δ closure)

### R-old-11 [retired] Workspace was a placeholder / activity dashboard
Resolved by δ.1+δ.2+δ.4 — real folders + files + nested tree + auto-saved outputs.

### R-old-12 [retired] Aiden persona was an α-era short stub
Resolved by δ.5 — IWO2 voice ported with explicit sub-agent enumeration; live model produces well-shaped briefs.

### R-old-13 [retired] Outputs had no operator-discoverable home
Resolved by δ.3 (auto-routing) + γ.3 (Output Packages polish) + δ.4 (Workspace UI).

## Process notes

The register is reviewed at every loop closeout. v0.3.0 expected at the end of MegaLoop Beta and will retire R-021, R-024, R-028 if Beta lands per-tenant overrides + production auth + `/health/channels`. R-034 retires when the dep install is verified post-network.
