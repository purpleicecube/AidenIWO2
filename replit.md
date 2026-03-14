# AIDEN_IWO v0.9.5 - Intelligent Work Order Orchestration

## Overview
AIDEN_IWO is a two-tier work order orchestration platform designed to streamline and automate complex operational workflows. It intelligently routes and manages work orders using AI-powered policy evaluation, human-in-the-loop (HITL) intervention, and specialized sub-agents. The platform aims to reduce manual effort, improve efficiency, and provide comprehensive visibility into work order lifecycles.

Key capabilities include:
- Two-Tier Orchestration: Aiden (Tier 1) manages policy evaluation and routing, while specialized Sub-Agents (Tier 2) execute work orders.
- LLM-Powered Routing: Utilizes multiple LLM providers for dynamic policy evaluation and routing.
- Human-in-the-Loop (HITL): Allows intervention on blocked, failed, or pending work orders.
- Multi-step Workflow Templates: Supports complex workflows with dependencies, conditions, and retry mechanisms.
- Agentic Tools Platform: Provides a framework for integrating and assigning various tools to sub-agents.
- Workspace & Sandbox: Offers artifact/folder management and sandboxed environments for command execution.
- Role-Based Access Control (RBAC): Manages user permissions for secure platform access.

## User Preferences
I want iterative development.
I prefer detailed explanations of decisions made, especially for critical routing or blocking events.
I want to be asked before any major architectural changes or significant modifications to core orchestration logic.
I prefer a clean, readable codebase and clear documentation.
I want to be kept informed about the status of work orders, particularly when human intervention is required.

## System Architecture
AIDEN_IWO employs a modern web stack with React, TypeScript, Vite, TanStack Query, Wouter, and shadcn/ui for the frontend, and Express.js with Drizzle ORM and PostgreSQL for the backend. Styling is managed with Tailwind CSS, offering dark/light theme support. LLM integration is handled via the OpenAI SDK (for OpenAI, OpenRouter, Groq) and Anthropic SDK (for Claude).

**Core Architectural Patterns & Design Decisions:**
- **Two-Tier Orchestration:** Clear separation between Aiden (high-level decisions, mandatory Tier 1 quality review) and sub-agents (execution). Features an autonomous revision loop for Aiden-controlled sub-agents to automatically address quality review rejections.
- **Multi-Provider LLM Abstraction:** A unified interface supports various LLM providers for robust decision-making.
- **PocketFlow Iterative Execution Engine:** A sophisticated Tier 2 engine enabling iterative planning, execution, evaluation, and refinement of steps, supporting parallel execution and delta-only refinement. Includes **format-aware prompt guidance** that detects the requested output format (HTML, code, document) from the work order title/description and injects explicit format constraints into both planning and execution prompts — preventing the LLM from producing JSON metadata or structural outlines instead of actual deliverables. **Smart deliverable assembly**: When building the final deliverable, PocketFlow filters intermediate outputs (raw JSON data, metadata, status messages) from the final product, selects the best HTML output when multiple step outputs are available, and cleans escape characters/trailing junk. **Structural pre-check gate**: Before the LLM quality review, a deterministic structural pre-check catches hard failures (raw escape chars in HTML, leaked JSON arrays, placeholder content like "Headline N – Source") and immediately rejects them without wasting an LLM call. Soft structural warnings are passed to the LLM reviewer as context.
- **GCC Memory Protocol:** A shared context mechanism for consistent state management across tiers.
- **BDM (Blocked Decision Marker) System:** A structured approach for managing work order blockages and facilitating HITL intervention.
- **Three-Tier Workflow Engine:** Full Aiden (Executive) → PM Sub-Agent → Step Workers hierarchy. PM sub-agents (`project_manager` type) coordinate multi-step workflows, perform front-line quality reviews of step outputs, request revisions, assemble final work products, and escalate to Aiden or HITL. Aiden performs final executive review. Steps execute via real PocketFlow with each step agent's LLM and tools. Templates support `preferredPmId`, `executionMode` (autonomous/semi_autonomous/manual), and `llmMode` (shared_with_aiden/own_llm/inherited). Step-level retry/skip/resolve API endpoints for operator control. PM coordination module: `server/workflow-pm.ts`. Workflow steps support three types via `stepType` field: `internal` (PM handles directly, no formal work order), `work_order` (creates a linked child work order through the full Aiden pipeline with GCC tracking), and `external` (placeholder for work done outside AIDEN_IWO — workflow pauses until operator marks it complete).
- **Agentic Tools Platform:** Standardized integration and assignment of diverse tools to sub-agents, enhancing capabilities.
- **Replit Auth Integration:** Secure user authentication with RBAC.
- **Responsive UI/UX:** Built with `shadcn/ui` and Tailwind CSS for a modern, accessible user experience.
- **Workspace Filing Engine & Sandbox:** Automates deliverable routing and artifact deployment. Supports HTML, code block, JavaScript (browser-compatible with console capture), Python (Pyodide), and Markdown previews within a secure sandboxed environment with a Content Security Policy (CSP). Sandbox previews use `srcdoc` iframes to render HTML inline without requiring a separate authenticated fetch, with embedded CSP meta tags for CDN access. Unfenced code detection extracts Python/JS from mixed markdown-code deliverables using heuristic scoring.
- **Work Order Lifecycle Management:** Comprehensive states including `pending`, `processing`, `completed`, `blocked`, `failed`, `awaiting_operator`, `reopened`, `deferred`, and archiving capabilities. Includes resilience features: startup orphan recovery (detects WOs stuck in "processing" >10min and sets to "failed"), stale processing guard (allows re-processing stuck WOs), and crash-safe background execution wrapper (`processWorkOrderSafe`) that catches errors and sets WO to "failed" instead of leaving orphaned.
- **Background Processing:** Work order process, retry, and HITL re-process endpoints respond immediately and run orchestration in the background via `processWorkOrderSafe`. The work order detail page auto-polls every 3s/5s while status is "processing" to reflect real-time progress.
- **Chat Organization:** Chat history supports grouping, nesting, archiving, drag-and-drop, and bulk move operations. Bulk select mode allows selecting multiple chats and moving them to a folder in one action via a dedicated dialog, with Select All/Deselect All and Ungroup options.
- **Chat Action Execution:** Aiden can create work orders from chat using a model-agnostic three-tier extraction architecture for flexible and reliable command processing.
- **Per-Sub-Agent LLM Configuration:** Allows independent LLM settings for individual sub-agents, enabling specialized AI behaviors.
- **HITL Capabilities:** Three intervention actions: Override Block & Continue, Close Without Processing, and Defer Decision, applicable to blocked, failed, and awaiting_operator orders. Admin-only **Kill** action immediately stops a work order (any non-completed status), sets status to "killed", auto-archives with "Killed" tag and reason. Kill button uses destructive red styling with skull icon. Work orders have a `tags` text array column for metadata labels.
- **Tools Locker System:** A governed, shared repository of callable tools and reusable skills. Tools are automatically discovered, injected into LLM prompts, and executed during work order processing. Includes features for governance (access tiers, limits), leasing, audit logs, and per-agent entitlements and history. Supports various tool types including MCP (Model Context Protocol) servers, skills, API calls, and code execution. Core tools with live execution: **Brave Search** (real API calls), **WebScrapper** (real HTTP fetch + HTML-to-text extraction), **Health Check CLI** (real HTTP HEAD probes with latency), **Data Validator** (CSV parsing + field validation), **PDF Processor** (URL fetch + text extraction). **Import Skills feature**: Admin users can import approved Claude Skills from the project's `.local/skills/` directory directly into the Tools Locker via an "Import Skills" dialog. The scanner reads SKILL.md files and their reference documents, auto-detecting name/description from frontmatter. Skills are imported as `skill` type tools with `prompt_injection` execution mode. Path traversal protection prevents reading files outside the skills directory.

## External Dependencies
- **PostgreSQL:** Primary database for persistent storage.
- **OpenAI:** Large Language Model provider.
- **Anthropic:** Large Language Model provider (Claude).
- **OpenRouter:** Large Language Model provider.
- **Groq:** Large Language Model provider.
- **Replit Auth:** User authentication and authorization service.
- **SendGrid:** Email integration for notifications.