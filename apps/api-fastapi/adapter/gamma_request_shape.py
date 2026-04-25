"""Loop 9 Phase 9.2 — Python mirror of ``packages/adapters/gamma/request_shape.ts``.

Pure payload builders + response parsers. The FastAPI side doesn't own
the Gamma HTTP plumbing (TS canonical holds that), but it does need to
verify the on-the-wire shape for fixture-driven parity and for future
tests that compose an OutputPackage → Gamma payload without booting
Node.

Byte-for-byte parity with the TS canonical is enforced by
``tests/contract/gamma-request-shape-parity.test.ts``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union


GammaRequestMode = Literal["generate", "from_template"]
GammaExportFormat = Literal["pptx", "pdf"]


@dataclass(frozen=True)
class GammaRequestShapeInput:
    output_kind: str
    title: str
    summary: Optional[str]
    content_blocks: dict
    template_external_ref: Optional[str]


@dataclass(frozen=True)
class GammaRequestShape:
    endpoint: str
    mode: GammaRequestMode
    export_as: GammaExportFormat
    body: dict


class GammaPackageInvalidError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"gamma package invalid: {'; '.join(errors)}")
        self.errors = errors


def _export_as_from_output_kind(output_kind: str) -> GammaExportFormat:
    if output_kind == "gamma_pptx":
        return "pptx"
    if output_kind == "gamma_pdf":
        return "pdf"
    raise GammaPackageInvalidError(
        [f"output_kind={json.dumps(output_kind)} is not a gamma_* kind"]
    )


def _extract_prompt_text(blocks: dict) -> Optional[str]:
    for key in ("prompt", "inputText", "body", "content"):
        v = blocks.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return None


def build_gamma_request_body(inp: GammaRequestShapeInput) -> GammaRequestShape:
    errors: list[str] = []

    export_as = _export_as_from_output_kind(inp.output_kind)

    if not inp.title or not inp.title.strip():
        errors.append("title must be non-empty")

    prompt_text = _extract_prompt_text(inp.content_blocks)
    if not prompt_text:
        errors.append(
            "content_blocks must carry prompt/inputText/body/content text"
        )

    if errors:
        raise GammaPackageInvalidError(errors)

    mode: GammaRequestMode = (
        "from_template"
        if inp.template_external_ref and len(inp.template_external_ref) > 0
        else "generate"
    )

    if mode == "from_template":
        return GammaRequestShape(
            endpoint="/generations/from-template",
            mode=mode,
            export_as=export_as,
            body={
                "gammaId": inp.template_external_ref,
                "prompt": prompt_text,
                "exportAs": export_as,
            },
        )

    return GammaRequestShape(
        endpoint="/generations",
        mode=mode,
        export_as=export_as,
        body={
            "inputText": prompt_text,
            "textMode": "generate",
            "format": "presentation" if export_as == "pptx" else "document",
            "exportAs": export_as,
        },
    )


# ──────────────────────────────────────────────────────────────────────
# Response parsers
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GammaSubmitParsed:
    generation_id: str
    gamma_url: Optional[str]


class GammaSubmitResponseInvalidError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(f"gamma submit response invalid: {detail}")


def parse_gamma_submit_response(raw: dict) -> GammaSubmitParsed:
    gid = raw.get("generationId")
    if not isinstance(gid, str) or len(gid) == 0:
        raise GammaSubmitResponseInvalidError(
            "generationId missing or not a string"
        )
    g_url = raw.get("gammaUrl")
    return GammaSubmitParsed(
        generation_id=gid,
        gamma_url=g_url if isinstance(g_url, str) else None,
    )


GammaPollStatus = Literal[
    "pending", "running", "completed", "failed"
]


@dataclass(frozen=True)
class GammaPollParsed:
    generation_id: str
    status: GammaPollStatus
    progress: Optional[int]
    export_urls: list[str]
    gamma_url: Optional[str]
    error_message: Optional[str]


def _as_string(v: Any) -> Optional[str]:
    return v if isinstance(v, str) else None


def extract_gamma_export_urls(raw: dict) -> list[str]:
    out: list[str] = []
    for key in ("exportUrl", "pptxUrl", "pdfUrl", "fileUrl", "downloadUrl"):
        v = raw.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    exports_obj = raw.get("exports")
    if isinstance(exports_obj, dict):
        for v in exports_obj.values():
            if isinstance(v, str) and v.startswith("http"):
                out.append(v)
    urls_arr = raw.get("exportUrls")
    if isinstance(urls_arr, list):
        for v in urls_arr:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and isinstance(v.get("url"), str):
                out.append(v["url"])
    files = raw.get("files")
    if isinstance(files, list):
        for v in files:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and isinstance(v.get("url"), str):
                out.append(v["url"])
    return out


def parse_gamma_poll_response(
    generation_id: str, raw: dict
) -> GammaPollParsed:
    raw_status = _as_string(raw.get("status")) or "pending"
    if raw_status == "completed":
        normalised: GammaPollStatus = "completed"
    elif raw_status in ("failed", "error"):
        normalised = "failed"
    elif raw_status in ("running", "processing"):
        normalised = "running"
    else:
        normalised = "pending"

    export_urls = (
        extract_gamma_export_urls(raw) if normalised == "completed" else []
    )

    error_message = None
    if normalised == "failed":
        err_obj = raw.get("error")
        if isinstance(err_obj, dict):
            error_message = _as_string(err_obj.get("message"))
        if not error_message:
            error_message = _as_string(raw.get("message")) or "unknown gamma error"

    progress = raw.get("progress") if isinstance(raw.get("progress"), int) else None

    return GammaPollParsed(
        generation_id=generation_id,
        status=normalised,
        progress=progress,
        export_urls=export_urls,
        gamma_url=_as_string(raw.get("gammaUrl")),
        error_message=error_message,
    )


# ──────────────────────────────────────────────────────────────────────
# JSON (de)serialisation for the parity CLI — must stay symmetric with
# the TS ``request_shape`` types.
# ──────────────────────────────────────────────────────────────────────


def shape_input_from_json(raw: dict) -> GammaRequestShapeInput:
    return GammaRequestShapeInput(
        output_kind=str(raw["outputKind"]),
        title=str(raw["title"]),
        summary=_as_string(raw.get("summary")),
        content_blocks=raw.get("contentBlocks") or {},
        template_external_ref=_as_string(raw.get("templateExternalRef")),
    )


def shape_to_json(shape: GammaRequestShape) -> dict:
    return {
        "endpoint": shape.endpoint,
        "mode": shape.mode,
        "exportAs": shape.export_as,
        "body": shape.body,
    }


def submit_response_from_json(raw: dict) -> Union[dict, None]:
    parsed = parse_gamma_submit_response(raw)
    return {
        "generationId": parsed.generation_id,
        "gammaUrl": parsed.gamma_url,
    }


def poll_response_from_json(generation_id: str, raw: dict) -> dict:
    parsed = parse_gamma_poll_response(generation_id, raw)
    return {
        "generationId": parsed.generation_id,
        "status": parsed.status,
        "progress": parsed.progress,
        "exportUrls": parsed.export_urls,
        "gammaUrl": parsed.gamma_url,
        "errorMessage": parsed.error_message,
    }
