"""
Support Desk — three-column ops console.
No open/close HTML div tricks. Each st.markdown call is self-contained.
"""
from __future__ import annotations

import queue as _queue
from typing import Any

import streamlit as st

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

_LIVE_DICTATION_SCRIPT = """
<script>
(function () {
  const active = __ACTIVE__;
  const token = "__TOKEN__";
  const doc = (window.parent && window.parent.document) ? window.parent.document : document;
  const win = (window.parent && window.parent.HTMLTextAreaElement) ? window.parent : window;

  const state = window.__refundLiveDictation || {
    finalText: "",
    interim: "",
    recognition: null,
    running: false,
    shouldRun: false,
    syncTimer: null,
    lastWritten: null,
    token: null
  };
  window.__refundLiveDictation = state;

  const SpeechRecognition = win.SpeechRecognition || win.webkitSpeechRecognition
    || window.SpeechRecognition || window.webkitSpeechRecognition;

  function findComposer() {
    const textareas = Array.from(doc.querySelectorAll('textarea'));
    return textareas.find((ta) => !ta.disabled) || textareas[0] || null;
  }

  function writeToComposer(text) {
    const textarea = findComposer();
    if (!textarea) return;
    const descriptor = Object.getOwnPropertyDescriptor(
      win.HTMLTextAreaElement.prototype, "value"
    );
    descriptor.set.call(textarea, text);
    textarea.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    state.lastWritten = text;
  }

  // Continuously push the latest transcript into the textarea so React
  // re-renders can't permanently clobber it.
  function startSync() {
    if (state.syncTimer) return;
    state.syncTimer = setInterval(() => {
      const text = (state.finalText + state.interim).trimStart();
      if (text !== state.lastWritten) writeToComposer(text);
    }, 120);
  }

  function stopSync() {
    if (state.syncTimer) { clearInterval(state.syncTimer); state.syncTimer = null; }
  }

  function ensureRecognition() {
    if (state.recognition) return state.recognition;
    if (!SpeechRecognition) { console.warn("[dictation] Web Speech API not supported"); return null; }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const r = event.results[i];
        if (r.isFinal) state.finalText += r[0].transcript + " ";
        else interim += r[0].transcript;
      }
      state.interim = interim;
    };

    recognition.onend = () => {
      state.running = false;
      if (state.shouldRun) startRecognition();
    };

    recognition.onerror = (event) => {
      if (event.error !== "no-speech" && event.error !== "aborted") {
        console.error("[dictation] recognition error:", event.error);
      }
    };

    state.recognition = recognition;
    return recognition;
  }

  function startRecognition() {
    if (state.running) return;
    const recognition = ensureRecognition();
    if (!recognition) return;
    try {
      recognition.start();
      state.running = true;
    } catch (error) {
      if (!error || error.name !== "InvalidStateError") {
        console.error("[dictation] start failed:", error);
      }
    }
  }

  function stopRecognition() {
    state.shouldRun = false;
    stopSync();
    if (state.recognition) {
      try { state.recognition.stop(); } catch (_) {}
    }
    state.running = false;
  }

  if (active) {
    if (state.token !== token) {
      state.token = token;
      state.finalText = "";
      state.interim = "";
      state.lastWritten = null;
      writeToComposer("");
    }
    state.shouldRun = true;
    startSync();
    startRecognition();
  } else {
    stopRecognition();
  }
})();
</script>
"""

# ── Page entry ────────────────────────────────────────────────────────────────

def main() -> None:
    left, center, right = st.columns([1.15, 2.75, 1.1], gap="large")
    with left:
        _render_left_panel()
    with center:
        with st.container(height=520, border=False):
            _render_conversation()
        render_composer()
    with right:
        if st.session_state.get(SK.PROCESSING):
            _render_intel_polling()
        else:
            _render_intel_static()


# ── Left panel ────────────────────────────────────────────────────────────────

def _render_left_panel() -> None:
    has_session = bool(st.session_state.get(SK.CHAT_MESSAGES))
    if has_session:
        if st.button("＋ New session", key="new_session_btn", use_container_width=True):
            reset_session()
            st.rerun()
        st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

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

        decs       = (detail or {}).get("final_decisions", [])
        tool_calls = (detail or {}).get("tool_calls", [])
        traces     = (detail or {}).get("traces", [])

        if decs:
            dt       = decs[-1]["decision_type"]
            chip_cls = dt.lower()
            chip_lbl = dt
        elif any(c["status"] == "failed" for c in tool_calls):
            chip_cls, chip_lbl = "errored", "ERRORED"
        elif tool_calls or traces:
            chip_cls, chip_lbl = "incomplete", "INCOMPLETE"
        else:
            chip_cls, chip_lbl = "no-activity", "NO ACTIVITY"

        chip_html = f'<span class="chip chip-{chip_cls}">{chip_lbl}</span>'

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
    # Anchor used by CSS :has() to target only this container for bottom-alignment
    st.markdown('<span id="_chat_top" style="display:none"></span>', unsafe_allow_html=True)

    messages = st.session_state.get(SK.CHAT_MESSAGES, [])

    if not messages:
        st.markdown(
            '<p style="font-size:0.82rem;color:var(--muted);margin:0.25rem 0">'
            'Pick a test scenario on the left, or describe a refund request below.'
            '</p>',
            unsafe_allow_html=True,
        )
        return

    for msg in messages:
        _render_message(msg)

    if st.session_state.get(SK.PROCESSING):
        with st.chat_message("assistant"):
            st.markdown("⋯")

    # Anchor at the bottom so the container scrolls to newest message
    st.markdown('<div id="chat-bottom"></div>', unsafe_allow_html=True)


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
    composer_nonce = st.session_state.setdefault("composer_draft_nonce", 0)
    composer_key = f"composer_draft_{composer_nonce}"

    st.markdown('<div style="height:0.15rem"></div>', unsafe_allow_html=True)

    # Reserve a stable status slot so the textarea doesn't jump when voice state changes.
    status_markup = (
        '<span style="color:var(--muted)">Voice or type your request below</span>'
        if voice_state == "idle"
        else '<span style="color:var(--deny)">● Listening — live transcript appears below</span>'
        if voice_state == "recording"
        else '<span style="color:var(--approve)">✓ Transcript ready — edit or send</span>'
    )
    st.markdown(
        f'<div style="min-height:1.25rem;margin:0 0 0.25rem;font-size:0.78rem">{status_markup}</div>',
        unsafe_allow_html=True,
    )

    draft = st.text_area(
        "Message",
        value=st.session_state.get(SK.CHAT_DRAFT, ""),
        placeholder=_VOICE_PLACEHOLDER.get(voice_state, "Describe the refund request…"),
        height=72,
        disabled=processing,
        label_visibility="collapsed",
        key=composer_key,
    )
    # Live dictation writes into the textarea in-browser while recording.
    if voice_state != "recording":
        st.session_state[SK.CHAT_DRAFT] = draft

    st.html(
        _LIVE_DICTATION_SCRIPT
        .replace("__ACTIVE__", "true" if voice_state == "recording" else "false")
        .replace("__TOKEN__", str(composer_nonce)),
        unsafe_allow_javascript=True,
    )

    c_actions, c_cancel, c_send = st.columns([0.85, 1.1, 4.9], gap="small")

    with c_actions:
        if voice_state == "idle" and not processing:
            if st.button("🎙", key="mic_btn"):
                st.session_state[SK.CHAT_DRAFT]  = ""
                st.session_state["composer_draft_nonce"] += 1
                st.session_state[SK.VOICE_STATE] = "recording"
                st.rerun()
        elif voice_state == "recording":
            if st.button("⏹", key="stop_rec"):
                captured = st.session_state.get(composer_key, "").strip()
                st.session_state[SK.CHAT_DRAFT] = captured
                st.session_state[SK.VOICE_STATE] = "ready" if captured else "idle"
                st.rerun()
        elif voice_state == "ready":
            if st.button("🔁", key="rerecord_btn"):
                st.session_state[SK.CHAT_DRAFT]  = ""
                st.session_state["composer_draft_nonce"] += 1
                st.session_state[SK.VOICE_STATE] = "recording"
                st.rerun()

    with c_cancel:
        if voice_state in ("recording", "ready"):
            if st.button("Cancel", key="cancel_rec", use_container_width=True):
                st.session_state[SK.CHAT_DRAFT] = ""
                st.session_state["composer_draft_nonce"] += 1
                st.session_state[SK.VOICE_STATE] = "idle"
                st.rerun()
        else:
            st.markdown('<div style="height:2.5rem"></div>', unsafe_allow_html=True)

    with c_send:
        current_draft = draft if voice_state != "recording" else st.session_state.get(SK.CHAT_DRAFT, "")
        disabled = voice_state == "recording" or processing
        if st.button("Send →", type="primary", disabled=disabled,
                     key="send_btn", use_container_width=True):
            msg = current_draft.strip()
            if not msg:
                return
            st.session_state[SK.CHAT_DRAFT]  = ""
            st.session_state["composer_draft_nonce"] += 1
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
