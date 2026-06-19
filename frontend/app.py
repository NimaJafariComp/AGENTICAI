from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st

from frontend.shared import (
    BACKEND_BASE_URL,
    SK,
    ensure_state,
    fetch_health,
    inject_styles,
)
from frontend.pages import audit_console, policy as policy_page, support_desk

st.set_page_config(
    page_title="Refund Support Console",
    page_icon="🧾",
    layout="wide",
)

ensure_state()
inject_styles(st.session_state.get(SK.THEME_MODE, "Light"))

# ── Sidebar: brand + status + theme (rendered before pg.run so it appears first) ──

_PAGES = [
    st.Page(support_desk.main,  title="Support Desk",  icon="💬", url_path="desk",   default=True),
    st.Page(audit_console.main, title="Audit Console", icon="🔍", url_path="audit"),
    st.Page(policy_page.main,   title="Policy",        icon="📋", url_path="policy"),
]

health, _ = fetch_health()

provider_name = "—"
fallback      = False
model_name    = "—"
backend_ok    = False

if health:
    backend_ok    = str(health.get("status", "")).lower() in {"ok", "healthy", "up"}
    provider_info = health.get("provider", {})
    fallback      = bool(provider_info.get("fallback_used"))
    provider_name = provider_info.get("active_provider", "—")
    model_name    = provider_info.get("model_name", "—")

with st.sidebar:
    st.markdown(
        '<div class="sidebar-brand">🧾 Refund Console</div>'
        '<div class="sidebar-tagline">Internal support operations</div>',
        unsafe_allow_html=True,
    )

    b_cls = "ok"   if backend_ok else "warn"
    b_txt = "ok"   if backend_ok else "degraded"
    p_cls = "warn" if fallback   else "ok"
    p_txt = f"{provider_name} ⚠ fallback" if fallback else provider_name

    st.markdown(
        f"""
        <div class="status-block">
          <div class="status-row"><span class="status-k">backend</span>
            <span class="{b_cls}">● {b_txt}</span></div>
          <div class="status-row"><span class="status-k">provider</span>
            <span class="{p_cls}">● {p_txt}</span></div>
          <div class="status-row"><span class="status-k">model</span>
            <span>{model_name}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if fallback:
        reason = health.get("provider", {}).get("fallback_reason") or "Using mock provider."
        st.markdown(
            f'<p style="font-size:0.73rem;color:var(--escalate);margin:0.3rem 0 0">'
            f'⚠ {reason}</p>',
            unsafe_allow_html=True,
        )

    st.divider()

    current_mode = st.session_state.get(SK.THEME_MODE, "Light")
    new_mode     = "Dark" if current_mode == "Light" else "Light"
    if st.button(
        f"{'☀' if current_mode == 'Dark' else '🌙'}  {new_mode} mode",
        key="theme_toggle",
        use_container_width=True,
    ):
        st.session_state[SK.THEME_MODE] = new_mode
        st.rerun()

# ── Navigation (sidebar nav is the standard Streamlit pattern) ─────────────────

pg = st.navigation(_PAGES)

if not backend_ok and health is None:
    st.error(
        f"Backend unreachable at `{BACKEND_BASE_URL}`. Run `make dev`.",
        icon="🔴",
    )
    st.stop()

pg.run()
