# ATLAS — Agentic Credit Intelligence System

**A production-grade Credit Analyst Agent that turns raw financial statements into a sourced, auditable, branded credit assessment — end to end.**

> Built by **Lawrence Oladeji** — *The Agent Build for Credit Analyst*
> 📧 oladeji.lawrence@gmail.com

---

## Why this exists

Credit analysis is one of the most numerically intensive, high-stakes jobs in finance — and one of the least automated. A single annual review means:

- Spreading multiple years of P&L, balance sheet and cash-flow statements by hand
- Computing dozens of ratios and mapping them to a risk rating
- Running covenant and stress tests
- Pulling *current, sourced* industry and macro context
- Writing a memo that a credit officer can actually defend

The output has to be **exact** (a transposed cell is a bad loan) and **grounded** (an LLM hallucinating a market CAGR is a compliance incident).

This project started as my **Standard Chartered Credit Analyst simulation on Forage** — an annual credit review for a hypothetical sustainable-drinkware manufacturer. I rebuilt that exercise as a working system that does the whole thing: ingest → spread → analyse → research → benchmark → stress-test → write → brand.

It is built with two audiences in mind:

1. **As a product / agentic-development service** for consulting firms and captive credit teams who want to deploy this capability for their analysts.
2. **As a portfolio piece** demonstrating what a modern credit analyst — who also builds agentic tooling — can ship.

---

## The problem, stated precisely

| Pain point | Consequence |
|---|---|
| Manual spreading | Slow, error-prone, not auditable |
| LLMs are fluent but ungrounded | Hallucinated figures, fake market data |
| Siloed tools (Excel + Bloomberg + a Word template) | No single source of truth, no traceability |
| Research is copied from the web, unsourced | Indefensible to a credit committee |
| Memos are static documents | No reuse, no comparability across clients |

The core engineering challenge is **trust**: how do you let an LLM write the *narrative* while guaranteeing the *numbers* are correct and the *facts* are sourced?

---

## My thought process

I approached it as a **separation of concerns**, not a "prompt an LLM to do credit analysis" shortcut.

### Principle 1 — LLM for judgement, code for arithmetic
Every ratio, covenant test and stress result is computed by deterministic Python from the canonical schema. The LLM never calculates. It only *interprets* verified bundles and writes prose. This single rule is what makes the output defensible.

### Principle 2 — Ground every claim
Industry and macro claims go through a **validated research layer**: sector-templated queries → tiered source credibility → every finding must carry a URL → automatic conflict flagging. If live search isn't configured, the agent is *explicitly forbidden* from inventing metrics — it says so in the memo.

### Principle 3 — Benchmark, don't assume
The system is validated against Standard Chartered's example-answer workbook. Every computed figure is diffable against the ground truth, so "looks right" becomes "is right."

### Principle 4 — One audit trail, end to end
From a raw `.xlsx` to a branded PDF/Word report, every number carries its formula and source line items. The memo is the *last* step, not the only step.

---

## How it works — end to end

```
            ┌────────────┐
 Ingest ───▶│  Spreading │  multi-file (xlsx/pdf), multi-year, re-yeared
            └─────┬──────┘
                  ▼
            ┌────────────┐
 Extract ──▶│  Engine    │  deterministic ratios, CAM, covenants, stress
            └─────┬──────┘
                  ▼
   ┌──────────────────┬───────────────────┐
   ▼                  ▼                   ▼
┌────────┐      ┌──────────┐       ┌──────────┐
│Research│      │ Standards│       │  Agent   │  (LLM: reads verified
│(sourced)│      │benchmark │       │  (LLM)   │   bundles, writes memo)
└───┬────┘      └────┬─────┘       └────┬─────┘
    │                 │                  │
    └────────────────▶▼◀─────────────────┘
                 ┌────────────┐
   Report ──────▶│ Assemble   │  cover + synthesis + answer-to-question
                 │ + Brand    │  → branded PDF / Word / HTML
                 └────────────┘
```

### The six surfaces (single-page web app)
1. **Ingest** — drag in the workbook (or PDF); we spread and normalise it.
2. **Extract** — review the full matrix, ratios and covenant results; export CSV/JSON.
3. **Research** — live, *sourced* industry & macro dossier, with your analyst notes folded in.
4. **Standards** — define the ratio thresholds that constitute an acceptable credit; the obligor is framed against the sector norm.
5. **Report** — branded cover (analyst, client, purpose), synthesised analysis and a direct answer to the engagement question, exported as PDF or Word.
6. **Memo** — run the autonomous agent end-to-end (verified analysis + live research + recommendation).

---

## What it actually does (verified on the SC example)

For *Green Solutions Manufacturing Ltd* (the Forage case):

- Revenue **+70.7% YoY** to USD 53.8m; EBITDA **+170%** to USD 5.5m; net margin **2.7% → 10.5%**
- Leverage benign — Debt/Equity **0.22x**, Debt/EBITDA **1.24x**; all five covenants pass in the base case
- Liquidity on a **deteriorating trajectory** (current ratio 1.88x → 1.38x)
- Combined-downturn stress → rating migrates **AAA → AA** and breaches Maximum Leverage
- Recommendation: **APPROVE WITH CONDITIONS**, with explicit monitoring thresholds

Every one of those numbers is computed, not generated.

---

## Engineering highlights

- **Deterministic core** — `ratios/`, `risk/`, `analysis/` compute everything; the LLM never touches arithmetic.
- **Multi-provider LLM fallback** — Groq → NVIDIA NIM chain, so the agent keeps working if one provider is rate-limited.
- **Sourced research validity** — tiered sources, URL-required findings, conflict detection.
- **Branded, consumption-ready output** — a single block model rendered identically to PDF, Word and HTML, carrying the analyst's branding on the cover and footer.
- **Agentic UI** — the live agent runs as a background task with polling, so the browser never hangs.

### A bug worth calling out (it shows the discipline)
Early on, the **Strengths** section rendered letter-by-letter (`A A A …`). Root cause: the model returned a JSON *array as a string* (`'["AAA …"]'`), and the renderer iterated it character-by-character. Fix: coerce stringified lists back into arrays at both the tool boundary and the renderer. Small bug, but exactly the kind of failure that destroys trust in an LLM product — so it's handled defensively, not patched ad hoc.

Other hardening from real testing: vendored `marked` locally (no CDN dependency), force-revealed dynamically-shown panels, cross-page navigation, and `no-store` headers so the dev server never serves a stale page.

---

## Validation

- Benchmarked against Standard Chartered's example-answer workbook (FY2023 EBITDA margin 10.26%, current ratio 1.38x, leverage 1.24x, EBITDA cover 17.53x — all matched).
- **40 automated tests** covering ingestion, ratio engine, standards scoring and the HTTP product layer.

---

## Run it

```bash
python -m pip install -e ".[dev,web,docx,pdf]"

# optional keys (the system degrades gracefully without them)
export GROQ_API_KEY=...            # or NVIDIA_API_KEYS=key1,key2,key3
export TAVILY_API_KEY=...         # live sourced research

python -m uvicorn credit_agent.api.app:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

No keys? The deterministic engine, standards benchmarking, extraction and branded report still run fully — only the live research and LLM memo are optional.

---

## Positioning

**For a consulting firm / credit team:** this is a template for deploying agentic credit tooling — deterministic where it must be, agentic where it helps, and always auditable. It can be white-labelled per analyst and wired into your deal pipeline.

**For a hiring manager:** this is what I build as a credit analyst who also ships software — the analytical rigour of the role, expressed as a system you can run.

---

*ATLAS — Agentic Credit Intelligence System · Lawrence Oladeji · oladeji.lawrence@gmail.com*
