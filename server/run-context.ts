/**
 * RunContext — Phase 2 context-passing foundation + Phase 3 execution profiles
 *
 * Resolved once per WO/workflow run, passed downstream, never mutated after creation.
 * Eliminates duplicate DB reads within a single processing run.
 */

import type { LlmSettings, SubAgent } from "@shared/schema";
import type { AvailableTool } from "./tool-executor";
import { storage } from "./storage";

// ==================== Execution Profiles (Phase 3) ====================

export type ProfileName = "safe" | "balanced" | "fast";

export interface ExecutionProfile {
  name: ProfileName;
  promptCompaction: boolean;
  batchedSynthesis: boolean;
  workflowParallelism: boolean;
  reviewReduction: boolean;
}

const PROFILES: Record<ProfileName, ExecutionProfile> = {
  safe: {
    name: "safe",
    promptCompaction: false,
    batchedSynthesis: false,
    workflowParallelism: false,
    reviewReduction: false,
  },
  balanced: {
    name: "balanced",
    promptCompaction: true,
    batchedSynthesis: true,
    workflowParallelism: false,
    reviewReduction: false,
  },
  fast: {
    name: "fast",
    promptCompaction: true,
    batchedSynthesis: true,
    workflowParallelism: true,
    reviewReduction: true,
  },
};

/**
 * Resolve the active execution profile.
 * HARD RULE: if executionProfile is null, undefined, or missing → returns "safe".
 * Never "balanced", never "fast", never last-used. All environments.
 */
export function resolveProfile(rawValue: string | null | undefined): ExecutionProfile {
  if (!rawValue || !(rawValue in PROFILES)) {
    return PROFILES.safe;
  }
  return PROFILES[rawValue as ProfileName];
}

/** Check if a specific feature flag is enabled in the current profile */
export function isFeatureEnabled(profile: ExecutionProfile, flag: keyof Omit<ExecutionProfile, "name">): boolean {
  return profile[flag] === true;
}

/** Get all profile definitions (for API/UI) */
export function getAllProfiles(): Record<ProfileName, ExecutionProfile> {
  return { ...PROFILES };
}

// ==================== GroupContext (Phase 6) ====================

/** Context for a parallel execution group — extends RunContext with frozen upstream outputs */
export interface GroupContext {
  /** Parent RunContext */
  runCtx: RunContext;
  /** Parallel group number */
  group: number;
  /** Frozen upstream outputs from completed dependencies (shared across branches) */
  frozenUpstreamOutputs: Record<string, any>;
  /** Collected results from parallel branches */
  branchResults: Map<string, any>;
}

// ==================== RunContext ====================

export interface RunContext {
  /** LLM settings (global) — null if LLM disabled */
  settings: LlmSettings | null;
  /** Whether LLM is enabled */
  useLLM: boolean;
  /** All active sub-agents at run start */
  activeSubAgents: SubAgent[];
  /** Operational settings (execution mode, memory advisor, etc.) */
  operationalSettings: any | null;
  /** Gamma template registry entries — cached for format resolution */
  gammaTemplates: any[];
  /** Resolved execution profile for this run */
  profile: ExecutionProfile;
  /** Timestamp when this context was resolved */
  resolvedAt: number;
}

/**
 * Resolve a RunContext from the database. Call once at the top of
 * processWorkOrder() or startWorkflowExecution(), then pass downstream.
 */
export async function resolveRunContext(): Promise<RunContext> {
  const [settings, activeSubAgents, operationalSettings, gammaTemplates] = await Promise.all([
    storage.getLlmSettings().catch(() => null),
    storage.getActiveSubAgents().catch(() => []),
    storage.getOperationalSettings().catch(() => null),
    storage.getGammaTemplates().catch(() => []),
  ]);

  const profile = resolveProfile(operationalSettings?.executionProfile);

  return {
    settings: settings || null,
    useLLM: settings?.enabled === true,
    activeSubAgents,
    operationalSettings,
    gammaTemplates,
    profile,
    resolvedAt: Date.now(),
  };
}
