"""Optional semantic layer with Claude: catches what regexes cannot (paraphrased vagueness,
contradictions between items, untendered 'Besondere Leistungen', missing companion work),
rewrites faulty items in STLB-Bau style, and writes the executive summary.

Set ANTHROPIC_API_KEY to enable. Model can be overridden with NR_MODEL.
Everything works without it – the rules + IFC layers are fully offline.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .model import BoQ, Flag, Item

DEFAULT_MODEL = os.environ.get("NR_MODEL", "claude-sonnet-5-5")

SYSTEM = """Du bist ein erfahrener Kalkulator und Nachtragsmanager im deutschen Bauwesen (VOB/A, VOB/B, VOB/C, STLB-Bau, GAEB).
Du prüfst Leistungsverzeichnis-Positionen auf Mängel, die später zu Nachträgen, Streit oder Fehlkalkulation führen.
Prüfe insbesondere:
1. Unklare/unbestimmte Formulierungen (auch umschrieben), die gegen VOB/A § 7 Abs. 1 (eindeutig, erschöpfend) verstoßen.
2. Fehlende technische Pflichtangaben gegenüber einem vollständigen STLB-Bau-Standardtext (Material, Klasse, Maße, Norm).
3. Besondere Leistungen nach VOB/C Abschnitt 4.2 der jeweiligen ATV, die erkennbar nötig sind, aber nicht ausgeschrieben wurden
   (→ zusätzliche Leistung, VOB/B § 2 Abs. 6).
4. Widersprüche zwischen Positionen oder zwischen Kurz- und Langtext, falsche Einheiten, unplausible Mengen.
5. Risikoverlagerungen auf den Bieter, die unwirksam sein können (z. B. Komplettheitsklauseln in AGB, § 307 BGB).
Melde nur konkrete, belegbare Befunde. Keine Befunde erfinden. Wenn eine Position in Ordnung ist, melde nichts.
Nenne zu jedem Befund die Rechts-/Normgrundlage so präzise wie sicher möglich; wenn du dir bei einer Paragraphennummer
nicht sicher bist, nenne nur die Norm (z. B. "VOB/C DIN 18331").
risk_share = geschätzter Anteil des Positionswerts, der als Nachtrag/Mehrkosten droht (0.0–0.5)."""

TOOL = {
    "name": "report_findings",
    "description": "Report BoQ findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "oz": {"type": "string", "description": "Ordnungszahl, leer für LV-weite Befunde"},
                        "category": {"type": "string", "enum": ["unklar", "pflichtangabe", "besondere_leistung",
                                                                 "widerspruch", "einheit_menge", "risikoverlagerung", "sonstiges"]},
                        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                        "title": {"type": "string"},
                        "message": {"type": "string"},
                        "reference": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "risk_share": {"type": "number"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["oz", "category", "severity", "title", "message", "risk_share", "confidence"],
                },
            }
        },
        "required": ["findings"],
    },
}


def _client():
    import anthropic
    return anthropic.Anthropic(max_retries=4)


def _fmt_item(it: Item) -> str:
    q = f"{it.qty:g}" if it.qty is not None else "?"
    p = f"{it.up:,.2f} €" if it.up is not None else "-"
    tags = [t for t, on in (("Bedarfsposition", it.provisional), ("Wahlposition", it.alternative), ("Pauschal", it.lump_sum)) if on]
    return (f"OZ {it.oz} | {q} {it.unit} | EP {p} {'[' + ', '.join(tags) + ']' if tags else ''}\n"
            f"Kurztext: {it.short_text}\nLangtext: {it.long_text}")


WORKERS = int(os.environ.get("NR_WORKERS", "6"))
EXAMPLES_PATH = Path(os.environ.get("NR_EXAMPLES", Path(__file__).resolve().parent.parent / "data" / "examples.json"))


def load_examples(path: Path = EXAMPLES_PATH) -> list[dict]:
    """Few-shot examples (faulty text -> finding -> fix). Replace with the organisers' own examples."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []


def _examples_for(chunk: list[Item], examples: list[dict], k: int = 4) -> str:
    """Retrieve the most similar examples for this batch (BGE-M3 or TF-IDF fallback)."""
    if not examples:
        return ""
    from .embeddings import top_k
    hits = top_k([i.text for i in chunk], [e["text"] for e in examples], k=1)
    seen, picked = set(), []
    for row in hits:
        for idx, sim in row:
            if idx not in seen and sim > 0.15:
                seen.add(idx)
                picked.append(examples[idx])
    picked = picked[:k]
    if not picked:
        return ""
    return "\n\nBeispiele für typische Mängel (Stil und Tiefe der Befunde):\n" + "\n".join(
        f"- Text: {e['text']}\n  Befund: {e['finding']}\n  Besser: {e.get('fix', '')}" for e in picked)


def _parse(resp, oz_map) -> list[Flag]:
    flags = []
    for block in resp.content:
        if getattr(block, "type", "") != "tool_use":
            continue
        for f in block.input.get("findings", []):
            it = oz_map.get(f.get("oz", ""))
            share = max(0.0, min(0.5, float(f.get("risk_share", 0) or 0)))
            flags.append(Flag(
                rule_id="AI-" + f.get("category", "sonstiges")[:12].upper(),
                title=f.get("title", "KI-Befund"),
                severity=f.get("severity", "medium") if f.get("severity") in ("high", "medium", "low") else "medium",
                message=f.get("message", ""),
                oz=f.get("oz", "") if it else "",
                reference=f.get("reference", ""),
                exposure_eur=share * (it.total if it else 0.0),
                suggestion=f.get("suggestion", ""),
                source="llm",
                confidence=float(f.get("confidence", 0.7) or 0.7),
            ))
    return flags


def llm_item_checks(boq: BoQ, model: str = DEFAULT_MODEL, batch: int = 20, client=None,
                    known: Optional[list[Flag]] = None, workers: int = WORKERS,
                    examples: Optional[list[dict]] = None) -> list[Flag]:
    """Semantic checks, batched and parallel.

    The system prompt + LV outline + rule findings are identical for every batch, so they sit in a
    cached prefix (prompt caching): the first batch writes the cache, the rest read it.
    """
    client = client or _client()
    items = boq.items
    oz_map = boq.by_oz()
    examples = load_examples() if examples is None else examples
    known_txt = ""
    if known:
        known_txt = "\n\nBereits durch Regeln/IFC erkannt (nicht erneut melden):\n" + "\n".join(
            f"- {f.oz or 'LV'}: {f.title}" for f in known if f.severity in ("high", "medium"))
    outline = "\n".join(f"{i.oz} {i.short_text} ({i.qty:g} {i.unit})" if i.qty is not None else f"{i.oz} {i.short_text}"
                        for i in items)
    system = [
        {"type": "text", "text": SYSTEM},
        {"type": "text", "text": f"Projekt: {boq.project}\nLV: {boq.name}\n\nGliederung des gesamten LV "
                                 f"(für Vollständigkeits- und Widerspruchsprüfung):\n{outline}{known_txt}",
         "cache_control": {"type": "ephemeral"}},
    ]
    chunks = [items[s:s + batch] for s in range(0, len(items), batch)]

    def call(chunk):
        user = "Prüfe im Detail diese Positionen:\n\n" + "\n\n".join(_fmt_item(i) for i in chunk) + _examples_for(chunk, examples)
        resp = client.messages.create(
            model=model, max_tokens=4000, system=system, tools=[TOOL],
            tool_choice={"type": "tool", "name": "report_findings"},
            messages=[{"role": "user", "content": user}],
        )
        return _parse(resp, oz_map)

    if not chunks:
        return []
    flags = call(chunks[0])                       # warm the cache first
    if len(chunks) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            for res in ex.map(call, chunks[1:]):  # keeps LV order
                flags.extend(res)
    return flags


def llm_fix_text(item: Item, flags: list[Flag], model: str = DEFAULT_MODEL, client=None) -> str:
    """Rewrite an item's long text so the flagged problems are resolved (STLB-Bau style)."""
    client = client or _client()
    issues = "\n".join(f"- {f.title}: {f.message}" for f in flags) or "- keine"
    resp = client.messages.create(
        model=model, max_tokens=1200,
        system="Du formulierst LV-Langtexte im Stil von STLB-Bau: eindeutig, vollständig, VOB-konform. "
               "Ergänze fehlende Angaben als Platzhalter in eckigen Klammern [..], wenn du den Wert nicht kennst. "
               "Antworte nur mit dem neuen Langtext.",
        messages=[{"role": "user", "content": f"{_fmt_item(item)}\n\nBefunde:\n{issues}\n\nNeuer Langtext:"}],
    )
    return "".join(getattr(b, "text", "") for b in resp.content).strip()


def llm_summary(boq: BoQ, flags: list[Flag], model: str = DEFAULT_MODEL, client=None) -> str:
    client = client or _client()
    top = sorted(flags, key=lambda f: -f.exposure_eur)[:15]
    lines = "\n".join(f"- [{f.severity}] {f.oz or 'LV'} {f.title}: {f.exposure_eur:,.0f} € – {f.message[:160]}" for f in top)
    resp = client.messages.create(
        model=model, max_tokens=700,
        system="Schreibe eine prägnante Management-Zusammenfassung (max. 120 Wörter, Deutsch) für Projektleitung/Kalkulation.",
        messages=[{"role": "user", "content": f"Projekt {boq.project}, LV-Summe {boq.total:,.0f} €.\nTop-Befunde:\n{lines}"}],
    )
    return "".join(getattr(b, "text", "") for b in resp.content).strip()


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
