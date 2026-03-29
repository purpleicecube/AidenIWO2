# Know-How Retrieval — User Guide

**AIDEN IWO v0.9.7+ | Last updated: 2026-03-27**

---

## What Is Know-How?

Know-How is AIDEN's context retrieval system. It feeds relevant reference material — code snippets, design guides, brand docs — directly into Work Order execution and Chat, so the AI works from **your actual sources** instead of guessing.

Think of it as: *"Hey AIDEN, when you do this task, look at these references first."*

---

## Two Ways It Activates

### 1. Automatic (Chat & Work Orders)

Just mention a source naturally. AIDEN detects keywords like **from**, **in**, **using**, **folder**, **reference**, **code block**, **snippet** and pulls matching content.

**Examples:**

```
Build a landing page using the brand guide in Design References/colors.md
```
```
Write copy based on the content from 04_Resources/Demo_Content
```
```
Show me the Python snippets about data processing
```

### 2. Explicit (Work Order `contextRequest` field)

Set the `contextRequest` JSON on a Work Order for precise control:

```json
{
  "paths": ["04_Resources/brand_guide.md"],
  "keywords": ["brand", "palette"],
  "codeLanguages": ["css"],
  "sourceTypes": ["code_block"],
  "tokenBudget": 6000
}
```

Explicit requests override auto-detection and give you full control over what AIDEN sees.

---

## How Sources Are Ranked

Know-How uses a **deterministic scoring system** (no vector search — predictable results every time):

| Priority | Source Type | Score | How It Matches |
| --- | --- | --- | --- |
| 1 | Explicit path | 1.0 | You named the exact file/folder |
| 2 | Keyword match | 0.7-0.8 | Matches artifact names & content |
| 3 | Code block | 0.6-0.9 | Matches language + tags + keywords |
| 4 | GCC boost | +0.1 | Recent agent memory reinforces relevance |

Sources are ranked by score, then by recency. The top results are packed into a **token budget** (default: 8,000 tokens) and injected into the AI prompt with grounding rules.

---

## Code Blocks

Code blocks are reusable snippets stored in AIDEN. They're the primary fuel for Know-How.

### Auto-Extracted

When a Work Order produces output containing fenced code (` ```css `, ` ```json `, etc.), AIDEN automatically extracts and stores those blocks with tags like `auto-extracted`, the language, and the source WO name.

### Manual Creation

Operators can create code blocks via the API:

```
POST /api/code-blocks
Content-Type: application/json

{
  "name": "klear-brand-palette",
  "language": "css",
  "content": ":root { --primary: #8B49E2; --navy: #091C53; }",
  "tags": ["brand", "klear", "colors"],
  "description": "Klear.ai primary brand colors"
}
```

### Browsing Code Blocks

```
GET /api/code-blocks
GET /api/code-blocks?language=css
GET /api/code-blocks?tag=brand
GET /api/code-blocks/:id
```

---

## Grounding Rules

When Know-How content is injected, AIDEN receives strict grounding instructions:

- **Use ONLY** facts, data, and quotes found in the provided sources
- **Do NOT** invent or extrapolate numbers, stats, or claims
- **Cite** which source a fact came from
- **Say so** if the sources don't contain what's needed

This prevents hallucination and keeps deliverables traceable to your actual reference material.

---

## ContextRequest Parameters

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `paths` | string[] | — | Explicit file/folder paths to include |
| `keywords` | string[] | — | Search terms for artifact matching |
| `sourceTypes` | string[] | all | `"artifact"`, `"code_block"`, `"workspace_file"`, `"operator_prompt"`, `"gcc_advisory"` |
| `codeLanguages` | string[] | — | Filter code blocks by language (`"css"`, `"python"`, etc.) |
| `tokenBudget` | number | 8000 | Max tokens for all sources combined |
| `maxPerSource` | number | 4000 | Max tokens per individual source |
| `limit` | number | 10 | Max number of sources to return |
| `recencyDays` | number | — | Only include sources updated within N days |
| `excludeIds` | string[] | — | Source IDs to skip |
| `operatorHint` | string | — | Free-text guidance for retrieval tuning |

---

## Audit Trail

Every retrieval is logged. View the last 50:

```
GET /api/knowhow/retrievals
```

Each record shows: what was requested, how many sources matched, tokens used, whether the budget was exceeded, and any errors.

---

## Tips

- **Be specific with paths** — `"04_Resources/Brand/colors.md"` scores 1.0 vs keyword guessing at 0.7
- **Tag your code blocks well** — tags directly improve matching score
- **Use `codeLanguages`** — filtering by language adds +0.2 to code block scores
- **Check retrievals** — if a Work Order missed context, inspect `/api/knowhow/retrievals` to see what was (or wasn't) resolved
- **Token budget matters** — large reference docs may get truncated; raise `tokenBudget` or split into focused code blocks

---

## Quick Reference

| Action | How |
| --- | --- |
| Trigger in Chat | Use words like "from", "in", "using", "folder", "reference" + a path or keyword |
| Trigger in Work Order | Set `contextRequest` JSON, or just describe sources in the title/description |
| Create a code block | `POST /api/code-blocks` (operator role) |
| List code blocks | `GET /api/code-blocks` |
| Test a retrieval | `POST /api/knowhow/resolve` with a `ContextRequest` body |
| View audit log | `GET /api/knowhow/retrievals` |
