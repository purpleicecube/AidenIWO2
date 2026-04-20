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

from streamlit.testing.v1 import AppTest  # noqa: E402


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


def test_render_sidebar_shell_derived_keys_use_distinct_names() -> None:
    """Guard the naming convention — widget keys and derived-state
    keys must be disjoint. A future refactor that re-collides them
    would trip this on any AppTest run."""
    at = AppTest.from_file(str(CONSOLE_DIR / "Home.py"), default_timeout=20)
    at.run()

    # Widget keys — these are Streamlit-owned; their values persist
    # across reruns but are not writeable post-instantiation.
    widget_keys = {"iwo3_user_label", "iwo3_tenant_idx", "iwo3_api_base_url"}
    # Derived keys — application-owned; we write these every render.
    derived_keys = {
        "iwo3_api",
        "iwo3_current_user_id",
        "iwo3_current_user_role",
        "iwo3_current_tenant_id",
        "iwo3_current_tenant_label",
    }

    overlap = widget_keys & derived_keys
    assert not overlap, f"Widget/derived key collision: {overlap}"

    # Derived keys must be present after render_sidebar_shell ran.
    ss = at.session_state
    missing = [k for k in derived_keys if k not in ss]
    assert missing == [], f"Derived session keys missing after shell render: {missing}"
