"""Chat with Aiden — Loop 8.3 product-shell MVP.

Chat-style layout with message history persisted in `st.session_state`.
No live LLM execution; the system response is a local dev placeholder
clearly labeled as such. The message loop is the future hook point for
the channel gateway (Telegram/Slack) and the AIDEN runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from shell import page_requires_api


def _seed_messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "content": (
                "Hi — this is the **Chat with Aiden** surface for the IWO3 "
                "operator console.\n\n"
                "The live AIDEN runtime is not wired up in Loop 8.3. "
                "Messages you send here are stored in your Streamlit "
                "session and answered with a labeled local dev "
                "placeholder. The real channel gateway + AIDEN runtime "
                "are Loop 9+ work."
            ),
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source": "system",
        }
    ]


def _placeholder_reply(user_text: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": (
            f"_(local dev placeholder — AIDEN runtime not wired yet)_\n\n"
            f"Received: **{user_text.strip()[:160]}**\n\n"
            f"When Loop 9+ lands, this response will come from the real "
            f"channel gateway → AIDEN (Tier 1) → downstream sub-agents."
        ),
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": "placeholder",
    }


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Chat with Aiden</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Ask Aiden anything. Messages persist in this browser session only.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    if "iwo3_chat_messages" not in st.session_state:
        st.session_state["iwo3_chat_messages"] = _seed_messages()

    messages: list[dict[str, Any]] = st.session_state["iwo3_chat_messages"]

    # Warning banner so there's no doubt about what this is.
    st.warning(
        "🧪 **Local dev placeholder** — AIDEN runtime is not yet connected. "
        "No external model executes here. Loop 9+ wires the channel "
        "gateway (Telegram/Slack) and the AIDEN runtime."
    )

    # Render history.
    for m in messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("source") == "placeholder":
                st.caption(f"_placeholder · {m.get('ts', '')}_")
            elif m.get("source") == "system":
                st.caption(f"_system · {m.get('ts', '')}_")
            else:
                st.caption(m.get("ts", ""))

    # Input.
    user_text = st.chat_input("Ask Aiden anything (local placeholder)…")
    if user_text:
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        messages.append(
            {"role": "user", "content": user_text, "ts": now, "source": "user"}
        )
        messages.append(_placeholder_reply(user_text))
        st.session_state["iwo3_chat_messages"] = messages
        st.rerun()

    with st.expander("Developer · raw session state", expanded=False):
        st.json(messages)

    if st.button("Clear history", key="chat-clear"):
        st.session_state["iwo3_chat_messages"] = _seed_messages()
        st.rerun()


main()
