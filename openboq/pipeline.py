"""One call: BoQ (+ optional IFC, + optional LLM) -> findings, per-item risk, headline numbers."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .model import BoQ, Flag
from .rules import run_rules

SEV_RANK = {"high": 3, "medium": 2, "low": 1, "info": 0}


@dataclass
class Result:
    boq: BoQ
    flags: list[Flag]
    ifc_table: list[dict] = field(default_factory=list)
    price_suggestions: dict = field(default_factory=dict)   # oz -> prices.Suggestion
    summary: str = ""
    seconds: float = 0.0

    @property
    def counted(self) -> list[Flag]:
        return [f for f in self.flags if f.severity in ("high", "medium") and f.decision.get("status") != "dismissed"]

    @property
    def dismissed(self) -> list[Flag]:
        return [f for f in self.flags if f.decision.get("status") == "dismissed"]

    @property
    def exposure(self) -> float:
        """Change-order exposure: high/medium findings, excluding provisional-item budget (info)."""
        return sum(f.exposure_eur for f in self.counted)

    def by_severity(self) -> dict[str, int]:
        out = {k: 0 for k in SEV_RANK}
        for f in self.flags:
            out[f.severity] = out.get(f.severity, 0) + 1
        return out

    def item_risk(self) -> dict[str, dict]:
        risk: dict[str, dict] = {}
        for f in self.flags:
            if not f.oz or f.decision.get("status") == "dismissed":
                continue
            r = risk.setdefault(f.oz, {"exposure": 0.0, "severity": "info", "n": 0})
            if f.severity in ("high", "medium"):
                r["exposure"] += f.exposure_eur
            r["n"] += 1
            if SEV_RANK[f.severity] > SEV_RANK[r["severity"]]:
                r["severity"] = f.severity
        return risk


def analyze(boq: BoQ, ifc=None, use_llm: bool = False, llm_client=None, model: Optional[str] = None,
            lang: str = "de", prices="auto", source: str = "", feedback="auto", rules="auto",
            meta: dict | None = None) -> Result:
    """prices: a prices.PriceModel, None (off) or "auto" (load data/price_db.json if it exists).
    source: file name of the BoQ, so its own project is never used as its price reference."""
    t0 = time.time()
    flags = run_rules(boq)
    sugg = {}
    if prices == "auto":
        from .prices import PriceModel
        prices = PriceModel.load()
    if prices is not None:
        from .prices import check_learned_prices
        f_p, sugg = check_learned_prices(boq, prices, source or boq.name)
        flags += f_p
    table: list[dict] = []
    if ifc is not None:
        from .ifc_check import check_ifc
        f2, table = check_ifc(boq, ifc)
        flags += f2
    summary = ""
    if use_llm:
        from . import llm_checks
        kw = {"client": llm_client} if llm_client else {}
        if model:
            kw["model"] = model
        flags += llm_checks.llm_item_checks(boq, known=flags, lang=lang, **kw)
        try:
            summary = llm_checks.llm_summary(boq, flags, lang=lang, **kw)
        except Exception:
            summary = ""
    from .rules import CATEGORY, _question
    llm_cat = {"unklar": "opportunity", "pflichtangabe": "risk", "besondere_l": "opportunity", "widerspruch": "error",
               "einheit_meng": "error", "risikoverlag": "risk"}
    for f in flags:
        if not f.category:
            f.category = CATEGORY.get(f.rule_id) or llm_cat.get(f.rule_id[3:].lower(), "risk")
        if not f.question and f.severity in ("high", "medium") and f.source != "rules":
            f.question = _question(f, boq)
    if feedback == "auto":
        from .feedback import DB_PATH, FeedbackStore
        feedback = FeedbackStore() if DB_PATH.exists() else None
    if feedback is not None:
        from .feedback import apply_learning
        apply_learning(flags, boq, feedback)
    if rules == "auto":
        from .userrules import load_rules
        rules = load_rules()
    if rules:
        from .userrules import apply_rules
        apply_rules(flags, boq, rules, meta or {})
    flags.sort(key=lambda f: (-SEV_RANK[f.severity], -f.exposure_eur))
    return Result(boq=boq, flags=flags, ifc_table=table, summary=summary, seconds=time.time() - t0, price_suggestions=sugg)
