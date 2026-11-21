"""Team rules written in plain language, e.g.
    "for client 2, 10% higher prices are normal"
    "vague wording is fine for public clients"
    "contract clauses are always high for private clients"

A sentence becomes a visible structured rule (scope + action), is previewed against the current BoQ,
and only then saved (data/rules.json, NR_RULES to share). Parsing: Claude if an API key is set, otherwise a
small built-in parser for common phrasings; the dashboard form lets the user correct either result.

Rule = {"id", "text", "scope": {"client", "trade", "public"}, "action": "suppress"|"severity"|"price_tolerance",
        "rules": [rule ids], "severity": "high|medium|low", "pct": float, "created_by", "created_at"}
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import uuid
from pathlib import Path

from .model import BoQ, Flag

RULES_PATH = Path(os.environ.get("NR_RULES") or Path(__file__).resolve().parent.parent / "data" / "rules.json")

# finding families users talk about -> rule ids
FAMILIES = {
    "price": (["R24", "R05", "R25"], r"price|preis|ep\b|einheitspreis|teuer|günstig|cheap|expensive"),
    "vague": (["R08"], r"vague|unklar|unbestimmt|ca\.|ungenau|wording|formulierung"),
    "unit": (["R02", "R22"], r"unit|einheit"),
    "duplicate": (["R04"], r"duplicate|doppel"),
    "longtext": (["R12"], r"long\s*text|langtext"),
    "details": (["R09"], r"detail|pflichtangabe|parameter|angabe"),
    "clauses": (["R20"], r"clause|klausel|vertrag|contract"),
    "missing": (["R10"], r"missing item|fehlende position|completeness|vollständig|formwork|schalung|gerüst|scaffold"),
    "norms": (["R11"], r"norm|standard|din\b"),
}
FAMILY_LABEL = {"price": ("Preisprüfungen", "price checks"), "vague": ("unbestimmte Formulierungen", "vague wording"),
                "unit": ("Einheiten", "units"), "duplicate": ("Doppelpositionen", "duplicates"),
                "longtext": ("Langtexte", "long texts"), "details": ("Pflichtangaben", "mandatory details"),
                "clauses": ("Vertragsklauseln", "contract clauses"), "missing": ("fehlende Positionen", "missing items"),
                "norms": ("Normbezüge", "standards")}


def parse_simple(text: str) -> dict:
    """Built-in parser for typical sentences (German or English). Returns a rule draft; the form can correct it."""
    t = text.lower()
    scope = {"client": None, "trade": None, "public": None}
    # one word ("client 2", "Kunde Müller") or a quoted multi-word name ("client 'Bau Müller GmbH'")
    m = re.search(r"(?:client|kunde|kunden|auftraggeber|ag)\s+(?:[\"„']([^\"“']+)[\"“']|([\w\-.]+))", t)
    if m:
        scope["client"] = (m.group(1) or m.group(2)).strip(" .,")
    if re.search(r"public|öffentlich", t):
        scope["public"] = True
    elif re.search(r"private|privat", t):
        scope["public"] = False
    m = re.search(r"(?:trade|gewerk|section|titel)\s+[\"„']?([\w\-. ]+?)[\"“']?(?:[,:;]|\s|$)", t)
    if m:
        scope["trade"] = m.group(1).strip()
    fams = [k for k, (_, rx) in FAMILIES.items() if re.search(rx, t)]
    rules = sorted({r for k in fams for r in FAMILIES[k][0]})
    pct = None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:%|prozent|percent)", t)
    if m:
        pct = float(m.group(1).replace(",", "."))
    if pct is not None and "price" in fams:
        action, sev = "price_tolerance", None
    elif re.search(r"always high|immer hoch|important|wichtig|critical|kritisch", t):
        action, sev = "severity", "high"
    elif re.search(r"\blow\b|niedrig|unwichtig|minor|gering", t):
        action, sev = "severity", "low"
    else:
        action, sev = "suppress", None              # "is normal / fine / ok / ignore / kein Problem"
    return {"id": uuid.uuid4().hex[:8], "text": text.strip(), "scope": scope, "action": action,
            "rules": rules, "severity": sev, "pct": pct}


def parse_with_claude(text: str, client=None, model: str | None = None) -> dict:
    """Claude turns the sentence into the same structure (used when ANTHROPIC_API_KEY is set)."""
    from .llm_checks import DEFAULT_MODEL, _client
    client = client or _client()
    tool = {"name": "make_rule", "description": "Structured review rule for a BoQ checker.",
            "input_schema": {"type": "object", "properties": {
                "client": {"type": ["string", "null"]}, "trade": {"type": ["string", "null"]},
                "public": {"type": ["boolean", "null"]},
                "action": {"type": "string", "enum": ["suppress", "severity", "price_tolerance"]},
                "families": {"type": "array", "items": {"type": "string", "enum": list(FAMILIES)}},
                "severity": {"type": ["string", "null"], "enum": ["high", "medium", "low", None]},
                "pct": {"type": ["number", "null"]}}, "required": ["action", "families"]}}
    resp = client.messages.create(
        model=model or DEFAULT_MODEL, max_tokens=500, tools=[tool], tool_choice={"type": "tool", "name": "make_rule"},
        system="Convert the user's sentence into a review rule. Families: " + ", ".join(
            f"{k} ({FAMILY_LABEL[k][1]})" for k in FAMILIES) + ". Only use scope fields the sentence mentions.",
        messages=[{"role": "user", "content": text}])
    d = next(b.input for b in resp.content if getattr(b, "type", "") == "tool_use")
    return {"id": uuid.uuid4().hex[:8], "text": text.strip(),
            "scope": {"client": d.get("client"), "trade": d.get("trade"), "public": d.get("public")},
            "action": d["action"], "rules": sorted({r for k in d.get("families", []) for r in FAMILIES.get(k, ([], ""))[0]}),
            "severity": d.get("severity"), "pct": d.get("pct")}


def parse(text: str, client=None) -> tuple[dict, str]:
    if client is not None or os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return parse_with_claude(text, client=client), "claude"
        except Exception:
            pass
    return parse_simple(text), "builtin"


def describe(rule: dict, lang: str = "de") -> str:
    sc = rule.get("scope", {})
    parts = []
    if sc.get("client"):
        parts.append(("AG = " if lang == "de" else "client = ") + sc["client"])
    if sc.get("trade"):
        parts.append(("Gewerk enthält " if lang == "de" else "trade contains ") + sc["trade"])
    if sc.get("public") is not None:
        parts.append(("öffentlich" if sc["public"] else "privat") if lang == "de" else ("public" if sc["public"] else "private"))
    fams = [k for k, (ids, _) in FAMILIES.items() if set(ids) & set(rule.get("rules", []))]
    checks = ", ".join(FAMILY_LABEL[k][0 if lang == "de" else 1] for k in fams) or ", ".join(rule.get("rules", [])) or "–"
    act = rule.get("action")
    if act == "suppress":
        a = "ausblenden" if lang == "de" else "hide"
    elif act == "severity":
        a = ("Schwere → " if lang == "de" else "severity → ") + str(rule.get("severity"))
    else:
        a = (f"Toleranz +{rule.get('pct') or 0:g} %" if lang == "de" else f"tolerance +{rule.get('pct') or 0:g}%")
    scope_txt = " · ".join(parts) or ("alle Projekte" if lang == "de" else "all projects")
    return (f"Geltung: {scope_txt} · Prüfungen: {checks} · Aktion: {a}" if lang == "de"
            else f"scope: {scope_txt} · checks: {checks} · action: {a}")


def _in_scope(rule: dict, f: Flag, boq: BoQ, meta: dict) -> bool:
    sc = rule.get("scope", {})
    client = (meta.get("client") or boq.client or "").lower()
    if sc.get("client") and sc["client"].lower() not in client:
        return False
    if sc.get("public") is not None and meta.get("public") is not None and bool(meta["public"]) != bool(sc["public"]):
        return False
    if sc.get("trade"):
        it = boq.by_oz().get(f.oz) if f.oz else None
        if not it or sc["trade"].lower() not in (it.section or "").lower():
            return False
    return not rule.get("rules") or f.rule_id in rule["rules"]


def _price_ratio(f: Flag) -> float | None:
    m = re.search(r"Faktor (\d+(?:[.,]\d+)?)", f.message)
    return float(m.group(1).replace(",", ".")) if m else None


def apply_rules(flags: list[Flag], boq: BoQ, rules: list[dict], meta: dict | None = None, preview: bool = False) -> list[tuple]:
    """Apply rules (or only compute what they would change, preview=True). Returns [(flag, effect_de, effect_en)]."""
    meta = meta or {}
    changes = []
    for f in flags:
        for r in rules:
            if not _in_scope(r, f, boq, meta):
                continue
            act = r.get("action")
            if act == "suppress":
                eff = ("ausgeblendet", "hidden")
                if not preview:
                    f.decision = {"status": "dismissed", "by": "Regel", "at": "", "source": "rule",
                                  "reason": f"Regel: „{r['text']}“"}
            elif act == "severity" and r.get("severity") and r["severity"] != f.severity:
                eff = (f"Schwere {f.severity} → {r['severity']}", f"severity {f.severity} → {r['severity']}")
                if not preview:
                    f.severity = r["severity"]
            elif act == "price_tolerance" and f.rule_id in ("R24", "R05"):
                ratio = _price_ratio(f)
                tol = 1 + (r.get("pct") or 0) / 100
                if ratio is None or not ("über" in f.title or "hoch" in f.title) or ratio > 3 * tol:
                    continue
                eff = ("innerhalb der Toleranz – ausgeblendet", "within tolerance – hidden")
                if not preview:
                    f.decision = {"status": "dismissed", "by": "Regel", "at": "", "source": "rule",
                                  "reason": f"Regel: „{r['text']}“"}
            else:
                continue
            f.learned = f.learned or {}
            if not preview:
                f.learned = {"de": f"Regel „{r['text']}“: {eff[0]}", "en": f"Rule '{r['text']}': {eff[1]}"}
            changes.append((f, eff[0], eff[1]))
            break
    return changes


def load_rules(path: Path = RULES_PATH) -> list[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []


def save_rule(rule: dict, by: str = "", path: Path = RULES_PATH) -> None:
    rules = [r for r in load_rules(path) if r.get("id") != rule.get("id")]
    rule = {**rule, "created_by": by, "created_at": _dt.datetime.now().isoformat(timespec="seconds")}
    rules.append(rule)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_rule(rule_id: str, path: Path = RULES_PATH) -> None:
    rules = [r for r in load_rules(path) if r.get("id") != rule_id]
    path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
