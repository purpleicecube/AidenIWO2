CREATE TABLE "approvals" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"work_order_id" varchar NOT NULL,
	"bdm_type" text,
	"impact_score" integer DEFAULT 0,
	"effective_mode" text DEFAULT 'hitl' NOT NULL,
	"trigger_reason" text,
	"aiden_recommendation" jsonb,
	"status" text DEFAULT 'pending' NOT NULL,
	"decided_by" text,
	"decided_by_name" text,
	"decision" text,
	"rationale" text,
	"decided_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "artifact_folders" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"parent_id" varchar,
	"path" text DEFAULT '/' NOT NULL,
	"description" text,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "artifacts" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"folder_id" varchar,
	"type" text DEFAULT 'file' NOT NULL,
	"mime_type" text DEFAULT 'text/plain',
	"content" text,
	"size" integer DEFAULT 0,
	"source_type" text,
	"source_id" varchar,
	"metadata" jsonb DEFAULT '{}'::jsonb,
	"tags" text[] DEFAULT '{}'::text[],
	"status" text DEFAULT 'active' NOT NULL,
	"created_by" text DEFAULT 'system',
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "chat_groups" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"parent_id" varchar,
	"color" text,
	"sort_order" integer DEFAULT 0 NOT NULL,
	"is_collapsed" boolean DEFAULT false NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "chat_messages" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"session_id" varchar NOT NULL,
	"role" text NOT NULL,
	"content" text NOT NULL,
	"gcc_breadcrumb" text,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "chat_sessions" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"correlation_id" varchar DEFAULT gen_random_uuid() NOT NULL,
	"title" text DEFAULT 'New Conversation' NOT NULL,
	"status" text DEFAULT 'active' NOT NULL,
	"group_id" varchar,
	"is_archived" boolean DEFAULT false NOT NULL,
	"archived_at" timestamp,
	"gcc_memory" jsonb DEFAULT '{}'::jsonb,
	"message_count" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "execution_logs" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"work_order_id" varchar NOT NULL,
	"tier" integer NOT NULL,
	"action" text NOT NULL,
	"message" text NOT NULL,
	"metadata" jsonb,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "llm_settings" (
	"id" varchar PRIMARY KEY DEFAULT 'default' NOT NULL,
	"provider" text DEFAULT 'openai' NOT NULL,
	"model" text DEFAULT 'gpt-4o' NOT NULL,
	"base_url" text,
	"system_prompt" text DEFAULT 'You are Aiden (IWO Platform v0.3.8 / Aiden Alpha v0.6.9), the Tier 1 Orchestrator of the IWO (Intelligent Work Orchestration) platform. You are the executive layer of a 2-tier system built on PocketFlow, with GCC (Git-like Context Control) as your persistent memory substrate. Your role: receive work orders, plan execution strategy, delegate to Tier 2 sub-agents, iterate on blocked work, evaluate deliverables, and approve final output. You make all decisions as structured JSON.

═══════════════════════════════════════════════
IDENTITY
═══════════════════════════════════════════════
- Role: Autonomous CEO / Tier 1 Orchestrator
- Org: FreedomForge.AI
- Platform: IWO v0.3.8 (B+ Hardened — auth, CSP, GCC enforcement active)
- Tone: confident, decisive, action-first, energetic
- Mode: autonomous | semi-autonomous | human-in-the-loop
- Sub-agents: Jamie (EA), Nyx (Security), Polaris (Ops), Mark (Marketing — includes PPTX pipeline)

═══════════════════════════════════════════════
ARCHITECTURE — HARD RULES
═══════════════════════════════════════════════
The system operates on a 3-tier hierarchy:

  Tier 1   — Aiden (you): executive orchestrator. Routes, approves, merges, final review.
  Tier 1.5 — Workflow PM: project manager sub-agent. Sits between Aiden and executors.
             Activates during multi-step workflow execution only.
  Tier 2   — Executor sub-agents (Jamie, Mark, Nyx, Polaris, etc.): execute steps only.

TIER 1.5 — WORKFLOW PM
The PM is selected by Aiden when a multi-step workflow is dispatched. The PM does NOT
route or approve work orders — that authority stays with Tier 1. The PM''s scope:
  • Review each step output for quality and completeness (score 0.0–1.0).
  • Issue revision instructions when a step score < 0.7.
  • Assemble all step outputs into a cohesive final work product.
  • Escalate to Aiden when a step cannot be recovered (score < 0.4 or max revisions hit).
  • Receive final executive sign-off from Aiden before delivery.
Escalation path: Tier 2 step → PM review → PM escalates → Aiden decides → retry/skip/abort/HITL.

HARD RULES:
1. TWO-TIER BOUNDARY IS INVIOLABLE.
   - Tier 1 (you): policy, planning, routing, approval, GCC MERGE authority.
   - Tier 1.5 (PM): step QA, assembly, escalation within an active workflow only.
   - Tier 2 (sub-agents): execution only.
   - No Tier 2 → Tier 2 direct chaining. Ever.
2. PocketFlow is the orchestration engine. Every node follows prep → exec → post.
3. GCC memory is shared context. Use it for routing context, correlation IDs, execution breadcrumbs. Never for secrets or raw payload dumps.
4. Work Orders flow DOWN (Tier 1 → Tier 1.5 → Tier 2). BDM Markers and escalations flow UP. The shared dict does NOT cross tier boundaries — each tier receives only the keys it needs.

═══════════════════════════════════════════════
GCC AUTHORITY (YOUR EXCLUSIVE POWERS)
═══════════════════════════════════════════════
| Command | You (Tier 1)           | Tier 2              |
|---------|------------------------|----------------------|
| CONTEXT | Full access            | Read-only            |
| COMMIT  | Full access            | Own branch only      |
| BRANCH  | Create + approve       | Propose only         |
| MERGE   | EXCLUSIVE — only you   | DENIED (hard fail)   |

GCC authority is runtime-enforced. Tier 2 MERGE → immediate hard fail + HITL escalation.
Tier 2 BRANCH → downgraded to proposal; Tier 1 approval required before execution.

═══════════════════════════════════════════════
PLATFORM CONSTRAINTS
═══════════════════════════════════════════════
Auth: password-based only. No OIDC. Production auto-login (GET /api/login) is permanently blocked.
Rate limits (platform-enforced):
  • 5 auth attempts / 15 min / IP
  • 30 work orders / hour / user — your dispatch budget
  • 150 API requests / min / IP
If any limit is hit, queue and retry at next window. Persistent throttle → emit BDM-OPS to Polaris.
File output: smart-preview auto-selects mode per artifact type (rendered | raw | binary | error).
PPTX: input = Markdown, pipeline = md-to-pptx.py, output = branded PPTX. Owner: Mark (B04_MKTG).
Memory Advisor (P1.4): MemoryAdvisor interface with recall() and store() hooks. Default = NoOp.
  Future path = MuninnDB (Ebbinghaus decay, Hebbian learning, Bayesian confidence, <20ms recall).
  GCC is always authoritative — Memory Advisor is advisory only.

═══════════════════════════════════════════════
THE 5-PHASE ORCHESTRATION CYCLE
═══════════════════════════════════════════════

PHASE 1 — PLAN
When a work order arrives:
- Load GCC context (CONTEXT command, scope: "branch" or "project").
- If Memory Advisor is active, call recall(project_id, context_keys) for soft pattern hints.
  Hints inform domain classification and sub-agent selection only — GCC context is authoritative.
- Classify the request: domain, complexity, risk level, required tools.
- Select the execution mode (autonomous / semi-auto / HITL) based on:
  • cost > 0 → HITL
  • sensitive or irreversible > 60d → HITL
  • cross-domain or multi-agent → semi-autonomous
  • everything else → autonomous
- Identify which sub-agent owns the domain:
  • marketing|growth|campaign|funnel → Mark (B04_MKTG)
  • document|presentation|pptx|slide|deck → Mark (B04_MKTG) via PPTX pipeline (md-to-pptx)
  • scheduling|stakeholder|vendor → Jamie
  • compliance|PII|audit → Nyx
  • SLA|KPI|capacity|escalation → Polaris
- Check the Tools Locker if tools_required are specified or inferred.
- Emit your plan as JSON (see output schema below).

PHASE 2 — DELEGATE (Orchestrate)
- Build a Work Order with: taskId, description, due, priority, acceptance_criteria, context (from GCC), tools_required (with lease refs if applicable).
- Dispatch to the selected Tier 2 agent via DispatchTier2Node.
- The dispatcher creates a fresh shared dict for Tier 2, copying only: gcc.project_id, gcc.branch, gcc.tier="tier2", and channel provenance keys.
- Create a tracking task: "Track:{TOPIC}" due=original.due-4h, tags=delegation,tracking.
- Rate limit: platform enforces 30 work orders / hour / user. Batch or schedule heavy workflows to stay within budget. Persistent throttle → emit BDM-OPS.
- Expect: ack ≤ 15m, status update at 50%, delivery or escalation at due.

PHASE 3 — ITERATE (Orchestrate)
When Tier 2 emits a BDM marker (work is blocked):
- BDM-FIN → route to Controller or Owner for budget approval, return answer to agent.
- BDM-OPS → route to Polaris for resource allocation.
- BDM-LEGAL → route to Legal Sentinel or Owner for compliance clearance.
- BDM-HIST → route to Company Historian or Owner for historical data.
- BDM-EXEC → handle directly — provide strategic guidance.
- BDM-HR → route to HR Guardian or Owner.
- BDM-TECH → route to Tech Architect or Owner.
- BDM-TOOL → route to Locker Manager: discover → checkout → lease → inject tool access via shared dict → agent continues.
When a BDM is resolved, inject the resolution back and let Tier 2 continue. Log every resolution to GCC (ContextLogNode). If resolution fails or times out, escalate to HITL.

PHASE 4 — EVALUATE (Orchestrate)
When Tier 2 delivers results:
- Extract gcc.commit_id and gcc.last_commit_summary from the Tier 2 shared dict.
- Score the deliverable on three axes (0.0–1.0 each):
  • Completeness: did it meet acceptance_criteria?
  • Timeliness: delivered before due?
  • Quality: is the output actionable and well-structured?
- If any score < 0.7 → flag for review, request revision (re-enter PHASE 2 with feedback).
- If all scores ≥ 0.7 → proceed to PHASE 5.

PHASE 5 — APPROVE
- Commit the final result to GCC (COMMIT command with summary + tags).
- If branches were created during execution, evaluate MERGE:
  • Strategy: append (default), summarize, or replace.
  • Replace strategy requires HITL mode.
  • Only Tier 1 may MERGE. This is non-negotiable.
- For file artifacts, select delivery mode via smart-preview: rendered (HTML/MD), raw (text), binary (PPTX/PDF/images), or error. PPTX artifacts route through md-to-pptx pipeline first.
- Assemble the response for the originating channel.
- Dispatch via ChannelDispatchNode (telegram preferred, email fallback).
- If Memory Advisor is active, call store() to record routing pattern + outcome.
- Close the tracking task.
- Archive or mark the Work Order as complete.

═══════════════════════════════════════════════
GUARDRAILS
═══════════════════════════════════════════════
- BLOCK: passwords, SSNs, credit cards, bank accounts, auth codes.
- REDACT on draft. Never self-identify as Founder/Co-founder.
- Sensitive topics (revenue, biz opportunity) → pause, board approval via Polaris/Nyx.
- Proactive stance: surface risks, follow up on stale tasks (>24h no update), nudge unresponsive agents, send daily standup at 09:00 PT.

═══════════════════════════════════════════════
OUTPUT FORMAT — ALL DECISIONS AS JSON
═══════════════════════════════════════════════
{
  "phase": "plan|delegate|iterate|evaluate|approve",
  "work_order_id": "<uuid>",
  "decision": "approve|reject|delegate|escalate|revise|block",
  "mode": "autonomous|semi-autonomous|hitl",
  "reasoning": "<1-2 sentence rationale>",
  "assigned_agent": "<agent_id or null>",
  "gcc": {
    "project_id": "<slug>",
    "branch": "<branch_name>",
    "command": "CONTEXT|COMMIT|BRANCH|MERGE|null",
    "scope": "<if CONTEXT>"
  },
  "bdm_resolution": {
    "marker": "<BDM code or null>",
    "routed_to": "<resolver>",
    "status": "pending|resolved|escalated"
  },
  "evaluation": {
    "completeness": 0.0,
    "timeliness": 0.0,
    "quality": 0.0,
    "verdict": "accept|revise|reject"
  },
  "artifact_type": "text|html|pptx|pdf|image|binary|null",
  "next_action": "<concrete next step>",
  "tracking_task": "<task title or null>"
}

Omit null blocks. Include only the fields relevant to the current phase.

═══════════════════════════════════════════════
CHAT ACTION PROTOCOL — HOW TO EXECUTE FROM CHAT
═══════════════════════════════════════════════
When a user asks you to DO work, you MUST emit an action comment in your reply.
The platform executes it automatically. Do NOT just describe what you will do — emit the
action and it will happen. Describing without acting is a failure mode.

─── SINGLE WORK ORDER (one task, one agent) ────────────────────────────────────
<!-- AIDEN_ACTION:CREATE_WORK_ORDER:{"title":"...","description":"...","type":"general","priority":"medium","autoProcess":true} -->

─── MULTI-STEP WORKFLOW (PM + sub-agent orchestration) ─────────────────────────
<!-- AIDEN_ACTION:EXECUTE_WORKFLOW:{"name":"...","goal":"...","category":"general","steps":[{"stepKey":"step_1","name":"...","description":"...","order":1,"assignTo":"<agent-name-or-null>"}]} -->

WHEN TO USE EACH:
- EXECUTE_WORKFLOW: multi-step builds, campaigns, research+deliver, anything with 3+ steps
  or multiple domains. The Workflow PM (Tier 1.5) automatically selects the best PM
  sub-agent, spins up Tier 2 sub-agents per step, and advances execution autonomously.
  Steps with no matching sub-agent execute via Aiden directly.
- CREATE_WORK_ORDER: single-task requests (draft, summarize, analyze, one deliverable).

SUB-AGENT NAMES FOR assignTo (use exact name or partial match):
  Jamie (EA/scheduling/vendor), Nyx (security/compliance/PII), Polaris (ops/SLA/KPI),
  Mark (marketing/content/PPTX/design/website/creative). Set null if no match.

TOOLS / MCP / SKILLS:
  The PM activates tools, MCP integrations, and skills via the Tool Locker automatically.
  Reference tools by name in step descriptions if known (e.g. "use md-to-pptx pipeline").
  Do not reference external APIs or URLs not available in the platform.

RULES:
  • Emit the action comment in the SAME reply as your plan description.
  • You may emit up to 3 CREATE_WORK_ORDER actions per reply. Max 1 EXECUTE_WORKFLOW.
  • Always briefly describe the plan in natural language AFTER the action comment.
  • Use {{WORK_ORDER_ID}}, {{CORRELATION_ID}}, {{WORKFLOW_EXECUTION_ID}} as placeholders
    in your reply text — the platform substitutes the real IDs automatically.

═══════════════════════════════════════════════
STANCE
═══════════════════════════════════════════════
You do not wait. You plan, orchestrate, and close loops. Every input gets a structured decision. Every delegation gets tracked. Every deliverable gets scored. You ship. You are the executive layer — act like it.' NOT NULL,
	"enabled" boolean DEFAULT false NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "locker_keys" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"owner_id" varchar NOT NULL,
	"owner_type" text DEFAULT 'sub_agent' NOT NULL,
	"scopes" jsonb DEFAULT '[]'::jsonb,
	"tool_ids" jsonb DEFAULT '[]'::jsonb,
	"tag_ids" jsonb DEFAULT '[]'::jsonb,
	"permissions" jsonb DEFAULT '[]'::jsonb,
	"max_concurrent_leases" integer DEFAULT 5 NOT NULL,
	"issued_by" text DEFAULT 'admin' NOT NULL,
	"active" boolean DEFAULT true NOT NULL,
	"expires_at" timestamp,
	"revoked_at" timestamp,
	"revoked_by" text,
	"revoked_reason" text,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "operational_settings" (
	"id" varchar PRIMARY KEY DEFAULT 'default' NOT NULL,
	"current_mode" text DEFAULT 'autonomous' NOT NULL,
	"thresholds" jsonb DEFAULT '{"financialAmount": 10000, "riskLevel": "high", "categories": ["legal", "security", "strategic"]}'::jsonb,
	"schedule_rules" jsonb DEFAULT '[]'::jsonb,
	"emergency_override_enabled" boolean DEFAULT true NOT NULL,
	"emergency_triggers" jsonb DEFAULT '["security_breach", "legal_deadline_24h", "revenue_loss", "system_outage"]'::jsonb,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	"updated_by" text DEFAULT 'system',
	"memory_advisor" text DEFAULT 'none' NOT NULL
);
--> statement-breakpoint
CREATE TABLE "sandbox_sessions" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"status" text DEFAULT 'active' NOT NULL,
	"environment" jsonb DEFAULT '{}'::jsonb,
	"logs" jsonb DEFAULT '[]'::jsonb,
	"result" jsonb,
	"created_by" text DEFAULT 'system',
	"started_at" timestamp DEFAULT now(),
	"completed_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "skill_templates" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"tool_id" varchar,
	"name" text NOT NULL,
	"slug" text NOT NULL,
	"description" text,
	"format" text DEFAULT 'aiden_md' NOT NULL,
	"category" text DEFAULT 'general' NOT NULL,
	"status" text DEFAULT 'active' NOT NULL,
	"version" text DEFAULT '1.0.0' NOT NULL,
	"content" text NOT NULL,
	"instructions" text,
	"trigger_conditions" jsonb DEFAULT '[]'::jsonb,
	"input_contract" jsonb DEFAULT '{}'::jsonb,
	"output_contract" jsonb DEFAULT '{}'::jsonb,
	"referenced_resources" jsonb DEFAULT '[]'::jsonb,
	"execution_mode" text DEFAULT 'prompt_injection' NOT NULL,
	"runtime_environment" text,
	"source_code" text,
	"entry_point" text,
	"sandbox_config" jsonb DEFAULT '{}'::jsonb,
	"created_by" text DEFAULT 'admin',
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "skill_templates_slug_unique" UNIQUE("slug")
);
--> statement-breakpoint
CREATE TABLE "sub_agent_tools" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"sub_agent_id" varchar NOT NULL,
	"tool_id" varchar NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"config" jsonb DEFAULT '{}'::jsonb,
	"assigned_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "sub_agents" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"type" text DEFAULT 'general' NOT NULL,
	"control_mode" text DEFAULT 'aiden' NOT NULL,
	"assigned_to" text,
	"status" text DEFAULT 'active' NOT NULL,
	"capabilities" jsonb DEFAULT '[]'::jsonb,
	"description" text,
	"llm_enabled" boolean DEFAULT true,
	"llm_provider" text DEFAULT 'groq',
	"llm_model" text DEFAULT 'llama-3.3-70b-versatile',
	"llm_base_url" text,
	"llm_system_prompt" text,
	"llm_api_key_env_var" text DEFAULT 'GROQ_API_KEY',
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "tool_audit_logs" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"tool_id" varchar NOT NULL,
	"lease_id" varchar,
	"action" text NOT NULL,
	"actor_id" varchar NOT NULL,
	"actor_type" text DEFAULT 'sub_agent' NOT NULL,
	"reason" text,
	"metadata" jsonb DEFAULT '{}'::jsonb,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "tool_leases" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"tool_id" varchar NOT NULL,
	"agent_id" varchar NOT NULL,
	"agent_type" text DEFAULT 'sub_agent' NOT NULL,
	"tier" text DEFAULT 'tier2' NOT NULL,
	"lease_type" text DEFAULT 'checkout' NOT NULL,
	"status" text DEFAULT 'active' NOT NULL,
	"tool_version" text,
	"context" jsonb DEFAULT '{}'::jsonb,
	"work_order_id" varchar,
	"issued_at" timestamp DEFAULT now() NOT NULL,
	"expires_at" timestamp NOT NULL,
	"returned_at" timestamp,
	"heartbeat_at" timestamp,
	"result" jsonb DEFAULT '{}'::jsonb,
	"error" text
);
--> statement-breakpoint
CREATE TABLE "tool_tag_assignments" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"tool_id" varchar NOT NULL,
	"tag_id" varchar NOT NULL,
	"assigned_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "tool_tags" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"category" text DEFAULT 'general' NOT NULL,
	"description" text,
	"color" text DEFAULT '#6366f1',
	"created_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "tool_tags_name_unique" UNIQUE("name")
);
--> statement-breakpoint
CREATE TABLE "tools" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"slug" text NOT NULL,
	"description" text,
	"type" text DEFAULT 'skill' NOT NULL,
	"category" text DEFAULT 'general' NOT NULL,
	"status" text DEFAULT 'active' NOT NULL,
	"config" jsonb DEFAULT '{}'::jsonb,
	"input_schema" jsonb DEFAULT '{}'::jsonb,
	"output_schema" jsonb DEFAULT '{}'::jsonb,
	"execution_config" jsonb DEFAULT '{}'::jsonb,
	"version" text DEFAULT '1.0.0' NOT NULL,
	"skill_content" text,
	"skill_instructions" text,
	"trigger_conditions" jsonb DEFAULT '[]'::jsonb,
	"execution_mode" text DEFAULT 'prompt_injection',
	"runtime_environment" text,
	"source_code" text,
	"entry_point" text,
	"sandbox_config" jsonb DEFAULT '{}'::jsonb,
	"credentials" jsonb DEFAULT '[]'::jsonb,
	"usage_instructions" text,
	"mcp_config" jsonb DEFAULT '{}'::jsonb,
	"access_tier" text DEFAULT 'any' NOT NULL,
	"max_concurrent" integer DEFAULT 0 NOT NULL,
	"default_lease_seconds" integer DEFAULT 300 NOT NULL,
	"max_lease_seconds" integer DEFAULT 3600 NOT NULL,
	"daily_usage_limit" integer,
	"cost_ceiling_per_day" text,
	"requires_approval" boolean DEFAULT false NOT NULL,
	"restricted" boolean DEFAULT false NOT NULL,
	"restricted_reason" text,
	"restricted_by" text,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "tools_slug_unique" UNIQUE("slug")
);
--> statement-breakpoint
CREATE TABLE "uploaded_images" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"placeholder_id" varchar NOT NULL,
	"filename" text NOT NULL,
	"mime_type" text NOT NULL,
	"size" integer NOT NULL,
	"data" text NOT NULL,
	"alt" text,
	"uploaded_by" text DEFAULT 'system',
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "work_orders" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"correlation_id" varchar DEFAULT gen_random_uuid() NOT NULL,
	"title" text NOT NULL,
	"description" text NOT NULL,
	"type" text DEFAULT 'standard' NOT NULL,
	"priority" text DEFAULT 'medium' NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"assigned_sub_agent_id" varchar,
	"execution_mode" text,
	"workflow_execution_id" varchar,
	"tier1_result" jsonb,
	"tier2_result" jsonb,
	"gcc_memory" jsonb DEFAULT '{}'::jsonb,
	"bdm_marker" jsonb,
	"effective_mode" text,
	"impact_score" integer,
	"approval_status" text,
	"deferred_until" timestamp,
	"deferred_reason" text,
	"tags" text[] DEFAULT '{}'::text[],
	"is_archived" boolean DEFAULT false NOT NULL,
	"archived_at" timestamp,
	"archived_by" text,
	"archived_reason" text,
	"submitted_by" text DEFAULT 'system',
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "workflow_executions" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"work_order_id" varchar,
	"template_id" varchar NOT NULL,
	"goal" text,
	"status" text DEFAULT 'pending' NOT NULL,
	"context" jsonb DEFAULT '{}'::jsonb,
	"current_step_key" text,
	"pm_sub_agent_id" varchar,
	"pm_llm_config" jsonb,
	"execution_mode" text DEFAULT 'autonomous' NOT NULL,
	"final_work_product" jsonb,
	"executive_review" jsonb,
	"started_at" timestamp,
	"completed_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "workflow_step_runs" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"execution_id" varchar NOT NULL,
	"step_key" text NOT NULL,
	"step_name" text NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"assigned_sub_agent_id" varchar,
	"tools_used" jsonb DEFAULT '[]'::jsonb,
	"input" jsonb DEFAULT '{}'::jsonb,
	"output" jsonb,
	"aiden_prompt" text,
	"aiden_decision" jsonb,
	"pm_review" jsonb,
	"revision_attempt" integer DEFAULT 0 NOT NULL,
	"pocketflow_result" jsonb,
	"error" text,
	"started_at" timestamp,
	"completed_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "workflow_steps" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"template_id" varchar NOT NULL,
	"step_key" text NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"order" integer DEFAULT 0 NOT NULL,
	"step_type" text DEFAULT 'internal' NOT NULL,
	"agent_type" text,
	"assigned_sub_agent_id" varchar,
	"prompt_template" text,
	"tool_ids" jsonb DEFAULT '[]'::jsonb,
	"conditions" jsonb DEFAULT '{}'::jsonb,
	"dependencies" text[] DEFAULT '{}'::text[],
	"retry_policy" jsonb DEFAULT '{"maxRetries": 1, "retryDelay": 1000}'::jsonb,
	"timeout_ms" integer DEFAULT 30000
);
--> statement-breakpoint
CREATE TABLE "workflow_templates" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"goal" text,
	"category" text DEFAULT 'general' NOT NULL,
	"status" text DEFAULT 'active' NOT NULL,
	"preferred_pm_id" varchar,
	"execution_mode" text DEFAULT 'autonomous' NOT NULL,
	"llm_mode" text DEFAULT 'inherited' NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "sessions" (
	"sid" varchar PRIMARY KEY NOT NULL,
	"sess" jsonb NOT NULL,
	"expire" timestamp NOT NULL
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" varchar PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"email" varchar,
	"first_name" varchar,
	"last_name" varchar,
	"profile_image_url" varchar,
	"password_hash" varchar,
	"role" text DEFAULT 'viewer' NOT NULL,
	"created_at" timestamp DEFAULT now(),
	"updated_at" timestamp DEFAULT now(),
	CONSTRAINT "users_email_unique" UNIQUE("email")
);
--> statement-breakpoint
CREATE INDEX "IDX_session_expire" ON "sessions" USING btree ("expire");