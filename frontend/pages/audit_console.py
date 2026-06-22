"""Audit Console: sessions listed newest-first with one active trace detail."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from frontend.shared import (
    DECISION_COPY,
    TOOL_LABELS,
    _cost,
    _humanize,
    _is_voice,
    _tok,
    _ts,
    fetch_session_detail,
    fetch_sessions,
    render_json_code,
)

_OUTCOME_ICON  = {"APPROVE": "✓", "DENY": "✕", "ESCALATE": "⚠"}
_OUTCOME_LABEL = {"APPROVE": "APPROVED", "DENY": "DENIED", "ESCALATE": "ESCALATED"}



def _short_ts(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %d  %H:%M")
    except (ValueError, TypeError):
        return ""


_DETAIL_CACHE_KEY = "_audit_detail_cache"
_ACTIVE_SESSION_KEY = "_audit_active_session_id"


def _cached_detail(sid: str) -> dict | None:
    cache = st.session_state.setdefault(_DETAIL_CACHE_KEY, {})
    if sid not in cache:
        detail, _ = fetch_session_detail(sid)
        cache[sid] = detail
    return cache[sid]


def _session_label(sess: dict[str, Any]) -> str:
    sid = sess["session_id"]
    email = sess.get("customer_email") or "no email"
    ts = _short_ts(sess.get("created_at", ""))
    ts_part = f"  ·  {ts}" if ts else ""
    return f"#{sid[-8:]}  ·  {email}{ts_part}"


def _session_status(detail: dict[str, Any] | None) -> tuple[str, str]:
    final_decisions = (detail or {}).get("final_decisions", [])
    tool_calls = (detail or {}).get("tool_calls", [])
    traces = (detail or {}).get("traces", [])

    if final_decisions:
        decision_type = final_decisions[-1]["decision_type"]
        return decision_type.lower(), decision_type
    if any(call["status"] == "failed" for call in tool_calls):
        return "errored", "ERRORED"
    if tool_calls or traces:
        return "incomplete", "INCOMPLETE"
    return "no-activity", "NO ACTIVITY"


def _render_session_button(
    *,
    sid: str,
    label: str,
    status_cls: str,
    status_label: str,
    selected: bool,
) -> None:
    card_key = f"audit_session_card_{status_cls}_{'active' if selected else 'idle'}_{sid[-8:]}"

    with st.container(key=card_key):
        if selected:
            st.markdown(
                f'<div class="audit-session-card {status_cls} active">'
                f'<span class="s-email">{label}</span>'
                f'<span class="chip chip-{status_cls} audit-status-chip">{status_label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        elif st.button(label, key=f"audit_session_{sid}", use_container_width=True):
            st.session_state[_ACTIVE_SESSION_KEY] = sid
            st.rerun()


def main() -> None:
    st.markdown('<span id="_audit_marker" style="display:none"></span>', unsafe_allow_html=True)
    st.markdown("### Audit Console")
    st.caption("Sessions newest first. Select any row for full trace.")

    sessions, err = fetch_sessions()
    if err:
        st.error(f"Could not load sessions: {err}")
        return

    if not sessions:
        st.markdown(
            '<div class="empty-state">'
            '<p class="es-title">No sessions yet</p>'
            '<p>Run a test scenario in Support Desk, then return here.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    ordered_sessions = list(reversed(sessions))
    labels = {sess["session_id"]: _session_label(sess) for sess in ordered_sessions}
    session_ids = list(labels)

    current_sid = st.session_state.get(_ACTIVE_SESSION_KEY)
    selected_sid = current_sid if current_sid in labels else session_ids[0]
    st.session_state[_ACTIVE_SESSION_KEY] = selected_sid

    list_col, detail_col = st.columns([0.28, 0.72], gap="large")

    with list_col:
        st.markdown('<span id="_audit_list_marker" style="display:none"></span>', unsafe_allow_html=True)
        st.markdown('<div class="panel-label">Recent sessions</div>', unsafe_allow_html=True)
        for sid in session_ids:
            detail = _cached_detail(sid)
            status_cls, status_label = _session_status(detail)
            label = labels[sid]
            _render_session_button(
                sid=sid,
                label=label,
                status_cls=status_cls,
                status_label=status_label,
                selected=sid == selected_sid,
            )

    with detail_col:
        st.markdown('<span id="_audit_detail_marker" style="display:none"></span>', unsafe_allow_html=True)
        st.markdown('<div class="panel-label">Trace detail</div>', unsafe_allow_html=True)
        st.caption(f"Showing {labels[selected_sid]} from {len(session_ids)} sessions.")
        detail = _cached_detail(selected_sid)
        if detail:
            _render_detail(detail)
        else:
            st.caption("Could not load session detail.")


def _render_detail(detail: dict[str, Any]) -> None:
    traces          = detail.get("traces", [])
    tool_calls      = detail.get("tool_calls", [])
    final_decisions = detail.get("final_decisions", [])
    failed          = [c for c in tool_calls if c["status"] == "failed"]

    total_lat  = (sum((t.get("latency_ms") or 0) for t in traces) +
                  sum((c.get("latency_ms") or 0) for c in tool_calls))
    total_tok  = sum(_tok(t.get("token_usage")) for t in traces)
    total_cost = sum(float(t.get("estimated_cost_usd") or 0) for t in traces)
    # If every LLM trace carries the same cost label (e.g. all "local"), surface
    # that label for the total rather than showing "$0.0000".
    llm_labels = {t.get("cost_label") for t in traces if t.get("event_type") == "llm_response"}
    total_cost_label = llm_labels.pop() if len(llm_labels) == 1 else None

    st.markdown(
        f'<div class="metric-grid">'
        f'<div class="metric"><div class="k">Traces</div><div class="v">{len(traces)}</div></div>'
        f'<div class="metric"><div class="k">Tools</div><div class="v">{len(tool_calls)}</div></div>'
        f'<div class="metric"><div class="k">Decisions</div><div class="v">{len(final_decisions)}</div></div>'
        f'<div class="metric{"  alert" if failed else ""}"><div class="k">Failed</div><div class="v">{len(failed)}</div></div>'
        f'<div class="metric"><div class="k">Latency</div><div class="v">{total_lat} ms</div></div>'
        f'<div class="metric"><div class="k">Tokens</div><div class="v">{total_tok}</div></div>'
        f'<div class="metric"><div class="k">Cost</div><div class="v">{_cost(total_cost or None, total_cost_label)}</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if final_decisions:
        dec = final_decisions[-1]
        dt  = dec["decision_type"]
        cls = dt.lower()
        _, label = DECISION_COPY.get(dt, ("", dt))
        codes_html = "".join(
            f'<span class="chip chip-brand" style="margin-right:0.3rem">{r}</span>'
            for r in (dec.get("reason_codes") or [])
        )
        st.markdown(
            f'<div class="verdict-block {cls}" style="margin-bottom:0.8rem">'
            f'<span class="verdict-type {cls}">{label.upper()}</span>'
            f'<br><span style="font-family:JetBrains Mono,monospace;font-size:0.65rem;'
            f'color:var(--faint)">id · {dec["decision_id"]}</span>'
            f'<br><span style="margin-top:0.3rem;display:inline-block">{codes_html}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        failed_calls = [c for c in tool_calls if c["status"] == "failed"]
        if failed_calls:
            s_cls  = "errored"
            s_label = "ERRORED"
            s_note  = f"{len(failed_calls)} tool call{'s' if len(failed_calls) != 1 else ''} failed, no decision was reached"
        elif tool_calls or traces:
            s_cls  = "incomplete"
            s_label = "INCOMPLETE"
            s_note  = "Session ended without reaching a terminal decision"
        else:
            s_cls  = "no-activity"
            s_label = "NO ACTIVITY"
            s_note  = "Session was created but no messages were processed"
        st.markdown(
            f'<div class="verdict-block {s_cls}" style="margin-bottom:0.8rem">'
            f'<span class="verdict-type {s_cls}">{s_label}</span>'
            f'<br><span style="font-size:0.82rem;color:var(--muted);margin-top:0.25rem;display:block">'
            f'{s_note}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    tl_tab, tc_tab, raw_tab = st.tabs(["Timeline", "Tool calls", "Raw JSON"])

    with tl_tab:
        _render_timeline(traces)
    with tc_tab:
        _render_tool_calls(tool_calls)
    with raw_tab:
        render_json_code(detail)


def _render_timeline(traces: list[dict[str, Any]]) -> None:
    if not traces:
        st.info("No trace events.")
        return

    for trace in sorted(traces, key=lambda t: t.get("created_at", "")):
        title = "Voice input" if _is_voice(trace["event_type"]) else _humanize(trace["event_type"])
        lat   = trace.get("latency_ms") or 0
        tok   = _tok(trace.get("token_usage"))
        cost  = _cost(trace.get("estimated_cost_usd"), trace.get("cost_label"))
        meta  = f"{_ts(trace['created_at'])} · {lat} ms · {tok} tok · {cost}"

        st.markdown(
            f'<div class="tl-row">'
            f'<span class="tl-dot">·</span>'
            f'<span class="tl-title">{title}</span>'
            f'<span class="tl-meta">&ensp;{meta}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        with st.expander("Payload", expanded=False):
            render_json_code(trace["payload"])


def _render_tool_calls(tool_calls: list[dict[str, Any]]) -> None:
    if not tool_calls:
        st.info("No tool calls.")
        return

    for call in tool_calls:
        is_failed = call["status"] == "failed"
        retried   = (call.get("attempt_number") or 1) > 1
        icon      = "✕" if is_failed else "✓"
        label     = TOOL_LABELS.get(call["tool_name"], call["tool_name"])
        lat       = call.get("latency_ms") or 0
        retry     = f" · retry #{call.get('attempt_number', 1)}" if retried else ""

        with st.expander(f"{icon} {label}{retry} · {lat} ms", expanded=is_failed):
            st.caption(f"{_ts(call['created_at'])} · {call['status']}")
            if call.get("error_message"):
                st.error(call["error_message"])
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Input**")
                render_json_code(call["tool_input"])
            with c2:
                st.markdown("**Output**")
                render_json_code(call.get("tool_output") or {})
