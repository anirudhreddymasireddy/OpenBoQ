"""Learn unit prices from past priced BoQs (bids D84/X84, awards D86/X86, priced PDFs) and use them to
 - flag unit prices far outside what comparable past items cost (speculative / mistyped prices),
 - suggest a unit-price range for unpriced tender items (estimating aid).

Matching = text similarity (TF-IDF char n-grams by default, BGE-M3 if NR_EMBED=bge-m3) within the same unit.
Build the database once:   python cli.py learn dataset/      -> data/price_db.json (git-ignored)
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .fmt import de
from .fmt import en as E
from .model import BoQ, Flag, Item
from .units import norm_unit

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "price_db.json"
MIN_SIM = 0.45          # cosine similarity needed to call a past item "comparable"
STRONG_SIM = 0.75
K = 5


def _item_text(it: Item) -> str:
    return re.sub(r"\s+", " ", f"{it.short_text} {it.long_text[:400]}").strip()


_PRICED_LINE = re.compile(r"\d,\d{2,3}\s+\d{1,3}(?:\.\d{3})*,\d{2}\s*$", re.M)


def has_prices(path) -> bool:
    """Cheap pre-check so `learn` does not fully parse tenders without prices."""
    p = Path(path)
    suf = p.suffix.lower()
    try:
        if suf == ".pdf":
            from .pdf_parser import _pages_pdfium
            return len(_PRICED_LINE.findall("\n".join(_pages_pdfium(p)))) >= 5
        raw = p.read_bytes()
        if raw.lstrip()[:1] == b"<":
            return b"<UP>" in raw or b"<UP " in raw
        return any(l[:2] == b"23" for l in raw.splitlines()[:5000])     # GAEB 90 price records
    except Exception:
        return True


def build_db(paths) -> list[dict]:
    from .gaeb_parser import load_boq
    rows = []
    for p in paths:
        if not has_prices(p):
            continue
        try:
            boq = load_boq(p)
        except Exception:
            continue
        for it in boq.items:
            if not it.up or it.up <= 0 or not it.unit or len(it.short_text.strip()) < 6:
                continue
            rows.append({"text": _item_text(it), "short": it.short_text.strip()[:120], "unit": norm_unit(it.unit),
                         "up": round(float(it.up), 2), "source": Path(p).name, "oz": it.oz})
    rows = assign_projects(rows)
    seen, out = set(), []
    for r in rows:                                  # the same item in PDF + GAEB of one project counts once
        key = (r["project"], r["short"].lower(), r["unit"], r["up"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def assign_projects(rows: list[dict]) -> list[dict]:
    """Files that share many identical items (same project as bid / award / PDF) get one project id,
    so evaluation and flagging never compare an item with its own project."""
    sets = {}
    for r in rows:
        sets.setdefault(r["source"], set()).add((r["unit"], r["up"]))      # same prices = same project
    names = sorted(sets)
    parent = {n: n for n in names}

    def find(n):
        while parent[n] != n:
            n = parent[n]
        return n
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            inter = len(sets[a] & sets[b])
            if inter >= 0.3 * min(len(sets[a]), len(sets[b])):
                parent[find(b)] = find(a)
    for r in rows:
        r["project"] = find(r["source"])
    return rows


def save_db(rows: list[dict], path: Path = DB_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    return path


def load_db(path: Path = DB_PATH) -> list[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []


@dataclass
class Suggestion:
    median: float
    lo: float
    hi: float
    n: int
    best_sim: float
    examples: list[dict]


class PriceModel:
    def __init__(self, rows: list[dict]):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.rows = rows
        self.by_unit: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            self.by_unit.setdefault(r["unit"], []).append(i)
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True, sublinear_tf=True)
        self.mat = self.vec.fit_transform([r["text"] for r in rows]) if rows else None

    @classmethod
    def load(cls, path: Path = DB_PATH) -> "PriceModel | None":
        rows = load_db(path)
        return cls(rows) if rows else None

    def project_of(self, source: str, items: list[Item] | None = None) -> str:
        """Project id of a file: known from the DB, or the DB project sharing most item texts with it."""
        for r in self.rows:
            if r["source"] == source:
                return r.get("project", source)
        if items:
            shorts = {(i.short_text.strip().lower()[:120], norm_unit(i.unit)) for i in items}
            best, n = "", 0
            counts = {}
            for r in self.rows:
                if (r["short"].lower(), r["unit"]) in shorts:
                    counts[r.get("project", r["source"])] = counts.get(r.get("project", r["source"]), 0) + 1
            for proj, c in counts.items():
                if c > n:
                    best, n = proj, c
            if n >= 0.3 * max(1, len(shorts)):
                return best
        return source

    def suggest_many(self, items: list[Item], exclude_source: str = "") -> dict[str, Suggestion]:
        if self.mat is None or not items:
            return {}
        exclude_project = self.project_of(exclude_source, items) if exclude_source else ""
        q = self.vec.transform([_item_text(i) for i in items])
        out = {}
        for row_i, it in enumerate(items):
            idx = self.by_unit.get(norm_unit(it.unit), [])
            idx = [j for j in idx if self.rows[j]["source"] != exclude_source
                   and self.rows[j].get("project", self.rows[j]["source"]) != exclude_project]
            if not idx:
                continue
            sims = (self.mat[idx] @ q[row_i].T).toarray().ravel()
            order = np.argsort(-sims)[:K]
            hits = [(idx[o], float(sims[o])) for o in order if sims[o] >= MIN_SIM]
            if not hits:
                continue
            ups = [self.rows[j]["up"] for j, _ in hits]
            out[it.oz] = Suggestion(median=statistics.median(ups), lo=min(ups), hi=max(ups), n=len(hits),
                                    best_sim=hits[0][1],
                                    examples=[{**self.rows[j], "sim": round(s, 2)} for j, s in hits[:3]])
        return out


def check_learned_prices(boq: BoQ, model: "PriceModel | None", source: str = "") -> tuple[list[Flag], dict]:
    """Flags for prices far from comparable past items + suggestions for every matchable item."""
    if model is None:
        return [], {}
    sugg = model.suggest_many(boq.items, exclude_source=source)
    flags = []
    for it in boq.items:
        s = sugg.get(it.oz)
        if not s or not it.up or it.up <= 0 or it.qty is None:
            continue
        strong = s.n >= 2 or s.best_sim >= STRONG_SIM
        if not strong:
            continue
        ex = s.examples[0]
        ex_de = f"z. B. „{ex['short'][:60]}“ {de(ex['up'], 2)} €/{ex['unit']} ({ex['source']})"
        ex_en = f"e.g. '{ex['short'][:60]}' €{E(ex['up'])}/{ex['unit']} ({ex['source']})"
        ratio = it.up / s.median if s.median else 1
        if ratio <= 1 / 3:
            sev = "high" if ratio <= 1 / 10 else "medium"
            flags.append(Flag(
                "R24", "Einheitspreis weit unter Vergleichspreisen", sev,
                f"EP {de(it.up, 2)} €/{it.unit} – vergleichbare Positionen aus früheren Projekten: Median {de(s.median, 2)} € "
                f"({de(s.lo, 2)}–{de(s.hi, 2)} €, n = {s.n}); {ex_de}. Faktor {ratio:.2f}. "
                "Tippfehler (Komma) oder Spekulationspreis – bei Mengenmehrung droht Unterdeckung.",
                oz=it.oz, reference="VOB/A § 16d Abs. 1; VOB/B § 2 Abs. 3 (Mengenmehrung > 10 %)",
                exposure_eur=(s.median - it.up) * it.qty,
                data={"direction": "low", "up": it.up, "ref": s.median, "factor": 1 / 3},
                suggestion=f"Preis prüfen; Vergleichsbereich {de(s.lo, 2)}–{de(s.hi, 2)} €/{it.unit}.",
                source="prices",
                en=dict(title="Unit price far below comparable past prices",
                        message=f"Unit price €{E(it.up)}/{it.unit} – comparable items from past projects: median €{E(s.median)} "
                                f"(€{E(s.lo)}–{E(s.hi)}, n = {s.n}); {ex_en}. Factor {ratio:.2f}. "
                                "Typo (decimal point) or speculative price – if the quantity grows, costs will not be covered.",
                        suggestion=f"Check the price; comparable range €{E(s.lo)}–{E(s.hi)}/{it.unit}.")))
        elif ratio >= 3:
            sev = "high" if ratio >= 10 else "medium"
            flags.append(Flag(
                "R24", "Einheitspreis weit über Vergleichspreisen", sev,
                f"EP {de(it.up, 2)} €/{it.unit} – vergleichbare Positionen: Median {de(s.median, 2)} € "
                f"({de(s.lo, 2)}–{de(s.hi, 2)} €, n = {s.n}); {ex_de}. Faktor {ratio:.1f}. Tippfehler oder Spekulationspreis?",
                oz=it.oz, reference="VOB/A § 16d Abs. 1",
                exposure_eur=(it.up - s.median) * it.qty,
                data={"direction": "high", "up": it.up, "ref": s.median, "factor": 3},
                suggestion=f"Preis prüfen; Vergleichsbereich {de(s.lo, 2)}–{de(s.hi, 2)} €/{it.unit}.",
                source="prices",
                en=dict(title="Unit price far above comparable past prices",
                        message=f"Unit price €{E(it.up)}/{it.unit} – comparable items: median €{E(s.median)} "
                                f"(€{E(s.lo)}–{E(s.hi)}, n = {s.n}); {ex_en}. Factor {ratio:.1f}. Typo or speculative price?",
                        suggestion=f"Check the price; comparable range €{E(s.lo)}–{E(s.hi)}/{it.unit}.")))
    return flags, sugg


def evaluate_leave_one_out(rows: list[dict]) -> dict:
    """For every priced item, predict its price from *other* files only. Honest accuracy of the suggestions."""
    model = PriceModel(rows)
    errs, covered = [], 0
    by_src: dict[str, list[dict]] = {}
    for r in rows:
        by_src.setdefault(r["source"], []).append(r)
    # predict each file from other *projects* only
    for src, rs in by_src.items():
        items = [Item(oz=f"{k}", short_text=r["text"], unit=r["unit"]) for k, r in enumerate(rs)]
        sugg = model.suggest_many(items, exclude_source=src)
        for k, r in enumerate(rs):
            s = sugg.get(str(k))
            if s:
                covered += 1
                errs.append(abs(s.median - r["up"]) / r["up"])
    return {"items": len(rows), "files": len(by_src), "covered": covered,
            "coverage": covered / max(1, len(rows)),
            "median_abs_pct_error": statistics.median(errs) if errs else None,
            "within_50pct": (sum(e <= 0.5 for e in errs) / len(errs)) if errs else None}
