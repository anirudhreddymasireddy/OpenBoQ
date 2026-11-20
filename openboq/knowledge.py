"""Domain knowledge: work types (Leistungsarten), expected units, mandatory parameters,
reference price ranges, and companion-item rules.

IMPORTANT: the reference price ranges below are illustrative placeholders for the demo.
Replace them with the sponsor's historical prices or a cost database (e.g. BKI, sirAdos)
before making any real claim about prices.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class WorkType:
    key: str
    label: str
    match: str                          # regex on short text (case-insensitive)
    families: tuple[str, ...]           # allowed unit families
    params: list[tuple[str, str, str]] = field(default_factory=list)  # (name, regex, why)
    price: dict[str, tuple[float, float]] = field(default_factory=dict)  # unit -> (min, max) EUR
    norm: str = ""                      # VOB/C ATV
    measurable: bool = True             # should normally be measured, not lump sum


WORK_TYPES: list[WorkType] = [
    WorkType("be", "Baustelleneinrichtung", r"baustelleneinrichtung|baustrom|bauwasser|bauzaun|turmdrehkran|kran vorhalten",
             ("lump", "length", "time", "count"), measurable=False, norm="DIN 18299"),
    WorkType("schalung", "Schalung", r"schalung",
             ("area", "length"), price={"m2": (22, 75), "m": (12, 45)}, norm="DIN 18331"),
    WorkType("betonstahl", "Betonstahl / Bewehrung", r"betonstahl|bewehrung|baustahlmatten|betonstahlmatten",
             ("mass",), params=[("Stahlsorte", r"b\s?500\s?[ab]?", "Stahlsorte (z. B. B500B) fehlt – Preis- und Nachtragsrisiko")],
             price={"t": (1100, 2400), "kg": (1.1, 2.4)}, norm="DIN 18331"),
    WorkType("sauberkeit", "Sauberkeitsschicht", r"sauberkeitsschicht|unterbeton",
             ("area", "volume"), params=[("Festigkeitsklasse", r"c\s?\d{1,2}\s?/\s?\d{2}", "Betonfestigkeitsklasse fehlt")],
             price={"m2": (5, 18), "m3": (110, 220)}, norm="DIN 18331"),
    WorkType("fertigteil", "Betonfertigteil", r"fertigteil",
             ("count", "area", "length", "volume"), norm="DIN 18331"),
    WorkType("beton", "Ortbeton / Stahlbeton", r"beton|stahlbeton",
             ("volume",),
             params=[("Festigkeitsklasse", r"c\s?\d{1,2}\s?/\s?\d{2}", "Betonfestigkeitsklasse (z. B. C25/30) fehlt"),
                     ("Expositionsklasse", r"\bx(0|c[1-4]|d[1-3]|s[1-3]|f[1-4]|a[1-3]|m[1-3])\b", "Expositionsklasse (z. B. XC1) fehlt – Dauerhaftigkeit unbestimmt")],
             price={"m3": (140, 480)}, norm="DIN 18331"),
    WorkType("oberboden", "Oberboden abtragen", r"oberboden|mutterboden",
             ("area", "volume"),
             params=[("Homogenbereich", r"homogenbereich", "Homogenbereich nach DIN 18300/18320 fehlt")],
             price={"m2": (2, 9), "m3": (5, 30)}, norm="DIN 18300"),
    WorkType("aushub", "Aushub / Bodenabtrag", r"aushub|ausheben|baugrube|bodenabtrag|graben",
             ("volume",),
             params=[("Homogenbereich", r"homogenbereich", "Homogenbereich nach DIN 18300 fehlt – Baugrundrisiko liegt unklar verteilt")],
             price={"m3": (6, 35)}, norm="DIN 18300"),
    WorkType("entsorgung", "Entsorgung / Abfuhr", r"entsorg|abfahren|abfuhr|abtransport|deponie",
             ("volume", "mass"), price={"m3": (12, 70), "t": (8, 60)}, norm="DIN 18300"),
    WorkType("verfuellen", "Verfüllung", r"verf[üu]ll",
             ("volume",), price={"m3": (12, 55)}, norm="DIN 18300"),
    WorkType("tragschicht", "Frostschutz- / Tragschicht", r"frostschutz|schotter|tragschicht",
             ("volume", "area"), price={"m3": (25, 75), "m2": (5, 25)}, norm="DIN 18300"),
    WorkType("wasserhaltung", "Wasserhaltung", r"wasserhaltung|pumpe",
             ("time", "lump", "count"), measurable=False, norm="DIN 18305"),
    WorkType("mauerwerk", "Mauerwerk", r"mauerwerk|mauern|kalksandstein|porenbeton|ziegel",
             ("area", "volume"),
             params=[("Wanddicke", r"d\s?=\s?\d|\d{2}[,.]?\d?\s?cm", "Wanddicke fehlt")],
             price={"m2": (30, 140), "m3": (180, 520)}, norm="DIN 18330"),
    WorkType("sturz", "Sturz", r"sturz|st[üu]rze",
             ("count", "length"), price={"St": (25, 250), "m": (20, 160)}, norm="DIN 18330"),
    WorkType("abdichtung", "Abdichtung", r"abdichtung|sperrbahn|dickbeschichtung",
             ("area", "length"),
             params=[("Wassereinwirkungsklasse", r"w\s?\d(\.\d)?\s?-\s?e|din\s?18533|din\s?18531|din\s?18532|din\s?18534|din\s?18535|mauersperrbahn|querschnitt",
                      "Wassereinwirkungsklasse / Norm (DIN 18533) fehlt")],
             price={"m2": (15, 85), "m": (3, 25)}, norm="DIN 18336"),
    WorkType("daemmung", "Dämmung", r"d[äa]mmung|d[äa]mmplatte|xps|eps",
             ("area",),
             params=[("Dämmdicke", r"d\s?=\s?\d|\d{2,3}\s?mm", "Dämmdicke fehlt"),
                     ("Wärmeleitfähigkeit", r"wls|wlg|λ|lambda|0[,.]0\d{2}", "Wärmeleitstufe (WLS) fehlt – GEG-Nachweis gefährdet")],
             price={"m2": (15, 90)}, norm="DIN 18336"),
    WorkType("drainage", "Drainage / Rohrleitung", r"drain|rohr|leitung",
             ("length",), params=[("Nennweite", r"dn\s?\d+", "Nennweite (DN) fehlt")],
             price={"m": (12, 120)}, norm="DIN 18308"),
    WorkType("geruest", "Gerüst", r"ger[üu]st",
             ("area", "area_time", "lump"),
             params=[("Lastklasse", r"lastklasse|lk\s?\d|gebrauchs[üu]berlassung", "Lastklasse fehlt"),
                     ("Standzeit", r"standzeit|woche|gebrauchs[üu]berlassung", "Standzeit fehlt – Vorhaltekosten offen")],
             price={"m2": (5, 22), "m2Wo": (0.2, 1.2)}, norm="DIN 18451"),
]


# Match order matters: specific types before generic ones ("Porenbeton-Mauerwerk" is masonry,
# "Schalung Stahlbetonwand" is formwork, "Aushub entsorgen" is disposal).
_ORDER = ["be", "schalung", "betonstahl", "sauberkeit", "fertigteil", "abdichtung", "daemmung", "sturz",
          "mauerwerk", "geruest", "drainage", "beton", "entsorgung", "oberboden", "aushub", "verfuellen", "tragschicht", "wasserhaltung"]
WORK_TYPES.sort(key=lambda w: _ORDER.index(w.key) if w.key in _ORDER else 99)
WT_BY_KEY = {w.key: w for w in WORK_TYPES}


def classify(short_text: str, long_text: str = "") -> WorkType | None:
    for t in (short_text.lower(), f"{short_text} {long_text}".lower()):
        for wt in WORK_TYPES:
            if re.search(wt.match, t):
                return wt
    return None


# ------------------------------------------------------------------ vague wording
VAGUE_PATTERNS: list[tuple[str, str, str]] = [
    (r"\bca\.(?=\s|\d)", "„ca.“", "Unbestimmte Angabe – Maß/Menge nicht eindeutig, Streit über Abrechnung programmiert"),
    (r"nach erfordernis", "„nach Erfordernis“", "Leistungsumfang offen – wer entscheidet über das Erfordernis?"),
    (r"nach bedarf", "„nach Bedarf“", "Leistungsumfang offen"),
    (r"nach wahl des (an|auftragnehmers)", "„nach Wahl des AN“", "Ausführung unbestimmt – Qualitätsrisiko für den AG"),
    (r"nach (angabe|anweisung|vorgabe) (der |des )?(bl|bauleitung|ag|auftraggebers|architekten)", "„nach Angabe der Bauleitung“",
     "Leistung erst später festgelegt → geänderte Leistung nach VOB/B § 2 Abs. 5 wahrscheinlich"),
    (r"o\.\s?ä\.|oder ähnlich", "„o. ä.“", "Unklarer Gleichwertigkeitsmaßstab – besser Leitfabrikat + Kriterien für Gleichwertigkeit"),
    (r"\bevtl\.|\beventuell\b", "„evtl.“", "Unklar, ob Leistung geschuldet ist – ggf. als Bedarfsposition ausschreiben"),
    (r"\bggf\.|gegebenenfalls", "„ggf.“", "Unklar, ob Leistung geschuldet ist – ggf. als Bedarfsposition ausschreiben"),
    (r"nach aufwand", "„nach Aufwand“", "Kein Einheitspreis-Charakter – Kostenkontrolle unmöglich"),
    (r"aller? (erforderlichen|notwendigen) (leistungen|nebenleistungen|arbeiten)|komplett(e)? (herstellen|leistung)|schlüsselfertig",
     "Komplettheitsklausel", "Pauschale Vollständigkeitsklauseln sind in AGB des AG häufig unwirksam (§ 307 BGB) – Lücken werden zu Nachträgen"),
    (r"\bw\.\s?v\.|wie vor\b", "„wie vor“", "Verweis auf andere Position – bei Änderungen inkonsistent"),
]

# ------------------------------------------------------------------ outdated standards
OUTDATED_PATTERNS: list[tuple[str, str, str, str]] = [
    (r"bodenklasse", "Bodenklassen statt Homogenbereiche",
     "Seit VOB/C 2016 beschreibt DIN 18300 Boden über Homogenbereiche; Bodenklassen sind keine vertragliche Grundlage mehr – Baugrundrisiko unklar",
     "VOB/C DIN 18300 (Ausgabe 2015/2016+)"),
    (r"din\s?18195", "DIN 18195 (zurückgezogen)",
     "Abdichtungen werden seit 2017 nach DIN 18531–18535 (erdberührt: DIN 18533) beschrieben",
     "DIN 18533"),
    (r"din\s?4108-?2?\s?:?\s?(19|200[0-9])", "veralteter Wärmeschutz-Normstand", "Norm-Ausgabe prüfen", "DIN 4108"),
]

# ------------------------------------------------------------------ companion rules
# (trigger regex on items, required companion regex, label, exposure estimator key)
MEMBERS = {
    "Fundament": r"fundament",
    "Bodenplatte": r"bodenplatte",
    "Wand": r"w[äa]nd",
    "Decke": r"decke",
    "Stütze": r"st[üu]tze",
    "Unterzug": r"unterz[üu]g|balken",
}
# m² formwork per m³ concrete (rough, for exposure estimate only)
FORMWORK_RATIO = {"Fundament": 2.5, "Bodenplatte": 0.8, "Wand": 8.0, "Decke": 5.0, "Stütze": 13.0, "Unterzug": 9.0}
REF_FORMWORK_EUR_M2 = 38.0
REF_REBAR_T_PER_M3 = 0.10
REF_REBAR_EUR_T = 1600.0
REF_DISPOSAL_EUR_M3 = 28.0
REF_SCAFFOLD_EUR_M2 = 10.0
REF_BE_SHARE = 0.03
REF_WATERPROOF_EUR_M2 = 35.0
