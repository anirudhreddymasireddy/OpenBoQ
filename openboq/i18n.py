"""Interface texts in German and English (report, dashboard, CLI)."""
from __future__ import annotations

LANGS = {"de": "Deutsch", "en": "English"}

UI = {
    "brand": ("LV-Prüfung", "BoQ check"),
    "tagline": ("KI-Prüfung von Leistungsverzeichnissen: Fehler, Lücken und Nachtragsrisiko in €.",
                "AI review of bills of quantities: errors, gaps and change-order exposure in €."),
    "items": ("Positionen", "items"),
    "lv_sum": ("LV-Summe", "BoQ total"),
    "analysis_in": ("Analyse in", "Analysed in"),
    "risk": ("Geschätztes Nachtragsrisiko", "Estimated change-order exposure"),
    "of_total": ("der LV-Summe", "of BoQ total"),
    "high": ("hohe Befunde", "high findings"),
    "medium": ("mittlere Befunde", "medium findings"),
    "affected": ("betroffene Positionen", "items affected"),
    "top": ("Top-Risiken", "Top risks"),
    "by_eur": ("nach € sortiert", "sorted by €"),
    "by_type": ("Risiko nach Befundart", "Exposure by finding type"),
    "ifc_title": ("Modell ↔ LV Mengenabgleich", "Model ↔ BoQ quantity check"),
    "col_group": ("Prüfgruppe", "Check group"),
    "col_elements": ("Bauteile", "Elements"),
    "col_model": ("Modell", "Model"),
    "col_lv": ("LV", "BoQ"),
    "col_unit": ("Einh.", "Unit"),
    "col_dev": ("Abw.", "Dev."),
    "col_status": ("Status", "Status"),
    "st_deviation": ("> 10 %", "> 10 %"),
    "st_missing_in_lv": ("fehlt im LV", "missing in BoQ"),
    "st_watch": ("5–10 %", "5–10 %"),
    "st_missing_in_model": ("fehlt im Modell", "missing in model"),
    "st_ok": ("ok", "ok"),
    "all": ("Alle Befunde", "All findings"),
    "in_order": ("in LV-Reihenfolge", "in BoQ order"),
    "lv_wide": ("LV-weit", "BoQ-wide"),
    "lv_wide_title": ("Vollständigkeit & Modellabgleich", "Completeness & model check"),
    "note": ("€-Werte sind transparente Schätzungen (Regel-Heuristiken, Referenzpreise, Modellmengen) zur Priorisierung – "
             "keine Rechtsberatung. Jeder Befund nennt Regel und Grundlage, damit Kalkulation und Bauleitung ihn prüfen können.",
             "€ values are transparent estimates (rule heuristics, reference prices, model quantities) for prioritisation – "
             "not legal advice. Every finding names its rule and basis so estimators and site managers can verify it."),
    "sev_high": ("Hoch", "High"),
    "sev_medium": ("Mittel", "Medium"),
    "sev_low": ("Gering", "Low"),
    "sev_info": ("Info", "Info"),
    "src_rules": ("Regel", "Rule"),
    "src_ifc": ("IFC", "IFC"),
    "src_llm": ("KI", "AI"),
    # dashboard
    "language": ("Sprache", "Language"),
    "upload_lv": ("LV (GAEB X81–X86 / D83–D86, PDF, CSV, XLSX)", "BoQ (GAEB X81–X86 / D83–D86, PDF, CSV, XLSX)"),
    "upload_ifc": ("IFC-Modell (optional)", "IFC model (optional)"),
    "load_demo": ("Demo-Daten laden", "Load demo data"),
    "demo_seed": ("Demo: Zufallsfehler (Seed)", "Demo: random errors (seed)"),
    "demo_seed_help": ("Pflanzt bekannte Fehler in ein sauberes LV.", "Plants known errors into a clean BoQ."),
    "ai_toggle": ("KI-Tiefenprüfung (Claude)", "AI deep check (Claude)"),
    "ai_needs_key": ("Benötigt ANTHROPIC_API_KEY", "Requires ANTHROPIC_API_KEY"),
    "ai_help": ("Semantische Prüfung + Management-Summary", "Semantic checks + management summary"),
    "intro": ("**Jede Position bekommt ein Nachtragsrisiko in Euro.**\n\n"
              "1. **Regelprüfung** – Rechenfehler, Einheiten, Pauschalen, Doppelpositionen, Preisausreißer, unklare Texte, "
              "fehlende Pflichtangaben, veraltete Normen, fehlende Begleitpositionen\n"
              "2. **IFC-Abgleich** – Modellmengen vs. Vordersätze, > 10 % = VOB/B § 2 Abs. 3; Bauteile ohne LV-Position = § 2 Abs. 6\n"
              "3. **KI-Tiefenprüfung** – was Regeln nicht sehen, plus Korrekturvorschläge im STLB-Bau-Stil\n\n"
              "← LV hochladen oder **Demo-Daten laden**.",
              "**Every line item gets a change-order risk in euros.**\n\n"
              "1. **Rule checks** – calculation errors, units, lump sums, duplicates, price outliers, vague wording, "
              "missing mandatory details, outdated standards, missing companion items\n"
              "2. **IFC check** – model quantities vs. BoQ quantities, > 10 % = VOB/B § 2(3); elements without a BoQ item = § 2(6)\n"
              "3. **AI deep check** – what rules cannot see, plus corrected texts in STLB-Bau style\n\n"
              "← Upload a BoQ or **load demo data**."),
    "checking": ("Prüfe LV …", "Checking BoQ …"),
    "tab_top": ("Top-Risiken", "Top risks"),
    "tab_all": ("Alle Befunde", "All findings"),
    "tab_pos": ("Positionen", "Items"),
    "tab_ifc": ("IFC-Abgleich", "IFC check"),
    "tab_eval": ("Bewertung", "Evaluation"),
    "f_severity": ("Schwere", "Severity"),
    "f_source": ("Quelle", "Source"),
    "c_oz": ("OZ", "Item"),
    "c_finding": ("Befund", "Finding"),
    "c_expl": ("Erläuterung", "Explanation"),
    "c_basis": ("Grundlage", "Basis"),
    "c_fix": ("Vorschlag", "Suggestion"),
    "c_risk": ("Risiko €", "Risk €"),
    "c_short": ("Kurztext", "Short text"),
    "c_qty": ("Menge", "Qty"),
    "c_unit": ("Einheit", "Unit"),
    "c_up": ("EP", "Unit price"),
    "c_it": ("GP", "Total"),
    "c_light": ("Ampel", "Status"),
    "c_count": ("Befunde", "Findings"),
    "pos_detail": ("Position im Detail", "Item details"),
    "fix_btn": ("✍️ Korrigierten Langtext vorschlagen (KI)", "✍️ Suggest corrected long text (AI)"),
    "fixing": ("Formuliere …", "Writing …"),
    "ifc_caption": ("> 10 % Abweichung: neuer Einheitspreis kann verlangt werden (VOB/B § 2 Abs. 3). "
                    "Bauteile ohne LV-Position: zusätzliche Leistung (VOB/B § 2 Abs. 6).",
                    "> 10 % deviation: a new unit price can be demanded (VOB/B § 2(3)). "
                    "Elements without a BoQ item: additional work (VOB/B § 2(6))."),
    "no_ifc": ("Kein IFC-Modell geladen.", "No IFC model loaded."),
    "eval_found": ("Gefundene eingepflanzte Fehler", "Planted errors found"),
    "eval_type": ("Fehlertyp", "Error type"),
    "eval_hit": ("Gefunden", "Found"),
    "eval_fp": ("Fehlalarme (hoch/mittel) außerhalb der eingepflanzten Fehler", "False alarms (high/medium) outside planted errors"),
    "eval_only_demo": ("Bewertung nur mit Demo-Daten (bekannte eingepflanzte Fehler).",
                       "Evaluation only with demo data (known planted errors)."),
    "dl_html": ("⬇️ Bericht (HTML)", "⬇️ Report (HTML)"),
    "dl_xlsx": ("⬇️ Befunde (Excel)", "⬇️ Findings (Excel)"),
    "sheet_findings": ("Befunde", "Findings"),
    "sheet_items": ("Positionen", "Items"),
    "sheet_ifc": ("IFC-Abgleich", "IFC check"),
    # cli
    "cli_risk": ("Nachtragsrisiko", "Change-order exposure"),
    "cli_findings": ("Befunde", "Findings"),
}


def T(key: str, lang: str = "de") -> str:
    de, en = UI[key]
    return en if lang == "en" else de


def sev_label(sev: str, lang: str = "de") -> str:
    return T(f"sev_{sev}", lang)


def src_label(src: str, lang: str = "de") -> str:
    return T(f"src_{src}", lang) if f"src_{src}" in UI else src
