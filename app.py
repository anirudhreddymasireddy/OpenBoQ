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
from openboq.i18n import LANGS, T, category_counts, questions, rule_name, sev_label, src_label
from openboq import auth
from openboq import userrules
from openboq.feedback import FeedbackStore, is_dismissed
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
    if auth.enabled() and st.session_state.get("user"):
        st.caption(f"👤 {T('logged_in_as', lang)} **{st.session_state['user']['name']}**")
        if st.button(T("logout", lang)):
            st.session_state.pop("user", None)
            st.rerun()
    lv_up = st.file_uploader(T("upload_lv", lang),
                             type=["x81", "x83", "x84", "x86", "xml", "d81", "d83", "d84", "d86", "pdf", "csv", "xlsx"])
    ifc_up = st.file_uploader(T("upload_ifc", lang), type=["ifc"])
    with st.expander(T("demo_box", lang)):
        demo = st.button(T("load_demo", lang), width="stretch")
        seed = st.number_input(T("demo_seed", lang), 0, 999, 1, help=T("demo_seed_help", lang))
    st.divider()
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    use_llm = st.toggle(T("ai_toggle", lang), value=False, disabled=not has_key,
                        help=T("ai_needs_key", lang) if not has_key else T("ai_help", lang))

if auth.enabled() and not st.session_state.get("user") and auth.autologin():
    st.session_state["user"] = auth.autologin()          # demo mode: NR_AUTOLOGIN=<username>
    st.rerun()
if auth.enabled() and not st.session_state.get("user"):
    st.title("OpenBoQ")
    with st.form("login"):
        st.subheader(T("login_title", lang))
        u = st.text_input(T("username", lang))
        pw = st.text_input(T("password", lang), type="password")
        if st.form_submit_button(T("login_btn", lang), type="primary"):
            user = auth.check(u, pw)
            if user:
                st.session_state["user"] = user
                st.rerun()
            st.error(T("login_failed", lang))
    st.stop()

if demo:
    DATA.mkdir(exist_ok=True)
    buggy, truth = inject(make_sample_boq(), n_item=10, n_lv=2, seed=int(seed))
    make_sample_ifc(DATA / "sample_model.ifc")
    st.session_state["boq"] = buggy
    st.session_state["ifc"] = str(DATA / "sample_model.ifc")
    st.session_state["truth"] = truth
    st.session_state["source"] = "demo"
elif lv_up is not None and st.session_state.get("upload_name") != (lv_up.name, ifc_up.name if ifc_up else None):
    st.session_state["boq"] = load_boq(_save(lv_up))
    st.session_state["ifc"] = str(_save(ifc_up)) if ifc_up else None
    st.session_state["truth"] = None
    st.session_state["upload_name"] = (lv_up.name, ifc_up.name if ifc_up else None)
    st.session_state["source"] = lv_up.name

boq = st.session_state.get("boq")
if boq is None:
    st.title("OpenBoQ")
    st.markdown(T("intro", lang))
    st.stop()

# ---------------------------------------------------------------- project details + reviewer (feed the learning)
from openboq.rules import _is_public
store = FeedbackStore()
with st.sidebar.expander(T("project_box", lang), expanded=False):
    if st.session_state.get("user"):
        reviewer = st.session_state["user"]["name"]          # signed in: decisions are signed automatically
        st.text_input(T("reviewer", lang), value=reviewer, disabled=True)
    else:
        reviewer = st.text_input(T("reviewer", lang), key="reviewer")
    client = st.text_input(T("client", lang), value=boq.client or "", key=f"client_{id(boq)}")
    public = st.checkbox(T("public", lang), value=_is_public(boq), key=f"public_{id(boq)}")
    ptypes = T("ptypes", lang).split("|")
    ptype = st.selectbox(T("project_type", lang), ptypes, key=f"ptype_{id(boq)}")
    s_ = store.summary()
    st.caption(f"{T('memory_stats', lang)}: {s_['decisions']} · ✅ {s_['confirmed']} · ✖ {s_['dismissed']}")
if client:
    boq.client = client
meta = {"client": client, "public": public, "project_type": ptype}

# rules/IFC findings carry both languages; only the AI layer depends on the language
ck = (id(boq), st.session_state.get("ifc"), use_llm, lang if use_llm else "-", client, public,
      st.session_state.get("fb_version", 0), st.session_state.get("rules_version", 0))
if st.session_state.get("ck") != ck:
    with st.spinner(T("checking", lang)):
        st.session_state["res"] = analyze(boq, ifc=st.session_state.get("ifc"), use_llm=use_llm, lang=lang,
                                          source=st.session_state.get("source", ""),
                                          prices=None if st.session_state.get("source") == "demo" else "auto",
                                          feedback=store, meta=meta)
    st.session_state["ck"] = ck
res = st.session_state["res"]

# ---------------------------------------------------------------- header + KPIs
st.title(boq.project or boq.name or "BoQ")
st.caption(f"{boq.name} · GAEB DA {boq.phase or '–'} · {len(boq.items)} {T('items', lang)} · "
           f"{T('lv_sum', lang)} {eur(boq.total)} · {T('analysis_in', lang)} {res.seconds*1000:.0f} ms")
cats = category_counts(res.flags)
qs = questions(res.flags, lang)
c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
if boq.total > 0:
    c1.metric(T("risk", lang), eur(res.exposure),
              f"{num(100 * res.exposure / boq.total, 1, lang)} % {T('of_total', lang)}", delta_color="off")
else:
    c1.metric(T("hero_unpriced", lang), f"{len(res.item_risk())} / {len(boq.items)}", help=T("hero_unpriced_sub", lang))
c2.metric(T("k_errors", lang), cats["error"], help=T("k_sub", lang))
c3.metric(T("k_risks", lang), cats["risk"], help=T("k_sub", lang))
c4.metric(T("k_opps", lang), cats["opportunity"], help=T("k_sub", lang))
c5.metric(T("k_questions", lang), len(qs))
if res.summary:
    st.info(res.summary)

tab_top, tab_rev, tab_q, tab_rules, tab_all, tab_pos, tab_ifc, tab_eval = st.tabs(
    [T("tab_top", lang), T("tab_review", lang), T("tab_questions", lang), T("tab_rules", lang), T("tab_all", lang),
     T("tab_pos", lang), T("tab_ifc", lang), T("tab_eval", lang)])

with tab_rules:
    st.caption(T("rules_hint", lang))
    txt = st.text_input(T("rule_input", lang), key="rule_text",
                        placeholder="for client 2, 10% higher prices are normal" if lang == "en"
                        else "für Kunde Müller sind 10 % höhere Preise normal")
    if st.button(T("rule_understand", lang)) and txt.strip():
        st.session_state["rule_draft"], st.session_state["rule_by"] = userrules.parse(txt)
    draft = st.session_state.get("rule_draft")
    if draft:
        st.info(f"**{userrules.describe(draft, lang)}**  \n_{T('rule_parsed_by', lang)}: "
                f"{'Claude' if st.session_state.get('rule_by') == 'claude' else 'OpenBoQ'}_")
        with st.expander(T("rule_adjust", lang)):
            c1, c2 = st.columns(2)
            draft["scope"]["client"] = c1.text_input(T("client", lang), draft["scope"].get("client") or "") or None
            draft["scope"]["trade"] = c2.text_input("Gewerk / trade", draft["scope"].get("trade") or "") or None
            pub_opts = [T("any", lang), "public", "private"]
            pub_now = 0 if draft["scope"].get("public") is None else (1 if draft["scope"]["public"] else 2)
            pub = c1.selectbox(T("public", lang), pub_opts, index=pub_now)
            draft["scope"]["public"] = None if pub == pub_opts[0] else pub == "public"
            acts = ["suppress", "severity", "price_tolerance"]
            draft["action"] = c2.selectbox(T("rule_action", lang), acts, index=acts.index(draft["action"]),
                                           format_func=lambda a: T("act_" + a, lang))
            fams = list(userrules.FAMILIES)
            chosen = [k for k in fams if set(userrules.FAMILIES[k][0]) & set(draft.get("rules", []))]
            chosen = st.multiselect(T("rule_checks", lang), fams, default=chosen,
                                    format_func=lambda k: userrules.FAMILY_LABEL[k][0 if lang == "de" else 1])
            draft["rules"] = sorted({r for k in chosen for r in userrules.FAMILIES[k][0]})
            if draft["action"] == "severity":
                draft["severity"] = st.selectbox(T("f_severity", lang), ["high", "medium", "low"],
                                                 index=["high", "medium", "low"].index(draft.get("severity") or "low"))
            if draft["action"] == "price_tolerance":
                draft["pct"] = st.number_input(T("rule_pct", lang), 0.0, 500.0, float(draft.get("pct") or 10))
        effect = userrules.apply_rules(res.flags, boq, [draft], meta, preview=True)
        st.markdown(f"**{T('rule_effect', lang)}: {len(effect)} {T('rule_effect_n', lang)}**")
        if effect:
            st.dataframe(pd.DataFrame([{T("c_oz", lang): f.oz or T("lv_wide", lang), T("c_finding", lang): f.txt(lang)[0],
                                        T("rule_action", lang): e_de if lang == "de" else e_en} for f, e_de, e_en in effect[:50]]),
                         hide_index=True, width="stretch")
        if st.button(T("rule_save", lang), type="primary"):
            userrules.save_rule(draft, by=reviewer or "")
            st.session_state.pop("rule_draft", None)
            st.session_state["rules_version"] = st.session_state.get("rules_version", 0) + 1
            st.success(T("rule_saved", lang))
            st.rerun()
    st.divider()
    st.markdown(f"**{T('rules_active', lang)}**")
    active = userrules.load_rules()
    if not active:
        st.caption(T("no_rules", lang))
    for r in active:
        a, b = st.columns([6, 1])
        a.markdown(f"„{r['text']}“  \n<small>{userrules.describe(r, lang)} · {r.get('created_by') or '–'} "
                   f"{(r.get('created_at') or '')[:10]}</small>", unsafe_allow_html=True)
        if b.button(T("rule_delete", lang), key=f"del_{r['id']}"):
            userrules.delete_rule(r["id"])
            st.session_state["rules_version"] = st.session_state.get("rules_version", 0) + 1
            st.rerun()

with tab_rev:
    st.caption(T("review_hint", lang))
    reviewable = [f for f in res.flags if f.severity in ("high", "medium")]
    rows = []
    for k, f in enumerate(reviewable):
        t, m, _ = f.txt(lang)
        note = f.learned.get(lang, "") if f.learned else ""
        if f.decision:
            word = T("d_confirm" if f.decision["status"] == "confirmed" else "d_dismiss", lang)
            note = (f"{word} – {T('decided_by', lang)} {f.decision.get('by')} {f.decision.get('at')}"
                    + (f": {f.decision['reason']}" if f.decision.get("reason") else ""))
        rows.append({"#": k, "": SEV_ICON[f.severity], T("c_oz", lang): f.oz or T("lv_wide", lang), T("c_finding", lang): t,
                     T("c_expl", lang): m[:220], T("c_learned", lang): note,
                     T("c_dismiss", lang): f.decision.get("status") == "dismissed",
                     T("c_reason", lang): f.decision.get("reason", "")})
    if rows:
        edited = st.data_editor(
            pd.DataFrame(rows), hide_index=True, width="stretch", height=480, key=f"rev_{st.session_state.get('ck')}",
            disabled=["#", "", T("c_oz", lang), T("c_finding", lang), T("c_expl", lang), T("c_learned", lang)],
            column_config={"#": None,
                           T("c_dismiss", lang): st.column_config.CheckboxColumn(width="small"),
                           T("c_reason", lang): st.column_config.TextColumn(width="medium")})
        if st.button(T("finish", lang), type="primary"):
            if not reviewer.strip():
                st.warning(T("need_reviewer", lang))
            else:
                n_d = n_c = 0
                for _, r in edited.iterrows():
                    f = reviewable[int(r["#"])]
                    status = "dismissed" if r[T("c_dismiss", lang)] else "confirmed"
                    reason = (r[T("c_reason", lang)] or "").strip()
                    if f.decision.get("status") == status and f.decision.get("reason", "") == reason:
                        n_d += status == "dismissed"; n_c += status == "confirmed"
                        continue                     # already decided like this – no duplicate record
                    store.record(f, boq, status, reason=reason, reviewer=reviewer.strip(), meta=meta)
                    f.decision = {"status": status, "by": reviewer.strip(), "reason": reason, "source": "user",
                                  "at": __import__("datetime").date.today().isoformat()}
                    n_d += status == "dismissed"; n_c += status == "confirmed"
                st.session_state["fb_version"] = st.session_state.get("fb_version", 0) + 1
                st.success(f"✖ {n_d} · ✅ {n_c} ({T('finished', lang)})")
                final_q = questions(res.flags, lang, only_confirmed=True)
                q_text = "\n\n".join(f"{i}. {q}" for i, q in enumerate(final_q, 1))
                st.text_area(T("questions_title", lang), q_text, height=260)
                st.download_button(T("dl_questions", lang), q_text, file_name=f"openboq_bidder_questions_{lang}.txt",
                                   type="primary")
    if res.dismissed:
        st.caption(f"✖ {len(res.dismissed)} {T('auto_dismissed', lang)}")

    st.divider()
    st.markdown(f"**{T('outcomes_title', lang)}**")
    st.caption(T("outcomes_hint", lang))
    past = store.project_decisions(boq.project or boq.name)
    if not past:
        st.caption(T("no_confirmed_yet", lang))
    else:
        O = {"": "", "dispute": T("o_dispute", lang), "clarified": T("o_clarified", lang), "no_issue": T("o_no_issue", lang)}
        inv = {v: k for k, v in O.items()}
        odf = pd.DataFrame([{"id": r["id"], T("c_oz", lang): r["item_oz"] or T("lv_wide", lang),
                             T("c_type", lang): rule_name(r["rule_id"], lang), T("c_finding", lang): r["flag_title"],
                             T("c_outcome", lang): O.get(r["outcome"] or "", "")} for r in past])
        oed = st.data_editor(odf, hide_index=True, width="stretch", key=f"out_{st.session_state.get('fb_version', 0)}",
                             disabled=["id", T("c_oz", lang), T("c_type", lang), T("c_finding", lang)],
                             column_config={"id": None, T("c_outcome", lang): st.column_config.SelectboxColumn(options=list(O.values()))})
        if st.button(T("save_outcomes", lang)):
            for _, r in oed.iterrows():
                o = inv.get(r[T("c_outcome", lang)], "")
                if o:
                    store.set_outcome(int(r["id"]), o)
            st.session_state["fb_version"] = st.session_state.get("fb_version", 0) + 1
            st.rerun()
    stats = store.outcome_stats()
    if stats:
        st.markdown(f"**{T('dispute_table', lang)}**")
        def _w(n, d):
            return f"×{max(0.25, min(2.0, 2 * d / n)):.2f}" if n >= 3 else "–"
        st.dataframe(pd.DataFrame([{T("c_type", lang): rule_name(k, lang), "n": n, T("o_dispute", lang): d,
                                    T("c_dispute_rate", lang): f"{100 * d / n:.0f} %", T("c_weight", lang): _w(n, d)}
                                   for k, (n, d) in sorted(stats.items(), key=lambda kv: -kv[1][1] / kv[1][0])]),
                     hide_index=True, width="stretch")

with tab_q:
    st.caption(T("questions_hint", lang))
    only_conf = st.checkbox(T("q_confirmed_only", lang),
                            value=any(f.decision.get("status") == "confirmed" for f in res.flags))
    qs = questions(res.flags, lang, only_confirmed=only_conf)
    if qs:
        q_text = "\n\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1))
        st.text_area(T("questions_title", lang), q_text, height=420)
        st.download_button(T("dl_questions", lang), q_text, file_name=f"openboq_bidder_questions_{lang}.txt")
    else:
        st.info(T("no_questions", lang))

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
                     "Typ" if lang == "de" else "Type": T("cat_" + (f.category or "risk"), lang),
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
        T("c_sugg", lang): round(res.price_suggestions[i.oz].median, 2) if i.oz in res.price_suggestions else None,
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
