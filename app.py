"""OpenBoQ – Streamlit dashboard (German / English).

Run:  streamlit run app.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

# hosted (Streamlit Community Cloud): API keys and logins live in the app's Secrets settings – copy them into the
# environment the providers read; nothing secret is ever in the repository
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float, bool)):
            os.environ.setdefault(_k, str(_v))
except Exception:                                   # no secrets file locally – fine
    pass

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
from openboq import ui_theme as UI

st.set_page_config(page_title="OpenBoQ", page_icon=str(UI.make_favicon()), layout="wide")
UI.inject_css()
DATA = Path(__file__).parent / "data"
SEV_ICON = {"high": "🔴", "medium": "🟠", "low": "⚪", "info": "🔵"}


@st.cache_resource(show_spinner=False)
def _prewarm():
    """Once per server process, in the background: import the text-matching library and build the price and history
    indexes, so the first check after an upload does not wait for them."""
    import threading

    def work():
        try:
            from openboq.prices import PriceModel
            from openboq.history import HistoryModel
            PriceModel.load()
            HistoryModel.load()
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()
    return True


_prewarm()


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]          # keep German noun capitals ("Hohe Befunde")


def _save(upload) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / upload.name
    p.write_bytes(upload.getvalue())
    return p


def _projects(batch: dict, lang: str = "de") -> dict:
    """Files of the same project (same item numbers/quantities, any format) -> one merged entry each, plus the
    differences between the versions as findings."""
    from openboq import crossfile as X
    key = st.session_state.get("upload_name")
    if st.session_state.get("merged_for") == key:
        return st.session_state.get("merged", {})
    boqs = {n: e["boq"] for n, e in batch.items() if e["boq"] is not None}
    copies = X.duplicates(boqs)                       # same content under another file name
    for c, orig in copies.items():
        batch[c]["copy_of"] = orig
    boqs = {n: b for n, b in boqs.items() if n not in copies}
    merged = {}
    for k, names in enumerate(X.group_projects(boqs), 1):
        label = f"🔗 Projekt {k} ({len(names)} Dateien)" if lang == "de" else f"🔗 Project {k} ({len(names)} files)"
        merged[label] = {"boq": X.merge(boqs, names), "error": "", "extra": X.compare(boqs, names), "files": names}
        for n in names:
            batch[n]["project"] = k
    st.session_state["merged"], st.session_state["merged_for"] = merged, key
    return merged


def _batch_overview(batch: dict, use_llm: bool, lang: str):
    """One row per uploaded file: format, reader, items, totals check, findings, exposure – then open one in detail.
    Files of the same project get a combined row (texts + prices + clauses of all files, plus version differences)."""
    de_ = lang == "de"
    merged = _projects(batch, lang)
    batch = {**batch, **merged}
    st.subheader((f"Stapelprüfung: {len(batch) - len(merged)} Dateien" if de_ else f"Batch check: {len(batch) - len(merged)} files")
                 + (f" · {len(merged)} " + ("Projekt(e) erkannt" if de_ else "project(s) recognised") if merged else ""))
    if merged:
        st.caption("Dateien desselben Projekts (gleiche Positionen/Mengen, beliebiges Format) werden zusammengeführt: Texte aus "
                   "der Textdatei, Preise aus der Preisdatei, Vorbemerkungen aus allen – und jede Abweichung zwischen den "
                   "Fassungen ist ein Befund." if de_ else
                   "Files of the same project (same items/quantities, any format) are combined: texts from the text file, "
                   "prices from the price file, preliminary notes from all – and every difference between the versions is a finding.")
    cache = st.session_state.setdefault("batch_res", {})
    todo = [n for n, e in batch.items() if e["boq"] is not None and not e.get("copy_of") and (n, use_llm, lang) not in cache]
    if todo:
        prog = st.progress(0.0, text="…")
        for k, n in enumerate(todo):
            prog.progress(k / len(todo), text=f"{n} ({k + 1}/{len(todo)})" + (" · KI" if use_llm and de_ else " · AI" if use_llm else ""))
            e = batch[n]
            try:
                r_ = analyze(e["boq"], use_llm=use_llm, lang=lang, source=n, feedback="auto", rules="auto")
                r_.flags += e.get("extra", [])
                if e.get("files"):
                    from openboq import crossfile as X
                    full = {m: batch[m]["boq"] for m in e["files"]}
                    r_.project_notes = X.project_notes(full, e["files"], e["boq"], r_.flags, e.get("extra", []))
                    e["notes"] = r_.project_notes
                cache[(n, use_llm, lang)] = r_
            except Exception as ex:
                e["error"] = f"{type(ex).__name__}: {str(ex)[:160]}"
        prog.empty()
    rows = []
    for n, e in batch.items():
        b, r = e["boq"], cache.get((n, use_llm, lang))
        if e.get("copy_of"):
            rows.append({"Datei" if de_ else "File": n, "Format": Path(n).suffix.lower().lstrip("."),
                         ("Fehler" if de_ else "Error"): (f"identischer Inhalt wie {e['copy_of']} – nicht doppelt geprüft"
                                                          if de_ else f"same content as {e['copy_of']} – not checked twice")})
            continue
        if b is None or r is None:
            rows.append({"Datei" if de_ else "File": n, "Format": Path(n).suffix.lower().lstrip("."),
                         ("Fehler" if de_ else "Error"): e["error"] or "–"})
            continue
        cnt = {s_: sum(1 for f in r.counted if f.severity == s_) for s_ in ("high", "medium")}
        tot = next((f for f in r.flags if f.rule_id == "R26" and not f.oz), None)
        diffs = sum(1 for f in e.get("extra", []))
        rows.append({
            "Datei" if de_ else "File": n,
            "Projekt" if de_ else "Project": (f"P{e['project']}" if e.get("project") else
                                              ("+".join(Path(x).suffix.lstrip(".") for x in e["files"]) if e.get("files") else "–")),
            "Format": "merged" if e.get("files") else Path(n).suffix.lower().lstrip("."),
            "Leser" if de_ else "Reader": (b.parse_info or {}).get("reader", "gaeb"),
            "Positionen" if de_ else "Items": len(b.items),
            "LV-Summe" if de_ else "BoQ total": round(b.total, 2),
            "🔴": cnt["high"], "🟠": cnt["medium"],
            "Risiko €" if de_ else "Risk €": round(r.exposure, 0),
            "Summenprüfung" if de_ else "Totals check": ("❌ " + money(tot.exposure_eur, lang)) if tot else
            ("✅" if b.totals else "–"),
            "KI" if de_ else "AI": ("⚠" if r.llm_errors else "✓") if use_llm else "",
            "Abweichungen" if de_ else "Version diffs": diffs if e.get("files") else None,
        })
    df = pd.DataFrame(rows)
    df = df.astype(object).where(pd.notna(df), None)        # failed files: empty cells instead of NaN
    st.dataframe(df, hide_index=True, width="stretch")
    for n, e in batch.items():
        notes = e.get("notes") or []
        if notes:
            with st.expander(f"{n} – " + (f"{len(notes)} Projekt-Hinweise" if de_ else f"{len(notes)} project notes"),
                             icon=":material/push_pin:", expanded=True):
                for nt in notes:
                    st.markdown(f"{SEV_ICON.get(nt['severity'], '')} {nt['de'] if de_ else nt['en']}")
    ok = [n for n, e in batch.items() if e["boq"] is not None and not e.get("copy_of") and (n, use_llm, lang) in cache]
    c1, c2 = st.columns([3, 2])
    with c1:
        sel = st.selectbox("Datei im Detail öffnen" if de_ else "Open file in detail", ok,
                           index=ok.index(st.session_state.get("open_file")) if st.session_state.get("open_file") in ok else 0)
    if sel and sel != st.session_state.get("open_file"):
        st.session_state["open_file"] = sel
        st.session_state["boq"] = batch[sel]["boq"]
        st.session_state["source"] = sel
        st.session_state["extra_flags"] = batch[sel].get("extra", [])
        st.rerun()
    with c2:
        st.download_button(("Alle Befunde (Excel)" if de_ else "All findings (Excel)"),
                           data=lambda: _batch_excel(batch, cache, use_llm, lang, df), icon=":material/download:",
                           file_name="openboq_batch.xlsx", width="stretch", on_click="ignore")
    st.divider()


def _batch_excel(batch, cache, use_llm, lang, overview) -> bytes:
    """One workbook, no duplicates: a project's findings appear once (on the combined row); a member file adds only
    findings that are specific to that file (reading problems, its own totals …); identical copies are skipped."""
    import io
    from openboq.report import notes_rows
    rows, qrows, nrows = [], [], []
    member_of = {m: n for n, e in batch.items() for m in (e.get("files") or [])}
    project_keys = {}
    order = [n for n, e in batch.items() if e.get("files")] + [n for n, e in batch.items() if not e.get("files")]
    for n in order:
        e = batch[n]
        r = cache.get((n, use_llm, lang))
        if r is None or e.get("copy_of"):
            continue
        seen = project_keys.get(member_of.get(n), set())
        own = set()
        for f in r.flags:
            key = (f.rule_id, f.oz, f.title)
            own.add(key)
            if key in seen:
                continue                                   # already reported on the project row
            t, m, sug = f.txt(lang)
            rows.append({"File": n, "Severity": sev_label(f.severity, lang), "Item": f.oz, "Rule": f.rule_id,
                         "Finding": t, "Explanation": m, "Basis": f.reference, "Suggestion": sug,
                         "Risk €": round(f.exposure_eur, 2)})
        if e.get("files"):
            project_keys[n] = own
        qs = questions(r.flags, lang)
        if n in member_of:
            pq = set(questions(cache.get((member_of[n], use_llm, lang)).flags, lang)) if cache.get((member_of[n], use_llm, lang)) else set()
            qs = [q for q in qs if q not in pq]
        qrows += [{"File": n, "Question": q} for q in qs]
        for nr in notes_rows(e.get("notes") or [], lang):
            nrows.append({"Project": n, **nr})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        overview.to_excel(xw, sheet_name="Overview", index=False)
        clean = lambda d: d.apply(lambda c: c.map(lambda v: _ILLEGAL.sub("", v) if isinstance(v, str) else v))
        if nrows:
            clean(pd.DataFrame(nrows)).to_excel(xw, sheet_name="Project notes", index=False)
        clean(pd.DataFrame(rows)).to_excel(xw, sheet_name="Findings", index=False)
        clean(pd.DataFrame(qrows)).to_excel(xw, sheet_name="Bidder questions", index=False)
    return buf.getvalue()


from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE as _ILLEGAL  # noqa: E402

# ---------------------------------------------------------------- sidebar
_HOME_CLEAR = ("boq", "batch", "batch_res", "source", "upload_name", "open_file", "merged", "merged_for", "extra_flags",
               "extra_flags_wide", "res", "ck", "main_tab", "pos_sel", "rule_draft")


def _go_home():
    """Logo click: back to the start page. Keeps language, login and history source; empties the upload box."""
    for k in _HOME_CLEAR:
        st.session_state.pop(k, None)
    st.session_state["up_gen"] = st.session_state.get("up_gen", 0) + 1


with st.sidebar:
    st.button("OpenBoQ", key="home", on_click=_go_home, help="Zur Startseite" if st.session_state.get("lang") != "en"
              else "Back to the start page")
    lang = st.segmented_control("Sprache / Language", list(LANGS), format_func=LANGS.get, key="lang",
                                default="de", required=True, label_visibility="collapsed")
    eur = lambda v: money(v, lang)
    st.caption(T("tagline", lang))
    if auth.enabled() and st.session_state.get("user"):
        st.caption(f":material/person: {T('logged_in_as', lang)} **{st.session_state['user']['name']}**")
        if st.button(T("logout", lang)):
            st.session_state.pop("user", None)
            st.rerun()
    lv_ups = st.file_uploader(T("upload_lv", lang) + (" (mehrere möglich)" if lang == "de" else " (several allowed)"),
                              type=["x81", "x83", "x84", "x86", "xml", "d81", "d83", "d84", "d86", "pdf", "docx", "txt",
                                    "csv", "xlsx"], accept_multiple_files=True,
                              key=f"lv_up_{st.session_state.get('up_gen', 0)}")
    with st.expander(T("demo_box", lang)):
        demo = st.button(T("load_demo", lang), width="stretch")
        seed = st.number_input(T("demo_seed", lang), 0, 999, 1, help=T("demo_seed_help", lang))
    st.divider()
    from openboq.llm_checks import available as _llm_available, default_model as _llm_model, provider_label as _llm_provider
    has_key = _llm_available()
    debug = st.toggle(":material/bug_report: Debug", value=False, help="Zeigt das interne Prüfprotokoll (zweite Prüfung durch die AG-Sicht). "
                      "Nur in der App, nie im Export." if lang == "de" else
                      "Shows the internal check log (second check from the client's side). App only, never exported.")
    use_llm = st.toggle(T("ai_toggle", lang).replace("(Claude)", f"({_llm_provider()})" if has_key else "(Claude)"),
                        value=False, disabled=not has_key,
                        help=T("ai_needs_key", lang) if not has_key else f"{T('ai_help', lang)} · {_llm_model()}")

if auth.enabled() and not st.session_state.get("user") and auth.autologin():
    st.session_state["user"] = auth.autologin()          # demo mode: NR_AUTOLOGIN=<username>
    st.rerun()
if auth.enabled() and not st.session_state.get("user"):
    with st.container(key="login"):
        st.markdown(UI.wordmark(height=64, stroke=2.0), unsafe_allow_html=True)
    with st.container(key="login_form"), st.form("login"):
        st.subheader(T("login_title", lang))
        if auth.name_only():                              # NR_LOGIN=name: just a name, no password
            u = st.text_input("Ihr Name" if lang == "de" else "Your name")
            pw = None
        else:
            u = st.text_input(T("username", lang))
            pw = st.text_input(T("password", lang), type="password")
        if st.form_submit_button(T("login_btn", lang), type="primary"):
            user = auth.name_login(u) if auth.name_only() else auth.check(u, pw)
            if user:
                st.session_state["user"] = user
                st.rerun()
            st.error(T("login_failed", lang))
    st.stop()

demo = demo or st.session_state.pop("demo_req", False)      # the landing page's demo button
if demo:
    DATA.mkdir(exist_ok=True)
    buggy, _truth = inject(make_sample_boq(), n_item=10, n_lv=2, seed=int(seed))
    st.session_state["boq"] = buggy
    st.session_state["source"] = "demo"
elif lv_ups and st.session_state.get("upload_name") != tuple(f.name for f in lv_ups):
    batch = {}
    prog = st.progress(0.0, text=T("checking", lang))
    for k, up in enumerate(lv_ups):
        entry = {"error": ""}
        try:
            entry["boq"] = load_boq(_save(up))
        except Exception as e:                      # one broken file must not stop the batch
            entry["boq"], entry["error"] = None, f"{type(e).__name__}: {str(e)[:160]}"
        batch[up.name] = entry
        prog.progress((k + 1) / len(lv_ups), text=f"{up.name} ({k + 1}/{len(lv_ups)})")
    prog.empty()
    st.session_state["batch"] = batch
    st.session_state["batch_res"] = {}
    first = next((n for n, e in batch.items() if e["boq"] is not None), None)
    st.session_state["open_file"] = first
    if first:
        st.session_state["boq"] = batch[first]["boq"]
    st.session_state["upload_name"] = tuple(f.name for f in lv_ups)
    st.session_state["source"] = first or ""

# ---------------------------------------------------------------- batch overview (several files)
batch = st.session_state.get("batch") or {}
if len(batch) > 1 and st.session_state.get("source") != "demo":
    _batch_overview(batch, use_llm, lang)

boq = st.session_state.get("boq")
if boq is None:
    st.markdown(UI.hero(lang), unsafe_allow_html=True)
    c1, c2 = st.container(key="cta").columns([1, 3], vertical_alignment="center")
    c1.button(T("load_demo", lang), type="primary", width="stretch",
              on_click=lambda: st.session_state.update(demo_req=True))
    c2.caption("… oder links ein eigenes LV hochladen – mehrere Dateien desselben Projekts werden zusammengeführt."
               if lang == "de" else
               "… or upload your own bill of quantities on the left – several files of one project are combined.")
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

# rule findings carry both languages; only the AI layer depends on the language
# past projects (milestone 4): an uploaded / example file chosen in the history tab, else data/history.csv if present
hist_src = st.session_state.get("history_path") or "auto"
ck = (id(boq), use_llm, lang if use_llm else "-", client, public,
      st.session_state.get("fb_version", 0), st.session_state.get("rules_version", 0), hist_src)
if st.session_state.get("ck") != ck:
    with st.spinner(T("checking", lang)):
        st.session_state["res"] = analyze(boq, use_llm=use_llm, lang=lang,
                                          source=st.session_state.get("source", ""),
                                          prices=None if st.session_state.get("source") == "demo" else "auto",
                                          feedback=store, meta=meta,
                                          history=None if st.session_state.get("source") == "demo" and hist_src == "auto"
                                          else hist_src)
        st.session_state["res"].flags += st.session_state.get("extra_flags_wide", [])
        if st.session_state.get("source", "").startswith("🔗"):
            st.session_state["res"].flags += st.session_state.get("extra_flags", [])
            st.session_state["res"].project_notes = (st.session_state.get("merged", {}).get(st.session_state["source"], {})
                                                     .get("notes") or [])
    st.session_state["ck"] = ck
res = st.session_state["res"]
if getattr(res, "llm_errors", None):
    st.warning((f"AI could not check {len(res.llm_errors)} batch(es) (usually the free-tier rate limit). "
                "Rule results are complete; try again in a minute or switch model.") if lang == "en" else
               (f"Die KI konnte {len(res.llm_errors)} Block/Blöcke nicht prüfen (meist Free-Tier-Limit). "
                "Regelergebnisse sind vollständig; in einer Minute erneut versuchen oder Modell wechseln."))
    with st.expander("Details"):
        st.code("\n".join(res.llm_errors))

# ---------------------------------------------------------------- header + KPIs
st.title(boq.project or boq.name or "BoQ")
_pi = boq.parse_info or {}
_reader = {"ava-print": "AVA print reader", "layout-independent": "layout-independent reader", "ai": "AI reader"}.get(
    _pi.get("reader", ""), "")
if lang == "de":
    _reader = {"AVA print reader": "AVA-Druck-Leser", "layout-independent reader": "layoutunabhängiger Leser",
               "AI reader": "KI-Leser"}.get(_reader, _reader)
st.caption(f"{boq.name} · GAEB DA {boq.phase or '–'} · {len(boq.items)} {T('items', lang)} · "
           f"{T('lv_sum', lang)} {eur(boq.total)} · {T('analysis_in', lang)} {res.seconds*1000:.0f} ms"
           + (f" · {_reader}" if _reader else ""))
if _pi.get("ai_error"):
    st.caption(("AI reader unavailable: " if lang == "en" else "KI-Leser nicht verfügbar: ") + _pi["ai_error"])
cats = category_counts(res.flags)
qs = questions(res.flags, lang)
with st.container(key="kpis"):
    c1, c2, c3, c4, c5 = st.columns([1.7, 0.9, 1.15, 1.3, 1])
if boq.total > 0:
    c1.metric(T("risk", lang), eur(res.exposure),
              f"{num(100 * res.exposure / boq.total, 1, lang)} % {T('of_total', lang)}", delta_color="off", delta_arrow="off")
else:
    c1.metric(T("hero_unpriced", lang), f"{len(res.item_risk())} / {len(boq.items)}", help=T("hero_unpriced_sub", lang))
c2.metric(T("k_errors", lang), cats["error"], help=T("k_sub", lang))
c3.metric(T("k_risks", lang), cats["risk"], help=T("k_sub", lang))
c4.metric(T("k_opps", lang), cats["opportunity"], help=T("k_sub", lang))
c5.metric(T("k_questions", lang), len(qs))
if res.summary:
    st.info(res.summary)
if getattr(res, "project_notes", None):
    with st.container(border=True):
        st.markdown(":material/push_pin: **" + ("Projekt-Hinweise (aus dem Vergleich der Dateien)" if lang == "de" else
                              "Project notes (from comparing the files)") + "**")
        for nt in res.project_notes:
            st.markdown(f"{SEV_ICON.get(nt['severity'], '')} {nt['de'] if lang == 'de' else nt['en']}")

if debug:
    with st.expander(("Internes Prüfprotokoll – zweite Prüfung (AG-Sicht)" if lang == "de" else
                              "Internal check log – second check (client's side)"), expanded=False, icon=":material/bug_report:"):
        log = [f for f in res.flags if f.challenge]
        if not log:
            st.caption("Keine zweite Prüfung gelaufen (KI aus oder keine Befunde)." if lang == "de" else
                       "No second check ran (AI off or no findings).")
        else:
            st.dataframe(pd.DataFrame([{
                "Item": f.oz or "LV", "Rule": f.rule_id, "Finding": f.txt(lang)[0],
                "Model said": f.challenge.get("raw_verdict", ""), "Accepted as": f.challenge.get("verdict", ""),
                "Severity": f"{f.challenge.get('before', '')} → {f.severity}" if f.challenge.get("before") != f.severity
                            else f"{f.severity} (unchanged)",
                "Argument": f.challenge.get(lang, ""), "Evidence": f.challenge.get("evidence", ""),
                "Checked by": f.challenge.get("model", ""), "Findings mostly by": f.challenge.get("findings_by", "")}
                for f in log]),
                hide_index=True, width="stretch")
            st.caption("'Model said' = Antwort des Modells; 'Accepted as' = was nach der Belegprüfung übrig bleibt "
                       "(ohne Beleg im Dokument → holds). Fakten und Vertragsklauseln werden nie herabgestuft." if lang == "de" else
                       "'Model said' = the model's answer; 'Accepted as' = what is left after the evidence check (no evidence "
                       "in the document → holds). Facts and contract clauses are never lowered.")
        if getattr(res, "llm_errors", None):
            st.code("\n".join(res.llm_errors))

# only the open tab runs (lazy tabs): switching tabs or moving a slider never recomputes the other seven
TAB_ICONS = {"top": ":material/priority_high:", "all": ":material/list_alt:", "pos": ":material/table_rows:",
             "rev": ":material/fact_check:", "q": ":material/forum:", "hist": ":material/history:",
             "what": ":material/tune:", "rules": ":material/rule:"}


def _tab_labels(lg: str) -> dict:
    names = {"top": T("tab_top", lg), "all": T("tab_all", lg), "pos": T("tab_pos", lg), "rev": T("tab_review", lg),
             "q": T("tab_questions", lg), "hist": "Historie & Zuschläge" if lg == "de" else "History & markups",
             "what": "Was-wäre-wenn" if lg == "de" else "What-if", "rules": T("tab_rules", lg)}
    return {k: f"{TAB_ICONS[k]} {v}" for k, v in names.items()}


labels = _tab_labels(lang)
cur = st.session_state.get("main_tab")
if cur is not None and cur not in labels.values():          # language switched: stay on the same tab
    other = {v: k for lg in LANGS for k, v in _tab_labels(lg).items()}
    st.session_state["main_tab"] = labels.get(other.get(cur, "top"), labels["top"])


def _open_item(oz: str):
    """Jump from a finding to its item in the Items tab."""
    st.session_state["main_tab"] = labels["pos"]
    st.session_state["pos_sel"] = oz


_tabs = dict(zip(labels, st.tabs(list(labels.values()), key="main_tab", on_change="rerun")))
tab_top, tab_all, tab_pos, tab_rev = _tabs["top"], _tabs["all"], _tabs["pos"], _tabs["rev"]
tab_q, tab_hist, tab_what, tab_rules = _tabs["q"], _tabs["hist"], _tabs["what"], _tabs["rules"]

if tab_hist.open:
    with tab_hist:
        from openboq.ui_history import history_tab
        history_tab(res, boq, lang, eur)

if tab_what.open:
    with tab_what:
        from openboq.ui_whatif import whatif_tab
        whatif_tab(res, boq, lang, eur)

if tab_rules.open:
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

if tab_rev.open:
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
                pd.DataFrame(rows), hide_index=True, width="stretch", height=min(480, 38 + 35 * len(rows)),
                key=f"rev_{st.session_state.get('ck')}",
                column_order=["", T("c_oz", lang), T("c_dismiss", lang), T("c_finding", lang), T("c_reason", lang),
                              T("c_expl", lang), T("c_learned", lang)],
                disabled=["#", "", T("c_oz", lang), T("c_finding", lang), T("c_expl", lang), T("c_learned", lang)],
                column_config={"#": None, "": st.column_config.TextColumn(width=36),
                               T("c_finding", lang): st.column_config.TextColumn(width="medium"),
                               T("c_dismiss", lang): st.column_config.CheckboxColumn(width="small"),
                               T("c_reason", lang): st.column_config.TextColumn(width="medium")})
            if st.button(T("finish", lang), type="primary", icon=":material/task_alt:"):
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
                                       type="primary", icon=":material/download:", on_click="ignore")
        if res.dismissed:
            st.caption(f"✖ {len(res.dismissed)} {T('auto_dismissed', lang)}")

        # ---- the reviewer adds a finding the system missed; it comes back for the same / similar items next time
        st.divider()
        de_ = lang == "de"
        st.markdown(":material/add_circle: **" + ("Eigenen Befund hinzufügen" if de_ else "Add your own finding") + "**")
        st.caption("Etwas übersehen? Position wählen und Befund eintragen – OpenBoQ meldet ihn künftig bei derselben Position "
                   "(in jedem Projekt, egal wie die Datei heißt) und schlägt ihn bei ähnlichen Positionen vor; die KI nutzt ihn als Beispiel."
                   if de_ else
                   "Something missed? Pick the item and describe the finding – OpenBoQ will report it for the same item in future "
                   "(any project, any file name), suggest it for similar items, and the AI uses it as an example.")
        with st.form(f"manual_{id(boq)}", clear_on_submit=True):
            opts = [""] + [f"{i.oz} · {i.short_text[:70]}" for i in boq.items]
            c1, c2 = st.columns([3, 2])
            pick = c1.selectbox("Position" if de_ else "Item", opts, format_func=lambda o: o or ("– LV-weit –" if de_ else "– whole BoQ –"))
            title = c2.text_input("Befund (kurz)" if de_ else "Finding (short)")
            c3, c4 = st.columns(2)
            cats = {"error": T("k_errors", lang), "risk": T("k_risks", lang), "opportunity": T("k_opps", lang)}
            cat = c3.selectbox("Art" if de_ else "Type", list(cats), format_func=cats.get, index=1)
            sev = c4.selectbox("Schwere" if de_ else "Severity", ["high", "medium", "low"], index=1, format_func=lambda x: sev_label(x, lang))
            note = st.text_area("Begründung / was ist das Problem?" if de_ else "Why / what is the problem?", height=80)
            if st.form_submit_button("Befund speichern" if de_ else "Save finding", type="primary"):
                if not title.strip():
                    st.warning("Bitte einen kurzen Befund eintragen." if de_ else "Please enter a short finding.")
                elif not reviewer.strip():
                    st.warning(T("need_reviewer", lang))
                else:
                    it = boq.by_oz().get(pick.split(" · ")[0]) if pick else None
                    store.add_manual(it, boq, title, cat, sev, note, reviewer=reviewer.strip(), meta=meta)
                    if it is None:                         # BoQ-wide: show it now for this project only
                        from openboq.model import Flag as _F
                        f_ = _F("M00", title.strip(), sev, note.strip() or title.strip(), source="team", reference="Team",
                                en=dict(title=title.strip(), message=note.strip() or title.strip(), suggestion=""))
                        f_.category = cat
                        st.session_state.setdefault("extra_flags_wide", []).append(f_)
                    st.session_state["fb_version"] = st.session_state.get("fb_version", 0) + 1
                    st.success("Gespeichert – gilt ab sofort für diese und ähnliche Positionen." if de_ else
                               "Saved – applies from now on to this and similar items.")
                    st.rerun()
        team = store.manual_all(active_only=False)
        if team:
            with st.expander(("Team-Befunde" if de_ else "Team findings") + f" ({sum(1 for m in team if m['active'])})"):
                tdf = pd.DataFrame([{"id": m["id"], ("aktiv" if de_ else "active"): bool(m["active"]),
                                     T("c_oz", lang): m["item_oz"] or "–", ("Position" if de_ else "Item"): m["item_text"][:60],
                                     T("c_finding", lang): m["title"], ("Von" if de_ else "By"): m["reviewer"],
                                     ("Projekt" if de_ else "Project"): m["project"], ("Datum" if de_ else "Date"): m["created_at"][:10]}
                                    for m in team])
                ted = st.data_editor(tdf, hide_index=True, width="stretch", key=f"team_{st.session_state.get('fb_version', 0)}",
                                     disabled=[c for c in tdf.columns if c not in ("aktiv", "active")], column_config={"id": None})
                if st.button("Änderungen speichern" if de_ else "Save changes", key="team_save"):
                    col = "aktiv" if de_ else "active"
                    for _, r in ted.iterrows():
                        store.set_manual_active(int(r["id"]), bool(r[col]))
                    st.session_state["fb_version"] = st.session_state.get("fb_version", 0) + 1
                    st.rerun()

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

if tab_q.open:
    with tab_q:
        st.caption(T("questions_hint", lang))
        only_conf = st.checkbox(T("q_confirmed_only", lang),
                                value=any(f.decision.get("status") == "confirmed" for f in res.flags))
        qs = questions(res.flags, lang, only_confirmed=only_conf)
        if qs:
            q_text = "\n\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1))
            st.text_area(T("questions_title", lang), q_text, height=420)
            st.download_button(T("dl_questions", lang), q_text, file_name=f"openboq_bidder_questions_{lang}.txt",
                           icon=":material/download:", on_click="ignore")
        else:
            st.info(T("no_questions", lang))

if tab_top.open:
    with tab_top:
        de_ = lang == "de"
        by_oz = boq.by_oz()
        top = sorted(res.counted, key=lambda f: -f.exposure_eur)[:10]
        left, right = st.columns([3, 2], gap="large")
        with left:
            if not top:
                st.info("Keine Befunde mit Euro-Betrag." if de_ else "No findings with a euro amount.")
            for k, f in enumerate(top):
                with st.container(border=True, key=f"card_{f.severity}_{k}"):
                    a, b = st.columns([5, 1.4])
                    a.markdown(UI.finding_html(f, lang, sev_label, T("lv_wide", lang)), unsafe_allow_html=True)
                    b.markdown(f'<div class="ob-eur">{eur(f.exposure_eur)}<small>{"geschätzt" if de_ else "estimated"}'
                               f'</small></div>', unsafe_allow_html=True)
                    if f.oz in by_oz:
                        b.button("Zur Position" if de_ else "Open item", key=f"go_{k}", type="tertiary",
                                 icon=":material/open_in_new:", on_click=_open_item, args=(f.oz,), width="stretch")
        with right:
            agg: dict = {}
            for f in res.counted:
                if f.exposure_eur > 0:
                    agg[rule_name(f.rule_id, lang)] = agg.get(rule_name(f.rule_id, lang), 0) + f.exposure_eur
            if agg:
                st.markdown("**" + ("Wo das Risiko liegt" if de_ else "Where the risk sits") + "**")
                st.markdown(UI.bar_list(sorted(agg.items(), key=lambda kv: -kv[1])[:8], eur), unsafe_allow_html=True)
                st.caption("Summe der geschätzten Beträge je Prüfung, alle gezählten Befunde." if de_ else
                           "Sum of the estimated amounts per check, all counted findings.")

if tab_all.open:
    with tab_all:
        de_ = lang == "de"
        c1, c2, c3 = st.columns([2, 2, 3], vertical_alignment="bottom")
        sel_sev = c1.pills(T("f_severity", lang), ["high", "medium", "low", "info"], selection_mode="multi",
                           default=["high", "medium"], format_func=lambda k: sev_label(k, lang), key="f_sev")
        sel_cat = c2.pills("Typ" if de_ else "Type", ["error", "risk", "opportunity"], selection_mode="multi",
                           default=["error", "risk", "opportunity"], format_func=lambda k: T("cat_" + k, lang), key="f_cat")
        q = c3.text_input("Suchen" if de_ else "Search", key="f_q", placeholder="Position, Text, Regel …" if de_
                          else "item, text, rule …").strip().lower()
        shown = []
        for f in res.flags:
            if sel_sev and f.severity not in sel_sev:
                continue
            if sel_cat and (f.category or "risk") not in sel_cat:
                continue
            t, m, s_ = f.txt(lang)
            if q and q not in " ".join([f.oz or "", t, m, f.reference or "", f.rule_id]).lower():
                continue
            shown.append(f)
        rows = []
        for f in shown:
            t, m, s_ = f.txt(lang)
            rows.append({"": SEV_ICON[f.severity], T("c_oz", lang): f.oz or T("lv_wide", lang), T("c_finding", lang): t,
                         T("c_risk", lang): round(f.exposure_eur, 0), "Typ" if de_ else "Type": T("cat_" + (f.category or "risk"), lang),
                         T("c_expl", lang): m, T("f_source", lang): src_label(f.source, lang), T("c_basis", lang): f.reference})
        st.caption((f"{len(shown)} von {len(res.flags)} Befunden – Zeile anklicken für Details" if de_ else
                    f"{len(shown)} of {len(res.flags)} findings – click a row for details"))
        top_eur = max([f.exposure_eur for f in shown] + [1])
        ev = st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=min(440, 38 + 35 * max(1, len(rows))),
                          on_select="rerun",
                          selection_mode="single-row", key=f"all_df_{hash((tuple(sel_sev or ()), tuple(sel_cat or ()), q))}",
                          column_config={"": st.column_config.TextColumn(width=36),
                                         T("c_finding", lang): st.column_config.TextColumn(width="medium"),
                                         T("c_risk", lang): st.column_config.ProgressColumn(
                                             min_value=0, max_value=float(top_eur), format="%.0f €", width=150)})
        picked = ev.selection.rows if ev else []
        if picked and picked[0] < len(shown):
            f = shown[picked[0]]
            with st.container(border=True, key=f"card_{f.severity}_sel"):
                a, b = st.columns([5, 1.4])
                a.markdown(UI.finding_html(f, lang, sev_label, T("lv_wide", lang)), unsafe_allow_html=True)
                b.markdown(f'<div class="ob-eur">{eur(f.exposure_eur)}<small>{"geschätzt" if de_ else "estimated"}'
                           f'</small></div>', unsafe_allow_html=True)
                it = boq.by_oz().get(f.oz)
                if it is not None:
                    a.caption(f"{it.oz} · {it.short_text} · {num(it.qty, 2, lang)} {it.unit}")
                    b.button("Zur Position" if de_ else "Open item", key="go_sel", type="tertiary",
                             icon=":material/open_in_new:", on_click=_open_item, args=(f.oz,), width="stretch")

if tab_pos.open:
    with tab_pos:
        de_ = lang == "de"
        risk = res.item_risk()
        oz_list = [i.oz for i in boq.items]
        pos = pd.DataFrame([{
            "": SEV_ICON.get(risk.get(i.oz, {}).get("severity"), "🟢"), T("c_oz", lang): i.oz, T("c_short", lang): i.short_text,
            T("c_qty", lang): i.qty, T("c_unit", lang): i.unit, T("c_up", lang): i.up, T("c_it", lang): i.it,
            T("c_risk", lang): round(risk.get(i.oz, {}).get("exposure", 0), 0),
            T("c_sugg", lang): round(res.price_suggestions[i.oz].median, 2) if i.oz in res.price_suggestions else float("nan"),
        } for i in boq.items])
        if not res.price_suggestions:
            pos = pos.drop(columns=[T("c_sugg", lang)])

        def _pick_row():
            sel = st.session_state.get("pos_df")
            rows_ = sel.selection.rows if sel is not None else []
            if rows_ and rows_[0] < len(oz_list):
                st.session_state["pos_sel"] = oz_list[rows_[0]]

        top_eur = float(max([0] + list(pos[T("c_risk", lang)]))) if len(pos) else 0
        st.caption("Zeile anklicken, um die Position zu öffnen." if de_ else "Click a row to open the item.")
        st.dataframe(pos, width="stretch", hide_index=True, height=min(360, 38 + 35 * max(1, len(pos))), key="pos_df",
                     on_select=_pick_row,
                     selection_mode="single-row",
                     column_config={"": st.column_config.TextColumn(width=36),
                                    T("c_short", lang): st.column_config.TextColumn(width=330),
                                    T("c_up", lang): st.column_config.NumberColumn(format="%.2f"),
                                    T("c_it", lang): st.column_config.NumberColumn(format="%.2f"),
                                    T("c_sugg", lang): st.column_config.NumberColumn(format="%.2f"),
                                    T("c_risk", lang): st.column_config.ProgressColumn(
                                        min_value=0, max_value=max(top_eur, 1.0), format="%.0f €", width=150)})
        if boq.items:
            if st.session_state.get("pos_sel") not in oz_list:
                st.session_state.pop("pos_sel", None)
            oz = st.selectbox(T("pos_detail", lang), oz_list, key="pos_sel",
                              format_func=lambda o: f"{o} – {boq.by_oz()[o].short_text}")
            it = boq.by_oz()[oz]
            sg = res.price_suggestions.get(oz)
            with st.container(border=True):
                st.markdown(f"**{it.oz} · {it.short_text}**")
                facts = [f"{num(it.qty, 2, lang)} {it.unit}"]
                e2 = (lambda v: f"€{num(v, 2, lang)}") if lang == "en" else (lambda v: f"{num(v, 2, lang)} €")
                if it.up:
                    facts.append(("EP " if de_ else "Unit price ") + e2(it.up))
                if it.it:
                    facts.append(("GP " if de_ else "Total ") + eur(it.it))
                if sg:
                    facts.append(("Vergleichspreise " if de_ else "Reference prices ") + f"{e2(sg.lo)} – {e2(sg.hi)}")
                st.caption("   |   ".join(facts))
                if it.long_text:
                    st.markdown(it.long_text)
            its_flags = [f for f in res.flags if f.oz == oz]
            for k, f in enumerate(its_flags):
                with st.container(border=True, key=f"card_{f.severity}_pos{k}"):
                    st.markdown(UI.finding_html(f, lang, sev_label, T("lv_wide", lang)), unsafe_allow_html=True)
            if not its_flags:
                st.caption("Keine Befunde für diese Position." if de_ else "No findings for this item.")
            if its_flags and has_key and st.button(T("fix_btn", lang), icon=":material/auto_fix_high:"):
                from openboq.llm_checks import llm_fix_text
                with st.spinner(T("fixing", lang)):
                    st.success(llm_fix_text(it, its_flags))


def _xlsx_bytes(r=res, lg=lang) -> bytes:
    p_ = Path(tempfile.mkdtemp()) / "openboq.xlsx"
    to_excel(r, p_, lg)
    return p_.read_bytes()


st.divider()
d1, d2, _ = st.columns([1, 1, 1])
# the files are built only when clicked, on a separate thread – no cost on every page update
d1.download_button(T("dl_html", lang), data=lambda r=res, lg=lang: to_html(r, lg), file_name=f"openboq_report_{lang}.html",
                   mime="text/html", width="stretch", icon=":material/description:", on_click="ignore")
d2.download_button(T("dl_xlsx", lang), data=_xlsx_bytes, file_name=f"openboq_findings_{lang}.xlsx", width="stretch",
                   icon=":material/table_view:", on_click="ignore",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
