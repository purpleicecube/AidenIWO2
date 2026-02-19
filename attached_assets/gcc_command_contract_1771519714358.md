# GCC Command Contract — WS014 P_PODE

**Document:** `WS014_P_PODE/03_Orchestration/gcc_command_contract.md`
**Task ID:** GCC-A-001
**Version:** 1.1
**Created:** 2026-02-18
**Status:** Draft

---

## 1. Purpose

This document defines the input/output contract, authority model, and error semantics for each GCC memory command. All GCC nodes, utilities, and tests MUST conform to these contracts.

---

## 2. Naming Conventions (Locked)

These conventions are final. Do not rename without a versioned contract amendment.

### 2.1 Shared Dict Key Prefix

All GCC runtime keys use the prefix `gcc.` in the shared dict. No GCC data may appear in Work Order or BDM Marker payloads (both enforce `additionalProperties: false`).

### 2.2 Command Names

| Command | Canonical Name | Verb Form |
|---------|---------------|-----------|
| Commit  | `COMMIT`      | commit    |
| Branch  | `BRANCH`      | branch    |
| Merge   | `MERGE`       | merge     |
| Context | `CONTEXT`     | context   |

### 2.3 Artifact Path Convention

```
WS014_P_PODE/05_Artifacts/gcc_memory/projects/<project_id>/
  main.md                           # project-level roadmap and summary
  branches/<branch_name>/
    commit.md                       # ordered milestone history
    log.md                          # OTA execution trace
    metadata.yaml                   # branch config and structural context
    index.yaml                      # commit index (IDs, timestamps, summaries)
```

### 2.4 Identifier Formats

| Identifier | Format | Example |
|------------|--------|---------|
| `project_id` | lowercase slug, `[a-z0-9_-]+` | `ws011-sia-win-plan` |
| `branch_name` | lowercase slug, `[a-z0-9_-]+` | `main`, `alt-pricing-model` |
| `commit_id` | `gcc-<8-char-hex>` | `gcc-a3f7b201` |

---

## 3. Authority Table

| Command | Tier 2 | Tier 1 | Mode Constraints |
|---------|--------|--------|------------------|
| `CONTEXT` | Allowed (read-only) | Allowed | None — always permitted |
| `COMMIT` | Allowed (active assigned branch only) | Allowed | None — always permitted |
| `BRANCH` | Propose only (emits request, does not create) | Approve + create | `autonomous`: low-risk auto-approve; `semi-autonomous`: Tier 1 review; `hitl`: human approval |
| `MERGE` | Denied (hard fail) | Exclusive authority | `autonomous`: policy-score gated; `semi-autonomous`: Tier 1 review; `hitl`: human approval required |

### 3.1 Enforcement

- Authority violations MUST raise `GCCAuthorityError` with the invoking tier, attempted command, and reason.
- Authority checks run in `gcc_policy.py` and are called from node `prep()` before any state mutation.
- Tier identity is read from `shared["gcc.tier"]` (set by the flow orchestrator, never by individual nodes).

---

## 4. Command Specifications

### 4.1 COMMIT

**Purpose:** Create a durable milestone snapshot of progress on the active branch.

**Invoking Node:** `ContextCommitNode`

**Input (from shared dict):**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `gcc.project_id` | `str` | Yes | Target project |
| `gcc.branch` | `str` | Yes | Active branch name |
| `gcc.tier` | `str` | Yes | `"tier1"` or `"tier2"` |
| `gcc.commit_summary` | `str` | Yes | Human-readable milestone description |
| `gcc.commit_node_outcomes` | `list[dict]` | No | Node names + results that led to this commit |
| `gcc.commit_tags` | `list[str]` | No | Optional classification tags |

**Output (written by node):**

| Key | Type | Description |
|-----|------|-------------|
| `gcc.commit_id` | `str` | Generated commit ID (`gcc-<8-hex>`) |
| `gcc.last_commit_summary` | `str` | Copy of the summary for downstream nodes |

**Side Effects:**
- Appends entry to `branches/<branch>/commit.md`
- Appends entry to `branches/<branch>/index.yaml`
- Updates `branches/<branch>/metadata.yaml` `last_commit` field

**Error Conditions:**

| Condition | Error | Behavior |
|-----------|-------|----------|
| `gcc.project_id` or `gcc.branch` missing | `GCCContractError` | Hard fail, no state mutation |
| `gcc.commit_summary` empty | `GCCContractError` | Hard fail |
| Authority check fails | `GCCAuthorityError` | Hard fail |
| Filesystem write fails | `GCCStoreError` | Hard fail, partial writes rolled back |

---

### 4.2 BRANCH

**Purpose:** Create an isolated memory branch for alternate strategy exploration.

**Invoking Node:** `ContextBranchNode`

**Input (from shared dict):**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `gcc.project_id` | `str` | Yes | Target project |
| `gcc.branch` | `str` | Yes | Current branch (becomes parent) |
| `gcc.tier` | `str` | Yes | `"tier1"` or `"tier2"` |
| `gcc.branch_request_name` | `str` | Yes | Proposed new branch name |
| `gcc.branch_request_reason` | `str` | Yes | Why this branch is needed |
| `gcc.branch_request_risk` | `str` | No | `"low"`, `"medium"`, `"high"` (default: `"medium"`) |

**Output (written by node):**

| Key | Type | Description |
|-----|------|-------------|
| `gcc.branch_created` | `bool` | `True` if branch was created, `False` if request was queued for Tier 1 |
| `gcc.branch` | `str` | Updated to new branch name if created |
| `gcc.parent_branch` | `str` | Set to the branch that was active before creation |

**Tier 2 Behavior (propose only):**
- Sets `gcc.branch_requested = True` and `gcc.branch_request_pending = True` in shared dict.
- Does NOT create filesystem artifacts.
- Tier 1 retrieves the request via `ContextQueryNode` and decides.

**Tier 1 Behavior (approve + create):**
- Runs policy check (`gcc_policy.check_branch`).
- If approved: creates `branches/<new_branch>/` directory tree, initializes `metadata.yaml` with parent reference, sets output keys.
- If denied: sets `gcc.branch_created = False` and `gcc.branch_denial_reason`.

**Side Effects (on creation):**
- Creates `branches/<new_branch>/` with empty `commit.md`, `log.md`, initial `metadata.yaml`, empty `index.yaml`
- Updates parent branch `metadata.yaml` to record child branch reference

**Error Conditions:**

| Condition | Error | Behavior |
|-----------|-------|----------|
| Branch name already exists | `GCCConflictError` | Hard fail |
| Branch name violates format | `GCCContractError` | Hard fail |
| Tier 2 attempts direct creation | `GCCAuthorityError` | Hard fail |
| Policy denies (Tier 1) | None (not an error) | Sets denial keys in shared dict |

---

### 4.3 MERGE

**Purpose:** Consolidate branch outcomes into a target branch under Tier 1 governance.

**Invoking Node:** `ContextMergeNode`

**Input (from shared dict):**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `gcc.project_id` | `str` | Yes | Target project |
| `gcc.tier` | `str` | Yes | Must be `"tier1"` |
| `gcc.merge_source_branch` | `str` | Yes | Branch to merge from |
| `gcc.merge_target_branch` | `str` | Yes | Branch to merge into (typically `"main"`) |
| `gcc.merge_strategy` | `str` | No | `"append"` (default), `"summarize"`, `"replace"` |
| `gcc.merge_reason` | `str` | Yes | Why this merge is happening |

**Output (written by node):**

| Key | Type | Description |
|-----|------|-------------|
| `gcc.merge_completed` | `bool` | `True` on success |
| `gcc.merge_commit_id` | `str` | Commit ID of the merge entry on target branch |
| `gcc.merge_conflicts` | `list[dict]` | Empty list if clean; conflict records if not |

**Merge Strategies:**

| Strategy | Behavior |
|----------|----------|
| `append` | Append all source commits to target `commit.md`; concatenate logs. Default. |
| `summarize` | Generate a single summary commit on the target from source branch history. |
| `replace` | Target branch `commit.md` and `log.md` are replaced by source content. Destructive — requires `hitl` mode or explicit policy override. |

**HITL Escalation Triggers:**
- `merge_strategy` is `"replace"`
- Source branch modifies cross-domain assumptions (flagged in `metadata.yaml`)
- Source branch introduced new external dependencies
- Any unresolved conflict records

**Side Effects:**
- Writes merge commit to target branch `commit.md` and `index.yaml`
- Appends merge event to source branch `metadata.yaml` (`merged_into` field)
- Optionally archives source branch (`metadata.yaml` status → `"merged"`)

**Error Conditions:**

| Condition | Error | Behavior |
|-----------|-------|----------|
| Tier 2 invocation | `GCCAuthorityError` | Hard fail |
| Source branch does not exist | `GCCContractError` | Hard fail |
| Target branch does not exist | `GCCContractError` | Hard fail |
| HITL required but not available | `GCCEscalationError` | Suspend, set `gcc.merge_awaiting_hitl = True` |

---

### 4.4 CONTEXT

**Purpose:** Retrieve scoped memory for decision-making or continuation.

**Invoking Node:** `ContextQueryNode` (Tier 1), `ContextLoadNode` (Tier 2 flow-start)

**Input (from shared dict):**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `gcc.project_id` | `str` | Yes | Target project |
| `gcc.tier` | `str` | Yes | `"tier1"` or `"tier2"` |
| `gcc.context_scope` | `str` | Yes | Scope selector (see below) |
| `gcc.context_branch` | `str` | No | Branch to query (default: `gcc.branch` or `"main"`) |
| `gcc.context_commit_id` | `str` | No | Specific commit to retrieve (for `"commit"` scope) |
| `gcc.context_limit` | `int` | No | Max entries to return (default: `20`) |

**Scope Values:**

| Scope | Returns |
|-------|---------|
| `"project"` | `main.md` content + branch listing |
| `"branch"` | Branch `commit.md` + `metadata.yaml` summary |
| `"commit"` | Single commit entry by ID |
| `"trace"` | Recent `log.md` entries (bounded by `context_limit`) |
| `"metadata"` | Branch `metadata.yaml` content |
| `"full"` | All of the above combined (use sparingly — expensive) |

**Output (written by node):**

| Key | Type | Description |
|-----|------|-------------|
| `gcc.context_result` | `str` | Retrieved content (markdown-formatted) |
| `gcc.context_branch_list` | `list[str]` | Available branches (for `"project"` scope) |
| `gcc.context_commit_count` | `int` | Total commits on queried branch |

**Side Effects:** None (read-only).

**Error Conditions:**

| Condition | Error | Behavior |
|-----------|-------|----------|
| Project does not exist | `GCCContractError` | Hard fail |
| Branch does not exist | `GCCContractError` | Hard fail |
| Commit ID not found | `GCCContractError` | Hard fail |
| Scope value invalid | `GCCContractError` | Hard fail |

---

## 5. Supplemental Nodes (Non-Command)

These nodes support GCC but do not map to a GCC command directly.

### 5.1 ContextLoadNode

**Purpose:** Load branch context at the start of a Tier 2 execution flow.

**Behavior:** Invokes `CONTEXT` with scope `"branch"` and populates shared dict with the result. Sets `gcc.branch` and `gcc.project_id` for downstream nodes.

**Placement:** First node in Tier 2 flow, before `ValidateWorkOrderNode`.

### 5.2 ContextLogNode

**Purpose:** Append execution trace segments to the active branch log.

**Input (from shared dict):**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `gcc.project_id` | `str` | Yes | Target project |
| `gcc.branch` | `str` | Yes | Active branch |
| `gcc.log_entry` | `str` | Yes | Trace content to append |
| `gcc.log_source_node` | `str` | No | Name of the node that generated this entry |
| `gcc.log_timestamp` | `str` | No | ISO-8601 (auto-generated if omitted) |
| `gcc.origin_channel` | `str` | No | `slack` / `telegram` / `email` for provenance |
| `gcc.origin_conversation_id` | `str` | No | Provider thread/channel/chat ID |
| `gcc.origin_message_id` | `str` | No | Provider-native inbound message ID |

**Side Effects:** Appends to `branches/<branch>/log.md`.

**Output:** `gcc.log_appended = True`

### 5.3 ChannelIngressNode (Tier 1 Gateway)

**Purpose:** Normalize external inbound events (Slack/Telegram/Email) and populate channel provenance keys in shared dict.

**Placement:** Tier 1 entrypoint before policy routing.

### 5.4 ChannelDispatchNode (Tier 1 Gateway)

**Purpose:** Deliver outbound responses to external channels via adapter selection by `gcc.outbound_channel`.

**Placement:** Tier 1 exitpoint after response assembly/query.

---

## 6. Error Type Hierarchy

| Error Class | Meaning | Typical Recovery |
|-------------|---------|------------------|
| `GCCContractError` | Missing or invalid required input | Fix caller; never retry as-is |
| `GCCAuthorityError` | Tier/mode violation | Route to correct tier |
| `GCCConflictError` | Name collision or state conflict | Choose different name or resolve conflict |
| `GCCStoreError` | Filesystem IO failure | Retry or escalate |
| `GCCEscalationError` | HITL required but unavailable | Suspend and wait |

All error classes inherit from a base `GCCError`.

---

## 7. Node Interface Contract (PocketFlow Lifecycle)

All GCC nodes follow the PocketFlow `BaseNode` lifecycle. This section locks the interface so skeletons can be built before PocketFlow core is vendored.

### 7.1 Required Methods

```python
class GCCNodeBase:
    """Abstract base for all GCC nodes. Inherits from PocketFlow Node."""

    def prep(self, shared: dict) -> dict:
        """Read GCC keys from shared dict. Run authority check.
        Return a prep_res dict with extracted values."""

    def exec(self, prep_res: dict) -> dict:
        """Pure computation and/or IO against gcc_store/gcc_context.
        No direct shared dict access. Return exec_res dict."""

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        """Write results back to shared dict.
        Return routing action string for PocketFlow DSL."""
```

### 7.2 Routing Actions

| Node | Success Action | Failure Actions |
|------|---------------|-----------------|
| `ContextLoadNode` | `"loaded"` | `"error"` |
| `ContextLogNode` | `"logged"` | `"error"` |
| `ContextCommitNode` | `"committed"` | `"error"` |
| `ContextBranchNode` (Tier 2) | `"requested"` | `"error"` |
| `ContextBranchNode` (Tier 1) | `"created"` / `"denied"` | `"error"` |
| `ContextMergeNode` | `"merged"` | `"conflict"` / `"escalated"` / `"error"` |
| `ContextQueryNode` | `"result"` | `"error"` |

---

## 8. Constraints Restatement

1. GCC keys live in shared dict and filesystem artifacts ONLY. They MUST NOT appear in Work Order or BDM Marker payloads.
2. `gcc.tier` is set by the flow orchestrator. Individual nodes MUST NOT modify it.
3. Tier 2 MUST NOT invoke `MERGE`. This is enforced in `gcc_policy.py` and tested in boundary eval suite (GCC-E-002).
4. All filesystem writes go through `gcc_store.py`. Nodes MUST NOT write directly.
5. Commit IDs are generated by `gcc_store.py` only. Callers MUST NOT fabricate them.
6. External channel ingress/egress runs in Tier 1 only. Tier 2 MUST NOT call channel adapters directly.

---

## 9. Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.1 | 2026-02-18 | Added Tier 1 channel gateway supplemental nodes and channel provenance fields for log contract. |
| 1.0 | 2026-02-18 | Initial command contract. Naming conventions locked. |
