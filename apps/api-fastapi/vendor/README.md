# IWO3 FastAPI vendor/

Bundled Node-side dependencies for the IWO3 FastAPI runtime.

## What lives here

- `stitch-mcp-proxy.mjs` — Stitch MCP stdio proxy (vendored from IWO2's
  `server/stitch-mcp-proxy.mjs`, originally Loop 33 / 2026-03-29).
  Bridges `@google/stitch-sdk` into a stdio MCP server that
  `runtime/mcp_client.py:McpSession.open()` can spawn as a child process.
- `package.json` — npm manifest pinning `@google/stitch-sdk@^0.0.3`
  and `@modelcontextprotocol/sdk@^1.27.1` (same versions IWO2 ships).

## Why vendored instead of imported from IWO2

The IWO3 FastAPI Docker image (`apps/api-fastapi/Dockerfile`) needs the
Stitch proxy + its npm deps **available inside the container** so that
Railway / Streamlit Cloud deploys can run the MCP integration without:

1. needing a sidecar container, or
2. assuming an IWO2 checkout exists at `/home/virgina/VS_AIDEN_IWO2/server/...`
   (it doesn't on Railway), or
3. asking the operator to set `STITCH_MCP_COMMAND` to a path that's
   different on every deploy.

By vendoring the script + pinning the npm deps, the Dockerfile sets a
known default `STITCH_MCP_COMMAND` of
`node /app/apps/api-fastapi/vendor/stitch-mcp-proxy.mjs` that resolves
inside the image. Operators can still override via the Railway env
variable for special cases.

## Drift from IWO2

If IWO2 updates `server/stitch-mcp-proxy.mjs` or its npm pins, this
vendor copy can drift. Re-vendor with:

```bash
cp /path/to/IWO2/server/stitch-mcp-proxy.mjs apps/api-fastapi/vendor/
# update apps/api-fastapi/vendor/package.json with the new version pins
# (find them via: jq '.dependencies' /path/to/IWO2/package.json |
#   grep -E '@google/stitch-sdk|@modelcontextprotocol/sdk')
docker build -f apps/api-fastapi/Dockerfile -t iwo3-api .
```

Authored: Loop Eta phase 1.3 (post-close hosting parity push), 2026-05-02.
