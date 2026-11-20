"""Self-contained HTML report + Excel export, in German or English (lang="de" | "en")."""
from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from .fmt import money, num
from .i18n import T, sev_label, src_label
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
            blocks.append(_item_block(it.oz, it.short_text, it, by_oz[it.oz], lang))

    summary = f'<p class="summary">{_e(res.summary)}</p>' if res.summary else ""

    return f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenBoQ – {_e(boq.project or boq.name)}</title>
<style>
:root{{--ink:#14213d;--muted:#5c6475;--line:#e4e1da;--bg:#faf8f4;--card:#fff;--high:#c0392b;--med:#d68910;--low:#7f8c8d;--ok:#1e8449}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px 20px 60px}}
header{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:14px}}
.brand{{font-weight:800;letter-spacing:.02em;font-size:13px;text-transform:uppercase;color:var(--muted)}}
h1{{margin:4px 0 0;font-size:26px;line-height:1.2}}.meta{{color:var(--muted);font-size:13px;text-align:right}}
.kpis{{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:12px;margin:22px 0}}
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
<div class="kpi hero"><div class="l">{T("risk", lang)}</div><div class="v">{eur(res.exposure, lang)}</div><div class="l">{_pct(share, lang)} {T("of_total", lang)}</div></div>
<div class="kpi"><div class="v" style="color:var(--high)">{sev['high']}</div><div class="l">{T("high", lang)}</div></div>
<div class="kpi"><div class="v" style="color:var(--med)">{sev['medium']}</div><div class="l">{T("medium", lang)}</div></div>
<div class="kpi"><div class="v">{len(risk)}</div><div class="l">{T("affected", lang)}</div></div>
</div>
{summary}
<section><h2>{T("top", lang)} <small>{T("by_eur", lang)}</small></h2><table class="t"><tbody>{top_rows}</tbody></table></section>
<section><h2>{T("by_type", lang)}</h2>{bars}<div style="height:8px"></div></section>
{ifc_html}
<section><h2>{T("all", lang)} <small>{T("in_order", lang)}</small></h2>{''.join(blocks)}</section>
<p class="note">{T("note", lang)}</p>
</div></body></html>"""


def _item_block(oz, title, it, flags, lang) -> str:
    q = ""
    if it is not None and it.qty is not None:
        q = (f"{num(it.qty, 2, lang)} {it.unit} × {eur_cents(it.up or 0, lang)} = {eur_cents(it.total, lang)}")
    rows = []
    for f in flags:
        t, m, s = f.txt(lang)
        rows.append(
            f'<div class="f"><div><span class="sev {f.severity}">{sev_label(f.severity, lang)}</span></div>'
            f'<div><b>{_e(t)}</b><span class="src">{src_label(f.source, lang)} {_e(f.rule_id)}</span>'
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
    } for i in res.boq.items]
    fl = []
    for f in res.flags:
        t, m, s = f.txt(lang)
        fl.append({T("f_severity", lang): sev_label(f.severity, lang), T("c_oz", lang): f.oz or T("lv_wide", lang),
                   "Rule": f.rule_id, T("f_source", lang): src_label(f.source, lang), T("c_finding", lang): t,
                   T("c_expl", lang): m, T("c_basis", lang): f.reference, T("c_fix", lang): s,
                   T("c_risk", lang): round(f.exposure_eur, 2)})
    out = Path(path)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame(fl or [{T("c_finding", lang): "–"}]).to_excel(xw, sheet_name=T("sheet_findings", lang), index=False)
        pd.DataFrame(pos or [{T("c_oz", lang): "–"}]).to_excel(xw, sheet_name=T("sheet_items", lang), index=False)
        if res.ifc_table:
            pd.DataFrame(res.ifc_table).to_excel(xw, sheet_name=T("sheet_ifc", lang), index=False)
    return out


def write_html(res: Result, path, lang: str = "de") -> Path:
    out = Path(path)
    out.write_text(to_html(res, lang), encoding="utf-8")
    return out
