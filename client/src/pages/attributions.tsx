import { Link } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ArrowLeft, ExternalLink, Scale, GitBranch, Cpu, Layers } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePageTitle } from "@/hooks/use-page-title";

function AttributionSection({
  icon: Icon,
  iconClass,
  title,
  subtitle,
  license,
  licenseVariant,
  children,
}: {
  icon: typeof Layers;
  iconClass: string;
  title: string;
  subtitle: string;
  license: string;
  licenseVariant: "destructive" | "secondary" | "outline";
  children: React.ReactNode;
}) {
  return (
    <Card className="bg-white/50 dark:bg-slate-800/50 border-slate-200/80 dark:border-slate-700/50">
      <CardHeader className="pb-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className={`flex items-center justify-center w-10 h-10 rounded-lg ${iconClass}`}>
              <Icon className="w-5 h-5" />
            </div>
            <div>
              <CardTitle className="text-lg">{title}</CardTitle>
              <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>
            </div>
          </div>
          <Badge variant={licenseVariant} className="shrink-0 mt-1" data-testid={`badge-license-${title.toLowerCase().replace(/\s+/g, "-")}`}>
            <Scale className="w-3 h-3 mr-1" />
            {license}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {children}
      </CardContent>
    </Card>
  );
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-2 text-sm">
      <span className="text-muted-foreground font-medium">{label}</span>
      <span>{children}</span>
    </div>
  );
}

export default function AttributionsPage() {
  usePageTitle("Attributions");

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50 dark:from-slate-950 dark:via-slate-900 dark:to-blue-950">
      <div className="max-w-4xl mx-auto px-6 py-12">
        <div className="flex items-center gap-3 mb-2">
          <Link href="/">
            <Button variant="ghost" size="sm" data-testid="button-back-from-attributions">
              <ArrowLeft className="w-4 h-4 mr-1" />
              Back
            </Button>
          </Link>
        </div>

        <div className="mb-10">
          <h1 className="text-3xl font-serif font-bold tracking-tight text-slate-900 dark:text-white">
            Attribution Register
          </h1>
          <p className="text-muted-foreground mt-2">
            AgentGoPro, GCC Memory &amp; PocketFlow — foundational components of PDOE (WS014).
          </p>
          <p className="text-xs text-muted-foreground mt-1">Collected 2026-02-21</p>
        </div>

        <div className="space-y-8">
          <AttributionSection
            icon={Layers}
            iconClass="bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400"
            title="AgentGoPro"
            subtitle="LuaAzullaB Orchestration Framework"
            license="Proprietary"
            licenseVariant="destructive"
          >
            <div className="space-y-3">
              <InfoRow label="Author">Darrel Vaughn</InfoRow>
              <InfoRow label="Consulting">10Touros</InfoRow>
              <InfoRow label="Lab">LuaAzullaB (formerly LuaLab)</InfoRow>
              <InfoRow label="Period">Mid-2024 – 2025</InfoRow>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Core Concept</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                AgentGoPro established the foundational orchestration patterns later refined in PDOE: agent-to-agent task delegation, tiered authority (executive vs. execution layers), structured handoff protocols, and flow-based coordination of LLM agents. This original framework informed the architectural decisions that led to adopting PocketFlow as the production execution substrate and GCC Memory as the persistence layer.
              </p>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Timeline &amp; Lineage</h4>
              <div className="space-y-1.5 text-sm text-muted-foreground">
                <div className="flex gap-3"><span className="text-xs font-mono w-20 shrink-0 text-right">Jun 2024</span><span>Agent architecture planning (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-20 shrink-0 text-right">Jul 2024</span><span>Agent prompt language &amp; infrastructure (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-20 shrink-0 text-right">Aug 2024</span><span>Multi-agent team structure (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-20 shrink-0 text-right">Nov 2024</span><span>Replit deployment infrastructure (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-20 shrink-0 text-right">Dec 2024</span><span>Agent Go Pro / RFP Bridge Assistant — LIVE</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-20 shrink-0 text-right">Jan 2025</span><span>API enhancements &amp; expansion (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-20 shrink-0 text-right">Feb–Mar 2025</span><span>Advanced agent research &amp; new tools (ongoing)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-20 shrink-0 text-right">Mid 2025</span><span>PDOE architecture formalized; PocketFlow adopted</span></div>
              </div>
            </div>

            <Separator />

            <div className="rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50 p-4">
              <h4 className="text-sm font-semibold mb-1.5">License Notice</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                AgentGoPro is proprietary software owned by Darrel Vaughn, operating under 10Touros (consulting company) and LuaAzullaB (formerly LuaLab, R&amp;D lab). This is NOT open-source. No MIT, Apache, or Creative Commons license applies. All rights to the AgentGoPro codebase, design patterns, and derived orchestration concepts are retained by Darrel Vaughn / 10Touros / LuaAzullaB. Any reproduction, distribution, or derivative use requires explicit written permission from the rights holder.
              </p>
            </div>

            <div className="rounded-lg bg-muted/40 p-4">
              <h4 className="text-sm font-semibold mb-1.5">Attribution Statement</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                AgentGoPro is the original LLM agent orchestration framework created by Darrel Vaughn under 10Touros (consulting) and LuaAzullaB (formerly LuaLab, R&amp;D lab), developed from mid-2024 into 2025. It established the foundational patterns for tiered agent governance, structured task delegation, and flow-based orchestration that underpin the PDOE architecture. AgentGoPro is proprietary software — all rights reserved by Darrel Vaughn / 10Touros / LuaAzullaB. The subsequent adoption of PocketFlow and GCC Memory within PDOE builds upon and extends these original concepts under their respective open-source licenses.
              </p>
            </div>
          </AttributionSection>

          <AttributionSection
            icon={GitBranch}
            iconClass="bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-400"
            title="GCC Memory"
            subtitle="Git Context Controller"
            license="CC BY 4.0 / MIT"
            licenseVariant="secondary"
          >
            <div className="space-y-3">
              <InfoRow label="Paper">Wu, Junde. &ldquo;Git Context Controller: Manage the Context of LLM-based Agents like Git.&rdquo; arXiv:2508.00031 (2025)</InfoRow>
              <InfoRow label="DOI">
                <a href="https://doi.org/10.48550/arXiv.2508.00031" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-1" data-testid="link-gcc-doi">
                  10.48550/arXiv.2508.00031 <ExternalLink className="w-3 h-3" />
                </a>
              </InfoRow>
              <InfoRow label="URL">
                <a href="https://arxiv.org/abs/2508.00031" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-1" data-testid="link-gcc-arxiv">
                  arxiv.org/abs/2508.00031 <ExternalLink className="w-3 h-3" />
                </a>
              </InfoRow>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Core Concept</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                GCC applies Git&rsquo;s version-control metaphor to LLM agent memory. Four canonical commands: <strong>COMMIT</strong> (durable milestone snapshot), <strong>BRANCH</strong> (isolated memory line for alternate strategy exploration), <strong>MERGE</strong> (consolidate branch outcomes under Tier 1 governance), <strong>CONTEXT</strong> (scoped history retrieval). Memory artifacts are stored as markdown files in a project/branch/commit filesystem hierarchy.
              </p>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">PDOE Integration (WS014)</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                GCC Memory is a Tier 1 platform service in PDOE, peer to Channel Gateway and Tools Locker. Tier 2 agents may COMMIT and CONTEXT; only Tier 1 may MERGE. Branch creation requires Tier 1 approval (mode-dependent). GCC metadata lives in shared dict (<code className="text-xs bg-muted px-1 py-0.5 rounded">gcc.*</code> keys) and filesystem artifacts only — never injected into Work Order or BDM payloads.
              </p>
            </div>

            <Separator />

            <div className="rounded-lg bg-purple-50 dark:bg-purple-950/30 border border-purple-200 dark:border-purple-800/50 p-4">
              <h4 className="text-sm font-semibold mb-1.5">License Details</h4>
              <div className="space-y-1 text-xs text-muted-foreground">
                <p><strong>Paper (CC BY 4.0):</strong> Cite + attribution if concepts are reused.</p>
                <p><strong>Implementation (MIT):</strong> Preserve MIT notice if code is reused (human-re/GCC).</p>
                <p><strong>Packages (MIT):</strong> Preserve MIT notice if aline-ai package code reused.</p>
              </div>
            </div>

            <div className="rounded-lg bg-muted/40 p-4">
              <h4 className="text-sm font-semibold mb-1.5">Attribution Statement</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                The GCC Memory Framework in PDOE is inspired by &ldquo;Git Context Controller: Manage the Context of LLM-based Agents like Git&rdquo; (Junde Wu, arXiv:2508.00031, 2025, CC BY 4.0). The reference implementation at human-re/GCC and the aline-ai tooling packages are both MIT-licensed. PDOE adapts the GCC conceptual model — Git-style COMMIT/BRANCH/MERGE/CONTEXT commands for persistent agent memory — within its existing two-tier PocketFlow orchestration architecture. No GCC source code is vendored; PDOE uses its own TypeScript implementation conforming to the GCC protocol contracts.
              </p>
            </div>
          </AttributionSection>

          <AttributionSection
            icon={Cpu}
            iconClass="bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-400"
            title="PocketFlow"
            subtitle="100-Line LLM Framework"
            license="MIT"
            licenseVariant="outline"
          >
            <div className="space-y-3">
              <InfoRow label="Author">Zachary Huang</InfoRow>
              <InfoRow label="Affiliation">Microsoft Research AI Frontiers; PhD Columbia University; 2023 Google PhD Fellow</InfoRow>
              <InfoRow label="Organization">The-Pocket (GitHub org)</InfoRow>
              <InfoRow label="Repository">
                <a href="https://github.com/The-Pocket/PocketFlow" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-1" data-testid="link-pocketflow-repo">
                  github.com/The-Pocket/PocketFlow <ExternalLink className="w-3 h-3" />
                </a>
              </InfoRow>
              <InfoRow label="Docs">
                <a href="https://the-pocket.github.io/PocketFlow/" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-1" data-testid="link-pocketflow-docs">
                  the-pocket.github.io/PocketFlow <ExternalLink className="w-3 h-3" />
                </a>
              </InfoRow>
              <InfoRow label="License">MIT (Copyright 2024 Zachary Huang)</InfoRow>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Core Concept</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                PocketFlow distills LLM framework abstractions into 100 lines of dependency-free Python. The core is a directed graph of Nodes and Flows: <strong>BaseNode</strong> (prep/exec/post lifecycle), <strong>Node</strong> (sync with retry), <strong>BatchNode</strong> (list processing), <strong>Flow</strong> (graph orchestrator with start_node and _orch() loop), plus async variants. From this 100-line core, users implement Agents, Multi-Agents, Workflows, RAG, Map-Reduce, Structured Output, and other LLM design patterns.
              </p>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">PDOE Integration (WS012 &rarr; WS014)</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                WS012 is the library/reference workspace (upstream clone + offline docs mirror + PDOE supplement). WS014 is the production integration workspace that vendors PocketFlow core and ships runnable two-tier flows. WS006 is the canonical source for the PocketFlow Supplement spec and schemas (Work Orders, BDM Markers, Policy Gates). PocketFlow runs INSIDE each tier as a flow executor, not as the overall system controller.
              </p>
            </div>

            <Separator />

            <div className="rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800/50 p-4">
              <h4 className="text-sm font-semibold mb-1.5">MIT License</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                MIT License — free to use, copy, modify, merge, publish, distribute, sublicense, sell. Obligation: preserve MIT notice when vendoring code. WS014 vendors <code className="text-xs bg-muted px-1 py-0.5 rounded">pocketflow/__init__.py</code> at <code className="text-xs bg-muted px-1 py-0.5 rounded">02_Execution/vendor/pocketflow/__init__.py</code>.
              </p>
            </div>

            <div className="rounded-lg bg-muted/40 p-4">
              <h4 className="text-sm font-semibold mb-1.5">Attribution Statement</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                PocketFlow, created by Zachary Huang and maintained under The-Pocket GitHub organization, is a minimalist LLM orchestration framework whose entire core fits in 100 lines of Python. It provides a graph-based abstraction (Nodes and Flows) with zero dependencies and zero vendor lock-in, supporting Agents, Multi-Agents, Workflows, and RAG patterns. Licensed under the MIT License (Copyright 2024 Zachary Huang). PDOE vendors the 100-line core from WS012 into the WS014 production runtime and extends it with PDOE-specific nodes for two-tier orchestration.
              </p>
            </div>
          </AttributionSection>
        </div>

        <footer className="mt-12 pt-6 border-t border-slate-200 dark:border-slate-800 text-center text-sm text-muted-foreground space-y-1">
          <p>AIDEN_PTIB v0.5.2 — Intelligent Work Orchestration</p>
          <p className="text-xs">designed by LuaAzullaB | darrel vaughn</p>
        </footer>
      </div>
    </div>
  );
}
