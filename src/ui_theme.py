"""Small shared UI helpers: theming, header banner, and risk badges."""

import streamlit as st

RISK_COLORS = {
    "high": "#e5484d",
    "medium": "#f5a623",
    "low": "#2dbf6e",
    "unknown": "#8a8f98",
}

CUSTOM_CSS = """
<style>
.soc-header {
    padding: 1.1rem 1.4rem;
    border-radius: 10px;
    background: linear-gradient(135deg, #0b1220 0%, #10233d 100%);
    border: 1px solid #1f3355;
    margin-bottom: 1.2rem;
}
.soc-header h1 {
    color: #f5f7fa;
    font-size: 1.5rem;
    margin: 0 0 0.2rem 0;
}
.soc-header p {
    color: #9fb3d1;
    margin: 0;
    font-size: 0.92rem;
}
.soc-tag {
    display: inline-block;
    background: #16345c;
    color: #7fd4ff;
    border-radius: 999px;
    padding: 0.15rem 0.7rem;
    font-size: 0.72rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-right: 0.4rem;
}
.risk-badge {
    display: inline-block;
    padding: 0.1rem 0.55rem;
    border-radius: 6px;
    font-size: 0.78rem;
    font-weight: 600;
    color: #0b1220;
}
.metric-note {
    color: #8a8f98;
    font-size: 0.8rem;
}
</style>
"""


def inject_theme() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str, tags: list[str] | None = None) -> None:
    tags_html = "".join(f'<span class="soc-tag">{t}</span>' for t in (tags or []))
    st.markdown(
        f"""
        <div class="soc-header">
            <div>{tags_html}</div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def risk_badge(risk: str) -> str:
    color = RISK_COLORS.get(risk, RISK_COLORS["unknown"])
    return f'<span class="risk-badge" style="background:{color};">{risk.upper()}</span>'
