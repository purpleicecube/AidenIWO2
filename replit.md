# AIDEN_PTIB - Intelligent Work Order Orchestration

## Overview
AIDEN_PTIB is a 2-tier work order orchestration platform built with a manager-worker model:
- **Tier 1 (Manager)**: Policy gate, approvals, routing
- **Tier 2 (Worker)**: Schema validation and execution
- **GCC Memory**: Shared context between tiers (routing context, correlation IDs, execution breadcrumbs)
- **BDM Markers**: Blocked Decision Markers emitted when work orders cannot proceed

## Architecture
- Frontend: React + TypeScript + Vite + TanStack Query + Wouter + shadcn/ui
- Backend: Express.js + Drizzle ORM + PostgreSQL
- Styling: Tailwind CSS with Inter font family

## Project Structure
- `client/src/pages/` - Dashboard, WorkOrders, WorkOrderDetail, SubmitOrder, SystemHealth, Architecture
- `client/src/components/` - AppSidebar, ThemeProvider, ThemeToggle, StatusBadge
- `server/routes.ts` - API endpoints
- `server/orchestration.ts` - Tier 1/Tier 2 processing logic
- `server/storage.ts` - DatabaseStorage with all CRUD operations
- `server/seed.ts` - Database seeding with sample work orders
- `server/db.ts` - Database connection pool
- `shared/schema.ts` - Data models (workOrders, executionLogs, users)

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

## Orchestration Rules
- Critical deployments are blocked at Tier 1 policy gate
- Critical incidents are blocked at Tier 2 execution (BDM marker)
- No Tier 2 to Tier 2 direct chaining
- GCC memory stores routing context, correlation IDs, and breadcrumbs

## Running
- `npm run dev` starts both frontend and backend on port 5000
- `npm run db:push` pushes schema changes to database
