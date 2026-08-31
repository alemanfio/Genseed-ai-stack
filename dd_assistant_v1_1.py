#!/usr/bin/env python3
"""
DD Assistant v1.1 — GenSeed Capital
Automated Due Diligence pipeline for ELTIF 2.0 fund (Longevity + Space sectors).

v1.1 improvements over v1.0:
  - ClinicalTrials.gov API integration (free, FDA database)
  - Stage-aware technology scoring (stealth/early-stage not penalised for lacking pubs)
  - New output fields: TRL estimate, IP status, stage adjustment flag
  - Enhanced PDF executive summary with data coverage metrics

Cost estimate: ~€0.50–1.00 per report (Claude API)
"""

import os
import sys
import json
import time
import requests
import datetime
import re
from typing import Optional, Dict, List, Any
from pathlib import Path

import anthropic
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY


# ─────────────────────────────────────────────────────────────────────────────
# Data Collection
# ─────────────────────────────────────────────────────────────────────────────

class DataCollector:
    """Aggregates free-tier data from OpenAlex, ClinicalTrials, GitHub and website."""

    def __init__(self, company_name: str, website: str, sector: str):
        self.company_name = company_name
        self.website = website
        self.sector = sector
        self.headers = {"User-Agent": "GenSeedDD/1.1 (research; ale.manfio22@gmail.com)"}

    # ── OpenAlex ──────────────────────────────────────────────────────────────
    def _get_publications(self) -> List[Dict]:
        try:
            url = "https://api.openalex.org/works"
            params = {
                "search": self.company_name,
                "filter": "publication_year:>2018",
                "per-page": 20,
                "sort": "cited_by_count:desc",
                "select": "title,publication_year,cited_by_count,authorships,concepts",
            }
            r = requests.get(url, params=params, headers=self.headers, timeout=20)
            r.raise_for_status()
            results = r.json().get("results", [])
            pubs = []
            for w in results[:10]:
                authors = [
                    a.get("author", {}).get("display_name", "")
                    for a in w.get("authorships", [])[:3]
                ]
                concepts = [
                    c.get("display_name", "")
                    for c in w.get("concepts", [])[:5]
                ]
                pubs.append({
                    "title": w.get("title", ""),
                    "year": w.get("publication_year"),
                    "citations": w.get("cited_by_count", 0),
                    "authors": authors,
                    "concepts": concepts,
                })
            return pubs
        except Exception as e:
            print(f"  [OpenAlex] error: {e}")
            return []

    # ── ClinicalTrials.gov ────────────────────────────────────────────────────
    def _get_clinical_trials(self) -> List[Dict]:
        if self.sector.lower() not in ["longevity", "biotech", "healthcare", "medtech"]:
            return []
        try:
            url = "https://clinicaltrials.gov/api/v2/studies"
            params = {
                "query.term": self.company_name,
                "pageSize": 20,
                "format": "json",
            }
            r = requests.get(url, params=params, headers=self.headers, timeout=20)
            r.raise_for_status()
            studies = r.json().get("studies", [])
            trials = []
            for s in studies:
                pm = s.get("protocolSection", {})
                id_mod = pm.get("identificationModule", {})
                status_mod = pm.get("statusModule", {})
                design_mod = pm.get("designModule", {})
                enroll_mod = design_mod.get("enrollmentInfo", {})
                trials.append({
                    "nct_id": id_mod.get("nctId", ""),
                    "title": id_mod.get("briefTitle", ""),
                    "status": status_mod.get("overallStatus", ""),
                    "phase": design_mod.get("phases", [""])[0] if design_mod.get("phases") else "",
                    "start_date": status_mod.get("startDateStruct", {}).get("date", ""),
                    "enrollment": enroll_mod.get("count", 0),
                })
            return trials
        except Exception as e:
            print(f"  [ClinicalTrials] error: {e}")
            return []

    # ── GitHub ────────────────────────────────────────────────────────────────
    def _get_github_data(self) -> Dict:
        try:
            slug = re.sub(r"[^a-zA-Z0-9-]", "-", self.company_name.lower()).strip("-")
            r = requests.get(
                f"https://api.github.com/orgs/{slug}/repos",
                headers={**self.headers, "Accept": "application/vnd.github.v3+json"},
                timeout=15,
            )
            if r.status_code == 200:
                repos = r.json()
                total_stars = sum(repo.get("stargazers_count", 0) for repo in repos)
                languages = list({repo.get("language") for repo in repos if repo.get("language")})
                return {
                    "found": True,
                    "org_slug": slug,
                    "repo_count": len(repos),
                    "total_stars": total_stars,
                    "languages": languages[:8],
                    "repos": [
                        {
                            "name": repo.get("name"),
                            "stars": repo.get("stargazers_count", 0),
                            "forks": repo.get("forks_count", 0),
                            "language": repo.get("language"),
                            "updated_at": repo.get("updated_at", "")[:10],
                        }
                        for repo in sorted(repos, key=lambda x: x.get("stargazers_count", 0), reverse=True)[:5]
                    ],
                }
            return {"found": False}
        except Exception as e:
            print(f"  [GitHub] error: {e}")
            return {"found": False}

    # ── Website ───────────────────────────────────────────────────────────────
    def _scrape_website(self) -> Dict:
        try:
            r = requests.get(self.website, headers=self.headers, timeout=20)
            r.raise_for_status()
            html = r.text
            # Strip tags crudely
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            text = text[:5000]

            # Extract emails
            emails = list(set(re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", html)))
            # Extract phone-like patterns
            phones = re.findall(r"\+?[\d\s\-\(\)]{10,20}", html)[:3]

            return {
                "accessible": True,
                "text_snippet": text,
                "emails": emails[:5],
                "phones": phones,
                "status_code": r.status_code,
            }
        except Exception as e:
            print(f"  [Website] error: {e}")
            return {"accessible": False, "error": str(e)}

    # ── Main collect ──────────────────────────────────────────────────────────
    def collect(self) -> Dict:
        print(f"  Collecting data for: {self.company_name}")
        print("  → OpenAlex publications...")
        publications = self._get_publications()
        print(f"     {len(publications)} publications found")

        print("  → ClinicalTrials.gov...")
        trials = self._get_clinical_trials()
        print(f"     {len(trials)} trials found")

        print("  → GitHub...")
        github = self._get_github_data()
        print(f"     GitHub org: {github.get('found')}")

        print("  → Website scrape...")
        website = self._scrape_website()
        print(f"     Website accessible: {website.get('accessible')}")

        return {
            "company_name": self.company_name,
            "website": self.website,
            "sector": self.sector,
            "publications": publications,
            "clinical_trials": trials,
            "github": github,
            "website_data": website,
            "collected_at": datetime.datetime.utcnow().isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# AI Analysis
# ─────────────────────────────────────────────────────────────────────────────

class AIAnalyzer:
    """5-call Claude analysis pipeline with prompt caching."""

    SYSTEM_PROMPT = """You are a senior VC analyst at GenSeed Capital, an ELTIF 2.0 fund focused on \
Longevity (aging biology, longevity biotech, healthspan extension) and Space Economy (launch, \
satellites, in-space manufacturing, planetary resources) sectors.

Your analysis is rigorous, evidence-based, and VC-grade. You back every claim with data from \
the provided research. You use the following scoring scale:
  9-10: Exceptional — rare, top-1% opportunity
  7-8:  Strong — above-average, clear investment thesis
  5-6:  Average — interesting but material risks
  3-4:  Weak — fundamental issues need resolving
  1-2:  Poor — do not invest

Always format numerical scores as integers 1–10. When returning JSON, return ONLY valid JSON with no markdown fences.
"""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def _call_claude(self, prompt: str, max_tokens: int = 2000) -> str:
        response = self.client.messages.create(
            model="claude-opus-4-7",
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": self.SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    # ── Team ──────────────────────────────────────────────────────────────────
    def _analyze_team(self, data: Dict) -> Dict:
        pub_summary = json.dumps(data["publications"][:5], indent=2) if data["publications"] else "No publications found."
        website_text = data["website_data"].get("text_snippet", "")[:2000]
        prompt = f"""Analyze the founding team and leadership of {data['company_name']} ({data['sector']} sector).

WEBSITE CONTENT:
{website_text}

ACADEMIC PUBLICATIONS (first authors):
{pub_summary}

Evaluate:
1. Founder backgrounds and domain expertise
2. Track record (previous startups, exits, academic credentials)
3. Team completeness (technical, commercial, scientific)
4. Advisor quality and network

Return ONLY valid JSON (no markdown):
{{
  "score": <integer 1-10>,
  "key_people": ["<name and role>", ...],
  "strengths": ["<strength>", ...],
  "gaps": ["<gap>", ...],
  "analysis": "<2-3 paragraph assessment>"
}}"""
        raw = self._call_claude(prompt, max_tokens=1500)
        try:
            return json.loads(raw)
        except Exception:
            return {"score": 5, "key_people": [], "strengths": [], "gaps": [], "analysis": raw}

    # ── Technology ────────────────────────────────────────────────────────────
    def _analyze_technology(self, data: Dict) -> Dict:
        pub_summary = json.dumps(data["publications"][:8], indent=2) if data["publications"] else "No publications found."
        trial_summary = json.dumps(data["clinical_trials"][:5], indent=2) if data["clinical_trials"] else "No clinical trials found."
        github_summary = json.dumps(data["github"], indent=2)
        website_text = data["website_data"].get("text_snippet", "")[:2000]

        prompt = f"""Analyze the technology and IP of {data['company_name']} ({data['sector']} sector).

IMPORTANT SCORING GUIDANCE — Stage Adjustment:
- Many early-stage and stealth biotech/deeptech companies intentionally publish little or nothing
  to protect IP. Absence of publications is NOT evidence of weak technology.
- Focus on: patent filings, regulatory milestones, technical depth of website claims,
  clinical trial phases, GitHub activity, and plausibility of approach.
- Apply a "stage adjustment" if the company appears to be pre-seed/seed or stealth mode.

WEBSITE CONTENT:
{website_text}

ACADEMIC PUBLICATIONS:
{pub_summary}

CLINICAL TRIALS (ClinicalTrials.gov):
{trial_summary}

GITHUB ACTIVITY:
{github_summary}

Evaluate:
1. Technology readiness level (TRL 1-9)
2. Novelty and defensibility
3. IP position (patents, trade secrets, regulatory exclusivity)
4. Clinical/regulatory progress (if applicable)
5. Open-source activity and engineering quality

Return ONLY valid JSON (no markdown):
{{
  "score": <integer 1-10>,
  "trl": <integer 1-9>,
  "ip_status": "<brief IP/patent assessment>",
  "stage_adjusted": <true/false — true if score was adjusted upward due to stealth/early stage>,
  "clinical_stage": "<e.g. Preclinical / Phase 1 / Phase 2 / N/A>",
  "strengths": ["<strength>", ...],
  "risks": ["<risk>", ...],
  "analysis": "<2-3 paragraph assessment>"
}}"""
        raw = self._call_claude(prompt, max_tokens=1800)
        try:
            return json.loads(raw)
        except Exception:
            return {
                "score": 5, "trl": 4, "ip_status": "Unknown",
                "stage_adjusted": False, "clinical_stage": "N/A",
                "strengths": [], "risks": [], "analysis": raw,
            }

    # ── Market ────────────────────────────────────────────────────────────────
    def _analyze_market(self, data: Dict) -> Dict:
        website_text = data["website_data"].get("text_snippet", "")[:2000]
        pub_concepts = []
        for p in data["publications"][:5]:
            pub_concepts.extend(p.get("concepts", []))
        pub_concepts = list(set(pub_concepts))[:15]

        prompt = f"""Analyze the market opportunity for {data['company_name']} ({data['sector']} sector).

WEBSITE CONTENT:
{website_text}

TECHNOLOGY CONCEPTS (from publications):
{pub_concepts}

Evaluate:
1. Total addressable market (TAM) size and growth rate
2. Competitive landscape and differentiation
3. Go-to-market strategy
4. Customer traction and partnerships
5. Fit with ELTIF 2.0 / European institutional investor appetite

Return ONLY valid JSON (no markdown):
{{
  "score": <integer 1-10>,
  "tam_estimate": "<e.g. $5B by 2030>",
  "key_competitors": ["<competitor>", ...],
  "differentiation": "<main competitive advantage>",
  "strengths": ["<strength>", ...],
  "risks": ["<risk>", ...],
  "analysis": "<2-3 paragraph assessment>"
}}"""
        raw = self._call_claude(prompt, max_tokens=1500)
        try:
            return json.loads(raw)
        except Exception:
            return {
                "score": 5, "tam_estimate": "Unknown", "key_competitors": [],
                "differentiation": "", "strengths": [], "risks": [], "analysis": raw,
            }

    # ── Risks ─────────────────────────────────────────────────────────────────
    def _analyze_risks(self, data: Dict, team: Dict, tech: Dict, market: Dict) -> Dict:
        prompt = f"""Identify and assess key risks for an investment in {data['company_name']} ({data['sector']} sector).

PRIOR ANALYSIS SUMMARY:
- Team score: {team.get('score')}/10 — gaps: {team.get('gaps', [])}
- Technology score: {tech.get('score')}/10 (TRL {tech.get('trl', 'N/A')}) — risks: {tech.get('risks', [])}
- Market score: {market.get('score')}/10 — risks: {market.get('risks', [])}
- Clinical stage: {tech.get('clinical_stage', 'N/A')}

Identify the top risks across:
1. Execution risk (team, operational)
2. Technology/scientific risk
3. Regulatory/compliance risk (EMA, FDA, ESA etc.)
4. Market risk (competition, timing, adoption)
5. Financial risk (runway, funding need, dilution)

Return ONLY valid JSON (no markdown):
{{
  "overall_risk_level": "<Low / Medium / High / Very High>",
  "top_risks": [
    {{"category": "<category>", "description": "<risk>", "severity": "<Low/Medium/High/Critical>", "mitigation": "<mitigation>"}},
    ...
  ],
  "analysis": "<1-2 paragraph summary>"
}}"""
        raw = self._call_claude(prompt, max_tokens=1500)
        try:
            return json.loads(raw)
        except Exception:
            return {"overall_risk_level": "Medium", "top_risks": [], "analysis": raw}

    # ── Recommendation ────────────────────────────────────────────────────────
    def _generate_recommendation(
        self, data: Dict, team: Dict, tech: Dict, market: Dict, risks: Dict
    ) -> Dict:
        prompt = f"""Generate a final investment recommendation for {data['company_name']} ({data['sector']} sector).

SCORES:
- Team: {team.get('score')}/10
- Technology (TRL {tech.get('trl', 'N/A')}): {tech.get('score')}/10
- Market: {market.get('score')}/10
- Risk level: {risks.get('overall_risk_level')}
- IP status: {tech.get('ip_status', 'Unknown')}
- Clinical stage: {tech.get('clinical_stage', 'N/A')}
- Stage adjusted scoring: {tech.get('stage_adjusted', False)}

TOP RISKS: {[r.get('description') for r in risks.get('top_risks', [])[:3]]}

Calculate a weighted composite score:
  Team 30% + Technology 35% + Market 35% = composite

Based on composite score, assign verdict:
  INVEST (>=7.5), DEEP_DIVE (6.0-7.4), MONITOR (4.5-5.9), PASS (<4.5)

Return ONLY valid JSON (no markdown):
{{
  "composite_score": <float one decimal>,
  "verdict": "<INVEST | DEEP_DIVE | MONITOR | PASS>",
  "suggested_stage": "<Pre-seed / Seed / Series A / Series B+>",
  "target_check_size": "<e.g. €500K–1M>",
  "key_conditions": ["<condition before investing>", ...],
  "next_steps": ["<action item>", ...],
  "executive_summary": "<3-4 paragraph investment thesis or pass rationale>"
}}"""
        raw = self._call_claude(prompt, max_tokens=2000)
        try:
            return json.loads(raw)
        except Exception:
            return {
                "composite_score": 5.0,
                "verdict": "MONITOR",
                "suggested_stage": "Unknown",
                "target_check_size": "TBD",
                "key_conditions": [],
                "next_steps": [],
                "executive_summary": raw,
            }

    # ── Main analyze ──────────────────────────────────────────────────────────
    def analyze(self, data: Dict) -> Dict:
        print("  AI analysis...")
        print("  → Team analysis...")
        team = self._analyze_team(data)
        print(f"     Team score: {team.get('score')}/10")
        time.sleep(1)

        print("  → Technology analysis (incl. ClinicalTrials + stage adjustment)...")
        tech = self._analyze_technology(data)
        print(f"     Tech score: {tech.get('score')}/10, TRL: {tech.get('trl')}, Stage adjusted: {tech.get('stage_adjusted')}")
        time.sleep(1)

        print("  → Market analysis...")
        market = self._analyze_market(data)
        print(f"     Market score: {market.get('score')}/10")
        time.sleep(1)

        print("  → Risk analysis...")
        risks = self._analyze_risks(data, team, tech, market)
        print(f"     Risk level: {risks.get('overall_risk_level')}")
        time.sleep(1)

        print("  → Final recommendation...")
        recommendation = self._generate_recommendation(data, team, tech, market, risks)
        print(f"     Verdict: {recommendation.get('verdict')} ({recommendation.get('composite_score')}/10)")

        return {
            "team": team,
            "technology": tech,
            "market": market,
            "risks": risks,
            "recommendation": recommendation,
        }


# ─────────────────────────────────────────────────────────────────────────────
# PDF Report Generator
# ─────────────────────────────────────────────────────────────────────────────

VERDICT_COLORS = {
    "INVEST": colors.HexColor("#1a7a1a"),
    "DEEP_DIVE": colors.HexColor("#1a4fa8"),
    "MONITOR": colors.HexColor("#b36b00"),
    "PASS": colors.HexColor("#b30000"),
}

SCORE_COLORS = {
    "high": colors.HexColor("#1a7a1a"),
    "mid": colors.HexColor("#b36b00"),
    "low": colors.HexColor("#b30000"),
}


def _score_color(score: int) -> colors.Color:
    if score >= 7:
        return SCORE_COLORS["high"]
    if score >= 5:
        return SCORE_COLORS["mid"]
    return SCORE_COLORS["low"]


class ReportGenerator:
    """Generates a VC-grade PDF due diligence report."""

    def __init__(self, company_name: str, output_dir: str = "dd_reports"):
        self.company_name = company_name
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        date_str = datetime.datetime.utcnow().strftime("%Y%m%d")
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", company_name)
        self.output_path = os.path.join(output_dir, f"DD_{safe_name}_{date_str}.pdf")

        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles - safe for multiple calls."""
        if "Title1" not in self.styles:
            self.styles.add(ParagraphStyle(
                "Title1", parent=self.styles["Heading1"],
                fontSize=22, spaceAfter=6, textColor=colors.HexColor("#0d1f40"),
            ))
        if "SectionHeader" not in self.styles:
            self.styles.add(ParagraphStyle(
                "SectionHeader", parent=self.styles["Heading2"],
                fontSize=14, spaceAfter=4, spaceBefore=12,
                textColor=colors.HexColor("#1a4fa8"),
            ))
        if "SubHeader" not in self.styles:
            self.styles.add(ParagraphStyle(
                "SubHeader", parent=self.styles["Heading3"],
                fontSize=11, spaceAfter=3, spaceBefore=8,
                textColor=colors.HexColor("#333333"),
            ))
        if "Body" not in self.styles:
            self.styles.add(ParagraphStyle(
                "Body", parent=self.styles["Normal"],
                fontSize=9.5, leading=14, spaceAfter=6, alignment=TA_JUSTIFY,
            ))
        if "Bullet" not in self.styles:
            self.styles.add(ParagraphStyle(
                "Bullet", parent=self.styles["Normal"],
                fontSize=9.5, leading=13, leftIndent=12, bulletIndent=0, spaceAfter=3,
            ))
        if "Caption" not in self.styles:
            self.styles.add(ParagraphStyle(
                "Caption", parent=self.styles["Normal"],
                fontSize=8, textColor=colors.grey, spaceAfter=4,
            ))

    def _verdict_badge(self, verdict: str) -> Table:
        color = VERDICT_COLORS.get(verdict, colors.grey)
        t = Table([[verdict]], colWidths=[5 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), color),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 16),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        return t

    def _scores_table(self, analysis: Dict) -> Table:
        team_s = analysis["team"].get("score", "-")
        tech_s = analysis["technology"].get("score", "-")
        mkt_s = analysis["market"].get("score", "-")
        comp_s = analysis["recommendation"].get("composite_score", "-")
        trl = analysis["technology"].get("trl", "-")
        stage_adj = "Yes" if analysis["technology"].get("stage_adjusted") else "No"

        data = [
            ["Dimension", "Score", "Details"],
            ["Team & Leadership", f"{team_s}/10", ""],
            ["Technology & IP", f"{tech_s}/10", f"TRL {trl} | Stage adj: {stage_adj}"],
            ["Market Opportunity", f"{mkt_s}/10", analysis["market"].get("tam_estimate", "")],
            ["COMPOSITE", f"{comp_s}/10", analysis["recommendation"].get("verdict", "")],
        ]
        col_widths = [6.5 * cm, 3 * cm, 8.5 * cm]
        t = Table(data, colWidths=col_widths)

        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d1f40")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -3), [colors.white, colors.HexColor("#f5f7fa")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8edf5")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        for row_idx, score in enumerate([team_s, tech_s, mkt_s], start=1):
            if isinstance(score, int):
                style.append(("TEXTCOLOR", (1, row_idx), (1, row_idx), _score_color(score)))
                style.append(("FONTNAME", (1, row_idx), (1, row_idx), "Helvetica-Bold"))
        t.setStyle(TableStyle(style))
        return t

    def _risks_table(self, risks: List[Dict]) -> Table:
        if not risks:
            return Paragraph("No risks identified.", self.styles["Body"])
        data = [["Category", "Risk", "Severity", "Mitigation"]]
        for r in risks[:6]:
            data.append([
                r.get("category", ""),
                Paragraph(r.get("description", ""), self.styles["Caption"]),
                r.get("severity", ""),
                Paragraph(r.get("mitigation", ""), self.styles["Caption"]),
            ])
        col_widths = [2.8 * cm, 5.5 * cm, 2 * cm, 7.7 * cm]
        t = Table(data, colWidths=col_widths)

        sev_colors = {
            "Critical": colors.HexColor("#b30000"),
            "High": colors.HexColor("#e05c00"),
            "Medium": colors.HexColor("#b36b00"),
            "Low": colors.HexColor("#1a7a1a"),
        }
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d1f40")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
        ]
        for row_idx, r in enumerate(risks[:6], start=1):
            sev = r.get("severity", "")
            c = sev_colors.get(sev, colors.grey)
            style.append(("TEXTCOLOR", (2, row_idx), (2, row_idx), c))
            style.append(("FONTNAME", (2, row_idx), (2, row_idx), "Helvetica-Bold"))
        t.setStyle(TableStyle(style))
        return t

    def _data_coverage_table(self, raw_data: Dict) -> Table:
        pub_count = len(raw_data.get("publications", []))
        trial_count = len(raw_data.get("clinical_trials", []))
        github_found = raw_data.get("github", {}).get("found", False)
        website_ok = raw_data.get("website_data", {}).get("accessible", False)

        data = [
            ["Data Source", "Status", "Records"],
            ["OpenAlex Publications", "OK" if pub_count > 0 else "None", str(pub_count)],
            ["ClinicalTrials.gov", "OK" if trial_count > 0 else "None", str(trial_count)],
            ["GitHub", "OK" if github_found else "None",
             str(raw_data.get("github", {}).get("repo_count", 0)) if github_found else "0"],
            ["Website", "OK" if website_ok else "Error", "scraped" if website_ok else "inaccessible"],
        ]
        col_widths = [7 * cm, 3 * cm, 3 * cm]
        t = Table(data, colWidths=col_widths)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d1f40")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
            ("ALIGN", (1, 0), (2, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for row_idx, ok in enumerate(
            [pub_count > 0, trial_count > 0, github_found, website_ok], start=1
        ):
            c = colors.HexColor("#1a7a1a") if ok else colors.HexColor("#b30000")
            style.append(("TEXTCOLOR", (1, row_idx), (1, row_idx), c))
            style.append(("FONTNAME", (1, row_idx), (1, row_idx), "Helvetica-Bold"))
        t.setStyle(TableStyle(style))
        return t

    def generate(self, raw_data: Dict, analysis: Dict) -> str:
        doc = SimpleDocTemplate(
            self.output_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )
        story = []
        rec = analysis["recommendation"]
        tech = analysis["technology"]

        # ── Cover ─────────────────────────────────────────────────────────────
        story.append(Paragraph("GenSeed Capital — Due Diligence Report", self.styles["Caption"]))
        story.append(Paragraph(f"Due Diligence Report: {self.company_name}", self.styles["Title1"]))
        story.append(Paragraph(
            f"Sector: {raw_data['sector']}  |  "
            f"Website: {raw_data['website']}  |  "
            f"Generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            self.styles["Caption"],
        ))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a4fa8")))
        story.append(Spacer(1, 0.3 * cm))

        # ── Verdict badge ──────────────────────────────────────────────────────
        verdict = rec.get("verdict", "MONITOR")
        story.append(self._verdict_badge(verdict))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            f"Composite Score: <b>{rec.get('composite_score')}/10</b>  |  "
            f"Stage: {rec.get('suggested_stage', '-')}  |  "
            f"Target check: {rec.get('target_check_size', '-')}",
            self.styles["Body"],
        ))
        story.append(Spacer(1, 0.4 * cm))

        # ── Scores table ──────────────────────────────────────────────────────
        story.append(Paragraph("Scorecard", self.styles["SectionHeader"]))
        story.append(self._scores_table(analysis))
        story.append(Spacer(1, 0.4 * cm))

        # ── Data coverage ─────────────────────────────────────────────────────
        story.append(Paragraph("Data Coverage", self.styles["SectionHeader"]))
        story.append(self._data_coverage_table(raw_data))
        story.append(Spacer(1, 0.4 * cm))

        # ── Executive summary ─────────────────────────────────────────────────
        story.append(Paragraph("Executive Summary", self.styles["SectionHeader"]))
        story.append(Paragraph(rec.get("executive_summary", ""), self.styles["Body"]))
        story.append(Spacer(1, 0.3 * cm))

        # ── Team ──────────────────────────────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
        story.append(Paragraph(
            f"1. Team & Leadership — Score: {analysis['team'].get('score')}/10",
            self.styles["SectionHeader"],
        ))
        story.append(Paragraph(analysis["team"].get("analysis", ""), self.styles["Body"]))
        if analysis["team"].get("key_people"):
            story.append(Paragraph("Key People:", self.styles["SubHeader"]))
            for p in analysis["team"]["key_people"]:
                story.append(Paragraph(f"• {p}", self.styles["Bullet"]))
        if analysis["team"].get("gaps"):
            story.append(Paragraph("Team Gaps:", self.styles["SubHeader"]))
            for g in analysis["team"]["gaps"]:
                story.append(Paragraph(f"• {g}", self.styles["Bullet"]))

        # ── Technology ────────────────────────────────────────────────────────
        story.append(Paragraph(
            f"2. Technology & IP — Score: {tech.get('score')}/10  |  TRL: {tech.get('trl')}  |  "
            f"Stage Adjusted: {'Yes' if tech.get('stage_adjusted') else 'No'}",
            self.styles["SectionHeader"],
        ))
        story.append(Paragraph(
            f"IP Status: {tech.get('ip_status', 'Unknown')}  |  "
            f"Clinical Stage: {tech.get('clinical_stage', 'N/A')}",
            self.styles["Caption"],
        ))
        story.append(Paragraph(tech.get("analysis", ""), self.styles["Body"]))
        if raw_data.get("clinical_trials"):
            story.append(Paragraph("Clinical Trials (ClinicalTrials.gov):", self.styles["SubHeader"]))
            for trial in raw_data["clinical_trials"][:5]:
                story.append(Paragraph(
                    f"• {trial.get('nct_id')} — {trial.get('title', '')[:80]} "
                    f"[{trial.get('phase', '-')} | {trial.get('status', '-')} | "
                    f"n={trial.get('enrollment', '-')}]",
                    self.styles["Bullet"],
                ))

        # ── Market ────────────────────────────────────────────────────────────
        story.append(Paragraph(
            f"3. Market Opportunity — Score: {analysis['market'].get('score')}/10",
            self.styles["SectionHeader"],
        ))
        story.append(Paragraph(
            f"TAM Estimate: {analysis['market'].get('tam_estimate', '-')}  |  "
            f"Differentiation: {analysis['market'].get('differentiation', '-')}",
            self.styles["Caption"],
        ))
        story.append(Paragraph(analysis["market"].get("analysis", ""), self.styles["Body"]))
        if analysis["market"].get("key_competitors"):
            story.append(Paragraph("Key Competitors:", self.styles["SubHeader"]))
            for c in analysis["market"]["key_competitors"][:6]:
                story.append(Paragraph(f"• {c}", self.styles["Bullet"]))

        # ── Risks ─────────────────────────────────────────────────────────────
        story.append(Paragraph(
            f"4. Risk Assessment — Level: {analysis['risks'].get('overall_risk_level')}",
            self.styles["SectionHeader"],
        ))
        story.append(Paragraph(analysis["risks"].get("analysis", ""), self.styles["Body"]))
        story.append(self._risks_table(analysis["risks"].get("top_risks", [])))

        # ── Recommendation ────────────────────────────────────────────────────
        story.append(Paragraph("5. Investment Recommendation", self.styles["SectionHeader"]))
        if rec.get("key_conditions"):
            story.append(Paragraph("Conditions / Pre-investment Checklist:", self.styles["SubHeader"]))
            for c in rec["key_conditions"]:
                story.append(Paragraph(f"[ ] {c}", self.styles["Bullet"]))
        if rec.get("next_steps"):
            story.append(Paragraph("Next Steps:", self.styles["SubHeader"]))
            for ns in rec["next_steps"]:
                story.append(Paragraph(f"-> {ns}", self.styles["Bullet"]))

        # ── Raw data appendix ─────────────────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
        story.append(Paragraph("Appendix — Raw Data", self.styles["SectionHeader"]))
        if raw_data.get("publications"):
            story.append(Paragraph("Top Publications (OpenAlex):", self.styles["SubHeader"]))
            for pub in raw_data["publications"][:5]:
                story.append(Paragraph(
                    f"• {pub.get('title', '')[:100]} ({pub.get('year')}, {pub.get('citations')} citations)",
                    self.styles["Bullet"],
                ))
        if raw_data.get("github", {}).get("found"):
            gh = raw_data["github"]
            story.append(Paragraph(
                f"GitHub: github.com/{gh.get('org_slug')} — "
                f"{gh.get('repo_count')} repos, {gh.get('total_stars')} stars, "
                f"languages: {', '.join(gh.get('languages', [])[:5])}",
                self.styles["Body"],
            ))

        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(
            "This report was generated automatically by GenSeed Capital's DD Assistant v1.1. "
            "It is for internal use only and does not constitute investment advice. "
            "All data from public sources; AI analysis should be verified by human analysts.",
            self.styles["Caption"],
        ))

        doc.build(story)
        return self.output_path


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_dd_pipeline(
    company_name: str,
    website: str,
    sector: str,
    api_key: str,
    output_dir: str = "dd_reports",
) -> str:
    """Full DD pipeline. Returns path to the generated PDF."""
    print(f"\n{'='*60}")
    print(f"DD Pipeline v1.1: {company_name}")
    print(f"Sector: {sector}  |  Website: {website}")
    print(f"{'='*60}\n")

    print("[1/3] Data Collection")
    collector = DataCollector(company_name=company_name, website=website, sector=sector)
    raw_data = collector.collect()

    print("\n[2/3] AI Analysis")
    analyzer = AIAnalyzer(api_key=api_key)
    analysis = analyzer.analyze(raw_data)

    print("\n[3/3] Generating PDF Report")
    generator = ReportGenerator(company_name=company_name, output_dir=output_dir)
    report_path = generator.generate(raw_data=raw_data, analysis=analysis)
    print(f"  Report saved: {report_path}")

    print(f"\n{'='*60}")
    print(f"VERDICT: {analysis['recommendation'].get('verdict')} "
          f"({analysis['recommendation'].get('composite_score')}/10)")
    print(f"{'='*60}\n")

    return report_path


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GenSeed Capital DD Assistant v1.1")
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument("--website", required=True, help="Company website URL")
    parser.add_argument("--sector", default="Longevity",
                        choices=["Longevity", "Space", "Biotech", "DeepTech"],
                        help="Investment sector")
    parser.add_argument("--output-dir", default="dd_reports", help="Output directory for PDFs")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    report = run_dd_pipeline(
        company_name=args.company,
        website=args.website,
        sector=args.sector,
        api_key=api_key,
        output_dir=args.output_dir,
    )
    print(f"Done. Report: {report}")
