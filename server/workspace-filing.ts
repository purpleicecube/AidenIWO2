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

function containsCodeBlock(content: string): boolean {
  if (/```(html|css|js|javascript|typescript|tsx|jsx|python|ruby|go|rust|java|c|cpp|csharp|sql|bash|sh|yaml|json|xml|php|swift|kotlin)\b/i.test(content)) {
    return true;
  }
  const codeBlocks = content.match(/```[\s\S]*?```/g);
  if (codeBlocks && codeBlocks.some(block => {
    const inner = block.slice(3, -3).trim();
    return inner.includes('<') && inner.includes('>') || 
           inner.includes('function ') || inner.includes('const ') ||
           inner.includes('import ') || inner.includes('class ') ||
           inner.includes('def ') || inner.includes('fn ');
  })) {
    return true;
  }
  return false;
}

function containsHtmlDocument(content: string): boolean {
  return /<!DOCTYPE\s+html|<html[\s>]/i.test(content);
}

function extractHtmlFromDeliverable(content: string): string | null {
  const htmlBlockMatch = content.match(/```html?\s*\n([\s\S]*?)```/i);
  if (htmlBlockMatch) return htmlBlockMatch[1].trim();

  if (containsHtmlDocument(content)) {
    const startIdx = content.search(/<!DOCTYPE\s+html|<html[\s>]/i);
    if (startIdx >= 0) {
      const htmlContent = content.slice(startIdx);
      const endIdx = htmlContent.lastIndexOf("</html>");
      if (endIdx >= 0) return htmlContent.slice(0, endIdx + 7);
      return htmlContent;
    }
  }
  return null;
}

function resolveOutputFolder(deliverableType: string, deliverableContent: string | null): string {
  if (deliverableType === "code") return "#Code_Blocks";
  if (deliverableType === "image") return "#Images";

  if (deliverableContent && (deliverableType === "mixed" || deliverableType === "document")) {
    if (containsCodeBlock(deliverableContent) || containsHtmlDocument(deliverableContent)) {
      return "#Code_Blocks";
    }
  }

  return "#Documents";
}

function classifyWorkProductFolder(order: WorkOrder): string {
  const tier2 = (order.tier2Result as any) || {};
  const title = (order.title || "").toLowerCase();
  const description = (order.description || "").toLowerCase();
  const deliverableTitle = (tier2.output?.deliverableTitle || "").toLowerCase();
  const deliverableType = (tier2.output?.deliverableType || "").toLowerCase();
  const handler = (tier2.handler || "").toLowerCase();
  const orderType = (order.type || "").toLowerCase();

  const allText = `${title} ${description} ${deliverableTitle} ${deliverableType}`;

  const planningKeywords = [
    "plan", "planning", "roadmap", "strategy", "proposal", "design",
    "blueprint", "architecture", "specification", "scope", "requirements",
    "staging plan", "deployment plan", "migration plan", "rollout plan",
    "assessment", "evaluation", "review plan", "audit plan",
  ];
  if (planningKeywords.some(kw => allText.includes(kw))) {
    return "00_Planning";
  }

  const policyKeywords = [
    "policy", "sop", "directive", "procedure", "guideline", "compliance",
    "standard", "regulation", "protocol", "rule",
  ];
  if (policyKeywords.some(kw => allText.includes(kw))) {
    return "01_Directive-SOP";
  }

  const orchestrationKeywords = [
    "workflow", "orchestration", "pipeline", "automation", "integration",
    "configuration", "template", "schedule",
  ];
  if (orchestrationKeywords.some(kw => allText.includes(kw))) {
    return "03_Orchestration";
  }

  const resourceKeywords = [
    "template", "reference", "resource", "guide", "documentation",
    "tutorial", "manual", "handbook",
  ];
  if (resourceKeywords.some(kw => allText.includes(kw))) {
    return "04_Resources";
  }

  const testKeywords = [
    "test", "testing", "qa", "quality", "validation", "verification",
    "benchmark", "performance test",
  ];
  if (testKeywords.some(kw => allText.includes(kw))) {
    return "06_Tests";
  }

  return "05_Artifacts";
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
      const outputFolderName = resolveOutputFolder(deliverableType, deliverable);
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

      const htmlContent = extractHtmlFromDeliverable(deliverable);
      if (htmlContent) {
        try {
          const sandboxSession = await storage.createSandboxSession({
            name: `Preview: ${order.title}`,
            description: `Auto-deployed from work order "${order.title}" — renderable HTML preview.`,
            environment: {
              sourceType: "work_order",
              sourceId: order.id,
              deliverableTitle,
              autoDeployed: true,
            },
            createdBy: "aiden",
          });

          const previewLog = {
            timestamp: new Date().toISOString(),
            command: "deploy-preview",
            input: { workOrderId: order.id, title: order.title },
            output: { message: `HTML preview deployed for "${order.title}"`, status: "success" },
          };

          await storage.updateSandboxSession(sandboxSession.id, {
            status: "completed",
            result: { html: htmlContent, renderable: true, title: deliverableTitle },
            logs: [previewLog],
            completedAt: new Date(),
          });

          console.log(`  Sandbox preview deployed: session ${sandboxSession.id}`);
        } catch (sandboxErr: any) {
          console.error("Sandbox auto-deploy failed:", sandboxErr.message);
        }
      }
    }

    const targetFolderName = classifyWorkProductFolder(order);
    let targetFolder = await getRootFolder(targetFolderName);

    if (!targetFolder) {
      targetFolder = artifactsFolder;
    }

    const targetDateFolder = await ensureSubFolder(
      targetFolder.id, targetFolder.path, dateStr,
      `${targetFolder.name.replace(/^\d+_/, "")} from ${dateStr}`
    );

    const targetOrderFolder = await ensureSubFolder(
      targetDateFolder.id, targetDateFolder.path, folderName,
      `Work order: ${order.title}`
    );

    const workProductContent = buildWorkProduct(order, logs, deliverableFilePath, targetFolderName);
    await storage.createArtifact({
      name: "work-product.md",
      folderId: targetOrderFolder.id,
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

    console.log(`Auto-filed work order "${order.title}" to Workspace (02_Execution + ${targetFolderName} + ${deliverableFilePath ? "deliverable" : "no deliverable"})`);
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

function buildWorkProduct(order: WorkOrder, logs: ExecutionLog[], deliverableFilePath: string | null, filedToFolder: string = "05_Artifacts"): string {
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

## Filed To
\`${filedToFolder}\`

## References
- Execution Log: \`02_Execution/${new Date().toISOString().split("T")[0]}/${slugify(order.title)}_${order.id.slice(0, 8)}/execution-log.md\`
- Work Order ID: \`${order.id}\`
- Correlation ID: \`${order.correlationId}\`

---
_Auto-filed by Aiden on ${new Date().toISOString()}_
`;
}
