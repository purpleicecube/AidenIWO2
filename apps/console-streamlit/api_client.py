"""Loop 8 Phase 8.1 — HTTP client for the IWO3 FastAPI runtime.

Wraps every Loop 7 route the Streamlit pages need. Each method returns
a typed Pydantic model or raises a typed exception. The client is
stateless beyond the `headers` attribute, which carries the dev auth
pair `X-IWO3-User` + `X-IWO3-Client` — set by the sidebar picker on
every page render.

No direct DB access. No bypass paths. Streamlit always goes through
the FastAPI gate.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict


DEFAULT_BASE_URL = os.environ.get(
    "IWO3_API_BASE_URL", "http://localhost:8000"
)


class APIError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        detail: Any,
        url: str,
    ) -> None:
        super().__init__(f"APIError {status_code} at {url}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.url = url


class TenantMembership(BaseModel):
    client_id: str
    designation: str
    display_name: str
    deployment_mode: str
    status: str
    role: str
    membership_status: str


class WorkOrderRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    client_id: str
    title: str
    description: Optional[str] = None
    type: str
    priority: str
    status: str
    submitted_by_user_id: Optional[str] = None
    correlation_id: Optional[str] = None
    created_at: str
    updated_at: str


class WorkflowRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    client_id: str
    key: str
    display_name: str
    description: Optional[str] = None
    status: str


class OutputPackageRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    client_id: str
    work_order_id: Optional[str] = None
    output_kind: str
    title: str
    status: str
    created_at: Optional[str] = None


class OutputHandoffRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    client_id: str
    output_package_id: Optional[str] = None
    external_destination: Optional[str] = None
    external_reference: Optional[str] = None
    status: str
    candidate_status: str
    candidate_group_id: Optional[str] = None
    created_at: Optional[str] = None


class AuditRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    client_id: str
    actor_user_id: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    metadata: dict[str, Any]
    created_at: str


class PermissionDecision(BaseModel):
    allowed: bool
    reason: str
    role: Optional[str] = None


class AdapterStatus(BaseModel):
    adapter_key: str
    status: str  # live_confirmed | pending_confirmation | disabled | credential_missing
    env_flag_name: Optional[str] = None
    env_flag_enabled: bool
    credential_id: Optional[str] = None
    credential_ref: Optional[str] = None
    first_invocation_confirmed_at: Optional[str] = None
    notes: Optional[str] = None


class WorkOrderMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")
    total: int
    by_status: dict[str, int]
    reopened_count: int


class ApiClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_id: Optional[str] = None,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers: dict[str, str] = {}
        if access_token:
            self.set_bearer_token(access_token)
        else:
            if user_id:
                self._headers["X-IWO3-User"] = user_id
            if client_id:
                self._headers["X-IWO3-Client"] = client_id

    def set_auth(self, user_id: str, client_id: str) -> None:
        self._headers.pop("Authorization", None)
        self._headers["X-IWO3-User"] = user_id
        self._headers["X-IWO3-Client"] = client_id

    def set_bearer_token(self, access_token: str) -> None:
        self._headers.pop("X-IWO3-User", None)
        self._headers.pop("X-IWO3-Client", None)
        self._headers["Authorization"] = f"Bearer {access_token}"

    def clear_auth(self) -> None:
        self._headers.clear()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            r = httpx.request(
                method,
                url,
                params=params,
                json=json,
                headers=self._headers,
                timeout=10.0,
            )
        except httpx.HTTPError as err:
            raise APIError(
                status_code=0, detail=f"http error: {err}", url=url
            )
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:  # noqa: BLE001
                detail = r.text
            raise APIError(status_code=r.status_code, detail=detail, url=url)
        return r.json()

    # ---- tenants ----

    def list_tenants(self) -> list[TenantMembership]:
        data = self._request("GET", "/tenants")
        return [TenantMembership(**t) for t in data["tenants"]]

    def login(
        self, *, email: str, password: str, client_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/auth/login",
            json={
                "email": email,
                "password": password,
                "client_id": client_id,
            },
        )

    def logout(self, *, refresh_token: Optional[str] = None) -> dict[str, Any]:
        payload = (
            {"refresh_token": refresh_token}
            if refresh_token
            else {}
        )
        return self._request("POST", "/auth/logout", json=payload)

    # ---- work_orders ----

    def list_work_orders(self) -> list[WorkOrderRow]:
        data = self._request("GET", "/work_orders")
        return [WorkOrderRow(**w) for w in data["work_orders"]]

    def get_work_order(self, wo_id: str) -> WorkOrderRow:
        data = self._request("GET", f"/work_orders/{wo_id}")
        return WorkOrderRow(**data)

    def work_order_metrics(self) -> WorkOrderMetrics:
        data = self._request("GET", "/work_orders/metrics")
        return WorkOrderMetrics(**data)

    # ---- Loop 9 Phase 9.5 — adapter status (Design Lab) ----

    def get_adapter_status(self, adapter_key: str) -> AdapterStatus:
        data = self._request("GET", f"/adapter_status/{adapter_key}")
        return AdapterStatus(**data)

    def create_work_order(
        self,
        *,
        title: str,
        description: Optional[str],
        wo_type: str,
        priority: str,
        correlation_id: Optional[str],
        output_kind: Optional[str] = None,
        template_profile_id: Optional[str] = None,
    ) -> dict:
        body = {
            "title": title,
            "description": description,
            "type": wo_type,
            "priority": priority,
            "correlation_id": correlation_id,
        }
        if output_kind is not None:
            body["output_kind"] = output_kind
        if template_profile_id is not None:
            body["template_profile_id"] = template_profile_id
        return self._request("POST", "/work_orders", json=body)

    def list_template_profiles(
        self,
        *,
        status: Optional[str] = "active",
        output_kind: Optional[str] = None,
    ) -> list[dict]:
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status
        if output_kind is not None:
            params["output_kind"] = output_kind
        data = self._request("GET", "/template_profiles", params=params)
        return data.get("template_profiles", [])

    def transition_work_order(
        self, wo_id: str, to: str, reason: Optional[str] = None
    ) -> dict:
        return self._request(
            "POST",
            f"/work_orders/{wo_id}/transition",
            json={"to": to, "reason": reason},
        )

    def watchdog_expire(self, wo_id: str, reason: str) -> dict:
        return self._request(
            "POST",
            f"/work_orders/{wo_id}/watchdog_expire",
            json={"reason": reason},
        )

    # ---- workflows ----

    def list_workflows(self) -> list[WorkflowRow]:
        data = self._request("GET", "/workflows")
        return [WorkflowRow(**w) for w in data["workflows"]]

    def transition_workflow(
        self, wf_id: str, to: str, reason: Optional[str] = None
    ) -> dict:
        return self._request(
            "POST",
            f"/workflows/{wf_id}/transition",
            json={"to": to, "reason": reason},
        )

    # ---- output packages / handoffs ----

    def list_output_packages(self) -> list[OutputPackageRow]:
        data = self._request("GET", "/output_packages")
        return [OutputPackageRow(**p) for p in data["output_packages"]]

    def list_output_handoffs(self) -> list[OutputHandoffRow]:
        data = self._request("GET", "/output_handoffs")
        return [OutputHandoffRow(**h) for h in data["output_handoffs"]]

    def select_candidate(
        self, handoff_id: str, reason: Optional[str] = None
    ) -> dict:
        return self._request(
            "POST",
            f"/output_handoffs/{handoff_id}/select_candidate",
            json={"reason": reason},
        )

    def reject_candidate(
        self, handoff_id: str, reason: Optional[str] = None
    ) -> dict:
        return self._request(
            "POST",
            f"/output_handoffs/{handoff_id}/reject_candidate",
            json={"reason": reason},
        )

    # ---- audit log / permissions ----

    def list_audit_log(
        self,
        work_order_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[AuditRow]:
        params: dict[str, Any] = {"limit": limit}
        if work_order_id:
            params["work_order_id"] = work_order_id
        data = self._request("GET", "/audit_log", params=params)
        return [AuditRow(**r) for r in data["audit_rows"]]

    def check_permission(self, permission: str) -> PermissionDecision:
        data = self._request(
            "GET", "/permissions/check", params={"permission": permission}
        )
        return PermissionDecision(**data)

    # ---- Alpha α.7 — Aiden chat + LLM configs + channel ops ----

    def aiden_chat(self, message: str) -> dict[str, Any]:
        return self._request("POST", "/aiden/chat", json={"message": message})

    def list_llm_configs(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/llm/configs")
        return data["configs"]

    # ── MegaLoop Theta — Tools Locker ──────────────────────────────

    def list_tool_catalog(
        self,
        *,
        enabled: bool = True,
        category: Optional[str] = None,
        runtime_status: Optional[str] = None,
        default_tier: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"enabled": str(enabled).lower()}
        if category:
            params["category"] = category
        if runtime_status:
            params["runtime_status"] = runtime_status
        if default_tier:
            params["default_tier"] = default_tier
        data = self._request("GET", "/tool_catalog", params=params)
        return data["tools"]

    def create_tool(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/tool_catalog", json=body)

    def update_tool(
        self, tool_key: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request("PUT", f"/tool_catalog/{tool_key}", json=body)

    def delete_tool(self, tool_key: str) -> None:
        self._request("DELETE", f"/tool_catalog/{tool_key}")

    def list_available_skills(self) -> dict[str, Any]:
        return self._request("GET", "/skills/available")

    def import_skill(
        self,
        *,
        dir_name: str,
        name_override: Optional[str] = None,
        description_override: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"dir_name": dir_name}
        if name_override:
            body["name_override"] = name_override
        if description_override:
            body["description_override"] = description_override
        return self._request("POST", "/tool_catalog/import_skill", json=body)

    def test_mcp_connection(self, mcp_config: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/tool_catalog/mcp/test_connection",
            json={"mcp_config": mcp_config},
        )

    def list_llm_providers(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/llm/providers")
        return data["providers"]

    def list_provider_models(self, *, provider: str) -> dict[str, Any]:
        """GET /llm/models?provider=X.

        Returns `{provider, keyConfigured, models, error?}`. Empty
        models with keyConfigured=false means the caller should fall
        back to manual text input — matches IWO2's ModelSelector.
        """
        return self._request("GET", "/llm/models", params={"provider": provider})

    def test_llm(
        self, *, agent_role: str, user_message: str = "ping"
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/llm/test",
            json={"agent_role": agent_role, "user_message": user_message},
        )

    def issue_channel_auth_code(
        self, *, channel_kind: str, ttl_minutes: int = 15
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/channel/auth_codes",
            json={"channel_kind": channel_kind, "ttl_minutes": ttl_minutes},
        )

    def list_channel_identities(
        self,
        *,
        channel_kind: Optional[str] = None,
        only_active: bool = True,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"only_active": str(only_active).lower()}
        if channel_kind:
            params["channel_kind"] = channel_kind
        data = self._request("GET", "/channel/identities", params=params)
        return data["identities"]

    def revoke_channel_identity(self, identity_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/channel/identities/{identity_id}/revoke"
        )

    # ---- Pre-Beta β.2 — LLM config CRUD ----

    def create_llm_config(self, **fields: Any) -> dict[str, Any]:
        return self._request("POST", "/llm/configs", json=fields)

    def update_llm_config(
        self, config_id: str, **fields: Any
    ) -> dict[str, Any]:
        return self._request(
            "PATCH", f"/llm/configs/{config_id}", json=fields
        )

    def delete_llm_config(
        self, config_id: str, hard: bool = False
    ) -> dict[str, Any]:
        params = {"hard": "true"} if hard else None
        return self._request(
            "DELETE", f"/llm/configs/{config_id}", params=params
        )

    # ---- Beta-2 phase 0.3 — load + version + rollback ----

    def get_llm_config_prompt(self, config_id: str) -> dict[str, Any]:
        """Writer-gated read of the actual system_prompt body for editor pre-fill."""
        return self._request("GET", f"/llm/configs/{config_id}/prompt")

    def list_llm_config_versions(
        self, config_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/llm/configs/{config_id}/versions",
            params={"limit": str(limit)},
        )
        return data.get("versions", [])

    def rollback_llm_config(
        self,
        config_id: str,
        *,
        version_id: str,
        change_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"version_id": version_id}
        if change_reason is not None:
            body["change_reason"] = change_reason
        return self._request(
            "POST", f"/llm/configs/{config_id}/rollback", json=body
        )

    # ---- Pre-Beta β.3 — dispatch ----

    def dispatch_work_order(
        self, wo_id: str, intake_override: Optional[str] = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if intake_override:
            body["intake_override"] = intake_override
        return self._request(
            "POST", f"/work_orders/{wo_id}/dispatch", json=body
        )

    def run_next_workflow_step(self, execution_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/workflows/{execution_id}/run_next_step"
        )

    def render_work_order(self, wo_id: str) -> dict[str, Any]:
        """Beta-2 phase 0.2 — submit the WO's latest gamma_* output_package
        to Gamma + create the handoff. Idempotent: 409 if already in flight."""
        return self._request("POST", f"/work_orders/{wo_id}/render", json={})

    # ---- Beta-1 ε.2 — operator chat persistence ----

    def get_my_chat_session(self) -> dict[str, Any]:
        return self._request("GET", "/chat_sessions/me")

    def put_my_chat_session(
        self, *, messages: list[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            "/chat_sessions/me",
            json={"messages": messages, "context": context},
        )

    def clear_my_chat_session(self) -> dict[str, Any]:
        return self._request("DELETE", "/chat_sessions/me")

    # ---- Beta-1.5 phase 2 — tenant settings + personas + scratch ----

    def get_my_tenant_settings(self) -> dict[str, Any]:
        return self._request("GET", "/tenants/me/settings")

    def update_my_tenant_settings(
        self,
        *,
        llm_per_wo_ceiling: Optional[int] = None,
        revert_to_default: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"revert_to_default": revert_to_default}
        if llm_per_wo_ceiling is not None:
            body["llm_per_wo_ceiling"] = llm_per_wo_ceiling
        return self._request("PATCH", "/tenants/me/settings", json=body)

    def list_personas(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/llm/personas")
        return data["personas"]

    def get_workspace_tree(self) -> dict[str, Any]:
        return self._request("GET", "/workspace/tree")

    def get_workspace_folder(self, folder_id: str) -> dict[str, Any]:
        return self._request("GET", f"/workspace/folders/{folder_id}")

    def get_workspace_file_content(self, file_id: str) -> dict[str, Any]:
        return self._request("GET", f"/workspace/files/{file_id}/content")

    def create_or_get_scratch_folder(self) -> dict[str, Any]:
        return self._request("POST", "/workspace/folders/scratch")

    # ---- Loop Eta phase 1 — tool catalog + sub-agent tool assignments ----

    def list_tool_catalog(
        self,
        *,
        category: Optional[str] = None,
        runtime_status: Optional[str] = None,
        default_tier: Optional[str] = None,
        enabled: bool = True,
    ) -> list[dict[str, Any]]:
        """GET /tool_catalog. Returns the global tool catalog rows.

        All filters optional. `enabled=True` (default) hides retired
        tools; pass `enabled=False` to inspect only retired rows.
        """
        params: dict[str, Any] = {"enabled": str(enabled).lower()}
        if category is not None:
            params["category"] = category
        if runtime_status is not None:
            params["runtime_status"] = runtime_status
        if default_tier is not None:
            params["default_tier"] = default_tier
        data = self._request("GET", "/tool_catalog", params=params)
        return data.get("tools", [])

    def get_sub_agent_tools(self, llm_config_id: str) -> dict[str, Any]:
        """GET /llm/configs/{id}/tools.

        Returns ``{llm_config_id, agent_role, tools: [...]}`` where each
        tool row carries both its catalog metadata and the assignment
        state (`assigned`, `enabled`, `granted_at`, etc.). Unassigned
        tools surface with ``assigned=false, enabled=false``.
        """
        return self._request(
            "GET", f"/llm/configs/{llm_config_id}/tools"
        )

    def set_sub_agent_tool(
        self,
        llm_config_id: str,
        tool_key: str,
        *,
        enabled: bool,
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        """PUT /llm/configs/{id}/tools/{tool_key} — toggle assignment.

        Returns the upserted ``sub_agent_tools`` row. Setting
        ``enabled=False`` is the soft-revoke path (the row stays for
        history). There is no DELETE endpoint.
        """
        body: dict[str, Any] = {"enabled": enabled}
        if notes is not None:
            body["notes"] = notes
        return self._request(
            "PUT",
            f"/llm/configs/{llm_config_id}/tools/{tool_key}",
            json=body,
        )

    def get_sub_agent_tool_history(
        self,
        llm_config_id: str,
        *,
        limit: int = 25,
    ) -> dict[str, Any]:
        """GET /llm/configs/{id}/tool_history.

        Returns recent runtime tool events scoped to one llm_config.
        This is narrower than the global audit log and intended for the
        Sub-Agents modal's Tool History tab.
        """
        return self._request(
            "GET",
            f"/llm/configs/{llm_config_id}/tool_history",
            params={"limit": limit},
        )

    # ── Loop Eta phase 1.1 — Stitch MCP runtime probe ────────────────

    def test_stitch_connection(self) -> dict[str, Any]:
        """GET /tools/stitch_design/test_connection.

        Opens the Stitch MCP stdio session, enumerates the server's
        tool catalog, closes the session, and returns
        ``{ok, server_name, tool_count, latency_ms, sample_tool_names}``
        on success. On any failure (config_missing, spawn_failed,
        handshake_failed, timeout) the route returns 503 + a JSON body
        with ``ok=false, error, kind``; this helper surfaces that body
        through the standard ``APIError`` path so callers can decide
        whether to retry or surface the diagnostic verbatim.
        """
        return self._request(
            "GET", "/tools/stitch_design/test_connection"
        )

    # ── Loop Kappa — Memory V1.5 canonical facts CRUD ───────────────

    def list_canonical_facts(
        self, *, include_inactive: bool = False
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/canonical_facts",
            params={"include_inactive": "true" if include_inactive else "false"},
        )

    def create_canonical_fact(
        self, *, body: str, severity: str = "medium"
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/canonical_facts",
            json={"body": body, "severity": severity},
        )

    def update_canonical_fact(
        self,
        fact_id: str,
        *,
        body: Optional[str] = None,
        severity: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if severity is not None:
            payload["severity"] = severity
        if is_active is not None:
            payload["is_active"] = is_active
        return self._request(
            "PATCH",
            f"/canonical_facts/{fact_id}",
            json=payload,
        )

    def delete_canonical_fact(self, fact_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/canonical_facts/{fact_id}")
