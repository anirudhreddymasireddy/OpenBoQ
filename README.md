# OpenBoQ – AI estimation & bid assistant for bills of quantities

Hackathon Challenge A "AI Estimation and Bid Assistant for Bills of Quantities" – team OpenBoQ. AI that analyses bills of quantities (Leistungsverzeichnisse),
flags faulty line items and estimates change-order (Nachtrag) exposure.

## Run it (2 minutes)

```bash
pip install -r requirements.txt
python cli.py demo                 # sample LV + planted errors + IFC model -> out/report.html, out/report.xlsx
streamlit run app.py               # dashboard: Deutsch/English switch in the sidebar, demo data or upload
python cli.py analyze LV.X84 --ifc model.ifc     # sponsor files
python cli.py analyze LV.pdf --lang en           # report + findings in English (default: German)
python cli.py batch dataset --lang en   # analyse all files in one go (~40 s for the 43 dataset files)
python cli.py learn dataset        # learn unit prices from all priced files (~6 s)
python cli.py eval --runs 100      # recall / precision on planted errors
pytest -q
export ANTHROPIC_API_KEY=...       # optional: enables the Claude layer (--llm / toggle in the app)
```

## AI stack (decided)

| Job | Model | Notes |
|---|---|---|
| Rules + IFC quantities | none – plain code | the backbone, offline, milliseconds |
| Reasoning: semantic checks, fix texts, summary | **Claude Sonnet 5.5** (`claude-sonnet-5-5`) | organisers provide Anthropic credits |
| Retrieval: pick the most similar example findings for each batch | **BGE-M3**, local | TF-IDF fallback if not installed |

Settings (environment variables):

```bash
ANTHROPIC_API_KEY=...   # required for the Claude layer
NR_MODEL=claude-sonnet-5-5   # e.g. claude-opus-5-5 for the final demo run
NR_WORKERS=6            # parallel batches – a 1,000-item LV is ~50 calls, run 6 at a time
NR_EMBED=bge-m3         # use BGE-M3 (pip install sentence-transformers; ~2 GB download on first use)
NR_EXAMPLES=data/examples.json   # few-shot examples: faulty text -> finding -> fix
```

How the Claude layer saves time and credits: the system prompt, the full LV outline and the rule findings are the
same for every batch, so they form a **cached prompt prefix** – the first batch writes it, the parallel batches read it.
Each batch gets only its 20 items plus the 1–4 most similar examples from `data/examples.json`.
**Replace those 6 seed examples with the organisers' real faulty items as soon as you have them** – that's the cheapest
way to make the AI think like their estimators, no fine-tuning needed.

## Input formats (checked on the Challenge A dataset: 43 files, ~3,800 items)

| Format | Reader | Check against GAEB version of the same LV |
|---|---|---|
| GAEB DA XML (.X81–.X86, v3.1–3.3) | `gaeb_parser.py` | – |
| GAEB 90 fixed-width (.D83/.D84/.D86, incl. price-only bids) | `gaeb90.py` | .D83 = .X83: 159/159 items, same quantities |
| PDF (AVA print-outs, tenders, bids; fast pypdfium2 engine with automatic pdfplumber fallback) | `pdf_parser.py` | bid 274/274 (quantities + prices 100 %), tender 242/249, print-out 48/50 |
| Excel / CSV | `gaeb_parser.parse_table` | – |

Known gaps: `LV_14a/b/c` PDFs (different layout, 0 items yet); rule thresholds still produce many false positives
on real data (units, mandatory parameters) → tune `knowledge.py` next.

## Who it is for: the bidder (contractor)

OpenBoQ reads a tender BoQ the way an experienced estimator and claims manager would and returns four things:

| Output | Examples |
|---|---|
| **Errors** | calculation errors, wrong/unknown units, unreadable numbers, fractional counts, duplicates, currency, missing items |
| **Contract risks to price in** | result obligations ("so …, dass"), "nicht gesondert vergütet / einzurechnen", risk shifts ("zu Lasten des AN"), claim exclusions, price locks, one-sided orders, penalties, ground risk – found in item texts **and preliminary notes**; weighted for public (VOB/A § 7) vs. private clients (§ 307 BGB) |
| **Change-order opportunities** | vague scope, missing companion work (formwork, rebar, disposal, scaffold, waterproofing) |
| **Bidder questions** | a numbered draft letter of clarification questions (DE/EN), one per finding that needs clarifying |

Security: hidden instructions aimed at AI tools and invisible characters are flagged; the GAEB XML reader blocks external entities (XXE).

Dataset run (43 files, 3,800 items): high/medium findings went from ~40,000 (first, untuned run) to ~750 after tuning on real data.
**Prices.** Two checks:
- *Cent prices* (no history needed): unit prices below any realistic cost, e.g. €1.13/h excavator, €0.10/t landfill, €0.95/t binder –
  29 hits in the sample bid `Angebot AN24-0305` (decimal typo or speculative pricing).
- *Learned prices*: `python cli.py learn dataset` builds `data/price_db.json` (git-ignored) from all priced files; each item is compared
  with comparable items from **other projects** (same unit, text similarity). Honest cross-project check on the dataset: only 3 priced
  projects, only ~2 % of items find a comparable item and the error estimate is too unstable to mean anything. The mechanism needs a
  contractor's own bid archive to be useful.
The old fixed reference ranges remain as a *low* hint only.

## Human in the loop: review and learning

In the dashboard tab **Review & learn**, reviewers tick **Dismiss** (with a short reason) only for findings that do not apply; one final button confirms the rest and creates the bidder questions (name + project details in the
sidebar). Stored per decision in `data/feedback.db` (SQLite, git-ignored; `NR_FEEDBACK_DB=<path>` to share one file in a team):
flag (rule, severity, category) · item (OZ, text, unit, trade, section context) · project (client, public/private, date, type) ·
decision (confirmed/dismissed, reason, reviewer, time) · optional later outcome (dispute / clarified / no issue).

**Login:** `python cli.py adduser anirudh "Anirudh R."` creates a dashboard login (password hashed, `data/users.json`, git-ignored).
Once any user exists, the dashboard asks for sign-in and signs every decision with that name. Demo-grade – production would use
company single sign-on. For demos: `$env:NR_AUTOLOGIN = "anirudh"` (PowerShell) before `streamlit run app.py` signs that user in
automatically.

Learning is simple and visible:
1. **Memory** – the same finding on the same item text is pre-decided next time (with who/when/why); auto-dismissed findings leave
   the counts but stay viewable.
2. **Calibration** – a rule dismissed ≥ 80 % of the time (≥ 5 decisions) for a trade or client is lowered one severity level, with the reason.
3. **Safety** – contract-risk and security findings are never calibrated down.

Confirmed findings become the bidder-question list.

**Team rules in plain language** (tab *Rules*): "for client 2, 10% higher prices are normal", "vague wording is fine for public
clients", "contract clauses are always high for private clients". The sentence becomes a visible rule (scope · checks · action:
hide / change severity / price tolerance), you see its effect on the current BoQ, adjust it in a form, then save
(`data/rules.json`, `NR_RULES` to share). Parsing: Claude when `ANTHROPIC_API_KEY` is set, otherwise a built-in parser for common
German/English phrasings.

**Outcome ("troublemaker") data** (tab *Review & learn*): after the project, mark confirmed findings as 🔴 *Warning (dispute/claim)*, 🟡 *clarified by bidder
question* or 🟢 *no issue*. The € weight of a new finding is re-scaled (×0.25 … ×2 by warning rate) from what became of past findings on **similar work** – matched by
short + long text (≥ 2 similar items, same finding type preferred; BGE-M3 if enabled, otherwise TF-IDF). Without similar items it falls back
to the finding type (check ID, from 3 outcomes). A table shows which findings really cost money.

## What it does – three layers

| Layer | Finds | Basis cited in every finding |
|---|---|---|
| **1. Rules** (offline, ms) | Qty × EP ≠ GP, wrong unit for the work, lump sums hiding measurable work, duplicate items, price outliers, vague wording ("ca.", "nach Angabe der Bauleitung", completeness clauses), missing mandatory parameters (concrete class, exposure class, wall thickness, DN, WLS …), outdated norms (Bodenklassen → Homogenbereiche, DIN 18195 → DIN 18533), missing companion items (concrete without formwork/rebar, excavation without disposal, facade masonry without scaffold, basement without waterproofing, no site setup) | VOB/A § 7, § 16c, § 16d · VOB/B § 2 · VOB/C ATVs |
| **2. IFC cross-check** | Model quantities vs. LV quantities per element group; **> 10 % deviation → VOB/B § 2 Abs. 3**; elements in the model with no LV item → **additional work, § 2 Abs. 6** | IfcOpenShell, Qto_* base quantities, geometry fallback |
| **3. Claude** (optional) | Paraphrased vagueness, contradictions, untendered "Besondere Leistungen", AGB risk shifts; rewrites the faulty long text STLB-Bau style; executive summary | Structured tool output, rules' findings passed in to avoid duplicates |

Every finding: severity · rule · legal/normative basis · suggested fix · **estimated € exposure**.
Exposure heuristics are transparent and configurable (`rules.RISK`, `knowledge.REF_*`).

## Files

```
nachtragsradar/
  gaeb_parser.py   namespace-agnostic GAEB DA XML (X81–X86, v3.x) + CSV/XLSX reader
  gaeb_writer.py   GAEB 3.3 writer (sample data, corrected export)
  knowledge.py     work types, units, mandatory parameters, price ranges, vague/outdated patterns  <- tune here
  rules.py         deterministic checks + € exposure
  ifc_check.py     model ↔ LV quantity check; MAPPINGS list is plain data  <- extend here
  llm_checks.py    Claude layer (parallel batches, prompt caching, example retrieval, text fix, summary)
  embeddings.py    BGE-M3 (local) with TF-IDF fallback
  inject.py        plants 16 defect types into a clean LV, records ground truth
  evaluate.py      recall / precision
  pipeline.py      analyze(boq, ifc, use_llm)
  report.py        HTML report + Excel export
app.py             Streamlit dashboard     cli.py   command line
```

## Honest notes (say these before a judge asks)

- **Planted-error benchmark = regression harness, not real-world accuracy.** We designed both the errors and the rules,
  so 100 % there proves coverage of 16 defect classes, nothing more. The real number comes from the sponsor's files.
- **Reference prices in `knowledge.py` are placeholders.** Swap in the sponsor's historical prices before quoting any price finding.
- **STLB-Bau is licensed.** The parser detects STLB-Bau references; parameter checks approximate STLB completeness. If the sponsor
  provides STLB data, use it as the reference text for the parameter and fix-text steps.
- € figures are prioritisation estimates, not legal advice.

## Hackathon game plan

**First hour:** get the sponsor's GAEB/IFC files → `python cli.py analyze` → look at every false positive → tune `knowledge.py`
(work type regexes, price ranges) and `ifc_check.MAPPINGS` (their IFC classes, materials, quantity names).
Put their known-bad items into `data/examples.json`, then run once with `--llm` and check what Claude adds on top of the rules.
Then plant errors into *their* clean LV (`inject.py` works on any BoQ) and report recall/precision on their data.

**Build next (in this order):**
1. LLM element↔item matching for IFC elements the static mappings don't cover (R18 lists them).
2. "Apply fix" → write corrected GAEB X83/X84 back out (`gaeb_writer.py`), so it fits into iTWO/ORCA/NEVARIS.
3. Bid comparison (Preisspiegel): several X84 bids → speculative-pricing detector (low EP where model says quantity grows).
4. Click a finding → highlight the IFC elements (IfcOpenShell + a web viewer like That Open / xeokit).

**3-minute pitch:**
1. *Problem (20 s)* – thousands of items, checked by hand; one bad item becomes a change order.
2. *Live demo (90 s)* – upload the sponsor's LV + model → headline € number → top risks → one finding with its VOB clause and fix →
   IFC table: "the model has 14 m³ of beams that nobody tendered".
3. *Why trust it (30 s)* – every finding cites its rule and basis; offline rules + IFC, AI only on top; recall/precision on their data.
4. *Value (20 s)* – minutes instead of days; € exposure per project; fits GAEB workflow.
5. *Ask (20 s)* – pilot on one live tender.
