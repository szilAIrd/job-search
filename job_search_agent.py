#!/usr/bin/env python3
"""
Daily Job Search Agent
======================
Fetches job listings from free public APIs, filters them against
requirements.yaml, scores/ranks them, and writes results to
results/YYYY-MM-DD.md and results/latest.md.
"""

import json
import logging
import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import xml.etree.ElementTree as ET

import requests
import yaml

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
REQUIREMENTS_FILE = REPO_ROOT / "requirements.yaml"
RESULTS_DIR = REPO_ROOT / "results"

# ---------------------------------------------------------------------------
# Job source implementations
# ---------------------------------------------------------------------------


def fetch_remotive(config: dict) -> list[dict]:
    """Fetch jobs from the Remotive public API (https://remotive.com/api/remote-jobs)."""
    jobs: list[dict] = []
    for keyword in config.get("keywords", []):
        url = "https://remotive.com/api/remote-jobs"
        params = {"search": keyword, "limit": 50}
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("jobs", []):
                jobs.append(
                    {
                        "title": item.get("title", ""),
                        "company": item.get("company_name", ""),
                        "location": item.get("candidate_required_location", "Remote"),
                        "url": item.get("url", ""),
                        "description": item.get("description", ""),
                        "job_type": item.get("job_type", ""),
                        "published_at": item.get("publication_date", ""),
                        "source": "remotive",
                    }
                )
        except requests.RequestException as exc:
            log.warning("Remotive fetch failed for keyword '%s': %s", keyword, exc)
    return jobs


def fetch_arbeitnow(config: dict) -> list[dict]:
    """Fetch jobs from the Arbeitnow public API (https://www.arbeitnow.com/api/job-board-api)."""
    jobs: list[dict] = []
    url = "https://www.arbeitnow.com/api/job-board-api"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        keywords = [k.lower() for k in config.get("keywords", [])]
        for item in data.get("data", []):
            title = item.get("title", "").lower()
            description = item.get("description", "").lower()
            if any(kw in title or kw in description for kw in keywords):
                jobs.append(
                    {
                        "title": item.get("title", ""),
                        "company": item.get("company_name", ""),
                        "location": item.get("location", ""),
                        "url": item.get("url", ""),
                        "description": item.get("description", ""),
                        "job_type": "full-time" if item.get("employment_type_label", "").lower() == "full time" else item.get("employment_type_label", "").lower(),
                        "published_at": item.get("created_at", ""),
                        "source": "arbeitnow",
                    }
                )
    except requests.RequestException as exc:
        log.warning("Arbeitnow fetch failed: %s", exc)
    return jobs


def fetch_jobicy(config: dict) -> list[dict]:
    """Fetch remote jobs from the Jobicy public API (https://jobicy.com/api/v2/remote-jobs).

    No API key required.  Supports ``count`` (1-50) and ``tag`` query params.
    """
    jobs: list[dict] = []
    for keyword in config.get("keywords", []):
        url = "https://jobicy.com/api/v2/remote-jobs"
        params = {"count": 50, "tag": keyword}
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("jobs", []):
                jobs.append(
                    {
                        "title": item.get("jobTitle", ""),
                        "company": item.get("companyName", ""),
                        "location": item.get("jobGeo", "Remote"),
                        "url": item.get("url", ""),
                        "description": item.get("jobDescription", ""),
                        "job_type": item.get("jobType", ""),
                        "published_at": item.get("pubDate", ""),
                        "source": "jobicy",
                    }
                )
        except requests.RequestException as exc:
            log.warning("Jobicy fetch failed for keyword '%s': %s", keyword, exc)
    return jobs


def fetch_weworkremotely(config: dict) -> list[dict]:
    """Fetch remote jobs from We Work Remotely RSS feeds.

    WWR provides per-category RSS feeds at https://weworkremotely.com.
    The programming/dev category is used for tech roles.
    """
    jobs: list[dict] = []
    feed_urls = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
    ]
    keywords = [k.lower() for k in config.get("keywords", [])]
    for feed_url in feed_urls:
        try:
            resp = requests.get(feed_url, timeout=20)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
            for item in root.iter("item"):
                title = item.findtext("title") or ""
                description = item.findtext("description") or ""
                content = item.find("content:encoded", ns)
                full_text = (content.text if content is not None else "") or description
                title_lc = title.lower()
                full_text_lc = full_text.lower()
                if not any(kw in title_lc or kw in full_text_lc for kw in keywords):
                    continue
                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate") or ""
                region = item.findtext("{https://weworkremotely.com}region") or "Remote"
                jobs.append(
                    {
                        "title": title,
                        "company": item.findtext("{https://weworkremotely.com}company") or "",
                        "location": region,
                        "url": link,
                        "description": full_text,
                        "job_type": "full-time",
                        "published_at": pub_date,
                        "source": "weworkremotely",
                    }
                )
        except (requests.RequestException, ET.ParseError) as exc:
            log.warning("We Work Remotely fetch failed for %s: %s", feed_url, exc)
    return jobs


def fetch_themuse(config: dict) -> list[dict]:
    """Fetch jobs from The Muse public API (https://www.themuse.com/api/public/jobs).

    No API key required for basic use.
    """
    jobs: list[dict] = []
    for keyword in config.get("keywords", []):
        url = "https://www.themuse.com/api/public/jobs"
        params = {"category": keyword, "page": 1, "descending": "true"}
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("results", []):
                locations = item.get("locations", [])
                location = locations[0].get("name", "Remote") if locations else "Remote"
                levels = item.get("levels", [])
                job_type = levels[0].get("name", "") if levels else ""
                refs = item.get("refs", {})
                link = refs.get("landing_page", "")
                # Build description from contents blocks
                contents = item.get("contents", "")
                jobs.append(
                    {
                        "title": item.get("name", ""),
                        "company": item.get("company", {}).get("name", ""),
                        "location": location,
                        "url": link,
                        "description": contents,
                        "job_type": job_type.lower(),
                        "published_at": item.get("publication_date", ""),
                        "source": "themuse",
                    }
                )
        except requests.RequestException as exc:
            log.warning("The Muse fetch failed for keyword '%s': %s", keyword, exc)
    return jobs


SOURCE_FETCHERS = {
    "remotive": fetch_remotive,
    "arbeitnow": fetch_arbeitnow,
    "jobicy": fetch_jobicy,
    "weworkremotely": fetch_weworkremotely,
    "themuse": fetch_themuse,
}

# ---------------------------------------------------------------------------
# Filtering & scoring
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub(" ", text)


def normalise(text: str) -> str:
    return strip_html(text).lower()


def passes_filters(job: dict, config: dict) -> bool:
    """Return True if the job satisfies all hard requirements."""
    desc_norm = normalise(job.get("description", ""))
    title_norm = normalise(job.get("title", ""))
    combined = f"{title_norm} {desc_norm}"

    # Required skills – ALL must appear somewhere in title + description
    for skill in config.get("required_skills", []):
        if skill.lower() not in combined:
            log.debug("Job '%s' rejected – missing required skill '%s'", job["title"], skill)
            return False

    # Job type filter (if configured)
    desired_types = [str(jt).lower() for jt in config.get("job_types", []) if jt]
    if desired_types:
        job_type_value = job.get("job_type", "")
        if isinstance(job_type_value, list):
            job_type_norm = " ".join(str(part) for part in job_type_value if part is not None).lower()
        else:
            job_type_norm = str(job_type_value or "").lower()
        if not any(dt in job_type_norm for dt in desired_types):
            log.debug("Job '%s' rejected – job_type '%s' not in %s", job["title"], job.get("job_type"), desired_types)
            return False

    return True


def score_job(job: dict, config: dict) -> int:
    """Return a relevance score; higher = better match."""
    combined = normalise(f"{job.get('title', '')} {job.get('description', '')}")
    score = 0

    # Keyword in title = extra weight
    for kw in config.get("keywords", []):
        if kw.lower() in normalise(job.get("title", "")):
            score += 10
        elif kw.lower() in combined:
            score += 3

    # Preferred skills
    for skill in config.get("preferred_skills", []):
        if skill.lower() in combined:
            score += 5

    return score


def deduplicate(jobs: list[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for job in jobs:
        url = job.get("url", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(job)
    return unique


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

MARKDOWN_TEMPLATE = """\
# Job Search Results – {date}

> Generated by the daily job search agent.  
> Requirements: [`requirements.yaml`](../requirements.yaml)

**{count}** matching jobs found across {sources}.

---

{job_sections}

---
*Last updated: {timestamp}*
"""

JOB_SECTION_TEMPLATE = """\
## {rank}. {title} @ {company}

| Field | Value |
|---|---|
| **Location** | {location} |
| **Type** | {job_type} |
| **Source** | {source} |
| **Posted** | {published_at} |
| **Score** | {score} |
| **URL** | [{url}]({url}) |

"""


def render_markdown(jobs: list[dict], today: str, sources_used: list[str]) -> str:
    job_sections = ""
    for rank, job in enumerate(jobs, start=1):
        job_sections += JOB_SECTION_TEMPLATE.format(
            rank=rank,
            title=job["title"],
            company=job.get("company", "N/A"),
            location=job.get("location", "N/A"),
            job_type=job.get("job_type", "N/A"),
            source=job.get("source", "N/A"),
            published_at=job.get("published_at", "N/A"),
            score=job.get("_score", 0),
            url=job.get("url", ""),
        )
    return MARKDOWN_TEMPLATE.format(
        date=today,
        count=len(jobs),
        sources=", ".join(sources_used) if sources_used else "all sources",
        job_sections=job_sections,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    log.info("Loading requirements from %s", REQUIREMENTS_FILE)
    with open(REQUIREMENTS_FILE, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    sources_to_use: list[str] = config.get("sources", list(SOURCE_FETCHERS.keys()))

    # Fetch jobs from all configured sources
    raw_jobs: list[dict] = []
    for source in sources_to_use:
        fetcher = SOURCE_FETCHERS.get(source)
        if fetcher is None:
            log.warning("Unknown source '%s', skipping.", source)
            continue
        log.info("Fetching from source: %s", source)
        fetched = fetcher(config)
        log.info("  → %d jobs fetched from %s", len(fetched), source)
        raw_jobs.extend(fetched)

    log.info("Total raw jobs: %d", len(raw_jobs))

    # Deduplicate
    raw_jobs = deduplicate(raw_jobs)
    log.info("After deduplication: %d jobs", len(raw_jobs))

    # Filter
    filtered = [j for j in raw_jobs if passes_filters(j, config)]
    log.info("After filtering: %d jobs", len(filtered))

    # Score & sort
    for job in filtered:
        job["_score"] = score_job(job, config)
    filtered.sort(key=lambda j: j["_score"], reverse=True)

    # Write results
    RESULTS_DIR.mkdir(exist_ok=True)
    today = date.today().isoformat()

    md_content = render_markdown(filtered, today, sources_to_use)

    dated_path = RESULTS_DIR / f"{today}.md"
    latest_path = RESULTS_DIR / "latest.md"

    dated_path.write_text(md_content, encoding="utf-8")
    latest_path.write_text(md_content, encoding="utf-8")

    # Also save raw JSON for programmatic use
    json_path = RESULTS_DIR / f"{today}.json"
    exportable = [{k: v for k, v in job.items() if k != "description"} for job in filtered]
    json_path.write_text(json.dumps(exportable, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("Results written to %s (and latest.md)", dated_path)
    log.info("Done. %d jobs found.", len(filtered))
    return 0


if __name__ == "__main__":
    sys.exit(main())
