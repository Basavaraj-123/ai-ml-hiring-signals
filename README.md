# AI/ML Hiring Signals — Track Who AI Companies Are Hiring

Monitor open roles across **98 verified AI and machine-learning companies** — foundation-model labs, inference providers, AI chip startups, agent tooling, vector databases, AI coding tools and applied-AI companies — and get back more than a job list: **hiring signals**.

Every run tells you which roles are **new since last time**, which **closed**, whether a company is **expanding or contracting**, and — the one that matters most — when a company posts its **first-ever role in a function it has never hired for**.

> A research lab posting its first Account Executive is a go-to-market signal.
> A dev-tools company posting its first Developer Advocate is an adoption push.
> A startup posting its first General Counsel is preparing for enterprise deals.
>
> None of that is visible in a flat list of job postings. This Actor surfaces it.

---

## Why this instead of a generic ATS scraper

Most job scrapers ask *you* to supply the company slugs. That's the hard part of the job, handed back to the buyer.

This Actor ships **the company universe**. You pick `foundation_model` or `ai_agents` or `vector_db` and it already knows who's in that category and where their board lives — including auto-detecting the ATS for companies you add yourself.

| | Generic ATS scraper | This Actor |
|---|---|---|
| Company list | You supply slugs | 98 curated AI/ML companies, categorised |
| Unknown company | You research the ATS | Auto-detected and cached |
| Output | Job listings | Listings **+ hiring deltas & signals** |
| Classification | Raw ATS fields | Function, seniority, region, workplace, salary band, AI tech tags |
| Repeat runs | Same data again | Diff against last run |

---

## What you get

### Job records (`outputMode: "jobs"`)

```json
{
  "company": "Anthropic",
  "company_category": "foundation_model",
  "company_stage": "late",
  "title": "Senior Research Engineer, Interpretability",
  "function": "ml_research",
  "seniority": "senior",
  "workplace": "onsite",
  "region": "US",
  "location_raw": "San Francisco, CA",
  "salary_min": 340000,
  "salary_max": 505000,
  "salary_currency": "USD",
  "salary_midpoint": 422500,
  "tech_tags": ["jax", "pytorch"],
  "is_new": true,
  "is_first_hire_for_function": false,
  "days_open": 3,
  "posted_at": "2026-09-10T14:00:00+00:00",
  "url": "https://job-boards.greenhouse.io/anthropic/jobs/4461450009",
  "ats": "greenhouse",
  "ats_slug": "anthropic"
}
```

### Company signals (`outputMode: "signals"`)

```json
{
  "record_type": "company_signal",
  "company": "Anthropic",
  "open_roles": 214,
  "new_roles_this_run": 6,
  "closed_roles_this_run": 3,
  "net_change_30d": 18,
  "hiring_trend": "expanding",
  "gtm_signal": true,
  "first_time_functions": ["devrel"],
  "new_role_titles": ["Developer Advocate, Claude Code"],
  "roles_by_function": {"ml_research": 61, "engineering": 44, "sales": 22},
  "closed_roles": [{"title": "ML Intern, Inference", "days_open": 41}]
}
```

---

## Who uses this

- **Sales & GTM teams** — hiring is the cleanest public buying signal. A company opening its first DevRel or RevOps role has budget and a new motion. `onlySignalCompanies: true` on a daily schedule gives you a lead feed.
- **Recruiters & talent partners** — see which AI companies are actively expanding, in which functions, in which regions, at what comp.
- **VCs & analysts** — headcount velocity by category is a leading indicator. Track `net_change_30d` across `foundation_model` vs `ai_agents` over months.
- **Job seekers & job boards** — filter 98 AI companies by function, seniority, region, remote status and salary floor in one run.
- **Competitive intelligence** — watch a rival's `roles_by_function` shift and you can see their roadmap before they announce it.

---

## Input

| Field | Type | Default | Notes |
|---|---|---|---|
| `categories` | array | `["all"]` | `foundation_model`, `ai_infrastructure`, `ai_chips`, `ai_devtools`, `ai_agents`, `ai_coding`, `ai_data`, `ai_search`, `vector_db`, `ai_application`, `ai_platform`, `ai_safety`, `ai_robotics` |
| `stages` | array | `["all"]` | `early`, `growth`, `late`, `public`, `nonprofit` |
| `outputMode` | string | `jobs` | `jobs`, `signals`, `both` |
| `functions` | array | all | `ml_research`, `ml_engineering`, `engineering`, `infrastructure`, `data`, `devrel`, `security`, `product`, `design`, `sales`, `marketing`, `recruiting`, `finance`, `legal`, `operations`, `support` |
| `seniorities` | array | all | `intern` → `executive` |
| `regions` | array | all | `us`, `uk`, `eu`, `in`, `apac`, `ca`, `latam`, `mea` |
| `workplace` | string | `any` | `remote`, `hybrid`, `onsite` |
| `titleKeywords` | array | — | Match if ANY keyword appears in title or description |
| `excludeKeywords` | array | — | Drop if ANY keyword appears |
| `onlyNewRoles` | bool | `false` | Needs ≥1 previous run |
| `onlySignalCompanies` | bool | `false` | Skip unchanged boards — ideal for daily schedules |
| `minSalary` | int | — | Filters on the top of the posted band |
| `maxCompanies` | int | `60` | Caps the registry slice (your own `extraCompanies` are never dropped) |
| `extraCompanies` | array | `[]` | `[{"name":"Acme AI"}]` — ATS and slug auto-detected |

### Example: daily GTM lead feed

```json
{
  "categories": ["foundation_model", "ai_agents", "ai_coding"],
  "outputMode": "signals",
  "onlySignalCompanies": true
}
```

### Example: senior remote ML roles paying $250k+

```json
{
  "categories": ["all"],
  "functions": ["ml_research", "ml_engineering"],
  "seniorities": ["senior", "staff", "principal"],
  "workplace": "remote",
  "minSalary": 250000
}
```

---

## How it works

Three public, documented job-board APIs — Greenhouse, Lever and Ashby — that companies publish specifically so their listings can be embedded elsewhere. No login, no browser, no proxies, no anti-bot evasion. A full 60-company run is a few hundred JSON requests and finishes in well under a minute at 256 MB.

Unknown companies go through a slug resolver that probes candidate slugs across all three ATSes and caches the result, so the registry heals itself over time.

Cross-run state lives in the Actor's key-value store. **The first run is a baseline** — it deliberately reports zero new roles rather than flagging all 800 as new. Signals start on run two.

### Limits, stated plainly

- Companies on Workday, SmartRecruiters or a custom careers page aren't covered. They're skipped and counted in `RUN_SUMMARY`.
- Salary is only as good as what the company publishes. Ashby exposes it most reliably; Greenhouse sometimes via metadata; Lever rarely.
- `region` and `workplace` are inferred from location and description text. Good, not perfect.
- Function and seniority are rule-based classifiers. Expect ~90% accuracy on standard titles and misses on creative ones ("Member of Technical Staff" is mapped; "Chief Vibes Officer" is not).

---

## Development

```bash
pip install -r requirements.txt

python -m tests.test_pipeline     # 101 offline assertions on parsing/enrichment/signals
python -m tests.smoke_run         # full Actor run against mocked ATS responses
python tools/verify_registry.py   # re-verify every company's ATS + slug (needs internet)
```

Deploy:

```bash
npm install -g apify-cli
apify login
apify push
```

---

## Cost

Pure JSON over HTTPS at 256 MB RAM — a 60-company run costs a fraction of one compute unit. Comfortably inside the Apify free tier for development and scheduled personal use.