# ATLAS

### Agentic Credit Intelligence System

> Built by **Lawrence Oladeji**
> oladeji.lawrence@gmail.com

---

## What this is

ATLAS takes a raw financial workbook and produces a complete credit assessment —
spreading the financials, computing every ratio, running covenant and stress tests,
pulling sourced industry research, and writing a branded analyst memo.

It is not a chatbot. It is not a prompt. It is a **credit-analysis pipeline** that
happens to use an LLM — only where an LLM is useful, and never where accuracy
matters.

---

## Why not just paste the workbook into ChatGPT or Claude?

This is the first question anyone should ask.

| | ChatGPT / Claude subscription | ATLAS |
|---|---|---|
| **Ratio calculation** | The LLM estimates numbers from the text you paste. It gets some right, some wrong, and you have no way to tell which. | Every ratio, covenant test and stress result is computed by deterministic Python against the canonical schema. The LLM never touches arithmetic. |
| **Research** | Generates plausible-sounding market data. No sources. A fabricated CAGR reads identically to a real one. | Research goes through tiered sources, every claim carries a URL, and a validation confidence score (0.92 across 30 sources on the benchmark case). |
| **Reproducibility** | Same spreadsheet, different prompt, different numbers every time. | Same input always yields the same output. Every figure is diffable against a known answer. |
| **Confidentiality** | Client financials leave your environment and are processed on a third-party server. For regulated firms, this is a compliance problem. | Runs on your own infrastructure. Client data never leaves your control. (See **Data sovereignty** below.) |
| **Audit trail** | You get a memo. No provenance for any number in it. | Every computed figure carries its formula and source line items, from ingestion through to the final PDF. |
| **Output format** | Unstructured text. You reformat it yourself. | Branded PDF and Word documents with analyst name, client, purpose, synthesis and a direct answer to the engagement question. |

The core point: a subscription gives you a fluent writer that also happens to do
arithmetic — badly. ATLAS gives you a deterministic engine with a fluent writer
attached. The difference is which one you trust when a number needs to be right.

---

## Data sovereignty and privacy

Credit analysis involves material non-public financial data. Sending it to a
third-party API is not always acceptable:

- **GDPR and sectoral regulation** — financial data subject to data-residency and
  processing-origin requirements may not leave a firm's jurisdictional perimeter.
- **Client confidentiality** — borrowers and guarantors expect their financials to
  stay within the engagement team.
- **Institutional policy** — many banks and advisory firms prohibit uploading
  client documents to consumer AI services.

ATLAS is designed for this reality. The deterministic core (spreading, ratios,
covenants, stress, rating, standards) runs entirely on your own infrastructure and
requires no external API keys. The LLM and research features are optional — they
activate only when you choose to provide API keys, and they degrade gracefully
without them. You control where the code runs, where the data goes, and which
external services (if any) are called.

**Deployment options:**
- **Local** — run on your own machine with `uvicorn`.
- **Vercel** — deploy as a serverless function on your own Vercel account, with your
  own API keys, in your chosen region.
- **Internal infrastructure** — any environment that runs Python 3.11+ and can
  `pip install` the package.

The system never phones home. There is no telemetry. The code is open and
readable.

---

## How it works

```
          ┌────────────┐
Ingest ──▶│  Spreading │  multi-file (xlsx/pdf), multi-year, re-yeared
          └─────┬──────┘
                ▼
          ┌────────────┐
Extract ─▶│  Engine    │  deterministic ratios, CAM, covenants, stress
          └─────┬──────┘
                ▼
 ┌────────────────┬────────────────┐
 ▼                ▼                ▼
┌──────────┐ ┌──────────┐  ┌──────────┐
│ Research │ │Standards │  │  Agent   │  LLM reads verified
│ (sourced)│ │benchmark │  │  (LLM)   │  bundles, writes memo
└────┬─────┘ └────┬─────┘  └────┬─────┘
     └────────────▶◀────────────┘
            ┌────────────┐
Report ────▶│ Assemble   │  cover + synthesis + answer
            │ + Brand    │  → PDF / Word / HTML
            └────────────┘
```

### The six surfaces

1. **Ingest** — upload workbooks (xlsx/pdf). The system spreads and normalises
   multi-year financials into a canonical schema.
2. **Extract** — review the full matrix of line items, computed ratios, and
   covenant results. Export CSV or JSON.
3. **Research** — live, sourced industry and macro dossier. Analyst notes are
   folded in. Every finding carries a URL.
4. **Standards** — define the ratio thresholds that constitute an acceptable
   credit. The obligor is framed against the sector norm.
5. **Report** — branded cover (analyst, client, purpose), synthesised analysis,
   and a direct answer to the engagement question. Exported as PDF or Word.
6. **Memo** — run the autonomous agent end-to-end: verified analysis + sourced
   research + recommendation.

---

## What it produces (verified benchmark)

For *Green Solutions Manufacturing Ltd* (Standard Chartered Credit Analyst
simulation, Forage):

| Metric | Result |
|---|---|
| Internal rating | **AAA** (composite 4.53, implied PD 0.0005) |
| Revenue growth | **+70.7% YoY** to USD 53.8m |
| Net margin | **10.5%** (up from 2.7%) |
| Leverage | Debt/Equity **0.22x**, Debt/EBITDA **1.24x** |
| Covenants | All five pass in base case |
| Liquidity trajectory | Deteriorating (current ratio 1.88x → 1.38x) |
| Stress test (combined downturn) | **AAA → AA**, breaches Maximum Leverage |
| Recommendation | **APPROVE WITH CONDITIONS** |

Every one of those numbers is computed, not generated. The output is diffable
against Standard Chartered's example-answer workbook.

---

## Architecture principles

**LLM for judgement, code for arithmetic.** The system's credibility depends on
a single architectural decision: the LLM never calculates. It interprets
*deterministically computed* bundles and writes narrative. A ratio is either right
or wrong — a language model cannot make it right by writing about it more
eloquently.

**Every claim must be sourced.** The research layer enforces tiered source
credibility, requires a URL for every finding, and flags conflicts automatically.
If no live search is configured, the agent is forbidden from inventing metrics —
the memo states this explicitly.

**Benchmarked, not assumed.** The system is validated against Standard Chartered's
example-answer workbook. Every computed figure is diffable against ground truth.

**One audit trail, end to end.** From raw `.xlsx` to branded PDF, every number
carries its formula and source line items. The memo is the last step, not the
only step.

---

## Engineering

- **Deterministic core** — `ratios/`, `risk/`, `analysis/` compute everything.
  The LLM never touches arithmetic.
- **Multi-provider LLM fallback** — Groq and NVIDIA NIM, so the agent remains
  operational if one provider is rate-limited.
- **Sourced research** — tiered sources, URL-required findings, conflict
  detection, validation confidence scoring.
- **Branded output** — a single block model rendered identically to PDF, Word and
  HTML, carrying the analyst's branding on the cover and footer.
- **40 automated tests** — covering ingestion, ratio engine, standards scoring,
  and the HTTP product layer.

---

## Run it

```bash
python -m pip install -e ".[dev,web,docx,pdf]"

# optional — the system runs fully without them
export GROQ_API_KEY=...            # or NVIDIA_API_KEYS=key1,key2,key3
export TAVILY_API_KEY=...          # live sourced research

python -m uvicorn credit_agent.api.app:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

No API keys? The deterministic engine, standards benchmarking, extraction and
branded report still run. Only live research and the LLM memo are optional.

---

## For consulting firms

This is a template for deploying agentic credit tooling inside a captive team.
The deterministic core runs on your infrastructure. The LLM is optional and
pluggable. It can be white-labelled per analyst and wired into an existing deal
pipeline.

The value proposition is not "we replaced analysts with AI." It is "we gave
analysts a system that does the mechanical work correctly, every time, while
keeping them in control of the judgement."

---

## For hiring managers

This is what I build as a credit analyst who also ships software — the analytical
rigour of the role, expressed as a system you can run. The Standard Chartered
Forage simulation provided the benchmark; the engineering makes it repeatable.

---

*ATLAS — Agentic Credit Intelligence System*
*Lawrence Oladeji · oladeji.lawrence@gmail.com*
