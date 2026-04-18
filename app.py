"""
app.py – McDonald's Management Dashboard – Hoofdapplicatie
Streamlit mobiel-first management dashboard met wachtwoordbeveiliging

Deployment: Streamlit Community Cloud of Docker (zie deployment.md)
Wachtwoord: stel in via st.secrets["dashboard_password"] of DASHBOARD_PASSWORD env-var
"""
import os
import streamlit as st

# ─── Pagina-configuratie (MOET als eerste Streamlit-aanroep staan) ─────────────
st.set_page_config(
    page_title="🍟 Rooster Dashboard",
    page_icon="🍟",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ─── Mobiel-first CSS ─────────────────────────────────────────────────────────

def _inject_css():
    st.markdown("""
    <style>
    /* ── Algemeen ── */
    #MainMenu, footer, .stDeployButton { visibility: hidden; }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        flex-wrap: wrap;
        overflow-x: auto;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 12px;
        font-size: 13px;
        white-space: nowrap;
        min-height: 40px;
    }

    /* ── Buttons touch-friendly ── */
    .stButton > button {
        min-height: 44px;
        border-radius: 8px;
        font-size: 15px;
    }

    /* ── Inputs: voorkom iOS-zoom ── */
    .stTextInput input,
    .stSelectbox select,
    .stNumberInput input,
    .stTextArea textarea {
        font-size: 16px !important;
    }

    /* ── Mobiel: minder padding ── */
    @media (max-width: 768px) {
        .block-container { padding: 0.4rem 0.4rem 3rem; }
        .stTabs [data-baseweb="tab"] { padding: 6px 8px; font-size: 11px; }
        h1 { font-size: 1.4rem !important; }
        h2 { font-size: 1.2rem !important; }
    }

    /* ── Header kleur ── */
    header[data-testid="stHeader"] { background-color: #DD0000; }

    /* ── Metriek-kaarten ── */
    [data-testid="metric-container"] {
        background: #F8F8F8;
        border-radius: 8px;
        padding: 12px;
        border-left: 4px solid #DD0000;
    }

    /* ── Data editor ── */
    .stDataFrame { border-radius: 8px; }

    /* ── Expander ── */
    .streamlit-expanderHeader {
        font-weight: 600;
        background: #FFF8F8;
        border-radius: 6px;
    }
    </style>
    """, unsafe_allow_html=True)


# ─── Wachtwoordbeveiliging ────────────────────────────────────────────────────

def _check_password() -> bool:
    """
    Eenvoudige wachtwoordbeveiliging via Streamlit Secrets.
    Stel in via .streamlit/secrets.toml:
        dashboard_password = "jouwwachtwoord"
    Of via omgevingsvariabele: DASHBOARD_PASSWORD=...
    """
    try:
        correct_pw = st.secrets["dashboard_password"]
    except (KeyError, FileNotFoundError):
        correct_pw = os.environ.get("DASHBOARD_PASSWORD", "mcdonalds2025")

    if st.session_state.get("authenticated", False):
        return True

    # Login formulier
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            "<div style='text-align:center'>"
            "<h1>🍟 Manager Dashboard</h1>"
            "<p style='color:#666'>Exclusief voor managers – voer wachtwoord in</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        pw = st.text_input("Wachtwoord", type="password", key="_login_pw",
                           placeholder="Voer wachtwoord in…")
        if st.button("🔐 Inloggen", use_container_width=True, type="primary"):
            if pw == correct_pw:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Onjuist wachtwoord. Neem contact op met de regiomanager.")
    return False


# ─── Session State initialisatie ──────────────────────────────────────────────

def _init_state():
    from data_model import AppState
    if "app_state" not in st.session_state:
        st.session_state["app_state"] = AppState()


# ─── Hoofdapp ────────────────────────────────────────────────────────────────

def main():
    _inject_css()

    if not _check_password():
        return

    _init_state()

    # Importeer UI-functies
    from ui import (
        render_tab1, render_tab2, render_tab3, render_tab4, render_tab5,
        render_tab6, render_tab7, render_tab8, render_tab9,
    )

    state     = st.session_state["app_state"]
    rest_name = state.restaurant.name if state.restaurant else "Restaurant"
    month_str = ""
    if state.current_schedule:
        from ui import NL_MONTHS
        sc = state.current_schedule
        month_str = f" – {NL_MONTHS[sc.month]} {sc.year}"

    st.title(f"🍟 {rest_name}{month_str}")

    # Tabs (emoji-labels voor compacte weergave op mobiel)
    tabs = st.tabs([
        "🏪 Restaurant",
        "👥 Medewerkers",
        "📊 Forecast",
        "⚙️ Regels",
        "🤖 Auto-Rooster",
        "✏️ Bewerken",
        "📈 Rapportage",
        "📤 Export",
        "👔 HR",
    ])

    renderers = [
        render_tab1, render_tab2, render_tab3, render_tab4, render_tab5,
        render_tab6, render_tab7, render_tab8, render_tab9,
    ]

    for tab, renderer in zip(tabs, renderers):
        with tab:
            try:
                renderer()
            except Exception as exc:
                st.error(f"⚠️ Fout in dit tabblad: {exc}")
                import traceback
                with st.expander("Technische details (voor ontwikkelaar)"):
                    st.code(traceback.format_exc())

    # Uitloggen (onderaan)
    st.sidebar.markdown("### 🍟 Manager Dashboard")
    st.sidebar.markdown(f"**Restaurant:** {rest_name}")
    if st.sidebar.button("🔓 Uitloggen"):
        st.session_state["authenticated"] = False
        st.rerun()


if __name__ == "__main__":
    main()
