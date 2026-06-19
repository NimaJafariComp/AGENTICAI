"""
Support Desk — three-column ops console.
No open/close HTML div tricks. Each st.markdown call is self-contained.
"""
from __future__ import annotations

import queue as _queue
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as _components

from frontend.shared import (
    DECISION_COPY,
    DEMO_SCENARIOS,
    SK,
    TOOL_LABELS,
    ensure_chat_session,
    extract_case_intel,
    fetch_session_detail,
    fetch_session_detail_live,
    fetch_sessions,
    reset_session,
    start_send,
)

_VOICE_PLACEHOLDER: dict[str, str] = {
    "idle":      "Describe the refund request…",
    "recording": "● Listening…",
    "ready":     "Transcript ready — edit or send",
}

# Declared component gets allow="microphone" on its iframe automatically
_SPEECH_COMPONENT_DIR = Path(__file__).resolve().parent.parent / "components" / "speech"
_speech_input = _components.declare_component("speech_input", path=str(_SPEECH_COMPONENT_DIR))


# ── Page entry ────────────────────────────────────────────────────────────────

def main() -> None:
    left, center, right = st.columns([1.15, 2.75, 1.1], gap="large")
    with left:
        _render_left_panel()
    with center:
        _render_conversation()
        render_composer()
    with right:
        if st.session_state.get(SK.PROCESSING):
            _render_intel_polling()
        else:
            _render_intel_static()


# ── Left panel ────────────────────────────────────────────────────────────────

def _render_left_panel() -> None:
    st.markdown('<p class="panel-label">Test scenarios</p>', unsafe_allow_html=True)

    for scenario in DEMO_SCENARIOS:
        exp     = scenario["expected"]
        exp_cls = exp.lower()

        if st.button(
            scenario["label"],
            key=f"s_{scenario['key']}",
            use_container_width=True,
        ):
            _run_scenario(scenario)

        # Single self-contained markdown — why text + chip
        st.markdown(
            f'<div class="scenario-meta">'
            f'<span class="scenario-why">{scenario["why"]}</span>'
            f'<span class="chip chip-{exp_cls}">{exp}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<hr style="margin:0.8rem 0;border-color:var(--border)">', unsafe_allow_html=True)
    st.markdown('<p class="panel-label">Recent sessions</p>', unsafe_allow_html=True)
    _render_session_list()


def _render_session_list() -> None:
    sessions, _ = fetch_sessions()
    if not sessions:
        st.caption("No sessions yet.")
        return

    for sess in list(reversed(sessions))[:6]:
        sid      = sess["session_id"]
        email    = sess.get("customer_email") or "—"
        short_id = sid[-10:]
        detail, _ = fetch_session_detail(sid)
        decision  = ""
        chip_html = ""
        if detail:
            decs = detail.get("final_decisions", [])
            if decs:
                dt        = decs[-1]["decision_type"]
                chip_html = f'<span class="chip chip-{dt.lower()}">{dt}</span>'
                decision  = dt

        # Two-row card: ID + chip on top, email below
        st.markdown(
            f'<div class="session-card">'
            f'<div class="session-card-top">'
            f'<span class="s-id">{short_id}</span>'
            f'{chip_html}'
            f'</div>'
            f'<span class="s-email">{email}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _run_scenario(scenario: dict[str, str]) -> None:
    reset_session()
    msg = scenario["message"]
    st.session_state[SK.CHAT_MESSAGES].append({"role": "user", "content": msg})
    _kick_send(msg)


# ── Center: conversation ──────────────────────────────────────────────────────

def _render_conversation() -> None:
    messages = st.session_state.get(SK.CHAT_MESSAGES, [])

    if not messages:
        st.markdown(
            '<div class="empty-state">'
            '<p class="es-title">Refund Support Console</p>'
            '<p>Pick a test scenario on the left, or describe a refund request below.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    for msg in messages:
        _render_message(msg)

    if st.session_state.get(SK.PROCESSING):
        with st.chat_message("assistant"):
            st.markdown("⋯")


def _render_message(msg: dict[str, Any]) -> None:
    role = msg["role"]
    with st.chat_message("user" if role == "user" else "assistant"):
        st.markdown(msg["content"])
        decision = msg.get("decision_type")
        if decision and decision in DECISION_COPY:
            klass, text = DECISION_COPY[decision]
            st.markdown(
                f'<span class="seal {klass}">{text}</span>',
                unsafe_allow_html=True,
            )


# ── Center: composer ──────────────────────────────────────────────────────────

@st.fragment
def render_composer() -> None:
    voice_state = st.session_state.get(SK.VOICE_STATE, "idle")
    processing  = st.session_state.get(SK.PROCESSING, False)

    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    # Live speech recognition via declared component (has allow="microphone" on iframe)
    if voice_state == "recording":
        result = _speech_input(default={"text": "", "final_text": ""}, key="speech_comp")
        if result and result.get("text"):
            st.session_state[SK.CHAT_DRAFT] = result["text"]

    # Status line above textarea (non-idle only)
    if voice_state == "recording":
        st.markdown(
            '<p style="font-size:0.78rem;color:var(--deny);margin:0 0 0.25rem">● Recording — tap ⏹ to stop</p>',
            unsafe_allow_html=True,
        )
    elif voice_state == "ready":
        st.markdown(
            '<p style="font-size:0.78rem;color:var(--approve);margin:0 0 0.25rem">✓ Transcript ready — edit or send</p>',
            unsafe_allow_html=True,
        )

    draft = st.text_area(
        "Message",
        value=st.session_state.get(SK.CHAT_DRAFT, ""),
        placeholder=_VOICE_PLACEHOLDER.get(voice_state, "Describe the refund request…"),
        height=72,
        disabled=processing,
        label_visibility="collapsed",
        key="composer_draft",
    )
    # Don't overwrite draft during recording (JS is writing to it)
    if voice_state != "recording":
        st.session_state[SK.CHAT_DRAFT] = draft

    c_mic, c_clear, c_send = st.columns([1, 1, 4.5])

    with c_mic:
        if voice_state == "idle" and not processing:
            if st.button("🎙", key="mic_btn", help="Start voice input"):
                st.session_state[SK.CHAT_DRAFT]  = ""
                st.session_state[SK.VOICE_STATE] = "recording"
                st.rerun()
        elif voice_state == "recording":
            if st.button("⏹", key="stop_rec", help="Stop recording"):
                # Capture whatever JS wrote to the textarea widget before rerun
                captured = st.session_state.get("composer_draft", "").strip()
                st.session_state[SK.CHAT_DRAFT]  = captured
                st.session_state[SK.VOICE_STATE] = "ready" if captured else "idle"
                st.rerun()
        elif voice_state == "ready":
            if st.button("🔁", key="rerecord_btn", help="Re-record"):
                st.session_state[SK.CHAT_DRAFT]  = ""
                st.session_state[SK.VOICE_STATE] = "recording"
                st.rerun()

    with c_clear:
        if voice_state in ("recording", "ready"):
            if st.button("✕", key="cancel_rec", help="Cancel"):
                st.session_state[SK.CHAT_DRAFT]  = ""
                st.session_state[SK.VOICE_STATE] = "idle"
                st.rerun()

    with c_send:
        current_draft = st.session_state.get(SK.CHAT_DRAFT, "")
        disabled = not current_draft.strip() or voice_state == "recording" or processing
        if st.button("Send →", type="primary", disabled=disabled,
                     key="send_btn", use_container_width=True):
            msg = current_draft.strip()
            st.session_state[SK.CHAT_DRAFT]  = ""
            st.session_state[SK.VOICE_STATE] = "idle"
            st.session_state[SK.CHAT_MESSAGES].append({"role": "user", "content": msg})
            _kick_send(msg)


# ── Send dispatch ─────────────────────────────────────────────────────────────

def _kick_send(message: str) -> None:
    session_id = ensure_chat_session()
    result_q   = start_send(session_id, message)
    st.session_state[SK.RESULT_QUEUE] = result_q
    st.session_state[SK.PROCESSING]   = True
    st.session_state[SK.CASE_INTEL]   = None
    fetch_sessions.clear()
    fetch_session_detail.clear()
    st.rerun(scope="app")


# ── Right panel: two modes ────────────────────────────────────────────────────

@st.fragment(run_every=1)
def _render_intel_polling() -> None:
    st.markdown('<p class="panel-label">Case intelligence · live</p>', unsafe_allow_html=True)
    sid = st.session_state.get(SK.ACTIVE_SID) or st.session_state.get(SK.CHAT_SESSION_ID)
    if sid:
        detail, _ = fetch_session_detail_live(sid)
        if detail:
            _render_intel_body(extract_case_intel(detail), live=True)

    result_q: _queue.Queue | None = st.session_state.get(SK.RESULT_QUEUE)
    if result_q is None:
        return
    try:
        result, error = result_q.get_nowait()
    except _queue.Empty:
        return

    st.session_state[SK.PROCESSING]   = False
    st.session_state[SK.RESULT_QUEUE] = None
    st.session_state[SK.CASE_INTEL]   = None
    fetch_sessions.clear()
    fetch_session_detail.clear()

    if error:
        st.session_state[SK.CHAT_MESSAGES].append(
            {"role": "assistant", "content": f"Request failed: {error}"}
        )
    else:
        st.session_state[SK.CHAT_MESSAGES].append(
            {
                "role":          "assistant",
                "content":       result.get("assistant_message", "No reply returned."),
                "decision_type": result.get("decision_type"),
            }
        )
    st.rerun(scope="app")


def _render_intel_static() -> None:
    st.markdown('<p class="panel-label">Case intelligence</p>', unsafe_allow_html=True)
    sid = st.session_state.get(SK.ACTIVE_SID) or st.session_state.get(SK.CHAT_SESSION_ID)

    if not sid:
        st.caption("No active case. Run a scenario to see live case details.")
        return

    intel = st.session_state.get(SK.CASE_INTEL)
    if intel is None:
        detail, err = fetch_session_detail(sid)
        if err or not detail:
            st.caption(f"Could not load: {err}")
            return
        intel = extract_case_intel(detail)
        st.session_state[SK.CASE_INTEL] = intel

    _render_intel_body(intel, live=False)


def _render_intel_body(intel: dict[str, Any], *, live: bool) -> None:
    customer      = intel.get("customer")
    order         = intel.get("order")
    decision      = intel.get("decision")
    reason_codes  = intel.get("reason_codes", [])
    tool_progress = intel.get("tool_progress", [])

    if customer:
        name  = customer.get("name") or customer.get("full_name") or "—"
        email = customer.get("email") or "—"
        st.markdown(
            f'<p class="intel-key">Customer</p>'
            f'<p class="intel-val">{name}</p>'
            f'<p class="intel-sub">{email}</p>',
            unsafe_allow_html=True,
        )

    if order:
        order_id  = order.get("order_id") or "—"
        item_name = order.get("item_name") or order.get("product_name") or "—"
        amount    = order.get("amount") or order.get("total_amount")
        amount_s  = f" · ${amount:.2f}" if amount else ""
        st.markdown(
            f'<p class="intel-key">Order</p>'
            f'<p class="intel-val">{order_id}</p>'
            f'<p class="intel-sub">{item_name}{amount_s}</p>',
            unsafe_allow_html=True,
        )

    if decision:
        dt       = decision["decision_type"]
        cls      = dt.lower()
        _, label = DECISION_COPY.get(dt, ("", dt))
        # Self-contained verdict block — open and close in one call
        st.markdown(
            f'<p class="intel-key">Decision</p>'
            f'<div class="verdict-block {cls}">'
            f'<span class="verdict-type {cls}">{label.upper()}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    elif live:
        st.markdown(
            '<p class="intel-key">Decision</p>'
            '<div class="verdict-block pending">'
            '<span class="verdict-type pending">PENDING</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    if reason_codes:
        codes_html = "".join(
            f'<p class="reason-code">— {r.replace("_", " ").capitalize()}</p>'
            for r in reason_codes
        )
        st.markdown(
            f'<p class="intel-key">Policy</p>{codes_html}',
            unsafe_allow_html=True,
        )

    if tool_progress:
        label_text = "Tools · live" if live else "Tools"
        rows_html = "".join(
            '<p class="tool-row">'
            f'<span class="tool-{("ok" if s["status"] == "succeeded" else ("fail" if s["status"] == "failed" else "pending"))}">'
            f'{"✓" if s["status"] == "succeeded" else ("✕" if s["status"] == "failed" else "·")}'
            f'</span> {s["label"]}</p>'
            for s in tool_progress
        )
        st.markdown(
            f'<hr style="border-color:var(--border);margin:0.6rem 0">'
            f'<p class="intel-key">{label_text}</p>'
            f'{rows_html}',
            unsafe_allow_html=True,
        )
    elif live:
        st.markdown(
            '<hr style="border-color:var(--border);margin:0.6rem 0">'
            '<p class="intel-key">Tools · live</p>'
            '<p class="tool-row"><span class="tool-pending">·</span> Waiting…</p>',
            unsafe_allow_html=True,
        )
