"""
End-to-end smoke run of the Actor with the network mocked.

Runs the real main() against an httpx MockTransport that serves the captured
ATS fixtures, so the full control flow -- input parsing, slug resolution,
concurrency, enrichment, cross-run diffing, key-value state, dataset pushes --
is exercised without touching the internet.

Run twice in a row to see the signal layer light up on the second pass.
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STORAGE = ROOT / "storage"

from tests.fixtures import ASHBY_PAYLOAD, GREENHOUSE_PAYLOAD, LEVER_PAYLOAD  # noqa: E402

# Which fixture each mocked board serves.
BOARDS = {
    ("greenhouse", "anthropic"): GREENHOUSE_PAYLOAD,
    ("ashby", "openai"): ASHBY_PAYLOAD,
    ("lever", "cohere"): LEVER_PAYLOAD,
}

# Second run: Anthropic closes the intern role and opens its first DevRel role.
GREENHOUSE_RUN2 = {
    "jobs": GREENHOUSE_PAYLOAD["jobs"][:2] + [{
        "id": 999111,
        "title": "Developer Advocate, Claude Code",
        "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/999111",
        "location": {"name": "Remote - United States"},
        "updated_at": "2026-09-13T10:00:00-04:00",
        "first_published": "2026-09-13T10:00:00-04:00",
        "metadata": [],
        "content": "<p>Help developers build agentic workflows with MCP.</p>",
    }]
}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    for (ats, slug), payload in BOARDS.items():
        marker = {
            "greenhouse": f"/boards/{slug}/jobs",
            "lever": f"/postings/{slug}",
            "ashby": f"/job-board/{slug}",
        }[ats]
        if marker in url:
            if ats == "greenhouse" and RUN_NUMBER == 2:
                payload = GREENHOUSE_RUN2
            return httpx.Response(200, json=payload)
    # Every other slug probe is a miss -- exactly what the resolver expects.
    return httpx.Response(404, json={"error": "not found"})


RUN_NUMBER = 1


def install_mock() -> None:
    import src.ats as ats_mod

    def mock_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    ats_mod.make_client = mock_client
    import src.main as main_mod
    main_mod.make_client = mock_client


def write_input(payload: dict) -> None:
    kv = STORAGE / "key_value_stores" / "default"
    kv.mkdir(parents=True, exist_ok=True)
    (kv / "INPUT.json").write_text(json.dumps(payload), encoding="utf-8")


def read_dataset() -> list[dict]:
    folder = STORAGE / "datasets" / "default"
    if not folder.exists():
        return []
    rows = []
    for f in sorted(folder.glob("*.json")):
        if f.name.startswith("__"):   # local storage bookkeeping file
            continue
        try:
            rows.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return rows


def clear_dataset() -> None:
    shutil.rmtree(STORAGE / "datasets", ignore_errors=True)


async def go(run_number: int, inp: dict) -> list[dict]:
    global RUN_NUMBER
    RUN_NUMBER = run_number
    write_input(inp)
    clear_dataset()
    install_mock()
    from src.main import main
    try:
        # `async with Actor` calls Actor.exit(), which raises SystemExit on the
        # way out. That is correct behaviour for a real run; the harness just
        # has to absorb it so both runs happen in one process.
        await main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise
    return read_dataset()


REPORT = []


def print(*args, **kwargs):  # noqa: A001 - Apify's logger owns stdout during a run
    REPORT.append(" ".join(str(a) for a in args))


def main_cli() -> int:
    shutil.rmtree(STORAGE, ignore_errors=True)
    base_input = {
        "outputMode": "both",
        "maxCompanies": 0,   # registry slice off; only the three extras below
        "concurrency": 3,
        "extraCompanies": [
            {"name": "Anthropic", "ats": "greenhouse", "slug": "anthropic"},
            {"name": "OpenAI", "ats": "ashby", "slug": "openai"},
            {"name": "Cohere", "ats": "lever", "slug": "cohere"},
        ],
        "categories": ["vector_db"],   # filtered out by maxCompanies=0
        "stages": ["all"],
    }

    print("\n=== RUN 1 (cold start) " + "=" * 40)
    rows1 = run_pass_subprocess(1, base_input)
    jobs1 = [r for r in rows1 if r.get("record_type") != "company_signal"]
    sigs1 = [r for r in rows1 if r.get("record_type") == "company_signal"]
    print(f"jobs={len(jobs1)}  signals={len(sigs1)}")
    for j in jobs1:
        print(f"  [{j['company']:<9}] {j['title'][:48]:<48} "
              f"{j['function']:<14} {j['seniority']:<9} {j['workplace']:<8} "
              f"{j.get('salary_max') or '-'}")
    for s in sigs1:
        print(f"  SIGNAL {s['company']}: open={s['open_roles']} new={s['new_roles_this_run']} "
              f"first_obs={s['is_first_observation']} gtm={s['gtm_signal']}")

    print("\n=== RUN 2 (Anthropic: intern closed, first DevRel opened) " + "=" * 5)
    rows2 = run_pass_subprocess(2, base_input)
    jobs2 = [r for r in rows2 if r.get("record_type") != "company_signal"]
    sigs2 = [r for r in rows2 if r.get("record_type") == "company_signal"]
    print(f"jobs={len(jobs2)}  signals={len(sigs2)}")
    for s in sigs2:
        print(f"  SIGNAL {s['company']}: open={s['open_roles']} new={s['new_roles_this_run']} "
              f"closed={s['closed_roles_this_run']} trend={s['hiring_trend']} "
              f"gtm={s['gtm_signal']} first={s['first_time_functions']}")
        for t in s.get("new_role_titles", []):
            print(f"      NEW -> {t}")
        for c in s.get("closed_roles", []):
            print(f"      CLOSED -> {c['title']} (open {c['days_open']}d)")

    # ------------------------------------------------------------- assertions
    problems = []
    if len(jobs1) != 7:
        problems.append(f"run1 expected 7 jobs, got {len(jobs1)}")
    if len(sigs1) != 3:
        problems.append(f"run1 expected 3 signals, got {len(sigs1)}")
    if not all(s["is_first_observation"] for s in sigs1):
        problems.append("run1 should be a cold start for every company")
    if any(s["new_roles_this_run"] for s in sigs1):
        problems.append("run1 must not report new roles")

    anth = next((s for s in sigs2 if s["company"] == "Anthropic"), None)
    if not anth:
        problems.append("run2 missing Anthropic signal")
    else:
        if anth["new_roles_this_run"] != 1:
            problems.append(f"run2 Anthropic new_roles={anth['new_roles_this_run']}, want 1")
        if anth["closed_roles_this_run"] != 1:
            problems.append(f"run2 Anthropic closed={anth['closed_roles_this_run']}, want 1")
        if not anth["gtm_signal"]:
            problems.append("run2 Anthropic should raise gtm_signal (first DevRel hire)")
        if anth["first_time_functions"] != ["devrel"]:
            problems.append(f"run2 first_time_functions={anth['first_time_functions']}")
    unchanged = next((s for s in sigs2 if s["company"] == "OpenAI"), None)
    if unchanged and unchanged["new_roles_this_run"] != 0:
        problems.append("run2 OpenAI board was unchanged; should report 0 new")

    # apify 2.x wrote "RUN_SUMMARY.json"; apify 4.x writes "RUN_SUMMARY". Accept both.
    kv = STORAGE / "key_value_stores" / "default"
    summary_file = next(
        (f for f in (kv / "RUN_SUMMARY", kv / "RUN_SUMMARY.json") if f.exists()), None
    )
    summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file else {}
    print(f"\nRUN_SUMMARY: {json.dumps(summary, indent=2)[:400]}")

    print()
    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        return 1
    print("  Smoke run green: cold start silent, second run produced the right signals.\n")
    return 0


# The Apify SDK registers global services on init and refuses to be
# re-initialised in the same process, so each pass runs as its own subprocess.
def run_pass_subprocess(run_number: int, inp: dict) -> list[dict]:
    import os
    import subprocess
    payload = ROOT / f".smoke_pass{run_number}.json"
    env = {**os.environ, "APIFY_PURGE_ON_START": "0"}
    proc = subprocess.run(
        [sys.executable, "-m", "tests.smoke_run", "--pass", str(run_number)],
        cwd=ROOT, capture_output=True, env=env,
        input=json.dumps(inp).encode(),
    )
    if proc.returncode != 0 or not payload.exists():
        sys.stderr.write(
            f"\n--- pass {run_number} failed (exit {proc.returncode}) ---\n"
            + proc.stderr.decode("utf-8", errors="replace")
            + proc.stdout.decode("utf-8", errors="replace")
            + "\n"
        )
        raise SystemExit(1)
    rows = json.loads(payload.read_text(encoding="utf-8"))
    payload.unlink(missing_ok=True)
    return rows


if __name__ == "__main__":
    if "--pass" in sys.argv:
        n = int(sys.argv[sys.argv.index("--pass") + 1])
        user_input = json.loads(sys.stdin.read())
        result = asyncio.run(go(n, user_input))
        (ROOT / f".smoke_pass{n}.json").write_text(
            json.dumps(result), encoding="utf-8"
        )
        sys.exit(0)

    code = main_cli()
    # The Apify SDK owns stdout during a run, so the report goes to a file.
    (ROOT / "smoke_report.txt").write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    sys.exit(code)