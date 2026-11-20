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
    summary: str = ""
    seconds: float = 0.0

    @property
    def counted(self) -> list[Flag]:
        return [f for f in self.flags if f.severity in ("high", "medium")]

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
            if not f.oz:
                continue
            r = risk.setdefault(f.oz, {"exposure": 0.0, "severity": "info", "n": 0})
            if f.severity in ("high", "medium"):
                r["exposure"] += f.exposure_eur
            r["n"] += 1
            if SEV_RANK[f.severity] > SEV_RANK[r["severity"]]:
                r["severity"] = f.severity
        return risk


def analyze(boq: BoQ, ifc=None, use_llm: bool = False, llm_client=None, model: Optional[str] = None) -> Result:
    t0 = time.time()
    flags = run_rules(boq)
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
        flags += llm_checks.llm_item_checks(boq, known=flags, **kw)
        try:
            summary = llm_checks.llm_summary(boq, flags, **kw)
        except Exception:
            summary = ""
    flags.sort(key=lambda f: (-SEV_RANK[f.severity], -f.exposure_eur))
    return Result(boq=boq, flags=flags, ifc_table=table, summary=summary, seconds=time.time() - t0)
