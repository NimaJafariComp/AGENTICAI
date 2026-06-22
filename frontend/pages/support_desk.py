"""
Support Desk: three-column ops console.
No open/close HTML div tricks. Each st.markdown call is self-contained.
"""
from __future__ import annotations

import queue as _queue
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from backend.demo_scenarios import DEMO_SCENARIOS, DemoScenario
from frontend.shared import (
    DECISION_COPY,
    SK,
    ensure_chat_session,
    ensure_state,
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
    "ready":     "Transcript ready, edit or send",
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

_ENTER_TO_SEND_SCRIPT = """
<script>
(function () {
  const doc = (window.parent && window.parent.document) ? window.parent.document : document;
  if (doc._refundEnterToSend) return;
  doc._refundEnterToSend = true;
  doc.addEventListener('keydown', function (e) {
    if (e.target.tagName !== 'TEXTAREA') return;
    if (e.key !== 'Enter' || e.shiftKey) return;
    const card = e.target.closest('[class*="st-key-composer_card"]');
    if (!card) return;
    e.preventDefault();
    const btn = card.querySelector('[data-testid="stBaseButton-primary"]')
             || card.querySelector('button[kind="primary"]');
    if (btn && !btn.disabled) btn.click();
  }, true);
})();
</script>
"""

_CHAT_AUTOSCROLL_SCRIPT = """
<div data-chat-scroll-token="__TOKEN__"></div>
<script>
(function () {
  const doc = (window.parent && window.parent.document) ? window.parent.document : document;

  function scrollChatToBottom() {
    const chatCard = doc.querySelector('[class*="st-key-chat_card"]');
    const bottom = doc.getElementById("chat-bottom");
    if (!chatCard) return;

    chatCard.scrollTop = chatCard.scrollHeight;
    if (bottom) bottom.scrollIntoView({ block: "end", inline: "nearest" });
  }

  requestAnimationFrame(scrollChatToBottom);
  setTimeout(scrollChatToBottom, 60);
  setTimeout(scrollChatToBottom, 180);
  setTimeout(scrollChatToBottom, 420);
})();
</script>
"""

# ── Page entry ────────────────────────────────────────────────────────────────

def main() -> None:
    ensure_state()

    left, center, right = st.columns([1.15, 2.75, 1.1], gap="large")
    with left, st.container(key="left_scroll_rail"):
        # Marker scopes the column-divider CSS to this top-level layout only.
        st.markdown('<span id="_desk_marker" style="display:none"></span>', unsafe_allow_html=True)
        _render_left_panel()
    with center:
        # Marker lets CSS make this column fill the row height and pin the composer.
        st.markdown('<span id="_center_marker" style="display:none"></span>', unsafe_allow_html=True)
        st.markdown(
            '<div class="console-header">'
            '<span class="console-title">Refund Decision Console</span>'
            '<span class="console-sub">Run a scenario or describe a request, and the decision appears here</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        with st.container(border=True, key="chat_card"):
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
        exp_cls = scenario["expected"].lower()

        with st.container(border=True, key=f"scncard_{exp_cls}_{scenario['key']}"):
            if st.button(
                scenario["label"],
                key=f"s_{scenario['key']}",
                use_container_width=True,
            ):
                _run_scenario(scenario)

    st.markdown('<hr style="margin:0.8rem 0;border-color:var(--border)">', unsafe_allow_html=True)
    st.markdown('<p class="panel-label">Recent sessions</p>', unsafe_allow_html=True)
    with st.container():
        st.markdown('<span id="_recent_sessions_marker" style="display:none"></span>', unsafe_allow_html=True)
        _render_session_list()


_RECENT_SESSION_LIMIT = 5
_SHOW_ALL_RECENT_SESSIONS = "show_all_recent_sessions"


def _render_session_card(sess: dict[str, Any]) -> None:
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


def _render_session_list() -> None:
    sessions, _ = fetch_sessions()
    if not sessions:
        st.caption("No sessions yet.")
        return

    ordered = list(reversed(sessions))

    for sess in ordered[:_RECENT_SESSION_LIMIT]:
        _render_session_card(sess)

    overflow = ordered[_RECENT_SESSION_LIMIT:]
    if not overflow:
        st.session_state[_SHOW_ALL_RECENT_SESSIONS] = False
        return

    if not st.session_state.get(_SHOW_ALL_RECENT_SESSIONS, False):
        if st.button(
            f"Show {len(overflow)} more",
            key="show_more_recent_sessions",
            use_container_width=True,
        ):
            st.session_state[_SHOW_ALL_RECENT_SESSIONS] = True
            st.rerun()
        return

    for sess in overflow:
        _render_session_card(sess)


def _run_scenario(scenario: DemoScenario) -> None:
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
            '<div class="chat-empty">'
            '<div class="chat-empty-icon">💬</div>'
            '<p class="chat-empty-title">No conversation yet</p>'
            '<p class="chat-empty-sub">Pick a test scenario on the left, '
            'or describe a refund request in the box below.</p>'
            '</div>',
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
    _auto_scroll_chat()


def _auto_scroll_chat() -> None:
    messages = st.session_state.get(SK.CHAT_MESSAGES, [])
    token = f"{len(messages)}-{int(bool(st.session_state.get(SK.PROCESSING)))}"
    components.html(_CHAT_AUTOSCROLL_SCRIPT.replace("__TOKEN__", token), height=0, width=0)


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

    with st.container(border=True, key="composer_card"):
        # Marker turns this container into the bottom composer card (CSS :has on id).
        st.markdown('<span id="_composer_marker" style="display:none"></span>', unsafe_allow_html=True)

        # Reserve a stable status slot so the textarea doesn't jump when voice state changes.
        status_markup = (
            '<span style="color:var(--muted)">Voice or type your request below</span>'
            if voice_state == "idle"
            else '<span style="color:var(--deny)">● Listening, live transcript appears below</span>'
            if voice_state == "recording"
            else '<span style="color:var(--approve)">✓ Transcript ready, edit or send</span>'
        )
        st.markdown(
            f'<div style="min-height:1.1rem;margin:0 0 0.3rem;font-size:0.76rem">{status_markup}</div>',
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
        st.html(_ENTER_TO_SEND_SCRIPT, unsafe_allow_javascript=True)

        c_actions, c_cancel, c_spacer, c_send = st.columns([0.8, 1.1, 3.1, 1.6], gap="small")
        c_spacer.empty()

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
            elif voice_state == "ready" and st.button("🔁", key="rerecord_btn"):
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
        st.markdown(
            '<div class="inspector-empty">'
            '<p class="inspector-empty-title">No active case yet</p>'
            '<p class="inspector-empty-sub">Run a scenario to populate:</p>'
            '<div class="inspector-skeleton">'
            '<div class="skeleton-row"><span class="skeleton-dot"></span>Eligibility checks</div>'
            '<div class="skeleton-row"><span class="skeleton-dot"></span>Policy citations</div>'
            '<div class="skeleton-row"><span class="skeleton-dot"></span>Risk flags</div>'
            '<div class="skeleton-row"><span class="skeleton-dot"></span>Recommended action</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
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
        email = customer.get("email") or ""
        name  = customer.get("name") or customer.get("full_name") or ""
        rows  = ""
        if email:
            rows += f'<div class="case-kv"><span class="case-kv-key">Email</span><span class="case-kv-val">{email}</span></div>'
        if name:
            rows += f'<div class="case-kv"><span class="case-kv-key">Name</span><span class="case-kv-val">{name}</span></div>'
        if rows:
            st.markdown(
                f'<p class="intel-key">Customer</p><div class="case-fact">{rows}</div>',
                unsafe_allow_html=True,
            )

    if order:
        order_id  = order.get("order_id") or "—"
        item_name = order.get("item_name") or order.get("product_name") or ""
        amount    = order.get("amount") or order.get("total_amount")
        rows  = f'<div class="case-kv"><span class="case-kv-key">ID</span><span class="case-kv-val">{order_id}</span></div>'
        if item_name:
            rows += f'<div class="case-kv"><span class="case-kv-key">Item</span><span class="case-kv-val dim">{item_name}</span></div>'
        if amount:
            rows += f'<div class="case-kv"><span class="case-kv-key">Amt</span><span class="case-kv-val">${amount:.2f}</span></div>'
        st.markdown(
            f'<p class="intel-key">Order</p><div class="case-fact">{rows}</div>',
            unsafe_allow_html=True,
        )

    if decision:
        dt       = decision["decision_type"]
        cls      = dt.lower()
        _, label = DECISION_COPY.get(dt, ("", dt))
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
            f'<span class="reason-code">{r.replace("_", " ").capitalize()}</span>'
            for r in reason_codes
        )
        st.markdown(
            f'<p class="intel-key">Policy</p>'
            f'<div style="display:flex;flex-wrap:wrap;gap:0.25rem;margin-bottom:0.35rem">{codes_html}</div>',
            unsafe_allow_html=True,
        )

    if tool_progress:
        n_unique = len(tool_progress)
        label_text = f"Tools · {n_unique}" + (" · live" if live else "")

        def _tool_row(s: dict[str, Any]) -> str:
            status   = s["status"]
            icon_cls = "ok" if status == "succeeded" else ("fail" if status == "failed" else "pending")
            icon     = "✓" if status == "succeeded" else ("✕" if status == "failed" else "·")
            count    = s.get("count", 1)
            badge    = f'<span class="tool-count">×{count}</span>' if count > 1 else ""
            return (
                '<div class="tool-row">'
                f'<span class="tool-{icon_cls}">{icon}</span>'
                f'<span class="tool-label">{s["label"]}</span>'
                f'{badge}'
                '</div>'
            )

        rows_html = "".join(_tool_row(s) for s in tool_progress)
        st.markdown(
            f'<hr style="border-color:var(--border);margin:0.5rem 0 0.4rem">'
            f'<p class="intel-key">{label_text}</p>'
            f'{rows_html}',
            unsafe_allow_html=True,
        )
    elif live:
        st.markdown(
            '<hr style="border-color:var(--border);margin:0.5rem 0 0.4rem">'
            '<p class="intel-key">Tools · live</p>'
            '<div class="tool-row"><span class="tool-pending">·</span><span class="tool-label">Waiting…</span></div>',
            unsafe_allow_html=True,
        )
