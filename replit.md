# AIDEN_PTIB - Intelligent Work Order Orchestration

## Overview
AIDEN_PTIB is a 2-tier work order orchestration platform designed to streamline and automate complex operational workflows. Its primary purpose is to intelligently route and manage work orders using AI-powered policy evaluation and routing, human-in-the-loop (HITL) intervention, and specialized sub-agents. The platform aims to reduce manual effort, improve efficiency, and provide comprehensive visibility into work order lifecycles.

**Key Capabilities:**
- **Two-Tier Orchestration:** Aiden (Tier 1) acts as an LLM-powered manager for policy evaluation and routing, while specialized Sub-Agents (Tier 2) execute work orders.
- **LLM-Powered Routing:** Utilizes multiple LLM providers for dynamic policy evaluation and routing of work orders.
- **Human-in-the-Loop (HITL):** Allows for intervention on blocked, failed, or pending work orders, enabling re-issuing or closing with explanations.
- **Multi-step Workflow Templates:** Supports the creation and execution of complex workflows with step dependencies, conditions, and retry mechanisms.
- **Agentic Tools Platform:** Provides a framework for integrating and assigning various tools (slash commands, skills, CLI, API, webhooks) to sub-agents.
- **Workspace & Sandbox:** Offers artifact/folder management and sandboxed environments for command execution.
- **Role-Based Access Control (RBAC):** Manages user permissions (admin, operator, viewer) for secure platform access.

## User Preferences
I want iterative development.
I prefer detailed explanations of decisions made, especially for critical routing or blocking events.
I want to be asked before any major architectural changes or significant modifications to core orchestration logic.
I prefer a clean, readable codebase and clear documentation.
I want to be kept informed about the status of work orders, particularly when human intervention is required.

## System Architecture
**Frontend:** React, TypeScript, Vite, TanStack Query, Wouter, shadcn/ui.
**Backend:** Express.js, Drizzle ORM, PostgreSQL.
**LLM Integration:** OpenAI SDK (for OpenAI, OpenRouter, Groq), Anthropic SDK (for Claude).
**Styling:** Tailwind CSS with Inter font family, offering dark/light theme support.

**Core Architectural Patterns & Design Decisions:**
- **Two-Tier Orchestration:** Clear separation of concerns with Aiden managing high-level decisions and sub-agents handling execution.
- **Multi-Provider LLM Abstraction:** Supports various LLM providers with a unified interface and structured JSON parsing for robust decision-making.
- **PocketFlow Iterative Execution Engine:** A sophisticated Tier 2 execution engine that enables iterative planning, execution, evaluation, and refinement of steps, supporting parallel execution and delta-only refinement for efficiency.
- **GCC Memory Protocol:** Utilizes a shared context mechanism (WS014 P_PODE contract) for consistent state management across tiers.
- **BDM (Blocked Decision Marker) System:** Structured approach to signal and manage work order blockages, enabling informed HITL intervention.
- **Workflow Engine:** Manages multi-step workflow templates with dependency resolution, conditional execution, and retry logic.
- **Agentic Tools Platform:** Provides a standardized way to integrate and assign diverse tools to sub-agents, enhancing their capabilities.
- **Replit Auth Integration:** Secure user authentication with RBAC for granular control over system functionalities.
- **Responsive UI/UX:** Designed with `shadcn/ui` and Tailwind CSS for a modern, responsive, and accessible user experience across various devices.
- **Workspace Filing Engine:** Automates routing of deliverables to specific folders and deployment of HTML artifacts to the sandbox.

**Feature Specifications:**
- **Work Order Lifecycle Management:** Comprehensive states including `pending`, `processing`, `completed`, `blocked`, `failed`, `awaiting_operator`.
- **Per-Sub-Agent LLM Configuration:** Allows independent LLM settings (model, prompt, provider) for individual sub-agents, enabling specialized AI worker behaviors.
- **HITL Capabilities:** Features for re-issuing work orders to Aiden, closing without output, and inline editing of order details during intervention.
- **Admin Tooling:** Includes user management with role assignment and system health monitoring.

**Universal Components:**
- **ImagePlaceholder** (`client/src/components/image-placeholder.tsx`): Reusable image placeholder with drag-and-drop upload. Uses `placeholderId` for persistence. Images stored as base64 in `uploaded_images` table. Supports click/drag upload, replace, remove. API: POST `/api/images/upload`, GET `/api/images/:placeholderId`, GET `/api/images/:placeholderId/meta`, DELETE `/api/images/:placeholderId`.
- **ExpandablePanel** (`client/src/components/expandable-panel.tsx`): Universal fullscreen expand/contract button. Uses React portals for overlay. ESC key to close. Wired into Sandbox preview, Workspace file preview, and Work Order execution timeline.

**Tools Locker System (Phase 1 — Data Foundation):**
A governed, shared repository of callable tools and reusable skills that agents can check out, execute, and return with results and metadata.
- **Locker Governance Fields** on `tools` table: `accessTier` (any/tier1/tier2), `maxConcurrent` (0=unlimited), `defaultLeaseSeconds`, `maxLeaseSeconds`, `dailyUsageLimit`, `costCeilingPerDay`, `requiresApproval`, `restricted`, `restrictedReason`, `restrictedBy`.
- **Tool Tags** (`tool_tags`, `tool_tag_assignments`): Discovery metadata (capability, cost, risk, latency) for categorizing tools.
- **Tool Leases** (`tool_leases`): Checkout/return/lease tracking with agent info, tier, expiry, heartbeat, result/error.
- **Locker Keys** (`locker_keys`): Agent permissions with scopes, tool/tag access, concurrency limits, revocation support.
- **Tool Audit Logs** (`tool_audit_logs`): Full audit trail of checkout, return, restrict, unrestrict actions.
- **Skill Templates** (`skill_templates`): Supports three formats — `claude_md`, `agents_md`, `aiden_md`. Two execution modes: `prompt_injection` (skills loaded into agent context) and `sandbox_execution` (code tools run in sandbox). Fields include `content`, `instructions`, `triggerConditions`, `inputContract`, `outputContract`, `sourceCode`, `entryPoint`, `runtimeEnvironment`, `sandboxConfig`.
- **API Namespace**: All locker routes under `/api/locker/*` — inventory, tags, leases, checkout/return, keys, audit, skills, restrict/unrestrict.

## External Dependencies
- **PostgreSQL:** Primary database for persistent storage.
- **OpenAI:** LLM provider.
- **Anthropic:** LLM provider (Claude).
- **OpenRouter:** LLM provider.
- **Groq:** LLM provider.
- **Replit Auth:** User authentication and authorization service (Google, GitHub login).
- **SendGrid:** Email integration for user invitations and notifications (via Replit Connectors).