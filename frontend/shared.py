"""
Shared state, HTTP, cache decorators, design tokens, and CSS for all pages.
"""
from __future__ import annotations

import json
import os
import queue as _queue
import threading
from datetime import datetime
from typing import Any

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")

DECISION_COPY: dict[str, tuple[str, str]] = {
    "APPROVE":  ("approve",  "Approved"),
    "DENY":     ("deny",     "Denied"),
    "ESCALATE": ("escalate", "Escalated"),
}

TOOL_LABELS: dict[str, str] = {
    "lookup_customer":          "Lookup customer",
    "lookup_order":             "Lookup order",
    "get_refund_policy":        "Read refund policy",
    "approve_refund":           "Approve refund",
    "deny_refund":              "Deny refund",
    "escalate_refund":          "Escalate refund",
    "check_refund_eligibility": "Eligibility check",
}


# ── Session state keys ────────────────────────────────────────────────────────

class SK:
    CHAT_SESSION_ID = "chat_session_id"
    CHAT_MESSAGES   = "chat_messages"
    CHAT_DRAFT      = "chat_draft"
    VOICE_STATE     = "voice_state"   # idle | recording | transcribing | ready
    VOICE_AUDIO     = "voice_audio"
    ACTIVE_SID      = "active_session_sid"
    CASE_INTEL      = "case_intel"
    PROCESSING      = "processing"        # True while background POST is in flight
    RESULT_QUEUE    = "result_queue"      # queue.Queue holding (result, error) when done
    THEME_MODE      = "theme_mode"
    INJECTED_THEME  = "_injected_theme"


def ensure_state() -> None:
    st.session_state.setdefault(SK.CHAT_SESSION_ID, None)
    st.session_state.setdefault(SK.CHAT_MESSAGES, [])
    st.session_state.setdefault(SK.CHAT_DRAFT, "")
    st.session_state.setdefault(SK.VOICE_STATE, "idle")
    st.session_state.setdefault(SK.VOICE_AUDIO, None)
    st.session_state.setdefault(SK.ACTIVE_SID, None)
    st.session_state.setdefault(SK.CASE_INTEL, None)
    st.session_state.setdefault(SK.PROCESSING, False)
    st.session_state.setdefault(SK.RESULT_QUEUE, None)
    st.session_state.setdefault(SK.THEME_MODE, "Light")
    st.session_state.setdefault(SK.INJECTED_THEME, None)


def reset_session() -> None:
    ensure_state()

    st.session_state[SK.CHAT_SESSION_ID] = None
    st.session_state[SK.CHAT_MESSAGES] = []
    st.session_state[SK.CHAT_DRAFT] = ""
    st.session_state[SK.VOICE_STATE] = "idle"
    st.session_state[SK.VOICE_AUDIO] = None
    st.session_state[SK.ACTIVE_SID] = None
    st.session_state[SK.CASE_INTEL] = None
    st.session_state[SK.PROCESSING] = False
    st.session_state[SK.RESULT_QUEUE] = None
    fetch_sessions.clear()
    fetch_session_detail.clear()


def ensure_chat_session() -> str:
    ensure_state()

    if st.session_state[SK.CHAT_SESSION_ID]:
        return st.session_state[SK.CHAT_SESSION_ID]
    session = api_post("/api/chat/sessions", {"customer_email": None})
    sid = session["session_id"]
    st.session_state[SK.CHAT_SESSION_ID] = sid
    st.session_state[SK.ACTIVE_SID] = sid
    return sid


# ── HTTP helpers ──────────────────────────────────────────────────────────────

@st.cache_resource
def _http_client() -> httpx.Client:
    return httpx.Client(timeout=30.0)


def api_get(path: str) -> Any:
    r = _http_client().get(f"{BACKEND_BASE_URL}{path}")
    r.raise_for_status()
    return r.json()


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = _http_client().post(f"{BACKEND_BASE_URL}{path}", json=payload)
    r.raise_for_status()
    return r.json()


def _err(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            d = exc.response.json().get("detail")
            if d:
                return str(d)
        except Exception:  # noqa: BLE001
            pass
    return str(exc)


def safe_get(path: str) -> tuple[Any, str | None]:
    try:
        return api_get(path), None
    except Exception as e:  # noqa: BLE001
        return None, _err(e)


# ── Cached API calls ──────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def fetch_health() -> tuple[Any, str | None]:
    return safe_get("/health")


@st.cache_data(ttl=120)
def fetch_policy() -> tuple[Any, str | None]:
    return safe_get("/api/policy")


@st.cache_data(ttl=5)
def fetch_sessions() -> tuple[Any, str | None]:
    return safe_get("/api/admin/sessions")


@st.cache_data(ttl=3)
def fetch_session_detail(sid: str) -> tuple[Any, str | None]:
    return safe_get(f"/api/chat/{sid}")


def fetch_session_detail_live(sid: str) -> tuple[Any, str | None]:
    """Uncached; called during active request polling to see tool calls as they land."""
    return safe_get(f"/api/chat/{sid}")


# ── Background send ───────────────────────────────────────────────────────────

def start_send(session_id: str, message: str) -> _queue.Queue:
    """
    Dispatch the chat POST to a daemon thread. Returns the queue into which
    (result, error) will be placed when the thread finishes.
    Thread uses its own httpx.Client so it doesn't touch the cached shared client.
    """
    result_q: _queue.Queue = _queue.Queue()

    def _worker() -> None:
        try:
            with httpx.Client(timeout=90.0) as client:
                r = client.post(
                    f"{BACKEND_BASE_URL}/api/chat/{session_id}/messages",
                    json={"message": message},
                )
                r.raise_for_status()
                result_q.put((r.json(), None))
        except Exception as exc:  # noqa: BLE001
            result_q.put((None, _err(exc)))

    threading.Thread(target=_worker, daemon=True).start()
    return result_q


# ── Case intel extraction ─────────────────────────────────────────────────────

def extract_case_intel(detail: dict[str, Any]) -> dict[str, Any]:
    tool_calls       = detail.get("tool_calls", [])
    final_decisions  = detail.get("final_decisions", [])

    def _first(name: str) -> dict[str, Any] | None:
        return next(
            (c for c in tool_calls if c["tool_name"] == name and c.get("tool_output")),
            None,
        )

    c_call = _first("lookup_customer")
    o_call = _first("lookup_order")
    e_call = _first("check_refund_eligibility")

    customer = c_call["tool_output"] if c_call and isinstance(c_call.get("tool_output"), dict) else None
    order    = o_call["tool_output"] if o_call and isinstance(o_call.get("tool_output"), dict) else None

    eligibility  = None
    reason_codes: list[str] = []
    if e_call and isinstance(e_call.get("tool_output"), dict):
        eligibility  = e_call["tool_output"]
        reason_codes = eligibility.get("reason_codes") or []

    decision = final_decisions[-1] if final_decisions else None
    if not reason_codes and decision:
        reason_codes = decision.get("reason_codes") or []

    # Collapse repeated invocations of the same tool into one row, preserving
    # first-seen order. A tool can run many times across follow-up turns; the
    # panel shows each tool once with an xN counter and an aggregated status.
    agg: dict[str, dict[str, Any]] = {}
    for c in tool_calls:
        name  = c["tool_name"]
        entry = agg.get(name)
        if entry is None:
            entry = agg[name] = {
                "name":     name,
                "label":    TOOL_LABELS.get(name, _humanize(name)),
                "count":    0,
                "statuses": [],
            }
        entry["count"] += 1
        entry["statuses"].append(c["status"])

    def _roll_up(statuses: list[str]) -> str:
        normalized = ["succeeded" if status == "completed" else status for status in statuses]
        if "succeeded" in normalized:
            return "succeeded"
        if "failed" in normalized:
            return "failed"
        return normalized[-1] if normalized else "pending"

    tool_progress = [
        {
            "name":   e["name"],
            "label":  e["label"],
            "status": _roll_up(e["statuses"]),
            "count":  e["count"],
        }
        for e in agg.values()
    ]

    return {
        "customer":      customer,
        "order":         order,
        "eligibility":   eligibility,
        "decision":      decision,
        "reason_codes":  reason_codes,
        "tool_progress": tool_progress,
    }


# ── Design tokens ─────────────────────────────────────────────────────────────


def inject_styles(mode: str) -> None:
    if mode == "Dark":
        _inject_dark()
    else:
        _inject_light()


# ── shared structural CSS (layout only, no colors) ────────────────────────────

_STRUCTURAL = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family:"Inter",system-ui,sans-serif !important; }
[data-testid="stHeader"] { height:0 !important; min-height:0 !important; padding:0 !important; overflow:visible !important; background:transparent !important; }
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stAppDeployButton"],
[data-testid="stMainMenuButton"] { display:none !important; }
[data-testid="stExpandSidebarButton"] { display:flex !important; visibility:visible !important; position:fixed !important; top:0.4rem !important; left:0.4rem !important; z-index:999999 !important; }
.block-container {
  padding-top:2.6rem !important; padding-left:1.2rem !important;
  padding-right:1.2rem !important; max-width:100% !important;
}
[data-testid="stSidebar"] > div { padding:1rem !important; }
section[data-testid="stSidebar"] > div { padding-top:0.75rem !important; }
[data-testid="stSidebarNav"] { padding-top:0 !important; margin-top:0 !important; }
[data-testid="stSidebarContent"] { padding-top:0.75rem !important; }
[data-testid="stSidebarContent"] > div:first-child { padding-top:0 !important; margin-top:0 !important; }
[data-testid="stSidebarNav"] a,
[data-testid="stSidebarNav"] span { font-size:0.9rem !important; font-family:"Inter",system-ui,sans-serif !important; }
[data-testid="stSidebarNav"] [aria-selected="true"] a,
[data-testid="stSidebarNav"] [aria-selected="true"] span { font-weight:600 !important; }

.sidebar-brand  { font-size:1rem; font-weight:600; margin-bottom:0.1rem; }
.sidebar-tagline { font-size:0.75rem; margin-bottom:0.8rem; }
.status-block { display:flex !important; flex-direction:column !important; gap:0.3rem; margin-bottom:0.5rem; }
.status-row   { display:flex !important; align-items:center !important; gap:0.5rem; font-size:0.8rem; }
.status-k { font-family:"JetBrains Mono",monospace !important; font-size:0.62rem !important; text-transform:uppercase !important; letter-spacing:0.06em; width:4.5rem; flex-shrink:0; }

.panel-label { font-family:"JetBrains Mono",monospace; font-size:0.66rem; font-weight:600; letter-spacing:0.1em; text-transform:uppercase; margin:0.1rem 0 0.55rem; }


.session-card     { padding:0.35rem 0 !important; margin-bottom:0.15rem; }
.session-card-top { display:flex !important; align-items:center !important; gap:0.4rem; margin-bottom:0.1rem; }
.s-id   { font-family:"JetBrains Mono",monospace !important; font-size:0.68rem !important; }
.s-email { font-size:0.8rem !important; white-space:nowrap !important; overflow:hidden !important; text-overflow:ellipsis !important; display:block !important; }
[class*="st-key-show_more_recent_sessions"] {
  display:flex !important; justify-content:center !important;
  margin:0.25rem 0 0.1rem !important;
}
[class*="st-key-show_more_recent_sessions"] > div,
[class*="st-key-show_more_recent_sessions"] [data-testid="stElementContainer"] {
  width:auto !important;
}
[class*="st-key-show_more_recent_sessions"] button {
  justify-content:center !important; gap:0.45rem !important;
  width:auto !important; min-width:0 !important;
  border-radius:999px !important;
  padding:0.3rem 1.1rem !important; font-size:0.78rem !important;
  background:transparent !important; box-shadow:none !important;
}
[class*="st-key-show_more_recent_sessions"] button::before {
  content:"" !important; display:inline-block !important;
  width:0.38rem !important; height:0.38rem !important;
  border-right:1.5px solid currentColor !important;
  border-bottom:1.5px solid currentColor !important;
  transform:rotate(45deg) translateY(-0.06rem) !important;
  flex:0 0 auto !important;
}

.chip { display:inline-block !important; font-family:"JetBrains Mono",monospace !important; font-size:0.62rem !important; font-weight:500 !important; letter-spacing:0.06em; padding:0.1rem 0.4rem !important; border-radius:4px !important; white-space:nowrap !important; }

[data-testid="stChatMessage"]        { padding:0.05rem 0 !important; }
[data-testid="stChatMessageContent"] { font-size:0.93rem; line-height:1.6; }

/* ── Fixed app-shell (Support Desk only): no page scroll, internal scroll only ── */
[data-testid="stAppViewContainer"]:has(#_desk_marker),
[data-testid="stMain"]:has(#_desk_marker) {
  height:100vh !important; height:100dvh !important; max-height:100dvh !important; overflow:hidden !important;
}
[data-testid="stMainBlockContainer"]:has(#_desk_marker),
[data-testid="stMain"]:has(#_desk_marker) .block-container:has(#_desk_marker) {
  height:100vh !important; height:100dvh !important; max-height:100dvh !important; overflow:hidden !important;
  display:flex !important; flex-direction:column !important;
  padding-top:2.6rem !important; padding-bottom:1.2rem !important;
}
[data-testid="stMainBlockContainer"]:has(#_desk_marker) > [data-testid="stVerticalBlock"],
[data-testid="stMain"]:has(#_desk_marker) .block-container:has(#_desk_marker) > [data-testid="stVerticalBlock"] {
  flex:1 1 auto !important; min-height:0 !important; display:flex !important; flex-direction:column !important;
}
/* Pass the height through EVERY wrapper that nests the column row (Streamlit 1.58 adds
   stLayoutWrapper between blocks; without this it sizes to content and grows the page
   instead of letting the left rail scroll internally). */
[data-testid="stVerticalBlock"]:has([data-testid="stHorizontalBlock"]:has(#_desk_marker)),
[data-testid="stLayoutWrapper"]:has(#_desk_marker) {
  flex:1 1 auto !important; min-height:0 !important; display:flex !important; flex-direction:column !important;
}
/* The column row fills remaining height; all 3 columns stretch to it */
[data-testid="stHorizontalBlock"]:has(#_desk_marker) {
  flex:1 1 auto !important; min-height:0 !important; align-items:stretch !important;
}
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"] {
  height:100% !important; min-height:0 !important; align-self:stretch !important;
}
/* Left rail scrolls independently; center and right stay fixed */
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"]:has(#_desk_marker) {
  height:calc(100dvh - 3.8rem) !important; max-height:calc(100dvh - 3.8rem) !important; min-height:0 !important;
  overflow-y:auto !important; overflow-x:hidden !important; overscroll-behavior:contain !important;
  scrollbar-gutter:stable !important; scroll-padding-bottom:3rem !important;
}
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"]:has(#_center_marker) { overflow:hidden !important; }
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"]:last-child           { overflow:hidden !important; }
[class*="st-key-left_scroll_rail"] {
  padding:0 0.55rem 3rem 0 !important;
}
[data-testid="stColumn"]:has(#_desk_marker) [data-testid="stVerticalBlock"]:has(#_recent_sessions_marker) {
  padding-bottom:0.5rem !important;
}

/* ── Main 3-column layout: vertical dividers between the rails ── */
[data-testid="stHorizontalBlock"]:has(#_desk_marker) { gap:0 !important; }
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"] { padding:0 1.5rem !important; }
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"]:first-child { padding-left:0.25rem !important; }
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"]:last-child  { padding-right:0.25rem !important; }
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"] + [data-testid="stColumn"] { border-left:1px solid var(--border-layout); }
/* Right column reads as a clean full-height inspector (matches card surface) */
[data-testid="stHorizontalBlock"]:has(#_desk_marker) > [data-testid="stColumn"]:last-child {
  background:var(--surface) !important; border-radius:0 !important; padding:0.25rem 1.5rem 1.5rem !important;
}

/* ── Center "command console": header → body card → composer card ── */
/* Fill the row height so the body grows and the composer pins to the bottom.
   Use descendant :has so it works regardless of Streamlit's wrapper nesting. */
[data-testid="stColumn"]:has(#_center_marker) {
  display:flex !important; flex-direction:column !important;
  height:calc(100dvh - 3.8rem) !important; max-height:calc(100dvh - 3.8rem) !important; min-height:0 !important;
  overflow:hidden !important;
}
[data-testid="stColumn"]:has(#_center_marker) > div {
  flex:1 1 auto !important; height:100% !important; min-height:0 !important; display:flex !important; flex-direction:column !important;
}
[data-testid="stColumn"]:has(#_center_marker) > div > [data-testid="stVerticalBlock"] {
  flex:1 1 auto !important; height:100% !important; min-height:0 !important;
  display:grid !important; grid-template-rows:auto minmax(0, 1fr) auto 4em !important;
  align-content:stretch !important;
}
[data-testid="stColumn"]:has(#_center_marker) [data-testid="stVerticalBlock"]:has([class*="st-key-chat_card"]) {
  min-height:0 !important;
}
[data-testid="stColumn"]:has(#_center_marker) [data-testid="stElementContainer"]:has([class*="st-key-chat_card"]),
[data-testid="stColumn"]:has(#_center_marker) [data-testid="stLayoutWrapper"]:has([class*="st-key-chat_card"]) {
  min-height:0 !important; height:100% !important; overflow:hidden !important;
}
[data-testid="stColumn"]:has(#_center_marker) [data-testid="stElementContainer"]:has([class*="st-key-composer_card"]),
[data-testid="stColumn"]:has(#_center_marker) [data-testid="stLayoutWrapper"]:has([class*="st-key-composer_card"]) {
  align-self:end !important; min-height:0 !important; margin-bottom:4em !important;
}
[class*="st-key-chat_card"] {
  min-height:0 !important; height:100% !important; max-height:100% !important;
  overflow-y:auto !important; overflow-x:hidden !important;
}
.console-header { display:flex; flex-direction:column; gap:0.1rem; padding:0.1rem 0.2rem 0.7rem; }
.console-title { font-size:0.98rem; font-weight:600; color:var(--ink); }
.console-sub   { font-size:0.78rem; color:var(--muted); }

/* Fixed-height chat container: scroll to bottom anchor on new messages */
[class*="st-key-chat_card"] { scroll-behavior:smooth; }
#chat-bottom { height:1px; }
/* Conversation surface card (results / transcript area) */
[class*="st-key-chat_card"] {
  border:1px solid var(--border-card) !important; border-radius:12px !important;
  background:var(--surface) !important; padding:0.4rem 0.95rem !important;
}
/* Push chat messages to bottom so short conversations look like iMessage */
[class*="st-key-chat_card"] [data-testid="stVerticalBlock"] {
  min-height:100% !important; display:flex !important; flex-direction:column !important; justify-content:flex-start !important;
}

/* Composer card anchored under the results area */
[class*="st-key-composer_card"] {
  border:1px solid var(--border-card) !important; border-radius:12px !important;
  background:var(--surface) !important; padding:0.7rem 0.85rem 0.6rem !important;
  margin-top:0.6rem !important; flex:0 0 auto !important; align-self:stretch !important;
}

/* ── Audit console: two independent work columns ── */
[data-testid="stAppViewContainer"]:has(#_audit_marker),
[data-testid="stMain"]:has(#_audit_marker) {
  height:100vh !important; height:100dvh !important; max-height:100dvh !important; overflow:hidden !important;
}
[data-testid="stMainBlockContainer"]:has(#_audit_marker),
[data-testid="stMain"]:has(#_audit_marker) .block-container:has(#_audit_marker) {
  height:100vh !important; height:100dvh !important; max-height:100dvh !important; overflow:hidden !important;
  display:flex !important; flex-direction:column !important;
  padding-top:1.2rem !important; padding-bottom:0.8rem !important;
}
[data-testid="stMainBlockContainer"]:has(#_audit_marker) > [data-testid="stVerticalBlock"],
[data-testid="stMain"]:has(#_audit_marker) .block-container:has(#_audit_marker) > [data-testid="stVerticalBlock"] {
  flex:1 1 auto !important; min-height:0 !important; display:flex !important; flex-direction:column !important;
  gap:0.75rem !important;
}
[data-testid="stVerticalBlock"]:has([data-testid="stHorizontalBlock"]:has(#_audit_list_marker)),
[data-testid="stLayoutWrapper"]:has(#_audit_list_marker) {
  flex:1 1 auto !important; min-height:0 !important; display:flex !important; flex-direction:column !important;
}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) {
  flex:1 1 auto !important; min-height:0 !important; gap:0 !important; align-items:stretch !important;
}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"] {
  height:100% !important; min-height:0 !important; align-self:stretch !important;
}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"]:has(#_audit_list_marker) {
  height:calc(100dvh - 9.6rem) !important; max-height:calc(100dvh - 9.6rem) !important; min-height:0 !important;
  overflow-y:auto !important; overflow-x:hidden !important; overscroll-behavior:contain !important;
  scrollbar-gutter:stable !important; scroll-padding-bottom:5rem !important;
}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"]:has(#_audit_list_marker) {
  padding:0 0.75rem 0 0.25rem !important;
}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"]:has(#_audit_detail_marker) {
  position:relative !important; top:-4rem !important;
  height:calc(100dvh - 7.4rem) !important; max-height:calc(100dvh - 7.4rem) !important; min-height:0 !important;
  overflow-y:auto !important; overflow-x:hidden !important; overscroll-behavior:contain !important;
  scrollbar-gutter:stable !important; scroll-padding-bottom:5rem !important;
  padding:0 1.25rem !important;
}
[data-testid="stColumn"]:has(#_audit_list_marker) [data-testid="stVerticalBlock"]:has([class*="st-key-audit_session_card_"]),
[data-testid="stColumn"]:has(#_audit_detail_marker) [data-testid="stVerticalBlock"]:has(#_audit_detail_marker) {
  padding-bottom:5rem !important;
}
[data-testid="stColumn"]:has(#_audit_detail_marker) [data-testid="stElementContainer"]:has(#_audit_detail_marker),
[data-testid="stColumn"]:has(#_audit_detail_marker) [data-testid="stElementContainer"]:has(#_audit_detail_marker) + [data-testid="stElementContainer"] {
  margin-top:0 !important; padding-top:0 !important;
}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"] + [data-testid="stColumn"] {
  border-left:1px solid var(--border-layout) !important;
}

[class*="st-key-audit_session_card_"] {
  margin-bottom:0.35rem !important;
}
[class*="st-key-audit_session_card_"] .stButton button,
[class*="st-key-audit_session_card_"] [data-testid^="stBaseButton"] {
  min-height:3.15rem !important; justify-content:flex-start !important; text-align:left !important;
  white-space:normal !important; line-height:1.3 !important; border-left-width:3px !important;
  padding:0.48rem 0.65rem !important; box-shadow:none !important;
}
[class*="st-key-audit_session_card_approve_"] .stButton button,
[class*="st-key-audit_session_card_approve_"] [data-testid^="stBaseButton"] { border-left-color:var(--approve) !important; }
[class*="st-key-audit_session_card_deny_"] .stButton button,
[class*="st-key-audit_session_card_deny_"] [data-testid^="stBaseButton"] { border-left-color:var(--deny) !important; }
[class*="st-key-audit_session_card_escalate_"] .stButton button,
[class*="st-key-audit_session_card_escalate_"] [data-testid^="stBaseButton"] { border-left-color:var(--escalate) !important; }
[class*="st-key-audit_session_card_errored_"] .stButton button,
[class*="st-key-audit_session_card_errored_"] [data-testid^="stBaseButton"] { border-left-color:var(--deny) !important; }
[class*="st-key-audit_session_card_incomplete_"] .stButton button,
[class*="st-key-audit_session_card_incomplete_"] [data-testid^="stBaseButton"] { border-left-color:var(--brand) !important; }
[class*="st-key-audit_session_card_no-activity_"] .stButton button,
[class*="st-key-audit_session_card_no-activity_"] [data-testid^="stBaseButton"] { border-left-color:var(--faint) !important; }

/* Centered empty state inside the conversation card */
.chat-empty { display:flex; flex:1 1 auto; flex-direction:column; align-items:center; justify-content:center; text-align:center; gap:0.5rem; min-height:260px; width:100%; }
.chat-empty-icon  { font-size:1.9rem; opacity:0.5; }
.chat-empty-title { font-size:0.98rem; font-weight:600; margin:0; color:var(--ink); }
.chat-empty-sub   { font-size:0.83rem; margin:0; color:var(--muted); max-width:22rem; line-height:1.5; }

/* ── Scenario cards: clickable title + verdict chip + verdict-coded accent stripe ── */
/* Targeted via st.container(key="scncard_<verdict>_<id>") → .st-key-scncard_* class */
[class*="st-key-scncard_"] {
  border:1px solid var(--border-card) !important;
  border-left:3px solid var(--faint) !important;
  border-radius:10px !important;
  background:var(--surface) !important;
  flex:0 0 auto !important;
  padding:0.15rem 0 !important;
  transition:border-color 0.14s ease, background 0.14s ease, transform 0.14s ease, box-shadow 0.14s ease;
}
[class*="st-key-scncard_"]:hover {
  border-color:var(--border-strong) !important; background:var(--surface-2) !important;
  transform:translateY(-2px) !important; box-shadow:0 4px 14px rgba(0,0,0,0.18) !important;
}
@media (prefers-reduced-motion: reduce) {
  [class*="st-key-scncard_"], [class*="st-key-scncard_"]:hover { transform:none !important; transition:none !important; }
}
/* Verdict-coded left stripe (encodes the expected decision) */
[class*="st-key-scncard_approve_"]  { border-left-color:var(--approve) !important; }
[class*="st-key-scncard_deny_"]     { border-left-color:var(--deny) !important; }
[class*="st-key-scncard_escalate_"] { border-left-color:var(--escalate) !important; }
[class*="st-key-scncard_"] [data-testid="stElementContainer"] { margin:0 !important; }
/* Title acts as the card's primary action; borderless, left-aligned */
[class*="st-key-scncard_"] .stButton button,
[class*="st-key-scncard_"] [data-testid^="stBaseButton"] {
  border:0 !important; border-color:transparent !important; box-shadow:none !important;
  background:transparent !important; text-align:left !important;
  justify-content:flex-start !important; padding:0.5rem 0.85rem !important;
  font-weight:600 !important; font-size:0.9rem !important; line-height:1.3 !important; min-height:0 !important;
}
[class*="st-key-scncard_"] .stButton button:hover,
[class*="st-key-scncard_"] [data-testid^="stBaseButton"]:hover,
[class*="st-key-scncard_"] .stButton button:focus-visible,
[class*="st-key-scncard_"] [data-testid^="stBaseButton"]:focus-visible {
  border:0 !important; border-color:transparent !important; box-shadow:none !important;
  background:transparent !important; filter:none !important; outline:none !important;
}

/* ── Right inspector empty state with skeleton sections ── */
.inspector-empty { padding:0.2rem 0 0.4rem; }
.inspector-empty-title { font-size:0.92rem; font-weight:600; color:var(--ink); margin:0 0 0.15rem; }
.inspector-empty-sub   { font-size:0.8rem; color:var(--muted); margin:0 0 0.75rem; }
.inspector-skeleton { display:flex; flex-direction:column; gap:0.5rem; }
.skeleton-row { display:flex; align-items:center; gap:0.55rem; font-size:0.82rem; color:var(--muted);
  padding:0.5rem 0.65rem; border:1px dashed var(--border-card); border-radius:8px; }
.skeleton-dot { width:7px; height:7px; border-radius:50%; background:var(--faint); flex-shrink:0; }

.seal { display:inline-flex; align-items:center; gap:0.35rem; margin-top:0.45rem; padding:0.2rem 0.5rem; border-radius:5px; border-width:1.5px; border-style:solid; font-family:"JetBrains Mono",monospace; font-size:0.67rem; font-weight:500; letter-spacing:0.07em; text-transform:uppercase; }
.seal::before { content:""; width:6px; height:6px; border-radius:2px; }

.empty-state { border-width:1px; border-style:dashed; border-radius:12px; padding:1.5rem 1.25rem; text-align:center; font-size:0.9rem; margin:0.2rem 0 0.45rem; }
.es-title    { font-size:0.98rem; font-weight:600; margin:0 0 0.3rem; }

.intel-key { font-family:"JetBrains Mono",monospace; font-size:0.54rem; letter-spacing:0.08em; text-transform:uppercase; margin:0.62rem 0 0.18rem; }
.intel-key:first-child { margin-top:0.1rem; }

/* Inset data card for Customer / Order facts */
.case-fact { border-left:2px solid var(--faint); border-radius:0 5px 5px 0; padding:0.22rem 0.5rem 0.22rem 0.55rem; margin-bottom:0.5rem; }
.case-kv { display:flex; align-items:baseline; gap:0.4rem; padding:0.06rem 0; min-width:0; }
.case-kv-key { font-family:"JetBrains Mono",monospace; font-size:0.57rem; text-transform:uppercase; letter-spacing:0.06em; width:2.9rem; flex-shrink:0; }
.case-kv-val { font-size:0.8rem; font-weight:500; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.case-kv-val.dim { font-weight:400; }

.verdict-block { border-radius:9px; padding:0.42rem 0.58rem; margin:0.28rem 0 0.42rem; border-left-width:3px; border-left-style:solid; }
.verdict-type  { font-family:"JetBrains Mono",monospace; font-size:0.75rem; font-weight:600; letter-spacing:0.05em; }
.reason-code { display:inline-flex; align-items:center; max-width:100%; font-size:0.68rem; line-height:1.25; margin:0.08rem 0.18rem 0.08rem 0; padding:0.14rem 0.38rem; border-radius:999px; white-space:normal; }
.tool-row    { display:grid !important; grid-template-columns:0.82rem minmax(0, 1fr) auto; align-items:center !important; gap:0.34rem; font-size:0.68rem; margin:0.08rem 0; min-width:0; }
.tool-ok, .tool-fail, .tool-pending { flex-shrink:0; width:0.62rem; height:0.62rem; border-radius:50%; text-align:center; line-height:0.62rem; font-size:0.5rem; }
.tool-label  { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tool-status { flex-shrink:0; font-family:"JetBrains Mono",monospace !important; font-size:0.48rem !important; letter-spacing:0.05em; text-transform:uppercase; }
.tool-count  { flex-shrink:0; font-family:"JetBrains Mono",monospace !important; font-size:0.52rem !important; font-weight:500; letter-spacing:0.02em; padding:0.04rem 0.26rem; border-radius:4px; line-height:1.2; }

.metric-grid { display:grid !important; grid-template-columns:repeat(auto-fit,minmax(95px,1fr)) !important; gap:0.45rem; margin:0.3rem 0 1rem; }
.metric      { border-radius:9px !important; padding:0.55rem 0.65rem !important; border-width:1px; border-style:solid; }
.metric .k   { font-family:"JetBrains Mono",monospace !important; font-size:0.58rem !important; letter-spacing:0.07em; text-transform:uppercase !important; }
.metric .v   { font-size:1.05rem !important; font-weight:600 !important; margin-top:0.12rem; }

.audit-session-card { display:block !important; border-width:1px; border-style:solid; border-left-width:3px !important; border-radius:8px !important; padding:0.5rem 0.7rem !important; margin-bottom:0.35rem !important; }
.audit-session-card.active { display:flex !important; align-items:center !important; gap:0.5rem !important; min-height:3.15rem !important; }
.audit-session-card.active .s-email { flex:1 1 auto !important; min-width:0 !important; }
.audit-status-chip { flex:0 0 auto !important; margin-left:auto !important; }

.tl-row  { display:flex !important; align-items:baseline !important; gap:0.5rem; padding:0.2rem 0; }
.tl-dot  { font-size:0.7rem !important; flex-shrink:0; }
.tl-title { font-size:0.87rem !important; font-weight:500 !important; }
.tl-meta  { font-family:"JetBrains Mono",monospace !important; font-size:0.63rem !important; }

.policy-callout { border-radius:9px !important; padding:0.7rem 0.85rem !important; font-size:0.85rem !important; margin-bottom:1rem !important; border-width:1px; border-style:solid; }
.rule-row  { display:flex !important; align-items:baseline !important; gap:0.6rem; padding:0.32rem 0 !important; border-bottom-width:1px; border-bottom-style:solid; font-size:0.86rem; }
.rule-key  { font-family:"JetBrains Mono",monospace !important; font-size:0.7rem !important; width:9rem; flex-shrink:0; }
.rule-val  { font-weight:500 !important; }
.rule-note { font-size:0.78rem !important; }

.stButton, .stButton button, [data-testid^="stBaseButton"] { outline:none !important; box-shadow:none !important; }
.stButton button:focus, .stButton button:focus-visible,
[data-testid^="stBaseButton"]:focus, [data-testid^="stBaseButton"]:focus-visible { outline:none !important; box-shadow:none !important; }
.stButton button { border-radius:8px !important; font-weight:500 !important; font-size:0.86rem !important; font-family:"Inter",system-ui,sans-serif !important; border-width:1px; border-style:solid; }
[data-testid="stBaseButton-primary"], .stButton button[kind="primary"] { color:#ffffff !important; }
[data-testid="stBaseButton-primary"]:hover, .stButton button[kind="primary"]:hover { filter:brightness(1.07) !important; color:#ffffff !important; }
[data-testid="stBaseButton-primary"]:disabled, .stButton button[kind="primary"]:disabled { opacity:0.4 !important; filter:none !important; }

[data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input { font-size:0.92rem !important; border-width:1px; border-style:solid; }
[data-testid="stTabs"] [data-baseweb="tab"] { font-weight:500 !important; font-size:0.87rem !important; }
[data-testid="stExpander"] summary { font-size:0.85rem !important; }
[data-testid="stCaption"] p { font-size:0.8rem !important; }
hr { margin:0.6rem 0 !important; }
code { border-radius:4px !important; padding:0.1rem 0.35rem !important; font-family:"JetBrains Mono",monospace !important; font-size:0.85em !important; border-width:1px; border-style:solid; }
pre { border-radius:6px !important; padding:0.85rem 1rem !important; font-size:0.82rem !important; line-height:1.65 !important; border-width:1px; border-style:solid; overflow:auto !important; }
pre code { padding:0 !important; border:0 !important; font-size:inherit !important; line-height:inherit !important; background:transparent !important; }
[data-testid="stJson"] { border-radius:6px !important; }
[data-testid="stJson"] > div { background:transparent !important; }
"""


def _inject_dark() -> None:
    st.markdown(f"""<style>
{_STRUCTURAL}

/* ════ DARK MODE ════════════════════════════════════════════════════ */
:root {{
  --bg:#0d1117; --surface:#161b22; --surface-2:#21262d;
  --ink:#e6edf3; --muted:#8b949e; --faint:#484f58;
  --brand:#4493f8; --approve:#3fb950; --deny:#f85149; --escalate:#e3b341;
  --border:rgba(230,237,243,0.075); --border-strong:rgba(230,237,243,0.22);
  --border-layout:rgba(230,237,243,0.145); --border-card:rgba(230,237,243,0.105); --border-input:rgba(230,237,243,0.16);
}}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background:#0d1117 !important; color:#e6edf3 !important; }}
[data-testid="stSidebar"] {{ background:#161b22 !important; }}
.sidebar-brand {{ color:#e6edf3; }}
.sidebar-tagline {{ color:#8b949e; }}
.status-row span {{ color:#e6edf3 !important; }}
.status-k {{ color:#6e7681 !important; }}
.ok   {{ color:#3fb950 !important; font-weight:600 !important; }}
.warn {{ color:#e3b341 !important; font-weight:600 !important; }}
.panel-label {{ color:#6e7681; }}
.session-card {{ border-bottom:1px solid var(--border) !important; }}
.s-id   {{ color:#6e7681 !important; }}
.s-email {{ color:#e6edf3 !important; }}
.chip-approve      {{ background:rgba(63,185,80,0.10)  !important; color:#3fb950 !important; }}
.chip-deny         {{ background:rgba(248,81,73,0.10)  !important; color:#f85149 !important; }}
.chip-escalate     {{ background:rgba(227,179,65,0.10) !important; color:#e3b341 !important; }}
.chip-brand        {{ background:rgba(68,147,248,0.10) !important; color:#4493f8 !important; }}
.chip-errored      {{ background:rgba(248,81,73,0.07)  !important; color:#f85149 !important; }}
.chip-incomplete   {{ background:rgba(68,147,248,0.10) !important; color:#4493f8 !important; }}
.chip-no-activity  {{ background:rgba(72,79,88,0.20)   !important; color:#8b949e !important; }}
.seal {{ border-color:#484f58; color:#8b949e; }}
.seal::before {{ background:#484f58; }}
.seal.approve  {{ border-color:#3fb950; color:#3fb950; }}
.seal.approve::before  {{ background:#3fb950; }}
.seal.deny     {{ border-color:#f85149; color:#f85149; }}
.seal.deny::before     {{ background:#f85149; }}
.seal.escalate {{ border-color:#e3b341; color:#e3b341; }}
.seal.escalate::before {{ background:#e3b341; }}
.empty-state {{ border-color:var(--border-card); color:#8b949e; }}
.es-title {{ color:#e6edf3; }}
.skeleton-dot {{ background:#6e7681 !important; }}
.skeleton-row {{ border-color:rgba(230,237,243,0.16) !important; color:#8b949e !important; }}
.intel-key {{ color:#6e7681; }}
.case-fact {{ background:rgba(230,237,243,0.035) !important; border-left-color:#484f58 !important; }}
.case-kv-key {{ color:#6e7681 !important; }}
.case-kv-val {{ color:#e6edf3 !important; }}
.case-kv-val.dim {{ color:#8b949e !important; }}
.verdict-block          {{ border-left-color:#484f58; background:#21262d; }}
.verdict-block.approve  {{ border-left-color:#3fb950; background:rgba(63,185,80,0.10); }}
.verdict-block.deny     {{ border-left-color:#f85149; background:rgba(248,81,73,0.10); }}
.verdict-block.escalate {{ border-left-color:#e3b341; background:rgba(227,179,65,0.10); }}
.verdict-block.pending     {{ border-left-color:#484f58; background:#21262d; }}
.verdict-block.errored     {{ border-left-color:#f85149; background:rgba(248,81,73,0.07); }}
.verdict-block.incomplete  {{ border-left-color:#4493f8; background:rgba(68,147,248,0.09); }}
.verdict-block.no-activity {{ border-left-color:#484f58; background:rgba(72,79,88,0.12); }}
.verdict-type.approve    {{ color:#3fb950; }}
.verdict-type.deny       {{ color:#f85149; }}
.verdict-type.escalate   {{ color:#e3b341; }}
.verdict-type.pending    {{ color:#484f58; }}
.verdict-type.errored    {{ color:#f85149; }}
.verdict-type.incomplete {{ color:#4493f8; }}
.verdict-type.no-activity {{ color:#484f58; }}
.reason-code {{ color:#8b949e; }}
.reason-code {{ background:rgba(139,148,158,0.10); }}
.tool-row    {{ color:#e6edf3; }}
.tool-ok     {{ color:#0d1117; background:#3fb950; }}
.tool-fail   {{ color:#0d1117; background:#f85149; }}
.tool-pending {{ color:#8b949e; background:rgba(139,148,158,0.14); }}
.tool-count  {{ background:rgba(230,237,243,0.08) !important; color:#8b949e !important; }}
.metric {{ background:#161b22 !important; border-color:var(--border-card) !important; }}
.metric .k {{ color:#6e7681 !important; }}
.metric .v {{ color:#e6edf3 !important; }}
.metric.alert .v {{ color:#e3b341 !important; }}
.audit-session-card {{ border-color:var(--border-card) !important; border-left-color:#484f58 !important; background:#161b22 !important; }}
.audit-session-card.approve  {{ border-left-color:#3fb950 !important; }}
.audit-session-card.deny     {{ border-left-color:#f85149 !important; }}
.audit-session-card.escalate {{ border-left-color:#e3b341 !important; }}
.audit-session-card.errored {{ border-left-color:#f85149 !important; background:rgba(248,81,73,0.07) !important; }}
.audit-session-card.incomplete {{ border-left-color:#4493f8 !important; background:rgba(68,147,248,0.09) !important; }}
.audit-session-card.no-activity {{ border-left-color:#484f58 !important; background:rgba(72,79,88,0.12) !important; }}
.audit-session-card.active {{ border-color:var(--border-strong) !important; }}
.tl-dot   {{ color:#6e7681 !important; }}
.tl-title {{ color:#e6edf3 !important; }}
.tl-meta  {{ color:#6e7681 !important; }}
.policy-callout {{ background:rgba(68,147,248,0.10) !important; border-color:#4493f8 !important; color:#e6edf3 !important; }}
.policy-callout strong {{ color:#4493f8 !important; }}
.rule-row  {{ border-bottom-color:var(--border) !important; }}
.rule-key  {{ color:#6e7681 !important; }}
.rule-val  {{ color:#e6edf3 !important; }}
.rule-note {{ color:#8b949e !important; }}
.stButton button, [data-testid="stBaseButton-secondary"] {{ background:#161b22 !important; color:#e6edf3 !important; border-color:var(--border-input) !important; }}
.stButton button:hover, [data-testid="stBaseButton-secondary"]:hover {{ border-color:#4493f8 !important; color:#4493f8 !important; }}
.stButton button:focus-visible, [data-testid^="stBaseButton"]:focus-visible {{ box-shadow:0 0 0 2px #4493f8 !important; }}
[data-testid="stBaseButton-primary"], .stButton button[kind="primary"] {{ background:#4493f8 !important; border-color:#4493f8 !important; }}
[data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input {{ background:#0d1117 !important; color:#e6edf3 !important; border-color:rgba(230,237,243,0.26) !important; }}
[data-testid="stTextArea"] textarea::placeholder {{ color:#6e7681 !important; }}
[data-testid="stTextArea"] textarea:focus, [data-testid="stTextInput"] input:focus {{ border-color:#4493f8 !important; box-shadow:0 0 0 2px rgba(68,147,248,0.22) !important; }}
[data-baseweb="select"] > div {{ background:#161b22 !important; color:#e6edf3 !important; border-color:var(--border-input) !important; }}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ border-bottom:1px solid var(--border) !important; }}
[data-testid="stTabs"] [data-baseweb="tab"] {{ color:#8b949e !important; }}
[data-testid="stTabs"] [aria-selected="true"] {{ color:#e6edf3 !important; }}
[data-testid="stExpander"] details {{ border:1px solid var(--border-card) !important; border-radius:8px !important; }}
[data-testid="stExpander"] details > summary:focus-visible {{ outline:none !important; box-shadow:0 0 0 2px #4493f8 !important; }}
[data-testid="stExpander"] summary {{ color:#e6edf3 !important; }}
[data-testid="stCaption"] p {{ color:#8b949e !important; }}
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNav"] a:hover {{ color:#8b949e !important; }}
[data-testid="stSidebarNav"] [aria-selected="true"] span {{ color:#e6edf3 !important; }}
hr {{ border-color:var(--border) !important; }}
p  {{ color:#e6edf3; }}
code {{ background:rgba(230,237,243,0.05) !important; color:#4493f8 !important; border-color:var(--border) !important; }}
pre {{ background:#161b22 !important; color:#e6edf3 !important; border-color:var(--border) !important; }}
pre code {{ background:transparent !important; color:inherit !important; border-color:transparent !important; }}
[data-testid="stJson"] {{ background:#161b22 !important; }}
[data-testid="stJson"] span[style], [data-testid="stJson"] .cm-string,
[data-testid="stJson"] .cm-number, [data-testid="stJson"] .cm-property {{ color:#4493f8 !important; }}
[data-testid="stJson"] .cm-punctuation, [data-testid="stJson"] .cm-bracket {{ color:#8b949e !important; }}
[data-testid="stJson"] .cm-atom, [data-testid="stJson"] .cm-bool, [data-testid="stJson"] .cm-null {{ color:#e3b341 !important; background:rgba(227,179,65,0.14) !important; border-radius:4px !important; }}
[data-testid="stTabs"] [data-baseweb="tab-panel"] {{ background:#0d1117 !important; }}
[data-testid="stChatMessageContent"],
[data-testid="stChatMessageContent"] p,
[data-testid="stChatMessageContent"] li,
[data-testid="stChatMessageContent"] ul,
[data-testid="stChatMessageContent"] ol,
[data-testid="stChatMessageContent"] blockquote {{ color:#e6edf3 !important; }}
[data-testid="stChatMessageContent"] li::marker {{ color:#8b949e !important; }}
</style>""", unsafe_allow_html=True)


def _inject_light() -> None:
    st.markdown(f"""<style>
{_STRUCTURAL}

/* ════ LIGHT MODE ═══════════════════════════════════════════════════ */
:root {{
  --bg:#f3f4f6; --surface:#ffffff; --surface-2:#f9fafb;
  --ink:#111827; --muted:#6b7280; --faint:#6b7280;
  --brand:#2563eb; --approve:#059669; --deny:#dc2626; --escalate:#d97706;
  --border:rgba(148,163,184,0.36); --border-strong:rgba(100,116,139,0.62);
  --border-layout:rgba(100,116,139,0.50); --border-card:rgba(100,116,139,0.44); --border-input:rgba(100,116,139,0.56);
}}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background:#f3f4f6 !important; color:#111827 !important; }}
[data-testid="stSidebar"] {{ background:#ffffff !important; }}
.sidebar-brand {{ color:#111827; }}
.sidebar-tagline {{ color:#6b7280; }}
.status-row span {{ color:#111827 !important; }}
.status-k {{ color:#6b7280 !important; }}
.ok   {{ color:#059669 !important; font-weight:600 !important; }}
.warn {{ color:#d97706 !important; font-weight:600 !important; }}
.panel-label {{ color:#6b7280; }}
[class*="st-key-scncard_"]:hover {{ box-shadow:0 4px 14px rgba(15,23,42,0.10) !important; }}
.session-card {{ border-bottom:1px solid var(--border) !important; }}
.s-id   {{ color:#6b7280 !important; }}
.s-email {{ color:#111827 !important; }}
.chip-approve      {{ background:rgba(5,150,105,0.07)   !important; color:#059669 !important; }}
.chip-deny         {{ background:rgba(220,38,38,0.07)   !important; color:#dc2626 !important; }}
.chip-escalate     {{ background:rgba(217,119,6,0.07)   !important; color:#d97706 !important; }}
.chip-brand        {{ background:rgba(37,99,235,0.07)   !important; color:#2563eb !important; }}
.chip-errored      {{ background:rgba(220,38,38,0.06)   !important; color:#dc2626 !important; }}
.chip-incomplete   {{ background:rgba(37,99,235,0.07)   !important; color:#2563eb !important; }}
.chip-no-activity  {{ background:rgba(107,114,128,0.10) !important; color:#6b7280 !important; }}
.seal {{ border-color:#6b7280; color:#6b7280; }}
.seal::before {{ background:#6b7280; }}
.seal.approve  {{ border-color:#059669; color:#059669; }}
.seal.approve::before  {{ background:#059669; }}
.seal.deny     {{ border-color:#dc2626; color:#dc2626; }}
.seal.deny::before     {{ background:#dc2626; }}
.seal.escalate {{ border-color:#d97706; color:#d97706; }}
.seal.escalate::before {{ background:#d97706; }}
.empty-state {{ border-color:var(--border-card); color:#6b7280; }}
.es-title {{ color:#111827; }}
.intel-key {{ color:#9ca3af; }}
.case-fact {{ background:rgba(100,116,139,0.055) !important; border-left-color:#d1d5db !important; }}
.case-kv-key {{ color:#9ca3af !important; }}
.case-kv-val {{ color:#111827 !important; }}
.case-kv-val.dim {{ color:#6b7280 !important; }}
.verdict-block          {{ border-left-color:#6b7280; background:#f9fafb; }}
.verdict-block.approve  {{ border-left-color:#059669; background:rgba(5,150,105,0.07); }}
.verdict-block.deny     {{ border-left-color:#dc2626; background:rgba(220,38,38,0.07); }}
.verdict-block.escalate {{ border-left-color:#d97706; background:rgba(217,119,6,0.07); }}
.verdict-block.pending     {{ border-left-color:#6b7280; background:#f9fafb; }}
.verdict-block.errored     {{ border-left-color:#dc2626; background:rgba(220,38,38,0.05); }}
.verdict-block.incomplete  {{ border-left-color:#2563eb; background:rgba(37,99,235,0.06); }}
.verdict-block.no-activity {{ border-left-color:#6b7280; background:rgba(107,114,128,0.06); }}
.verdict-type.approve    {{ color:#059669; }}
.verdict-type.deny       {{ color:#dc2626; }}
.verdict-type.escalate   {{ color:#d97706; }}
.verdict-type.pending    {{ color:#6b7280; }}
.verdict-type.errored    {{ color:#dc2626; }}
.verdict-type.incomplete {{ color:#2563eb; }}
.verdict-type.no-activity {{ color:#6b7280; }}
.reason-code {{ color:#6b7280; }}
.reason-code {{ background:rgba(100,116,139,0.10); }}
.tool-row    {{ color:#111827; }}
.tool-ok     {{ color:#ffffff; background:#059669; }}
.tool-fail   {{ color:#ffffff; background:#dc2626; }}
.tool-pending {{ color:#6b7280; background:rgba(100,116,139,0.14); }}
.tool-count  {{ background:rgba(100,116,139,0.12) !important; color:#6b7280 !important; }}
.metric {{ background:#ffffff !important; border-color:var(--border-card) !important; }}
.metric .k {{ color:#6b7280 !important; }}
.metric .v {{ color:#111827 !important; }}
.metric.alert .v {{ color:#d97706 !important; }}
.audit-session-card {{ border-color:var(--border-card) !important; border-left-color:#6b7280 !important; background:#ffffff !important; }}
.audit-session-card.approve  {{ border-left-color:#059669 !important; }}
.audit-session-card.deny     {{ border-left-color:#dc2626 !important; }}
.audit-session-card.escalate {{ border-left-color:#d97706 !important; }}
.audit-session-card.errored {{ border-left-color:#dc2626 !important; background:rgba(220,38,38,0.05) !important; }}
.audit-session-card.incomplete {{ border-left-color:#2563eb !important; background:rgba(37,99,235,0.06) !important; }}
.audit-session-card.no-activity {{ border-left-color:#6b7280 !important; background:rgba(107,114,128,0.06) !important; }}
.audit-session-card.active {{ border-color:var(--border-strong) !important; }}
.tl-dot   {{ color:#6b7280 !important; }}
.tl-title {{ color:#111827 !important; }}
.tl-meta  {{ color:#6b7280 !important; }}
.policy-callout {{ background:rgba(37,99,235,0.07) !important; border-color:#2563eb !important; color:#111827 !important; }}
.policy-callout strong {{ color:#2563eb !important; }}
.rule-row  {{ border-bottom-color:var(--border) !important; }}
.rule-key  {{ color:#6b7280 !important; }}
.rule-val  {{ color:#111827 !important; }}
.rule-note {{ color:#6b7280 !important; }}
.stButton button, [data-testid="stBaseButton-secondary"] {{ background:#ffffff !important; color:#111827 !important; border-color:var(--border-input) !important; }}
.stButton button:hover, [data-testid="stBaseButton-secondary"]:hover {{ border-color:var(--border-strong) !important; color:#111827 !important; }}
.stButton button:focus-visible, [data-testid^="stBaseButton"]:focus-visible {{ box-shadow:0 0 0 2px rgba(148,163,184,0.55) !important; }}
[data-testid="stBaseButton-primary"], .stButton button[kind="primary"] {{ background:#2563eb !important; border-color:#2563eb !important; }}
[data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input {{ background:#ffffff !important; color:#111827 !important; border-color:var(--border-input) !important; }}
[data-testid="stTextArea"] textarea::placeholder {{ color:#6b7280 !important; }}
[data-baseweb="select"] > div {{ background:#ffffff !important; color:#111827 !important; border-color:var(--border-input) !important; }}
[data-testid="stTextArea"] textarea:focus,
[data-testid="stTextInput"] input:focus,
[data-baseweb="select"] > div:focus-within {{
  border-color:var(--border-strong) !important;
  box-shadow:0 0 0 2px rgba(148,163,184,0.35) !important;
}}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ background:#f3f4f6 !important; border-bottom:1px solid var(--border) !important; }}
[data-testid="stTabs"] [data-baseweb="tab"] {{ color:#6b7280 !important; background:#f3f4f6 !important; }}
[data-testid="stTabs"] [aria-selected="true"] {{ color:#111827 !important; }}
[data-testid="stExpander"],
[data-testid="stExpander"] details,
[data-testid="stExpander"] details > summary,
[data-testid="stExpander"] details > summary:hover,
[data-testid="stExpander"] details[open] > summary,
[data-testid="stExpander"] details[open] > summary:hover,
[data-testid="stExpander"] details > summary:focus,
[data-testid="stExpander"] details > summary:focus-visible {{ background:transparent !important; }}
[data-testid="stExpander"] details {{ border:1px solid var(--border-card) !important; border-radius:8px !important; }}
[data-testid="stExpander"] details > summary:focus-visible {{ outline:none !important; box-shadow:0 0 0 2px rgba(148,163,184,0.55) !important; }}
[data-testid="stExpander"] summary {{ color:#111827 !important; }}
[data-testid="stCaption"] p {{ color:#6b7280 !important; }}
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNav"] a:hover {{ color:#6b7280 !important; }}
[data-testid="stSidebarNav"] [aria-selected="true"] span {{ color:#111827 !important; }}
hr {{ border-color:var(--border) !important; }}
p  {{ color:#111827; }}
code {{ background:rgba(17,24,39,0.04) !important; color:#2563eb !important; border-color:var(--border) !important; }}
pre {{ background:#ffffff !important; color:#111827 !important; border-color:var(--border) !important; }}
pre code {{ background:transparent !important; color:inherit !important; border-color:transparent !important; }}
[data-testid="stJson"] {{ background:#ffffff !important; }}
[data-testid="stJson"] span[style], [data-testid="stJson"] .cm-string,
[data-testid="stJson"] .cm-number, [data-testid="stJson"] .cm-property {{ color:#2563eb !important; }}
[data-testid="stJson"] .cm-punctuation, [data-testid="stJson"] .cm-bracket {{ color:#6b7280 !important; }}
[data-testid="stJson"] span[style] {{ background:transparent !important; border:0 !important; box-shadow:none !important; padding:0 !important; border-radius:0 !important; }}
[data-testid="stJson"] .cm-atom, [data-testid="stJson"] .cm-bool, [data-testid="stJson"] .cm-null {{ color:#2563eb !important; background:transparent !important; border-radius:0 !important; }}
[data-testid="stTabs"] [data-baseweb="tab-panel"] {{ background:#f3f4f6 !important; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{ background:#e5e7eb !important; border-radius:12px !important; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {{ background:transparent !important; }}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"] {{
  scrollbar-color:#cbd5e1 rgba(148,163,184,0.10) !important;
}}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"]::-webkit-scrollbar {{
  width:10px !important; height:10px !important;
}}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"]::-webkit-scrollbar-track {{
  background:rgba(148,163,184,0.10) !important; border-radius:999px !important;
}}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"]::-webkit-scrollbar-thumb {{
  background:#cbd5e1 !important; border:2px solid #f3f4f6 !important; border-radius:999px !important;
}}
[data-testid="stHorizontalBlock"]:has(#_audit_list_marker) > [data-testid="stColumn"]::-webkit-scrollbar-thumb:hover {{
  background:#94a3b8 !important;
}}
[data-testid="stChatMessageContent"],
[data-testid="stChatMessageContent"] p,
[data-testid="stChatMessageContent"] li,
[data-testid="stChatMessageContent"] ul,
[data-testid="stChatMessageContent"] ol,
[data-testid="stChatMessageContent"] blockquote {{ color:#111827 !important; }}
[data-testid="stChatMessageContent"] li::marker {{ color:#6b7280 !important; }}
[data-testid="stBaseButton-primary"]:disabled {{ background:rgba(37,99,235,0.12) !important; border-color:transparent !important; color:rgba(37,99,235,0.45) !important; opacity:1 !important; }}
[data-testid="stSidebarCollapseButton"],
[data-testid="stExpandSidebarButton"] {{ background:#ffffff !important; border:1px solid var(--border-layout) !important; border-radius:6px !important; box-shadow:0 1px 4px rgba(0,0,0,0.08) !important; }}
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"],
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {{ color:#1f2937 !important; opacity:1 !important; }}
</style>""", unsafe_allow_html=True)


# ── Format helpers ────────────────────────────────────────────────────────────

def _ts(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return value or ""


def _tok(token_usage: dict[str, Any] | None) -> int:
    return int((token_usage or {}).get("total_tokens") or 0)


def _cost(value: float | None, label: str | None = None) -> str:
    if label:
        return label
    return "n/a" if value is None else f"${value:.4f}"


def _humanize(s: str) -> str:
    return s.replace("_", " ").title()


def _is_voice(event_type: str) -> bool:
    return event_type.startswith("speech_to_text") or event_type in {
        "voice_input_received", "transcription_completed",
    }


def render_json_code(payload: Any) -> None:
    """Render JSON as plain themed code instead of Streamlit's badge-heavy JSON tree."""
    st.code(json.dumps(payload, indent=2, default=str), language="json")
