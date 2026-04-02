"""Glassmorphism CSS theme for Пульс Рунета dashboard."""

GLASSMORPHISM_CSS = """
<style>
/* === GLOBAL THEME === */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

.stApp {
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%) !important;
    font-family: 'Inter', sans-serif;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: rgba(15, 12, 41, 0.95) !important;
    border-right: 1px solid rgba(255,255,255,0.08);
}

section[data-testid="stSidebar"] .stMarkdown {
    color: #e2e8f0;
}

/* === GLASSMORPHISM CARDS === */
.glass-card {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    padding: 24px;
    margin: 12px 0;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    transition: all 0.3s ease;
}

.glass-card:hover {
    border-color: rgba(100, 200, 255, 0.3);
    box-shadow: 0 8px 32px rgba(100, 200, 255, 0.1);
}

.glass-card-accent {
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(168, 85, 247, 0.15));
    backdrop-filter: blur(20px);
    border: 1px solid rgba(168, 85, 247, 0.2);
    border-radius: 16px;
    padding: 24px;
    margin: 12px 0;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

/* === METRICS === */
div[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 16px 20px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
}

div[data-testid="stMetric"] label {
    color: #94a3b8 !important;
    font-size: 0.85rem !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    color: #f1f5f9 !important;
    font-weight: 600;
}

/* === EXPANDER === */
div[data-testid="stExpander"] {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    overflow: hidden;
}

div[data-testid="stExpander"] summary {
    color: #e2e8f0 !important;
}

/* === DATAFRAME === */
div[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.06);
}

/* === BUTTONS === */
.stButton button {
    background: linear-gradient(135deg, #6366f1, #a855f7) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 500;
    padding: 8px 24px;
    transition: all 0.3s ease;
    box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
}

.stButton button:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5) !important;
}

/* === TABS === */
button[data-baseweb="tab"] {
    color: #94a3b8 !important;
    border-bottom: 2px solid transparent !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    color: #a78bfa !important;
    border-bottom: 2px solid #a78bfa !important;
}

/* === TEXT === */
.stApp h1, .stApp h2, .stApp h3 {
    color: #f1f5f9 !important;
}

.stApp p, .stApp span, .stApp li {
    color: #cbd5e1;
}

.stApp .stCaption {
    color: #64748b !important;
}

/* === INPUTS === */
.stTextInput input, .stSelectbox select, .stDateInput input {
    background: rgba(255, 255, 255, 0.06) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    color: #e2e8f0 !important;
}

/* === PLOTLY dark theme overrides === */
.js-plotly-plot .plotly .modebar {
    background: transparent !important;
}

/* === CUSTOM CLASSES === */
.neon-text {
    color: #a78bfa;
    text-shadow: 0 0 10px rgba(167, 139, 250, 0.5);
}

.pulse-badge {
    display: inline-block;
    background: linear-gradient(135deg, #6366f1, #a855f7);
    color: white;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 500;
}

.signal-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    animation: pulse-glow 2s ease-in-out infinite;
}

@keyframes pulse-glow {
    0%, 100% { opacity: 0.4; box-shadow: 0 0 5px currentColor; }
    50% { opacity: 1; box-shadow: 0 0 20px currentColor; }
}

.sonar-ring {
    position: relative;
    width: 100%;
    padding-top: 100%;
    border-radius: 50%;
    background: radial-gradient(circle,
        rgba(99, 102, 241, 0.1) 0%,
        rgba(99, 102, 241, 0.05) 40%,
        rgba(99, 102, 241, 0.02) 70%,
        transparent 100%);
    border: 1px solid rgba(99, 102, 241, 0.2);
}

/* Drama meter */
.drama-bar {
    height: 8px;
    border-radius: 4px;
    background: linear-gradient(90deg, #22c55e 0%, #eab308 50%, #ef4444 100%);
}

/* Chain reaction animation dots */
.chain-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin: 0 2px;
}

/* Scrollbar styling */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}

::-webkit-scrollbar-track {
    background: rgba(255, 255, 255, 0.02);
}

::-webkit-scrollbar-thumb {
    background: rgba(167, 139, 250, 0.3);
    border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
    background: rgba(167, 139, 250, 0.5);
}
</style>
"""


def inject_glassmorphism():
    """Inject glassmorphism CSS into Streamlit."""
    import streamlit as st
    st.markdown(GLASSMORPHISM_CSS, unsafe_allow_html=True)


def glass_card(content: str, accent: bool = False):
    """Wrap content in a glass card."""
    import streamlit as st
    cls = "glass-card-accent" if accent else "glass-card"
    st.markdown(f'<div class="{cls}">{content}</div>', unsafe_allow_html=True)


def neon_header(text: str, level: int = 2):
    """Render a neon-styled header."""
    import streamlit as st
    st.markdown(f'<h{level} class="neon-text">{text}</h{level}>', unsafe_allow_html=True)
