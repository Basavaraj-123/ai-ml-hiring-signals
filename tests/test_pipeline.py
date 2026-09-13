"""Offline verification of the parse -> enrich -> signal pipeline."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ats import ASHBY, GREENHOUSE, LEVER, board_url, extract_jobs  # noqa: E402
from src.enrich import (  # noqa: E402
    classify_function, classify_seniority, detect_region, detect_remote,
    detect_tech_tags, enrich, parse_salary,
)
from src.registry import load_seed, select_companies, slug_variants  # noqa: E402
from src.signals import company_key, diff_company, load_state, prune_state  # noqa: E402
from tests.fixtures import ASHBY_PAYLOAD, GREENHOUSE_PAYLOAD, LEVER_PAYLOAD  # noqa: E402

PASS, FAIL = [], []


def check(label, condition, detail=""):
    (PASS if condition else FAIL).append(f"{label}{(' -> ' + str(detail)) if detail else ''}")


NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)

# -------------------------------------------------------------------- parsing
gh = [enrich(j) for j in extract_jobs(GREENHOUSE, GREENHOUSE_PAYLOAD)]
ab = [enrich(j) for j in extract_jobs(ASHBY, ASHBY_PAYLOAD)]
lv = [enrich(j) for j in extract_jobs(LEVER, LEVER_PAYLOAD)]

check("greenhouse parses 3 jobs", len(gh) == 3, len(gh))
check("ashby drops isListed:false", len(ab) == 2, [j["title"] for j in ab])
check("lever parses 2 jobs", len(lv) == 2, len(lv))
check("lever epoch ms -> ISO", (lv[0]["posted_at"] or "").startswith("2026-"), lv[0]["posted_at"])
check("greenhouse tz offset -> UTC",
      (gh[0]["updated_at"] or "").endswith("+00:00"), gh[0]["updated_at"])
check("urls preserved", all(j["url"] for j in gh + ab + lv))

# ----------------------------------------------------------------- functions
check("AE -> sales", gh[0]["function"] == "sales", gh[0]["function"])
check("Research Engineer -> ml_research", gh[1]["function"] == "ml_research", gh[1]["function"])
check("ML Intern -> ml_engineering", gh[2]["function"] == "ml_engineering", gh[2]["function"])
check("TPM -> product", ab[0]["function"] == "product", ab[0]["function"])
check("Developer Advocate -> devrel", ab[1]["function"] == "devrel", ab[1]["function"])
check("Staff SWE -> engineering", lv[0]["function"] == "engineering", lv[0]["function"])
check("Head of RevOps -> sales", lv[1]["function"] == "sales", lv[1]["function"])
check("standalone: security", classify_function("Senior Security Engineer") == "security")
check("standalone: infrastructure", classify_function("SRE, GPU Fleet") == "infrastructure")
check("standalone: recruiting", classify_function("Technical Recruiter") == "recruiting")
check("standalone: legal", classify_function("Associate General Counsel") == "legal")
check("dept fallback", classify_function("Analyst", "Data") == "data")

# ---------------------------------------------------------------- seniority
check("senior detected", gh[1]["seniority"] == "senior", gh[1]["seniority"])
check("intern detected", gh[2]["seniority"] == "intern", gh[2]["seniority"])
check("staff detected", lv[0]["seniority"] == "staff", lv[0]["seniority"])
check("head of -> executive", lv[1]["seniority"] == "executive", lv[1]["seniority"])
check("vp -> executive", classify_seniority("VP of Engineering") == "executive")
check("principal", classify_seniority("Principal Engineer") == "principal")
check("plain title -> mid", classify_seniority("Software Engineer") == "mid")

# ------------------------------------------------------------------ salary
check("greenhouse metadata salary", gh[0]["salary_max"] == 280000, gh[0].get("salary_max"))
check("salary from description", gh[1]["salary_min"] == 340000, gh[1].get("salary_min"))
check("ashby K-notation", ab[0]["salary_min"] == 257000, ab[0].get("salary_min"))
check("ashby K max", ab[0]["salary_max"] == 335000, ab[0].get("salary_max"))
check("euro currency", lv[1].get("salary_currency") == "EUR", lv[1].get("salary_currency"))
check("midpoint computed", gh[0]["salary_midpoint"] == 250000, gh[0].get("salary_midpoint"))
check("no salary -> no keys", "salary_min" not in ab[1], ab[1].get("salary_min"))
check("absurd numbers rejected", parse_salary("$5 - $9") == {})
check("reversed range rejected", parse_salary("$200,000 - $100,000") == {})

# ---------------------------------------------------------- remote / region
check("hybrid from description", gh[0]["workplace"] == "hybrid", gh[0]["workplace"])
check("remote from location", gh[2]["workplace"] == "remote", gh[2]["workplace"])
check("ashby isRemote flag", ab[1]["workplace"] == "remote", ab[1]["workplace"])
check("lever hybrid", lv[0]["workplace"] == "hybrid", lv[0]["workplace"])
check("region US", gh[1]["region"] == "US", gh[1]["region"])
check("region IN", lv[0]["region"] == "IN", lv[0]["region"])
check("region EU", lv[1]["region"] == "EU", lv[1]["region"])
check("region UK", detect_region("London, United Kingdom") == "UK")
check("unknown location -> None", detect_region("Mars Colony 7") is None)

# -------------------------------------------------------------- tech tags
check("cuda+vllm tagged", {"cuda", "vllm"} <= set(gh[2]["tech_tags"]), gh[2]["tech_tags"])
check("pytorch+jax tagged", {"pytorch", "jax"} <= set(gh[1]["tech_tags"]), gh[1]["tech_tags"])
check("agents tagged", "agents" in ab[1]["tech_tags"], ab[1]["tech_tags"])
check("kubernetes tagged", "kubernetes" in ab[0]["tech_tags"], ab[0]["tech_tags"])
check("tags sorted", gh[1]["tech_tags"] == sorted(gh[1]["tech_tags"]))

# ------------------------------------------------------------ html stripped
check("html stripped from excerpt", "<p>" not in gh[0]["description_excerpt"])
check("raw description dropped", "description" not in gh[0])
check("excerpt capped", all(len(j["description_excerpt"]) <= 600 for j in gh + ab + lv))

# ------------------------------------------------------------------ signals
# Run 1 (cold start): nothing should be flagged new.
closed1, sig1, rec1 = diff_company(None, [dict(j) for j in gh], now=NOW)
check("cold start: is_first_observation", sig1["is_first_observation"])
check("cold start: no new roles", sig1["new_roles_this_run"] == 0, sig1["new_roles_this_run"])
check("cold start: no false GTM signal", sig1["gtm_signal"] is False)
check("cold start: open_roles counted", sig1["open_roles"] == 3)
check("functions remembered", set(rec1["functions_ever"]) ==
      {"sales", "ml_research", "ml_engineering"}, rec1["functions_ever"])

# Run 2: one role closes, one brand-new DevRel role appears.
run2 = [dict(j) for j in gh[:2]] + [dict(ab[1])]
LATER = NOW + timedelta(days=7)
closed2, sig2, rec2 = diff_company(rec1, run2, now=LATER)

check("closed role detected", len(closed2) == 1, [c["title"] for c in closed2])
check("closed role is the intern", closed2[0]["title"].startswith("Machine Learning Intern"))
check("closed role days_open", closed2[0]["days_open"] == 7, closed2[0]["days_open"])
check("new role detected", sig2["new_roles_this_run"] == 1, sig2["new_roles_this_run"])
check("existing roles not flagged new", not any(j["is_new"] for j in run2[:2]))
check("new role flagged", run2[2]["is_new"] is True)
check("first devrel hire flagged", run2[2]["is_first_hire_for_function"] is True)
check("signal note written", "First-ever devrel" in (run2[2].get("signal_note") or ""),
      run2[2].get("signal_note"))
check("gtm_signal raised", sig2["gtm_signal"] is True)
check("first_time_functions", sig2["first_time_functions"] == ["devrel"],
      sig2["first_time_functions"])
check("net change 30d", sig2["net_change_30d"] == 0, sig2["net_change_30d"])
check("roles_by_function present", sig2["roles_by_function"].get("devrel") == 1)
check("first_seen_at carried over",
      run2[0]["first_seen_at"] == NOW.isoformat(), run2[0]["first_seen_at"])
check("days_open uses posted_at", run2[1]["days_open"] > 30, run2[1]["days_open"])

# Run 3: board shrinks -> contracting trend.
run3 = [dict(gh[0])]
_, sig3, _ = diff_company(rec2, run3, now=LATER + timedelta(days=3))
check("contracting trend", sig3["hiring_trend"] == "contracting", sig3["hiring_trend"])
check("net change negative", sig3["net_change_30d"] == -2, sig3["net_change_30d"])
check("no repeat first-hire flag", sig3["first_time_functions"] == [])

# ---------------------------------------------------------------- state mgmt
check("bad state -> empty", load_state({"version": 999})["companies"] == {})
check("none state -> empty", load_state(None)["companies"] == {})
stale = {"version": 1, "companies": {
    "greenhouse:old": {"last_seen_at": "2020-01-01T00:00:00+00:00"},
    "greenhouse:fresh": {"last_seen_at": NOW.isoformat()},
}}
check("stale pruned", list(prune_state(stale, now=NOW)["companies"]) == ["greenhouse:fresh"])
check("history capped at 24", len(rec2["history"]) <= 24)
check("company_key format", company_key("greenhouse", "anthropic") == "greenhouse:anthropic")

# ------------------------------------------------------------------ registry
seed = load_seed()
check("registry has 100+ companies", len(seed) >= 100, len(seed))
names = [c["name"] for c in seed]
check("no duplicate companies", len(names) == len(set(names)))
check("every company has category", all(c.get("category") for c in seed))
check("every company has stage", all(c.get("stage") for c in seed))
SCHEMA_PATH = Path(__file__).resolve().parents[1] / ".actor" / "input_schema.json"
schema_cats = set(json.loads(
    SCHEMA_PATH.read_text(encoding="utf-8")
)["properties"]["categories"]["items"]["enum"]) - {"all"}
check("seed categories match input schema",
      {c["category"] for c in seed} <= schema_cats,
      {c["category"] for c in seed} - schema_cats)

check("category filter works",
      all(c["category"] == "vector_db"
          for c in select_companies(categories_filter=["vector_db"])))
check("stage filter works",
      all(c["stage"] == "early" for c in select_companies(stages_filter=["early"])))
check("'all' is a no-op", len(select_companies(categories_filter=["all"])) == len(seed))
check("limit respected", len(select_companies(limit=5)) == 5)
extra = select_companies(categories_filter=["vector_db"],
                         extra_companies=[{"name": "My Startup"}])
check("extraCompanies appended", extra[-1]["name"] == "My Startup")
check("extra defaults category", extra[-1]["category"] == "custom")
capped = select_companies(limit=2, extra_companies=[{"name": "My Startup"}])
check("limit caps registry only", len(capped) == 3, len(capped))
check("extras survive the limit", capped[-1]["name"] == "My Startup")
dupe = select_companies(categories_filter=["vector_db"],
                        extra_companies=[{"name": "Pinecone"}, {"name": "Pinecone"}])
check("extras dedupe against registry",
      [c["name"] for c in dupe].count("Pinecone") == 1)

v = slug_variants("Cursor (Anysphere)")
check("variant: parenthetical", "anysphere" in v, v)
v2 = slug_variants("Scale AI", "scaleai")
check("variant: hint first", v2[0] == "scaleai", v2)
check("variant: suffix stripped", "scale" in v2, v2)
check("variant: hyphenated", "black-forest-labs" in slug_variants("Black Forest Labs"))
check("variants deduped", len(v2) == len(set(v2)))

# ---------------------------------------------------------------- board urls
check("gh url", board_url(GREENHOUSE, "anthropic") ==
      "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs?content=true")
check("lever url", board_url(LEVER, "acme") ==
      "https://api.lever.co/v0/postings/acme?mode=json")
check("ashby url", board_url(ASHBY, "openai") ==
      "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true")
check("probe url skips content", "content=true" not in board_url(GREENHOUSE, "x", with_content=False))

# -------------------------------------------------------------------- report
print(f"\n  PASSED {len(PASS)}   FAILED {len(FAIL)}\n")
for f in FAIL:
    print(f"  FAIL  {f}")
if not FAIL:
    print("  All pipeline assertions green.\n")
sys.exit(1 if FAIL else 0)
