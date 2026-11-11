"""Global visual layer for the AIT Solutions portal.

Base colours, fonts and radii live in ``.streamlit/config.toml`` (the
native Streamlit way). This module adds the things a theme file cannot
express: entrance animations, gradient accents, hover depth, refined
input/button styling, elevated card shadows, and the animated hero banners.

Injected once per run from ``app/main.py`` with ``st.html`` so the
stylesheet reaches every page, including the sign-in screen.

Everything is wrapped in a ``prefers-reduced-motion`` guard, so users
who ask their OS for less motion get a completely static app.
"""

import streamlit as st


# ============================================================
# BRAND TOKENS (mirror of .streamlit/config.toml)
# ============================================================

ACCENT = "#16856B"          # the primary emerald accent
ACCENT_DEEP = "#116B57"     # deep emerald, used in gradients
ACCENT_SOFT = "#E8F2ED"     # pale green tint
INK = "#252A2A"             # primary text on light surfaces
MUTED = "#68716F"           # supporting text
BORDER = "#E1E5DF"          # warm neutral hairlines
PAGE = "#F7F6F2"            # warm off-white application background

DEFAULT_THEME = "Warm neutral"

# Reversible contrasting sidebar mode.
# When True, each theme pairs the dashboard with a complementary contrasting
# sidebar shade. Set to False to restore the original page-matching sidebar color.
CONTRASTING_SIDEBAR_ENABLED = True

THEME_PRESETS = {
    "Warm neutral": {
        "background": "#F7F6F2",
        "surface": "#FFFFFF",
        "accent": "#16856B",
        "sidebar": "#1E2926",
    },
    "Ocean blue": {
        "background": "#F3F7FB",
        "surface": "#FFFFFF",
        "accent": "#2563EB",
        "sidebar": "#162238",
    },
    "Soft violet": {
        "background": "#F7F5FB",
        "surface": "#FFFFFF",
        "accent": "#76528B",
        "sidebar": "#221D32",
    },
    "Forest green": {
        "background": "#F3F7F3",
        "surface": "#FFFFFF",
        "accent": "#28704F",
        "sidebar": "#192822",
    },
    "Midnight": {
        "background": "#111827",
        "surface": "#1F2937",
        "accent": "#34D399",
        "sidebar": "#0B111E",
    },
}


# ============================================================
# STYLESHEET
# ============================================================
# Kept as one block so the browser parses it a single time. Brace
# heavy CSS is stored in a plain string (never an f-string).

STYLESHEET = """
<style>

/* ---------- Motion primitives ---------- */

@keyframes ait-fade-up {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: none; }
}

@keyframes ait-pop {
    from { opacity: 0; transform: translateY(6px) scale(.988); }
    to   { opacity: 1; transform: none; }
}

@keyframes ait-fade {
    from { opacity: 0; }
    to   { opacity: 1; }
}

@keyframes ait-float {
    0%, 100% { transform: translateY(0); }
    50%      { transform: translateY(-4px); }
}

@keyframes ait-drift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

@keyframes ait-pulse {
    0%, 100% { box-shadow: 0 10px 24px -14px rgba(79,70,229,.85); }
    50%      { box-shadow: 0 16px 32px -8px rgba(79,70,229,1); }
}


/* ---------- Ambient page background ----------
   Subtle, modern slate with a very soft indigo & sky tint in the corners.
   Crisp, clean, enterprise SaaS feel. */

[data-testid="stAppViewContainer"] {
    background-image:
        radial-gradient(
            1000px 480px at 100% -12%,
            rgba(99, 102, 241, 0.08),
            transparent 65%
        ),
        radial-gradient(
            760px 420px at 0% 100%,
            rgba(56, 189, 248, 0.035),
            transparent 60%
        );
    background-repeat: no-repeat;
    background-attachment: fixed;
}

/* Page content eases in on every rerun (a soft page transition). */
[data-testid="stMainBlockContainer"] {
    max-width: 1680px;
    padding: 1.75rem clamp(1.25rem, 3vw, 3rem) 3rem !important;
    animation: ait-fade .38s cubic-bezier(.22,.7,.28,1) both;
}


/* ---------- Metrics become elevated cards ---------- */

[data-testid="stMetric"] {
    position: relative;
    border-radius: 11px;
    background-color: #111D33;
    border: 1px solid #263853;
    box-shadow: 0 4px 14px rgba(0, 0, 0, .14);
    overflow: hidden;
    transition:
        transform .2s cubic-bezier(.2,.7,.3,1),
        box-shadow .2s ease,
        border-color .2s ease;
    animation: ait-pop .44s cubic-bezier(.22,.7,.28,1) both;
}

/* Gradient accent bar that expands on hover. */
[data-testid="stMetric"]::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    width: 3.5px;
    border-radius: 0 3px 3px 0;
    background: linear-gradient(180deg, #A5B4FC, #6366F1);
    transform: scaleY(.3);
    transform-origin: top center;
    transition: transform .28s cubic-bezier(.2,.7,.3,1);
}

[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 24px rgba(0, 0, 0, .22);
    border-color: #465C7D;
}

[data-testid="stMetric"]:hover::before {
    transform: scaleY(1);
}

[data-testid="stMetricLabel"] {
    text-transform: uppercase;
    letter-spacing: .08em;
    font-size: .72rem;
    font-weight: 600;
    color: #A8B6CA;
}

[data-testid="stMetricValue"] {
    font-weight: 750;
    letter-spacing: -.02em;
    color: #F8FAFC;
}

[data-testid="stMetricDelta"] {
    color: #CBD5E1;
}

[data-testid="stMetric"] svg {
    color: #A5B4FC;
}


/* ---------- Modern Elevated Cards ----------
   Give a bordered container a key starting with "lift_" and it
   becomes a sleek hover-lift card. */

[class*="st-key-lift_"] {
    border-radius: 11px;
    background-color: #111D33;
    border: 1px solid #263853;
    color: #E2E8F0;
    box-shadow: 0 4px 14px rgba(0, 0, 0, .14);
    transition:
        transform .2s cubic-bezier(.2,.7,.3,1),
        box-shadow .2s ease,
        border-color .2s ease;
    animation: ait-pop .44s cubic-bezier(.22,.7,.28,1) both;
}

[class*="st-key-lift_"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 24px rgba(0, 0, 0, .22);
    border-color: #465C7D;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: #263853 !important;
    border-radius: 11px !important;
    background: #111D33;
}

[class*="st-key-lift_"] [data-testid="stMarkdownContainer"],
[class*="st-key-lift_"] [data-testid="stMarkdownContainer"] p,
[class*="st-key-lift_"] [data-testid="stCaptionContainer"],
[class*="st-key-lift_"] [data-testid="stCaptionContainer"] p,
[class*="st-key-lift_"] [data-testid="stWidgetLabel"] p,
[class*="st-key-lift_"] [data-testid="stWidgetLabel"] label {
    color: #E2E8F0 !important;
}

[data-testid="stVerticalBlockBorderWrapper"] [style*="color: #64748B"],
[data-testid="stVerticalBlockBorderWrapper"] [style*="color:#64748B"],
[data-testid="stVerticalBlockBorderWrapper"] [style*="color: #94A3B8"],
[data-testid="stVerticalBlockBorderWrapper"] [style*="color:#94A3B8"],
[data-testid="stVerticalBlockBorderWrapper"] [style*="color: #334155"],
[data-testid="stVerticalBlockBorderWrapper"] [style*="color:#334155"],
[data-testid="stVerticalBlockBorderWrapper"] [style*="color: #0F172A"],
[data-testid="stVerticalBlockBorderWrapper"] [style*="color:#0F172A"] {
    color: #A8B6CA !important;
}

/* Keep the employee dashboard identity card on the same dark surface. */
.st-key-lift_profile {
    background-color: #111D33 !important;
    border-color: #263853 !important;
    color: #E2E8F0 !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, .18);
}

.st-key-lift_profile h1,
.st-key-lift_profile h2,
.st-key-lift_profile h3,
.st-key-lift_profile h4,
.st-key-lift_profile p,
.st-key-lift_profile label,
.st-key-lift_profile [data-testid="stCaptionContainer"],
.st-key-lift_profile [data-testid="stCaptionContainer"] p {
    color: #E2E8F0 !important;
}


/* ---------- Multi-colour module cards (HR dashboard) ---------- */

[class*="st-key-lift_module_"] {
    border-left: 5px solid var(--card-accent, #16856B);
}

[class*="st-key-lift_module_"] h3 {
    color: var(--card-accent, #16856B);
    font-weight: 700;
}

[class*="st-key-lift_module_"] button {
    border-color: var(--card-accent, #16856B) !important;
    color: var(--card-accent, #16856B) !important;
    font-weight: 600;
    transition:
        background .2s ease,
        color .2s ease,
        transform .16s ease;
}

[class*="st-key-lift_module_"] button:hover {
    background: var(--card-accent, #16856B) !important;
    color: #FFFFFF !important;
}


/* ---------- Form Inputs & Controls ---------- */

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stDateInput"] input,
[data-baseweb="select"] > div {
    border-radius: 8px !important;
    border: 1px solid #E2E8F0 !important;
    background-color: #FFFFFF !important;
    color: #0F172A !important;
    font-size: 0.94rem !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease !important;
}

[data-testid="stTextInput"] input:disabled,
[data-testid="stNumberInput"] input:disabled,
[data-testid="stTextArea"] textarea:disabled,
[data-testid="stDateInput"] input:disabled {
    color: #0F172A !important;
    -webkit-text-fill-color: #0F172A !important;
    opacity: 1 !important;
}

[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stDateInput"] input::placeholder {
    color: #64748B !important;
    opacity: 1 !important;
}

[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stDateInput"] input:focus,
[data-baseweb="select"] > div:focus-within {
    border-color: #6366F1 !important;
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.14) !important;
    outline: none !important;
}

[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label {
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    color: #CBD5E1 !important;
    letter-spacing: -0.01em;
}


/* ---------- Refined Buttons ---------- */

[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"] {
    position: relative;
    overflow: hidden;
    border-radius: 8px !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
    background: #4F46E5 !important;
    border: 1px solid #4338CA !important;
    color: #FFFFFF !important;
    box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05), 0 2px 5px rgba(79, 70, 229, 0.25) !important;
    transition:
        transform .16s cubic-bezier(.2,.7,.3,1),
        box-shadow .2s ease,
        background-color .18s ease !important;
}

[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {
    background: #4338CA !important;
    border-color: #3730A3 !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(79, 70, 229, 0.35) !important;
}

[data-testid="stBaseButton-primary"]:active,
[data-testid="stBaseButton-primaryFormSubmit"]:active {
    transform: translateY(0) scale(.985);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
}

[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondaryFormSubmit"] {
    position: relative;
    overflow: hidden;
    border-radius: 8px !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
    background: #1A2942 !important;
    border: 1px solid #3A4F70 !important;
    color: #F1F5F9 !important;
    -webkit-text-fill-color: #F1F5F9 !important;
    box-shadow: 0 2px 6px rgba(0, 0, 0, .16) !important;
    transition:
        transform .16s cubic-bezier(.2,.7,.3,1),
        box-shadow .2s ease,
        border-color .18s ease,
        background-color .18s ease !important;
}

[data-testid="stBaseButton-secondary"] *,
[data-testid="stBaseButton-secondaryFormSubmit"] * {
    color: #F1F5F9 !important;
    -webkit-text-fill-color: #F1F5F9 !important;
}

[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
    background: #263853 !important;
    border-color: #647A9D !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 10px rgba(0, 0, 0, .2) !important;
}

[data-testid="stBaseButton-secondary"]:hover *,
[data-testid="stBaseButton-secondaryFormSubmit"]:hover * {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}

[data-testid="stBaseButton-secondary"]:active,
[data-testid="stBaseButton-secondaryFormSubmit"]:active {
    transform: translateY(0) scale(.985);
}

[data-testid="stBaseButton-secondary"]:focus-visible,
[data-testid="stBaseButton-secondaryFormSubmit"]:focus-visible,
[data-testid="stBaseButton-primary"]:focus-visible,
[data-testid="stBaseButton-primaryFormSubmit"]:focus-visible {
    outline: 2px solid #A5B4FC !important;
    outline-offset: 2px !important;
}

[data-testid="stBaseButton-secondary"]:disabled,
[data-testid="stBaseButton-secondaryFormSubmit"]:disabled {
    background: #17243A !important;
    border-color: #2A3A54 !important;
    color: #A8B6CA !important;
    -webkit-text-fill-color: #A8B6CA !important;
    opacity: 1 !important;
}

[data-testid="stBaseButton-secondary"]:disabled *,
[data-testid="stBaseButton-secondaryFormSubmit"]:disabled * {
    color: #A8B6CA !important;
    -webkit-text-fill-color: #A8B6CA !important;
}

/* ---------- Photo uploader ---------- */

.st-key-profile_photo_upload [data-testid="stFileUploaderDropzone"] {
    border: none;
    background: transparent;
    padding: 0;
    min-height: 0;
    gap: .4rem;
}

.st-key-profile_photo_upload
[data-testid="stFileUploaderDropzoneInstructions"] {
    display: none;
}

.st-key-profile_photo_upload [data-testid="stFileUploaderDropzone"] button {
    width: 100%;
    justify-content: center;
}


/* ---------- Sidebar navigation ---------- */

[data-testid="stSidebar"] h2 {
    color: #E2E8F0;
    letter-spacing: -.01em;
    font-weight: 750;
    animation: ait-fade .6s ease both;
}

[data-testid="stSidebar"] [data-testid="stExpander"] {
    border: none !important;
    background: transparent !important;
    margin: 0 0 2px !important;
    animation: none !important;
}

[data-testid="stSidebar"] [data-testid="stExpander"] details {
    border: none !important;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    padding: 7px 8px !important;
    border-radius: 8px;
    transition: background .18s ease;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: rgba(129, 140, 248, 0.1);
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary p {
    font-size: .72rem !important;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: #A5B4FC;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary svg {
    color: #A5B4FC;
}

[data-testid="stSidebar"] [class*="st-key-nav_"] button {
    justify-content: flex-start;
    border-radius: 8px;
    font-size: .92rem;
    font-weight: 500;
    transition:
        transform .18s cubic-bezier(.2,.7,.3,1),
        box-shadow .18s ease,
        background .18s ease;
}

[data-testid="stSidebar"] [class*="st-key-nav_"] button:hover {
    transform: translateX(3px);
    background: rgba(129, 140, 248, 0.16);
    color: #F8FAFC;
}


/* ---------- Segmented Modern Tabs ---------- */

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background-color: #0F1B30;
    border: 1px solid #263853;
    padding: 4px;
    border-radius: 10px;
    gap: 4px;
    border-bottom: none !important;
    margin-bottom: 1.25rem;
}

[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    display: none !important;
}

[data-testid="stTabs"] [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 8px 18px !important;
    background: transparent !important;
    border: none !important;
    font-weight: 600;
    font-size: 0.9rem;
    color: #A8B6CA;
    transition: all .18s ease;
}

[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    color: #F8FAFC;
    background: rgba(255, 255, 255, 0.06) !important;
}

[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    background: #263853 !important;
    color: #C7D2FE !important;
    font-weight: 700;
    box-shadow: inset 0 -2px 0 #818CF8 !important;
}


/* ---------- Corporate UI Components ---------- */

.corp-topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #111D33;
    border: 1px solid #263853;
    border-radius: 12px;
    padding: 9px 16px;
    margin-bottom: 16px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, .14);
    font-size: 0.84rem;
}

.corp-topbar-left {
    display: flex;
    align-items: center;
    gap: 12px;
    color: #E2E8F0;
    font-weight: 550;
}

.corp-topbar-right {
    display: flex;
    align-items: center;
    gap: 10px;
}

.corp-status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #ECFDF5;
    border: 1px solid #A7F3D0;
    color: #065F46;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 650;
    letter-spacing: 0.02em;
}

.corp-badge-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #202D4C;
    border: 1px solid #3A4B70;
    color: #C7D2FE;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 650;
}

.corp-icon-tile {
    width: 38px;
    height: 38px;
    border-radius: 9px;
    background: #202D4C;
    color: #C7D2FE;
    display: grid;
    place-items: center;
    font-family: 'Material Symbols Rounded', sans-serif;
    font-size: 21px;
    line-height: 1;
}

.corp-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}


/* ---------- Progress bar ---------- */

[data-testid="stProgressBarTrack"] {
    border-radius: 999px;
    overflow: hidden;
    background-color: #263853;
}

[data-testid="stProgressBarTrack"] div {
    border-radius: 999px;
    background-image: linear-gradient(90deg, #4F46E5, #6366F1);
}


/* ---------- Alerts & expanders ease in ---------- */

[data-testid="stAlert"],
[data-testid="stMain"] [data-testid="stExpander"] {
    animation: ait-fade-up .36s cubic-bezier(.22,.7,.28,1) both;
}


/* ---------- Hero banner ---------- */

.ait-hero {
    position: relative;
    overflow: hidden;
    border-radius: 14px;
    padding: 24px 28px;
    margin-bottom: 20px;
    color: #ffffff;
    background: linear-gradient(
        135deg,
        #14243D 0%,
        #1E3154 54%,
        #373A78 100%
    );
    box-shadow: 0 16px 36px -24px rgba(0, 0, 0, 0.65);
    border: 1px solid rgba(165, 180, 252, 0.16);
    animation: ait-fade-up .5s cubic-bezier(.22,.7,.28,1) both;
}

.ait-hero::after {
    content: "";
    position: absolute;
    top: -46%;
    right: -6%;
    width: 320px;
    height: 320px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(129, 140, 248, .22), transparent 64%);
    animation: ait-float 7s ease-in-out infinite;
    pointer-events: none;
}

.ait-hero__row {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 16px;
}

.ait-hero--center .ait-hero__row {
    flex-direction: column;
    text-align: center;
    gap: 12px;
}

.ait-hero__icon {
    flex: 0 0 auto;
    width: 52px;
    height: 52px;
    border-radius: 14px;
    display: grid;
    place-items: center;
    font-family: 'Material Symbols Rounded', sans-serif;
    font-size: 28px;
    line-height: 1;
    background: rgba(255, 255, 255, .15);
    border: 1px solid rgba(255, 255, 255, .25);
    backdrop-filter: blur(8px);
    animation: ait-float 6s ease-in-out infinite;
}

.ait-hero__title {
    margin: 0;
    font-size: 1.75rem;
    font-weight: 750;
    letter-spacing: -.02em;
    line-height: 1.15;
}

.ait-hero__sub {
    margin-top: 4px;
    font-size: .96rem;
    opacity: .9;
}

.ait-hero__badges {
    position: relative;
    z-index: 1;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 16px;
}

.ait-hero--center .ait-hero__badges {
    justify-content: center;
}

.ait-hero__badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    border-radius: 999px;
    font-size: .78rem;
    background: rgba(255, 255, 255, .14);
    border: 1px solid rgba(255, 255, 255, .22);
    backdrop-filter: blur(8px);
    transition: transform .18s ease, background .18s ease;
    animation: ait-fade .7s ease both;
}

.ait-hero__badge:hover {
    transform: translateY(-2px) scale(1.03);
    background: rgba(255, 255, 255, .24);
}

.ait-hero__badge .ait-hero__badge-icon {
    font-family: 'Material Symbols Rounded', sans-serif;
    font-size: 16px;
    line-height: 1;
}


/* ---------- Holiday calendar cards ---------- */

.ait-hol {
    display: flex;
    align-items: center;
    gap: 14px;
}

.ait-hol__chip {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    border-radius: 12px;
    color: #ffffff;
    line-height: 1;
    background:
        linear-gradient(
            150deg,
            var(--hol-accent, #4F46E5),
            #312E81
        );
    box-shadow:
        0 10px 20px -12px rgba(49, 46, 129, .45);
    animation: ait-pop .42s cubic-bezier(.22,.7,.28,1) both;
}

.ait-hol__day {
    font-size: 1.45rem;
    font-weight: 750;
    letter-spacing: -.02em;
}

.ait-hol__mon {
    margin-top: 2px;
    font-size: .66rem;
    font-weight: 650;
    letter-spacing: .08em;
    text-transform: uppercase;
    opacity: .92;
}

.ait-hol__body {
    min-width: 0;
}

.ait-hol__name {
    font-size: 1.02rem;
    font-weight: 700;
    color: #F1F5F9;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ait-hol__meta {
    margin-top: 3px;
    font-size: .82rem;
    color: #A8B6CA;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}


/* ---------- Asset cards ---------- */

.ait-asset {
    display: flex;
    align-items: center;
    gap: 14px;
}

.ait-asset__chip {
    flex: 0 0 auto;
    display: grid;
    place-items: center;
    width: 56px;
    height: 56px;
    border-radius: 12px;
    color: #ffffff;
    line-height: 1;
    font-family: 'Material Symbols Rounded', sans-serif;
    font-size: 28px;
    background:
        linear-gradient(
            150deg,
            var(--asset-accent, #4F46E5),
            #312E81
        );
    box-shadow:
        0 10px 20px -12px rgba(49, 46, 129, .45);
    animation: ait-pop .42s cubic-bezier(.22,.7,.28,1) both;
}

.ait-asset__body {
    min-width: 0;
}

.ait-asset__name {
    font-size: 1.02rem;
    font-weight: 700;
    color: #F1F5F9;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ait-asset__meta {
    margin-top: 3px;
    font-size: .82rem;
    color: #A8B6CA;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}


/* ---------- Reimbursement bill cards ---------- */

.ait-bill {
    display: flex;
    align-items: center;
    gap: 14px;
}

.ait-bill__chip {
    flex: 0 0 auto;
    display: grid;
    place-items: center;
    width: 56px;
    height: 56px;
    border-radius: 12px;
    color: #ffffff;
    line-height: 1;
    font-family: 'Material Symbols Rounded', sans-serif;
    font-size: 28px;
    background:
        linear-gradient(
            150deg,
            var(--bill-accent, #4F46E5),
            #312E81
        );
    box-shadow:
        0 10px 20px -12px rgba(49, 46, 129, .45);
    animation: ait-pop .42s cubic-bezier(.22,.7,.28,1) both;
}

.ait-bill__body {
    min-width: 0;
}

.ait-bill__name {
    font-size: 1.02rem;
    font-weight: 700;
    color: #F1F5F9;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ait-bill__meta {
    margin-top: 3px;
    font-size: .82rem;
    color: #A8B6CA;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}


/* ---------- Scrollbars ---------- */

::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: transparent;
}

::-webkit-scrollbar-thumb {
    background: #CBD5E1;
    border: 2px solid transparent;
    border-radius: 999px;
    background-clip: content-box;
}

::-webkit-scrollbar-thumb:hover {
    background: #94A3B8;
    background-clip: content-box;
}

/* ---------- Warm neutral and emerald brand palette ---------- */

[data-testid="stAppViewContainer"] {
    background-color: #F7F6F2 !important;
    background-image:
        radial-gradient(900px 420px at 100% -12%, rgba(22, 133, 107, .07), transparent 65%),
        radial-gradient(700px 360px at 0% 100%, rgba(198, 106, 74, .035), transparent 60%) !important;
}

[data-testid="stHeader"],
[data-testid="stMain"] {
    background-color: transparent !important;
}

[data-testid="stMetric"],
[class*="st-key-lift_"],
[data-testid="stVerticalBlockBorderWrapper"],
.corp-topbar {
    background-color: #FFFFFF !important;
    border-color: #E1E5DF !important;
    color: #252A2A !important;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricDelta"],
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
[class*="st-key-lift_"] [data-testid="stMarkdownContainer"],
[class*="st-key-lift_"] [data-testid="stMarkdownContainer"] p,
[class*="st-key-lift_"] [data-testid="stWidgetLabel"] p {
    color: #68716F !important;
}

[data-testid="stMetricValue"],
[class*="st-key-lift_"] h1,
[class*="st-key-lift_"] h2,
[class*="st-key-lift_"] h3,
[class*="st-key-lift_"] h4,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4,
.corp-topbar-left {
    color: #252A2A !important;
}

[data-testid="stMetric"]::before {
    background: linear-gradient(180deg, #69B69D, #16856B) !important;
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stDateInput"] input,
[data-baseweb="select"] > div {
    background-color: #FFFFFF !important;
    border-color: #D7DDD6 !important;
    color: #252A2A !important;
}

[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stDateInput"] input:focus,
[data-baseweb="select"] > div:focus-within {
    border-color: #16856B !important;
    box-shadow: 0 0 0 3px rgba(22, 133, 107, .14) !important;
}

[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"] {
    background: #16856B !important;
    border-color: #116B57 !important;
    color: #FFFFFF !important;
}

[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {
    background: #116B57 !important;
    border-color: #0D5A49 !important;
}

[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondaryFormSubmit"] {
    background: #FFFFFF !important;
    border-color: #D7DDD6 !important;
    color: #34413B !important;
    -webkit-text-fill-color: #34413B !important;
}

[data-testid="stBaseButton-secondary"] *,
[data-testid="stBaseButton-secondaryFormSubmit"] * {
    color: #34413B !important;
    -webkit-text-fill-color: #34413B !important;
}

[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
    background: #E8F2ED !important;
    border-color: #9FC7B5 !important;
}

[data-testid="stBaseButton-secondary"]:focus-visible,
[data-testid="stBaseButton-secondaryFormSubmit"]:focus-visible,
[data-testid="stBaseButton-primary"]:focus-visible,
[data-testid="stBaseButton-primaryFormSubmit"]:focus-visible {
    outline-color: #16856B !important;
}

[data-testid="stSidebar"] {
    background-color: #252B29 !important;
}

[data-testid="stSidebar"] h2 {
    color: #F4F4EF !important;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary svg {
    color: #A8D4C2 !important;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover,
[data-testid="stSidebar"] [class*="st-key-nav_"] button:hover {
    background: rgba(105, 182, 157, .16) !important;
    color: #FFFFFF !important;
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background-color: #F0F0E9 !important;
    border-color: #E1E5DF !important;
}

[data-testid="stTabs"] [data-baseweb="tab"] {
    color: #68716F !important;
}

[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    color: #252A2A !important;
    background: rgba(22, 133, 107, .08) !important;
}

[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    background: #FFFFFF !important;
    color: #116B57 !important;
    box-shadow: inset 0 -2px 0 #16856B !important;
}

[data-testid="stProgressBarTrack"] {
    background-color: #E1E5DF !important;
}

[data-testid="stProgressBarTrack"] div {
    background-image: linear-gradient(90deg, #116B57, #16856B) !important;
}

.ait-hero {
    background: linear-gradient(135deg, #116B57 0%, #16856B 58%, #47765E 100%) !important;
    border-color: rgba(232, 242, 237, .42) !important;
}

.ait-hero::after {
    background: radial-gradient(circle, rgba(168, 212, 194, .28), transparent 64%) !important;
}

.corp-badge-pill,
.corp-icon-tile {
    background: #E8F2ED !important;
    border-color: #C6DED1 !important;
    color: #116B57 !important;
}

/* Keep the employee identity card readable over its white surface. */
.st-key-lift_profile,
.st-key-lift_profile h1,
.st-key-lift_profile h2,
.st-key-lift_profile h3,
.st-key-lift_profile h4,
.st-key-lift_profile [data-testid="stMarkdownContainer"],
.st-key-lift_profile [data-testid="stMarkdownContainer"] p,
.st-key-lift_profile [data-testid="stWidgetLabel"] p,
.st-key-lift_profile [data-testid="stWidgetLabel"] label {
    color: #252A2A !important;
}

.st-key-lift_profile [data-testid="stCaptionContainer"],
.st-key-lift_profile [data-testid="stCaptionContainer"] *,
.st-key-lift_profile [data-testid="stWidgetLabel"],
.st-key-lift_profile [data-testid="stWidgetLabel"] * {
    color: #68716F !important;
    -webkit-text-fill-color: #68716F !important;
    opacity: 1 !important;
}

.st-key-lift_profile [data-testid="stMetricLabel"],
.st-key-lift_profile [data-testid="stMetricDelta"] {
    color: #68716F !important;
}

/* HTML-rendered cards do not inherit Streamlit widget text colors. */
.ait-hol__name,
.ait-asset__name,
.ait-bill__name {
    color: #252A2A !important;
}

.ait-hol__meta,
.ait-asset__meta,
.ait-bill__meta {
    color: #68716F !important;
}

.ait-hol__chip {
    background: linear-gradient(150deg, #16856B, #116B57) !important;
    box-shadow: 0 10px 20px -12px rgba(17, 107, 87, .4) !important;
}

/* Migrate legacy light-on-dark inline text in cards now using white surfaces. */
[class*="st-key-lift_"] [style*="color: #E2E8F0"],
[class*="st-key-lift_"] [style*="color:#E2E8F0"],
[class*="st-key-lift_"] [style*="color: #F1F5F9"],
[class*="st-key-lift_"] [style*="color:#F1F5F9"],
[class*="st-key-lift_"] [style*="color: #CBD5E1"],
[class*="st-key-lift_"] [style*="color:#CBD5E1"] {
    color: #252A2A !important;
}

[class*="st-key-lift_"] [style*="color: #A8B6CA"],
[class*="st-key-lift_"] [style*="color:#A8B6CA"],
[class*="st-key-lift_"] [style*="color: #94A3B8"],
[class*="st-key-lift_"] [style*="color:#94A3B8"] {
    color: #68716F !important;
}

[class*="st-key-lift_"] [style*="color: #A5B4FC"],
[class*="st-key-lift_"] [style*="color:#A5B4FC"] {
    color: #116B57 !important;
}

.ait-asset__chip,
.ait-bill__chip {
    background: linear-gradient(150deg, #47765E, #315B49) !important;
    box-shadow: 0 10px 20px -12px rgba(49, 91, 73, .4) !important;
}

[data-testid="stMetric"]:hover,
[class*="st-key-lift_"]:hover {
    border-color: #9FC7B5 !important;
}

/* Keep the account panel legible for both HR and employee logins. */
.st-key-lift_sidebar_user,
.st-key-lift_sidebar_user [data-testid="stMarkdownContainer"],
.st-key-lift_sidebar_user [data-testid="stMarkdownContainer"] p {
    color: #252A2A !important;
}

.st-key-lift_sidebar_user [data-testid="stCaptionContainer"],
.st-key-lift_sidebar_user [data-testid="stCaptionContainer"] *,
.st-key-lift_sidebar_user code {
    color: #68716F !important;
    -webkit-text-fill-color: #68716F !important;
    opacity: 1 !important;
}

.st-key-lift_sidebar_user code {
    background: #E8F2ED !important;
    color: #116B57 !important;
}

[data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stMarkdownContainer"] p {
    color: #252A2A !important;
}

[data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stCaptionContainer"] * {
    color: #68716F !important;
    -webkit-text-fill-color: #68716F !important;
    opacity: 1 !important;
}

.st-key-lift_sidebar_user [data-testid="stBaseButton-secondary"],
.st-key-lift_sidebar_user [data-testid="stBaseButton-secondaryFormSubmit"],
.st-key-lift_sidebar_user [data-testid="stPopover"] button {
    background: #FFFFFF !important;
    border-color: #D7DDD6 !important;
    color: #34413B !important;
    -webkit-text-fill-color: #34413B !important;
}

.st-key-lift_sidebar_user [data-testid="stBaseButton-secondary"] {
    min-height: 2.4rem;
    padding: .3rem .25rem !important;
    font-size: .75rem !important;
    white-space: nowrap;
}

.st-key-lift_sidebar_user [data-testid="stBaseButton-secondary"] *,
.st-key-lift_sidebar_user [data-testid="stBaseButton-secondaryFormSubmit"] *,
.st-key-lift_sidebar_user [data-testid="stPopover"] button * {
    color: #34413B !important;
    -webkit-text-fill-color: #34413B !important;
}

[data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stBaseButton-secondary"]:hover *,
[data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stBaseButton-secondaryFormSubmit"]:hover *,
[data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stPopover"] button:hover * {
    color: #34413B !important;
    -webkit-text-fill-color: #34413B !important;
}

.st-key-lift_sidebar_user [data-testid="stBaseButton-secondary"]:hover,
.st-key-lift_sidebar_user [data-testid="stBaseButton-secondaryFormSubmit"]:hover,
.st-key-lift_sidebar_user [data-testid="stPopover"] button:hover {
    background: #E8F2ED !important;
    border-color: #9FC7B5 !important;
}

.st-key-lift_sidebar_user [data-testid="stPopover"] button:focus-visible {
    outline: 2px solid #16856B !important;
    outline-offset: 2px;
}

hr,
[data-testid="stDivider"] {
    border-color: #D7DDD6 !important;
    color: #D7DDD6 !important;
}

[data-testid="stSubheader"] [data-testid="stDivider"],
[data-testid="stSubheader"] hr {
    border-color: #D7DDD6 !important;
}

/* Preserve readable foregrounds on hover, keyboard focus, and press. */
[data-testid="stBaseButton-secondary"]:hover *,
[data-testid="stBaseButton-secondaryFormSubmit"]:hover *,
[data-testid="stBaseButton-secondary"]:focus *,
[data-testid="stBaseButton-secondaryFormSubmit"]:focus *,
[data-testid="stBaseButton-secondary"]:active *,
[data-testid="stBaseButton-secondaryFormSubmit"]:active * {
    color: #34413B !important;
    -webkit-text-fill-color: #34413B !important;
}

[data-testid="stBaseButton-secondary"]:hover svg,
[data-testid="stBaseButton-secondaryFormSubmit"]:hover svg,
[data-testid="stBaseButton-secondary"]:focus svg,
[data-testid="stBaseButton-secondaryFormSubmit"]:focus svg,
[data-testid="stBaseButton-secondary"]:active svg,
[data-testid="stBaseButton-secondaryFormSubmit"]:active svg {
    fill: #34413B !important;
}

[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover *,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondaryFormSubmit"]:hover *,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:focus *,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondaryFormSubmit"]:focus * {
    color: #F4F4EF !important;
    -webkit-text-fill-color: #F4F4EF !important;
}

[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondaryFormSubmit"]:hover,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:focus,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondaryFormSubmit"]:focus {
    background: #315B49 !important;
    border-color: #69B69D !important;
}

[data-testid="stBaseButton-primary"]:hover *,
[data-testid="stBaseButton-primaryFormSubmit"]:hover *,
[data-testid="stBaseButton-primary"]:focus *,
[data-testid="stBaseButton-primaryFormSubmit"]:focus *,
[data-testid="stBaseButton-primary"]:active *,
[data-testid="stBaseButton-primaryFormSubmit"]:active * {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}

[data-testid="stBaseButton-secondary"]:disabled,
[data-testid="stBaseButton-secondaryFormSubmit"]:disabled {
    background: #F0F0E9 !important;
    border-color: #E1E5DF !important;
    color: #68716F !important;
    -webkit-text-fill-color: #68716F !important;
}

[data-testid="stBaseButton-secondary"]:disabled *,
[data-testid="stBaseButton-secondaryFormSubmit"]:disabled * {
    color: #68716F !important;
    -webkit-text-fill-color: #68716F !important;
}

::-webkit-scrollbar-thumb {
    background: #B7C0B9 !important;
}

::-webkit-scrollbar-thumb:hover {
    background: #87948C !important;
}


/* ---------- Respect reduced motion ---------- */

@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: .001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: .001ms !important;
        scroll-behavior: auto !important;
    }
}

</style>
"""


def inject():
    """Add the global stylesheet. Call once per run, early in main.py."""

    st.html(STYLESHEET)


def _rgb(color):
    """Convert a validated hex color into an RGB tuple."""

    value = color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _luminance(color):
    """Calculate relative luminance for contrast checks."""

    channels = []

    for channel in _rgb(color):
        normalized = channel / 255
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )

    return (
        0.2126 * channels[0]
        + 0.7152 * channels[1]
        + 0.0722 * channels[2]
    )


def _contrast_ratio(first, second):
    """Return the WCAG contrast ratio between two hex colors."""

    light = max(_luminance(first), _luminance(second))
    dark = min(_luminance(first), _luminance(second))
    return (light + 0.05) / (dark + 0.05)


def _mix(first, second, first_weight):
    """Blend two hex colors, weighting the first color."""

    first_rgb = _rgb(first)
    second_rgb = _rgb(second)
    channels = [
        round(a * first_weight + b * (1 - first_weight))
        for a, b in zip(first_rgb, second_rgb)
    ]
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def _readable_text(backgrounds):
    """Choose black or white text with the best worst-case contrast."""

    candidates = ("#111827", "#FFFFFF")
    return max(
        candidates,
        key=lambda candidate: min(
            _contrast_ratio(candidate, background)
            for background in backgrounds
        ),
    )


def _accessible_accent(accent, backgrounds):
    """Keep the selected accent hue while ensuring readable link contrast."""

    if isinstance(backgrounds, str):
        backgrounds = (backgrounds,)

    if min(_contrast_ratio(accent, color) for color in backgrounds) >= 4.5:
        return accent

    targets = ("#000000", "#FFFFFF")
    candidates = []
    for target in targets:
        for weight in range(95, 0, -5):
            candidate = _mix(accent, target, weight / 100)
            ratio = min(
                _contrast_ratio(candidate, color)
                for color in backgrounds
            )
            if ratio >= 4.5:
                return candidate
            candidates.append((ratio, candidate))

    return max(candidates)[1]


def user_theme_colors(preferences):
    """Return the selected palette with automatically contrasted text."""

    theme_name = preferences.get("theme", DEFAULT_THEME)
    preset = THEME_PRESETS.get(theme_name, THEME_PRESETS[DEFAULT_THEME])
    selected = preferences.get("colors", {})

    background = selected.get("background", preset["background"])
    surface = selected.get("surface", preset["surface"])
    accent = selected.get("accent", preset["accent"])
    text = _readable_text((background,))
    surface_text = _readable_text((surface,))
    muted = _mix(text, background, 0.68)
    surface_muted = _mix(surface_text, surface, 0.68)

    if _contrast_ratio(muted, background) < 4.5:
        muted = text

    if _contrast_ratio(surface_muted, surface) < 4.5:
        surface_muted = surface_text

    border = _mix(surface_text, surface, 0.2)
    accent_soft = _mix(accent, surface, 0.12)
    strong_accent = _accessible_accent(accent, "#FFFFFF")
    hero_accent_end = _mix(strong_accent, "#000000", 0.12)
    accent_text = _readable_text((accent,))

    sidebar_background = (
        selected.get("sidebar", preset.get("sidebar", background))
        if CONTRASTING_SIDEBAR_ENABLED
        else background
    )
    sidebar_text = _readable_text((sidebar_background,))
    sidebar_muted = _mix(sidebar_text, sidebar_background, 0.72)
    if _contrast_ratio(sidebar_muted, sidebar_background) < 4.5:
        sidebar_muted = sidebar_text
    sidebar_border = (
        _mix(sidebar_text, sidebar_background, 0.16)
        if CONTRASTING_SIDEBAR_ENABLED
        else border
    )

    return {
        "background": background,
        "surface": surface,
        "accent": accent,
        "accent_text": accent_text,
        "accent_readable": _accessible_accent(
            accent,
            (background, surface),
        ),
        "accent_soft": accent_soft,
        "strong_accent": strong_accent,
        "hero_accent_end": hero_accent_end,
        "text": text,
        "surface_text": surface_text,
        "muted": muted,
        "surface_muted": surface_muted,
        "border": border,
        "sidebar_background": sidebar_background,
        "sidebar_text": sidebar_text,
        "sidebar_muted": sidebar_muted,
        "sidebar_border": sidebar_border,
        "scheme": "dark" if _luminance(background) < 0.22 else "light",
    }


def inject_user_theme(preferences):
    """Apply a saved per-user palette across Streamlit's shared UI."""

    colors = user_theme_colors(preferences)
    css = f"""
    <style>
    :root {{
        color-scheme: {colors["scheme"]};
        --ait-page: {colors["background"]};
        --ait-surface: {colors["surface"]};
        --ait-accent: {colors["accent"]};
        --ait-accent-text: {colors["accent_text"]};
        --ait-accent-readable: {colors["accent_readable"]};
        --ait-accent-soft: {colors["accent_soft"]};
        --ait-accent-strong: {colors["strong_accent"]};
        --ait-hero-accent-end: {colors["hero_accent_end"]};
        --ait-text: {colors["text"]};
        --ait-surface-text: {colors["surface_text"]};
        --ait-muted: {colors["muted"]};
        --ait-surface-muted: {colors["surface_muted"]};
        --ait-border: {colors["border"]};
        --ait-sidebar-bg: {colors["sidebar_background"]};
        --ait-sidebar-text: {colors["sidebar_text"]};
        --ait-sidebar-muted: {colors["sidebar_muted"]};
        --ait-sidebar-border: {colors["sidebar_border"]};
    }}

    html, body, [data-testid="stAppViewContainer"],
    [data-testid="stMain"], [data-testid="stMainBlockContainer"] {{
        background-color: var(--ait-page) !important;
        background-image: none !important;
        color: var(--ait-text) !important;
    }}

    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div:first-child {{
        background: var(--ait-sidebar-bg) !important;
        border-color: var(--ait-sidebar-border) !important;
    }}

    [data-testid="stSidebar"] hr {{
        border-color: var(--ait-sidebar-border) !important;
    }}

    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] *,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] *,
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {{
        color: var(--ait-sidebar-text) !important;
        -webkit-text-fill-color: var(--ait-sidebar-text) !important;
    }}

    [data-testid="stSidebar"] [data-testid="stExpander"] summary {{
        background: var(--ait-surface) !important;
        border: 1px solid var(--ait-border) !important;
    }}

    [data-testid="stSidebar"] [data-testid="stExpander"] summary p,
    [data-testid="stSidebar"] [data-testid="stExpander"] summary svg {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    /* Captions inside transparent nav expanders (e.g. Government Portals) sit on sidebar bg */
    [data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stCaptionContainer"] * {{
        color: var(--ait-sidebar-muted) !important;
        -webkit-text-fill-color: var(--ait-sidebar-muted) !important;
    }}

    /* Give the bottom Settings panel a crisp card surface so Profile & Theme are clearly readable */
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] {{
        background: var(--ait-surface) !important;
        border: 1px solid var(--ait-border) !important;
        border-radius: 10px !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stMarkdownContainer"] *,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stWidgetLabel"] *,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] h1,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] h2,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] h3,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] h4,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] p,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] label {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stCaptionContainer"] * {{
        color: var(--ait-surface-muted) !important;
        -webkit-text-fill-color: var(--ait-surface-muted) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stTabs"] [data-baseweb="tab-list"] {{
        background: var(--ait-page) !important;
        border: 1px solid var(--ait-border) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stTabs"] [data-baseweb="tab"] {{
        background: transparent !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stTabs"] [data-baseweb="tab"] * {{
        color: var(--ait-surface-muted) !important;
        -webkit-text-fill-color: var(--ait-surface-muted) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stTabs"] [data-baseweb="tab"]:hover {{
        background: var(--ait-accent-soft) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stTabs"] [data-baseweb="tab"]:hover * {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {{
        background: var(--ait-surface) !important;
        box-shadow: inset 0 -2px 0 var(--ait-accent) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] * {{
        color: var(--ait-accent-readable) !important;
        -webkit-text-fill-color: var(--ait-accent-readable) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stBaseButton-primary"] *,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] [data-testid="stBaseButton-primaryFormSubmit"] * {{
        color: var(--ait-accent-text) !important;
        -webkit-text-fill-color: var(--ait-accent-text) !important;
    }}

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] code,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] code {{
        background: var(--ait-accent-soft) !important;
        color: var(--ait-accent-readable) !important;
        -webkit-text-fill-color: var(--ait-accent-readable) !important;
    }}

    [data-testid="stSidebar"] .ait-sidebar-brand-title {{
        color: var(--ait-sidebar-text) !important;
        -webkit-text-fill-color: var(--ait-sidebar-text) !important;
    }}

    [data-testid="stSidebar"] .ait-sidebar-brand-label {{
        color: var(--ait-sidebar-muted) !important;
        -webkit-text-fill-color: var(--ait-sidebar-muted) !important;
    }}

    [data-testid="stSidebar"] .ait-sidebar-brand-icon {{
        background: var(--ait-accent) !important;
        color: var(--ait-accent-text) !important;
        box-shadow: none !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] summary {{
        width: 100% !important;
        background: var(--ait-accent) !important;
        border: 1px solid var(--ait-accent-readable) !important;
        border-radius: 8px !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] summary *,
    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] summary p {{
        color: var(--ait-accent-text) !important;
        -webkit-text-fill-color: var(--ait-accent-text) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [data-testid="stExpander"] summary:hover {{
        filter: brightness(.94);
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [class*="st-key-settings_profile_"] button {{
        background: var(--ait-accent) !important;
        border: 1px solid var(--ait-accent-readable) !important;
        color: var(--ait-accent-text) !important;
        -webkit-text-fill-color: var(--ait-accent-text) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [class*="st-key-settings_profile_"] button * {{
        color: var(--ait-accent-text) !important;
        -webkit-text-fill-color: var(--ait-accent-text) !important;
    }}

    [data-testid="stSidebar"] .st-key-sidebar_settings [class*="st-key-settings_profile_"] button:hover {{
        filter: brightness(.92);
    }}

    [data-testid="stSidebar"] .st-key-lift_sidebar_user {{
        background: var(--ait-surface) !important;
        border-color: var(--ait-border) !important;
        color: var(--ait-surface-text) !important;
    }}

    [data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stMarkdownContainer"] *,
    [data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stCaptionContainer"] *,
    [data-testid="stSidebar"] .st-key-lift_sidebar_user code {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stSidebar"] .st-key-lift_sidebar_user [data-testid="stCaptionContainer"] * {{
        color: var(--ait-surface-muted) !important;
        -webkit-text-fill-color: var(--ait-surface-muted) !important;
    }}

    [data-testid="stSidebar"] [class*="st-key-nav_"] button,
    [data-testid="stSidebar"] [data-testid="stLinkButton"] a,
    [data-testid="stSidebar"] [data-testid="stDownloadButton"] button {{
        background: var(--ait-surface) !important;
        border: 1px solid var(--ait-border) !important;
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stSidebar"] [class*="st-key-nav_"] button *,
    [data-testid="stSidebar"] [data-testid="stLinkButton"] a *,
    [data-testid="stSidebar"] [data-testid="stDownloadButton"] button * {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stSidebar"] [class*="st-key-nav_"] button:hover,
    [data-testid="stSidebar"] [data-testid="stLinkButton"] a:hover,
    [data-testid="stSidebar"] [data-testid="stDownloadButton"] button:hover {{
        background: var(--ait-accent-soft) !important;
        border-color: var(--ait-accent-readable) !important;
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stSidebar"] [class*="st-key-nav_"] button:hover *,
    [data-testid="stSidebar"] [data-testid="stLinkButton"] a:hover *,
    [data-testid="stSidebar"] [data-testid="stDownloadButton"] button:hover * {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stSidebar"] [class*="st-key-nav_"] [data-testid="stBaseButton-primary"],
    [data-testid="stSidebar"] [class*="st-key-nav_"] [data-testid="stBaseButton-primary"] * {{
        background: var(--ait-accent) !important;
        border-color: var(--ait-accent-readable) !important;
        color: var(--ait-accent-text) !important;
        -webkit-text-fill-color: var(--ait-accent-text) !important;
    }}

    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{
        background: var(--ait-accent-soft) !important;
    }}

    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4,
    [data-testid="stMarkdownContainer"] h5,
    [data-testid="stMarkdownContainer"] h6,
    [data-testid="stWidgetLabel"] *,
    [data-testid="stCaptionContainer"] *,
    [data-testid="stSubheader"] *,
    [data-testid="stHeader"] *,
    [data-testid="stStatusWidget"] *,
    [data-testid="stAlert"] p {{
        color: var(--ait-text) !important;
        -webkit-text-fill-color: var(--ait-text) !important;
    }}

    [data-testid="stDataFrame"],
    [data-testid="stDataEditor"],
    [data-testid="stTable"],
    [data-testid="stDataFrame"] [role="grid"],
    [data-testid="stDataEditor"] [role="grid"],
    [data-testid="stTable"] table {{
        background: var(--ait-surface) !important;
        color: var(--ait-surface-text) !important;
        border-color: var(--ait-border) !important;
    }}

    [data-testid="stDataFrame"] [role="grid"] *,
    [data-testid="stDataEditor"] [role="grid"] *,
    [data-testid="stTable"] th,
    [data-testid="stTable"] td {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stAlert"] {{
        background: var(--ait-surface) !important;
        border-color: var(--ait-border) !important;
    }}

    [data-testid="stCaptionContainer"] *,
    [data-testid="stMarkdownContainer"] small {{
        color: var(--ait-muted) !important;
        -webkit-text-fill-color: var(--ait-muted) !important;
    }}

    [data-testid="stPopover"] *,
    [data-testid="stDialog"] > div * {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stPopover"] [data-testid="stCaptionContainer"] *,
    [data-testid="stDialog"] > div [data-testid="stCaptionContainer"] * {{
        color: var(--ait-surface-muted) !important;
        -webkit-text-fill-color: var(--ait-surface-muted) !important;
    }}

    [data-testid="stMetric"],
    [class*="st-key-lift_"],
    [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stExpander"],
    [data-testid="stPopover"],
    [data-testid="stDialog"] > div {{
        background: var(--ait-surface) !important;
        border-color: var(--ait-border) !important;
        color: var(--ait-text) !important;
    }}

    [data-testid="stMetric"] *,
    [class*="st-key-lift_"] [data-testid="stMarkdownContainer"] *,
    [class*="st-key-lift_"] [data-testid="stCaptionContainer"] *,
    [class*="st-key-lift_"] [data-testid="stWidgetLabel"] *,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdownContainer"] *,
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"] * {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"] * {{
        color: var(--ait-surface-muted) !important;
        -webkit-text-fill-color: var(--ait-surface-muted) !important;
    }}

    [data-testid="stMetric"]::before {{
        background: linear-gradient(180deg, var(--ait-accent), var(--ait-accent-strong)) !important;
    }}

    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-primaryFormSubmit"] {{
        background: var(--ait-accent) !important;
        border-color: var(--ait-accent-readable) !important;
        color: var(--ait-accent-text) !important;
        -webkit-text-fill-color: var(--ait-accent-text) !important;
    }}

    [data-testid="stBaseButton-primary"] *,
    [data-testid="stBaseButton-primaryFormSubmit"] * {{
        color: var(--ait-accent-text) !important;
        -webkit-text-fill-color: var(--ait-accent-text) !important;
    }}

    [data-testid="stBaseButton-secondary"],
    [data-testid="stBaseButton-secondaryFormSubmit"],
    [data-testid="stBaseButton-tertiary"],
    [data-testid="stPopover"] > button,
    [data-testid="stDownloadButton"] button {{
        background: var(--ait-surface) !important;
        border-color: var(--ait-border) !important;
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stBaseButton-secondary"] *,
    [data-testid="stBaseButton-secondaryFormSubmit"] *,
    [data-testid="stBaseButton-tertiary"] *,
    [data-testid="stPopover"] > button *,
    [data-testid="stDownloadButton"] button * {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stBaseButton-secondary"]:hover,
    [data-testid="stBaseButton-secondaryFormSubmit"]:hover,
    [data-testid="stBaseButton-tertiary"]:hover,
    [data-testid="stPopover"] > button:hover {{
        background: var(--ait-accent-soft) !important;
        border-color: var(--ait-accent-readable) !important;
    }}

    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stDateInput"] input,
    [data-testid="stChatInput"] textarea,
    [data-baseweb="select"] > div,
    [data-baseweb="select"] input {{
        background: var(--ait-surface) !important;
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
        border-color: var(--ait-border) !important;
    }}

    [data-testid="stTextInput"] input:disabled,
    [data-testid="stNumberInput"] input:disabled,
    [data-testid="stTextArea"] textarea:disabled,
    [data-testid="stDateInput"] input:disabled {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
        opacity: .8 !important;
    }}

    [data-testid="stTextInput"] input::placeholder,
    [data-testid="stNumberInput"] input::placeholder,
    [data-testid="stTextArea"] textarea::placeholder,
    [data-testid="stChatInput"] textarea::placeholder {{
        color: var(--ait-muted) !important;
        -webkit-text-fill-color: var(--ait-muted) !important;
        opacity: 1 !important;
    }}

    [data-testid="stTextInput"] input:focus,
    [data-testid="stNumberInput"] input:focus,
    [data-testid="stTextArea"] textarea:focus,
    [data-testid="stDateInput"] input:focus,
    [data-testid="stChatInput"] textarea:focus,
    [data-baseweb="select"] > div:focus-within {{
        border-color: var(--ait-accent-readable) !important;
        box-shadow: 0 0 0 3px var(--ait-accent-soft) !important;
    }}

    [data-testid="stTabs"] [data-baseweb="tab-list"],
    [data-baseweb="popover"],
    [data-baseweb="menu"] {{
        background: var(--ait-surface) !important;
        border-color: var(--ait-border) !important;
    }}

    [data-testid="stTabs"] [data-baseweb="tab"] {{
        background: transparent !important;
        color: var(--ait-surface-muted) !important;
    }}

    [data-testid="stTabs"] [data-baseweb="tab"] * {{
        color: var(--ait-surface-muted) !important;
        -webkit-text-fill-color: var(--ait-surface-muted) !important;
    }}

    [data-testid="stTabs"] [data-baseweb="tab"]:hover {{
        background: var(--ait-accent-soft) !important;
    }}

    [data-testid="stTabs"] [data-baseweb="tab"]:hover * {{
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {{
        background: var(--ait-accent-soft) !important;
        color: var(--ait-accent-readable) !important;
        box-shadow: inset 0 -2px 0 var(--ait-accent) !important;
    }}

    [data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] * {{
        color: var(--ait-accent-readable) !important;
        -webkit-text-fill-color: var(--ait-accent-readable) !important;
    }}

    [role="listbox"],
    [role="option"],
    [data-baseweb="menu"] *,
    [data-baseweb="popover"] * {{
        background-color: var(--ait-surface) !important;
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [role="option"][aria-selected="true"],
    [role="option"]:hover {{
        background-color: var(--ait-accent-soft) !important;
        color: var(--ait-surface-text) !important;
        -webkit-text-fill-color: var(--ait-surface-text) !important;
    }}

    [data-testid="stDataFrame"] *,
    [data-testid="stDataEditor"] * {{
        --gdg-bg-cell: var(--ait-surface);
        --gdg-bg-cell-medium: var(--ait-surface);
        --gdg-bg-cell-light: var(--ait-surface);
        --gdg-bg-header: var(--ait-surface);
        --gdg-bg-header-hover: var(--ait-accent-soft);
        --gdg-text-dark: var(--ait-surface-text);
        --gdg-text-medium: var(--ait-surface-muted);
        --gdg-text-light: var(--ait-surface-muted);
        --gdg-text-header: var(--ait-surface-text);
        --gdg-text-group-header: var(--ait-surface-text);
        --gdg-border-color: var(--ait-border);
        --gdg-horizontal-border-color: var(--ait-border);
        --gdg-accent-color: var(--ait-accent);
    }}

    [data-testid="stVegaLiteChart"] svg text {{
        fill: var(--ait-surface-text) !important;
    }}

    [data-testid="stAlert"] svg {{
        color: var(--ait-surface-text) !important;
        fill: var(--ait-surface-text) !important;
    }}

    [data-testid="stProgressBarTrack"] {{
        background: var(--ait-border) !important;
    }}

    [data-testid="stProgressBarTrack"] div {{
        background: var(--ait-accent) !important;
    }}

    .ait-hero {{
        background: linear-gradient(
            135deg,
            var(--ait-accent-strong),
            var(--ait-hero-accent-end)
        ) !important;
        color: #FFFFFF !important;
    }}

    a, [data-testid="stMarkdownContainer"] a {{
        color: var(--ait-accent-readable) !important;
    }}
    </style>
    """
    st.html(css)


def hero(
    title,
    subtitle="",
    icon=None,
    badges=None,
    center=False
):
    """Render an animated gradient hero banner.

    title    -- main heading text.
    subtitle -- supporting line under the heading.
    icon     -- optional Material Symbols ligature name, e.g. "groups".
    badges   -- optional iterable of (label, icon) tuples.
    center   -- centre the content (used by the splash screen).
    """

    classes = "ait-hero ait-hero--center" if center else "ait-hero"

    icon_html = (
        f'<div class="ait-hero__icon">{icon}</div>'
        if icon else ""
    )

    text_html = (
        '<div>'
        f'<div class="ait-hero__title">{title}</div>'
        + (
            f'<div class="ait-hero__sub">{subtitle}</div>'
            if subtitle else ""
        )
        + '</div>'
    )

    badges_html = ""

    if badges:

        chips = []

        for label, badge_icon in badges:

            icon_span = (
                f'<span class="ait-hero__badge-icon">{badge_icon}</span>'
                if badge_icon else ""
            )

            chips.append(
                f'<span class="ait-hero__badge">{icon_span}{label}</span>'
            )

        badges_html = (
            '<div class="ait-hero__badges">'
            + "".join(chips)
            + '</div>'
        )

    st.html(
        f'<div class="{classes}">'
        f'<div class="ait-hero__row">{icon_html}{text_html}</div>'
        f'{badges_html}'
        '</div>'
    )
