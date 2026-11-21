"""Streamlit tab: what-if analyses (milestone 5) – material prices, quantities, alternatives."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from . import whatif as W
from .fmt import num

PRESETS = {   # name (de, en) -> driver changes
    ("Keine Änderung", "No change"): {},
    ("Stahlpreis +20 %", "Steel price +20 %"): {"steel": 0.20},
    ("Energiekrise (Diesel +40 %, Bitumen +25 %, Stahl +15 %, Kunststoff +20 %)",
     "Energy crisis (diesel +40 %, bitumen +25 %, steel +15 %, plastics +20 %)"):
        {"fuel": 0.40, "bitumen": 0.25, "steel": 0.15, "plastic": 0.20},
    ("Tarifrunde Bau (Lohn +6 %)", "Wage round (wages +6 %)"): {"labour": 0.06},
    ("Deponiekosten +30 %", "Landfill fees +30 %"): {"disposal": 0.30},
    ("Preisrückgang (Stahl −15 %, Diesel −10 %)", "Prices fall (steel −15 %, diesel −10 %)"): {"steel": -0.15, "fuel": -0.10},
}


@st.fragment   # sliders rerun only this tab, not the whole page
def whatif_tab(res, boq, lang: str, eur):
    de = lang == "de"
    L = (lambda a, b: a if de else b)
    sugg = res.price_suggestions
    ctx = W.contract_context(boq)

    names = [k[0] if de else k[1] for k in PRESETS]
    pick = st.selectbox(L("Szenario", "Scenario"), names, key="wi_preset")
    preset = list(PRESETS.values())[names.index(pick)]
    st.caption(L("Szenario wählen und einzelne Preise anpassen (Änderung gegenüber den Preisen im LV).",
                 "Choose a scenario and adjust individual prices (change against the prices in the BoQ)."))
    changes = {}
    cols = st.columns(3)
    for k, (d, (dn, en)) in enumerate(W.DRIVERS.items()):
        changes[d] = cols[k % 3].slider(dn if de else en, -30, 60, int(round(100 * preset.get(d, 0))), step=5,
                                        format="%d %%", key=f"wi_{d}_{pick}") / 100

    c1, c2 = st.columns(2)
    esc = c1.checkbox(L("Stoffpreisgleitklausel vereinbart (Stahl, Bitumen, Diesel, Kunststoff)",
                        "Material price escalation clause agreed (steel, bitumen, diesel, plastics)"),
                      value=ctx["escalation"], key="wi_esc",
                      help=L("Im LV erkannt" if ctx["escalation"] else "Im LV nicht gefunden",
                             "Found in the BoQ" if ctx["escalation"] else "Not found in the BoQ"))
    use_hist = False
    if res.history_info:
        use_hist = c2.checkbox(L("Mengen wie in früheren Projekten", "Quantities as in past projects"), key="wi_hist",
                               help=L("Abrechnungsmengen = LV-Menge × typische Ist/LV-Abweichung vergleichbarer Positionen",
                                      "Billed quantities = BoQ quantity × typical actual/planned deviation of comparable items"))
    qty = {oz: h.qty_ratio for oz, h in res.history_info.items() if h.qty_ratio} if use_hist else None
    r = W.run_scenario(boq, changes, sugg, qty_ratio=qty, escalation=esc)

    if r.priced == 0:
        st.info(L("Keine Preise im LV und keine Vergleichspreise gefunden – Was-wäre-wenn braucht Einheitspreise.",
                  "No prices in the BoQ and no comparable prices – what-if needs unit prices."))
        return
    if r.suggested:
        st.caption(L(f"{r.suggested} von {r.priced} Positionen ohne eigenen Preis – dort wird der Vergleichspreis aus "
                     "früheren Projekten verwendet.",
                     f"{r.suggested} of {r.priced} items have no own price – the comparable price from past projects is used."))

    m1, m2, m3, m4 = st.container(key="kpis_wi").columns(4)
    m1.metric(L("Angebotssumme (LV-Preise)", "Bid total (BoQ prices)"), eur(r.base_total))
    m2.metric(L("Mehrkosten durch Preise", "Extra cost from prices"), eur(r.material),
              f"{'+' if r.material >= 0 else ''}{num(100 * r.material / r.base_total, 1, lang)} %" if r.base_total else None,
              delta_color="inverse")
    m3.metric(L("Trägt der AN", "Carried by contractor"), eur(r.carried),
              help=L("Preisänderung, die keine Gleitklausel abdeckt, + Gemeinkosten, die bei Mindermengen nicht mehr gedeckt sind",
                     "Price change not covered by an escalation clause + overheads no longer recovered on reduced quantities"))
    if qty:
        m4.metric(L("Umsatz durch Mengen", "Revenue from quantities"), eur(r.qty_revenue),
                  help=L("Abrechnung nach Aufmaß zu Angebotspreisen", "Billed as measured at bid prices"))
    else:
        m4.metric(L("Über Gleitklausel erstattet", "Passed on via escalation clause"), eur(r.passed_on))
    carried = r.carried
    if carried > 0 and ctx["fixed"] and not esc:
        st.error(L(f"Festpreis ohne Gleitklausel: {eur(carried)} Mehrkosten gehen voll zu Lasten der Marge. "
                   "Gleitklausel (Formblatt 225) als Bieterfrage anregen oder Risiko einpreisen.",
                   f"Fixed price without escalation clause: {eur(carried)} extra cost comes straight out of the margin. "
                   "Ask for an escalation clause (Formblatt 225) or price the risk in."))
    margin = st.slider(L("Kalkulierte Marge (W&G)", "Planned margin (profit)"), 0, 15, 4, format="%d %%", key="wi_margin") / 100
    if r.base_total and margin:
        left = margin * r.base_total - max(0.0, carried)
        st.caption(L(f"Marge {eur(margin * r.base_total)} → nach Szenario {eur(left)} "
                     f"({num(100 * left / r.base_total, 1, lang)} % statt {num(100 * margin, 0, lang)} %).",
                     f"Margin {eur(margin * r.base_total)} → after scenario {eur(left)} "
                     f"({num(100 * left / r.base_total, 1, lang)} % instead of {num(100 * margin, 0, lang)} %)."))

    # ---- by driver + sensitivity (plain HTML bars: full labels, exact values, nothing extra to load)
    from .ui_theme import bar_list
    name = lambda k: W.DRIVERS[k][0] if de else W.DRIVERS[k][1]
    a, b = st.columns(2, gap="large")
    with a:
        st.markdown("**" + L("Wirkung je Preistreiber", "Effect per cost driver") + "**")
        bd = sorted(((name(k), v) for k, v in r.by_driver.items() if abs(v) >= 1), key=lambda kv: -abs(kv[1]))
        if bd:
            st.markdown(bar_list(bd, eur, signed=True), unsafe_allow_html=True)
        else:
            st.caption(L("Keine Preisänderung gewählt.", "No price change selected."))
    with b:
        st.markdown("**" + L("Empfindlichkeit: +10 % je Preistreiber", "Sensitivity: +10 % per driver") + "**")
        sens = sorted(((name(k), v) for k, v in W.sensitivity(boq, sugg) if abs(v) >= 1), key=lambda kv: -abs(kv[1]))
        st.markdown(bar_list(sens, eur, signed=True), unsafe_allow_html=True)
        st.caption(L("Welche Preisentwicklung dieses Angebot am stärksten trifft.",
                     "Which price movement hits this bid hardest."))

    # ---- items
    st.markdown("**" + L("Am stärksten betroffene Positionen", "Most affected items") + "**")
    items = sorted(r.items, key=lambda x: -abs(x["delta"]))[:25]
    idf = pd.DataFrame([{
        L("OZ", "Item"): x["oz"], L("Kurztext", "Short text"): x["short_text"][:70],
        L("Kostenstruktur", "Cost structure"): ", ".join(f"{(W.DRIVERS[k][0] if de else W.DRIVERS[k][1]).split(' ')[0]} "
                                                          f"{100 * v:.0f} %" for k, v in x["shares"].items()),
        L("EP", "Unit price"): round(x["up"], 2), L("EP neu", "New unit price"): round(x["up_new"], 2),
        L("Menge", "Qty"): round(x["qty"], 2), L("Menge neu", "New qty"): round(x["qty_new"], 2),
        "Δ €": round(x["delta"], 0), L("Vergleichspreis", "Comparable price"): "✓" if x["suggested"] else ""}
        for x in items if abs(x["delta"]) >= 1])
    if len(idf):
        st.dataframe(idf, hide_index=True, width="stretch")

    # ---- alternatives
    st.markdown("**" + L("Alternativen", "Alternatives") + "**")
    alts = W.alternatives(boq, sugg)
    if not alts:
        st.caption(L("Keine Positionen mit austauschbarer Spezifikation erkannt (Betonklasse, Deponieklasse, Rohrwerkstoff, "
                     "Asphaltdicke).", "No items with a swappable specification found (concrete class, disposal class, pipe "
                     "material, asphalt thickness)."))
    else:
        kinds = {"nebenangebot": L("💡 Nebenangebot (Einsparung)", "💡 Alternative offer (saving)"),
                 "risk": L("⚠️ Risiko (Mehrkosten)", "⚠️ Risk (extra cost)")}
        adf = pd.DataFrame([{
            L("Art", "Kind"): kinds[x["kind"]], L("OZ", "Item"): x["oz"], L("Kurztext", "Short text"): x["short_text"][:60],
            L("Heute", "Now"): x["current"] if de else x["current_en"],
            L("Alternative", "Alternative"): x["alternative"] if de else x["alternative_en"],
            L("EP", "Unit price"): round(x["up"], 2), L("EP Alternative", "Alt. unit price"): round(x["up_new"], 2),
            "Δ €": round(x["delta_total"], 0), L("Hinweis", "Note"): x["note_de"] if de else x["note_en"]} for x in alts])
        st.dataframe(adf, hide_index=True, width="stretch")
        sav = sum(x["delta_total"] for x in alts if x["kind"] == "nebenangebot" and x["delta_total"] < 0)
        rsk = sum(x["delta_total"] for x in alts if x["kind"] == "risk")
        st.caption(L(f"Einsparpotenzial durch Nebenangebote bis {eur(-sav)} · Mehrkostenrisiko bis {eur(rsk)} "
                     "(je Position nur die günstigste bzw. nächsthöhere Variante zählen).",
                     f"Saving potential from alternative offers up to {eur(-sav)} · extra-cost risk up to {eur(rsk)} "
                     "(per item count only the cheapest / next-higher variant)."))

    with st.expander(L("Annahmen: Kostenstruktur je Leistungsart", "Assumptions: cost structure per kind of work")):
        from . import knowledge as K
        labels = {w.key: w.label for w in K.WORK_TYPES}
        st.dataframe(pd.DataFrame([{L("Leistungsart", "Kind of work"): labels.get(k, k),
                                    **{(W.DRIVERS[d][0] if de else W.DRIVERS[d][1]): f"{100 * v:.0f} %" for d, v in sh.items()}}
                                   for k, sh in W.SHARES.items()]).fillna(""), hide_index=True, width="stretch")
        st.caption(L("Anteile am Einheitspreis, typische Werte aus Tief- und Rohbaukalkulationen. Der Rest (Gerät, "
                     "Gemeinkosten, Gewinn) bewegt sich im Szenario nicht.",
                     "Shares of the unit price, typical values from civil-works calculations. The rest (plant, overheads, "
                     "profit) does not move in the scenario."))

    def _xlsx(changes=dict(changes), r=r, alts=alts) -> bytes:      # built only when the button is clicked
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            pd.DataFrame([{L("Preistreiber", "Driver"): (W.DRIVERS[k][0] if de else W.DRIVERS[k][1]),
                           L("Änderung", "Change"): f"{100 * changes[k]:+.0f} %", "Δ €": round(r.by_driver[k], 2)}
                          for k in W.DRIVERS]).to_excel(xw, sheet_name=L("Szenario", "Scenario"), index=False)
            pd.DataFrame(r.items).drop(columns=["shares"]).to_excel(xw, sheet_name=L("Positionen", "Items"), index=False)
            if alts:
                pd.DataFrame(alts).to_excel(xw, sheet_name=L("Alternativen", "Alternatives"), index=False)
        return buf.getvalue()
    st.download_button(L("Szenario als Excel", "Scenario as Excel"), _xlsx, file_name="openboq_whatif.xlsx",
                       icon=":material/download:", on_click="ignore")
