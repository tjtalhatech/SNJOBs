"""
Fetches "ServiceNow" job listings from two sources:
  1. Adzuna API        (https://developer.adzuna.com)
  2. JSearch / RapidAPI (https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)

Both are free-tier, legal aggregator APIs (no scraping of LinkedIn/Indeed directly).
Results are merged, de-duplicated, sorted by date, and saved to data/jobs.json
which the docs/index.html dashboard reads.

Required environment variables (set as GitHub Actions secrets):
  ADZUNA_APP_ID
  ADZUNA_APP_KEY
  RAPIDAPI_KEY

If a key is missing, that source is simply skipped (so you can start with
just one provider while you sign up for the other).
"""

import os
import json
import hashlib
import datetime
import urllib.request
import urllib.parse

SEARCH_TERM = "ServiceNow"
# Specific role variants give much better matches than the bare word "ServiceNow"
ROLE_VARIANTS = [
    "ServiceNow Developer",
    "ServiceNow Administrator",
    "ServiceNow Architect",
    "ServiceNow Consultant",
    "ServiceNow Implementation",
]
DATA_FILE = os.path.join(os.getcwd(), "public", "data", "jobs.json")


def http_get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def job_id(title, company, link):
    raw = f"{title}|{company}|{link}".lower()
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def fetch_adzuna():
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        print("Skipping Adzuna (no credentials set)")
        return []

    # Adzuna is per-country. Default covers the biggest English-language
    # markets; override with ADZUNA_COUNTRIES="us,gb,in,..." secret/var.
    raw_countries = os.environ.get("ADZUNA_COUNTRIES", "us,gb,in,ca,au").split(",")
    countries = []
    for c in raw_countries:
        c = c.strip().lower()
        if c == "india": countries.append("in")
        elif c == "uk": countries.append("gb")
        elif c == "united kingdom": countries.append("gb")
        elif c == "canada": countries.append("ca")
        elif c == "australia": countries.append("au")
        elif c == "usa" or c == "united states": countries.append("us")
        elif len(c) == 2: countries.append(c)
        else: countries.append(c) # fallback

    jobs = []
    for country in countries:
        country = country.strip()
        if not country:
            continue
        for term in ROLE_VARIANTS:
            url = (
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
                f"?app_id={app_id}&app_key={app_key}"
                f"&what={urllib.parse.quote(term)}"
                f"&results_per_page=30&sort_by=date"
            )
            try:
                data = http_get_json(url)
            except Exception as e:
                print(f"Adzuna error ({country}, {term}): {e}")
                continue
            for r in data.get("results", []):
                title = r.get("title", "").strip()
                company = (r.get("company") or {}).get("display_name", "Unknown")
                link = r.get("redirect_url", "")
                location = (r.get("location") or {}).get("display_name", "")
                
                # Remote detection
                is_remote = any(x in location.lower() or x in title.lower() for x in ["remote", "work from home", "anywhere", "telecommute"])
                
                jobs.append({
                    "id": job_id(title, company, link),
                    "title": title,
                    "company": company,
                    "location": location,
                    "link": link,
                    "source": "Adzuna",
                    "posted": r.get("created", ""),
                    "salary": r.get("salary_min"),
                    "country": country.upper(),
                    "is_remote": is_remote
                })
    print(f"Adzuna: {len(jobs)} jobs")
    return jobs


def fetch_jsearch():
    if os.environ.get("SKIP_JSEARCH") == "true":
        print("Skipping JSearch this run (quota-saving schedule)")
        return []

    key = os.environ.get("RAPIDAPI_KEY")
    if not key:
        print("Skipping JSearch (no RAPIDAPI_KEY set)")
        return []

    jobs = []
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    query = urllib.parse.quote(f"{SEARCH_TERM} developer OR admin OR consultant")
    url = f"https://jsearch.p.rapidapi.com/search?query={query}&num_pages=2&date_posted=week"
    try:
        data = http_get_json(url, headers=headers)
    except Exception as e:
        print(f"JSearch error: {e}")
        return []

    for r in data.get("data", []):
        title = r.get("job_title", "").strip()
        company = r.get("employer_name", "Unknown")
        link = r.get("job_apply_link", "") or r.get("job_google_link", "")
        job_city = r.get("job_city")
        job_country = r.get("job_country")
        location = ", ".join(filter(None, [job_city, job_country]))
        
        # Remote detection
        is_remote = r.get("job_is_remote", False) or any(x in title.lower() for x in ["remote", "work from home", "anywhere"])
        
        jobs.append({
            "id": job_id(title, company, link),
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "source": "JSearch",
            "posted": r.get("job_posted_at_datetime_utc", ""),
            "salary": r.get("job_min_salary"),
            "country": job_country,
            "is_remote": is_remote
        })
    print(f"JSearch: {len(jobs)} jobs")
    return jobs


def fetch_remoteok():
    """Free, no API key required. https://remoteok.com/api"""
    jobs = []
    try:
        data = http_get_json(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0 (servicenow-leads-bot)"},
        )
    except Exception as e:
        print(f"RemoteOK error: {e}")
        return jobs

    for r in data:
        if not isinstance(r, dict) or "position" not in r:
            continue  # first element is metadata, skip it
        title = r.get("position", "")
        tags = " ".join(r.get("tags", [])).lower()
        desc = (r.get("description") or "").lower()
        if "servicenow" not in title.lower() and "servicenow" not in tags and "servicenow" not in desc:
            continue
        company = r.get("company", "Unknown")
        link = r.get("url", "")
        jobs.append({
            "id": job_id(title, company, link),
            "title": title,
            "company": company,
            "location": r.get("location", "Remote"),
            "link": link,
            "source": "RemoteOK",
            "posted": r.get("date", ""),
            "salary": r.get("salary_min"),
            "country": "Remote",
            "is_remote": True
        })
    print(f"RemoteOK: {len(jobs)} jobs")
    return jobs


def fetch_arbeitnow():
    """Free, no API key required. https://www.arbeitnow.com/api/job-board-api"""
    jobs = []
    try:
        data = http_get_json("https://www.arbeitnow.com/api/job-board-api")
    except Exception as e:
        print(f"Arbeitnow error: {e}")
        return jobs

    for r in data.get("data", []):
        title = r.get("title", "")
        tags = " ".join(r.get("tags", [])).lower()
        desc = (r.get("description") or "").lower()
        if "servicenow" not in title.lower() and "servicenow" not in tags and "servicenow" not in desc:
            continue
        company = r.get("company_name", "Unknown")
        link = r.get("url", "")
        location = r.get("location", "")
        is_remote = r.get("remote", False) or any(x in title.lower() or x in location.lower() for x in ["remote", "work from home"])
        
        jobs.append({
            "id": job_id(title, company, link),
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "source": "Arbeitnow",
            "posted": str(r.get("created_at", "")),
            "salary": None,
            "country": "DE" if "germany" in location.lower() else "",
            "is_remote": is_remote
        })
    print(f"Arbeitnow: {len(jobs)} jobs")
    return jobs


def main():
    all_jobs = (
        fetch_adzuna() + fetch_jsearch() + fetch_remoteok() + fetch_arbeitnow()
    )

    # de-dupe by id, keep newest data first
    seen = {}
    for j in all_jobs:
        seen[j["id"]] = j
    deduped = list(seen.values())

    # merge with previously saved jobs so we keep a growing history
    existing = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                existing = json.load(f).get("jobs", [])
        except Exception:
            existing = []

    merged = {j["id"]: j for j in existing}
    for j in deduped:
        merged[j["id"]] = j  # new data overwrites old for same id

    now = datetime.datetime.utcnow()
    thirty_days_ago = now - datetime.timedelta(days=30)

    # Process status and categories
    processed_jobs = []
    for j in merged.values():
        # Recover country for Adzuna if missing
        if not j.get("country") and j.get("source") == "Adzuna":
            link = j.get("link", "").lower()
            if ".in" in link: j["country"] = "IN"
            elif ".com.au" in link: j["country"] = "AU"
            elif ".ca" in link: j["country"] = "CA"
            elif ".org.uk" in link or ".co.uk" in link: j["country"] = "GB"
            elif ".adzuna.com" in link: j["country"] = "US"
        
        # 1. Categorization
        title_lower = j.get("title", "").lower()
        if any(x in title_lower for x in ["developer", "dev ", "engineer"]):
            j["category"] = "Development"
        elif "admin" in title_lower:
            j["category"] = "Administration"
        elif "architect" in title_lower:
            j["category"] = "Architecture"
        elif any(x in title_lower for x in ["consultant", "consulting"]):
            j["category"] = "Consultancy"
        elif "implementation" in title_lower:
            j["category"] = "Implementation"
        else:
            j["category"] = "General"

        # 2. Archiving Logic (30 days)
        try:
            # Handle various date formats (iso or simple strings)
            p_str = j.get("posted", "")
            if "T" in p_str:
                posted_dt = datetime.datetime.fromisoformat(p_str.split(".")[0].replace("Z", ""))
            else:
                posted_dt = datetime.datetime.strptime(p_str[:10], "%Y-%m-%d")
            
            if posted_dt < thirty_days_ago:
                j["status"] = "archived"
            else:
                j["status"] = "active"
        except Exception:
            # If we can't parse the date, assume it's active if it was just fetched
            j["status"] = j.get("status", "active")

        processed_jobs.append(j)

    final_jobs = sorted(
        processed_jobs, key=lambda j: j.get("posted", ""), reverse=True
    )

    output = {
        "updated_at": now.isoformat() + "Z",
        "count": len(final_jobs),
        "jobs": final_jobs,
    }

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved {len(final_jobs)} total jobs to {DATA_FILE}")


if __name__ == "__main__":
    main()
