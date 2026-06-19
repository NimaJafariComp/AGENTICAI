"""Audit Console — sessions listed newest-first, each expandable for full trace."""
from __future__ import annotations

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
)


def main() -> None:
    st.markdown("### Audit Console")
    st.caption("Sessions newest first — expand any row for full trace.")

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

        detail, _ = fetch_session_detail(sid)
        decs      = (detail or {}).get("final_decisions", [])
        dt        = decs[-1]["decision_type"] if decs else ""
        cls       = dt.lower() if dt else ""
        chip      = f' <span class="chip chip-{cls}">{dt}</span>' if dt else ""

        tool_calls = (detail or {}).get("tool_calls", [])
        traces     = (detail or {}).get("traces", [])
        tc_count   = len(tool_calls)
        lat        = sum((t.get("latency_ms") or 0) for t in traces)
        failed     = sum(1 for c in tool_calls if c["status"] == "failed")
        fail_tag   = f" · **{failed} failed**" if failed else ""

        label = (
            f"`{sid[-12:]}` · {email}{chip}  "
            f"<span style='font-size:0.78rem;color:var(--faint)'>"
            f"{tc_count} tools · {lat} ms{fail_tag}</span>"
        )

        with st.expander(f"{sid[-12:]}  {email}  {dt}", expanded=False):
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

    tl_tab, tc_tab, raw_tab = st.tabs(["Timeline", "Tool calls", "Raw JSON"])

    with tl_tab:
        _render_timeline(traces)
    with tc_tab:
        _render_tool_calls(tool_calls)
    with raw_tab:
        st.json(detail, expanded=True)


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
            st.json(trace["payload"])


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
                st.json(call["tool_input"], expanded=True)
            with c2:
                st.markdown("**Output**")
                st.json(call.get("tool_output") or {}, expanded=True)
