"""Common data model for bills of quantities (Leistungsverzeichnis, LV) and findings."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Item:
    """One BoQ line item (LV-Position)."""
    oz: str                      # Ordnungszahl, e.g. "03.02.0010"
    short_text: str              # Kurztext
    long_text: str = ""          # Langtext
    qty: Optional[float] = None  # Menge
    unit: str = ""               # Einheit (m2, m3, St, psch, t, ...)
    up: Optional[float] = None   # Einheitspreis (EP)
    it: Optional[float] = None   # Gesamtbetrag (GP)
    section: str = ""            # Titel / Los label, e.g. "03 Beton- und Stahlbetonarbeiten"
    section_oz: str = ""         # e.g. "03"
    provisional: bool = False    # Bedarfs-/Eventualposition (GAEB <Provis>)
    alternative: bool = False    # Wahl-/Alternativposition (GAEB <ALNGroupNo>/<ALNSerNo>)
    lump_sum: bool = False       # Pauschalposition (GAEB <LumpSumItem>)
    qty_tbd: bool = False        # Menge noch festzulegen (GAEB <QtyTBD>)
    hourly: bool = False         # Stundenlohnarbeiten (GAEB <HourIt>)
    stlb: bool = False           # Item carries an STLB-Bau reference (standardised text)
    raw_id: str = ""             # GAEB ID attribute, for write-back
    issues: list = field(default_factory=list)   # parse problems, e.g. "Menge unlesbar: '1,5,0'"

    @property
    def text(self) -> str:
        return f"{self.short_text}\n{self.long_text}".strip()

    @property
    def total(self) -> float:
        """Best estimate of the item's money value."""
        if self.it is not None:
            return float(self.it)
        if self.qty is not None and self.up is not None:
            return float(self.qty) * float(self.up)
        return 0.0


@dataclass
class Flag:
    """One finding."""
    rule_id: str                 # e.g. "R01"
    title: str                   # short German/English label
    severity: str                # "high" | "medium" | "low" | "info"
    message: str                 # human explanation
    oz: str = ""                 # affected item ("" = whole LV)
    reference: str = ""          # legal / normative basis (VOB/B, VOB/C, DIN ...)
    exposure_eur: float = 0.0    # estimated money at risk
    suggestion: str = ""         # proposed fix
    source: str = "rules"        # "rules" | "ifc" | "llm"
    confidence: float = 1.0
    en: dict = field(default_factory=dict)   # English texts: {"title", "message", "suggestion"}
    category: str = ""           # "error" | "risk" | "opportunity" | "security" (contractor view)
    question: dict = field(default_factory=dict)   # bidder question {"de": ..., "en": ...}
    decision: dict = field(default_factory=dict)   # {"status": confirmed|dismissed, "by", "at", "reason", "source"}
    learned: dict = field(default_factory=dict)    # calibration note {"de", "en"} when severity was lowered
    data: dict = field(default_factory=dict)       # machine-readable details (e.g. price ratio) for rules
    fp: str = ""                 # stable fingerprint, used to remember decisions across runs
    status: str = "open"         # open | confirmed | dismissed | suppressed
    status_note: str = ""        # why (reason of the decision / rule that suppressed it)

    @property
    def active(self) -> bool:
        return self.status in ("open", "confirmed")

    def txt(self, lang: str = "de") -> tuple[str, str, str]:
        """(title, message, suggestion) in the requested language, German as fallback."""
        if lang == "en" and self.en:
            return (self.en.get("title") or self.title, self.en.get("message") or self.message,
                    self.en.get("suggestion", self.suggestion))
        return self.title, self.message, self.suggestion

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BoQ:
    project: str = ""
    name: str = ""
    currency: str = "EUR"
    phase: str = ""              # GAEB data phase: 81, 83, 84, 86 ...
    items: list[Item] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)  # section_oz -> label
    notes: list[dict] = field(default_factory=list)          # preliminary notes / remarks: {"ref", "text"}
    client: str = ""                                         # Auftraggeber, if known

    @property
    def total(self) -> float:
        return sum(i.total for i in self.items if not i.provisional and not i.alternative)

    def by_oz(self) -> dict[str, Item]:
        return {i.oz: i for i in self.items}
