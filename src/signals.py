"""
Signal layer -- the real product.

A job listing is a commodity. What a buyer pays for is the *delta*: which
roles are new since last run, which closed, how fast a company is hiring,
and -- the highest-value one -- the moment a company posts its FIRST role
in a function it has never hired for. A pure-research lab posting its first
Account Executive is a go-to-market signal a sales team will pay for; it is
invisible in any flat list of job postings.

State lives in the Actor's default key-value store under STATE_KEY, so the
signals work automatically on every scheduled re-run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .enrich import SIGNAL_FUNCTIONS

STATE_KEY = "HIRING_STATE"
STATE_VERSION = 1
# Drop company history after this long without a successful fetch.
STALE_AFTER_DAYS = 120


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "companies": {}}


def load_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        return empty_state()
    if not isinstance(raw.get("companies"), dict):
        return empty_state()
    return raw


def prune_state(state: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Keep the KV record small so it never becomes the expensive part of a run."""
    now = now or utcnow()
    cutoff = now - timedelta(days=STALE_AFTER_DAYS)
    kept = {}
    for key, record in state.get("companies", {}).items():
        seen = _parse(record.get("last_seen_at"))
        if seen is None or seen >= cutoff:
            kept[key] = record
    state["companies"] = kept
    return state


def company_key(ats: str, slug: str) -> str:
    return f"{ats}:{slug}"


def diff_company(
    prior: dict[str, Any] | None,
    jobs: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """
    Compare this run's jobs against the stored snapshot.

    Returns (closed_jobs, company_signal, next_record) and stamps every job in
    `jobs` with its per-job signal fields in place.
    """
    now = now or utcnow()
    prior = prior or {}
    first_run = not prior

    prior_jobs: dict[str, Any] = prior.get("jobs", {}) if isinstance(prior.get("jobs"), dict) else {}
    seen_functions: set[str] = set(prior.get("functions_ever", []))
    history: list[dict[str, Any]] = prior.get("history", [])

    current_ids = set()
    new_jobs: list[dict[str, Any]] = []
    newly_opened_functions: list[str] = []

    for job in jobs:
        job_id = job["job_id"]
        current_ids.add(job_id)
        record = prior_jobs.get(job_id)
        function = job.get("function") or "other"

        if record:
            first_seen = record.get("first_seen_at") or now.isoformat()
            job["is_new"] = False
        else:
            first_seen = now.isoformat()
            # On a cold start everything looks new; don't cry wolf.
            job["is_new"] = not first_run
            if not first_run:
                new_jobs.append(job)

        job["first_seen_at"] = first_seen
        opened = _parse(job.get("posted_at")) or _parse(first_seen)
        job["days_open"] = max(0, (now - opened).days) if opened else None

        is_first_of_function = function not in seen_functions
        job["is_first_hire_for_function"] = bool(is_first_of_function and not first_run)
        if is_first_of_function:
            seen_functions.add(function)
            if not first_run and function in SIGNAL_FUNCTIONS:
                newly_opened_functions.append(function)
                job["signal_note"] = (
                    f"First-ever {function.replace('_', ' ')} role seen at this "
                    f"company — {SIGNAL_FUNCTIONS[function]}."
                )

    closed_jobs = [
        {
            "job_id": job_id,
            "title": rec.get("title"),
            "function": rec.get("function"),
            "first_seen_at": rec.get("first_seen_at"),
            "closed_at": now.isoformat(),
            "days_open": (
                (now - _parse(rec.get("first_seen_at"))).days
                if _parse(rec.get("first_seen_at")) else None
            ),
        }
        for job_id, rec in prior_jobs.items()
        if job_id not in current_ids
    ]

    history = (history + [{"at": now.isoformat(), "open_roles": len(jobs)}])[-24:]

    # Hiring velocity: change in open headcount vs the oldest point in a
    # 30-day trailing window. Positive = expanding, negative = contracting.
    window_start = now - timedelta(days=30)
    in_window = [h for h in history if (_parse(h.get("at")) or now) >= window_start]
    baseline = in_window[0]["open_roles"] if in_window else len(jobs)
    velocity_30d = len(jobs) - baseline

    function_counts: dict[str, int] = {}
    for job in jobs:
        fn = job.get("function") or "other"
        function_counts[fn] = function_counts.get(fn, 0) + 1

    signal = {
        "open_roles": len(jobs),
        "new_roles_this_run": len(new_jobs),
        "closed_roles_this_run": len(closed_jobs),
        "net_change_30d": velocity_30d,
        "hiring_trend": (
            "expanding" if velocity_30d > 0
            else "contracting" if velocity_30d < 0
            else "flat"
        ),
        "first_time_functions": newly_opened_functions,
        "gtm_signal": bool({"sales", "marketing", "devrel"} & set(newly_opened_functions)),
        "roles_by_function": dict(sorted(function_counts.items(), key=lambda kv: -kv[1])),
        "is_first_observation": first_run,
    }

    next_record = {
        "last_seen_at": now.isoformat(),
        "functions_ever": sorted(seen_functions),
        "history": history,
        "jobs": {
            job["job_id"]: {
                "title": job.get("title"),
                "function": job.get("function"),
                "first_seen_at": job["first_seen_at"],
            }
            for job in jobs
        },
    }
    return closed_jobs, signal, next_record
