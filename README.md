# job-search

A **daily job search agent** that automatically fetches job listings from free public job APIs, filters them against your personal requirements, scores/ranks them by relevance, and commits the results to this repository every morning.

---

## How it works

```
requirements.yaml  ──►  job_search_agent.py  ──►  results/YYYY-MM-DD.md
                                                   results/YYYY-MM-DD.json
                                                   results/latest.md
```

1. The GitHub Actions workflow ([`.github/workflows/daily_job_search.yml`](.github/workflows/daily_job_search.yml)) triggers every day at **07:00 UTC**.
2. The agent reads [`requirements.yaml`](requirements.yaml) to load your search preferences.
3. It fetches jobs from configured sources (currently **Remotive** and **Arbeitnow** – both free, no API key needed).
4. Jobs are **filtered** (required skills, job type), **deduplicated**, and **scored** by keyword/skill relevance.
5. Results are written to `results/latest.md` (and a date-stamped file) and committed back to the repository.

---

## Customising your requirements

Edit [`requirements.yaml`](requirements.yaml):

| Field | Purpose |
|---|---|
| `keywords` | Search terms – any match triggers a fetch |
| `locations` | Preferred locations (informational for now) |
| `required_skills` | **All** must appear in the job posting; failing jobs are dropped |
| `preferred_skills` | Increase the job's relevance score |
| `job_types` | `full-time`, `contract`, `part-time`, etc. |
| `sources` | Which APIs to query (`remotive`, `arbeitnow`) |

---

## Running locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Edit requirements.yaml

# 3. Run the agent
python job_search_agent.py

# Results written to results/
```

---

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## Project structure

```
.
├── job_search_agent.py         # Main agent script
├── requirements.yaml           # Your job search preferences
├── requirements.txt            # Python dependencies
├── tests/
│   └── test_agent.py           # Unit tests
├── results/
│   ├── latest.md               # Most recent search results
│   ├── YYYY-MM-DD.md           # Date-stamped Markdown report
│   └── YYYY-MM-DD.json         # Date-stamped JSON (no description bodies)
└── .github/workflows/
    └── daily_job_search.yml    # Scheduled GitHub Actions workflow
```
