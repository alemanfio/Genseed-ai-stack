# GenSeed AI Investing Stack

An AI-native **sourcing + diligence** pipeline built to give a single-partner ELTIF 2.0 fund the reach of a research team — across two thesis areas, longevity science and the space economy.

It is two components wired into one workflow:

```
        ┌─────────────────────┐        ┌──────────────────────┐
        │  Deal Sourcing      │        │  Due Diligence       │
        │  Engine             │──────▶ │  Assistant           │
        │  (find + qualify)   │  CRM   │  (research + memo)    │
        └─────────────────────┘        └──────────────────────┘
         9 public data sources          multi-source collection
         → ELTIF pre-screen             → structured AI analysis
         → AI scoring                   → PDF investment memo
         → push to Attio CRM
```

The design goal throughout: **spend machine time and API budget only where a human partner's judgment actually adds value**, and encode the fund's regulatory constraints so nothing ineligible ever reaches the human.

---

## Why this exists

A small fund lives or dies on coverage and speed: seeing enough of the right companies, and forming a view faster than the next fund. A solo or lean team can't manually watch nine data sources across two sectors, so this stack does the mechanical 80% — discovery, eligibility filtering, first-pass scoring, memo drafting — and hands the partner a shortlist that is already regulation-compliant and pre-analyzed. It is leverage, not autopilot: every gate is tuned to surface decisions, not to make them.

---

## Component 1 — Deal Sourcing Engine

Finds early-stage private companies in longevity and space, qualifies them against ELTIF 2.0 rules, scores them with Claude, and pushes only compliant high-scorers into the CRM.

**The nine sources, and why each was chosen.** Every source is picked because it surfaces *private, early-stage* companies rather than noise:
- **OpenAlex /institutions** — research-active companies, filtered server-side to `type:company`.
- **NIH RePORTER (SBIR/STTR)** — filtered to R41/R42/R43/R44 award codes, which by law go only to small businesses — so the org names are real private biotech companies.
- **CORDIS** — EU Horizon SME participants.
- **ClinicalTrials.gov** — industry sponsors only.
- **AgingBiotech.info** — a curated longevity company database.
- **Y Combinator (yc-oss), GitHub, HackerNews, bioRxiv** — early signal on teams and traction.

**ELTIF pre-screen as a cost gate — the core design decision.** Before paying for any AI scoring, every candidate passes a cheap, deterministic eligibility check encoding EU Reg 2023/606: the target must be unlisted or ≤ €1.5B market cap, domiciled in the EU or a safe third country, and not a financial undertaking (except fintechs under five years old). Candidates in FATF high-risk or EU tax-blacklist jurisdictions are hard-rejected. This means AI budget is spent only on companies that could actually be invested in — regulatory knowledge used as an efficiency lever, not just a compliance footnote.

**Scoring and CRM push.** Survivors are scored by Claude against the fund mandate and source-quality priors. Only candidates that clear the score threshold **and** are flagged ELTIF-compliant are pushed to Attio, tagged with a compliance-confidence level (HIGH / MEDIUM / LOW). Everything is de-duplicated across sources and logged with per-source statistics for observability.

---

## Component 2 — Due Diligence Assistant

Takes a single company and produces a structured, partner-style due-diligence memo as a formatted PDF.

**Data collection.** Pulls from the company website, OpenAlex publications, and GitHub presence, with patent and news modules stubbed for a later pass (see Roadmap).

**AI analysis.** A single system prompt fixes the analyst's frame — a senior VC at an ELTIF fund reasoning over a 10+ year horizon and an illiquid profile — and Claude then scores four dimensions independently: team, technology, market, and risk. Scores roll up into an overall rating and a clear verdict: **INVEST / DEEP_DIVE / PASS**.

**Output.** A cover page, an executive-summary scorecard, per-section assessments, and a recommendation, rendered to a clean PDF with ReportLab — the kind of artifact that goes straight into an IC folder.

*Also packaged as a deployed API (Railway + Make.com) so the same logic can run as an automation, not only from the command line.*

---

## Design principles (what to look at)

- **Cost-aware:** deterministic filters run before any paid AI call; the ELTIF pre-screen exists specifically to avoid scoring ineligible targets.
- **ELTIF-native:** the fund's regulatory reality is encoded in code, not left to the human to remember on every candidate.
- **Evidence-based:** the AI is instructed to cite the data it was given and flag what's missing, not to invent.
- **Human-in-the-loop:** thresholds and compliance gates decide what a human *sees*, never what a human decides.
- **Extensible:** sources and analysis modules are independent functions/classes, so a new data source or a new scoring dimension is an additive change.

---

## Tech stack

Python · `requests` · Anthropic SDK (Claude) · ReportLab (PDF) · Attio (CRM) · Railway + Make.com (deployment of the DD service).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your own keys — never commit .env
```

Required environment variables (see `.env.example`):

```
ANTHROPIC_API_KEY=      # Claude API
ATTIO_TOKEN=            # Attio CRM (sourcing engine only)
ATTIO_LIST_ID=          # target Attio list (sourcing engine only)
```

## Usage

```bash
# Sourcing engine — runs the full pipeline across both sectors
python genseed_sourcing.py

# DD assistant — one company at a time
python dd_assistant.py --company "Example Bio" --website "https://example.com" --sector Longevity
```

---

## Status & roadmap

This is working software used in a live fund workflow, not a finished product. Known and intentional gaps:
- Patent and news collection in the DD assistant are stubbed and flagged as pending.
- Scoring prompts and thresholds are tuned by hand and evolve with use.
- Next: patent/news integration, richer source priors, and back-testing scores against realized outcomes.

## How this was built

Designed and built by directing **Claude Code** — the judgment on show here is in the *architecture*: which sources are worth querying, how to encode ELTIF eligibility as a cost gate, where the human stays in the loop. The AI wrote code to a spec; the spec is the taste.

---

*Built for GenSeed Capital. Sectors: longevity science, space economy. Structure: ELTIF 2.0.*
