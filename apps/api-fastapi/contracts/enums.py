"""Loop 5 Phase 5.2 — Python mirror of Postgres enum vocabulary.

Byte-identical with the TS frozen snapshot at
``tests/fixtures/contract-enums.snapshot.json``. Parity is enforced by
``tests/contract/enum-parity.test.ts`` which spawns the CLI at
``apps/api-fastapi/contracts/enum_dump.py`` and compares byte-for-byte
with the TS snapshot.

Usage in FastAPI handlers (Loop 7):

    from contracts.enums import MEMBERSHIP_ROLE, WORK_ORDER_STATUS

    if role not in MEMBERSHIP_ROLE:
        raise ValueError(f"unknown role: {role}")

    from contracts.enums import MembershipRole
    def greet(role: MembershipRole) -> str: ...

Policy: every enum here is authoritative Python; any change must
also update the TS snapshot in the same commit or CI fails.
"""

from __future__ import annotations

from typing import Final, Literal

ADAPTER_CATALOG_STATUS: Final[tuple[str, ...]] = ('active', 'beta', 'deprecated',)
ADAPTER_CATEGORY: Final[tuple[str, ...]] = ('design_render', 'storage', 'campaign', 'crm', 'other',)
ADAPTER_CREDENTIAL_STATUS: Final[tuple[str, ...]] = ('active', 'rotation_due', 'revoked', 'expired',)
ADAPTER_POLICY_MODE: Final[tuple[str, ...]] = ('none', 'approval_required', 'disallowed',)
ARTIFACT_CONTENT_CLASS: Final[tuple[str, ...]] = ('c0', 'c1', 'c2', 'c3',)
ARTIFACT_SOURCE_TYPE: Final[tuple[str, ...]] = ('upload', 'generated', 'imported',)
CLIENT_ADAPTER_CONFIG_STATUS: Final[tuple[str, ...]] = ('active', 'paused', 'revoked',)
CLIENT_STATUS: Final[tuple[str, ...]] = ('active', 'suspended',)
DATA_SOURCE_BINDING_STATUS: Final[tuple[str, ...]] = ('active', 'paused', 'revoked',)
DATA_SOURCE_CONNECTOR_TYPE: Final[tuple[str, ...]] = ('postgres', 'bigquery', 'snowflake', 'sheets', 'rest_api', 'custom',)
DEPLOYMENT_MODE: Final[tuple[str, ...]] = ('dedicated_single_client', 'shared_multi_tenant', 'hybrid',)
EXECUTION_CYCLE_TRIGGER: Final[tuple[str, ...]] = ('new', 'retry', 'reopen', 'unblock', 'watchdog', 'admin_repair', 'candidate_request_more', 'auto_dispatch',)
EXTERNAL_EXECUTION_RESULT_STATUS: Final[tuple[str, ...]] = ('success', 'partial', 'failed', 'unknown',)
FALLBACK_POLICY: Final[tuple[str, ...]] = ('none', 'allowed_with_approval', 'allowed',)
MANIFEST_OWNER: Final[tuple[str, ...]] = ('drizzle', 'alembic',)
MANIFEST_SOURCE: Final[tuple[str, ...]] = ('iwo2_parity', 'iwo3_native',)
MEMBERSHIP_ROLE: Final[tuple[str, ...]] = ('owner', 'admin', 'operator', 'reviewer', 'viewer', 'agent_system',)
MEMBERSHIP_STATUS: Final[tuple[str, ...]] = ('active', 'revoked',)
OUTPUT_HANDOFF_CANDIDATE_STATUS: Final[tuple[str, ...]] = ('not_candidate', 'candidate', 'selected', 'rejected', 'finalized',)
OUTPUT_HANDOFF_STATUS: Final[tuple[str, ...]] = ('queued', 'submitted', 'accepted', 'completed', 'failed', 'cancelled',)
OUTPUT_KIND: Final[tuple[str, ...]] = ('pptx', 'pdf', 'other',)
OUTPUT_PACKAGE_KIND: Final[tuple[str, ...]] = ('gamma_pptx', 'gamma_pdf', 'sandbox_pptx', 'sandbox_pdf', 'email_campaign', 'drive_upload', 'crm_mutation', 'figma_handoff', 'stitch_handoff', 'designlab_handoff', 'generic',)
OUTPUT_PACKAGE_STATUS: Final[tuple[str, ...]] = ('draft', 'validated', 'rejected', 'submitted', 'delivered', 'failed', 'cancelled',)
PERMISSION_GRANT_TYPE: Final[tuple[str, ...]] = ('allow', 'deny',)
PERMISSION_SCOPE: Final[tuple[str, ...]] = ('global', 'tenant', 'resource',)
PROMPT_PROFILE_SCOPE: Final[tuple[str, ...]] = ('client', 'workflow', 'wo',)
PROMPT_PROFILE_STATUS: Final[tuple[str, ...]] = ('active', 'archived',)
PROMPT_VERSION_STATUS: Final[tuple[str, ...]] = ('draft', 'published', 'deprecated',)
RENDER_ENGINE: Final[tuple[str, ...]] = ('gamma', 'gamma_basic', 'sandbox_pptx', 'sandbox_pdf', 'designlab',)
REPOSITORY_BINDING_STATUS: Final[tuple[str, ...]] = ('active', 'paused', 'revoked',)
REPOSITORY_CONNECTOR_TYPE: Final[tuple[str, ...]] = ('google_drive', 'dropbox', 'github', 's3', 'local', 'custom',)
TEMPLATE_PROFILE_STATUS: Final[tuple[str, ...]] = ('active', 'archived',)
USER_STATUS: Final[tuple[str, ...]] = ('active', 'disabled',)
WORK_ORDER_PRIORITY: Final[tuple[str, ...]] = ('low', 'medium', 'high', 'critical',)
WORK_ORDER_STATUS: Final[tuple[str, ...]] = ('pending', 'processing', 'blocked', 'awaiting_operator', 'completed', 'done', 'failed', 'deferred', 'cancelled',)
WORKFLOW_EXECUTION_STATUS: Final[tuple[str, ...]] = ('pending', 'running', 'completed', 'failed', 'cancelled',)
WORKFLOW_STATUS: Final[tuple[str, ...]] = ('active', 'paused', 'archived',)
WORKFLOW_STEP_RUN_STATUS: Final[tuple[str, ...]] = ('pending', 'running', 'completed', 'failed', 'skipped',)
WORKFLOW_TEMPLATE_STATUS: Final[tuple[str, ...]] = ('draft', 'published', 'deprecated',)

# --- Literal type aliases (for Pydantic / FastAPI response models) ---

AdapterCatalogStatus = Literal['active', 'beta', 'deprecated']
AdapterCategory = Literal['design_render', 'storage', 'campaign', 'crm', 'other']
AdapterCredentialStatus = Literal['active', 'rotation_due', 'revoked', 'expired']
AdapterPolicyMode = Literal['none', 'approval_required', 'disallowed']
ArtifactContentClass = Literal['c0', 'c1', 'c2', 'c3']
ArtifactSourceType = Literal['upload', 'generated', 'imported']
ClientAdapterConfigStatus = Literal['active', 'paused', 'revoked']
ClientStatus = Literal['active', 'suspended']
DataSourceBindingStatus = Literal['active', 'paused', 'revoked']
DataSourceConnectorType = Literal['postgres', 'bigquery', 'snowflake', 'sheets', 'rest_api', 'custom']
DeploymentMode = Literal['dedicated_single_client', 'shared_multi_tenant', 'hybrid']
ExecutionCycleTrigger = Literal['new', 'retry', 'reopen', 'unblock', 'watchdog', 'admin_repair', 'candidate_request_more']
ExternalExecutionResultStatus = Literal['success', 'partial', 'failed', 'unknown']
FallbackPolicy = Literal['none', 'allowed_with_approval', 'allowed']
ManifestOwner = Literal['drizzle', 'alembic']
ManifestSource = Literal['iwo2_parity', 'iwo3_native']
MembershipRole = Literal['owner', 'admin', 'operator', 'reviewer', 'viewer', 'agent_system']
MembershipStatus = Literal['active', 'revoked']
OutputHandoffCandidateStatus = Literal['not_candidate', 'candidate', 'selected', 'rejected', 'finalized']
OutputHandoffStatus = Literal['queued', 'submitted', 'accepted', 'completed', 'failed', 'cancelled']
OutputKind = Literal['pptx', 'pdf', 'other']
OutputPackageKind = Literal['gamma_pptx', 'gamma_pdf', 'sandbox_pptx', 'sandbox_pdf', 'email_campaign', 'drive_upload', 'crm_mutation', 'figma_handoff', 'stitch_handoff', 'designlab_handoff', 'generic']
OutputPackageStatus = Literal['draft', 'validated', 'rejected', 'submitted', 'delivered', 'failed', 'cancelled']
PermissionGrantType = Literal['allow', 'deny']
PermissionScope = Literal['global', 'tenant', 'resource']
PromptProfileScope = Literal['client', 'workflow', 'wo']
PromptProfileStatus = Literal['active', 'archived']
PromptVersionStatus = Literal['draft', 'published', 'deprecated']
RenderEngine = Literal['gamma', 'gamma_basic', 'sandbox_pptx', 'sandbox_pdf', 'designlab']
RepositoryBindingStatus = Literal['active', 'paused', 'revoked']
RepositoryConnectorType = Literal['google_drive', 'dropbox', 'github', 's3', 'local', 'custom']
TemplateProfileStatus = Literal['active', 'archived']
UserStatus = Literal['active', 'disabled']
WorkOrderPriority = Literal['low', 'medium', 'high', 'critical']
WorkOrderStatus = Literal['pending', 'processing', 'blocked', 'awaiting_operator', 'completed', 'done', 'failed', 'deferred', 'cancelled']
WorkflowExecutionStatus = Literal['pending', 'running', 'completed', 'failed', 'cancelled']
WorkflowStatus = Literal['active', 'paused', 'archived']
WorkflowStepRunStatus = Literal['pending', 'running', 'completed', 'failed', 'skipped']
WorkflowTemplateStatus = Literal['draft', 'published', 'deprecated']

# MegaLoop Alpha α.5 — channel layer enums
CHANNEL_KIND: Final[tuple[str, ...]] = ('telegram', 'slack', 'email', 'sms')
CHANNEL_IDENTITY_STATUS: Final[tuple[str, ...]] = ('active', 'revoked')
CHANNEL_AUTH_CODE_STATUS: Final[tuple[str, ...]] = (
    'pending', 'consumed', 'expired', 'revoked'
)
CHANNEL_MESSAGE_DIRECTION: Final[tuple[str, ...]] = ('inbound', 'outbound')
CHANNEL_MESSAGE_STATUS: Final[tuple[str, ...]] = (
    'received', 'processed', 'failed', 'pending', 'sent'
)
ChannelKind = Literal['telegram', 'slack', 'email', 'sms']
ChannelIdentityStatus = Literal['active', 'revoked']
ChannelAuthCodeStatus = Literal[
    'pending', 'consumed', 'expired', 'revoked'
]
ChannelMessageDirection = Literal['inbound', 'outbound']
ChannelMessageStatus = Literal[
    'received', 'processed', 'failed', 'pending', 'sent'
]

# Loop Eta phase 0 — tool catalog + sub-agent tools
TOOL_CATEGORY: Final[tuple[str, ...]] = (
    'search', 'document', 'rendering', 'design', 'data', 'ops',
    'introspection', 'skill_only',
)
TOOL_RUNTIME_STATUS: Final[tuple[str, ...]] = (
    'runnable', 'skill_only', 'mcp', 'planned',
)
TOOL_DEFAULT_TIER: Final[tuple[str, ...]] = (
    'tier_1', 'tier_2', 'either',
)
ToolCategory = Literal[
    'search', 'document', 'rendering', 'design', 'data', 'ops',
    'introspection', 'skill_only',
]
ToolRuntimeStatus = Literal[
    'runnable', 'skill_only', 'mcp', 'planned',
]
ToolDefaultTier = Literal['tier_1', 'tier_2', 'either']

# --- Registry — enables run-time introspection and the parity CLI ---

ALL_ENUMS: Final[dict[str, tuple[str, ...]]] = {
    'adapter_catalog_status': ADAPTER_CATALOG_STATUS,
    'adapter_category': ADAPTER_CATEGORY,
    'adapter_credential_status': ADAPTER_CREDENTIAL_STATUS,
    'adapter_policy_mode': ADAPTER_POLICY_MODE,
    'artifact_content_class': ARTIFACT_CONTENT_CLASS,
    'channel_auth_code_status': CHANNEL_AUTH_CODE_STATUS,
    'channel_identity_status': CHANNEL_IDENTITY_STATUS,
    'channel_kind': CHANNEL_KIND,
    'channel_message_direction': CHANNEL_MESSAGE_DIRECTION,
    'channel_message_status': CHANNEL_MESSAGE_STATUS,
    'artifact_source_type': ARTIFACT_SOURCE_TYPE,
    'client_adapter_config_status': CLIENT_ADAPTER_CONFIG_STATUS,
    'client_status': CLIENT_STATUS,
    'data_source_binding_status': DATA_SOURCE_BINDING_STATUS,
    'data_source_connector_type': DATA_SOURCE_CONNECTOR_TYPE,
    'deployment_mode': DEPLOYMENT_MODE,
    'execution_cycle_trigger': EXECUTION_CYCLE_TRIGGER,
    'external_execution_result_status': EXTERNAL_EXECUTION_RESULT_STATUS,
    'fallback_policy': FALLBACK_POLICY,
    'manifest_owner': MANIFEST_OWNER,
    'manifest_source': MANIFEST_SOURCE,
    'membership_role': MEMBERSHIP_ROLE,
    'membership_status': MEMBERSHIP_STATUS,
    'output_handoff_candidate_status': OUTPUT_HANDOFF_CANDIDATE_STATUS,
    'output_handoff_status': OUTPUT_HANDOFF_STATUS,
    'output_kind': OUTPUT_KIND,
    'output_package_kind': OUTPUT_PACKAGE_KIND,
    'output_package_status': OUTPUT_PACKAGE_STATUS,
    'permission_grant_type': PERMISSION_GRANT_TYPE,
    'permission_scope': PERMISSION_SCOPE,
    'prompt_profile_scope': PROMPT_PROFILE_SCOPE,
    'prompt_profile_status': PROMPT_PROFILE_STATUS,
    'prompt_version_status': PROMPT_VERSION_STATUS,
    'render_engine': RENDER_ENGINE,
    'repository_binding_status': REPOSITORY_BINDING_STATUS,
    'repository_connector_type': REPOSITORY_CONNECTOR_TYPE,
    'template_profile_status': TEMPLATE_PROFILE_STATUS,
    'user_status': USER_STATUS,
    'work_order_priority': WORK_ORDER_PRIORITY,
    'work_order_status': WORK_ORDER_STATUS,
    'workflow_execution_status': WORKFLOW_EXECUTION_STATUS,
    'workflow_status': WORKFLOW_STATUS,
    'workflow_step_run_status': WORKFLOW_STEP_RUN_STATUS,
    'workflow_template_status': WORKFLOW_TEMPLATE_STATUS,
    # Loop Eta phase 0
    'tool_category': TOOL_CATEGORY,
    'tool_default_tier': TOOL_DEFAULT_TIER,
    'tool_runtime_status': TOOL_RUNTIME_STATUS,
}
