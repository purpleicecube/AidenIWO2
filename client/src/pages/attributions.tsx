import { Link } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ArrowLeft, ExternalLink, Scale, GitBranch, Cpu, Layers, Sparkles } from "lucide-react";
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
  licenseVariant: "destructive" | "secondary" | "outline" | "default";
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
            AgentGoPro, Aiden Zephyr/TIB, GCC Memory &amp; PocketFlow — foundational lineages of IWO/PDOE (WS014).
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
              <InfoRow label="Period">Mid-2024 – Aug 2025</InfoRow>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Creator &amp; Origin</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                AgentGoPro — originally named &ldquo;Agent Commander&rdquo; in Replit — was a basic orchestration framework for LLM-based agent coordination, developed independently by Darrel Vaughn under 10Touros (consulting) and LuaAzullaB (R&amp;D lab), beginning mid-2024 and continuing into 2025. The project was renamed from Agent Commander to AgentGoPro during active development. It predates the adoption of PocketFlow and GCC Memory and is the foundational precursor to the PDOE agent orchestration architecture.
              </p>
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
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Jun 2024</span><span>Agent architecture planning (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Jul 2024</span><span>Agent prompt language &amp; infrastructure (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Aug 2024</span><span>Multi-agent team structure (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Nov 2024</span><span>Replit deployment infrastructure (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Dec 2024</span><span>&ldquo;Agent Commander&rdquo; (original Replit project name) / RFP Bridge Assistant LAUNCH — LIVE. Project renamed to AgentGoPro during this period.</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Jan 2025</span><span>API enhancements &amp; expansion (complete)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Feb–Mar 2025</span><span>Advanced agent research &amp; new tools (ongoing)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Through Aug 2025</span><span>PDOE architecture formalized; PocketFlow adopted as execution substrate</span></div>
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
            icon={Sparkles}
            iconClass="bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-400"
            title="Aiden Zephyr & TIB"
            subtitle="Thomas C. Appling III / FF.AI"
            license="Creative Attribution"
            licenseVariant="default"
          >
            <div className="space-y-3">
              <InfoRow label="Contributor">Thomas C. Appling III</InfoRow>
              <InfoRow label="Organization">Freedom Forge AI (FF.AI)</InfoRow>
              <InfoRow label="Type">Creative inspiration &amp; conceptual framing</InfoRow>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Contributor &amp; Source</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Thomas C. Appling III introduced the &ldquo;Aiden Zephyr&rdquo; agent concept and later contributed The Internal Brain (TIB) framework through his work with FF.AI. These ideas shaped the identity, persona, and cognitive architecture of the Aiden agent within PDOE. Note: Darrel Vaughn&rsquo;s multi-agent orchestration framework (Agent Commander, later AgentGoPro) was already in active planning and development prior to the introduction of the Aiden Zephyr concept.
              </p>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Core Contribution</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Two distinct contributions: (1) <strong>Aiden Zephyr</strong> — the original agent identity concept that became &ldquo;Aiden&rdquo; in PDOE&rsquo;s Tier 1 executive orchestrator. Appling&rsquo;s vision gave the agent its name, persona, and early character as an autonomous reasoning entity. (2) <strong>The Internal Brain (TIB)</strong> — a cognitive architecture concept contributed through FF.AI that informed how Aiden processes, reasons, and maintains internal state. TIB influenced the design of Aiden&rsquo;s executive decision-making layer within the two-tier PDOE architecture. The current implementation of the AIDEN_IWO supports the TIB framework but is by design — not limited by it.
              </p>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Timeline &amp; Precedence</h4>
              <div className="space-y-1.5 text-sm text-muted-foreground">
                <div className="rounded-lg bg-rose-50 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-800/40 p-3 mb-3">
                  <p className="text-xs font-semibold text-rose-800 dark:text-rose-300 mb-1">PRECEDENCE NOTE</p>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    Darrel Vaughn began Agent Commander (multi-agent orchestration framework) architecture planning in Jun 2024, with prompt language, infrastructure, and multi-agent team structure built through Aug 2024 — all prior to the introduction of the Aiden Zephyr concept.
                  </p>
                </div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Late 2024</span><span>Aiden Zephyr agentic concepts evolved (Appling)</span></div>
                <div className="flex gap-3"><span className="text-xs font-mono w-24 shrink-0 text-right">Mar 17, 2025</span><span>&ldquo;Aiden Zephyr&rdquo; reference email from Thomas C. Appling III</span></div>
              </div>
              <p className="text-xs text-muted-foreground mt-3 leading-relaxed">
                The Aiden Zephyr identity and FF.AI / TIB concepts were introduced subsequent to Vaughn&rsquo;s foundational orchestration work and were integrated into the already-established multi-agent architecture as creative and conceptual enhancements.
              </p>
            </div>

            <Separator />

            <div className="rounded-lg bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800/50 p-4">
              <h4 className="text-sm font-semibold mb-1.5">License Notice</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                The Aiden Zephyr concept and TIB (The Internal Brain) framework are attributed to Thomas C. Appling III and the Freedom Forge AI (FF.AI) as creative and collaborative contributions. These are acknowledged as inspirational and collaborative inputs, not code-level dependencies. No open-source license applies. Attribution is granted in recognition of creative influence and collaborative development of agent identity, persona design, and cognitive architecture framing within the PDOE ecosystem.
              </p>
            </div>

            <div className="rounded-lg bg-muted/40 p-4">
              <h4 className="text-sm font-semibold mb-1.5">Attribution Statement</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                PDOE gratefully acknowledges Thomas C. Appling III and the Freedom Forge AI (FF.AI) for the creative inspiration behind the Aiden agent identity — originally conceived as &ldquo;Aiden Zephyr&rdquo; — and for the conceptual contributions of The Internal Brain (TIB) cognitive architecture framework. These contributions shaped the persona, identity, and reasoning character of Aiden as PDOE&rsquo;s Tier 1 executive orchestrator. It is expressly noted that Darrel Vaughn&rsquo;s multi-agent orchestration framework (Agent Commander / AgentGoPro) was already in active planning and development prior to the introduction of the Aiden Zephyr concept — the creative identity was layered onto an existing architectural foundation.
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
                GCC applies Git&rsquo;s version-control metaphor to LLM agent memory. Four canonical commands: <strong>COMMIT</strong> (durable milestone snapshot of branch progress), <strong>BRANCH</strong> (isolated memory line for alternate strategy exploration), <strong>MERGE</strong> (consolidate branch outcomes under Tier 1 governance), <strong>CONTEXT</strong> (scoped history retrieval at multiple granularities). Memory artifacts are stored as markdown files in a project/branch/commit filesystem hierarchy.
              </p>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">PDOE Integration (WS014)</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                GCC Memory is a Tier 1 platform service in PDOE, peer to Channel Gateway and Tools Locker. Tier 2 agents may COMMIT and CONTEXT; only Tier 1 may MERGE. Branch creation requires Tier 1 approval (mode-dependent). GCC metadata lives in shared dict (<code className="text-xs bg-muted px-1 py-0.5 rounded">gcc.*</code> keys) and filesystem artifacts only — never injected into Work Order or BDM payloads. Contracts: <code className="text-xs bg-muted px-1 py-0.5 rounded">gcc_command_contract.md</code> (GCC-A-001), <code className="text-xs bg-muted px-1 py-0.5 rounded">gcc_shared_dict_contract.md</code> (GCC-A-002).
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
              <InfoRow label="Author">Zachary Huang (GitHub: zachary62)</InfoRow>
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
              <InfoRow label="PyPI">pocketflow (v0.0.3)</InfoRow>
              <InfoRow label="License">MIT (Copyright 2024 Zachary Huang)</InfoRow>
            </div>

            <Separator />

            <div>
              <h4 className="text-sm font-semibold mb-2">Core Concept</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">
                PocketFlow distills LLM framework abstractions into 100 lines of dependency-free Python. The core is a directed graph of Nodes and Flows: <strong>BaseNode</strong> (prep/exec/post lifecycle, <code className="text-xs bg-muted px-1 py-0.5 rounded">&gt;&gt;</code> and <code className="text-xs bg-muted px-1 py-0.5 rounded">-</code> DSL operators), <strong>Node</strong> (sync with retry), <strong>BatchNode</strong> (list processing), <strong>Flow</strong> (graph orchestrator with start_node and _orch() loop), plus async variants. From this 100-line core, users implement Agents, Multi-Agents, Workflows, RAG, Map-Reduce, Structured Output, and other LLM design patterns.
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
