# AIDEN_PTIB - Intelligent Work Order Orchestration

## Overview
AIDEN_PTIB is a 2-tier work order orchestration platform:
- **Tier 1 — Aiden (Manager)**: LLM-powered policy gate, approvals, routing decisions
- **Tier 2 — Sub-Agents (Workers)**: Specialized workers that execute work orders
  - **Aiden-controlled**: Aiden directly controls and executes through the sub-agent
  - **Independent**: Authorized human or AI operator executes independently
- **System Admin**: A human who configures sub-agents, their control modes, and operator assignments
- **GCC Memory**: Shared context between tiers (routing context, correlation IDs, execution breadcrumbs)
- **BDM Markers**: Blocked Decision Markers emitted when work orders cannot proceed

## Architecture
- Frontend: React + TypeScript + Vite + TanStack Query + Wouter + shadcn/ui
- Backend: Express.js + Drizzle ORM + PostgreSQL
- LLM: OpenAI SDK (for OpenAI/OpenRouter/Groq) + Anthropic SDK (for Claude)
- Styling: Tailwind CSS with Inter font family

## Project Structure
- `client/src/pages/` - Dashboard, WorkOrders, WorkOrderDetail, SubmitOrder, SystemHealth, Architecture, Settings, SubAgents
- `client/src/components/` - AppSidebar, ThemeProvider, ThemeToggle, StatusBadge
- `client/src/hooks/` - usePageTitle
- `server/routes.ts` - API endpoints
- `server/orchestration.ts` - Aiden (Tier 1) and sub-agent (Tier 2) processing logic
- `server/llm-client.ts` - Multi-provider LLM abstraction with structured JSON parsing
- `server/storage.ts` - DatabaseStorage with all CRUD operations
- `server/seed.ts` - Database seeding with sample work orders
- `server/db.ts` - Database connection pool
- `shared/schema.ts` - Data models (subAgents, workOrders, executionLogs, llmSettings, users)

## Key API Endpoints
- `GET /api/health` - System health check
- `GET /api/work-orders` - List all work orders
- `GET /api/work-orders/stats` - Dashboard statistics
- `GET /api/work-orders/recent` - Recent work orders
- `GET /api/work-orders/:id` - Work order detail
- `GET /api/work-orders/:id/logs` - Execution logs for a work order
- `POST /api/work-orders` - Submit new work order
- `POST /api/work-orders/:id/process` - Process a pending work order
- `POST /api/work-orders/:id/retry` - Retry a blocked/failed work order
- `GET /api/sub-agents` - List all sub-agents
- `GET /api/sub-agents/:id` - Get sub-agent detail
- `POST /api/sub-agents` - Create a sub-agent
- `PUT /api/sub-agents/:id` - Update a sub-agent
- `DELETE /api/sub-agents/:id` - Delete a sub-agent
- `GET /api/llm-settings` - Get Aiden LLM configuration
- `PUT /api/llm-settings` - Update Aiden LLM configuration
- `POST /api/llm-settings/test` - Test LLM provider connection

## LLM Integration
- **Providers**: OpenAI, Anthropic, OpenRouter, Groq
- **API Keys**: Stored as secrets (OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY)
- **System Prompt**: Configurable via Settings page, defines Aiden's behavior as Tier 1 manager
- **Fallback**: When LLM is disabled or fails, hardcoded orchestration rules are used
- **Structured Output**: LLM responses are parsed with Zod schemas for Tier1Result/Tier2Result

## Orchestration Flow
1. Work order submitted via API
2. Aiden (Tier 1) evaluates against policy rules
3. If approved, Aiden routes to the best matching sub-agent
4. If sub-agent is "aiden" mode → Aiden runs Tier 2 execution automatically
5. If sub-agent is "independent" mode → work order set to "awaiting_operator" for human/AI action
6. Sub-agents can emit BDM markers if execution is blocked
7. Aiden resolves or pauses for human decision

## Work Order Statuses
- `pending` - Awaiting processing
- `processing` - Being evaluated by Aiden
- `completed` - Successfully executed
- `blocked` - Blocked by policy or BDM marker
- `failed` - Execution failed
- `awaiting_operator` - Assigned to independent sub-agent, waiting for operator

## Running
- `npm run dev` starts both frontend and backend on port 5000
- `npm run db:push` pushes schema changes to database
