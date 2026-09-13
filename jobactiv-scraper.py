#!/usr/bin/env python3
"""
JobActiv Scraper — extrage oferte de muncă de pe multiple platforme
și le salvează în jobs.json pentru dashboard.

Platforme:
- RemoteOK (API JSON gratuit)
- Himalayas (API JSON gratuit)
- We Work Remotely (RSS feed)
- Wellfound (scrapare HTML — fallback)
- Bestjobs (scrapare HTML — fallback)

Usage:
    python jobactiv-scraper.py [--keywords "construction tech,propTech,AEC"]
    python jobactiv-scraper.py --dashboard  # copiază jobs.json în repo dashboard

Output: jobs.json cu oferte normalizate.
"""

import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
import os
import sys
import time
from datetime import datetime, timezone

# === Config ===
KEYWORDS_DEFAULT = [
    "construction technology", "propTech", "AEC automation",
    "edilizia 4.0", "digital construction", "construction tech",
    "building information modeling", "BIM", "AI construction",
    "automation construction", "site manager", "project coordinator",
    "construction manager", "site coordinator", "edilizia digitale",
    "digitalizzazione edilizia", "cantiere digitale",
]

REMOTE_OK_API = "https://remoteok.com/api"
HIMALAYAS_API = "https://himalayas.app/api/v1/jobs"
WWR_RSS = "https://weworkremotely.com/remote-jobs.rss"

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "jobs.json")
DASHBOARD_REPO = os.path.join(os.path.dirname(__file__), "..", "..", "projects", "jobactiv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (JobActiv-Scraper/1.0; +https://github.com/ivanovandreidimitrov-ctrl)"
}

def fetch_url(url, timeout=15):
    """Fetch URL cu error handling."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            # Detect encoding
            encoding = resp.headers.get_content_charset() or "utf-8"
            return data.decode(encoding, errors="replace")
    except Exception as e:
        print(f"  [ERR] {url}: {e}")
        return None

def matches_keywords(text, keywords):
    """Verifică dacă textul conține vreun keyword."""
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False

def normalize_job(source, job_id, title, company, url, location, tags, description, posted_at):
    """Normalizează un job în format统一."""
    return {
        "id": f"{source}-{job_id}",
        "source": source,
        "title": title or "—",
        "company": company or "—",
        "url": url or "",
        "location": location or "Remote",
        "tags": tags or [],
        "description": (description or "")[:500],
        "posted_at": posted_at or datetime.now(timezone.utc).isoformat(),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }

# === RemoteOK ===
def scrape_remoteok(keywords):
    """RemoteOK are API JSON gratuit, fără auth."""
    print("[RemoteOK] Fetching API...")
    data = fetch_url(REMOTE_OK_API)
    if not data:
        return []
    try:
        jobs_raw = json.loads(data)
    except json.JSONDecodeError:
        print("  [ERR] RemoteOK: JSON parse failed")
        return []
    
    # Primul element e metadata, restul sunt joburi
    if isinstance(jobs_raw, list) and len(jobs_raw) > 1:
        jobs_raw = jobs_raw[1:]
    elif isinstance(jobs_raw, dict) and "jobs" in jobs_raw:
        jobs_raw = jobs_raw["jobs"]
    
    results = []
    for job in jobs_raw:
        if not isinstance(job, dict):
            continue
        title = job.get("position") or job.get("title") or ""
        company = job.get("company") or ""
        desc = job.get("description") or job.get("tags") or ""
        tags = job.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        url = job.get("url") or job.get("apply_url") or ""
        if url and not url.startswith("http"):
            url = "https://remoteok.com" + url
        location = job.get("location") or "Remote"
        posted = job.get("date") or job.get("posted_at")
        
        full_text = f"{title} {company} {desc} {' '.join(tags)}"
        if matches_keywords(full_text, keywords):
            results.append(normalize_job(
                "remoteok", job.get("id", ""), title, company, url,
                location, tags, desc, posted
            ))
    print(f"  [OK] RemoteOK: {len(results)} joburi găsite")
    return results

# === Himalayas ===
def scrape_himalayas(keywords):
    """Himalayas API JSON gratuit."""
    print("[Himalayas] Fetching API...")
    data = fetch_url(HIMALAYAS_API)
    if not data:
        return []
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        print("  [ERR] Himalayas: JSON parse failed")
        return []
    
    jobs_raw = parsed.get("jobs", []) if isinstance(parsed, dict) else parsed
    results = []
    for job in jobs_raw:
        if not isinstance(job, dict):
            continue
        title = job.get("title") or job.get("position") or ""
        company = job.get("company_name") or job.get("company", {}).get("name", "") if isinstance(job.get("company"), dict) else job.get("company", "")
        desc = job.get("description") or ""
        tags = job.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        url = job.get("url") or job.get("apply_url") or ""
        location = job.get("location") or "Remote"
        posted = job.get("posted_at") or job.get("date")
        
        full_text = f"{title} {company} {desc} {' '.join(tags)}"
        if matches_keywords(full_text, keywords):
            results.append(normalize_job(
                "himalayas", job.get("id", ""), title, company, url,
                location, tags, desc, posted
            ))
    print(f"  [OK] Himalayas: {len(results)} joburi găsite")
    return results

# === We Work Remotely (RSS) ===
def scrape_wwr(keywords):
    """WWR are RSS feeds gratuite."""
    print("[WWR] Fetching RSS...")
    results = []
    for feed_url in [WWR_RSS]:
        data = fetch_url(feed_url)
        if not data:
            continue
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            print(f"  [ERR] WWR RSS parse failed: {feed_url}")
            continue
        
        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")
            
            title = title_el.text if title_el is not None else ""
            # WWR format: "Company: Job Title"
            company = ""
            if ": " in title:
                company, title = title.split(": ", 1)
            
            url = link_el.text if link_el is not None else ""
            desc = desc_el.text if desc_el is not None else ""
            # Strip HTML from description
            desc = re.sub(r'<[^>]+>', ' ', desc).strip()
            posted = pub_el.text if pub_el is not None else ""
            
            full_text = f"{title} {company} {desc}"
            if matches_keywords(full_text, keywords):
                results.append(normalize_job(
                    "wwr", hash(url), title, company, url,
                    "Remote", [], desc[:300], posted
                ))
    print(f"  [OK] WWR: {len(results)} joburi găsite")
    return results

# === Bestjobs (HTML scrape — simplificat) ===
def scrape_bestjobs(keywords):
    """Bestjobs — scrapare simplă HTML."""
    print("[Bestjobs] Fetching...")
    results = []
    search_url = "https://www.bestjobs.eu/jobs?q=" + urllib.parse.quote("construction technology")
    data = fetch_url(search_url)
    if not data:
        return []
    
    # Extrage job-uri din HTML (pattern simplu)
    # Caută link-uri către pagini de joburi
    job_pattern = r'href="(/ro/[^"]*job[^"]*)"[^>]*>([^<]*)'
    matches = re.findall(job_pattern, data, re.IGNORECASE)
    seen = set()
    for url_path, title in matches[:20]:
        full_url = "https://www.bestjobs.eu" + url_path
        if full_url in seen:
            continue
        seen.add(full_url)
        if matches_keywords(title, keywords):
            results.append(normalize_job(
                "bestjobs", hash(full_url), title.strip(), "", full_url,
                "EU", [], "", ""
            ))
    print(f"  [OK] Bestjobs: {len(results)} joburi găsite")
    return results

# === Main ===
def main():
    keywords = KEYWORDS_DEFAULT
    if "--keywords" in sys.argv:
        idx = sys.argv.index("--keywords")
        if idx + 1 < len(sys.argv):
            keywords = [k.strip() for k in sys.argv[idx + 1].split(",")]
    
    print(f"=== JobActiv Scraper v1.0 ===")
    print(f"Keywords: {', '.join(keywords[:5])}...")
    print()
    
    all_jobs = []
    
    # RemoteOK (API JSON — cel mai reliable)
    try:
        all_jobs.extend(scrape_remoteok(keywords))
    except Exception as e:
        print(f"  [ERR] RemoteOK: {e}")
    
    time.sleep(1)
    
    # Himalayas (API JSON)
    try:
        all_jobs.extend(scrape_himalayas(keywords))
    except Exception as e:
        print(f"  [ERR] Himalayas: {e}")
    
    time.sleep(1)
    
    # We Work Remotely (RSS)
    try:
        all_jobs.extend(scrape_wwr(keywords))
    except Exception as e:
        print(f"  [ERR] WWR: {e}")
    
    time.sleep(1)
    
    # Bestjobs (HTML scrape)
    try:
        all_jobs.extend(scrape_bestjobs(keywords))
    except Exception as e:
        print(f"  [ERR] Bestjobs: {e}")
    
    # Deduplicate by URL
    seen_urls = set()
    unique_jobs = []
    for job in all_jobs:
        if job["url"] and job["url"] not in seen_urls:
            seen_urls.add(job["url"])
            unique_jobs.append(job)
        elif not job["url"]:
            unique_jobs.append(job)
    
    # Sort by posted_at (newest first)
    unique_jobs.sort(key=lambda j: j.get("posted_at", ""), reverse=True)
    
    # Output
    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_jobs": len(unique_jobs),
        "sources": list(set(j["source"] for j in unique_jobs)),
        "jobs": unique_jobs,
    }
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== Gata: {len(unique_jobs)} joburi unice ===")
    print(f"Salvat în: {OUTPUT_FILE}")
    
    # Copiază în dashboard repo dacă --dashboard
    if "--dashboard" in sys.argv:
        dest = os.path.join(DASHBOARD_REPO, "jobs.json")
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"Copiat în dashboard: {dest}")
    
    return unique_jobs

if __name__ == "__main__":
    jobs = main()