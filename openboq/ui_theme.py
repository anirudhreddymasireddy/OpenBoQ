"""Look and feel: thin-line wordmark (pure SVG, no font download), one small stylesheet, HTML snippets.

Everything here is a string sent once per page run – no web fonts, no images, no extra requests.
"""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

INK = "#15202B"
ORANGE = "#E8772E"          # on the dark sidebar
ORANGE_D = "#C9561A"        # on light backgrounds (contrast ≥ 3:1 for strokes, ~4.4:1 for text)
SEV_COLOR = {"high": "#B3261E", "medium": "#8A5300", "low": "#5F6B78", "info": "#2A6FC9"}
SEV_TINT = {"high": "#FBE9E7", "medium": "#FDF1DC", "low": "#EEF1F4", "info": "#E6EFFB"}
FAVICON = Path(__file__).resolve().parent.parent / "data" / "favicon.png"

# monoline letters on a 280 × 76 grid; "Open" in the text colour, "BoQ" in orange
_OPEN = ('<circle cx="22" cy="30" r="20"/>'
         '<path d="M52 24 V62"/><circle cx="65" cy="37" r="13"/>'
         '<path d="M86 37 H112 A13 13 0 1 0 108.19 46.19"/>'
         '<path d="M120 50 V24 M120 37 A12 12 0 0 1 144 37 V50"/>')
_BOQ = ('<path d="M158 10 V50 M158 10 H170 A9.5 9.5 0 0 1 170 29 H158 M158 29 H172 A10.5 10.5 0 0 1 172 50 H158"/>'
        '<circle cx="204" cy="37" r="13"/>'
        '<circle cx="248" cy="30" r="20"/><path d="M256 40 L272 56"/>')
# a drawing's dimension line under the name: hairline with slash ticks at both ends
_DIM = '<path d="M2 70 H272"/><path d="M-1 73 L5 67"/><path d="M269 73 L275 67"/>'


def wordmark(height: int = 40, dark: bool = False, stroke: float = 2.2, dim: bool = True, draw: bool = False,
             label: str = "OpenBoQ") -> str:
    """Inline SVG. dark=True for the ink sidebar. draw=True lets the strokes draw in once (landing page only)."""
    text = "#F1F4F7" if dark else INK
    accent = ORANGE if dark else ORANGE_D
    cls = "ob-wm ob-draw" if draw else "ob-wm"
    dim_svg = (f'<g stroke="{text}" stroke-width="1" opacity=".45">{_DIM}</g>' if dim else "")
    svg = (f'<svg class="{cls}" viewBox="-2 0 282 76" height="{height}" role="img" aria-label="{label}" '
            f'xmlns="http://www.w3.org/2000/svg" fill="none" stroke-linecap="round" stroke-linejoin="round">'
            f'<g stroke="{text}" stroke-width="{stroke}">{_OPEN}</g>'
            f'<g stroke="{accent}" stroke-width="{stroke}">{_BOQ}</g>{dim_svg}</svg>')
    if draw:                                       # normalised lengths so one dash animation fits every stroke
        svg = svg.replace("<circle ", '<circle pathLength="1" ').replace("<path ", '<path pathLength="1" ')
    return svg


CSS = f"""
<style>
:root {{ --ob-ink:{INK}; --ob-or:{ORANGE_D}; --ob-line:#D9DFE6; --ob-muted:#5F6B78; }}
[data-testid="stDecoration"] {{ display:none; }}
[data-testid="stMainBlockContainer"] {{ padding-top:2.4rem; max-width:1320px; }}
h1, h2, h3 {{ letter-spacing:-0.015em; }}
[data-testid="stMetricValue"], .ob-eur {{ font-variant-numeric: tabular-nums; }}

/* sidebar */
[data-testid="stSidebar"] .ob-wm {{ display:block; margin:.1rem 0 .2rem; }}
[data-testid="stSidebarHeader"] {{ height:1.6rem; }}

/* key figures as a drawing title block: one ruled box, hairline cells */
[class*="st-key-kpis"] {{ border:1px solid var(--ob-ink); border-radius:3px; background:#fff; gap:0; }}
[class*="st-key-kpis"] [data-testid="stHorizontalBlock"] {{ gap:0; }}
[class*="st-key-kpis"] [data-testid="stColumn"] {{ border-left:1px solid var(--ob-line); padding:.65rem 1rem .55rem; }}
[class*="st-key-kpis"] [data-testid="stColumn"]:first-child {{ border-left:0; }}
[class*="st-key-kpis"] [data-testid="stMetricLabel"] p {{ font-size:.8rem; color:var(--ob-muted); }}
.st-key-kpis_wi [data-testid="stMetricValue"], .st-key-kpis_hist [data-testid="stMetricValue"] {{ font-size:1.9rem; }}

/* finding cards */
.ob-pill {{ display:inline-block; padding:.08rem .55rem; border-radius:999px; font-size:.74rem; font-weight:600;
           line-height:1.35rem; margin-right:.45rem; vertical-align:1px; }}
.ob-oz {{ font-variant-numeric: tabular-nums; color:var(--ob-muted); margin-right:.4rem; }}
.ob-t {{ font-weight:600; }}
.ob-m {{ margin:.3rem 0 .2rem; line-height:1.5; }}
.ob-ref {{ color:var(--ob-muted); font-size:.85rem; }}
.ob-fix {{ font-size:.9rem; margin-top:.25rem; }}
.ob-eur {{ font-size:1.45rem; font-weight:650; text-align:right; line-height:1.2; }}
.ob-eur small {{ display:block; font-size:.75rem; font-weight:400; color:var(--ob-muted); }}
[class*="st-key-card_high"] {{ border-left:3px solid {SEV_COLOR['high']} !important; }}
[class*="st-key-card_medium"] {{ border-left:3px solid #C77A12 !important; }}
[class*="st-key-card_low"], [class*="st-key-card_info"] {{ border-left:3px solid var(--ob-line) !important; }}

/* ranked bars: full labels, exact values, no chart library to load */
.ob-bars {{ margin-top:.2rem; }}
.ob-bar {{ margin:0 0 .8rem; }}
.ob-bl {{ display:flex; justify-content:space-between; gap:1rem; font-size:.88rem; line-height:1.35; }}
.ob-bl b {{ font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.ob-track {{ height:6px; background:#E3E8ED; border-radius:3px; margin-top:.3rem; }}
.ob-track i {{ display:block; height:100%; background:var(--ob-or); border-radius:3px; }}
.ob-bar:hover .ob-track i {{ background:#A84612; }}

/* landing page */
.ob-hero {{ padding:2.2rem 0 1.4rem; max-width:760px; }}
.ob-hero h1 {{ font-size:2.35rem; line-height:1.15; margin:1.6rem 0 .6rem; font-weight:650; }}
.ob-hero p {{ font-size:1.08rem; line-height:1.55; color:#33404D; max-width:62ch; }}
.ob-steps {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:0; margin:1.6rem 0 .4rem;
            border-top:1px solid var(--ob-ink); max-width:980px; }}
.ob-steps div {{ padding:.9rem 1.2rem 0 0; }}
.ob-steps b {{ display:block; font-size:.95rem; margin-bottom:.25rem; }}
.ob-steps span {{ color:#44515E; font-size:.92rem; line-height:1.5; }}
.ob-steps i {{ font-style:normal; color:var(--ob-or); font-weight:650; margin-right:.35rem; }}
.ob-steps + div, .st-key-cta {{ margin-top:1.4rem; }}
@media (max-width: 720px) {{ .ob-steps {{ grid-template-columns:1fr; }} .ob-hero h1 {{ font-size:1.8rem; }} }}

/* the one moment of motion: the name draws itself on the landing page */
.ob-draw circle, .ob-draw path {{ stroke-dasharray:1; stroke-dashoffset:1; animation:ob-draw 1.1s ease-out forwards; }}
.ob-draw g:nth-of-type(2) circle, .ob-draw g:nth-of-type(2) path {{ animation-delay:.35s; }}
.ob-draw g:nth-of-type(3) path {{ animation-delay:.8s; }}
@keyframes ob-draw {{ to {{ stroke-dashoffset:0; }} }}
@media (prefers-reduced-motion: reduce) {{ .ob-draw circle, .ob-draw path {{ animation:none; stroke-dashoffset:0; }} }}

/* login */
.st-key-login, .st-key-login_form {{ max-width:420px; margin-left:auto; margin-right:auto; }}
.st-key-login {{ margin-top:8vh; }}
</style>
"""


def _home_css() -> str:
    """The sidebar logo is a real button (keeps the session and login) that shows the wordmark as its picture."""
    from urllib.parse import quote
    svg = quote(wordmark(height=40, dark=True))
    return (f'<style>.st-key-home button {{ background:transparent url("data:image/svg+xml,{svg}") no-repeat left center;'
            f' background-size:auto 40px; border:0 !important; box-shadow:none !important; height:46px; width:160px;'
            f' padding:0; justify-content:flex-start; }}'
            f'.st-key-home button p {{ color:transparent; }}'
            f'.st-key-home button:hover, .st-key-home button:active, .st-key-home button:focus'
            f' {{ background-color:transparent !important; opacity:.8; }}'
            f'.st-key-home button:focus-visible {{ outline:2px solid {ORANGE}; outline-offset:3px; }}</style>')


def inject_css():
    st.html(CSS + _home_css())


def pill(sev: str, label: str) -> str:
    return (f'<span class="ob-pill" style="background:{SEV_TINT.get(sev, "#EEF1F4")};color:{SEV_COLOR.get(sev, INK)}">'
            f'{html.escape(label)}</span>')


def finding_html(f, lang: str, sev_label, lv_wide: str, with_fix: bool = True) -> str:
    """One finding as a compact block: severity pill, item number, title, explanation, basis, suggestion."""
    t, m, s = f.txt(lang)
    out = (f'{pill(f.severity, sev_label(f.severity, lang))}<span class="ob-oz">{html.escape(f.oz or lv_wide)}</span>'
           f'<span class="ob-t">{html.escape(t)}</span><div class="ob-m">{html.escape(m)}</div>')
    if f.reference:
        out += f'<div class="ob-ref">{html.escape(f.reference)}</div>'
    if with_fix and s:
        out += f'<div class="ob-fix"><b>{"Vorschlag" if lang == "de" else "Suggestion"}:</b> {html.escape(s)}</div>'
    return out


def bar_list(rows: list[tuple[str, float]], fmt, signed: bool = False) -> str:
    """Ranked horizontal bars as plain HTML (label and value above a thin bar). signed=True: a minus value is a
    saving and gets a second colour and an explicit sign."""
    mx = max([abs(v) for _, v in rows] + [1e-9])
    out = []
    for label, v in rows:
        w = max(1.5, 100 * abs(v) / mx)
        val = (("+" if v > 0 else "−") + fmt(abs(v))) if signed and v else fmt(v)
        fill = f"width:{w:.1f}%" + (";background:#1F7A5C" if signed and v < 0 else "")
        out.append(f'<div class="ob-bar" title="{html.escape(label)}: {html.escape(val)}"><div class="ob-bl">'
                   f'<span>{html.escape(label)}</span><b>{html.escape(val)}</b></div>'
                   f'<div class="ob-track"><i style="{fill}"></i></div></div>')
    return '<div class="ob-bars">' + "".join(out) + "</div>"


def hero(lang: str) -> str:
    de = lang == "de"
    head = ("Jede Position bekommt ein Nachtragsrisiko in Euro." if de else
            "Every line item gets a change-order risk in euros.")
    sub = ("OpenBoQ liest Ihr Leistungsverzeichnis in jedem Format, findet fehlerhafte Positionen und Vertragsrisiken, "
           "schätzt den Betrag dahinter und schreibt die Bieterfragen gleich mit." if de else
           "OpenBoQ reads your bill of quantities in any format, finds faulty items and contract risks, puts a euro "
           "figure on each, and drafts the bidder questions for you.")
    steps = ([("Einlesen", "GAEB X81–X86 und D8x, PDF, Word, Excel, CSV – auch Druckbilder aus AVA-Programmen."),
              ("Prüfen", "35 Regeln für Rechnung, Einheiten, Preise, Texte und Klauseln, dazu eine KI-Tiefenprüfung mit "
                         "Gegenprüfung aus Auftraggebersicht."),
              ("Kalkulieren", "Zuschläge aus eigenen Projekten, Was-wäre-wenn für Materialpreise, fertige Bieterfragen.")]
             if de else
             [("Read", "GAEB X81–X86 and D8x, PDF, Word, Excel, CSV – including print layouts from estimating software."),
              ("Check", "35 rules for arithmetic, units, prices, wording and clauses, plus an AI deep check that a second "
                        "model challenges from the client's side."),
              ("Price", "Markups from your own past projects, what-if for material prices, ready-to-send bidder questions.")])
    cells = "".join(f"<div><b><i>{k}</i>{html.escape(a)}</b><span>{html.escape(b)}</span></div>"
                    for k, (a, b) in enumerate(steps, 1))
    return (f'<div class="ob-hero">{wordmark(height=92, stroke=1.8, draw=True)}'
            f'<h1>{html.escape(head)}</h1><p>{html.escape(sub)}</p></div><div class="ob-steps">{cells}</div>')


def make_favicon(path: Path = FAVICON) -> Path:
    """64 px PNG: a thin orange Q on ink – generated once, committed with the repo."""
    if path.exists():
        return path
    from PIL import Image, ImageDraw
    s = 4                                                     # draw large, scale down for smooth edges
    im = Image.new("RGBA", (64 * s, 64 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, 64 * s - 1, 64 * s - 1], radius=12 * s, fill=INK)
    w = 5 * s
    d.ellipse([14 * s, 12 * s, 48 * s, 46 * s], outline=ORANGE, width=w)
    d.line([38 * s, 37 * s, 51 * s, 51 * s], fill=ORANGE, width=w)
    path.parent.mkdir(exist_ok=True)
    im.resize((64, 64), Image.LANCZOS).save(path)
    return path
