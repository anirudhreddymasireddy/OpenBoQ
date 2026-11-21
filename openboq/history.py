"""Historical project data (milestone 4): what happened to similar work in past projects.

One row per item of a finished project – planned vs actual quantity, planned vs actual own cost, change orders:

    project | oz | short_text | unit | qty_planned | qty_actual | up | cost_planned | cost_actual |
    change_order | co_amount | co_reason

German or English column names, CSV or Excel; only project, short_text and one planned/actual pair are required.
From it we learn, per item of the BoQ in hand (by text similarity, fallback: work type):

  * quantity deviation  (actual / planned quantity)       → R32: VOB/B § 2 Abs. 3 opportunity or risk
  * change-order rate + typical amount + reasons           → R33: where change orders are likely
  * own-cost overrun   (actual / planned cost)             → R34: calculation too optimistic → markup
  * a markup suggestion per item: base markup + history surcharge + findings surcharge
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from . import knowledge as K
from .fmt import de
from .fmt import en as E
from .model import BoQ, Flag, Item
from .units import family, norm_unit

DATA = Path(__file__).resolve().parent.parent / "data"
HISTORY_PATH = DATA / "history.csv"            # the company's own history (git-ignored)
EXAMPLE_PATH = DATA / "history_example.csv"    # simulated example – clearly labelled in the app

MIN_SIM = 0.35        # text similarity for "same kind of work"
MIN_N = 3             # never conclude from fewer than 3 past items

COLS = {   # canonical name -> accepted header spellings (lower-case, without spaces/_/-)
    "project": ["project", "projekt", "bauvorhaben", "bv", "projektname"],
    "oz": ["oz", "pos", "position", "ordnungszahl", "item", "itemno"],
    "short_text": ["shorttext", "kurztext", "text", "description", "beschreibung", "leistung", "bezeichnung"],
    "unit": ["unit", "einheit", "me"],
    "qty_planned": ["qtyplanned", "mengelv", "mengesoll", "lvmenge", "vordersatz", "plannedqty", "menge", "qty"],
    "qty_actual": ["qtyactual", "mengeist", "istmenge", "abrechnungsmenge", "actualqty", "abgerechnet"],
    "up": ["up", "ep", "einheitspreis", "unitprice", "rate"],
    "cost_planned": ["costplanned", "kostensoll", "sollkosten", "kalkulationskosten", "plannedcost", "herstellkostensoll"],
    "cost_actual": ["costactual", "kostenist", "istkosten", "actualcost", "herstellkostenist"],
    "change_order": ["changeorder", "nachtrag", "nachtragjanein", "co"],
    "co_amount": ["coamount", "nachtrageur", "nachtragsbetrag", "nachtragsumme", "changeorderamount", "coeur"],
    "co_reason": ["coreason", "nachtraggrund", "grund", "reason", "nachtragsgrund", "ursache"],
}


def _key(h: str) -> str:
    return re.sub(r"[\s_\-/€()\.]", "", str(h).lower())


_PLAN = ("plan", "soll", "lv", "tender", "budget", "kalk", "calc", "estimat")
_ACT = ("act", "ist", "real", "abgerech", "final", "billed", "abrechn")


def _guess(k: str) -> str | None:
    has = lambda *ws: any(w in k for w in ws)
    if has("reason", "grund", "ursache", "cause"):
        return "co_reason"
    if has("change", "nachtrag", "variation", "claim") or k.startswith("co"):
        return "co_amount" if has("eur", "amount", "betrag", "sum", "value", "wert", "€") else "change_order"
    if has("qty", "menge", "quantity", "quant"):
        return "qty_actual" if has(*_ACT) else "qty_planned" if has(*_PLAN) else None
    if has("cost", "kosten"):
        return "cost_actual" if has(*_ACT) else "cost_planned" if has(*_PLAN) else None
    if has("unitprice", "einheitspreis", "rate") or k in ("ep", "up", "preis", "price"):
        return "up"
    if has("text", "desc", "beschreib", "leistung", "bezeichn", "work", "position") and not has("pos", "nr", "no") or \
            has("text", "desc", "beschreib"):
        return "short_text"
    if has("proj", "bauvorhaben", "baustelle", "site", "job"):
        return "project"
    if has("unit", "einheit"):
        return "unit"
    if has("pos", "oz", "item"):
        return "oz"
    return None


def _num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    s = str(v).strip().replace("€", "").replace(" ", "")
    if not s or s.lower() in ("nan", "none", "-", "–"):
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?|-?\d+,\d+", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _yes(v) -> bool:
    if isinstance(v, (int, float)):
        return v == v and v > 0
    return str(v).strip().lower() in ("1", "ja", "yes", "y", "x", "true", "wahr", "j")


def read_history(path) -> list[dict]:
    """Rows of a history file (CSV or Excel), columns mapped to the canonical names."""
    import pandas as pd
    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(p, dtype=str)
    else:
        df = None
        for enc in ("utf-8-sig", "cp1252"):
            try:
                df = pd.read_csv(p, sep=None, engine="python", encoding=enc, dtype=str, index_col=False)
                break
            except UnicodeDecodeError:
                continue
    cmap = {}
    for c in df.columns:
        k = _key(c)
        for canon, names in COLS.items():
            if canon not in cmap.values() and k in names:
                cmap[c] = canon
                break
    # exports name columns freely ("work_description", "planned_cost_eur", "Ist-Menge abgerechnet") – fall back to word parts
    for c in df.columns:
        if c in cmap:
            continue
        canon = _guess(_key(c))
        if canon and canon not in cmap.values():
            cmap[c] = canon
    df = df.rename(columns=cmap)
    if "short_text" not in df.columns:
        raise ValueError("History file needs a short-text column (Kurztext / short_text)")
    rows = []
    for _, r in df.iterrows():
        g = lambda k: r[k] if k in df.columns else None
        st = str(g("short_text") or "").strip()
        if not st or st.lower() == "nan":
            continue
        row = {"project": str(g("project") or "").strip() or "?", "oz": str(g("oz") or "").strip(),
               "short_text": st, "unit": norm_unit(str(g("unit") or "").strip()),
               "qty_planned": _num(g("qty_planned")), "qty_actual": _num(g("qty_actual")), "up": _num(g("up")),
               "cost_planned": _num(g("cost_planned")), "cost_actual": _num(g("cost_actual")),
               "co_amount": _num(g("co_amount")), "co_reason": str(g("co_reason") or "").strip()}
        co = g("change_order")
        row["change_order"] = _yes(co) if co is not None and str(co).strip() not in ("", "nan") else bool(row["co_amount"])
        if row["co_reason"].lower() == "nan":
            row["co_reason"] = ""
        wt = K.classify(st)
        row["work_type"] = wt.key if wt else ""
        rows.append(row)
    return rows


@dataclass
class HistInfo:
    n: int                       # past items used
    basis: str                   # "similar" (text) | "work_type"
    label: str                   # what was matched (work type label or example text)
    qty_ratio: float | None      # median actual / planned quantity
    cost_ratio: float | None     # median actual / planned own cost per unit
    co_rate: float               # share of past items with a change order
    co_pct: float | None         # median change-order amount as share of the item value
    reasons: list[str] = field(default_factory=list)
    projects: int = 0
    examples: list[dict] = field(default_factory=list)


_LOADED: dict = {}


class HistoryModel:
    def __init__(self, rows: list[dict], example: bool = False):
        self.rows = rows
        self.example = example
        self.projects = sorted({r["project"] for r in rows})
        self.mat = None
        if rows:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True, sublinear_tf=True)
            self.mat = self.vec.fit_transform([r["short_text"] for r in rows])

    @classmethod
    def load(cls, path=None) -> "HistoryModel | None":
        p = Path(path) if path else HISTORY_PATH
        if not p.exists():
            return None
        key = (str(p.resolve()), p.stat().st_mtime_ns, p.stat().st_size)
        if key not in _LOADED:                     # same file, same version -> reuse the index (it never changes)
            if len(_LOADED) > 8:
                _LOADED.clear()
            _LOADED[key] = cls(read_history(p), example=p.name == EXAMPLE_PATH.name)
        return _LOADED[key]

    def _stats(self, pool: list[dict], basis: str, label: str) -> HistInfo | None:
        if len(pool) < MIN_N:
            return None
        qr = [r["qty_actual"] / r["qty_planned"] for r in pool if r["qty_planned"] and r["qty_actual"] is not None]
        # own cost per unit, so a quantity change is not counted as a cost overrun a second time
        cr = [(r["cost_actual"] / r["qty_actual"]) / (r["cost_planned"] / r["qty_planned"])
              if r["qty_planned"] and r["qty_actual"] else r["cost_actual"] / r["cost_planned"]
              for r in pool if r["cost_planned"] and r["cost_actual"] is not None]
        cos = [r for r in pool if r["change_order"]]
        cop = [r["co_amount"] / (r["qty_planned"] * r["up"]) if r["qty_planned"] and r["up"] else
               r["co_amount"] / r["cost_planned"] for r in cos
               if r["co_amount"] and ((r["qty_planned"] and r["up"]) or r["cost_planned"])]
        reasons = [r["co_reason"] for r in cos if r["co_reason"]]
        top = [k for k, _ in sorted(((x, reasons.count(x)) for x in set(reasons)), key=lambda kv: -kv[1])][:3]
        return HistInfo(n=len(pool), basis=basis, label=label,
                        qty_ratio=statistics.median(qr) if len(qr) >= MIN_N else None,
                        cost_ratio=statistics.median(cr) if len(cr) >= MIN_N else None,
                        co_rate=len(cos) / len(pool), co_pct=statistics.median(cop) if cop else None,
                        reasons=top, projects=len({r["project"] for r in pool}),
                        examples=[{k: r[k] for k in ("project", "short_text", "unit", "qty_planned", "qty_actual",
                                                     "change_order", "co_reason")} for r in pool[:3]])

    def match(self, items: list[Item], exclude_project: str = "") -> dict[str, HistInfo]:
        """oz -> what happened to similar work. Text similarity first (same unit family), then work type."""
        if self.mat is None or not items:
            return {}
        q = self.vec.transform([i.short_text for i in items])
        sims_all = (q @ self.mat.T).toarray()
        out = {}
        by_wt: dict[str, list[dict]] = {}
        for r in self.rows:
            if r["work_type"] and r["project"] != exclude_project:
                by_wt.setdefault(r["work_type"], []).append(r)
        for k, it in enumerate(items):
            if not it.short_text.strip():
                continue
            fam = family(it.unit)
            sims = sims_all[k]
            cand = [(sims[j], self.rows[j]) for j in range(len(self.rows))
                    if sims[j] >= MIN_SIM and self.rows[j]["project"] != exclude_project
                    and (fam == "unknown" or family(self.rows[j]["unit"]) in (fam, "unknown"))]
            cand.sort(key=lambda t: -t[0])
            info = self._stats([r for _, r in cand[:25]], "similar", cand[0][1]["short_text"] if cand else "")
            if info is None:
                wt = K.classify(it.short_text, it.long_text)
                if wt and wt.key in by_wt:
                    pool = [r for r in by_wt[wt.key] if fam == "unknown" or family(r["unit"]) in (fam, "unknown")]
                    info = self._stats(pool, "work_type", wt.label)
            if info is not None:
                out[it.oz] = info
        return out


# ---------------------------------------------------------------- findings from history

def _value(it: Item, sugg=None) -> float:
    if it.it:
        return it.it
    up = it.up or (sugg.median if sugg else 0) or 0
    return (it.qty or 0) * up


def check_history(boq: BoQ, model: "HistoryModel | None", sugg: dict | None = None,
                  exclude_project: str = "") -> tuple[list[Flag], dict]:
    if model is None:
        return [], {}
    info = model.match(boq.items, exclude_project=exclude_project)
    sugg = sugg or {}
    flags = []
    src_de = "Beispieldaten (simuliert)" if model.example else "eigene Projekthistorie"
    src_en = "example data (simulated)" if model.example else "own project history"
    for it in boq.items:
        h = info.get(it.oz)
        if not h:
            continue
        val = _value(it, sugg.get(it.oz))
        basis_de = f"{h.n} vergleichbare Positionen aus {h.projects} Projekt(en), {src_de}"
        basis_en = f"{h.n} comparable items from {h.projects} project(s), {src_en}"
        lump = norm_unit(it.unit) == "psch" or it.lump_sum
        if h.qty_ratio is not None and abs(h.qty_ratio - 1) >= 0.2:
            over = h.qty_ratio > 1
            pct = 100 * (h.qty_ratio - 1)
            if lump:
                sev, cat = ("high" if over else "medium"), "risk"
                de_why = ("Pauschalposition: Mehrmengen trägt der AN ohne Mehrvergütung." if over else
                          "Pauschalposition: Mindermengen bleiben vergütet – Kalkulation prüfen.")
                en_why = ("Lump-sum item: extra quantities are carried by the contractor without extra pay." if over else
                          "Lump-sum item: reduced quantities stay paid – check the calculation.")
            elif over:
                sev, cat = "medium", "opportunity"
                de_why = ("Einheitspreis: Mehrmengen > 10 % erlauben nach VOB/B § 2 Abs. 3 einen neuen Preis; "
                          "Fixkosten sind bei Mehrmenge überdeckt.")
                en_why = ("Unit price: extra quantities > 10 % allow a new price under VOB/B § 2(3); "
                          "fixed costs are over-recovered.")
            else:
                sev, cat = "medium", "risk"
                de_why = ("Einheitspreis: Bei Mindermengen > 10 % sind die im EP umgelegten Gemeinkosten nicht gedeckt "
                          "(Anspruch auf Preisanpassung nach VOB/B § 2 Abs. 3 Nr. 3 dokumentieren).")
                en_why = ("Unit price: with quantities reduced by > 10 % the overheads spread over the unit price are not "
                          "covered (document the claim under VOB/B § 2(3) no. 3).")
            flags.append(Flag(
                "R32", "Mengenabweichung aus Erfahrung", sev,
                f"In früheren Projekten wich die abgerechnete Menge bei „{h.label[:60]}“ im Median um {pct:+.0f} % vom LV ab "
                f"({basis_de}). {de_why}",
                oz=it.oz, reference="VOB/B § 2 Abs. 3 (Mengenänderung > 10 %)" + ("; § 2 Abs. 7 (Pauschalvertrag)" if lump else ""),
                exposure_eur=abs(h.qty_ratio - 1) * val, source="history", category=cat,
                data={"qty_ratio": h.qty_ratio, "n": h.n},
                suggestion=("Menge prüfen und Mengenrisiko einpreisen bzw. Bieterfrage stellen." if lump or not over else
                            "Mehrmenge im Blick behalten: rechtzeitig Nachtragsangebot nach § 2 Abs. 3 vorbereiten."),
                en=dict(title="Quantity deviation from experience",
                        message=f"In past projects the billed quantity for '{h.label[:60]}' deviated from the BoQ by a median "
                                f"of {pct:+.0f} % ({basis_en}). {en_why}",
                        suggestion=("Check the quantity and price the quantity risk, or ask a bidder question." if lump or not over
                                    else "Watch the extra quantity: prepare a change-order offer under § 2(3) in time."))))
        if h.co_rate >= 0.3:
            pct_co = h.co_pct if h.co_pct is not None else 0.15
            why_de = ("; typische Gründe: " + "; ".join(h.reasons)) if h.reasons else ""
            why_en = ("; typical reasons: " + "; ".join(h.reasons)) if h.reasons else ""
            flags.append(Flag(
                "R33", "Nachtragsträchtige Leistung", "high" if h.co_rate >= 0.5 else "medium",
                f"Bei {100 * h.co_rate:.0f} % vergleichbarer Positionen gab es Nachträge, im Median {100 * pct_co:.0f} % des "
                f"Positionswerts ({basis_de}){why_de}.",
                oz=it.oz, reference="VOB/B § 2 Abs. 5/6 (geänderte / zusätzliche Leistungen)",
                exposure_eur=h.co_rate * pct_co * val, source="history", category="opportunity",
                data={"co_rate": h.co_rate, "co_pct": pct_co, "n": h.n},
                suggestion="Leistungsgrenzen und Annahmen im Angebot festhalten; Nachtrag früh anmelden (§ 2 Abs. 6: vor Ausführung).",
                en=dict(title="Change-order-prone work",
                        message=f"{100 * h.co_rate:.0f} % of comparable items had change orders, median {100 * pct_co:.0f} % of the "
                                f"item value ({basis_en}){why_en}.",
                        suggestion="Record scope limits and assumptions in the bid; announce change orders early "
                                   "(§ 2(6): before execution).")))
        if h.cost_ratio is not None and h.cost_ratio >= 1.15:
            flags.append(Flag(
                "R34", "Kosten wurden früher unterschätzt", "high" if h.cost_ratio >= 1.3 else "medium",
                f"Die Ist-Kosten je Einheit lagen bei vergleichbaren Positionen im Median {100 * (h.cost_ratio - 1):.0f} % über der Kalkulation "
                f"({basis_de}). Ohne Korrektur wiederholt sich die Unterdeckung.",
                oz=it.oz, reference="Nachkalkulation", exposure_eur=(h.cost_ratio - 1) * val / max(1.0, h.cost_ratio),
                source="history", category="risk", data={"cost_ratio": h.cost_ratio, "n": h.n},
                suggestion="Kalkulationsansatz (Leistungswerte, Material, Gerät) anhand der Nachkalkulation korrigieren.",
                en=dict(title="Costs were underestimated before",
                        message=f"Actual unit costs of comparable items were a median {100 * (h.cost_ratio - 1):.0f} % above the "
                                f"calculation ({basis_en}). Without correction the shortfall repeats.",
                        suggestion="Correct the calculation basis (output rates, material, plant) from the post-calculation.")))
    return flags, info


# ---------------------------------------------------------------- markup suggestion

def markup_table(boq: BoQ, flags: list[Flag], info: dict, sugg: dict | None = None, base: float = 0.12,
                 cap: float = 0.30, overhead_share: float = 0.10) -> list[dict]:
    """Per item: base markup (overheads + profit) + history surcharge + findings surcharge.

    history:  own-cost overrun on similar work (always the contractor's), for lump-sum items the quantity overrun,
              for unit-price items a typical quantity shortfall (overheads recovered from fewer units)
    findings: money at risk from risk-type findings (not opportunities) as a share of the item value, max 15 %
    """
    sugg = sugg or {}
    risk_by_oz: dict[str, float] = {}
    for f in flags:
        if f.oz and f.category == "risk" and f.severity in ("high", "medium") and f.decision.get("status") != "dismissed" \
                and f.source != "history":
            risk_by_oz[f.oz] = risk_by_oz.get(f.oz, 0.0) + f.exposure_eur
    rows = []
    for it in boq.items:
        val = _value(it, sugg.get(it.oz))
        h = info.get(it.oz)
        hist = 0.0
        why = []
        lump = norm_unit(it.unit) == "psch" or it.lump_sum
        if h and h.cost_ratio and h.cost_ratio > 1.03:              # below 3 % is noise
            hist += h.cost_ratio - 1
            why.append(("cost", h.cost_ratio))
        if h and h.qty_ratio and h.qty_ratio > 1 and lump:
            hist += h.qty_ratio - 1
            why.append(("lump_qty", h.qty_ratio))
        if h and h.qty_ratio and h.qty_ratio < 0.9 and not lump:
            # the overheads spread over the planned quantity must be recovered from the smaller billed quantity
            hist += overhead_share * (1 / h.qty_ratio - 1)
            why.append(("under_qty", h.qty_ratio))
        fnd = min(0.15, risk_by_oz.get(it.oz, 0.0) / val) if val > 0 else 0.0
        total = min(base + cap, base + hist + fnd)
        rows.append({"oz": it.oz, "short_text": it.short_text, "value": val, "base": base, "history": hist,
                     "findings": fnd, "markup": total, "why": why, "n": h.n if h else 0})
    return rows


def expected_change_orders(info: dict, boq: BoQ, sugg: dict | None = None) -> float:
    sugg = sugg or {}
    tot = 0.0
    for it in boq.items:
        h = info.get(it.oz)
        if h:
            tot += h.co_rate * (h.co_pct if h.co_pct is not None else 0.15) * _value(it, sugg.get(it.oz))
    return tot


# ---------------------------------------------------------------- template + example data

TEMPLATE_HEADER = ["Projekt", "OZ", "Kurztext", "Einheit", "Menge_LV", "Menge_Ist", "EP", "Kosten_Soll", "Kosten_Ist",
                   "Nachtrag", "Nachtrag_EUR", "Nachtrag_Grund"]


def template_csv() -> str:
    return ";".join(TEMPLATE_HEADER) + "\n" + \
        "Neubau Kita Nord;2.1.20;Baugrubenaushub Homogenbereich B;m3;1200;1450;24,50;26000;31500;ja;5400;Mehrmenge Fels\n"


# simulated behaviour per work type: (qty factor mean, sd, change-order probability, CO share, cost factor, reasons)
_SIM = {
    "aushub": (1.18, 0.12, 0.45, 0.18, 1.08, ["Bodenklasse/Homogenbereich abweichend", "Mehrmenge Aushub", "Wasserhaltung erforderlich"]),
    "entsorgung": (1.22, 0.15, 0.55, 0.25, 1.12, ["belastetes Material (Z1.2/Z2)", "Deponiewechsel", "Mehrmenge"]),
    "verfuellen": (1.10, 0.10, 0.25, 0.10, 1.05, ["Austausch Boden nicht verdichtbar"]),
    "wasserhaltung": (1.35, 0.25, 0.60, 0.30, 1.15, ["längere Vorhaltung", "höherer Grundwasserstand"]),
    "be": (1.00, 0.02, 0.35, 0.12, 1.18, ["Bauzeitverlängerung", "zusätzliche Container"]),
    "beton": (1.04, 0.06, 0.20, 0.08, 1.06, ["Planänderung", "geänderte Expositionsklasse"]),
    "betonstahl": (1.08, 0.08, 0.30, 0.10, 1.10, ["Bewehrungsmehrmenge nach Statik"]),
    "schalung": (1.06, 0.07, 0.15, 0.08, 1.12, ["Sichtbetonanforderung nachträglich"]),
    "abdichtung": (1.05, 0.08, 0.40, 0.15, 1.10, ["Wassereinwirkungsklasse geändert", "Durchdringungen zusätzlich"]),
    "rohr": (1.07, 0.08, 0.30, 0.12, 1.06, ["Leitungsbestand nicht wie Plan", "Umverlegung"]),
    "drainage": (1.08, 0.09, 0.25, 0.10, 1.05, ["Mehrlänge"]),
    "strasse": (1.03, 0.05, 0.20, 0.07, 1.09, ["Bitumenpreis (Gleitklausel)", "Anschlussflächen"]),
    "tragschicht": (1.06, 0.07, 0.20, 0.08, 1.04, ["Bodenaustausch"]),
    "oberboden": (1.12, 0.10, 0.20, 0.08, 1.03, ["Mehrmenge Oberboden"]),
    "geruest": (1.10, 0.10, 0.35, 0.15, 1.08, ["längere Standzeit"]),
    "mauerwerk": (1.02, 0.04, 0.12, 0.05, 1.04, ["Planänderung"]),
    "daemmung": (1.02, 0.04, 0.10, 0.05, 1.03, []),
}


def make_example(price_rows: list[dict], path: Path = EXAMPLE_PATH, seed: int = 7) -> Path:
    """SIMULATED history for the demo: real item texts (from the price database) with invented actuals.
    The project names say so – this file must never be presented as real data."""
    import csv
    import random
    rnd = random.Random(seed)
    usable = [r for r in price_rows if r.get("short") and r.get("unit") and r.get("up")]
    out = []
    for p in range(1, 7):
        proj = f"BEISPIEL {chr(64 + p)} (simuliert)"
        for r in rnd.sample(usable, min(120, len(usable))):
            wt = K.classify(r["short"])
            mu, sd, pco, coshare, cf, reasons = _SIM.get(wt.key if wt else "", (1.0, 0.05, 0.10, 0.06, 1.02, []))
            qp = rnd.choice([1, 1, 5, 12, 40, 120, 350, 900]) if norm_unit(r["unit"]) != "psch" else 1
            qa = max(0.0, qp * rnd.gauss(mu, sd)) if norm_unit(r["unit"]) != "psch" else 1
            cost_p = qp * r["up"] * 0.88
            cost_a = qa * r["up"] * 0.88 * rnd.gauss(cf, 0.05)
            co = rnd.random() < pco
            out.append([proj, r.get("oz", ""), r["short"][:140], r["unit"], f"{qp:.2f}", f"{qa:.2f}", f"{r['up']:.2f}",
                        f"{cost_p:.2f}", f"{cost_a:.2f}", "ja" if co else "nein",
                        f"{qp * r['up'] * max(0.02, rnd.gauss(coshare, 0.05)):.2f}" if co else "",
                        rnd.choice(reasons) if co and reasons else ""])
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Projekt", "OZ", "Kurztext", "Einheit", "Menge_LV", "Menge_Ist", "EP", "Kosten_Soll", "Kosten_Ist",
                    "Nachtrag", "Nachtrag_EUR", "Nachtrag_Grund"])
        w.writerows(out)
    return path


def price_rows(model: "HistoryModel") -> list[dict]:
    """Past unit prices of the company in the price-database row format (prices.PriceModel)."""
    return [{"text": r["short_text"], "short": r["short_text"][:120], "unit": r["unit"], "up": r["up"],
             "source": f"Historie: {r['project']}", "oz": r["oz"], "project": r["project"]}
            for r in model.rows if r["up"] and r["up"] > 0 and r["unit"]]


def suggested_up(ref_up: float | None, markup: float, base: float) -> float | None:
    """Reference unit price (own or comparable) with the base markup swapped for the risk-adjusted one."""
    if not ref_up:
        return None
    return ref_up / (1 + base) * (1 + markup)
