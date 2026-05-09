"""Loop Kappa — Memory V1.5 chat-side intent parser.

Ports IWO2's `parseContextRequestFromChat()` from `server/knowhow.ts`
into deterministic Python regex extraction. Produces structured
`ContextIntent` signals (paths, filename_terms, wants_folder_listing,
wants_canonical_facts) that the assembler consumes alongside the
existing tsquery path.

Code-block intent is **intentionally not ported** per parity matrix
row 5. GCC advisory boost is intentionally not ported per matrix row
11. Recency filter is deferred per matrix row 12.

The parser is pure: no DB, no I/O, no LLM. Same architectural posture
as `_intent_matches_scratch` in assembler.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Common filler / programming words that an underscore-pattern would
# falsely flag as workspace folder names. Keep narrow — being too
# aggressive here drops real folder references.
_BARE_UNDERSCORE_DENYLIST = {
    "Work_Order",
    "Sub_Agent",
    "Know_How",
    "Tier_1",
    "Tier_2",
    "Tier_1_5",
}


# Phase 1: "Label text: <path>"  (label-colon path extraction)
# Catches "Web Style Guide: Design References/Purplegoo_1016-DESIGN.md"
# and  "Content Guide: Workspace/04_Resources/Demo_Content/Foo"
_LABEL_COLON_RE = re.compile(
    r"^[ \t]*[\w][\w\s.'-]*?:\s*([^\s:][^\n]*\/[^\n]+)$",
    re.MULTILINE,
)


# Phase 2: "Workspace > 04_Resources > Demo_Content > File"  (legacy
# breadcrumb rewrite — turns the breadcrumb into "from <path>" so
# Phase 3 picks it up).
_BREADCRUMB_RE = re.compile(
    r"(?:Workspace\s*>\s*)?(\d{2}_[A-Za-z_]+(?:\s*>\s*[A-Za-z0-9_.-]+)+)",
    re.IGNORECASE,
)


# Phase 3: preposition + path. Optional articles between preposition
# and the candidate path. "from /04_Resources", "in the Outputs/",
# "folder 02_Execution".
_PREP_PATH_RE = re.compile(
    r"(?:from|in|of|find\s+in|inside|within|folder|path|directory|"
    r"content\s+from|references?\s+(?:in|at|from)?)\s+"
    r"(?:the\s+|a\s+|an\s+)?[/\"]?"
    r"([A-Za-z0-9_#][\w-]*(?:\/[^\s\"]*)?)",
    re.IGNORECASE,
)


# Phase 3b: bare workspace folder reference like "04_Resources"
# without a leading preposition. The ##_Name shape is unambiguous.
_BARE_NUMBERED_FOLDER_RE = re.compile(
    r"\b(\d{2}_[A-Za-z][A-Za-z0-9_-]*(?:\/[^\s\"]*)?)\b"
)


# Phase 3c: bare underscore-joined names like "Demo_Content".
# Requires CapitalCase + at least one underscore so generic identifiers
# don't match.
_BARE_UNDERSCORE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?:\/[^\s\"]*)?)\b"
)


# Phase 4 (Kappa-new): folder-listing intent.  "what's in",
# "list files in", "contents of", "show me the", "what folders are in",
# "directory of".
_FOLDER_LISTING_INTENT_RE = re.compile(
    r"\b(?:"
    r"what(?:'?s|\s+is|\s+files?\s+are|\s+folders?\s+are)\s+in|"
    r"list\s+(?:the\s+)?(?:files?|folders?|contents)\s+(?:in|of|under)|"
    r"contents?\s+of|"
    r"show\s+(?:me\s+)?(?:the\s+)?(?:files?|folders?|contents)\s+(?:in|of|under)|"
    r"directory\s+(?:of|listing)|"
    r"what(?:'?s|\s+is)\s+(?:in|under)\s+(?:the\s+)?folder"
    r")\b",
    re.IGNORECASE,
)


# Phase 5 (Kappa-new): canonical-facts intent.  Operators asking for
# the authoritative facts surface specifically.
_CANONICAL_FACTS_INTENT_RE = re.compile(
    r"\b(?:canonical\s+facts?|authoritative\s+facts?|"
    r"corrections?\s+(?:list|file)|fact\s+sheet|"
    r"what\s+(?:do\s+)?we\s+know\s+about)\b",
    re.IGNORECASE,
)


# Phase 6 (Kappa-new): filename terms.  Quoted names ("RMIS_pricing_deck.pptx")
# OR bare extension-bearing tokens (.pptx/.pdf/.md/.html/.json/.csv/.docx/.xlsx).
_QUOTED_FILENAME_RE = re.compile(r"['\"]([\w\-. ]+\.\w{2,5})['\"]")
_BARE_FILENAME_RE = re.compile(
    r"\b([\w\-]+\.(?:pptx|pdf|md|html|json|csv|docx|xlsx|txt|sql))\b",
    re.IGNORECASE,
)


# Stopwords for keyword leftover (matches `_build_tsquery_from_intake`
# semantics so we do not double-tokenize).
_KEYWORD_STOPWORDS = {
    "the", "and", "but", "for", "with", "this", "that", "from", "into",
    "what", "when", "where", "why", "how", "are", "you", "your", "our",
    "have", "has", "can", "could", "should", "would", "will", "any",
    "tell", "give", "show", "find", "make", "build", "want", "need",
    "tier", "deck", "pdf", "html",
}


@dataclass(frozen=True)
class ContextIntent:
    """Structured signals extracted from operator intake.

    Consumed by the assembler alongside the tsquery path. Empty
    fields are normal — most short turns yield no path/filename hits
    and the assembler falls back to tsquery + canonical_facts only.
    """

    paths: tuple[str, ...] = field(default_factory=tuple)
    filename_terms: tuple[str, ...] = field(default_factory=tuple)
    wants_folder_listing: bool = False
    wants_canonical_facts: bool = False
    # Tokens left after path/filename/intent extraction. Caller may
    # join these for the residual tsquery so retrieval does not
    # re-fire on tokens already represented as paths or filenames.
    keywords_remaining: tuple[str, ...] = field(default_factory=tuple)


def _normalize_path(raw: str) -> str:
    """Strip "Workspace/" prefix, leading slashes, trailing punctuation,
    trailing prose suffix. Mirrors IWO2 `normalizePath()`.
    """
    s = raw
    s = re.sub(r"^Workspace\/", "", s, flags=re.IGNORECASE)
    s = s.lstrip("/")
    s = re.sub(r"[,;)\]]+$", "", s)
    s = re.sub(r"\s+(?:folder|directory|path)$", "", s, flags=re.IGNORECASE)
    return s.strip()


def _looks_like_path(candidate: str) -> bool:
    """Final sanity gate before adding to paths[].

    Accept iff the candidate has a path-shape (a `/` between word
    chars) OR starts with `##_` (numbered workspace folder) OR
    contains an underscore (workspace folder convention).
    Reject http(s) URLs and pure version strings (`v1.2.3`).
    """
    if not candidate:
        return False
    if candidate.lower().startswith(("http://", "https://")):
        return False
    if re.fullmatch(r"v?\d+(?:\.\d+)+(?:-[\w.]+)?", candidate):
        return False
    if re.search(r"\w\/\w", candidate):
        return True
    if re.match(r"^\d{2}_", candidate):
        return True
    if "_" in candidate:
        return True
    return False


def _extract_paths(message: str) -> list[str]:
    """Run all four path-extraction phases and de-duplicate.

    Strategy: build a `normalized` view of the message where
    breadcrumb syntax is rewritten to slashed paths in place. Run
    every phase against `normalized` (not the original) so the bare-
    folder regex picks up rewritten breadcrumbs. Avoids the IWO2
    "double from" bug where prepending 'from' before an already-
    preposition-led breadcrumb confused the preposition regex.
    """
    paths: list[str] = []

    # Phase 1: label-colon paths (run against original — labels are
    # preserved verbatim).
    for match in _LABEL_COLON_RE.finditer(message):
        raw_capture = match.group(1)
        # Reject URLs at the raw-capture stage: protocol-led
        # captures like "//example.com/..." normalize away the
        # leading slashes and pass downstream checks otherwise.
        if re.search(r"^//|^https?:|^ftp:|^[a-zA-Z]+://", raw_capture):
            continue
        candidate = _normalize_path(raw_capture)
        if re.search(r"\w\/\w", candidate) and not candidate.lower().startswith(
            ("http://", "https://", "ftp://")
        ):
            if candidate not in paths:
                paths.append(candidate)

    # Phase 2: rewrite breadcrumb syntax to slashed-path form. No
    # "from " prefix — let the bare-folder phases pick it up.
    normalized = message
    for bc_match in _BREADCRUMB_RE.finditer(message):
        breadcrumb = bc_match.group(0)
        rewritten = re.sub(
            r"^Workspace\s*>\s*",
            "",
            breadcrumb,
            flags=re.IGNORECASE,
        )
        rewritten = re.sub(r"\s*>\s*", "/", rewritten)
        normalized = normalized.replace(breadcrumb, rewritten)

    # Phase 3: preposition + path on the normalized string.
    for match in _PREP_PATH_RE.finditer(normalized):
        candidate = _normalize_path(match.group(1))
        if _looks_like_path(candidate) and candidate not in paths:
            paths.append(candidate)

    # Phase 3b: bare numbered workspace folders on the normalized
    # string — picks up the rewritten breadcrumbs as full slashed
    # paths.
    for match in _BARE_NUMBERED_FOLDER_RE.finditer(normalized):
        candidate = _normalize_path(match.group(1))
        if candidate not in paths:
            paths.append(candidate)

    # Phase 3c: bare underscore-joined CapitalCase names.
    for match in _BARE_UNDERSCORE_RE.finditer(normalized):
        candidate = _normalize_path(match.group(1))
        if candidate in _BARE_UNDERSCORE_DENYLIST:
            continue
        # Skip if already covered by an earlier phase as a path
        # PREFIX (e.g. "Demo_Content" is part of
        # "04_Resources/Demo_Content/Foo")
        if any(
            candidate == p or p.endswith("/" + candidate) or p.startswith(candidate + "/")
            for p in paths
        ):
            continue
        paths.append(candidate)

    return paths


def _extract_filename_terms(message: str) -> list[str]:
    """Quoted filenames + bare extension-bearing tokens. Limit to
    the first 5 unique terms so the assembler doesn't fan out the
    filename CTE on a sea of tokens.
    """
    terms: list[str] = []
    for match in _QUOTED_FILENAME_RE.finditer(message):
        candidate = match.group(1).strip()
        if candidate and candidate not in terms:
            terms.append(candidate)
    for match in _BARE_FILENAME_RE.finditer(message):
        candidate = match.group(1).strip()
        if candidate and candidate not in terms:
            terms.append(candidate)
    return terms[:5]


def _residual_keywords(message: str, paths: list[str], filenames: list[str]) -> list[str]:
    """Tokens left after stripping path components + filenames + stopwords.
    Used by callers that want a focused tsquery in addition to the
    structured signals. Cap at 8 terms; deduplicate.
    """
    head = message[:200].lower()
    tokens = re.findall(r"[a-z][a-z0-9]{2,}", head)

    # Build a set of substrings to suppress: path segments + filename
    # bases (without extensions). Split on `/`, whitespace, AND `_` so
    # individual word tokens drawn from a snake_case path component
    # don't double-fire as keywords (e.g. "demo_content" → both
    # "demo" and "content" suppressed).
    suppress: set[str] = set()
    for p in paths:
        for seg in re.split(r"[\/\s_]+", p.lower()):
            if seg:
                suppress.add(seg)
    for fn in filenames:
        base = re.sub(r"\.[^.]+$", "", fn).lower()
        if base:
            for seg in re.split(r"[\s_\-.]+", base):
                if seg:
                    suppress.add(seg)

    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        if tok in _KEYWORD_STOPWORDS:
            continue
        if tok in suppress:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= 8:
            break
    return out


def parse_context_intent(message: str) -> ContextIntent:
    """Parse operator intake into structured retrieval signals.

    Empty/short messages return an empty ContextIntent. The assembler
    treats an all-empty intent as "tsquery-only path" — same as
    pre-Kappa behavior.
    """
    if not message or len(message.strip()) < 3:
        return ContextIntent()

    paths = _extract_paths(message)
    filenames = _extract_filename_terms(message)
    wants_folder = bool(_FOLDER_LISTING_INTENT_RE.search(message))
    wants_canonical = bool(_CANONICAL_FACTS_INTENT_RE.search(message))
    residual = _residual_keywords(message, paths, filenames)

    return ContextIntent(
        paths=tuple(paths),
        filename_terms=tuple(filenames),
        wants_folder_listing=wants_folder,
        wants_canonical_facts=wants_canonical,
        keywords_remaining=tuple(residual),
    )
