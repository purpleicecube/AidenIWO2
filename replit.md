# AIDEN_PTIB - Intelligent Work Order Orchestration

## Version
**Current: v0.3.0 MVP** — Core orchestration engine with LLM-powered routing, HITL intervention, admin tooling, and Replit Auth with RBAC.

### v0.3.0 MVP — What's Included
- 2-tier orchestration (Aiden as Tier 1 manager, sub-agents as Tier 2 workers)
- Work order lifecycle: submit, process, complete, block, fail, retry, edit
- LLM-powered policy evaluation and routing (multi-provider: OpenAI, Anthropic, OpenRouter, Groq)
- Per-sub-agent LLM configuration (independent model/prompt per worker)
- BDM (Blocked Decision Marker) system with structured failure info
- HITL intervention: Re-issue to Aiden or Close Without Output with required explanation
- Work order inline editing (title, description, type, priority) for blocked/pending/failed orders
- Multi-step workflow templates with step dependencies, conditions, retries, timeouts
- Agentic tools platform (slash_command, skill, cli, api, webhook) with sub-agent assignment
- Workspace with artifact/folder management
- Sandbox sessions for command execution
- Persistent chat with GCC memory protocol (WS014 P_PODE contract)
- Dashboard with stats, recent orders, system health monitoring
- Dark/light theme, responsive sidebar navigation
- Hardcoded fallback orchestration when LLM is unavailable
- User authentication via Replit Auth (Google, GitHub login)
- Role-based access control (admin, operator, viewer) with first-user-is-admin logic
- Admin user management page with role assignment
- Landing page for unauthenticated users
- User identity tracking in GCC memory and execution logs for all work order actions

### v1.0.0 MVP — Roadmap (remaining items)
- **Real-time updates**: WebSocket or SSE push for live work order status changes, log streaming
- **Notification system**: Email/webhook alerts for blocked orders, completed workflows, operator assignments
- **Audit trail**: Immutable log of all state transitions, user actions, and LLM decisions with timestamps
- **Sub-agent health monitoring**: Heartbeat checks, uptime tracking, auto-disable on repeated failures
- **Workflow visual builder**: Drag-and-drop workflow template editor with step dependency graph
- **Bulk operations**: Multi-select work orders for batch processing, reassignment, or closure
- **Search & filtering**: Full-text search across work orders, advanced filters (date range, status, assignee, type)
- **Metrics & analytics**: Processing time trends, throughput charts, sub-agent performance scorecards
- **LLM observability**: Token usage tracking, cost estimation, prompt versioning, response quality scoring
- **API keys & external integrations**: Secure API key management for external consumers, webhook subscriptions
- **Data export**: CSV/JSON export for work orders, execution logs, and analytics data

## Overview
AIDEN_PTIB is a 2-tier work order orchestration platform:
- **Tier 1 — Aiden (Manager)**: LLM-powered policy gate, approvals, routing decisions
- **Tier 2 — Sub-Agents (Workers)**: Specialized workers that execute work orders
  - **Aiden-controlled**: Aiden directly controls and executes through the sub-agent
  - **Independent**: Authorized human or AI operator executes independently
- **System Admin**: A human who configures sub-agents, workflows, tools, and their assignments
- **GCC Memory**: Shared context between tiers following the WS014 P_PODE command contract (COMMIT, BRANCH, MERGE, CONTEXT commands with gcc.* prefixed keys)
- **BDM Markers**: Blocked Decision Markers emitted when work orders cannot proceed

## Architecture
- Frontend: React + TypeScript + Vite + TanStack Query + Wouter + shadcn/ui
- Backend: Express.js + Drizzle ORM + PostgreSQL
- LLM: OpenAI SDK (for OpenAI/OpenRouter/Groq) + Anthropic SDK (for Claude)
- Styling: Tailwind CSS with Inter font family

## Project Structure
- `client/src/pages/` - Dashboard, WorkOrders, WorkOrderDetail, SubmitOrder, SystemHealth, Architecture, Settings, SubAgents, Workflows, Tools, Workspace, Sandbox, Chat, Landing, UserManagement
- `client/src/components/` - AppSidebar, ThemeProvider, ThemeToggle, StatusBadge, SplitPane
- `client/src/hooks/` - use-page-title, use-toast, use-auth
- `server/replit_integrations/auth/` - Replit Auth integration (OIDC, session, user upsert)
- `server/routes.ts` - API endpoints
- `server/orchestration.ts` - Aiden (Tier 1), sub-agent (Tier 2), and workflow execution engine
- `server/llm-client.ts` - Multi-provider LLM abstraction with structured JSON parsing
- `server/workspace-filing.ts` - Auto-filing engine: routes deliverables to #Code_Blocks, #Documents, #Images; auto-deploys HTML to Sandbox
- `server/storage.ts` - DatabaseStorage with all CRUD operations
- `server/seed.ts` - Database seeding with sample work orders
- `server/db.ts` - Database connection pool
- `shared/schema.ts` - Data models (subAgents, workOrders, executionLogs, llmSettings, users, workflowTemplates, workflowSteps, workflowExecutions, workflowStepRuns, tools, subAgentTools, artifactFolders, artifacts, sandboxSessions, chatSessions, chatMessages)

## Key API Endpoints
- `GET /api/health` - System health check
- `GET /api/login` - Initiates Replit Auth login (redirects to OIDC provider)
- `GET /api/logout` - Logs user out and destroys session
- `GET /api/auth/user` - Get current authenticated user (returns 401 if not logged in)
- `GET /api/admin/users` - List all users (admin only)
- `PUT /api/admin/users/:id/role` - Update user role (admin only)
- `GET /api/work-orders` - List all work orders
- `GET /api/work-orders/stats` - Dashboard statistics
- `GET /api/work-orders/recent` - Recent work orders
- `GET /api/work-orders/:id` - Work order detail
- `GET /api/work-orders/:id/logs` - Execution logs for a work order
- `POST /api/work-orders` - Submit new work order
- `POST /api/work-orders/:id/process` - Process a pending work order
- `PUT /api/work-orders/:id` - Update work order (title, description, type, priority)
- `POST /api/work-orders/:id/retry` - Retry a blocked/failed work order
- `POST /api/work-orders/:id/refile` - Re-trigger workspace filing for a completed work order
- `POST /api/work-orders/:id/unblock` - HITL unblock: clear BDM marker with resolution notes, optionally re-process
- `GET /api/sub-agents` - List all sub-agents
- `GET /api/sub-agents/:id` - Get sub-agent detail
- `POST /api/sub-agents` - Create a sub-agent
- `PUT /api/sub-agents/:id` - Update a sub-agent
- `DELETE /api/sub-agents/:id` - Delete a sub-agent
- `GET /api/llm-settings` - Get Aiden LLM configuration
- `PUT /api/llm-settings` - Update Aiden LLM configuration
- `POST /api/llm-settings/test` - Test LLM provider connection
- `GET /api/workflow-templates` - List workflow templates
- `GET /api/workflow-templates/:id` - Get template with steps
- `POST /api/workflow-templates` - Create workflow template
- `PUT /api/workflow-templates/:id` - Update workflow template
- `DELETE /api/workflow-templates/:id` - Delete workflow template
- `POST /api/workflow-templates/:templateId/steps` - Create workflow step
- `PUT /api/workflow-steps/:id` - Update workflow step
- `DELETE /api/workflow-steps/:id` - Delete workflow step
- `GET /api/workflow-executions` - List workflow executions
- `GET /api/workflow-executions/:id` - Get execution with step runs
- `POST /api/workflow-executions` - Start workflow execution
- `POST /api/workflow-executions/:id/advance` - Advance workflow execution
- `GET /api/tools` - List all tools
- `GET /api/tools/:id` - Get tool detail
- `POST /api/tools` - Create/deploy a tool
- `PUT /api/tools/:id` - Update a tool
- `DELETE /api/tools/:id` - Delete a tool
- `GET /api/sub-agents/:id/tools` - Get tools assigned to a sub-agent
- `POST /api/sub-agents/:id/tools` - Assign a tool to a sub-agent
- `DELETE /api/sub-agents/:subAgentId/tools/:toolId` - Remove tool assignment
- `GET /api/artifact-folders` - List folders (query: parentId=root for root level)
- `GET /api/artifact-folders/:id` - Get folder detail
- `POST /api/artifact-folders` - Create folder
- `PUT /api/artifact-folders/:id` - Update folder
- `DELETE /api/artifact-folders/:id` - Delete folder (cascades)
- `GET /api/artifacts` - List artifacts (query: folderId=root for root level)
- `GET /api/artifacts/:id` - Get artifact detail
- `POST /api/artifacts` - Create artifact
- `PUT /api/artifacts/:id` - Update artifact
- `DELETE /api/artifacts/:id` - Delete artifact
- `POST /api/workspace/seed` - Initialize workspace with default folder structure
- `GET /api/sandbox-sessions` - List sandbox sessions
- `GET /api/sandbox-sessions/:id` - Get session detail
- `POST /api/sandbox-sessions` - Create sandbox session
- `PUT /api/sandbox-sessions/:id` - Update session
- `DELETE /api/sandbox-sessions/:id` - Delete session
- `POST /api/sandbox-sessions/:id/execute` - Execute command in sandbox
- `GET /api/sandbox-sessions/:id/preview` - Serve raw HTML preview for renderable sandbox sessions (iframe)
- `GET /api/chat/sessions` - List chat sessions (GCC memory protocol)
- `POST /api/chat/sessions` - Create new chat session with correlationId
- `GET /api/chat/sessions/:id` - Get session detail with messages
- `PUT /api/chat/sessions/:id` - Update session (title, status)
- `DELETE /api/chat/sessions/:id` - Delete session and messages
- `POST /api/chat/sessions/:id/messages` - Send message to session (persists + calls LLM + updates GCC memory breadcrumbs)
- `POST /api/chat` - Legacy chat endpoint (sends message + history, returns LLM response with system context)

## LLM Integration
- **Providers**: OpenAI, Anthropic, OpenRouter, Groq
- **API Keys**: Stored as secrets (OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY)
- **System Prompt**: Configurable via Settings page, defines Aiden's behavior as Tier 1 manager
- **Fallback**: When LLM is disabled or fails, hardcoded orchestration rules are used
- **Structured Output**: LLM responses are parsed with Zod schemas for Tier1Result/Tier2Result
- **Per-Sub-Agent LLM**: Each sub-agent can have its own LLM configuration (provider, model, API key, system prompt) for Tier 2 execution. When enabled, the sub-agent uses its own model instead of Aiden's global settings. Falls back to global if sub-agent key is missing or LLM is disabled. Configured via the Sub-Agents page with fields: llmEnabled, llmProvider, llmModel, llmBaseUrl, llmSystemPrompt, llmApiKeyEnvVar.

## Orchestration Flow
1. Work order submitted via API
2. Aiden (Tier 1) evaluates against policy rules
3. If approved, Aiden routes to the best matching sub-agent
4. If sub-agent is "aiden" mode -> Aiden runs Tier 2 execution automatically
5. If sub-agent is "independent" mode -> work order set to "awaiting_operator" for human/AI action
6. Sub-agents can emit BDM markers if execution is blocked
7. Aiden resolves or pauses for human decision

## Multi-Step Workflow Orchestration
1. Workflow templates define reusable multi-step pipelines with ordered steps
2. Each step can be assigned a sub-agent type, specific sub-agent, and tools
3. Steps support dependencies, conditions, retry policies, and timeouts
4. Workflow executions track running instances step-by-step
5. Aiden selects appropriate tools for each step during execution
6. Steps pause for independent operators (awaiting_operator status)
7. Workflow engine resolves dependencies and advances through steps automatically

## Agentic Tools Platform
- Tools are deployable capabilities (slash_command, skill, cli, api, webhook)
- Tools are registered in the tools registry with versioning and status
- Tools are assigned to sub-agents for use during workflow execution
- Aiden selects tools per step based on sub-agent assignments and step requirements

## Work Order Statuses
- `pending` - Awaiting processing
- `processing` - Being evaluated by Aiden
- `completed` - Successfully executed
- `blocked` - Blocked by policy or BDM marker
- `failed` - Execution failed
- `awaiting_operator` - Assigned to independent sub-agent, waiting for operator

## Workflow Step Statuses
- `pending` - Step not yet started
- `running` - Step currently executing
- `completed` - Step finished successfully
- `skipped` - Step skipped (conditions not met)
- `failed` - Step execution failed
- `awaiting_operator` - Waiting for independent operator

## Running
- `npm run dev` starts both frontend and backend on port 5000
- `npm run db:push` pushes schema changes to database
