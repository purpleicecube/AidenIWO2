"""BUG-066 regression — Aiden's appended output-schema contract must
explicitly SUPERSEDE any obsolete IWO2-era schema embedded in tenant
persona prompts. Without the SUPERSEDES directive, the LLM sees two
competing schemas (the IWO2 `phase`/`decision`/`mode` shape from the
ported persona prompt + the IWO3 `decision_kind`/`title` shape from
the appended contract) and sometimes produces the IWO2 shape, which
fails `_parse_aiden_decision` with `decision_malformed: title missing
or non-string`.

See `BUGFIX_LOG.md` BUG-066 for full context.
"""

from __future__ import annotations

from runtime import tier_1_aiden


def test_aiden_schema_template_supersedes_obsolete_iwo2_format() -> None:
    """The schema template must include an explicit clause stating
    that this schema overrides any earlier `OUTPUT FORMAT` /
    `DECISION SCHEMA` / JSON example in the persona prompt. This is
    BUG-066's prompt-engineering belt over Klear/FFAI personas that
    were IWO2-ported and embed an obsolete top-level shape."""
    src = tier_1_aiden._AIDEN_OUTPUT_SCHEMA_TEMPLATE
    # Must declare supersession explicitly enough that the LLM can't
    # silently pick the wrong schema.
    assert "SUPERSEDES" in src or "supersedes" in src, (
        "Aiden output-schema template no longer declares schema "
        "supersession. See IWO3_BUG_FIX_LOG_v0.1.0 BUG-066."
    )
    # Must name the obsolete IWO2 fields by token so the LLM can match
    # against its own persona prose if needed.
    assert "phase" in src, (
        "Aiden schema template no longer names the obsolete IWO2 "
        "`phase` field. BUG-066 regression."
    )
    # Must emphasize that title is always required.
    assert "ALWAYS present" in src or "must be present" in src.lower(), (
        "Aiden schema template no longer emphasises that `title` is "
        "always required. BUG-066 regression."
    )


def test_aiden_schema_template_lists_required_top_level_fields() -> None:
    """Sanity — the schema template still lists `decision_kind` and
    `title` as top-level fields the LLM must produce."""
    src = tier_1_aiden._AIDEN_OUTPUT_SCHEMA_TEMPLATE
    assert '"decision_kind"' in src
    assert '"title"' in src


def test_aiden_runtime_appends_schema_to_tenant_persona() -> None:
    """Lock — Aiden's invocation still uses the `cfg.system_prompt or
    AIDEN_SYSTEM_PROMPT` + `AIDEN_OUTPUT_SCHEMA` concatenation. If
    that pattern changes, the BUG-066 SUPERSEDES clause stops being
    delivered to the LLM at the end of the prompt."""
    import inspect
    src = inspect.getsource(tier_1_aiden)
    assert "AIDEN_OUTPUT_SCHEMA" in src
    # The call site composition pattern. The literal substring guards
    # against a future refactor that replaces the pattern with bare
    # `cfg.system_prompt`.
    assert "+ AIDEN_OUTPUT_SCHEMA" in src or "AIDEN_OUTPUT_SCHEMA +" in src, (
        "Aiden runtime no longer concatenates AIDEN_OUTPUT_SCHEMA "
        "to the resolved system prompt. BUG-066 regression."
    )
