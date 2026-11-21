"""Self-contained HTML report + Excel export, in German or English (lang="de" | "en")."""
from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from .fmt import money, num
from .i18n import T, category_counts, questions, sev_label, src_label
from .pipeline import Result

SEV_LABEL = {"high": "Hoch", "medium": "Mittel", "low": "Gering", "info": "Info"}   # kept for older imports


def _e(s) -> str:
    return html.escape(str(s or ""))


def eur(v: float, lang: str = "de") -> str:
    return money(v, lang)


def _dur(sec: float, lang: str) -> str:
    return f"{sec*1000:.0f} ms" if sec < 1 else f"{num(sec, 1, lang)} s"


def _pct(v: float, lang: str, sign: bool = False) -> str:
    s = f"{v * 100:{'+' if sign else ''}.1f}"
    return (s if lang == "en" else s.replace(".", ",")) + (" %" if lang == "de" else "%")


def to_html(res: Result, lang: str = "de") -> str:
    boq = res.boq
    risk = res.item_risk()
    sev = res.by_severity()
    lv_total = boq.total or 1
    share = res.exposure / lv_total

    by_type = defaultdict(float)
    for f in res.counted:
        by_type[f.txt(lang)[0].split(":")[0]] += f.exposure_eur
    top_types = sorted(by_type.items(), key=lambda kv: -kv[1])[:8]
    max_t = max([v for _, v in top_types] or [0]) or 1   # unpriced tenders: all € values can be 0
    bars = "".join(
        f'<div class="bar"><span class="bl">{_e(k)}</span><span class="bt"><i style="width:{100*v/max_t:.1f}%"></i></span>'
        f'<span class="bv">{eur(v, lang)}</span></div>' for k, v in top_types)

    top = sorted(res.counted, key=lambda f: -f.exposure_eur)[:8]
    top_rows = "".join(
        f'<tr><td><span class="sev {f.severity}">{sev_label(f.severity, lang)}</span></td><td class="mono">{_e(f.oz or T("lv_wide", lang))}</td>'
        f'<td><b>{_e(f.txt(lang)[0])}</b><div class="msg">{_e(f.txt(lang)[1])}</div></td><td class="num">{eur(f.exposure_eur, lang)}</td></tr>'
        for f in top)

    ifc_html = ""
    if res.ifc_table:
        rows = []
        for r in res.ifc_table:
            dev = r["Abweichung"]
            cls = {"deviation": "high", "missing_in_lv": "high", "watch": "medium", "missing_in_model": "low"}.get(r["Status"], "ok")
            group = r["Prüfgruppe"]
            if lang == "en":
                from .ifc_check import MAPPING_EN
                group = MAPPING_EN.get(group, group)
            rows.append(
                f'<tr><td>{_e(group)}</td><td class="num">{r["Bauteile"]}</td>'
                f'<td class="num">{num(r["Modell"], 1, lang)}</td><td class="num">{num(r["LV"], 1, lang)}</td><td>{_e(r["Einheit"])}</td>'
                f'<td class="num">{"" if dev is None else _pct(dev, lang, True)}</td>'
                f'<td><span class="sev {cls}">{T("st_" + r["Status"], lang)}</span></td></tr>')
        cols = "".join(f"<th>{T(c, lang)}</th>" for c in ("col_group", "col_elements", "col_model", "col_lv", "col_unit", "col_dev", "col_status"))
        ifc_html = f"""
        <section><h2>{T("ifc_title", lang)} <small>IFC · VOB/B § 2 Abs. 3</small></h2>
        <table class="t"><thead><tr>{cols}</tr></thead><tbody>{''.join(rows)}</tbody></table></section>"""

    by_oz = defaultdict(list)
    for f in res.flags:
        by_oz[f.oz].append(f)
    blocks = []
    if by_oz.get(""):
        blocks.append(_item_block(T("lv_wide", lang), T("lv_wide_title", lang), None, by_oz[""], lang))
    for it in boq.items:
        if it.oz in by_oz:
            blocks.append(_item_block(it.oz, it.short_text, it, by_oz[it.oz], lang, res.price_suggestions.get(it.oz)))

    summary = f'<p class="summary">{_e(res.summary)}</p>' if res.summary else ""
    cats = category_counts(res.flags)
    if boq.total > 0:
        hero = (f'<div class="kpi hero"><div class="l">{T("risk", lang)}</div><div class="v">{eur(res.exposure, lang)}</div>'
                f'<div class="l">{_pct(share, lang)} {T("of_total", lang)}</div></div>')
    else:
        hero = (f'<div class="kpi hero"><div class="l">{T("hero_unpriced", lang)}</div><div class="v">{len(risk)} / {len(boq.items)}</div>'
                f'<div class="l">{T("hero_unpriced_sub", lang)}</div></div>')
    qs = questions(res.flags, lang)
    q_html = ("<ol class='qs'>" + "".join(f"<li>{_e(q)}</li>" for q in qs) + "</ol>") if qs else f"<p>{T('no_questions', lang)}</p>"

    return f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenBoQ – {_e(boq.project or boq.name)}</title>
<style>
:root{{--ink:#14213d;--muted:#5c6475;--line:#e4e1da;--bg:#faf8f4;--card:#fff;--high:#c0392b;--med:#d68910;--low:#7f8c8d;--ok:#1e8449}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px 20px 60px}}
header{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:14px}}
.brand{{font-weight:800;letter-spacing:.02em;font-size:13px;text-transform:uppercase;color:var(--muted)}}
h1{{margin:4px 0 0;font-size:26px;line-height:1.2}}.meta{{color:var(--muted);font-size:13px;text-align:right}}
.kpis{{display:grid;grid-template-columns:2fr 1fr 1fr 1fr 1fr;gap:12px;margin:22px 0}}
.qs{{margin:0 0 10px 0;padding-left:22px;font-size:13.5px}}.qs li{{margin:6px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}}
.kpi .v{{font-size:28px;font-weight:800;font-variant-numeric:tabular-nums}}.kpi .l{{color:var(--muted);font-size:13px}}
.kpi.hero{{background:var(--ink);color:#fff;border-color:var(--ink)}}.kpi.hero .l{{color:#c9cfdb}}.kpi.hero .v{{font-size:38px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 18px 8px;margin:16px 0}}
h2{{font-size:17px;margin:0 0 12px}}h2 small{{color:var(--muted);font-weight:500;font-size:12px;margin-left:6px}}
.bar{{display:grid;grid-template-columns:240px 1fr 110px;gap:10px;align-items:center;margin:6px 0;font-size:13px}}
.bt{{background:#f0ede6;border-radius:4px;height:12px;overflow:hidden}}.bt i{{display:block;height:100%;background:var(--ink)}}
.bv,.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
table.t{{width:100%;border-collapse:collapse;font-size:13.5px}}.t th{{text-align:left;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);padding:6px}}
.t td{{border-bottom:1px solid var(--line);padding:8px 6px;vertical-align:top}}.mono{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;white-space:nowrap}}
.msg{{color:var(--muted);font-size:12.5px;margin-top:2px}}
.sev{{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;color:#fff;white-space:nowrap}}
.sev.high{{background:var(--high)}}.sev.medium{{background:var(--med)}}.sev.low{{background:var(--low)}}.sev.info{{background:#aab2bd}}.sev.ok{{background:var(--ok)}}
.item{{border-top:1px solid var(--line);padding:12px 0}}.item:first-of-type{{border-top:0}}
.ih{{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}}.ih .mono{{font-weight:700}}.ih .q{{color:var(--muted);font-size:12.5px;margin-left:auto}}
.f{{display:grid;grid-template-columns:70px 1fr 100px;gap:10px;margin:8px 0 0 0;font-size:13.5px}}
.ref{{font-size:12px;color:var(--muted)}}.sug{{font-size:12.5px;margin-top:3px}}.sug:before{{content:"→ ";color:var(--ok);font-weight:700}}
.src{{font-size:10.5px;border:1px solid var(--line);border-radius:4px;padding:0 5px;margin-left:6px;color:var(--muted)}}
.summary{{font-size:15px;background:#fff7e6;border-left:4px solid var(--med);padding:12px 14px;border-radius:6px}}
.note{{color:var(--muted);font-size:12px;margin-top:18px}}
@media (max-width:720px){{.kpis{{grid-template-columns:1fr 1fr 1fr}}.kpi .v{{font-size:24px}}.kpi.hero{{grid-column:1/-1}}.bar{{grid-template-columns:1fr 80px}}.bar .bt{{display:none}}.f{{grid-template-columns:60px 1fr}}.f .num{{grid-column:2;text-align:left}}.meta{{text-align:left}}}}
</style></head><body><div class="wrap">
<header><div><div class="brand">OpenBoQ · {T("brand", lang)}</div><h1>{_e(boq.project or boq.name)}</h1>
<div class="msg">{_e(boq.name)} · GAEB DA {_e(boq.phase or "–")} · {len(boq.items)} {T("items", lang)}</div></div>
<div class="meta">{T("lv_sum", lang)} {eur(boq.total, lang)}<br>{T("analysis_in", lang)} {_dur(res.seconds, lang)}</div></header>
<div class="kpis">
{hero}
<div class="kpi"><div class="v" style="color:var(--high)">{cats['error']}</div><div class="l">{T("k_errors", lang)}</div></div>
<div class="kpi"><div class="v" style="color:var(--med)">{cats['risk']}</div><div class="l">{T("k_risks", lang)}</div></div>
<div class="kpi"><div class="v" style="color:var(--ok)">{cats['opportunity']}</div><div class="l">{T("k_opps", lang)}</div></div>
<div class="kpi"><div class="v">{len(qs)}</div><div class="l">{T("k_questions", lang)}</div></div>
</div>
{summary}
{_notes_html(res, lang)}
{_plan_html(res, lang)}
<section><h2>{T("top", lang)} <small>{T("by_eur", lang)}</small></h2><table class="t"><tbody>{top_rows}</tbody></table></section>
<section><h2>{T("questions_title", lang)} <small>{T("questions_hint", lang)}</small></h2>{q_html}</section>
<section><h2>{T("by_type", lang)}</h2>{bars}<div style="height:8px"></div></section>
{ifc_html}
<section><h2>{T("all", lang)} <small>{T("in_order", lang)}</small></h2>{''.join(blocks)}</section>
<p class="note">{T("note", lang)}</p>
</div></body></html>"""


def plan_rows(res, lang: str, base: float = 0.12) -> tuple[list[dict], list[dict], list[dict]]:
    """Milestone 4/5 tables for the exports: markups from history, sensitivity per cost driver, alternatives."""
    from . import history as H
    from . import whatif as W
    de_ = lang == "de"
    L = (lambda a, b: a if de_ else b)
    boq, sugg = res.boq, res.price_suggestions
    hist = []
    if res.history_info:
        for r in H.markup_table(boq, res.flags, res.history_info, sugg, base=base):
            h = res.history_info.get(r["oz"])
            if not h and not r["findings"]:
                continue
            up, _ = W.unit_price(boq.by_oz()[r["oz"]], sugg)
            hist.append({L("OZ", "Item"): r["oz"], L("Kurztext", "Short text"): r["short_text"][:80], "n": h.n if h else None,
                         L("Menge Ist/LV", "Qty actual/planned"): round(h.qty_ratio, 2) if h and h.qty_ratio else None,
                         L("Nachtragsquote", "Change-order rate"): round(h.co_rate, 2) if h else None,
                         L("Kosten Ist/Soll je Einheit", "Unit cost actual/planned"): round(h.cost_ratio, 2) if h and h.cost_ratio else None,
                         L("Nachtragsgründe", "Change-order reasons"): "; ".join(h.reasons) if h else "",
                         L("Zuschlag Vorschlag", "Suggested markup"): round(r["markup"], 3),
                         L("EP", "Unit price"): round(up, 2) if up else None,
                         L("EP-Vorschlag", "Suggested unit price"): round(H.suggested_up(up, r["markup"], base), 2) if up else None})
    sens = [{L("Preistreiber", "Cost driver"): W.DRIVERS[k][0 if de_ else 1], L("Δ € bei +10 %", "Δ € at +10 %"): round(v, 0)}
            for k, v in W.sensitivity(boq, sugg) if abs(v) >= 1]
    alts = [{L("OZ", "Item"): a["oz"], L("Kurztext", "Short text"): a["short_text"][:70],
             L("Heute", "Now"): a["current"], L("Alternative", "Alternative"): a["alternative"],
             L("Art", "Kind"): {"nebenangebot": L("Nebenangebot", "Alternative offer"), "risk": L("Risiko", "Risk")}[a["kind"]],
             "Δ €": round(a["delta_total"], 0), L("Hinweis", "Note"): a["note_de"] if de_ else a["note_en"]}
            for a in W.alternatives(boq, sugg)]
    return hist, sens, alts


def _plan_html(res, lang: str) -> str:
    from . import history as H
    from . import whatif as W
    hist, sens, alts = plan_rows(res, lang)
    if not (hist or sens or alts):
        return ""
    de_ = lang == "de"
    L = (lambda a, b: a if de_ else b)
    parts = []
    if res.history_info:
        co = H.expected_change_orders(res.history_info, res.boq, res.price_suggestions)
        ex = L(" – Beispieldaten (simuliert)", " – example data (simulated)") if getattr(res.history_model, "example", False) else ""
        parts.append(f"<p>{L('Erfahrungswerte für', 'Experience data for')} {len(res.history_info)} / {len(res.boq.items)} "
                     f"{L('Positionen', 'items')}{_e(ex)} · {L('erwartetes Nachtragsvolumen', 'expected change-order volume')} "
                     f"<b>{eur(co, lang)}</b></p>")
    ctx = W.contract_context(res.boq)
    if sens:
        top = ", ".join(f"{_e(r[list(r)[0]])} {eur(r[list(r)[1]], lang)}" for r in sens[:3])
        clause = (L("Stoffpreisgleitklausel erkannt.", "Material price escalation clause found.") if ctx["escalation"] else
                  L("Keine Preisgleitklausel erkannt – Preissteigerungen trägt der AN.", "No price escalation clause found – "
                    "the contractor carries price increases."))
        parts.append(f"<p>{L('Empfindlichkeit (+10 % je Preistreiber)', 'Sensitivity (+10 % per cost driver)')}: {top}. {clause}</p>")
    if alts:
        sav = -sum(a["Δ €"] for a in alts if a["Δ €"] < 0)
        parts.append(f"<p>{len(alts)} {L('Alternativen erkannt; Einsparpotenzial durch Nebenangebote bis', 'alternatives found; saving potential from alternative offers up to')} "
                     f"<b>{eur(sav, lang)}</b>.</p>")
    return f"<section><h2>{L('Kalkulation: Historie & Was-wäre-wenn', 'Pricing: history & what-if')}</h2>{''.join(parts)}</section>"


def _notes_html(res, lang: str) -> str:
    notes = getattr(res, "project_notes", None) or []
    if not notes:
        return ""
    icon = {"high": "🔴", "medium": "🟠", "low": "⚪", "info": "🔵"}
    rows = "".join(f"<li>{icon.get(n['severity'], '')} {_e(n['de'] if lang == 'de' else n['en'])}</li>" for n in notes)
    title = "Projekt-Hinweise (aus dem Vergleich der Dateien)" if lang == "de" else "Project notes (from comparing the files)"
    return f"<section><h2>{title}</h2><ul class='notes'>{rows}</ul></section>"


def _item_block(oz, title, it, flags, lang, sugg=None) -> str:
    q = ""
    if it is not None and it.qty is not None:
        q = (f"{num(it.qty, 2, lang)} {it.unit} × {eur_cents(it.up or 0, lang)} = {eur_cents(it.total, lang)}")
    if sugg is not None:
        q += (f" · {T('sugg_line', lang)}: {eur_cents(sugg.median, lang)} "
              f"({eur_cents(sugg.lo, lang)}–{eur_cents(sugg.hi, lang)}, n={sugg.n})")
    rows = []
    for f in flags:
        t, m, s = f.txt(lang)
        if f.learned:
            m = f"{m} [{f.learned.get(lang, '')}]"
        if f.decision:
            d = f.decision
            word = T("d_confirm" if d["status"] == "confirmed" else "d_dismiss", lang)
            m = f"{m} [{word} – {T('decided_by', lang)} {d.get('by', '–')} {d.get('at', '')}" + (f": {d['reason']}" if d.get("reason") else "") + "]"
        rows.append(
            f'<div class="f"><div><span class="sev {f.severity}">{sev_label(f.severity, lang)}</span></div>'
            f'<div><b>{_e(t)}</b><span class="src">{T("cat_" + (f.category or "risk"), lang)} · {src_label(f.source, lang)} {_e(f.rule_id)}</span>'
            f'<div class="msg">{_e(m)}</div>'
            f'{f"<div class=ref>{_e(f.reference)}</div>" if f.reference else ""}'
            f'{f"<div class=sug>{_e(s)}</div>" if s else ""}</div>'
            f'<div class="num">{eur(f.exposure_eur, lang) if f.exposure_eur else ""}</div></div>')
    return (f'<div class="item"><div class="ih"><span class="mono">{_e(oz)}</span><span>{_e(title)}</span>'
            f'<span class="q">{q}</span></div>{"".join(rows)}</div>')


def eur_cents(v: float, lang: str) -> str:
    return f"€{num(v, 2, lang)}" if lang == "en" else f"{num(v, 2, lang)} €"


def to_excel(res: Result, path, lang: str = "de") -> Path:
    import pandas as pd
    risk = res.item_risk()
    pos = [{
        T("c_oz", lang): i.oz, T("c_short", lang): i.short_text, T("c_qty", lang): i.qty, T("c_unit", lang): i.unit,
        T("c_up", lang): i.up, T("c_it", lang): i.it,
        T("c_light", lang): sev_label(risk[i.oz]["severity"], lang) if i.oz in risk else "ok",
        T("c_risk", lang): round(risk.get(i.oz, {}).get("exposure", 0.0), 2),
        T("c_count", lang): risk.get(i.oz, {}).get("n", 0),
        T("c_sugg", lang): round(res.price_suggestions[i.oz].median, 2) if i.oz in res.price_suggestions else None,
        T("c_sugg_n", lang): res.price_suggestions[i.oz].n if i.oz in res.price_suggestions else None,
    } for i in res.boq.items]
    fl = []
    for f in res.flags:
        t, m, s = f.txt(lang)
        fl.append({T("f_severity", lang): sev_label(f.severity, lang), T("c_oz", lang): f.oz or T("lv_wide", lang),
                   "Rule": f.rule_id, T("f_source", lang): src_label(f.source, lang), T("c_finding", lang): t,
                   T("c_expl", lang): m, T("c_basis", lang): f.reference, T("c_fix", lang): s,
                   T("c_risk", lang): round(f.exposure_eur, 2)})
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    def clean(rows):
        return [{k: (ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v) for k, v in r.items()} for r in rows]
    fl, pos = clean(fl), clean(pos)
    out = Path(path)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame(fl or [{T("c_finding", lang): "–"}]).to_excel(xw, sheet_name=T("sheet_findings", lang), index=False)
        pd.DataFrame(pos or [{T("c_oz", lang): "–"}]).to_excel(xw, sheet_name=T("sheet_items", lang), index=False)
        if res.ifc_table:
            pd.DataFrame(res.ifc_table).to_excel(xw, sheet_name=T("sheet_ifc", lang), index=False)
        if getattr(res, "project_notes", None):
            pd.DataFrame(notes_rows(res.project_notes, lang)).to_excel(
                xw, sheet_name="Projekt-Hinweise" if lang == "de" else "Project notes", index=False)
        hist, sens, alts = plan_rows(res, lang)
        if hist:
            pd.DataFrame(clean(hist)).to_excel(xw, sheet_name="Historie & Zuschläge" if lang == "de" else "History & markups",
                                               index=False)
        if sens or alts:
            sh = "Was-wäre-wenn" if lang == "de" else "What-if"
            pd.DataFrame(sens or [{"–": "–"}]).to_excel(xw, sheet_name=sh, index=False)
            if alts:
                pd.DataFrame(clean(alts)).to_excel(xw, sheet_name=sh, index=False, startrow=len(sens) + 3)
    return out


def notes_rows(notes, lang: str) -> list[dict]:
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    de = lang == "de"
    return [{("Stufe" if de else "Severity"): sev_label(n["severity"], lang),
             ("Hinweis" if de else "Note"): ILLEGAL_CHARACTERS_RE.sub("", n["de"] if de else n["en"]),
             ("Positionen" if de else "Items"): ", ".join(n["items"]), ("Betrag €" if de else "Amount €"): n["eur"] or None}
            for n in notes]


def write_html(res: Result, path, lang: str = "de") -> Path:
    out = Path(path)
    out.write_text(to_html(res, lang), encoding="utf-8")
    return out
