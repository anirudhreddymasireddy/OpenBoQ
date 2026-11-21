"""Interface texts in German and English (report, dashboard, CLI)."""
from __future__ import annotations

LANGS = {"de": "Deutsch", "en": "English"}

UI = {
    "brand": ("LV-Prüfung", "BoQ check"),
    "tagline": ("KI-Prüfung von Leistungsverzeichnissen für Bieter: Fehler, Vertragsrisiken, Nachtragschancen, Bieterfragen.",
                "AI review of bills of quantities for bidders: errors, contract risks, change-order opportunities, bidder questions."),
    "items": ("Positionen", "items"),
    "lv_sum": ("LV-Summe", "BoQ total"),
    "analysis_in": ("Analyse in", "Analysed in"),
    "risk": ("Betroffener Wert (Risiken + Chancen)", "Value at stake (risks + opportunities)"),
    "k_errors": ("Fehler", "Errors"),
    "hero_unpriced": ("Positionen mit Befund", "Items with findings"),
    "hero_unpriced_sub": ("LV ohne Preise – €-Werte erst mit Angebotspreisen", "BoQ without prices – € values need bid prices"),
    "k_risks": ("Vertragsrisiken", "Contract risks"),
    "k_opps": ("Nachtragschancen", "Change-order opportunities"),
    "k_questions": ("Bieterfragen", "Bidder questions"),
    "k_sub": ("hoch + mittel", "high + medium"),
    "questions_title": ("Bieterfragen (Entwurf)", "Bidder questions (draft)"),
    "questions_hint": ("Vor Angebotsabgabe an die Vergabestelle senden. Entwurf – bitte fachlich prüfen.",
                       "Send to the contracting authority before the bid deadline. Draft – please review."),
    "no_questions": ("Keine offenen Fragen.", "No open questions."),
    "cat_error": ("Fehler", "Error"), "cat_risk": ("Risiko", "Risk"), "cat_opportunity": ("Chance", "Opportunity"),
    "cat_security": ("Sicherheit", "Security"),
    "tab_questions": ("Bieterfragen", "Bidder questions"),
    "dl_questions": ("⬇️ Bieterfragen (Text)", "⬇️ Bidder questions (text)"),
    "demo_box": ("Demo / Testmodus", "Demo / test mode"),
    # review / learning
    "tab_review": ("Prüfen & Lernen", "Review & learn"),
    "reviewer": ("Prüfer/in", "Reviewer"),
    "project_box": ("Projektangaben", "Project details"),
    "client": ("Auftraggeber", "Client"),
    "public": ("Öffentlicher AG", "Public client"),
    "project_type": ("Projektart", "Project type"),
    "ptypes": ("Tiefbau|Hochbau|TGA|Ausbau|Sonstiges", "Civil works|Building|MEP|Fit-out|Other"),
    "c_decision": ("Entscheidung", "Decision"),
    "c_reason": ("Begründung", "Reason"),
    "c_learned": ("Gelernt", "Learned"),
    "d_confirm": ("bestätigen", "confirm"),
    "d_dismiss": ("verwerfen", "dismiss"),
    "save_decisions": ("💾 Entscheidungen speichern", "💾 Save decisions"),
    "saved_n": ("Entscheidungen gespeichert – OpenBoQ berücksichtigt sie ab jetzt.", "decisions saved – OpenBoQ uses them from now on."),
    "need_reviewer": ("Bitte zuerst Prüfer/in in der Seitenleiste eintragen.", "Please enter a reviewer name in the sidebar first."),
    "auto_dismissed": ("automatisch verworfen (früher so entschieden)", "auto-dismissed (decided like this before)"),
    "review_hint": ("Nur unpassende Befunde verwerfen (mit kurzer Begründung). Am Ende werden alle übrigen bestätigt und zu "
                    "Bieterfragen. Verworfene merkt sich OpenBoQ für ähnliche Positionen.",
                    "Dismiss only the findings that don't apply (with a short reason). At the end, everything else is confirmed and "
                    "becomes bidder questions. OpenBoQ remembers dismissals for similar items."),
    "c_dismiss": ("Verwerfen", "Dismiss"),
    "tab_rules": ("Regeln", "Rules"),
    "rules_hint": ("Regel in eigenen Worten, z. B. „für Kunde Müller sind 10 % höhere Preise normal“ oder "
                   "„unklare Formulierungen sind bei öffentlichen AG ok“. OpenBoQ zeigt die erkannte Regel und ihre Wirkung, bevor sie gespeichert wird.",
                   "A rule in your own words, e.g. 'for client Müller, 10% higher prices are normal' or "
                   "'vague wording is fine for public clients'. OpenBoQ shows the understood rule and its effect before saving."),
    "rule_input": ("Neue Regel", "New rule"),
    "rule_understand": ("Regel verstehen", "Understand rule"),
    "rule_parsed_by": ("verstanden von", "understood by"),
    "rule_adjust": ("Anpassen", "Adjust"),
    "rule_action": ("Aktion", "Action"),
    "act_suppress": ("ausblenden", "hide"), "act_severity": ("Schwere ändern", "change severity"),
    "act_price_tolerance": ("Preistoleranz", "price tolerance"),
    "rule_checks": ("Betroffene Prüfungen", "Checks affected"),
    "rule_pct": ("Toleranz %", "Tolerance %"),
    "rule_effect": ("Wirkung auf dieses LV", "Effect on this BoQ"),
    "rule_effect_n": ("Befunde würden sich ändern", "findings would change"),
    "rule_save": ("💾 Regel speichern", "💾 Save rule"),
    "rule_saved": ("Regel gespeichert.", "Rule saved."),
    "rules_active": ("Aktive Regeln", "Active rules"),
    "rule_delete": ("löschen", "delete"),
    "no_rules": ("Noch keine Regeln.", "No rules yet."),
    "any": ("beliebig", "any"),
    "outcomes_title": ("Ergebnis nach dem Projekt („Troublemaker“-Daten)", "Outcome after the project ('troublemaker' data)"),
    "outcomes_hint": ("Für bestätigte Befunde dieses Projekts festhalten, was daraus wurde. Befundarten, die oft zu Streit führen, "
                      "bekommen mehr €-Gewicht (ab 3 Ergebnissen).",
                      "Record what became of confirmed findings in this project. Finding types that often caused disputes "
                      "get more € weight (from 3 outcomes)."),
    "c_outcome": ("Ergebnis", "Outcome"),
    "o_dispute": ("🔴 Warnung – führte zu Streit/Nachtrag", "🔴 Warning – led to dispute/claim"),
    "o_clarified": ("🟡 per Bieterfrage geklärt", "🟡 Clarified by bidder question"),
    "o_no_issue": ("🟢 kein Problem", "🟢 No issue"),
    "c_type": ("Befundart", "Finding type"),
    "c_dispute_rate": ("Warnquote", "Warning rate"),
    "c_weight": ("€-Gewicht", "€ weight"),
    "save_outcomes": ("💾 Ergebnisse speichern", "💾 Save outcomes"),
    "no_confirmed_yet": ("Noch keine bestätigten Befunde für dieses Projekt.", "No confirmed findings for this project yet."),
    "dispute_table": ("Welche Befunde wirklich Geld kosten", "Which findings really cost money"),
    "login_title": ("Anmelden", "Sign in"),
    "username": ("Benutzername", "Username"),
    "password": ("Passwort", "Password"),
    "login_btn": ("Anmelden", "Sign in"),
    "login_failed": ("Benutzername oder Passwort falsch.", "Wrong username or password."),
    "logged_in_as": ("Angemeldet als", "Signed in as"),
    "logout": ("Abmelden", "Sign out"),
    "finish": ("✅ Rest bestätigen & Bieterfragen erstellen", "✅ Confirm the rest & create bidder questions"),
    "finished": ("verworfen · bestätigt", "dismissed · confirmed"),
    "memory_stats": ("Gedächtnis", "Memory"),
    "q_confirmed_only": ("Nur bestätigte Befunde", "Confirmed findings only"),
    "decided_by": ("entschieden von", "decided by"),
    "of_total": ("der LV-Summe", "of BoQ total"),
    "high": ("hohe Befunde", "high findings"),
    "medium": ("mittlere Befunde", "medium findings"),
    "affected": ("betroffene Positionen", "items affected"),
    "top": ("Top-Risiken", "Top risks"),
    "by_eur": ("nach € sortiert", "sorted by €"),
    "by_type": ("Risiko nach Befundart", "Exposure by finding type"),
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
    "src_llm": ("KI", "AI"),
    "src_prices": ("Preisdaten", "Price data"),
    "src_history": ("Projekthistorie", "Project history"),
    "c_sugg": ("Vergleichs-EP (Median)", "Comparable unit price (median)"),
    "c_sugg_n": ("Vergleiche", "Matches"),
    "sugg_line": ("Vergleichspreise früherer Projekte", "Comparable past prices"),
    # dashboard
    "language": ("Sprache", "Language"),
    "upload_lv": ("LV (GAEB X81–X86 / D83–D86, PDF, CSV, XLSX)", "BoQ (GAEB X81–X86 / D83–D86, PDF, CSV, XLSX)"),
    "load_demo": ("Demo-Daten laden", "Load demo data"),
    "demo_seed": ("Demo: Zufallsfehler (Seed)", "Demo: random errors (seed)"),
    "demo_seed_help": ("Pflanzt bekannte Fehler in ein sauberes LV.", "Plants known errors into a clean BoQ."),
    "ai_toggle": ("KI-Tiefenprüfung (Claude)", "AI deep check (Claude)"),
    "ai_needs_key": ("Benötigt ANTHROPIC_API_KEY oder OPENROUTER_API_KEY", "Requires ANTHROPIC_API_KEY or OPENROUTER_API_KEY"),
    "ai_help": ("Semantische Prüfung + Management-Summary", "Semantic checks + management summary"),
    "intro": ("**Jede Position bekommt ein Nachtragsrisiko in Euro.**\n\n"
              "1. **Regelprüfung** – Rechenfehler, Einheiten, Pauschalen, Doppelpositionen, Preisausreißer, unklare Texte, "
              "fehlende Pflichtangaben, veraltete Normen, fehlende Begleitpositionen\n"
              "2. **KI-Tiefenprüfung** – was Regeln nicht sehen, plus Korrekturvorschläge im STLB-Bau-Stil\n\n"
              "← LV hochladen oder **Demo-Daten laden**.",
              "**Every line item gets a change-order risk in euros.**\n\n"
              "1. **Rule checks** – calculation errors, units, lump sums, duplicates, price outliers, vague wording, "
              "missing mandatory details, outdated standards, missing companion items\n"
              "2. **AI deep check** – what rules cannot see, plus corrected texts in STLB-Bau style\n\n"
              "← Upload a BoQ or **load demo data**."),
    "checking": ("Prüfe LV …", "Checking BoQ …"),
    "tab_top": ("Top-Risiken", "Top risks"),
    "tab_all": ("Alle Befunde", "All findings"),
    "tab_pos": ("Positionen", "Items"),
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
    "dl_html": ("⬇️ Bericht (HTML)", "⬇️ Report (HTML)"),
    "dl_xlsx": ("⬇️ Befunde (Excel)", "⬇️ Findings (Excel)"),
    "sheet_findings": ("Befunde", "Findings"),
    "sheet_items": ("Positionen", "Items"),
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


def questions(flags, lang: str = "de", only_confirmed: bool | None = None) -> list[str]:
    """Numbered bidder questions, BoQ-wide first, then in item order, de-duplicated.
    Once any finding has been confirmed, only confirmed findings become questions (dismissed never)."""
    if only_confirmed is None:
        only_confirmed = any(f.decision.get("status") == "confirmed" for f in flags)
    seen, out = set(), []
    pool = [f for f in flags if f.decision.get("status") != "dismissed"
            and (not only_confirmed or f.decision.get("status") == "confirmed")]
    for f in sorted(pool, key=lambda f: (bool(f.oz), f.oz)):
        q = (f.question or {}).get(lang)
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def category_counts(flags) -> dict:
    c = {"error": 0, "risk": 0, "opportunity": 0, "security": 0}
    for f in flags:
        if f.severity in ("high", "medium") and f.decision.get("status") != "dismissed":
            c[f.category or "risk"] = c.get(f.category or "risk", 0) + 1
    return c


RULE_NAMES = {
    "R01": ("Rechenfehler", "Calculation error"), "R02": ("Einheit passt nicht", "Unit does not fit"),
    "R03": ("Pauschale für messbare Leistung", "Lump sum for measurable work"), "R04": ("Doppelposition", "Duplicate item"),
    "R05": ("Preis vs. Richtwert", "Price vs. reference range"), "R06": ("Menge fehlt/0", "Quantity missing/zero"),
    "R07": ("Bedarfs-/Wahlposition", "Provisional/alternative item"), "R08": ("Unbestimmte Formulierung", "Vague wording"),
    "R09": ("Pflichtangabe fehlt", "Missing technical detail"), "R10": ("Fehlende Position", "Missing item"),
    "R11": ("Veralteter Normbezug", "Outdated standard"), "R12": ("Formaler Mangel", "Formal defect"),
    "R13": ("Preis fehlt", "Price missing"), "R14": ("Mengenabweichung Modell", "Model quantity deviation"),
    "R15": ("Im Modell, nicht im LV", "In model, not in BoQ"), "R16": ("Im LV, nicht im Modell", "In BoQ, not in model"),
    "R20": ("Vertragsrisiko-Klausel", "Contract risk clause"), "R21": ("Wert nicht lesbar", "Unreadable value"),
    "R22": ("Unplausibles Format/Einheit", "Implausible format/unit"), "R23": ("Währung", "Currency"),
    "R24": ("Preis vs. frühere Projekte", "Price vs. past projects"), "R25": ("Cent-Preis", "Cent price"), "R31": ("Preis vs. gleiche Positionen", "Price vs. identical items"), "R32": ("Mengen aus Erfahrung", "Quantities from experience"), "R33": ("Nachtragsträchtig (Historie)", "Change-order-prone (history)"), "R34": ("Kosten unterschätzt (Historie)", "Costs underestimated (history)"), "R35": ("Mengen passen nicht zueinander", "Quantities do not fit together"),
    "S01": ("Versteckte KI-Anweisung", "Hidden AI instruction"), "S02": ("Unsichtbare Zeichen", "Invisible characters"),
}


def rule_name(rule_id: str, lang: str = "de") -> str:
    de, en = RULE_NAMES.get(rule_id, (rule_id, rule_id))
    return f"{en if lang == 'en' else de} ({rule_id})"
