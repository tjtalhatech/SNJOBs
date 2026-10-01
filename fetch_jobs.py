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

    # Adzuna is per-country. Default covers the biggest English-language markets.
    raw_countries = os.environ.get("ADZUNA_COUNTRIES", "us,gb,in,ca,au").split(",")
    countries = []
    for c in raw_countries:
        c = c.strip().lower()
        if c in ["india", "in"]: countries.append("in")
        elif c in ["uk", "united kingdom", "gb"]: countries.append("gb")
        elif c in ["canada", "ca"]: countries.append("ca")
        elif c in ["australia", "au"]: countries.append("au")
        elif c in ["usa", "united states", "us"]: countries.append("us")
        elif len(c) == 2: countries.append(c)

    jobs = []
    # Query "ServiceNow" master search per country to get up to 50 fresh jobs per country with minimal API quota usage
    for country in countries:
        country = country.strip()
        if not country:
            continue
        
        # Primary search term for max coverage in 1 API call per country
        terms_to_query = ["ServiceNow"]
        
        for term in terms_to_query:
            url = (
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
                f"?app_id={app_id}&app_key={app_key}"
                f"&what={urllib.parse.quote(term)}"
                f"&results_per_page=50&sort_by=date"
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
                    "is_remote": is_remote,
                    "description": r.get("description", "")
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
            "is_remote": is_remote,
            "description": r.get("job_description", "")
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
            "is_remote": True,
            "description": r.get("description", "")
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
        # Stricter matching: require servicenow in title or tags, or prominent in description
        if "servicenow" not in title.lower() and "servicenow" not in tags and "servicenow developer" not in desc and "servicenow admin" not in desc and "servicenow consultant" not in desc:
            continue
        company = r.get("company_name", "Unknown")
        link = r.get("url", "")
        location = r.get("location", "")
        is_remote = r.get("remote", False) or any(x in title.lower() or x in location.lower() for x in ["remote", "work from home"])
        
        # Handle created_at which may be a unix timestamp integer or string
        created_val = r.get("created_at")
        posted_iso = ""
        if isinstance(created_val, (int, float)):
            posted_iso = datetime.datetime.utcfromtimestamp(created_val).isoformat() + "Z"
        elif isinstance(created_val, str) and created_val.isdigit():
            posted_iso = datetime.datetime.utcfromtimestamp(int(created_val)).isoformat() + "Z"
        elif isinstance(created_val, str):
            posted_iso = created_val

        jobs.append({
            "id": job_id(title, company, link),
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "source": "Arbeitnow",
            "posted": posted_iso,
            "salary": None,
            "country": "DE" if "germany" in location.lower() else "",
            "is_remote": is_remote,
            "description": r.get("description", "")
        })
    print(f"Arbeitnow: {len(jobs)} jobs")
    return jobs


def fetch_remotive():
    """Free, no API key required. https://remotive.com/api/remote-jobs"""
    jobs = []
    try:
        data = http_get_json(
            "https://remotive.com/api/remote-jobs?search=servicenow",
            headers={"User-Agent": "Mozilla/5.0 (servicenow-leads-bot)"},
        )
    except Exception as e:
        print(f"Remotive error: {e}")
        return jobs

    for r in data.get("jobs", []):
        title = r.get("title", "")
        desc = (r.get("description") or "")
        tags = " ".join(r.get("tags", [])).lower()
        if "servicenow" not in title.lower() and "servicenow" not in tags and "servicenow" not in desc.lower():
            continue
        company = r.get("company_name", "Unknown")
        link = r.get("url", "")
        location = r.get("candidate_required_location", "Worldwide")
        
        jobs.append({
            "id": job_id(title, company, link),
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "source": "Remotive",
            "posted": r.get("publication_date", ""),
            "salary": r.get("salary"),
            "country": "Remote",
            "is_remote": True,
            "description": desc
        })
    print(f"Remotive: {len(jobs)} jobs")
    return jobs


def fetch_jobicy():
    """Free, no API key required. https://jobicy.com/api/v2/remote-jobs"""
    jobs = []
    try:
        data = http_get_json("https://jobicy.com/api/v2/remote-jobs?count=50")
    except Exception as e:
        print(f"Jobicy error: {e}")
        return jobs

    for r in data.get("data", []):
        title = r.get("jobTitle", "")
        desc = (r.get("jobDescription") or "")
        if "servicenow" not in title.lower() and "servicenow" not in desc.lower():
            continue
        company = r.get("companyName", "Unknown")
        link = r.get("url", "")
        location = r.get("jobGeo", "Remote")
        
        jobs.append({
            "id": job_id(title, company, link),
            "title": title,
            "company": company,
            "location": location,
            "link": link,
            "source": "Jobicy",
            "posted": r.get("pubDate", ""),
            "salary": None,
            "country": "Remote",
            "is_remote": True,
            "description": desc
        })
    print(f"Jobicy: {len(jobs)} jobs")
    return jobs


def fetch_themuse():
    """Free, no API key required. https://www.themuse.com/developers/api/v2"""
    jobs = []
    try:
        data = http_get_json("https://www.themuse.com/api/public/jobs?category=Software%20Engineering&page=1")
    except Exception as e:
        print(f"TheMuse error: {e}")
        return jobs

    for r in data.get("results", []):
        title = r.get("name", "")
        desc = (r.get("contents") or "").lower()
        company = (r.get("company") or {}).get("name", "Unknown")
        if "servicenow" not in title.lower() and "servicenow" not in desc:
            continue
        
        locations = r.get("locations", [])
        loc_name = locations[0].get("name", "USA") if locations else "USA"
        is_remote = any("remote" in (l.get("name", "").lower()) for l in locations) or "remote" in title.lower()
        
        jobs.append({
            "id": job_id(title, company, r.get("refs", {}).get("landing_page", "")),
            "title": title,
            "company": company,
            "location": loc_name,
            "link": r.get("refs", {}).get("landing_page", ""),
            "source": "TheMuse",
            "posted": r.get("publication_date", ""),
            "salary": None,
            "country": "US",
            "is_remote": is_remote,
            "description": desc
        })
    print(f"TheMuse: {len(jobs)} jobs")
    return jobs


def fetch_himalayas():
    """Free, no API key required. https://himalayas.app/jobs/api"""
    jobs = []
    try:
        data = http_get_json(
            "https://himalayas.app/jobs/api?search=servicenow",
            headers={"User-Agent": "Mozilla/5.0 (servicenow-leads-bot)"}
        )
    except Exception as e:
        print(f"Himalayas error: {e}")
        return jobs

    for r in data.get("jobs", []):
        title = r.get("title", "")
        desc = (r.get("description") or "").lower()
        company = r.get("companyName", "Unknown")
        if "servicenow" not in title.lower() and "servicenow" not in desc:
            continue

        link = r.get("applicationLink") or f"https://himalayas.app/companies/{r.get('companySlug')}/jobs/{r.get('slug')}"
        loc_str = ", ".join(r.get("locationRestrictions", ["Remote"]))

        jobs.append({
            "id": job_id(title, company, link),
            "title": title,
            "company": company,
            "location": loc_str,
            "link": link,
            "source": "Himalayas",
            "posted": r.get("pubDate", ""),
            "salary": r.get("minSalary"),
            "country": "Remote",
            "is_remote": True,
            "description": desc
        })
    print(f"Himalayas: {len(jobs)} jobs")
    return jobs


def fetch_usajobs():
    """US Federal Jobs for ServiceNow (public API)"""
    jobs = []
    try:
        url = "https://data.usajobs.gov/api/search?Keyword=ServiceNow&ResultsPerPage=25"
        headers = {
            "User-Agent": "servicenow-leads-bot@github.com"
        }
        data = http_get_json(url, headers=headers)
        search_result = data.get("SearchResult", {})
        for r in search_result.get("SearchResultItems", []):
            item = r.get("MatchedObjectDescriptor", {})
            title = item.get("PositionTitle", "")
            company = item.get("OrganizationName", "US Federal Agency")
            link = item.get("PositionURI", "")
            locs = item.get("PositionLocation", [])
            location = locs[0].get("LocationName", "United States") if locs else "United States"
            rem = item.get("PositionLocationDisplay", "").lower()
            is_remote = "telework" in rem or "remote" in rem
            
            jobs.append({
                "id": job_id(title, company, link),
                "title": title,
                "company": company,
                "location": location,
                "link": link,
                "source": "USAJobs",
                "posted": item.get("PublicationStartDate", ""),
                "salary": item.get("PositionRemuneration", [{}])[0].get("MinimumRange"),
                "country": "US",
                "is_remote": is_remote,
                "description": item.get("UserArea", {}).get("Details", {}).get("MajorDuties", [""])[0] if item.get("UserArea", {}).get("Details", {}).get("MajorDuties") else ""
            })
    except Exception as e:
        print(f"USAJobs notice: {e}")
    print(f"USAJobs: {len(jobs)} jobs")
    return jobs


def is_servicenow_role(title, desc=""):
    t = (title or "").lower()
    d = (desc or "").lower()
    
    # Exclude obvious false positive domains
    disqualified = ["flight", "pilot", "aviation", "cabin crew", "sap access", "cashier", "nurse", "warehouse", "delivery driver"]
    if any(x in t for x in disqualified):
        return False

    # Positive matches in title
    if any(k in t for k in ["servicenow", "service-now", "service now", "sn dev", "sn admin", "snow dev", "snow admin", "sn architect", "sn consultant"]):
        return True

    # Technical title with explicit ServiceNow implementation in description
    is_tech_role = any(k in t for k in ["developer", "engineer", "architect", "consultant", "administrator", "admin", "lead", "manager", "specialist", "analyst"])
    if is_tech_role:
        has_sn_core = ("servicenow" in d or "service-now" in d or "gliderecord" in d or "csa" in d or "cad" in d)
        has_sn_modules = any(m in d for m in ["itsm", "itom", "itam", "hrsd", "csm", "secops", "irm", "spm", "flow designer", "service portal"])
        if has_sn_core and has_sn_modules:
            return True

    return False


def detect_agency_opportunity(title, desc=""):
    t = (title or "").lower()
    d = (desc or "").lower()
    combined = f"{t} {d}"
    
    # Multi-hire / Multiple developers needed
    multi_hire_keywords = [
        "multiple opening", "multiple position", "multiple vacancies", "multiple resources", 
        "multiple developers", "multiple consultants", "2+ developer", "3+ developer", "2-3 developer",
        "hiring multiple", "team of developers", "team expansion", "several developers",
        "ramp up", "several positions", "immediate requirements"
    ]
    if any(k in combined for k in multi_hire_keywords):
        return True, "Multi-Hire (2-3+ Devs / Team)"
        
    # C2C / Contract / Agency / Staff Augmentation
    c2c_keywords = [
        "c2c", "corp to corp", "corp-to-corp", "corp 2 corp", "1099", 
        "subcontract", "vendor", "agency", "staff augmentation", "implementation partner",
        "contractor", "hourly rate", "c2h", "contract-to-hire", "w2/c2c", "w2 or c2c"
    ]
    if any(k in combined for k in c2c_keywords):
        return True, "C2C / Agency Contract"
        
    return False, ""


def classify_servicenow_role(title, desc=""):
    t = (title or "").lower()
    d = (desc or "").lower()

    # 1. Platform Owner / Product Owner / Manager
    if any(x in t for x in ["platform owner", "product owner", "servicenow owner", "platform manager", "servicenow manager", "platform lead", "servicenow lead owner", "head of servicenow"]):
        return "Platform Owner"

    # 2. Developer (any level: jr, sr, lead, principal, staff, engineer, dev)
    if any(x in t for x in ["developer", "dev ", "dev,", "engineer", "programmer", "coder", "technical lead", "software engineer", "solution developer"]):
        return "Developer"

    # 3. Consultant (functional, technical, solution consultant, advisory)
    if any(x in t for x in ["consultant", "consulting", "advisory", "implementation"]):
        return "Consultant"

    # 4. Administrator (admin, system admin, platform admin)
    if any(x in t for x in ["admin", "administrator"]):
        return "Administrator"

    # Fallback checking description
    if "platform owner" in d or "product owner" in d or "servicenow manager" in d:
        return "Platform Owner"
    if "developer" in d or "software engineer" in d:
        return "Developer"
    if "consultant" in d:
        return "Consultant"
    if "admin" in d or "administrator" in d:
        return "Administrator"

    return "Other"


def main():
    all_jobs = (
        fetch_adzuna()
        + fetch_jsearch()
        + fetch_himalayas()
        + fetch_themuse()
        + fetch_usajobs()
        + fetch_remoteok()
        + fetch_arbeitnow()
        + fetch_remotive()
        + fetch_jobicy()
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
        
        # 0. Strict ServiceNow relevance check
        if not is_servicenow_role(j.get("title"), j.get("description")):
            continue

        # 1. Categorization
        role_cat = classify_servicenow_role(j.get("title"), j.get("description"))
        j["category"] = role_cat
        j["role_category"] = role_cat

        # 1b. Agency / Multi-Hire / Contract opportunity tagging
        is_agency, agency_badge = detect_agency_opportunity(j.get("title"), j.get("description"))
        j["is_agency_lead"] = is_agency
        j["agency_badge"] = agency_badge

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
