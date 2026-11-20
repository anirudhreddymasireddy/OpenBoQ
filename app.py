"""OpenBoQ – Streamlit demo dashboard.

Run:  streamlit run app.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from openboq.fmt import de
from openboq.gaeb_parser import load_boq, parse_gaeb_xml
from openboq.inject import inject
from openboq.pipeline import analyze
from openboq.report import SEV_LABEL, to_excel, to_html
from openboq.sample import make_sample_boq
from openboq.sample_ifc import make_sample_ifc

st.set_page_config(page_title="OpenBoQ", page_icon="📐", layout="wide")
DATA = Path(__file__).parent / "data"
SEV_ICON = {"high": "🔴", "medium": "🟠", "low": "⚪", "info": "🔵"}


def eur(v):
    return f"{de(v, 0)} €"


def _save(upload) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / upload.name
    p.write_bytes(upload.getvalue())
    return p


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## 📐 OpenBoQ")
    st.caption("KI-Prüfung von Leistungsverzeichnissen: Fehler, Lücken und Nachtragsrisiko in €.")
    lv_up = st.file_uploader("LV (GAEB X81–X86, CSV, XLSX)", type=["x81", "x83", "x84", "x86", "xml", "csv", "xlsx"])
    ifc_up = st.file_uploader("IFC-Modell (optional)", type=["ifc"])
    demo = st.button("Demo-Daten laden", width="stretch")
    seed = st.number_input("Demo: Zufallsfehler (Seed)", 0, 999, 1, help="Pflanzt bekannte Fehler in ein sauberes LV.")
    st.divider()
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    use_llm = st.toggle("KI-Tiefenprüfung (Claude)", value=False, disabled=not has_key,
                        help="Benötigt ANTHROPIC_API_KEY" if not has_key else "Semantische Prüfung + Management-Summary")

if demo:
    DATA.mkdir(exist_ok=True)
    buggy, truth = inject(make_sample_boq(), n_item=10, n_lv=2, seed=int(seed))
    make_sample_ifc(DATA / "sample_model.ifc")
    st.session_state["boq"] = buggy
    st.session_state["ifc"] = str(DATA / "sample_model.ifc")
    st.session_state["truth"] = truth
elif lv_up is not None:
    st.session_state["boq"] = load_boq(_save(lv_up))
    st.session_state["ifc"] = str(_save(ifc_up)) if ifc_up else None
    st.session_state["truth"] = None

boq = st.session_state.get("boq")
if boq is None:
    st.title("OpenBoQ")
    st.markdown(
        "**Jede Position bekommt ein Nachtragsrisiko in Euro.**\n\n"
        "1. **Regelprüfung** – Rechenfehler, Einheiten, Pauschalen, Doppelpositionen, Preisausreißer, unklare Texte, "
        "fehlende Pflichtangaben, veraltete Normen, fehlende Begleitpositionen\n"
        "2. **IFC-Abgleich** – Modellmengen vs. Vordersätze, > 10 % = VOB/B § 2 Abs. 3; Bauteile ohne LV-Position = § 2 Abs. 6\n"
        "3. **KI-Tiefenprüfung** – was Regeln nicht sehen, plus Korrekturvorschläge im STLB-Bau-Stil\n\n"
        "← LV hochladen oder **Demo-Daten laden**.")
    st.stop()

ck = (id(boq), st.session_state.get("ifc"), use_llm)
if st.session_state.get("ck") != ck:
    with st.spinner("Prüfe LV …"):
        st.session_state["res"] = analyze(boq, ifc=st.session_state.get("ifc"), use_llm=use_llm)
    st.session_state["ck"] = ck
res = st.session_state["res"]

# ---------------------------------------------------------------- header + KPIs
st.title(boq.project or boq.name or "Leistungsverzeichnis")
st.caption(f"{boq.name} · GAEB DA {boq.phase or '–'} · {len(boq.items)} Positionen · LV-Summe {eur(boq.total)} · "
           f"Analyse in {res.seconds*1000:.0f} ms")
sev = res.by_severity()
c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
c1.metric("Geschätztes Nachtragsrisiko", eur(res.exposure), f"{de(100*res.exposure/max(boq.total,1),1)} % der LV-Summe",
          delta_color="inverse")
c2.metric("Hohe Befunde", sev["high"])
c3.metric("Mittlere Befunde", sev["medium"])
c4.metric("Betroffene Positionen", len(res.item_risk()))
if res.summary:
    st.info(res.summary)

tab_top, tab_all, tab_pos, tab_ifc, tab_eval = st.tabs(["Top-Risiken", "Alle Befunde", "Positionen", "IFC-Abgleich", "Bewertung"])

with tab_top:
    for f in sorted(res.counted, key=lambda f: -f.exposure_eur)[:10]:
        with st.container(border=True):
            a, b = st.columns([5, 1])
            a.markdown(f"{SEV_ICON[f.severity]} **{f.oz or 'LV'} · {f.title}**  \n{f.message}")
            a.caption(f"{f.reference}" + (f"  \n→ {f.suggestion}" if f.suggestion else ""))
            b.markdown(f"### {eur(f.exposure_eur)}")

with tab_all:
    df = pd.DataFrame([{
        "": SEV_ICON[f.severity], "Schwere": SEV_LABEL[f.severity], "OZ": f.oz or "LV", "Befund": f.title,
        "Erläuterung": f.message, "Grundlage": f.reference, "Vorschlag": f.suggestion, "Quelle": f.source,
        "Risiko €": round(f.exposure_eur, 0)} for f in res.flags])
    f1, f2 = st.columns(2)
    sel_sev = f1.multiselect("Schwere", list(SEV_LABEL.values()), default=["Hoch", "Mittel"])
    sel_src = f2.multiselect("Quelle", sorted(df["Quelle"].unique()) if len(df) else [], default=None)
    view = df[df["Schwere"].isin(sel_sev)] if sel_sev else df
    if sel_src:
        view = view[view["Quelle"].isin(sel_src)]
    st.dataframe(view, width="stretch", hide_index=True,
                 column_config={"Risiko €": st.column_config.NumberColumn(format="%.0f €")})

with tab_pos:
    risk = res.item_risk()
    pos = pd.DataFrame([{
        "": SEV_ICON.get(risk.get(i.oz, {}).get("severity"), "🟢"), "OZ": i.oz, "Kurztext": i.short_text,
        "Menge": i.qty, "Einheit": i.unit, "EP": i.up, "GP": i.it, "Risiko €": round(risk.get(i.oz, {}).get("exposure", 0), 0),
    } for i in boq.items])
    st.dataframe(pos, width="stretch", hide_index=True, height=420)
    oz = st.selectbox("Position im Detail", [i.oz for i in boq.items],
                      format_func=lambda o: f"{o} – {boq.by_oz()[o].short_text}")
    it = boq.by_oz()[oz]
    st.markdown(f"**{it.short_text}**  \n{it.long_text}")
    its_flags = [f for f in res.flags if f.oz == oz]
    for f in its_flags:
        st.markdown(f"{SEV_ICON[f.severity]} **{f.title}** – {f.message}  \n*{f.reference}*")
    if its_flags and has_key and st.button("✍️ Korrigierten Langtext vorschlagen (KI)"):
        from openboq.llm_checks import llm_fix_text
        with st.spinner("Formuliere …"):
            st.success(llm_fix_text(it, its_flags))

with tab_ifc:
    if res.ifc_table:
        t = pd.DataFrame(res.ifc_table)
        t["Abweichung"] = t["Abweichung"].map(lambda v: "" if pd.isna(v) else f"{v:+.1%}")
        st.dataframe(t, width="stretch", hide_index=True)
        st.caption("> 10 % Abweichung: neuer Einheitspreis kann verlangt werden (VOB/B § 2 Abs. 3). "
                   "Bauteile ohne LV-Position: zusätzliche Leistung (VOB/B § 2 Abs. 6).")
    else:
        st.info("Kein IFC-Modell geladen.")

with tab_eval:
    truth = st.session_state.get("truth")
    if truth:
        from openboq.evaluate import score
        found, fps, _ = score(res.flags, truth)
        st.metric("Gefundene eingepflanzte Fehler", f"{sum(found)} / {len(truth)}")
        st.dataframe(pd.DataFrame([{"Fehlertyp": g["type"], "OZ": g["oz"] or g.get("match", ""), "Gefunden": "✅" if ok else "❌"}
                                   for g, ok in zip(truth, found)]), hide_index=True, width="stretch")
        st.caption(f"Fehlalarme (hoch/mittel) außerhalb der eingepflanzten Fehler: {len(fps)}")
    else:
        st.info("Bewertung nur mit Demo-Daten (bekannte eingepflanzte Fehler).")

st.divider()
d1, d2 = st.columns(2)
d1.download_button("⬇️ Bericht (HTML)", to_html(res), file_name="openboq_bericht.html", mime="text/html",
                   width="stretch")
xlsx = Path(tempfile.mkdtemp()) / "openboq.xlsx"
to_excel(res, xlsx)
d2.download_button("⬇️ Befunde (Excel)", xlsx.read_bytes(), file_name="openboq_befunde.xlsx", width="stretch")
