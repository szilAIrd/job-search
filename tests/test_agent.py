#!/usr/bin/env python3
"""
Tests for the job search agent.
Run with:  python -m pytest tests/ -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from job_search_agent import (
    deduplicate,
    fetch_arbeitnow,
    fetch_jobicy,
    fetch_remotive,
    fetch_themuse,
    fetch_weworkremotely,
    normalise,
    passes_filters,
    render_markdown,
    score_job,
    strip_html,
)

# ---------------------------------------------------------------------------
# strip_html / normalise
# ---------------------------------------------------------------------------

def test_strip_html_removes_tags():
    assert "<p>" not in strip_html("<p>Hello <b>world</b></p>")
    assert "Hello" in strip_html("<p>Hello <b>world</b></p>")


def test_normalise_lowercases():
    assert normalise("Python Developer") == "python developer"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "required_skills": ["Python"],
    "keywords": ["software engineer"],
    "preferred_skills": ["Docker"],
    "job_types": ["full-time"],
}

GOOD_JOB = {
    "title": "Senior Software Engineer",
    "description": "We need a Python developer who knows Docker",
    "job_type": "full-time",
    "url": "https://example.com/job/1",
}

BAD_JOB_NO_SKILL = {
    "title": "Senior Java Engineer",
    "description": "We need a Java developer",
    "job_type": "full-time",
    "url": "https://example.com/job/2",
}

BAD_JOB_TYPE = {
    "title": "Senior Software Engineer",
    "description": "We need a Python developer",
    "job_type": "internship",
    "url": "https://example.com/job/3",
}


def test_passes_filters_good_job():
    assert passes_filters(GOOD_JOB, BASE_CONFIG) is True


def test_passes_filters_missing_required_skill():
    assert passes_filters(BAD_JOB_NO_SKILL, BASE_CONFIG) is False


def test_passes_filters_wrong_job_type():
    assert passes_filters(BAD_JOB_TYPE, BASE_CONFIG) is False


def test_passes_filters_no_job_types_configured():
    config = {**BASE_CONFIG, "job_types": []}
    # Should not reject based on job_type when list is empty
    assert passes_filters(BAD_JOB_TYPE, config) is True


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_score_job_higher_for_keyword_in_title():
    job_title_match = {**GOOD_JOB, "title": "software engineer Python"}
    job_desc_match = {**GOOD_JOB, "title": "Generic Role", "description": "software engineer Python"}
    assert score_job(job_title_match, BASE_CONFIG) > score_job(job_desc_match, BASE_CONFIG)


def test_score_job_preferred_skills_add_score():
    job_with = {**GOOD_JOB, "description": "Python developer with Docker and Kubernetes"}
    job_without = {**GOOD_JOB, "description": "Python developer"}
    assert score_job(job_with, BASE_CONFIG) > score_job(job_without, BASE_CONFIG)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_deduplicate_removes_same_url():
    jobs = [GOOD_JOB, GOOD_JOB.copy(), BAD_JOB_TYPE]
    result = deduplicate(jobs)
    assert len(result) == 2


def test_deduplicate_keeps_different_urls():
    j1 = {**GOOD_JOB, "url": "https://example.com/1"}
    j2 = {**GOOD_JOB, "url": "https://example.com/2"}
    assert len(deduplicate([j1, j2])) == 2


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def test_render_markdown_contains_job_title():
    jobs = [{**GOOD_JOB, "_score": 25}]
    md = render_markdown(jobs, "2026-01-01", ["remotive"])
    assert "Senior Software Engineer" in md
    assert "2026-01-01" in md


def test_render_markdown_empty_jobs():
    md = render_markdown([], "2026-01-01", ["remotive"])
    assert "0" in md


# ---------------------------------------------------------------------------
# Source fetchers (mocked)
# ---------------------------------------------------------------------------

REMOTIVE_RESPONSE = {
    "jobs": [
        {
            "title": "Python Engineer",
            "company_name": "Acme Corp",
            "candidate_required_location": "Remote",
            "url": "https://remotive.com/job/1",
            "description": "Python FastAPI",
            "job_type": "full_time",
            "publication_date": "2026-01-01",
        }
    ]
}

ARBEITNOW_RESPONSE = {
    "data": [
        {
            "title": "Python Backend Developer",
            "company_name": "Beta GmbH",
            "location": "Berlin",
            "url": "https://arbeitnow.com/job/2",
            "description": "Python Django developer needed",
            "employment_type_label": "Full Time",
            "created_at": "2026-01-01",
        }
    ]
}


def _mock_get(url, **kwargs):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if "remotive" in url:
        resp.json.return_value = REMOTIVE_RESPONSE
    elif "arbeitnow" in url:
        resp.json.return_value = ARBEITNOW_RESPONSE
    else:
        resp.json.return_value = {}
    return resp


JOBICY_RESPONSE = {
    "jobs": [
        {
            "jobTitle": "Python Remote Engineer",
            "companyName": "Gamma Inc",
            "jobGeo": "Worldwide",
            "url": "https://jobicy.com/job/3",
            "jobDescription": "Python FastAPI remote position",
            "jobType": "full-time",
            "pubDate": "2026-01-01",
        }
    ]
}

WWR_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:wwr="https://weworkremotely.com">
  <channel>
    <item>
      <title>Senior Python Engineer at Delta Ltd</title>
      <link>https://weworkremotely.com/job/4</link>
      <description>Python backend engineer needed</description>
      <pubDate>Mon, 01 Jan 2026 00:00:00 +0000</pubDate>
      <wwr:company>Delta Ltd</wwr:company>
      <wwr:region>Worldwide</wwr:region>
    </item>
  </channel>
</rss>
"""

THEMUSE_RESPONSE = {
    "results": [
        {
            "name": "Python Software Engineer",
            "company": {"name": "Epsilon Co"},
            "locations": [{"name": "Remote"}],
            "levels": [{"name": "Mid Level"}],
            "refs": {"landing_page": "https://themuse.com/job/5"},
            "contents": "We are looking for a Python developer",
            "publication_date": "2026-01-01",
        }
    ]
}


def _mock_get_extended(url, **kwargs):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if "remotive" in url:
        resp.json.return_value = REMOTIVE_RESPONSE
    elif "arbeitnow" in url:
        resp.json.return_value = ARBEITNOW_RESPONSE
    elif "jobicy" in url:
        resp.json.return_value = JOBICY_RESPONSE
    elif "weworkremotely" in url:
        resp.text = WWR_RSS
    elif "themuse" in url:
        resp.json.return_value = THEMUSE_RESPONSE
    else:
        resp.json.return_value = {}
    return resp


def test_fetch_remotive():
    config = {"keywords": ["Python"]}
    with patch("job_search_agent.requests.get", side_effect=_mock_get):
        jobs = fetch_remotive(config)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Python Engineer"
    assert jobs[0]["source"] == "remotive"


def test_fetch_arbeitnow():
    config = {"keywords": ["Python"]}
    with patch("job_search_agent.requests.get", side_effect=_mock_get):
        jobs = fetch_arbeitnow(config)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Python Backend Developer"
    assert jobs[0]["source"] == "arbeitnow"


def test_fetch_jobicy():
    config = {"keywords": ["Python"]}
    with patch("job_search_agent.requests.get", side_effect=_mock_get_extended):
        jobs = fetch_jobicy(config)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Python Remote Engineer"
    assert jobs[0]["source"] == "jobicy"


def test_fetch_weworkremotely():
    config = {"keywords": ["python"]}
    with patch("job_search_agent.requests.get", side_effect=_mock_get_extended):
        jobs = fetch_weworkremotely(config)
    assert any(j["source"] == "weworkremotely" for j in jobs)
    assert any("Python" in j["title"] for j in jobs)


def test_fetch_themuse():
    config = {"keywords": ["Python"]}
    with patch("job_search_agent.requests.get", side_effect=_mock_get_extended):
        jobs = fetch_themuse(config)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Python Software Engineer"
    assert jobs[0]["source"] == "themuse"
