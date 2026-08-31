#!/usr/bin/env python3
"""
GenSeed Capital - AI-Powered Deal Sourcing Engine v3.0
Combines multiple free sources + Claude AI scoring + Attio CRM integration
"""

import requests
import json
import time
from datetime import datetime
from typing import List, Dict, Optional
import re

# ============================================
# CONFIGURATION
# ============================================

# Attio CRM
ATTIO_TOKEN = "---"
ATTIO_LIST_ID = "--"

# Anthropic Claude API (add your key)
CLAUDE_API_KEY = "---"  

# Rate limiting
RATE_LIMIT_DELAY = 1.0  # seconds between API calls

# Scoring threshold
MIN_SCORE_TO_PUSH = 70  # Only push companies scoring 70+ to Attio

# ============================================
# DATA SOURCE: OPENALEX (Academic Research)
# ============================================

def fetch_openalex_companies(query: str, sector: str, limit: int = 20) -> List[Dict]:
    """
    Fetch companies from OpenAlex by finding recent research papers,
    then extracting non-academic affiliated institutions
    """
    print(f"  🔍 Searching OpenAlex for '{query}'...")
    
    url = "https://api.openalex.org/works"
    params = {
        "search": query,
        "filter": "publication_year:2024-2025,type:journal-article",
        "per_page": limit,
        "mailto": "hello@genseed.vc"  # Polite API usage
    }
    
    companies = []
    seen_names = set()
    
    try:
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"    ⚠️  OpenAlex error: {resp.status_code}")
            return companies
            
        data = resp.json()
        results = data.get('results', [])
        
        for work in results:
            # Extract institutions from authorships
            for authorship in work.get('authorships', []):
                for inst in authorship.get('institutions', []):
                    inst_name = inst.get('display_name', '')
                    inst_type = inst.get('type', '')
                    inst_url = inst.get('homepage_url', '')
                    
                    # Filter: Skip universities, colleges, government labs
                    skip_keywords = ['university', 'college', 'institute', 'national lab', 
                                   'government', 'ministry', 'agency', 'hospital']
                    if any(kw in inst_name.lower() for kw in skip_keywords):
                        continue
                    
                    # Filter: Only private/company types
                    if inst_type not in ['company', 'facility', 'healthcare', 'nonprofit', 'other']:
                        continue
                    
                    # Deduplicate
                    if inst_name in seen_names:
                        continue
                    seen_names.add(inst_name)
                    
                    companies.append({
                        "name": inst_name,
                        "website": inst_url or "",
                        "description": f"Identified via research paper: {work.get('title', '')[:100]}...",
                        "sector": sector,
                        "source": "OpenAlex",
                        "trl": "TRL 3-5 (Estimated)",
                        "raw_data": {
                            "paper_title": work.get('title', ''),
                            "paper_url": work.get('doi', ''),
                            "cited_by": work.get('cited_by_count', 0)
                        }
                    })
        
        print(f"    ✓ Found {len(companies)} potential companies")
        
    except Exception as e:
        print(f"    ❌ OpenAlex error: {e}")
    
    return companies


# ============================================
# DATA SOURCE: PRODUCT HUNT (New Launches)
# ============================================

def fetch_producthunt_companies(query: str, sector: str, limit: int = 10) -> List[Dict]:
    """
    Fetch new product launches from Product Hunt
    Great for finding early-stage startups
    """
    print(f"  🔍 Searching Product Hunt for '{query}'...")
    
    companies = []
    
    # Product Hunt GraphQL API (no auth needed for basic search)
    url = "https://api.producthunt.com/v2/api/graphql"
    
    # GraphQL query
    graphql_query = """
    query {
      posts(first: %d, order: VOTES, postedAfter: "2024-01-01") {
        edges {
          node {
            name
            tagline
            description
            website
            votesCount
            makers {
              name
            }
          }
        }
      }
    }
    """ % limit
    
    try:
        # Note: Product Hunt requires API token for most endpoints
        # For free tier: we'll scrape the website instead
        
        # Alternative: Scrape Product Hunt search page
        search_url = f"https://www.producthunt.com/search?q={query.replace(' ', '+')}"
        
        # For MVP: Simple HTTP request to check for companies
        # TODO: Implement proper scraping with BeautifulSoup
        print(f"    ⚠️  Product Hunt scraping - implement with BeautifulSoup")
        print(f"    → Search URL: {search_url}")
        
    except Exception as e:
        print(f"    ❌ Product Hunt error: {e}")
    
    return companies


# ============================================
# DATA SOURCE: bioRxiv/medRxiv (Longevity Research)
# ============================================

def fetch_biorxiv_companies(query: str, sector: str, limit: int = 15) -> List[Dict]:
    """
    Fetch recent biology/medicine preprints from bioRxiv and medRxiv
    Excellent source for cutting-edge longevity research
    """
    print(f"  🔍 Searching bioRxiv/medRxiv for '{query}'...")
    
    companies = []
    seen_affiliations = set()
    
    # bioRxiv API endpoint
    url = "https://api.biorxiv.org/details/biorxiv/2024-01-01/2025-12-31"
    
    try:
        # Search recent papers
        params = {"format": "json", "cursor": 0}
        resp = requests.get(url, params=params, timeout=20)
        
        if resp.status_code != 200:
            print(f"    ⚠️  bioRxiv error: {resp.status_code}")
            return companies
        
        data = resp.json()
        
        # Filter by query keywords
        query_terms = query.lower().split()
        
        for paper in data.get('collection', [])[:limit]:
            title = paper.get('title', '').lower()
            abstract = paper.get('abstract', '').lower()
            
            # Check if paper matches query
            if not any(term in title or term in abstract for term in query_terms):
                continue
            
            # Extract author affiliations
            authors = paper.get('authors', '').split(';')
            for author_info in authors:
                # Affiliations usually in format: "Name (Institution)"
                if '(' in author_info and ')' in author_info:
                    affiliation = author_info.split('(')[1].split(')')[0].strip()
                    
                    # Filter out academic institutions
                    skip_keywords = ['university', 'college', 'institute', 'hospital', 
                                   'school', 'center', 'laboratory']
                    if any(kw in affiliation.lower() for kw in skip_keywords):
                        continue
                    
                    if affiliation and affiliation not in seen_affiliations:
                        seen_affiliations.add(affiliation)
                        
                        companies.append({
                            "name": affiliation,
                            "website": "",
                            "description": f"Research: {paper.get('title', '')[:80]}...",
                            "sector": sector,
                            "source": "bioRxiv",
                            "trl": "TRL 2-4 (Pre-clinical)",
                            "raw_data": {
                                "paper_doi": paper.get('doi', ''),
                                "paper_date": paper.get('date', '')
                            }
                        })
        
        print(f"    ✓ Found {len(companies)} affiliated organizations")
        
    except Exception as e:
        print(f"    ❌ bioRxiv error: {e}")
    
    return companies


# ============================================
# DATA SOURCE: NASA Tech Transfer (Space)
# ============================================

def fetch_nasa_techransfer(query: str, sector: str, limit: int = 10) -> List[Dict]:
    """
    NASA Technology Transfer Program - space tech available for licensing
    Great for finding space economy opportunities
    """
    print(f"  🔍 Searching NASA Tech Transfer for '{query}'...")
    
    companies = []
    
    # NASA Tech Transfer API
    url = "https://technology.nasa.gov/api/patents"
    
    try:
        # Search patents/technologies
        params = {
            "query": query,
            "limit": limit
        }
        
        resp = requests.get(url, params=params, timeout=20)
        
        if resp.status_code != 200:
            print(f"    ⚠️  NASA API error: {resp.status_code}")
            return companies
        
        data = resp.json()
        
        for tech in data.get('results', []):
            # Look for licensees (companies that licensed NASA tech)
            licensee = tech.get('licensee', '')
            
            if licensee and licensee != 'Available':
                companies.append({
                    "name": licensee,
                    "website": "",
                    "description": f"Licensed NASA tech: {tech.get('title', '')[:100]}",
                    "sector": sector,
                    "source": "NASA Tech Transfer",
                    "trl": "TRL 4-6 (NASA validated)",
                    "raw_data": {
                        "tech_id": tech.get('id', ''),
                        "tech_category": tech.get('category', '')
                    }
                })
        
        print(f"    ✓ Found {len(companies)} NASA tech licensees")
        
    except Exception as e:
        print(f"    ❌ NASA Tech Transfer error: {e}")
    
    return companies


# ============================================
# DATA SOURCE: F6S (Startup Accelerators)
# ============================================

def fetch_f6s_companies(query: str, sector: str, limit: int = 15) -> List[Dict]:
    """
    F6S - startup accelerator and funding platform
    Good source for early-stage companies
    """
    print(f"  🔍 Searching F6S for '{query}'...")
    
    companies = []
    
    # F6S doesn't have official API - need to scrape
    # For MVP: returning placeholder
    search_url = f"https://www.f6s.com/search?q={query.replace(' ', '+')}"
    
    print(f"    ⚠️  F6S scraping - implement with BeautifulSoup")
    print(f"    → Search URL: {search_url}")
    
    # TODO: Implement scraping
    # Key fields to extract: company name, website, description, funding stage
    
    return companies


# ============================================
# DATA SOURCE: HACKER NEWS (YC + Startup Mentions)
# ============================================

def fetch_hackernews_companies(query: str, sector: str, limit: int = 10) -> List[Dict]:
    """
    Search HackerNews for startup launches and Show HN posts
    Great for finding YC companies and early-stage startups
    """
    print(f"  🔍 Searching Hacker News for '{query}'...")
    
    companies = []
    
    # Algolia HN Search API (official, free)
    url = "https://hn.algolia.com/api/v1/search"
    
    try:
        params = {
            "query": query,
            "tags": "(show_hn,launch_hn)",  # Filter for startup launches
            "hitsPerPage": limit
        }
        
        resp = requests.get(url, params=params, timeout=20)
        
        if resp.status_code != 200:
            print(f"    ⚠️  HackerNews error: {resp.status_code}")
            return companies
        
        data = resp.json()
        
        for hit in data.get('hits', []):
            title = hit.get('title', '')
            url_hn = hit.get('url', '')
            author = hit.get('author', '')
            
            # Extract company name from "Show HN: [Company] - description"
            if 'Show HN:' in title:
                company_name = title.replace('Show HN:', '').split('-')[0].strip()
                
                companies.append({
                    "name": company_name,
                    "website": url_hn,
                    "description": f"HN Launch: {title}",
                    "sector": sector,
                    "source": "HackerNews",
                    "trl": "TRL 3-5 (Public Launch)",
                    "raw_data": {
                        "hn_author": author,
                        "hn_points": hit.get('points', 0),
                        "hn_comments": hit.get('num_comments', 0)
                    }
                })
        
        print(f"    ✓ Found {len(companies)} HN launches")
        
    except Exception as e:
        print(f"    ❌ HackerNews error: {e}")
    
    return companies


# ============================================
# DATA SOURCE: GITHUB (Open Source Projects)
# ============================================

def fetch_github_projects(query: str, sector: str, limit: int = 10) -> List[Dict]:
    """
    Find relevant open-source projects on GitHub
    Can indicate early-stage companies or research teams
    """
    print(f"  🔍 Searching GitHub for '{query}'...")
    
    url = "https://api.github.com/search/repositories"
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": limit
    }
    
    companies = []
    
    try:
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"    ⚠️  GitHub error: {resp.status_code}")
            return companies
        
        data = resp.json()
        
        for repo in data.get('items', []):
            # Extract organization/owner
            owner = repo.get('owner', {})
            owner_type = owner.get('type', '')
            
            # Focus on Organizations (not individual users)
            if owner_type != 'Organization':
                continue
            
            org_name = owner.get('login', '')
            org_url = owner.get('html_url', '')
            
            companies.append({
                "name": org_name,
                "website": org_url,
                "description": f"GitHub project: {repo.get('description', '')[:100]}",
                "sector": sector,
                "source": "GitHub",
                "trl": "TRL 2-4 (Open Source)",
                "raw_data": {
                    "repo_name": repo.get('name', ''),
                    "stars": repo.get('stargazers_count', 0),
                    "language": repo.get('language', 'Unknown')
                }
            })
        
        print(f"    ✓ Found {len(companies)} GitHub organizations")
        
    except Exception as e:
        print(f"    ❌ GitHub error: {e}")
    
    return companies


# ============================================
# AI SCORING with Claude
# ============================================

def score_company_with_ai(company: Dict) -> Dict:
    """
    Use Claude AI to score company fit for GenSeed investment thesis
    Returns enhanced company dict with score and analysis
    """
    
    if not CLAUDE_API_KEY or CLAUDE_API_KEY == "YOUR_ANTHROPIC_API_KEY_HERE":
        print(f"    ⚠️  No Claude API key - skipping AI scoring for {company['name']}")
        company['ai_score'] = 50  # Default neutral score
        company['ai_analysis'] = "AI scoring disabled (no API key)"
        return company
    
    prompt = f"""You are an expert VC analyst for GenSeed Capital, an ELTIF 2.0 fund focused on longevity and space economy investments.

FUND THESIS:
- Sectors: Longevity (cellular health, disease prevention, healthspan extension) OR Space (launch tech, satellites, space infrastructure)
- Stage: Seed / Series A (€500K-€3M rounds preferred)
- Geography: US + EU preferred
- Ticket size: €150K-€500K

COMPANY TO ANALYZE:
Name: {company['name']}
Sector Tag: {company['sector']}
Description: {company['description']}
Source: {company['source']}
Website: {company.get('website', 'Unknown')}

TASK:
Score this company 0-100 for investment fit and provide structured analysis.

OUTPUT FORMAT (JSON):
{{
  "score": <0-100 integer>,
  "thesis_fit": "HIGH/MEDIUM/LOW - brief explanation",
  "stage_fit": "LIKELY_SEED/LIKELY_SERIES_A/TOO_EARLY/TOO_LATE - brief explanation",
  "red_flags": ["list any concerns based on available info"],
  "green_flags": ["list positive signals"],
  "recommendation": "DEEP_DIVE / MONITOR / PASS",
  "one_line_summary": "concise investment memo headline"
}}

SCORING RUBRIC:
90-100: Perfect fit (strong thesis alignment + appropriate stage signals)
70-89: Strong candidate (good fit with minor unknowns)
50-69: Possible fit (needs more research to determine)
30-49: Weak fit (thesis mismatch or wrong stage likely)
0-29: Clear pass (out of scope)

Respond with ONLY the JSON, no other text."""

    try:
        headers = {
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if resp.status_code == 200:
            response_text = resp.json()['content'][0]['text']
            
            # Parse JSON from response
            # Claude sometimes wraps in ```json blocks, so clean it
            json_text = response_text.strip()
            if json_text.startswith('```json'):
                json_text = json_text[7:]  # Remove ```json
            if json_text.endswith('```'):
                json_text = json_text[:-3]  # Remove ```
            json_text = json_text.strip()
            
            analysis = json.loads(json_text)
            
            company['ai_score'] = analysis.get('score', 0)
            company['ai_analysis'] = analysis
            
            print(f"    🤖 AI Score: {company['ai_score']}/100 - {analysis.get('recommendation', 'N/A')}")
            
        else:
            print(f"    ❌ Claude API error: {resp.status_code}")
            company['ai_score'] = 50
            company['ai_analysis'] = f"API error: {resp.status_code}"
            
    except Exception as e:
        print(f"    ❌ AI scoring error: {e}")
        company['ai_score'] = 50
        company['ai_analysis'] = f"Error: {str(e)}"
    
    return company


# ============================================
# PUSH TO ATTIO CRM
# ============================================

def push_to_attio(company: Dict) -> bool:
    """
    Push high-scoring company to Attio CRM
    """
    headers = {
        "Authorization": f"Bearer {ATTIO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    name = company['name']
    website = company.get('website', '')
    
    # Clean domain
    clean_domain = None
    if website and 'http' in website:
        clean_domain = website.split("//")[-1].split("/")[0].replace("www.", "")
    
    # 1. Create Company Record
    company_payload = {
        "data": {
            "values": {
                "name": [{"value": name}],
            }
        }
    }
    
    if clean_domain:
        company_payload["data"]["values"]["domains"] = [{"domain": clean_domain}]
    
    try:
        # Create or find company
        resp = requests.post(
            "https://api.attio.com/v2/objects/companies/records",
            headers=headers,
            json=company_payload
        )
        
        record_id = None
        
        if resp.status_code in [200, 201]:
            record_id = resp.json()["data"]["id"]["record_id"]
        elif resp.status_code == 400:
            # Company might already exist - search for it
            search_payload = {
                "data": {
                    "filter": {
                        "name": {"condition": "equals", "value": name}
                    }
                }
            }
            search_resp = requests.post(
                "https://api.attio.com/v2/objects/companies/records/query",
                headers=headers,
                json=search_payload
            )
            if search_resp.status_code == 200 and search_resp.json().get("data"):
                record_id = search_resp.json()["data"][0]["id"]["record_id"]
        
        if not record_id:
            print(f"    ❌ Failed to create/find company: {name}")
            return False
        
        # 2. Add to List
        list_payload = {
            "data": {
                "parent_object": "companies",
                "parent_record_id": record_id,
                "entry_values": {
                    # Add custom fields if you've configured them in Attio
                    # "ai_score": company.get('ai_score', 0),
                    # "sector": company.get('sector', ''),
                    # "source": company.get('source', '')
                }
            }
        }
        
        list_resp = requests.post(
            f"https://api.attio.com/v2/lists/{ATTIO_LIST_ID}/entries",
            headers=headers,
            json=list_payload
        )
        
        if list_resp.status_code in [200, 201]:
            print(f"    ✅ Pushed to Attio: {name} (Score: {company.get('ai_score', 'N/A')})")
            return True
        else:
            print(f"    ⚠️  Failed to add to list: {list_resp.status_code}")
            return False
            
    except Exception as e:
        print(f"    ❌ Attio push error for {name}: {e}")
        return False


# ============================================
# MAIN ORCHESTRATION
# ============================================

def run_sourcing_pipeline():
    """
    Main pipeline: Fetch → Score → Filter → Push
    """
    print("=" * 60)
    print("🚀 GenSeed Capital - AI Deal Sourcing Engine v3.0")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Define search queries by sector (REDUCED FOR TEST)
    searches = [
        # LONGEVITY - Testing with 1 query
        {
            "sector": "Longevity Biotech",
            "queries": [
                "cellular reprogramming aging",  # Single test query
                # Commented out for test run:
                # "senolytic drugs discovery",
                # "NAD+ longevity therapeutics",
                # "mitochondrial health compounds"
            ]
        },
        # SPACE - Testing with 1 query
        {
            "sector": "Space Economy",
            "queries": [
                "microgravity manufacturing",  # Single test query
                # Commented out for test run:
                # "satellite propulsion systems",
                # "orbital debris removal",
                # "space-based solar power"
            ]
        }
    ]
    
    all_companies = []
    stats = {
        "total_found": 0,
        "scored_above_70": 0,
        "pushed_to_attio": 0,
        "by_source": {}
    }
    
    # STEP 1: Fetch from all sources
    for search_config in searches:
        sector = search_config['sector']
        print(f"\n📊 SECTOR: {sector}")
        print("-" * 60)
        
        for query in search_config['queries']:
            print(f"\n🔎 Query: '{query}'")
            
            # Source 1: OpenAlex (Academic Research)
            openalex_companies = fetch_openalex_companies(query, sector, limit=5)  # Reduced for test
            all_companies.extend(openalex_companies)
            stats['by_source']['OpenAlex'] = stats['by_source'].get('OpenAlex', 0) + len(openalex_companies)
            
            # Source 2: GitHub (Open Source)
            github_companies = fetch_github_projects(query, sector, limit=3)  # Reduced for test
            all_companies.extend(github_companies)
            stats['by_source']['GitHub'] = stats['by_source'].get('GitHub', 0) + len(github_companies)
            
            # Source 3: bioRxiv (Longevity-specific)
            if 'longevity' in sector.lower() or 'biotech' in sector.lower():
                biorxiv_companies = fetch_biorxiv_companies(query, sector, limit=5)  # Reduced for test
                all_companies.extend(biorxiv_companies)
                stats['by_source']['bioRxiv'] = stats['by_source'].get('bioRxiv', 0) + len(biorxiv_companies)
            
            # Source 4: NASA Tech Transfer (Space-specific)
            if 'space' in sector.lower():
                nasa_companies = fetch_nasa_techransfer(query, sector, limit=3)  # Reduced for test
                all_companies.extend(nasa_companies)
                stats['by_source']['NASA'] = stats['by_source'].get('NASA', 0) + len(nasa_companies)
            
            # Source 5: HackerNews (Startup launches)
            hn_companies = fetch_hackernews_companies(query, sector, limit=3)  # Added!
            all_companies.extend(hn_companies)
            stats['by_source']['HackerNews'] = stats['by_source'].get('HackerNews', 0) + len(hn_companies)
            
            # Rate limiting between queries
            time.sleep(RATE_LIMIT_DELAY)
    
    stats['total_found'] = len(all_companies)
    print(f"\n{'=' * 60}")
    print(f"📈 FETCHING COMPLETE: {stats['total_found']} companies found")
    print(f"{'=' * 60}\n")
    
    # STEP 2: AI Scoring
    print("\n🤖 AI SCORING PHASE")
    print("-" * 60)
    
    for i, company in enumerate(all_companies, 1):
        print(f"\n[{i}/{len(all_companies)}] Scoring: {company['name']}")
        company = score_company_with_ai(company)
        
        if company.get('ai_score', 0) >= MIN_SCORE_TO_PUSH:
            stats['scored_above_70'] += 1
        
        time.sleep(RATE_LIMIT_DELAY)  # Rate limit Claude API
    
    # STEP 3: Filter and Push to Attio
    print(f"\n{'=' * 60}")
    print(f"📤 PUSHING HIGH-SCORING COMPANIES TO ATTIO (Score >= {MIN_SCORE_TO_PUSH})")
    print(f"{'=' * 60}\n")
    
    high_scorers = [c for c in all_companies if c.get('ai_score', 0) >= MIN_SCORE_TO_PUSH]
    
    for company in high_scorers:
        if push_to_attio(company):
            stats['pushed_to_attio'] += 1
        time.sleep(RATE_LIMIT_DELAY)
    
    # FINAL REPORT
    print(f"\n{'=' * 60}")
    print("📊 SOURCING PIPELINE COMPLETE")
    print(f"{'=' * 60}")
    print(f"Total companies found:       {stats['total_found']}")
    print(f"\nBreakdown by source:")
    for source, count in stats['by_source'].items():
        print(f"  - {source}: {count}")
    print(f"\nScored 70+:                  {stats['scored_above_70']}")
    print(f"Pushed to Attio:             {stats['pushed_to_attio']}")
    print(f"Completion time:             {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")
    
    # Export detailed results to JSON
    output_file = f"sourcing_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump({
            "stats": stats,
            "companies": all_companies
        }, f, indent=2)
    
    print(f"💾 Detailed results saved to: {output_file}\n")


if __name__ == "__main__":
    run_sourcing_pipeline()
