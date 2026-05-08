import { describe, it, expect } from "vitest";

import {
  scanForDirectLlmContentInjection,
  isPathAllowlistedForMemoryInjection,
} from "../../tools/eslint-plugin-iwo3/rules/no-direct-llm-content-injection";

describe("Loop Iota — no-direct-llm-content-injection rule", () => {
  it("flags a Tier-N call with memory_block= but no memory import", () => {
    const src = [
      "import asyncpg",
      "from runtime.tier_1_aiden import invoke_aiden_tier_1",
      "",
      "async def run(conn, message):",
      "    block = '<spoofed memory>'",
      "    return await invoke_aiden_tier_1(conn, intake_text=message, memory_block=block)",
    ].join("\n");
    const findings = scanForDirectLlmContentInjection(
      "apps/api-fastapi/runtime/some_other_helper.py",
      src
    );
    expect(findings).toHaveLength(1);
    expect(findings[0].rule).toBe("no-direct-llm-content-injection");
    expect(findings[0].snippet).toContain("memory_block=block");
  });

  it("allows the call when the file imports from memory", () => {
    const src = [
      "import asyncpg",
      "from memory import memory_context_builder",
      "from runtime.tier_1_aiden import invoke_aiden_tier_1",
      "",
      "async def run(conn, client_id, user_id, message):",
      "    bundle = await memory_context_builder(",
      "        conn, client_id=client_id, user_id=user_id, message=message",
      "    )",
      "    return await invoke_aiden_tier_1(",
      "        conn, intake_text=message, memory_block=bundle.block or None",
      "    )",
    ].join("\n");
    const findings = scanForDirectLlmContentInjection(
      "apps/api-fastapi/routes/some_other_route.py",
      src
    );
    expect(findings).toHaveLength(0);
  });

  it("allows files in the memory/ package itself", () => {
    expect(
      isPathAllowlistedForMemoryInjection(
        "apps/api-fastapi/memory/context_builder.py"
      )
    ).toBe(true);
    expect(
      isPathAllowlistedForMemoryInjection(
        "apps/api-fastapi/memory/types.py"
      )
    ).toBe(true);
  });

  it("allows test files (allowlisted prefix)", () => {
    expect(
      isPathAllowlistedForMemoryInjection(
        "apps/api-fastapi/tests/test_memory_route.py"
      )
    ).toBe(true);
    const src = [
      "from runtime.tier_1_aiden import invoke_aiden_tier_1",
      "",
      "async def test_memory_passthrough():",
      "    await invoke_aiden_tier_1(c, intake_text='x', memory_block='synthetic')",
    ].join("\n");
    const findings = scanForDirectLlmContentInjection(
      "apps/api-fastapi/tests/test_memory_route.py",
      src
    );
    expect(findings).toHaveLength(0);
  });

  it("allowlists routes/aiden.py specifically", () => {
    expect(
      isPathAllowlistedForMemoryInjection("apps/api-fastapi/routes/aiden.py")
    ).toBe(true);
  });

  it("ignores non-Python files entirely", () => {
    const src = "memory_block=arbitrary";
    const findings = scanForDirectLlmContentInjection(
      "apps/console-streamlit/views/chat.py.ts",
      src
    );
    expect(findings).toHaveLength(0);
  });

  it("does nothing when memory_block= is not in the file", () => {
    const src = [
      "from runtime.tier_1_aiden import invoke_aiden_tier_1",
      "",
      "async def run(conn, message):",
      "    return await invoke_aiden_tier_1(conn, intake_text=message)",
    ].join("\n");
    const findings = scanForDirectLlmContentInjection(
      "apps/api-fastapi/runtime/some_other_helper.py",
      src
    );
    expect(findings).toHaveLength(0);
  });
});
