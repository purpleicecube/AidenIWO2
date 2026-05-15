"""Loop Eta post-close — natural-language Gamma template resolver.

Aiden's chat-classifier produces a `work_order_brief` from operator intake
text, but until now did not capture which `template_profile_id` to render
the artifact against. As a result, requests like:

  "I need a 4 slide Intro deck for Klear.ai - using GAMMA Klear.ai
   Template for PPT"

created a WO with `requested_outputs IS NULL`, which made
`dispatch_gamma_for_package` fall back to Gamma defaults instead of the
operator's intended Klear-branded template.

This module bridges that gap deterministically (no token cost): given the
operator's intake text + the tenant's active `template_profiles` rows,
resolve the most plausible template via keyword + alias matching.

The resolver is intentionally conservative:
  - returns the strongest match if score crosses a confidence threshold
  - returns a `needs_clarification` signal with the candidate list when
    the intake clearly wants a templated artifact (deck / pptx / pdf /
    template) but no single template scores high enough
  - returns `None` for non-templated intent (a content brief, a deploy
    request, etc) so the rest of the pipeline is unaffected

Scope guard: the resolver never rewrites Aiden's `assigned_role` or
`priority`. It only adds template context to the existing brief.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

import asyncpg


# ---------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateChoice:
    """One template surfaced to the operator (chat clarification, brief
    metadata, or audit). Mirrors the wire-shape of `/template_profiles`
    plus a derived display label."""

    template_profile_id: str
    profile_key: str
    output_kind: str
    engine: str
    label: str
    external_ref: Optional[str]


@dataclass(frozen=True)
class TemplateResolution:
    """Result of resolving the operator's intake against tenant templates.

    Exactly one of the three cases applies:

      matched        — `match` is the winning TemplateChoice; the WO can
                       carry its template_profile_id immediately.
      needs_choice   — operator clearly wants a templated artifact but no
                       single template scored high enough; surface
                       `choices` to the operator for explicit pick.
      no_template    — intake doesn't look templated; let the pipeline
                       run with the existing Gamma default.
    """

    kind: str  # "matched" | "needs_choice" | "no_template"
    match: Optional[TemplateChoice] = None
    choices: tuple[TemplateChoice, ...] = ()
    detected_output_kind: Optional[str] = None
    score: int = 0
    matched_terms: tuple[str, ...] = ()


# ---------------------------------------------------------------------
# Regex / phrase tables
# ---------------------------------------------------------------------


# A request "looks templated" if it mentions one of these. Used to
# decide whether a missing match should escalate to needs_choice or
# silently degrade to no_template.
_TEMPLATED_INTENT_RE = re.compile(
    r"\b("
    r"template|"
    r"deck|"
    r"slide|slides|"
    r"presentation|"
    r"pptx|ppt|"
    r"pdf|"
    r"gamma|"
    r"intro\s+deck|"
    r"pitch\s+deck|"
    r"branded|brand[- ]aware"
    r")\b",
    re.IGNORECASE,
)


# Heuristic: detect requested output kind so we can prefer templates
# of the right kind when both sides are available.
#
# Loop CAP-E Φ.8 — extended to cover the full broadened
# template_profiles.output_kind enum (Loop CAP-A Φ.0a / migration 0029):
# pptx | pdf | html | docx | md | other. CAP-B handback flagged that
# CAP-B's resolver only supported pptx/pdf detection; CAP-C seeded
# branded chains for html/docx/md and CAP-E activates them, so the
# detector now needs to cover those surfaces. `other` stays None
# because there's no positive token signal for "other" intake.
_OUTPUT_KIND_TOKENS = {
    "pptx": ("pptx", "ppt", "powerpoint", "deck", "slide", "slides", "presentation", "pitch deck", "intro deck"),
    "pdf":  ("pdf", "rmis", "claims report"),
    "html": ("html", "landing page", "landing-page", "web page", "webpage", "site page", "microsite", "mini-site"),
    "docx": ("docx", "word doc", "word document", "ms word", "microsoft word"),
    "md":   ("markdown", "md file", ".md", "readme", "sop md"),
}


# Curated phrase aliases keyed by a canonical token. The resolver
# rewards a profile when any of its aliases appear in the intake text.
# Each value is a (alias_phrase, weight) tuple. Higher weights for
# more-specific phrases.
_PROFILE_KEY_ALIASES: dict[str, tuple[tuple[str, int], ...]] = {
    "klear_pptx_primary": (
        ("klear template", 6),
        ("klear pptx", 7),
        ("klearai-pptx", 7),
        ("klear ai pptx", 7),
        ("klear deck", 6),
        ("klear-branded deck", 6),
        ("klear pitch deck", 6),
        ("klear intro deck", 6),
        ("klear primary", 6),
        ("primary pptx", 4),
        ("klear.ai template", 6),
        ("gamma klear", 5),
        ("klear gamma", 5),
        ("klear", 2),
        ("brand template", 3),
        ("branded deck", 3),
    ),
    "klear_pdf_rmis": (
        ("rmis", 7),
        ("rmis pdf", 8),
        ("rmis report", 8),
        ("roi", 5),
        ("risk pdf", 6),
        ("klear rmis", 8),
        ("klear roi", 6),
        ("klear risk", 5),
    ),
    "klear_pdf_claims": (
        ("claims", 5),
        ("claims pdf", 8),
        ("claims report", 8),
        ("klear claims", 8),
        ("claims overview", 7),
    ),
    "ffai_pptx_gamma_basic": (
        ("ffai pptx", 7),
        ("ffai deck", 6),
        ("freedomforge pptx", 7),
        ("freedomforge deck", 7),
        ("ffai template", 5),
        ("ffai", 2),
    ),
    "ffai_pdf_gamma_basic": (
        ("ffai pdf", 7),
        ("freedomforge pdf", 7),
        ("ffai pdf template", 8),
    ),
}


# Minimum total score for a template to win autonomously. Below this
# we either escalate to needs_choice (templated intent present) or
# silently fall through (no template intent at all).
_AUTO_PICK_THRESHOLD = 5


# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------


def _norm(text: str) -> str:
    return text.lower().replace(" ", " ")


def _label_from_contract(content_contract: Any, profile_key: str) -> str:
    """Return the human-readable label from `content_contract.label`.

    asyncpg returns jsonb columns as JSON-encoded strings by default
    (no codec set in this project), so we accept both pre-parsed dicts
    and raw string payloads. Falls back to `profile_key` if the
    content_contract is missing, malformed, or has no label field.
    """
    parsed: Any = content_contract
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, TypeError):
            return profile_key
    if isinstance(parsed, dict):
        label = parsed.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return profile_key


def _detect_output_kind(intake_norm: str) -> Optional[str]:
    """Return one of 'pptx' | 'pdf' | 'html' | 'docx' | 'md' when
    intake clearly signals it. Returns None on ambiguous intake (>1
    kind matched) OR no kind detected — caller (resolver / branded-
    intent detector) treats None as "no kind preference / keep all
    templates in scope".

    Loop CAP-E Φ.8 — extended from {pptx, pdf} to cover the full
    broadened enum so html / docx / md branded chains can route
    correctly. Selection rule: pick the kind with positive hits when
    no other kind also has hits; ties → None (ambiguous)."""
    hits: dict[str, int] = {}
    for kind, tokens in _OUTPUT_KIND_TOKENS.items():
        n = sum(1 for tok in tokens if tok in intake_norm)
        if n > 0:
            hits[kind] = n
    if len(hits) == 1:
        return next(iter(hits))
    if len(hits) > 1:
        # >1 kind matched. Pick the one with strictly more hits;
        # tie → None (genuinely ambiguous).
        ordered = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
        if ordered[0][1] > ordered[1][1]:
            return ordered[0][0]
        return None
    return None


def _score_profile(
    profile_key: str,
    intake_norm: str,
    label_norm: str,
) -> tuple[int, list[str]]:
    """Return (score, matched_phrases) for one profile against intake."""
    score = 0
    matched: list[str] = []

    aliases = _PROFILE_KEY_ALIASES.get(profile_key, ())
    for phrase, weight in aliases:
        if phrase in intake_norm:
            score += weight
            matched.append(phrase)

    # Profile-key direct hit ("klear_pptx_primary" mentioned verbatim)
    if profile_key in intake_norm:
        score += 8
        matched.append(profile_key)

    # Label tokens — bonus when 2+ words from the label appear in intake.
    label_words = [w for w in re.findall(r"[a-z0-9]+", label_norm) if len(w) >= 3]
    label_hits = sum(1 for w in label_words if w in intake_norm)
    if label_hits >= 2:
        score += 2
        matched.append(f"label:{label_hits}-words")

    return score, matched


def _row_to_choice(row: dict[str, Any]) -> TemplateChoice:
    return TemplateChoice(
        template_profile_id=row["id"],
        profile_key=row["profile_key"],
        output_kind=row["output_kind"],
        engine=row["engine"],
        label=_label_from_contract(row.get("content_contract"), row["profile_key"]),
        external_ref=row.get("external_ref"),
    )


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


async def load_active_templates(
    conn: asyncpg.Connection,
    *,
    client_id: str,
) -> tuple[TemplateChoice, ...]:
    """Fetch the tenant's active templates as TemplateChoice records.
    Tenant-scoped via RLS on the caller's connection."""
    rows = await conn.fetch(
        """
        SELECT id::text              AS id,
               profile_key           AS profile_key,
               output_kind::text     AS output_kind,
               engine::text          AS engine,
               external_ref          AS external_ref,
               content_contract      AS content_contract
          FROM template_profiles
         WHERE client_id = $1::uuid
           AND status = 'active'
         ORDER BY output_kind::text, profile_key
        """,
        client_id,
    )
    return tuple(_row_to_choice(dict(r)) for r in rows)


def resolve_template_for_intake(
    intake_text: str,
    templates: tuple[TemplateChoice, ...],
    *,
    auto_pick_threshold: int = _AUTO_PICK_THRESHOLD,
) -> TemplateResolution:
    """Pure function: score the operator's intake against the tenant's
    active templates and return a resolution.

    Caller fetches `templates` once (per chat turn) via
    `load_active_templates` and passes them in. Splitting fetch from
    score keeps this unit-testable without a DB.
    """
    if not templates:
        return TemplateResolution(kind="no_template")

    intake_norm = _norm(intake_text)
    detected_kind = _detect_output_kind(intake_norm)

    # Score each template; track the leader.
    best_score = 0
    best_choice: Optional[TemplateChoice] = None
    best_terms: list[str] = []
    scored: list[tuple[int, TemplateChoice, list[str]]] = []
    for tpl in templates:
        score, matched = _score_profile(tpl.profile_key, intake_norm, _norm(tpl.label))
        # Bonus when output_kind detection matches the template's kind.
        if detected_kind and tpl.output_kind == detected_kind:
            score += 2
        # Penalty when output_kind detection clashes with the template's kind.
        elif detected_kind and tpl.output_kind != detected_kind:
            score -= 3
        scored.append((score, tpl, matched))
        if score > best_score:
            best_score = score
            best_choice = tpl
            best_terms = matched

    templated_intent = bool(_TEMPLATED_INTENT_RE.search(intake_text))

    if best_choice is not None and best_score >= auto_pick_threshold:
        return TemplateResolution(
            kind="matched",
            match=best_choice,
            detected_output_kind=detected_kind,
            score=best_score,
            matched_terms=tuple(best_terms),
        )

    if templated_intent:
        # Surface a focused choice list. Prefer same-kind templates when
        # detection produced one; otherwise show all active templates.
        if detected_kind:
            choices = tuple(
                tpl for tpl in templates if tpl.output_kind == detected_kind
            )
            if not choices:
                choices = templates
        else:
            choices = templates
        return TemplateResolution(
            kind="needs_choice",
            choices=choices,
            detected_output_kind=detected_kind,
            score=best_score,
        )

    return TemplateResolution(
        kind="no_template",
        detected_output_kind=detected_kind,
        score=best_score,
    )


async def resolve_template_for_client(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    intake_text: str,
) -> TemplateResolution:
    """Convenience wrapper: load tenant templates + run the resolver.

    Used by the Aiden chat surface in routes/aiden.py post-classification.
    """
    templates = await load_active_templates(conn, client_id=client_id)
    return resolve_template_for_intake(intake_text, templates)
