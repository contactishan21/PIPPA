from __future__ import annotations

from pathlib import Path


def turnstile_token(site_key: str, key: str = "pippa-turnstile") -> str:
    """Render Cloudflare Turnstile and return its short-lived verification token."""
    if not site_key:
        return ""
    import streamlit.components.v1 as components

    component = components.declare_component(
        "pippa_turnstile",
        path=str(Path(__file__).resolve().parent / "turnstile_component"),
    )
    return str(component(site_key=site_key, key=key, default="") or "")
