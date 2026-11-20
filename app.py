"""OpenBoQ – Streamlit dashboard (German / English).

Run:  streamlit run app.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from openboq.fmt import money, num
from openboq.gaeb_parser import load_boq
from openboq.i18n import LANGS, T, sev_label, src_label
from openboq.inject import inject
from openboq.pipeline import analyze
from openboq.report import to_excel, to_html
from openboq.sample import make_sample_boq
from openboq.sample_ifc import make_sample_ifc

st.set_page_config(page_title="OpenBoQ", page_icon="📐", layout="wide")
DATA = Path(__file__).parent / "data"
SEV_ICON = {"high": "🔴", "medium": "🟠", "low": "⚪", "info": "🔵"}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]          # keep German noun capitals ("Hohe Befunde")


def _save(upload) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / upload.name
    p.write_bytes(upload.getvalue())
    return p


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## 📐 OpenBoQ")
    lang = st.radio("Sprache / Language", list(LANGS), format_func=LANGS.get, horizontal=True, key="lang")
    eur = lambda v: money(v, lang)
    st.caption(T("tagline", lang))
    lv_up = st.file_uploader(T("upload_lv", lang),
                             type=["x81", "x83", "x84", "x86", "xml", "d81", "d83", "d84", "d86", "pdf", "csv", "xlsx"])
    ifc_up = st.file_uploader(T("upload_ifc", lang), type=["ifc"])
    demo = st.button(T("load_demo", lang), width="stretch")
    seed = st.number_input(T("demo_seed", lang), 0, 999, 1, help=T("demo_seed_help", lang))
    st.divider()
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    use_llm = st.toggle(T("ai_toggle", lang), value=False, disabled=not has_key,
                        help=T("ai_needs_key", lang) if not has_key else T("ai_help", lang))

if demo:
    DATA.mkdir(exist_ok=True)
    buggy, truth = inject(make_sample_boq(), n_item=10, n_lv=2, seed=int(seed))
    make_sample_ifc(DATA / "sample_model.ifc")
    st.session_state["boq"] = buggy
    st.session_state["ifc"] = str(DATA / "sample_model.ifc")
    st.session_state["truth"] = truth
elif lv_up is not None and st.session_state.get("upload_name") != (lv_up.name, ifc_up.name if ifc_up else None):
    st.session_state["boq"] = load_boq(_save(lv_up))
    st.session_state["ifc"] = str(_save(ifc_up)) if ifc_up else None
    st.session_state["truth"] = None
    st.session_state["upload_name"] = (lv_up.name, ifc_up.name if ifc_up else None)

boq = st.session_state.get("boq")
if boq is None:
    st.title("OpenBoQ")
    st.markdown(T("intro", lang))
    st.stop()

# rules/IFC findings carry both languages; only the AI layer depends on the language
ck = (id(boq), st.session_state.get("ifc"), use_llm, lang if use_llm else "-")
if st.session_state.get("ck") != ck:
    with st.spinner(T("checking", lang)):
        st.session_state["res"] = analyze(boq, ifc=st.session_state.get("ifc"), use_llm=use_llm, lang=lang)
    st.session_state["ck"] = ck
res = st.session_state["res"]

# ---------------------------------------------------------------- header + KPIs
st.title(boq.project or boq.name or "BoQ")
st.caption(f"{boq.name} · GAEB DA {boq.phase or '–'} · {len(boq.items)} {T('items', lang)} · "
           f"{T('lv_sum', lang)} {eur(boq.total)} · {T('analysis_in', lang)} {res.seconds*1000:.0f} ms")
sev = res.by_severity()
c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
c1.metric(T("risk", lang), eur(res.exposure),
          f"{num(100 * res.exposure / max(boq.total, 1), 1, lang)} % {T('of_total', lang)}", delta_color="inverse")
c2.metric(_cap(T("high", lang)), sev["high"])
c3.metric(_cap(T("medium", lang)), sev["medium"])
c4.metric(_cap(T("affected", lang)), len(res.item_risk()))
if res.summary:
    st.info(res.summary)

tab_top, tab_all, tab_pos, tab_ifc, tab_eval = st.tabs(
    [T("tab_top", lang), T("tab_all", lang), T("tab_pos", lang), T("tab_ifc", lang), T("tab_eval", lang)])

with tab_top:
    for f in sorted(res.counted, key=lambda f: -f.exposure_eur)[:10]:
        t, m, s = f.txt(lang)
        with st.container(border=True):
            a, b = st.columns([5, 1])
            a.markdown(f"{SEV_ICON[f.severity]} **{f.oz or T('lv_wide', lang)} · {t}**  \n{m}")
            a.caption(f"{f.reference}" + (f"  \n→ {s}" if s else ""))
            b.markdown(f"### {eur(f.exposure_eur)}")

with tab_all:
    rows = []
    for f in res.flags:
        t, m, s = f.txt(lang)
        rows.append({"": SEV_ICON[f.severity], T("f_severity", lang): sev_label(f.severity, lang),
                     T("c_oz", lang): f.oz or T("lv_wide", lang), T("c_finding", lang): t, T("c_expl", lang): m,
                     T("c_basis", lang): f.reference, T("c_fix", lang): s, T("f_source", lang): src_label(f.source, lang),
                     T("c_risk", lang): round(f.exposure_eur, 0)})
    df = pd.DataFrame(rows)
    f1, f2 = st.columns(2)
    sev_opts = [sev_label(k, lang) for k in ("high", "medium", "low", "info")]
    sel_sev = f1.multiselect(T("f_severity", lang), sev_opts, default=sev_opts[:2])
    src_col = T("f_source", lang)
    sel_src = f2.multiselect(T("f_source", lang), sorted(df[src_col].unique()) if len(df) else [], default=None)
    view = df[df[T("f_severity", lang)].isin(sel_sev)] if (sel_sev and len(df)) else df
    if sel_src:
        view = view[view[src_col].isin(sel_src)]
    st.dataframe(view, width="stretch", hide_index=True,
                 column_config={T("c_risk", lang): st.column_config.NumberColumn(format="%.0f €")})

with tab_pos:
    risk = res.item_risk()
    pos = pd.DataFrame([{
        "": SEV_ICON.get(risk.get(i.oz, {}).get("severity"), "🟢"), T("c_oz", lang): i.oz, T("c_short", lang): i.short_text,
        T("c_qty", lang): i.qty, T("c_unit", lang): i.unit, T("c_up", lang): i.up, T("c_it", lang): i.it,
        T("c_risk", lang): round(risk.get(i.oz, {}).get("exposure", 0), 0),
    } for i in boq.items])
    st.dataframe(pos, width="stretch", hide_index=True, height=420)
    if boq.items:
        oz = st.selectbox(T("pos_detail", lang), [i.oz for i in boq.items],
                          format_func=lambda o: f"{o} – {boq.by_oz()[o].short_text}")
        it = boq.by_oz()[oz]
        st.markdown(f"**{it.short_text}**  \n{it.long_text}")
        its_flags = [f for f in res.flags if f.oz == oz]
        for f in its_flags:
            t, m, _ = f.txt(lang)
            st.markdown(f"{SEV_ICON[f.severity]} **{t}** – {m}  \n*{f.reference}*")
        if its_flags and has_key and st.button(T("fix_btn", lang)):
            from openboq.llm_checks import llm_fix_text
            with st.spinner(T("fixing", lang)):
                st.success(llm_fix_text(it, its_flags))

with tab_ifc:
    if res.ifc_table:
        from openboq.ifc_check import MAPPING_EN
        t = pd.DataFrame(res.ifc_table)
        if lang == "en":
            t["Prüfgruppe"] = t["Prüfgruppe"].map(lambda g: MAPPING_EN.get(g, g))
            t["Status"] = t["Status"].map(lambda s: T("st_" + s, "en"))
        t["Abweichung"] = t["Abweichung"].map(lambda v: "" if pd.isna(v) else f"{v:+.1%}")
        t = t.rename(columns={"Prüfgruppe": T("col_group", lang), "Bauteile": T("col_elements", lang),
                              "Modell": T("col_model", lang), "LV": T("col_lv", lang), "Einheit": T("col_unit", lang),
                              "Abweichung": T("col_dev", lang), "OZ": T("c_oz", lang)})
        st.dataframe(t, width="stretch", hide_index=True)
        st.caption(T("ifc_caption", lang))
    else:
        st.info(T("no_ifc", lang))

with tab_eval:
    truth = st.session_state.get("truth")
    if truth:
        from openboq.evaluate import score
        found, fps, _ = score(res.flags, truth)
        st.metric(T("eval_found", lang), f"{sum(found)} / {len(truth)}")
        st.dataframe(pd.DataFrame([{T("eval_type", lang): g["type"], T("c_oz", lang): g["oz"] or g.get("match", ""),
                                    T("eval_hit", lang): "✅" if ok else "❌"} for g, ok in zip(truth, found)]),
                     hide_index=True, width="stretch")
        st.caption(f"{T('eval_fp', lang)}: {len(fps)}")
    else:
        st.info(T("eval_only_demo", lang))

st.divider()
d1, d2 = st.columns(2)
d1.download_button(T("dl_html", lang), to_html(res, lang), file_name=f"openboq_report_{lang}.html", mime="text/html",
                   width="stretch")
xlsx = Path(tempfile.mkdtemp()) / "openboq.xlsx"
to_excel(res, xlsx, lang)
d2.download_button(T("dl_xlsx", lang), xlsx.read_bytes(), file_name=f"openboq_findings_{lang}.xlsx", width="stretch")
