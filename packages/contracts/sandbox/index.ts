/**
 * Sandbox contract surface sub-barrel.
 *
 * β.0 ships state-machine constants only (no transition validator,
 * no dispatcher — those land in β.1+ per the Sandbox-Hosted-In-App
 * brief).
 */

export {
  SANDBOX_ACCEPTANCE_STATES,
  SANDBOX_TERMINAL_STATES,
  SANDBOX_SESSION_TRANSITIONS,
  SANDBOX_DISPATCH_GATE_ERROR_CODE,
  SANDBOX_BETA_0_PERMISSION_KEYS,
  type SandboxAcceptanceState,
  type SandboxTerminalState,
  type SandboxTransitionSpec,
} from "./state_machines";
