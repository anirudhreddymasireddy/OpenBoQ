"""Streamlit tab: historical project data (milestone 4) – source, what was learned, markup suggestions."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from . import history as H
from .fmt import num

DATA = Path(__file__).resolve().parent.parent / "data"


def _example_source() -> list[dict]:
    """Item texts for the simulated example: the price database if built, otherwise the built-in sample BoQ."""
    p = DATA / "price_db.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    from .sample import make_sample_boq
    return [{"short": i.short_text, "unit": i.unit, "up": i.up, "oz": i.oz} for i in make_sample_boq().items if i.up]


def _set_source(path: str | None):
    st.session_state["history_path"] = path
    st.rerun()


def history_tab(res, boq, lang: str, eur):
    de = lang == "de"
    L = (lambda a, b: a if de else b)
    model = res.history_model

    # ---- source
    with st.container(border=True):
        st.markdown("**" + L("Datenquelle: abgeschlossene Projekte", "Data source: finished projects") + "**")
        if model is None:
            st.caption(L("Noch keine Projekthistorie geladen. Eine Datei mit Soll/Ist-Mengen, Soll/Ist-Kosten und Nachträgen "
                         "je Position hochladen – oder die simulierten Beispieldaten laden, um die Funktion zu sehen.",
                         "No project history loaded yet. Upload a file with planned/actual quantities, planned/actual costs and "
                         "change orders per item – or load the simulated example data to see how it works."))
        else:
            co = sum(r["change_order"] for r in model.rows)
            st.caption(L(f"{len(model.projects)} Projekte · {len(model.rows)} Positionen · {co} mit Nachtrag",
                         f"{len(model.projects)} projects · {len(model.rows)} items · {co} with change order"))
            if model.example:
                st.warning(L("⚠️ Beispieldaten – **simuliert** (echte Positionstexte, erfundene Ist-Werte). Nur zur Demonstration; "
                             "für echte Aussagen die eigene Nachkalkulation hochladen.",
                             "⚠️ Example data – **simulated** (real item texts, invented actuals). Demonstration only; upload your "
                             "own post-calculation for real conclusions."))
        c1, c2, c3 = st.columns([3, 2, 2])
        up = c1.file_uploader(L("Projekthistorie (CSV / Excel)", "Project history (CSV / Excel)"), type=["csv", "xlsx"],
                              key="hist_up", label_visibility="collapsed")
        if up is not None and st.session_state.get("hist_up_name") != up.name:
            DATA.mkdir(exist_ok=True)
            p = DATA / f"history_upload_{Path(up.name).stem}{Path(up.name).suffix.lower()}"
            p.write_bytes(up.getbuffer())
            try:
                H.read_history(p)
                st.session_state["hist_up_name"] = up.name
                _set_source(str(p))
            except Exception as e:
                st.error(f"{type(e).__name__}: {e}")
        if c2.button(L("Beispieldaten (simuliert) laden", "Load example data (simulated)"), width="stretch"):
            if not H.EXAMPLE_PATH.exists():
                H.make_example(_example_source())
            _set_source(str(H.EXAMPLE_PATH))
        c3.download_button(L("Vorlage herunterladen", "Download template"), H.template_csv(),
                           file_name="openboq_history_template.csv", width="stretch")
        if model is not None and not model.example and st.session_state.get("history_path") \
                and st.session_state["history_path"] != str(H.HISTORY_PATH):
            if st.button(L("Als Standard für alle Prüfungen speichern", "Save as default for all checks")):
                H.HISTORY_PATH.write_bytes(Path(st.session_state["history_path"]).read_bytes()) \
                    if st.session_state["history_path"].endswith(".csv") else \
                    pd.DataFrame(H.read_history(st.session_state["history_path"])).to_csv(H.HISTORY_PATH, sep=";", index=False)
                _set_source(None)
        if st.session_state.get("history_path") and st.button(L("Historie entfernen", "Remove history")):
            st.session_state["hist_up_name"] = None
            _set_source("none")

    if model is None:
        st.markdown(L(
            "**So funktioniert es:** Für jede Position werden vergleichbare Positionen aus früheren Projekten gesucht "
            "(Textähnlichkeit, sonst gleiche Leistungsart, mindestens 3). Daraus folgen: typische **Mengenabweichung** "
            "(VOB/B § 2 Abs. 3), **Nachtragsquote** und -höhe mit Gründen, **Kostenunterdeckung** je Einheit – und ein "
            "**Zuschlagsvorschlag** je Position. Die eigenen Einheitspreise fließen zusätzlich in die Preisvorschläge ein.",
            "**How it works:** for every item, comparable items from past projects are found (text similarity, otherwise the "
            "same kind of work, at least 3). From them: typical **quantity deviation** (VOB/B § 2(3)), **change-order rate** "
            "and size with reasons, **unit-cost shortfall** – and a **markup suggestion** per item. Your own unit prices also "
            "feed the price suggestions."))
        return

    info = res.history_info
    # ---- headline
    from .whatif import unit_price
    matched = len(info)
    co_exp = H.expected_change_orders(info, boq, res.price_suggestions)
    qty_eff = 0.0
    for it in boq.items:
        h = info.get(it.oz)
        up, _ = unit_price(it, res.price_suggestions)
        if h and h.qty_ratio and up and it.qty:
            qty_eff += (h.qty_ratio - 1) * it.qty * up
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(L("Positionen mit Erfahrungswerten", "Items with experience data"), f"{matched} / {len(boq.items)}")
    m2.metric(L("Erwartetes Nachtragsvolumen", "Expected change-order volume"), eur(co_exp),
              help=L("Σ Positionswert × Nachtragsquote × typische Nachtragshöhe vergleichbarer Positionen",
                     "Σ item value × change-order rate × typical change-order size of comparable items"))
    m3.metric(L("Erwarteter Mengeneffekt", "Expected quantity effect"), eur(qty_eff),
              help=L("Σ (Ist/LV-Menge − 1) × LV-Menge × EP – Mehr- (+) oder Minderumsatz (−) bei Abrechnung nach Aufmaß",
                     "Σ (actual/planned − 1) × planned qty × unit price – more (+) or less (−) revenue when billed as measured"))

    base = st.slider(L("Basiszuschlag (AGK + Wagnis & Gewinn)", "Base markup (overheads + risk & profit)"), 0, 30, 12,
                     format="%d %%", key="base_markup") / 100
    rows = H.markup_table(boq, res.flags, info, res.price_suggestions, base=base)
    tot_v = sum(r["value"] for r in rows) or 1
    avg = sum(r["markup"] * r["value"] for r in rows) / tot_v
    m4.metric(L("Ø Zuschlagsvorschlag", "Avg. suggested markup"), f"{num(100 * avg, 1, lang)} %",
              f"{num(100 * (avg - base), 1, lang)} {L('Pkt. Risiko', 'pts risk')}", delta_color="off")

    # ---- per-item table
    tab = []
    for r in rows:
        it = boq.by_oz()[r["oz"]]
        h = info.get(r["oz"])
        up, is_s = unit_price(it, res.price_suggestions)
        tab.append({
            L("OZ", "Item"): r["oz"], L("Kurztext", "Short text"): r["short_text"][:70],
            L("Wert €", "Value €"): round(r["value"], 0),
            "n": h.n if h else None,
            L("Basis", "Basis"): (L("ähnliche Texte", "similar texts") if h.basis == "similar" else h.label) if h else "",
            L("Menge Ist/LV", "Qty actual/planned"): round(h.qty_ratio, 2) if h and h.qty_ratio else None,
            L("Nachtragsquote", "Change-order rate"): f"{100 * h.co_rate:.0f} %" if h else "",
            L("Kosten Ist/Soll je Einheit", "Unit cost actual/planned"): round(h.cost_ratio, 2) if h and h.cost_ratio else None,
            L("Typische Nachtragsgründe", "Typical change-order reasons"): "; ".join(h.reasons) if h else "",
            L("Zuschlag Basis", "Base markup"): f"{100 * r['base']:.0f} %",
            L("+ Historie", "+ history"): f"{100 * r['history']:.1f} %" if r["history"] else "",
            L("+ Befunde", "+ findings"): f"{100 * r['findings']:.1f} %" if r["findings"] else "",
            L("Zuschlag Vorschlag", "Suggested markup"): f"{100 * r['markup']:.1f} %",
            L("EP aktuell", "Unit price now"): round(up, 2) if up else None,
            L("EP-Vorschlag", "Suggested unit price"): round(H.suggested_up(up, r["markup"], base), 2) if up else None,
        })
    df = pd.DataFrame(tab)
    only = st.checkbox(L("Nur Positionen mit Erfahrungswerten oder Risikozuschlag", "Only items with experience data or a risk surcharge"),
                       value=True)
    if only:
        df = df[(df["n"].notna()) | (df[L("+ Befunde", "+ findings")] != "")]
    st.dataframe(df, hide_index=True, width="stretch", height=420)
    st.download_button(L("Zuschlagstabelle (CSV)", "Markup table (CSV)"), df.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       file_name="openboq_markups.csv")
    st.caption(L(
        "Zuschlag = Basiszuschlag + Historie (Kostenunterdeckung je Einheit vergleichbarer Positionen; bei Pauschalen die "
        "Mengenüberschreitung; bei typischen Mindermengen die nicht mehr gedeckten Gemeinkosten) + Befunde (Risiko-Befunde dieser Position in € / Positionswert, max. 15 %). "
        "EP-Vorschlag = EP ÷ (1 + Basis) × (1 + Vorschlag). Nachtragspotenzial wird bewusst **nicht** vom Zuschlag abgezogen.",
        "Markup = base + history (unit-cost shortfall of comparable items; for lump sums the quantity overrun; for typical "
        "quantity shortfalls the overheads no longer recovered) + findings "
        "(risk findings of this item in € / item value, max 15 %). Suggested unit price = price ÷ (1 + base) × (1 + suggested). "
        "Change-order potential is deliberately **not** deducted from the markup."))
