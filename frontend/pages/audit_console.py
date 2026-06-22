"""Audit Console: sessions listed newest-first, each expandable for full trace."""
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


def _session_status(outcome: str, tool_calls: list, traces: list) -> tuple[str, str]:
    """Return (icon, label) for a session row."""
    if outcome:
        return _OUTCOME_ICON.get(outcome, "·"), _OUTCOME_LABEL.get(outcome, outcome)
    failed = any(c["status"] == "failed" for c in tool_calls)
    if failed:
        return "✕", "ERRORED"
    if tool_calls or traces:
        return "—", "INCOMPLETE"
    return "○", "NO ACTIVITY"


def _short_ts(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %d  %H:%M")
    except (ValueError, TypeError):
        return ""


def main() -> None:
    st.markdown("### Audit Console")
    st.caption("Sessions newest first. Expand any row for full trace.")

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

    for sess in reversed(sessions):
        sid   = sess["session_id"]
        email = sess.get("customer_email") or "no email"
        ts    = _short_ts(sess.get("created_at", ""))

        detail, _ = fetch_session_detail(sid)
        decs       = (detail or {}).get("final_decisions", [])
        tool_calls = (detail or {}).get("tool_calls", [])
        traces     = (detail or {}).get("traces", [])
        outcome    = decs[-1]["decision_type"] if decs else ""
        icon, label_txt = _session_status(outcome, tool_calls, traces)
        ts_part    = f"  ·  {ts}" if ts else ""

        row_label = f"{icon}  {label_txt}  ·  {email}  ·  #{sid[-8:]}{ts_part}"

        with st.expander(row_label, expanded=False):
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

    st.markdown(
        f'<div class="metric-grid">'
        f'<div class="metric"><div class="k">Traces</div><div class="v">{len(traces)}</div></div>'
        f'<div class="metric"><div class="k">Tools</div><div class="v">{len(tool_calls)}</div></div>'
        f'<div class="metric"><div class="k">Decisions</div><div class="v">{len(final_decisions)}</div></div>'
        f'<div class="metric{"  alert" if failed else ""}"><div class="k">Failed</div><div class="v">{len(failed)}</div></div>'
        f'<div class="metric"><div class="k">Latency</div><div class="v">{total_lat} ms</div></div>'
        f'<div class="metric"><div class="k">Tokens</div><div class="v">{total_tok}</div></div>'
        f'<div class="metric"><div class="k">Cost</div><div class="v">{_cost(total_cost or None)}</div></div>'
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
        cost  = _cost(trace.get("estimated_cost_usd"))
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
