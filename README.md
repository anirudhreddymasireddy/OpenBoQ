# OpenBoQ – AI estimation & bid assistant for bills of quantities

Challenge 01 "Beyond the Line Item" – team OpenBoQ. Upload a bill of quantities (Leistungsverzeichnis) in any common
format and see, in seconds, what is wrong, what is risky and where change orders are likely – ranked in euros, from the
**bidder's** (contractor's) point of view.

## What it covers (all five challenge milestones)

| Milestone | In OpenBoQ |
| --- | --- |
| 1 Parsing | GAEB DA XML (X81–X86) and GAEB 90 (D83/D84/D86), PDF prints, Excel/CSV/TSV, Word, text – any layout. An AI reader helps only on weak parses, and every value it returns must appear verbatim in the document. |
| 2 Error detection | 35 rules: arithmetic and totals, units, prices (reference ranges, identical items, site-setup share, cent prices), short/long text contradictions, typos graded by impact, item numbers, missing companion work, outdated norms – plus AI judgement for unclear texts. |
| 3 Risk & change orders | Severity and € exposure per finding; contract clauses (penalties, no claims, ground risk, fixed price, unpaid work, one-sided orders) weighted for public vs private clients; quantities cross-checked against each other (rebar per m³, disposal vs excavation, road layers, topsoil); bidder questions drafted. |
| 4 Historical data | Tab "History & markups": planned vs actual quantities, costs and change orders of finished projects are matched to new items → quantity deviations (VOB/B § 2(3)), change-order-prone work with reasons, past cost underestimates, a markup and unit-price suggestion per item. |
| 5 What-if | Tab "What-if": 9 cost drivers per work type, scenarios and sliders, price escalation clause detected (who carries the cost), margin impact, quantities as in past projects, alternatives (concrete class, disposal class, pipe material, recycled aggregate, asphalt thickness). |

Beyond the brief: batch upload with project recognition by content (renamed copies, versions, excerpts), version
comparison and project notes, a contractor agent plus an internal client-reviewer agent, review & learn, team rules,
prompt-injection detection, German/English, HTML and Excel reports.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py               # dashboard: upload one or several files, or load demo data
python cli.py analyze LV.X84       # report + Excel in out/ (add --lang en, --llm)
python cli.py batch dataset        # every file in a folder
python cli.py demo                 # sample BoQ with planted errors -> out/report.html
pytest -q                          # 36 tests
```

AI is optional – without a key every rule check runs in full. For the AI layer put free keys into
`.streamlit/secrets.toml` (git-ignored) or the environment:

```toml
GROQ_API_KEY = "..."                       # console.groq.com
NVIDIA_API_KEY = "..."                     # build.nvidia.com, backup
NVIDIA_MODEL = "mistralai/mistral-large-4-1t-a52b"
NR_LLM_CHAIN = "groq,nvidia"
```

## How it works

1. **Read** – readers in a chain, best result wins: GAEB parser → printed-schedule reader → layout-independent reader
   (tables with header mapping, free text, one sentence per item, English numbers) → AI reader only if the others look weak.
2. **Rule checks** – deterministic, explainable, every finding cites its basis (VOB/A, VOB/B, VOB/C, DIN) and gets a € value.
3. **Contractor agent (AI)** – judges what rules cannot (is a one-word text really unclear?) and must quote the text a finding
   rests on; duplicates of rule findings are merged.
4. **Client-reviewer agent (AI)** – a devil's advocate on the strongest findings, run on a *different* model where one is
   reachable. It may only lower a finding with evidence from the document that code verifies; facts, contract clauses and
   findings based on reference data are never lowered. Its log is visible only in the app's debug view, never in exports.
5. **Learning** – reviewer decisions, team findings and team rules are applied to the next file, including similar items.
6. **History & what-if** – past projects and price scenarios turn findings into a priced bid.
7. **Report** – findings ranked by €, bidder questions, HTML and Excel (findings, items, project notes, history, what-if).

## AI providers

Free, open models; OpenBoQ switches to the next provider automatically when one is rate limited (`openboq/providers.py`),
with per-model pacing, retries and a response cache.

| Provider | Key | Default model |
| --- | --- | --- |
| Groq (fast, first) | `GROQ_API_KEY` | `openai/gpt-oss-120b`, plus Qwen and gpt-oss-20b lanes |
| NVIDIA build (backup) | `NVIDIA_API_KEY` | `mistralai/mistral-large-4-1t-a52b` |
| also supported | `OVH_AI_ENDPOINTS_ACCESS_TOKEN`, `SCW_SECRET_KEY`, `DEEPINFRA_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`, Ollama, `ANTHROPIC_API_KEY` | see `providers.py` |

`python cli.py providers` tests every configured provider. **Response cache** (`NR_LLM_CACHE`): `on` stores every answer in
`data/llm_cache/`; `replay` sends nothing and answers from the cache – for a demo that cannot break on Wi-Fi or rate limits.
Item texts are sent to a provider only when AI is switched on; do not send confidential client BoQs to free tiers.

## Free hosting (Streamlit Community Cloud)

1. Push the repository to GitHub (public).
2. [share.streamlit.io](https://share.streamlit.io) → "Create app" → this repo, branch `main`, file `app.py`, Python 3.12.
3. **Settings → Secrets** (TOML), never in the repository:

```toml
GROQ_API_KEY = "..."
NVIDIA_API_KEY = "..."
NVIDIA_MODEL = "mistralai/mistral-large-4-1t-a52b"
NR_LLM_CHAIN = "groq,nvidia"
NR_LOGIN = "name"            # visitors enter just their name; or NR_APP_USERS = "team:pw1; jury:pw2" for passwords
```

## Testing

```bash
python tools/score_synthetic.py <folder>            # score any folder of BoQ files + expected.json (answer key)
python tools/make_history_test.py histtest          # simulated history / quantity / what-if set with known answers
python tools/layout_test.py <file>                  # same BoQ in 10 layouts (Word/PDF, reordered, English, free text …)
python cli.py eval --runs 100                       # recall / precision on planted errors in the sample BoQ
```

| Test set | Result |
| --- | --- |
| Organisers' errored bid, 10 layouts | 262/262 items identical, every planted error found in each |
| Synthetic set 2 (80 planted) | 78 caught (98 %), 6 false alarms (2 of them correct) |
| Synthetic set 3 (19 planted + history + what-if) | 18 caught (95 %), no real false alarm |
| Synthetic set 1 (93 planted) | 86 caught (92 %) |
| Simulated history set | 8/8, 0 false alarms, what-if checks 5/5 |

Test data generators used by other AIs are in `tools/generators/`. Every change was also re-run on the organisers' 43 real
files to keep false alarms down.

## Project structure

```
app.py                Streamlit dashboard          cli.py   command line
openboq/
  gaeb_parser.py      GAEB DA XML + CSV/XLSX/TSV      gaeb90.py   GAEB 90 fixed-width
  pdf_parser.py       printed AVA schedules           generic_reader.py   layout-independent reader
  smart_reader.py     picks the best reader, AI reader on weak parses
  knowledge.py        work types, units, mandatory details, reference prices, clause patterns  <- tune here
  rules.py            deterministic checks + € exposure
  llm_checks.py       contractor agent, client-reviewer agent, AI reader, text fixes, summary
  providers.py        provider chain, pacing, cache
  crossfile.py        same project by content, version comparison, project notes
  history.py          past projects → R32–R34, markups        whatif.py   cost drivers, scenarios, alternatives
  feedback.py         review & learn, team findings            userrules.py   team rules
  prices.py           learned unit prices                      report.py   HTML + Excel
  pipeline.py         analyze(boq, use_llm, …)
  ui_history.py, ui_whatif.py   the two dashboard tabs      ui_theme.py   wordmark (SVG), styles
.streamlit/config.toml  theme: colours, system fonts (no downloads)
tools/                scorer, layout test, history test generator, generators/
tests/                pytest
```

## Honest notes

- The example history in the app is **simulated** (real item texts, invented actuals); real conclusions need a finished
  project's post-calculation (template in the app).
- Reference prices and the cost structures for what-if are typical values, not company figures; they are visible and editable.
- STLB-Bau is licensed: parameter checks approximate STLB completeness.
- Scanned PDFs without a text layer are not read.
- € figures prioritise the review; they are not legal advice.
