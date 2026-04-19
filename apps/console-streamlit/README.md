# IWO3 Streamlit Operator Console

Placeholder. Pages and visual implementation land in Loop 8 per the
Streamlit/UI Agent scope in `IWO3_SUBAGENT_WORKPLAN_v0.1.0.md`.

**Continuity rule.** Must preserve IWO2 look and feel per
`docs/ui/iwo2-tokens.json` and `docs/ui/status-semantics.json`.

**Architectural rule.** Streamlit must only call FastAPI (`apps/api-fastapi`)
through a typed client at `api_client.py`. No direct DB access, no webhook
ownership, no privileged state transitions.
