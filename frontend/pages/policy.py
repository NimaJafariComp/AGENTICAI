"""
Policy page — human-readable refund policy with machine-readable rule summary
and a callout explaining server-side enforcement.
"""
from __future__ import annotations

import streamlit as st

from frontend.shared import fetch_policy, render_json_code


def main() -> None:
    st.markdown("### Refund Policy")
    st.markdown(
        '<p style="font-size:0.88rem;color:var(--muted);margin-bottom:1rem">'
        "The governing rules the policy engine enforces. The LLM explains decisions — "
        "it cannot override them."
        "</p>",
        unsafe_allow_html=True,
    )

    policy, err = fetch_policy()
    if err:
        st.error(f"Could not load policy: {err}")
        return

    meta = policy.get("metadata", {})

    # Machine-readable rule summary
    st.markdown('<div class="panel-label">Rule summary</div>', unsafe_allow_html=True)

    rules = [
        ("return_window",        f"{meta.get('return_window_days', '—')} days",          "Requests older than this are automatically denied"),
        ("final_sale",           "No returns",                                             "Items flagged final_sale are never eligible regardless of window"),
        ("escalation_threshold", f"${meta.get('human_escalation_amount', '—')}",          "Orders above this amount require human approval"),
        ("policy_version",       meta.get("policy_version", "—"),                         "Loaded at startup — changes require backend restart"),
        ("policy_name",          meta.get("policy_name", "—"),                            ""),
        ("decision_id",          "Required for terminal actions",                          "Issued by check_refund_eligibility; enforced by the tool executor"),
        ("injection_handling",   "Escalate on suspicious override claims",                 "Detected via policy engine heuristics, not LLM judgment"),
    ]

    for key, value, note in rules:
        note_html = f'<span class="rule-note">{note}</span>' if note else ""
        st.markdown(
            f"""
            <div class="rule-row">
              <span class="rule-key">{key}</span>
              <span class="rule-val">{value}</span>
              {note_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Human-readable policy body
    markdown_body = policy.get("markdown_body")
    if markdown_body:
        st.markdown('<div class="panel-label">Full policy text</div>', unsafe_allow_html=True)
        with st.expander("Read full policy", expanded=False):
            st.markdown(markdown_body)
    else:
        st.markdown('<div class="panel-label">Full policy</div>', unsafe_allow_html=True)
        with st.expander("Raw policy object", expanded=False):
            render_json_code(policy)
