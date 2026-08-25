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


SOURCE_FETCHERS = {
    "remotive": fetch_remotive,
    "arbeitnow": fetch_arbeitnow,
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
    desired_types = [jt.lower() for jt in config.get("job_types", [])]
    if desired_types:
        job_type_norm = job.get("job_type", "").lower()
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
