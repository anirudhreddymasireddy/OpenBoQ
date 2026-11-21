"""One call: BoQ (+ optional LLM) -> findings, per-item risk, headline numbers."""
from __future__ import annotations

import os
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
    price_suggestions: dict = field(default_factory=dict)   # oz -> prices.Suggestion
    llm_errors: list = field(default_factory=list)           # AI batches that failed (e.g. rate limit)
    project_notes: list = field(default_factory=list)        # cross-file observations (crossfile.project_notes)
    history_info: dict = field(default_factory=dict)         # oz -> history.HistInfo (past projects)
    history_model: object = None                             # history.HistoryModel used
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


def _judge_candidates(flags, sent: set, failed: bool = False):
    """Short-text candidates from the rules (R27 'cut off' / 'without details') are decided by the AI: confirmed ones
    become medium, rejected ones (AI saw the item and found the context clear) become info. Empty short texts stay high
    – that is objective. Without an AI run the candidates keep their rule severity."""
    if failed:
        return
    ai_oz = {f.oz for f in flags if f.source == "llm" and f.oz}
    for f in flags:
        if f.rule_id != "R27" or f.severity == "high" or f.oz not in sent or f.title != "Kurztext ohne Angaben":
            continue                      # empty or visibly cut-off texts are objective; only one-word texts need judgment
        if f.oz in ai_oz:
            f.severity = "medium"
            f.message += " (KI bestätigt: im Zusammenhang unklar)"
            if f.en:
                f.en["message"] = f.en.get("message", "") + " (confirmed by AI: unclear in context)"
        else:
            f.severity = "info"
            f.message += " (KI: im Zusammenhang eindeutig)"
            if f.en:
                f.en["message"] = f.en.get("message", "") + " (AI: clear from context)"


def _merge_ai_duplicates(flags):
    """The AI sometimes re-reports what a rule already found on the same item (e.g. 'missing description' next to
    'Short text missing'). Keep the rule finding (exact, cited), attach the AI's wording to it, drop the copy –
    so nothing is counted twice."""
    MISSING = ("missing", "fehlt", "fehlend", "unvollständig", "incomplete", "unclear", "unklar", "without")
    rule_by_oz = {}
    for f in flags:
        if f.source == "rules" and f.oz and f.severity in ("high", "medium"):
            rule_by_oz.setdefault(f.oz, []).append(f)
    lv_rules = [f for f in flags if f.source == "rules" and not f.oz and f.rule_id in ("R20", "R26")]
    CLAUSE_WORDS = {"strafe": "penalty", "vertragsstrafe": "penalty", "penalty": "penalty", "vergütet": "price_in",
                    "einzurechnen": "price_in", "zu lasten": "risk_shift", "risikoverlag": "risk_shift"}
    out = []
    for f in flags:
        if f.source != "rules" and not f.oz and lv_rules:
            words = {v for k, v in CLAUSE_WORDS.items() if k in (f.title + " " + f.message).lower()}
            twin = next((r for r in lv_rules if words and any(
                w in (r.title + " " + r.message).lower() for k, w2 in CLAUSE_WORDS.items() if w2 in words for w in (k,))), None)
            if twin is not None:
                twin.message += f" · KI: {f.txt('de')[1][:200]}"
                if twin.en:
                    twin.en["message"] = twin.en.get("message", "") + f" · AI: {f.txt('en')[1][:200]}"
                continue
        if f.source != "rules" and f.oz in rule_by_oz:
            title = (f.title + " " + f.txt("en")[0]).lower()
            twin = next((r for r in rule_by_oz[f.oz] if r.category == f.category or
                         (r.rule_id == "R27" and any(w in title for w in MISSING)) or
                         (r.rule_id in ("R01", "R22") and any(w in title for w in ("calculat", "rechen", "format", "total")))),
                        None)
            if twin is not None:
                de_m, en_m = f.txt("de")[1], f.txt("en")[1]
                twin.message += f" · KI: {de_m[:200]}"
                if twin.en:
                    twin.en["message"] = twin.en.get("message", "") + f" · AI: {en_m[:200]}"
                twin.confidence = max(twin.confidence or 0, 0.95)
                continue
        out.append(f)
    return out


_MERGED: dict = {}                               # (price model, history) -> merged model, built once


def analyze(boq: BoQ, use_llm: bool = False, llm_client=None, model: Optional[str] = None,
            lang: str = "de", prices="auto", source: str = "", feedback="auto", rules="auto",
            meta: dict | None = None, history="auto") -> Result:
    """prices: a prices.PriceModel, None (off) or "auto" (load data/price_db.json if it exists).
    source: file name of the BoQ, so its own project is never used as its price reference."""
    t0 = time.time()
    flags = run_rules(boq)
    sugg = {}
    if prices == "auto":
        from .prices import PriceModel
        prices = PriceModel.load()
    if history == "auto":
        from .history import HistoryModel
        history = HistoryModel.load()            # data/history.csv – the company's own past projects, if present
    elif isinstance(history, (str, os.PathLike)):
        from .history import HistoryModel
        history = HistoryModel.load(history)
    if history is not None and not history.example and prices is not None:
        from .history import price_rows
        from .prices import PriceModel
        mk = (id(prices), id(history))
        if mk not in _MERGED:                     # own past unit prices also feed the price suggestions
            _MERGED.clear()
            _MERGED[mk] = (prices, history, PriceModel(prices.rows + price_rows(history)))
        prices = _MERGED[mk][2]
    if prices is not None:
        from .prices import check_learned_prices
        f_p, sugg = check_learned_prices(boq, prices, source or boq.name)
        flags += f_p
    hinfo: dict = {}
    if history is not None:
        from .history import check_history
        f_h, hinfo = check_history(boq, history, sugg)
        flags += f_h
    summary = ""
    llm_errors: list[str] = []
    if use_llm:
        from . import llm_checks
        kw = {"client": llm_client} if llm_client else {}
        if model:
            kw["model"] = model
        try:
            flags += llm_checks.llm_item_checks(boq, known=flags, lang=lang, **kw)
        except Exception as e:                    # no key / provider down: keep the rule results
            llm_checks.LAST_ERRORS.append(f"AI layer: {type(e).__name__} {str(e)[:160]}")
        llm_errors = list(llm_checks.LAST_ERRORS)
        _judge_candidates(flags, llm_checks.LAST_SENT, failed=bool(llm_errors))
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
    flags = _merge_ai_duplicates(flags)
    if use_llm and os.environ.get("NR_CHALLENGE", "on") != "off":
        from . import llm_checks
        try:                                      # client-side reviewer tries to rebut the strongest findings
            llm_checks.llm_challenge(boq, flags, lang=lang, **({"client": llm_client} if llm_client else {}))
        except Exception as e:
            llm_errors.append(f"client reviewer: {type(e).__name__} {str(e)[:120]}")
    if feedback == "auto":
        from .feedback import DB_PATH, FeedbackStore
        feedback = FeedbackStore() if DB_PATH.exists() else None
    if feedback is not None:
        from .feedback import apply_learning, apply_manual
        apply_manual(flags, boq, feedback)        # team findings for the same / similar items
        apply_learning(flags, boq, feedback)
    if rules == "auto":
        from .userrules import load_rules
        rules = load_rules()
    if rules:
        from .userrules import apply_rules
        apply_rules(flags, boq, rules, meta or {})
    flags.sort(key=lambda f: (-SEV_RANK[f.severity], -f.exposure_eur))
    return Result(boq=boq, flags=flags, summary=summary, seconds=time.time() - t0, price_suggestions=sugg, llm_errors=llm_errors, history_info=hinfo, history_model=history)
