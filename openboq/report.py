"""Self-contained HTML report + Excel export."""
from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from .fmt import de, dep
from .pipeline import Result

SEV_LABEL = {"high": "Hoch", "medium": "Mittel", "low": "Gering", "info": "Info"}
SOURCE_LABEL = {"rules": "Regel", "ifc": "IFC", "llm": "KI"}


def _e(s) -> str:
    return html.escape(str(s or ""))


def eur(v: float) -> str:
    return f"{de(v, 0)} €"


def _dur(sec: float) -> str:
    return f"{sec*1000:.0f} ms" if sec < 1 else f"{de(sec, 1)} s"


def to_html(res: Result) -> str:
    boq = res.boq
    risk = res.item_risk()
    sev = res.by_severity()
    lv_total = boq.total or 1
    share = res.exposure / lv_total

    # exposure by finding type
    by_type = defaultdict(float)
    for f in res.counted:
        by_type[f.title.split(":")[0]] += f.exposure_eur
    top_types = sorted(by_type.items(), key=lambda kv: -kv[1])[:8]
    max_t = max([v for _, v in top_types] or [0]) or 1   # unpriced tenders: all € values can be 0

    bars = "".join(
        f'<div class="bar"><span class="bl">{_e(k)}</span><span class="bt"><i style="width:{100*v/max_t:.1f}%"></i></span>'
        f'<span class="bv">{eur(v)}</span></div>' for k, v in top_types)

    top = [f for f in res.counted][:8]
    top = sorted(res.counted, key=lambda f: -f.exposure_eur)[:8]
    top_rows = "".join(
        f'<tr><td><span class="sev {f.severity}">{SEV_LABEL[f.severity]}</span></td><td class="mono">{_e(f.oz or "LV")}</td>'
        f'<td><b>{_e(f.title)}</b><div class="msg">{_e(f.message)}</div></td><td class="num">{eur(f.exposure_eur)}</td></tr>'
        for f in top)

    ifc_html = ""
    if res.ifc_table:
        rows = []
        for r in res.ifc_table:
            dev = r["Abweichung"]
            cls = {"deviation": "high", "missing_in_lv": "high", "watch": "medium", "missing_in_model": "low"}.get(r["Status"], "ok")
            label = {"deviation": "> 10 %", "missing_in_lv": "fehlt im LV", "watch": "5–10 %", "missing_in_model": "fehlt im Modell",
                     "ok": "ok"}[r["Status"]]
            rows.append(
                f'<tr><td>{_e(r["Prüfgruppe"])}</td><td class="num">{r["Bauteile"]}</td>'
                f'<td class="num">{de(r["Modell"], 1)}</td><td class="num">{de(r["LV"], 1)}</td><td>{_e(r["Einheit"])}</td>'
                f'<td class="num">{"" if dev is None else f"{dep(dev, 1)}"}</td><td><span class="sev {cls}">{label}</span></td></tr>')
        ifc_html = f"""
        <section><h2>Modell ↔ LV Mengenabgleich <small>IFC · VOB/B § 2 Abs. 3</small></h2>
        <table class="t"><thead><tr><th>Prüfgruppe</th><th>Bauteile</th><th>Modell</th><th>LV</th><th>Einh.</th><th>Abw.</th><th>Status</th></tr></thead>
        <tbody>{''.join(rows)}</tbody></table></section>"""

    # all findings grouped by item, in LV order
    by_oz = defaultdict(list)
    for f in res.flags:
        by_oz[f.oz].append(f)
    blocks = []
    if by_oz.get(""):
        blocks.append(_item_block("LV-weit", "Vollständigkeit & Modellabgleich", None, by_oz[""]))
    for it in boq.items:
        if it.oz in by_oz:
            blocks.append(_item_block(it.oz, it.short_text, it, by_oz[it.oz]))

    summary = f'<p class="summary">{_e(res.summary)}</p>' if res.summary else ""

    return f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenBoQ – {_e(boq.project)}</title>
<style>
:root{{--ink:#14213d;--muted:#5c6475;--line:#e4e1da;--bg:#faf8f4;--card:#fff;--high:#c0392b;--med:#d68910;--low:#7f8c8d;--ok:#1e8449;--accent:#14213d}}
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
<header><div><div class="brand">OpenBoQ · LV-Prüfung</div><h1>{_e(boq.project or boq.name)}</h1>
<div class="msg">{_e(boq.name)} · GAEB DA {_e(boq.phase or "–")} · {len(boq.items)} Positionen</div></div>
<div class="meta">LV-Summe {eur(boq.total)}<br>Analyse in {_dur(res.seconds)}</div></header>
<div class="kpis">
<div class="kpi hero"><div class="l">Geschätztes Nachtragsrisiko</div><div class="v">{eur(res.exposure)}</div><div class="l">{dep(share, 1, False)} der LV-Summe</div></div>
<div class="kpi"><div class="v" style="color:var(--high)">{sev['high']}</div><div class="l">hohe Befunde</div></div>
<div class="kpi"><div class="v" style="color:var(--med)">{sev['medium']}</div><div class="l">mittlere Befunde</div></div>
<div class="kpi"><div class="v">{len(risk)}</div><div class="l">betroffene Positionen</div></div>
</div>
{summary}
<section><h2>Top-Risiken <small>nach € sortiert</small></h2><table class="t"><tbody>{top_rows}</tbody></table></section>
<section><h2>Risiko nach Befundart</h2>{bars}<div style="height:8px"></div></section>
{ifc_html}
<section><h2>Alle Befunde <small>in LV-Reihenfolge</small></h2>{''.join(blocks)}</section>
<p class="note">€-Werte sind transparente Schätzungen (Regel-Heuristiken, Referenzpreise, Modellmengen) zur Priorisierung – keine Rechtsberatung.
Jeder Befund nennt Regel und Grundlage, damit Kalkulation und Bauleitung ihn prüfen können.</p>
</div></body></html>"""


def _item_block(oz, title, it, flags) -> str:
    q = ""
    if it is not None and it.qty is not None:
        q = f"{de(it.qty, 2)} {it.unit} × {de(it.up or 0, 2)} € = {de(it.total, 2)} €"
    rows = "".join(
        f'<div class="f"><div><span class="sev {f.severity}">{SEV_LABEL[f.severity]}</span></div>'
        f'<div><b>{_e(f.title)}</b><span class="src">{SOURCE_LABEL.get(f.source, f.source)} {_e(f.rule_id)}</span>'
        f'<div class="msg">{_e(f.message)}</div>'
        f'{f"<div class=ref>{_e(f.reference)}</div>" if f.reference else ""}'
        f'{f"<div class=sug>{_e(f.suggestion)}</div>" if f.suggestion else ""}</div>'
        f'<div class="num">{eur(f.exposure_eur) if f.exposure_eur else ""}</div></div>' for f in flags)
    return f'<div class="item"><div class="ih"><span class="mono">{_e(oz)}</span><span>{_e(title)}</span><span class="q">{q}</span></div>{rows}</div>'


def to_excel(res: Result, path) -> Path:
    import pandas as pd
    risk = res.item_risk()
    pos = [{
        "OZ": i.oz, "Kurztext": i.short_text, "Menge": i.qty, "Einheit": i.unit, "EP": i.up, "GP": i.it,
        "Ampel": risk.get(i.oz, {}).get("severity", "ok"), "Risiko €": round(risk.get(i.oz, {}).get("exposure", 0.0), 2),
        "Befunde": risk.get(i.oz, {}).get("n", 0),
    } for i in res.boq.items]
    fl = [{
        "Schwere": f.severity, "OZ": f.oz or "LV", "Regel": f.rule_id, "Quelle": f.source, "Befund": f.title,
        "Erläuterung": f.message, "Grundlage": f.reference, "Vorschlag": f.suggestion, "Risiko €": round(f.exposure_eur, 2),
    } for f in res.flags]
    out = Path(path)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        pd.DataFrame(fl).to_excel(xw, sheet_name="Befunde", index=False)
        pd.DataFrame(pos).to_excel(xw, sheet_name="Positionen", index=False)
        if res.ifc_table:
            pd.DataFrame(res.ifc_table).to_excel(xw, sheet_name="IFC-Abgleich", index=False)
    return out


def write_html(res: Result, path) -> Path:
    out = Path(path)
    out.write_text(to_html(res), encoding="utf-8")
    return out
