# OpenBoQ – AI estimation & bid assistant for bills of quantities

Hackathon Challenge A "AI Estimation and Bid Assistant for Bills of Quantities" – team OpenBoQ. AI that analyses bills of quantities (Leistungsverzeichnisse),
flags faulty line items and estimates change-order (Nachtrag) exposure.

## Run it (2 minutes)

```bash
pip install -r requirements.txt
python cli.py demo                 # sample LV + planted errors + IFC model -> out/report.html, out/report.xlsx
streamlit run app.py               # dashboard: DE/EN, demo data or upload – several files at once (PDF, Word, GAEB, Excel mixed)
python cli.py analyze LV.X84 --ifc model.ifc     # sponsor files
python cli.py analyze LV.pdf --lang en           # report + findings in English (default: German)
python cli.py batch dataset --lang en   # analyse all files in one go (~40 s for the 43 dataset files)
python cli.py learn dataset        # learn unit prices from all priced files (~6 s)
python cli.py eval --runs 100      # recall / precision on planted errors
pytest -q
export ANTHROPIC_API_KEY=...       # optional: enables the Claude layer (--llm / toggle in the app)
```

## What it covers (all five challenge milestones)

| Milestone | In OpenBoQ |
| --- | --- |
| 1 Parsing | GAEB XML / GAEB 90, PDF prints, Excel/CSV/TSV, Word, text – any layout; AI reader only on weak parses, values must appear verbatim |
| 2 Error detection | 35 rules (arithmetic, units, prices, texts, typos, item numbers, totals, missing companion work) + AI judgement |
| 3 Risk & change orders | € exposure per finding; contract clauses weighted public/private; quantity cross-checks without a model; bidder questions |
| 4 Historical data | tab "History & markups": planned vs actual quantities/costs and change orders of past projects → R32–R34, markup and unit-price suggestion |
| 5 What-if | tab "What-if": 9 cost drivers, escalation clause, margin impact, quantities as in past projects, alternatives |

Test it yourself: `python tools/make_history_test.py histtest` then `python tools/score_synthetic.py histtest`
(any folder with BoQ files + `expected.json` can be scored the same way).

## Free hosting (Streamlit Community Cloud)

1. Push this repository to GitHub (public).
2. On [share.streamlit.io](https://share.streamlit.io) → "Create app" → pick the repo, branch `main`, file `app.py`,
   Python 3.12 (Advanced settings).
3. In the app's **Settings → Secrets** paste (TOML) – keys never go into the repository:

```toml
GROQ_API_KEY = "gsk_..."              # free key from console.groq.com
NVIDIA_API_KEY = "nvapi-..."          # optional backup
NR_LLM_CHAIN = "groq,nvidia"
NR_LOGIN = "name"                     # visitors enter just their name (signs their review decisions)
# or, with passwords instead: NR_APP_USERS = "team:choose-a-password; jury:another-password"
```

With `NR_LOGIN = "name"` anyone with the link gets in by typing a name; without either setting there is no login
screen at all. Either way, visitors can use your free AI quota.
The rules work without any key; the AI toggle appears once a key is set. Do not upload confidential client BoQs
to a public demo.

## AI providers (open models, no Claude credits needed)

Set one or more keys; OpenBoQ uses them in order and **switches to the next provider automatically** when one is rate
limited (`openboq/providers.py`). Batches are sized to each provider's free-tier limits.

| Provider | Key variable | Default model | Cost / limits (checked 21 Nov 2026) |
|---|---|---|---|
| **NVIDIA build** (recommended start) | `NVIDIA_API_KEY` | `mistralai/mistral-large-4-1t-a52b` (alternatives: `z-ai/glm-5.3-flash`, `google/gemma-4-31b-it`) | free, ~40 req/min, dev/evaluation use, US |
| Groq | `GROQ_API_KEY` | `openai/gpt-oss-120b` | free but only 8K tokens/min, 1K req/day → small batches |
| OVHcloud AI Endpoints (EU) | `OVH_AI_ENDPOINTS_ACCESS_TOKEN` | `gpt-oss-120b` | ~£0.07/£0.34 per 1M tokens; 2 req/min without key |
| Scaleway (EU, Paris) | `SCW_SECRET_KEY` | `gpt-oss-120b` | 1M tokens free, then ~€0.15/€0.60 per 1M |
| DeepInfra | `DEEPINFRA_API_KEY` | `Qwen/Qwen3-235B-A22B-Instruct-2507` | ~$0.09/$0.55 per 1M |
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/free` | 50 free req/day (1,000 with $10 credit) |
| Mistral (EU) | `MISTRAL_API_KEY` | `mistral-small-latest` | free plan unclear, may train on prompts |
| Gemini | `GEMINI_API_KEY` | `gemini-flash-latest` | free tier gave 429s for us |
| Local Ollama | – (`NR_LLM_CHAIN=ollama`) | `gemma4:12b` | free, slow without GPU; set `OLLAMA_CONTEXT_LENGTH=16384` |
| Claude | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` | used instead of the chain when set |

```powershell
$env:NVIDIA_API_KEY = "nvapi-..."         # free key from build.nvidia.com
$env:GROQ_API_KEY   = "gsk_..."           # optional second provider
$env:NR_LLM_CHAIN   = "nvidia,groq"       # optional order; default = every provider with a key
$env:NVIDIA_MODEL   = "openai/gpt-oss-120b"   # optional per provider: <NAME>_MODEL
python cli.py providers                   # tests each provider and lists its models
```

**Response cache** (`NR_LLM_CACHE`): `on` (default) stores every AI answer in `data/llm_cache/` – the same document never
costs a second call. Before the demo run each demo file once, then use `replay`: nothing is sent, results come from the
cache, so a dead Wi-Fi or a 429 cannot break the live demo.

Model choice (research 21 Nov 2026): `gpt-oss-120b` is hosted almost everywhere and reliable with JSON; quality options are
DeepSeek V4.1 Flash (MIT, very strong, use a non-Chinese host) and Mistral Large 4 (EU). German-specific models
(EuroLLM, Teuken) trail clearly. Use low reasoning effort for checks, none for extraction. Fine-tuning (Unsloth) is not worth
it this weekend: no labelled German BoQ dataset exists; few-shot examples (`data/examples.json`) + rules do more.
**Don't send confidential client BoQs to free tiers that may train on prompts.**

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

## Input formats (Challenge A dataset: 44 files, ~4,150 items read)

| Format | Reader | Check |
|---|---|---|
| GAEB DA XML (.X81–.X86, v3.1–3.3) | `gaeb_parser.py` | – |
| GAEB 90 fixed-width (.D83/.D84/.D86, incl. price-only bids) | `gaeb90.py` | .D83 = .X83: 159/159 items |
| PDF, Word (.docx), text – **any layout** | `smart_reader.py` picks the best of three readers | see below |
| Excel / CSV | `gaeb_parser.parse_table` | – |

**Documents with unknown layout** (`smart_reader.py`):
1. *AVA print reader* (`pdf_parser.py`) – fast and exact on GAEB-style prints (bid 274/274, quantities and prices 100 %).
2. *Layout-independent reader* (`generic_reader.py`) – ruled tables (header mapped by meaning: Pos/Menge/EP/GP,
   Item/Qty/Rate/Amount …), free text ("Menge: … EP: …"), one sentence per item ("… à 3,40 €/m = …"),
   German or English number format (detected per document). Calculation errors are never "repaired".
3. *AI reader* (only when 1 and 2 look weak and an AI provider is set): the model returns the items as JSON;
   **every number must literally appear in the document**, otherwise it is dropped (no invented prices).

Each result gets a quality score (items, texts, qty × EP = GP, printed totals, coverage of item numbers on the page);
the best one wins and the dashboard shows which reader was used.

Layout test (`python tools/layout_test.py <file>`): the errored bid re-typeset as Word table, reordered columns,
English format, free text and sentences, each also as PDF → **262/262 items identical in all 10 files, all 6 planted
errors found in every layout**. On the dataset the work also fixed real reader losses (`LV_00` 175 → 264 items,
`LV_14a/b/c` 0 → 36/60/14 items, `Abgabe LV` +2 items).

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

## Batch check in the dashboard

Upload several BoQ files at once (any mix of PDF, Word, GAEB XML/90, Excel/CSV) and optionally IFC models (matched to
BoQ files by file name; a single model is used for all). The dashboard shows one row per file – format, reader used,
items, BoQ total, high/medium findings, risk €, printed-totals check, IFC, AI status; unreadable files are listed with
their error instead of stopping the batch. Pick a file to open it in the normal detail view (review, bidder questions …),
or download all findings and bidder questions of all files as one Excel workbook.

**Same project in several files** (`crossfile.py`): files are grouped by their item numbers and quantities – not by name –
so a tender X83, a bid D84 and a bid PDF of the same job are recognised as one project. You get an extra row
"🔗 Project n" that combines them (texts from the text file, prices from the price file, preliminary notes/clauses from all,
printed totals from whichever has them) and lists every **difference between the versions** as a finding: items missing
in one file (deleted/added), changed quantity, unit price, total, unit or short text. Test: original bid D84 vs. the
errored PDF → exactly the 12 deleted items 4.1.210–4.1.320 and the changed price at 4.1.110, plus the cut short texts.
Price-only files (GAEB D84) no longer get "missing description" AI findings on every item – the AI checks their notes only.

Matching is by **content only**: item numbers, quantities and – where both files have texts – short texts. Renamed copies
with identical content are detected and checked once; files with similar names but different content stay separate; an
extract (trade package) of a larger BoQ is recognised as such, so its "missing" items are not reported.

**Project notes** (app, HTML report, Excel): concrete observations that need more than one file, each naming the files and
item numbers it rests on – e.g. "12 items are missing in errors.pdf (€18,751): 4.1.210 …", "unit price €0.50 ≠ €10.00 (4.1.110)",
"penalty clause only in errors.pdf", "4 contract clauses only in the D84 notes", "the total printed on errors.pdf equals the
items of the D84, not its own items". Computed by code from the documents – no AI needed, nothing inferred.

**Clean batch export:** a project's findings appear once (combined row); member files add only what is specific to them;
identical copies are skipped (on the test: 240 → 100 rows, nothing lost).

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

## Team findings and the client-side reviewer

**Add your own finding** (tab *Review & learn*): pick an item, write the finding, choose type and severity. OpenBoQ stores it
(`data/feedback.db`, table `manual`) and from then on reports it for the **same item text in any file or project** (rule M01,
same severity) and **suggests it for similar items** (M02, one level lower, naming the item it resembles; TF-IDF/BGE-M3 ≥ 0.6
and same unit). Team findings also become few-shot examples for the AI. They can be switched off in the "Team findings" list.

**Client reviewer (devil's advocate)** – one extra AI request when the AI is on (`NR_CHALLENGE=off` disables it): the
client's side tries to rebut the 12 strongest findings and answers per finding *holds / contestable / rebutted*, with its
likely argument. "Contestable" and "rebutted" count only with evidence that really appears in the document – an item
number or a verbatim quote, checked by code; arguments resting on things outside the documents (rounding, annexes,
later billing, discounts) are treated as "holds" (first real run: the model called everything "weak" with such guesses).
Contract clauses (R20) are never lowered by the client side. Judgment calls are adjusted (contestable: one level lower; rebutted: info); facts –
calculation errors, totals, number formats, version differences, missing/cut texts, cent prices, team findings – keep
their severity. The reviewer is an internal second check (like 2FA) – it is not shown in the app, HTML or Excel; it only
lowers a judgment call when the document itself backs the counter-argument.

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
