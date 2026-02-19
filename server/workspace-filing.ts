import { storage } from "./storage";
import type { WorkOrder, ExecutionLog } from "@shared/schema";

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

function getDateFolder(): string {
  return new Date().toISOString().split("T")[0];
}

async function ensureSubFolder(parentFolderId: string, parentPath: string, name: string, description?: string) {
  const existing = await storage.getArtifactFolders(parentFolderId);
  const found = existing.find(f => f.name === name);
  if (found) return found;

  return storage.createArtifactFolder({
    name,
    parentId: parentFolderId,
    path: `${parentPath}/${name}`,
    description: description || null,
  });
}

async function getRootFolder(name: string) {
  const rootFolders = await storage.getArtifactFolders(null);
  return rootFolders.find(f => f.name === name);
}

function getOutputFolderName(deliverableType: string): string {
  switch (deliverableType) {
    case "code": return "#Code_Blocks";
    case "image": return "#Images";
    case "document":
    case "mixed":
    default: return "#Documents";
  }
}

function getFileExtension(deliverableType: string): string {
  switch (deliverableType) {
    case "code": return ".md";
    case "image": return ".md";
    default: return ".md";
  }
}

export async function fileWorkOrderOutput(order: WorkOrder) {
  try {
    const executionFolder = await getRootFolder("02_Execution");
    const artifactsFolder = await getRootFolder("05_Artifacts");
    if (!executionFolder || !artifactsFolder) {
      console.warn("Workspace not initialized — skipping auto-filing. Run POST /api/workspace/seed first.");
      return;
    }

    const dateStr = getDateFolder();
    const orderSlug = slugify(order.title);
    const folderName = `${orderSlug}_${order.id.slice(0, 8)}`;

    const execDateFolder = await ensureSubFolder(
      executionFolder.id, executionFolder.path, dateStr,
      `Executions from ${dateStr}`
    );

    const execOrderFolder = await ensureSubFolder(
      execDateFolder.id, execDateFolder.path, folderName,
      `Work order: ${order.title}`
    );

    const logs = await storage.getExecutionLogs(order.id);

    const executionLogContent = buildExecutionLog(order, logs);
    await storage.createArtifact({
      name: "execution-log.md",
      folderId: execOrderFolder.id,
      type: "file",
      mimeType: "text/markdown",
      content: executionLogContent,
      size: executionLogContent.length,
      status: "active",
      createdBy: "aiden",
      tags: ["auto-filed", "execution-log", order.type],
      sourceType: "work_order",
      sourceId: order.id,
    });

    const tier2 = (order.tier2Result as any) || {};
    const deliverable = tier2.output?.deliverable || null;
    const deliverableType = tier2.output?.deliverableType || "document";
    const deliverableTitle = tier2.output?.deliverableTitle || order.title;
    let deliverableFilePath: string | null = null;

    if (deliverable) {
      const outputFolderName = getOutputFolderName(deliverableType);
      let outputFolder = await getRootFolder(outputFolderName);

      if (!outputFolder) {
        outputFolder = await storage.createArtifactFolder({
          name: outputFolderName,
          path: `/${outputFolderName}`,
          description: `Auto-created output folder for ${outputFolderName.replace("#", "")}`,
          parentId: null,
        });
      }

      if (outputFolder) {
        const outDateFolder = await ensureSubFolder(
          outputFolder.id, outputFolder.path, dateStr,
          `${outputFolderName.replace("#", "")} from ${dateStr}`
        );

        const outOrderFolder = await ensureSubFolder(
          outDateFolder.id, outDateFolder.path, folderName,
          `Work order: ${order.title}`
        );

        const fileSlug = slugify(deliverableTitle);
        const ext = getFileExtension(deliverableType);
        const fileName = `${fileSlug}${ext}`;

        await storage.createArtifact({
          name: fileName,
          folderId: outOrderFolder.id,
          type: "file",
          mimeType: "text/markdown",
          content: deliverable,
          size: deliverable.length,
          status: "active",
          createdBy: "aiden",
          tags: ["auto-filed", "deliverable", deliverableType, order.type],
          sourceType: "work_order",
          sourceId: order.id,
        });

        deliverableFilePath = `${outputFolderName}/${dateStr}/${folderName}/${fileName}`;
        console.log(`  Deliverable saved to ${deliverableFilePath}`);
      }
    }

    const artDateFolder = await ensureSubFolder(
      artifactsFolder.id, artifactsFolder.path, dateStr,
      `Artifacts from ${dateStr}`
    );

    const artOrderFolder = await ensureSubFolder(
      artDateFolder.id, artDateFolder.path, folderName,
      `Work order: ${order.title}`
    );

    const workProductContent = buildWorkProduct(order, logs, deliverableFilePath);
    await storage.createArtifact({
      name: "work-product.md",
      folderId: artOrderFolder.id,
      type: "file",
      mimeType: "text/markdown",
      content: workProductContent,
      size: workProductContent.length,
      status: "active",
      createdBy: "aiden",
      tags: ["auto-filed", "work-product", order.type],
      sourceType: "work_order",
      sourceId: order.id,
    });

    console.log(`Auto-filed work order "${order.title}" to Workspace (02_Execution + 05_Artifacts + ${deliverableFilePath ? "deliverable" : "no deliverable"})`);
  } catch (err: any) {
    console.error("Auto-filing failed:", err.message);
  }
}

function buildExecutionLog(order: WorkOrder, logs: ExecutionLog[]): string {
  const tier1 = (order.tier1Result as any) || {};
  const tier2 = (order.tier2Result as any) || {};
  const gcc = (order.gccMemory as any) || {};

  return `# Execution Log: ${order.title}

## Work Order Summary
| Field | Value |
|-------|-------|
| **ID** | \`${order.id}\` |
| **Correlation ID** | \`${order.correlationId}\` |
| **Type** | ${order.type} |
| **Priority** | ${order.priority} |
| **Status** | ${order.status} |
| **Submitted By** | ${order.submittedBy || "system"} |
| **Created** | ${order.createdAt} |
| **Completed** | ${gcc.completedAt || "N/A"} |

## Description
${order.description}

## Tier 1 — Aiden Policy Decision
- **Approved**: ${tier1.approved ?? "N/A"}
- **Reason**: ${tier1.reason || "N/A"}
- **Mode**: ${tier1.mode || "N/A"}
- **Handler**: ${tier1.handler || "N/A"}

## Tier 2 — Sub-Agent Execution
- **Blocked**: ${tier2.blocked ?? "N/A"}
- **Execution ID**: ${tier2.executionId || "N/A"}
- **Handler**: ${tier2.handler || "N/A"}
- **Output**: ${tier2.output?.message || "N/A"}

## Execution Timeline
${logs.map((log, i) => `${i + 1}. **[Tier ${log.tier}] ${log.action}** — ${log.message} _(${log.createdAt})_`).join("\n") || "No execution logs recorded."}

## GCC Memory (Routing Context)
\`\`\`json
${JSON.stringify(gcc, null, 2)}
\`\`\`

---
_Auto-filed by Aiden on ${new Date().toISOString()}_
`;
}

function buildWorkProduct(order: WorkOrder, logs: ExecutionLog[], deliverableFilePath: string | null): string {
  const tier2 = (order.tier2Result as any) || {};
  const gcc = (order.gccMemory as any) || {};
  const summary = tier2.output?.message || "Work order completed successfully.";
  const deliverableType = tier2.output?.deliverableType || "document";
  const deliverableTitle = tier2.output?.deliverableTitle || order.title;

  const deliverableReference = deliverableFilePath
    ? `**Deliverable**: [\`${deliverableTitle}\`](${deliverableFilePath})
**Location**: \`${deliverableFilePath}\`
**Type**: ${deliverableType}`
    : `_No standalone deliverable was generated. Enable LLM integration in Settings for AI-generated outputs._`;

  return `# Work Product: ${order.title}

## Summary
| Field | Value |
|-------|-------|
| **Work Order** | ${order.title} |
| **Type** | ${order.type} |
| **Priority** | ${order.priority} |
| **Final Status** | ${order.status} |
| **Completed** | ${gcc.completedAt || new Date().toISOString()} |

## Result
${summary}

## Deliverable Output
${deliverableReference}

## Execution Path
${(gcc.breadcrumbs as string[] || []).map((b: string) => `- ${b.replace(/_/g, " ")}`).join("\n") || "- Direct execution"}

## Key Decisions
- **Routing**: ${tier2.handler || "N/A"}
- **Execution Mode**: ${order.executionMode || "auto"}
${order.assignedSubAgentId ? `- **Assigned Sub-Agent**: ${order.assignedSubAgentId}` : ""}

## References
- Execution Log: \`02_Execution/${new Date().toISOString().split("T")[0]}/${slugify(order.title)}_${order.id.slice(0, 8)}/execution-log.md\`
- Work Order ID: \`${order.id}\`
- Correlation ID: \`${order.correlationId}\`

---
_Auto-filed by Aiden on ${new Date().toISOString()}_
`;
}
