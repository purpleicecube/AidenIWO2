"""Loop 8.3 hotfix regression test.

Reproduces the session-state collision bug with `streamlit.testing.v1.AppTest`
and proves Home.py renders without raising `StreamlitAPIException`.

Root cause that was fixed: `shell.render_sidebar_shell()` instantiated a
selectbox with `key="iwo3_user_label"` and later wrote back to
`st.session_state["iwo3_user_label"]`. Streamlit disallows post-widget
writes to widget-owned keys. The fix renames the derived slot to
`iwo3_current_user_role` / `iwo3_current_tenant_label` /
`iwo3_current_user_id` / `iwo3_current_tenant_id` so the widget keys are
only written by the widgets themselves.

This test runs headless — no FastAPI subprocess required. The sidebar's
/tenants preflight will surface an APIError banner instead of a crash,
which is the correct failure mode for "API down".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `apps/console-streamlit` importable so AppTest can resolve the
# `shell` / `api_client` / `views` modules the way streamlit run does.
CONSOLE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(CONSOLE_DIR))

# Streamlit isn't part of the api-fastapi uv env that CI runs these
# tests from. When the Streamlit package isn't importable we skip —
# the `test_views_import.py` suite still proves every view module
# parses. Local dev + any env that installs streamlit exercises the
# real AppTest render.
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def test_home_renders_without_streamlit_api_exception() -> None:
    """Home.py must render without raising StreamlitAPIException.

    The regression we're guarding: writing to a widget-owned session
    key after the widget is instantiated. AppTest surfaces those as
    exceptions in `at.exception`.
    """
    at = AppTest.from_file(str(CONSOLE_DIR / "Home.py"), default_timeout=20)
    at.run()

    # Surface any unexpected exceptions with useful context.
    if at.exception:
        messages = [f"{e.name}: {e.value}" for e in at.exception]
        assert False, (
            "Home.py raised during render — widget/session collision "
            f"or similar Streamlit error:\n  " + "\n  ".join(messages)
        )


def test_home_renders_public_landing_before_auth() -> None:
    """Unauthenticated Home.py should present the landing-page login
    surface instead of auto-seeding a dev-auth session."""
    at = AppTest.from_file(str(CONSOLE_DIR / "Home.py"), default_timeout=20)
    at.run()

    ss = at.session_state
    assert "iwo3_api" not in ss
    assert "iwo3_logged_in" not in ss
    assert "iwo3_login_email" in ss
    assert "iwo3_login_password" in ss
