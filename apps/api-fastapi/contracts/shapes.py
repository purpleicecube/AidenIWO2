"""Loop 5 Phase 5.2 — Python TypedDicts for API-boundary shapes.

These are the rows FastAPI (Loop 7) will serialise into JSON
responses. They mirror the Drizzle-inferred TS shapes but are
hand-maintained on the Python side because TS types don't compile
to Python — the parity story for shapes is:

  - Enums: byte-identical via ``tests/contract/enum-parity.test.ts``.
  - Shapes: structural parity reviewed by humans at PR time. A future
    loop may add a structural parity test that dumps both sides and
    diffs (Loop 7 candidate).

Scope (per Loop 5 scope proposal §3.2):
  - WorkOrderRow, WorkflowRow, WorkflowExecutionRow, OutputPackageRow,
    OutputHandoffRow, AuditRow, PermissionDecision, DispatchInput,
    DispatchResult variants.

Internal-only TS types are NOT mirrored — only the rows that cross
the HTTP boundary.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from contracts.enums import (
    MembershipRole,
    OutputHandoffStatus,
    OutputPackageKind,
    OutputPackageStatus,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkflowExecutionStatus,
    WorkflowStatus,
)

# --- Row shapes (Loop 7 response bodies) ------------------------------


class WorkOrderRow(TypedDict):
    id: str
    client_id: str
    title: str
    description: NotRequired[str | None]
    type: str
    priority: WorkOrderPriority
    status: WorkOrderStatus
    submitted_by_user_id: NotRequired[str | None]
    correlation_id: NotRequired[str | None]
    deferred_until: NotRequired[str | None]
    deferred_reason: NotRequired[str | None]
    created_at: str
    updated_at: str


class WorkflowRow(TypedDict):
    id: str
    client_id: str
    key: str
    display_name: str
    description: NotRequired[str | None]
    status: WorkflowStatus
    created_at: str
    updated_at: str


class WorkflowExecutionRow(TypedDict):
    id: str
    client_id: str
    workflow_id: str
    template_id: str
    status: WorkflowExecutionStatus
    started_at: NotRequired[str | None]
    completed_at: NotRequired[str | None]
    correlation_id: NotRequired[str | None]


class OutputPackageRow(TypedDict):
    id: str
    client_id: str
    work_order_id: NotRequired[str | None]
    workflow_execution_id: NotRequired[str | None]
    output_kind: OutputPackageKind
    title: str
    summary: NotRequired[str | None]
    status: OutputPackageStatus
    template_profile_id: NotRequired[str | None]
    correlation_id: NotRequired[str | None]
    created_by_user_id: NotRequired[str | None]
    created_at: str
    updated_at: str


class OutputHandoffRow(TypedDict):
    id: str
    client_id: str
    output_package_id: str
    external_destination: NotRequired[str | None]
    external_reference: NotRequired[str | None]
    status: OutputHandoffStatus
    result_payload_ref: NotRequired[str | None]
    correlation_id: NotRequired[str | None]
    created_at: str
    updated_at: str


class AuditRow(TypedDict):
    id: str
    client_id: str
    actor_user_id: NotRequired[str | None]
    action: str  # one of AUDIT_EVENTS values; not typed as Literal
    # because the event vocabulary grows additively per loop.
    target_type: NotRequired[str | None]
    target_id: NotRequired[str | None]
    metadata: dict[str, Any]
    created_at: str


# --- Authz boundary shapes (from TS checkPermission / requirePermission) ----


class PermissionDecision(TypedDict):
    allowed: bool
    reason: Literal[
        "role_default",
        "allow_override",
        "deny_override",
        "no_membership",
        "role_lacks_permission",
        "unknown_permission",
    ]
    role: MembershipRole | None


# --- Dispatcher boundary shapes (from TS adapter/registry) ---------------


class DispatchInput(TypedDict):
    client_id: str
    adapter_key: str
    action_key: str
    output_package_id: str
    actor_user_id: NotRequired[str | None]
    work_order_id: NotRequired[str | None]
    workflow_id: NotRequired[str | None]
    execution_cycle_id: NotRequired[str | None]
    deployment_id: NotRequired[str | None]
    approval_ref: NotRequired[str | None]
    correlation_id: NotRequired[str | None]


class DispatchResultCompleted(TypedDict):
    status: Literal["completed"]
    handoff_id: str
    external_reference: str
    result_payload_ref: str | None


class DispatchResultPermissionDenied(TypedDict):
    status: Literal["permission_denied"]
    reason: str
    role: MembershipRole | None


class DispatchResultRejectedPolicy(TypedDict):
    status: Literal["rejected_policy"]
    reason: str


class DispatchResultApprovalRequired(TypedDict):
    status: Literal["approval_required"]
    reason: str


class DispatchResultPackageInvalid(TypedDict):
    status: Literal["package_invalid"]
    errors: list[str]


class DispatchResultAdapterNotFound(TypedDict):
    status: Literal["adapter_not_found"]
    adapter_key: str


class DispatchResultFailed(TypedDict):
    status: Literal["failed"]
    handoff_id: str | None
    error_message: str


# Union — FastAPI will discriminate on `.status`
DispatchResult = (
    DispatchResultCompleted
    | DispatchResultPermissionDenied
    | DispatchResultRejectedPolicy
    | DispatchResultApprovalRequired
    | DispatchResultPackageInvalid
    | DispatchResultAdapterNotFound
    | DispatchResultFailed
)
