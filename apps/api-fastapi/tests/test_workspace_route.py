"""Pre-Beta Loop δ.2 — /workspace/* CRUD smoke tests.

Covers tree fetch + folder create/rename/move/delete + file
create/rename/move/delete + cycle detection + RBAC + 401/403/404/409
boundary cases.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


def _new_name(prefix: str = "test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _root_id(client) -> str:
    tree = client.get("/workspace/tree", headers=_hdr(KLEAR_OWNER)).json()
    root = next(f for f in tree["folders"] if f["is_root"])
    return root["id"]


def _outputs_id(client) -> str:
    tree = client.get("/workspace/tree", headers=_hdr(KLEAR_OWNER)).json()
    out = next(f for f in tree["folders"] if f["name"] == "Outputs")
    return out["id"]


# ── auth + tree ───────────────────────────────────────────────────────


def test_tree_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.get("/workspace/tree")
    assert r.status_code == 401


@iwo3_db
def test_tree_visible_to_viewer() -> None:
    with TestClient(app) as client:
        r = client.get("/workspace/tree", headers=_hdr(KLEAR_VIEWER))
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(f["is_root"] for f in body["folders"])
    assert any(f["name"] == "Outputs" for f in body["folders"])


@iwo3_db
def test_tree_carries_seeded_outputs_folder() -> None:
    with TestClient(app) as client:
        r = client.get("/workspace/tree", headers=_hdr(KLEAR_OPERATOR))
    body = r.json()
    outputs = next((f for f in body["folders"] if f["name"] == "Outputs"), None)
    assert outputs is not None
    assert outputs["is_root"] is False


# ── folder CRUD ───────────────────────────────────────────────────────


@iwo3_db
def test_create_folder_403_for_viewer() -> None:
    with TestClient(app) as client:
        root = _root_id(client)
        r = client.post(
            "/workspace/folders",
            json={"parent_folder_id": root, "name": _new_name()},
            headers=_hdr(KLEAR_VIEWER),
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_create_folder_400_for_unknown_parent() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/workspace/folders",
            json={
                "parent_folder_id": str(uuid.uuid4()),
                "name": _new_name(),
            },
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 404, r.text


@iwo3_db
def test_create_then_rename_then_move_then_delete_folder() -> None:
    with TestClient(app) as client:
        root = _root_id(client)
        outputs = _outputs_id(client)

        # Create child of root
        r = client.post(
            "/workspace/folders",
            json={"parent_folder_id": root, "name": _new_name("Drafts")},
            headers=_hdr(KLEAR_OWNER),
        )
        assert r.status_code == 201, r.text
        fid = r.json()["folder"]["id"]

        # Conflict on dup name
        dup_name = r.json()["folder"]["name"]
        r2 = client.post(
            "/workspace/folders",
            json={"parent_folder_id": root, "name": dup_name},
            headers=_hdr(KLEAR_OWNER),
        )
        assert r2.status_code == 409, r2.text

        # Rename
        r3 = client.patch(
            f"/workspace/folders/{fid}",
            json={"name": _new_name("Drafts-renamed")},
            headers=_hdr(KLEAR_OWNER),
        )
        assert r3.status_code == 200, r3.text

        # Move under Outputs
        r4 = client.patch(
            f"/workspace/folders/{fid}",
            json={"parent_folder_id": outputs},
            headers=_hdr(KLEAR_OWNER),
        )
        assert r4.status_code == 200, r4.text
        assert r4.json()["folder"]["parent_folder_id"] == outputs

        # Soft-delete
        r5 = client.delete(
            f"/workspace/folders/{fid}",
            headers=_hdr(KLEAR_OWNER),
        )
        assert r5.status_code == 200, r5.text


@iwo3_db
def test_root_folder_cannot_be_renamed_or_deleted() -> None:
    with TestClient(app) as client:
        root = _root_id(client)
        r = client.patch(
            f"/workspace/folders/{root}",
            json={"name": "newroot"},
            headers=_hdr(KLEAR_OWNER),
        )
        assert r.status_code == 409, r.text
        r2 = client.delete(
            f"/workspace/folders/{root}",
            headers=_hdr(KLEAR_OWNER),
        )
        assert r2.status_code == 409, r2.text


@iwo3_db
def test_folder_cycle_rejected() -> None:
    with TestClient(app) as client:
        root = _root_id(client)
        # Make A under root, B under A
        a = client.post(
            "/workspace/folders",
            json={"parent_folder_id": root, "name": _new_name("A")},
            headers=_hdr(KLEAR_OWNER),
        ).json()["folder"]["id"]
        b = client.post(
            "/workspace/folders",
            json={"parent_folder_id": a, "name": _new_name("B")},
            headers=_hdr(KLEAR_OWNER),
        ).json()["folder"]["id"]
        # Try to move A under B → cycle
        r = client.patch(
            f"/workspace/folders/{a}",
            json={"parent_folder_id": b},
            headers=_hdr(KLEAR_OWNER),
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "move_would_create_cycle"


# ── file CRUD ─────────────────────────────────────────────────────────


@iwo3_db
def test_create_file_403_for_viewer() -> None:
    with TestClient(app) as client:
        outputs = _outputs_id(client)
        r = client.post(
            "/workspace/files",
            json={
                "workspace_folder_id": outputs,
                "filename": _new_name("test") + ".txt",
                "content_text": "hi",
            },
            headers=_hdr(KLEAR_VIEWER),
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_create_then_rename_then_move_then_delete_file() -> None:
    with TestClient(app) as client:
        root = _root_id(client)
        outputs = _outputs_id(client)
        fname = _new_name("note") + ".md"
        r = client.post(
            "/workspace/files",
            json={
                "workspace_folder_id": outputs,
                "filename": fname,
                "mime_type": "text/markdown",
                "content_text": "# Hello",
            },
            headers=_hdr(KLEAR_OPERATOR),
        )
        assert r.status_code == 201, r.text
        fid = r.json()["file"]["id"]

        # Rename
        r2 = client.patch(
            f"/workspace/files/{fid}",
            json={"filename": _new_name("renamed") + ".md"},
            headers=_hdr(KLEAR_OPERATOR),
        )
        assert r2.status_code == 200, r2.text

        # Move to root
        r3 = client.patch(
            f"/workspace/files/{fid}",
            json={"workspace_folder_id": root},
            headers=_hdr(KLEAR_OPERATOR),
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["file"]["workspace_folder_id"] == root

        # Delete (admin perm)
        r4 = client.delete(
            f"/workspace/files/{fid}",
            headers=_hdr(KLEAR_OWNER),
        )
        assert r4.status_code == 200, r4.text


@iwo3_db
def test_create_file_400_for_invalid_b64() -> None:
    with TestClient(app) as client:
        outputs = _outputs_id(client)
        r = client.post(
            "/workspace/files",
            json={
                "workspace_folder_id": outputs,
                "filename": _new_name("bin") + ".bin",
                "mime_type": "application/octet-stream",
                "content_b64": "@@@not-base64@@@",
            },
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 400, r.text


@iwo3_db
def test_create_file_404_for_unknown_folder() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/workspace/files",
            json={
                "workspace_folder_id": str(uuid.uuid4()),
                "filename": _new_name() + ".txt",
                "content_text": "x",
            },
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 404, r.text


@iwo3_db
def test_get_folder_contents_returns_children_and_files() -> None:
    with TestClient(app) as client:
        outputs = _outputs_id(client)
        # Create a child + file inside
        sub = client.post(
            "/workspace/folders",
            json={"parent_folder_id": outputs, "name": _new_name("sub")},
            headers=_hdr(KLEAR_OWNER),
        ).json()["folder"]["id"]
        f = client.post(
            "/workspace/files",
            json={
                "workspace_folder_id": outputs,
                "filename": _new_name() + ".txt",
                "content_text": "x",
            },
            headers=_hdr(KLEAR_OWNER),
        ).json()["file"]
        r = client.get(
            f"/workspace/folders/{outputs}",
            headers=_hdr(KLEAR_OPERATOR),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert any(c["id"] == sub for c in body["children"])
        assert any(file["id"] == f["id"] for file in body["files"])
