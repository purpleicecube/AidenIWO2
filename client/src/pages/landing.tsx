import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Layers, Shield, Zap, GitBranch, Bot, ArrowRight } from "lucide-react";
import { queryClient } from "@/lib/queryClient";

export default function LandingPage() {
  const [loginPending, setLoginPending] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!loginPending) return;
    const timeoutId = setTimeout(() => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      setLoginPending(false);
    }, 5 * 60 * 1000);
    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch("/api/auth/user", { credentials: "include" });
        if (res.ok) {
          if (pollingRef.current) clearInterval(pollingRef.current);
          clearTimeout(timeoutId);
          queryClient.invalidateQueries({ queryKey: ["/api/auth/user"] });
          window.location.reload();
        }
      } catch {}
    }, 2000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      clearTimeout(timeoutId);
    };
  }, [loginPending]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50 dark:from-slate-950 dark:via-slate-900 dark:to-blue-950">
      <nav className="fixed top-0 w-full z-50 backdrop-blur-md bg-white/70 dark:bg-slate-900/70 border-b border-slate-200 dark:border-slate-800">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary">
              <Layers className="w-5 h-5 text-primary-foreground" />
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-semibold tracking-tight">AIDEN_IWO | FF.AI</span>
              <span className="text-[10px] text-muted-foreground">Orchestration Engine</span>
            </div>
          </div>
          <Button asChild data-testid="button-login-nav" onClick={() => setLoginPending(true)}>
            <a href="/api/login" target="_blank" rel="noopener noreferrer">
              {loginPending ? "Waiting for login…" : "Sign In"}
            </a>
          </Button>
        </div>
      </nav>

      <section className="pt-32 pb-20 px-6">
        <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
          <div className="space-y-8">
            <h1 className="text-4xl lg:text-5xl font-serif font-bold tracking-tight text-slate-900 dark:text-white leading-tight">
              Intelligent Work<br />
              <span className="text-primary">Orchestration</span>
            </h1>
            <p className="text-lg text-muted-foreground max-w-lg">
              Aiden is your AI-powered Tier 1 manager. It evaluates policy, routes work orders to specialized sub-agents, and orchestrates multi-step workflows — autonomously.
            </p>
            <div className="flex gap-4">
              <Button size="lg" asChild data-testid="button-login-hero" onClick={() => setLoginPending(true)}>
                <a href="/api/login" target="_blank" rel="noopener noreferrer">
                  {loginPending ? "Waiting for login…" : "Get Started"}
                  {!loginPending && <ArrowRight className="w-4 h-4 ml-2" />}
                </a>
              </Button>
            </div>
            <div className="flex items-center gap-6 text-sm text-muted-foreground">
              <div className="flex items-center gap-1.5">
                <Shield className="w-4 h-4 text-green-600" />
                <span>Role-based access</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Bot className="w-4 h-4 text-blue-600" />
                <span>Multi-LLM support</span>
              </div>
            </div>
          </div>
          <div className="relative hidden lg:block">
            <div className="rounded-2xl bg-gradient-to-br from-primary/10 to-primary/5 dark:from-primary/20 dark:to-primary/5 p-8 border border-primary/10 shadow-lg">
              <div className="space-y-4">
                <div className="flex items-center gap-3 p-3 rounded-lg bg-white/80 dark:bg-slate-800/80 border">
                  <div className="w-2 h-2 rounded-full bg-green-500" />
                  <span className="text-sm font-medium">Aiden (Tier 1) — Policy Gate</span>
                  <span className="ml-auto text-xs text-green-600 font-medium">ACTIVE</span>
                </div>
                <div className="ml-6 border-l-2 border-dashed border-primary/30 pl-4 space-y-3">
                  <div className="flex items-center gap-3 p-2.5 rounded-lg bg-white/60 dark:bg-slate-800/60 border text-sm">
                    <Bot className="w-4 h-4 text-blue-500" />
                    <span>General Executor</span>
                    <span className="ml-auto text-xs text-muted-foreground">groq/llama-3.3</span>
                  </div>
                  <div className="flex items-center gap-3 p-2.5 rounded-lg bg-white/60 dark:bg-slate-800/60 border text-sm">
                    <Bot className="w-4 h-4 text-purple-500" />
                    <span>Incident Handler</span>
                    <span className="ml-auto text-xs text-muted-foreground">groq/llama-3.3</span>
                  </div>
                  <div className="flex items-center gap-3 p-2.5 rounded-lg bg-white/60 dark:bg-slate-800/60 border text-sm">
                    <Bot className="w-4 h-4 text-orange-500" />
                    <span>Deploy Executor</span>
                    <span className="ml-auto text-xs text-muted-foreground">groq/llama-3.3</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="py-16 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="grid md:grid-cols-3 gap-6">
            <Card className="bg-white/50 dark:bg-slate-800/50 border-slate-200/80 dark:border-slate-700/50 hover:bg-white dark:hover:bg-slate-800 transition-colors">
              <CardContent className="pt-6 space-y-3">
                <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/50 flex items-center justify-center">
                  <Zap className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                </div>
                <h3 className="font-semibold">LLM-Powered Routing</h3>
                <p className="text-sm text-muted-foreground">
                  Aiden evaluates every work order against policy rules using AI, then routes to the right sub-agent automatically.
                </p>
              </CardContent>
            </Card>
            <Card className="bg-white/50 dark:bg-slate-800/50 border-slate-200/80 dark:border-slate-700/50 hover:bg-white dark:hover:bg-slate-800 transition-colors">
              <CardContent className="pt-6 space-y-3">
                <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/50 flex items-center justify-center">
                  <GitBranch className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                </div>
                <h3 className="font-semibold">Multi-Step Workflows</h3>
                <p className="text-sm text-muted-foreground">
                  Build reusable workflow templates with step dependencies, conditions, retry policies, and operator assignments.
                </p>
              </CardContent>
            </Card>
            <Card className="bg-white/50 dark:bg-slate-800/50 border-slate-200/80 dark:border-slate-700/50 hover:bg-white dark:hover:bg-slate-800 transition-colors">
              <CardContent className="pt-6 space-y-3">
                <div className="w-10 h-10 rounded-lg bg-green-100 dark:bg-green-900/50 flex items-center justify-center">
                  <Shield className="w-5 h-5 text-green-600 dark:text-green-400" />
                </div>
                <h3 className="font-semibold">Human-in-the-Loop</h3>
                <p className="text-sm text-muted-foreground">
                  Blocked decisions surface for human review. Reopen, edit, and reprocess completed work with full audit trails.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      <footer className="py-8 px-6 border-t border-slate-200 dark:border-slate-800">
        <div className="max-w-6xl mx-auto text-center text-sm text-muted-foreground space-y-1">
          <p>AIDEN_IWO v0.5.7 — Intelligent Work Orchestration</p>
          <p className="text-xs">designed by LuaAzullaB | darrel vaughn</p>
          <a href="/attributions" className="inline-block mt-2 text-[11px] text-muted-foreground/60 hover:text-muted-foreground transition-colors" data-testid="link-attributions-landing">
            Attributions &amp; Licenses
          </a>
        </div>
      </footer>
    </div>
  );
}
