"""AI/ML Hiring Signals -- Apify Actor entry point."""

from __future__ import annotations

import asyncio
from typing import Any

from apify import Actor

from .ats import fetch_board, make_client
from .enrich import enrich
from .registry import CACHE_KEY, CACHE_STORE_NAME, resolve_all, select_companies
from .signals import (
    STATE_KEY,
    company_key,
    diff_company,
    load_state,
    prune_state,
    utcnow,
)

# Pay-per-event charge names. These must match .actor/pay_per_event.json.
EVENT_START = "actor-start"
EVENT_JOB = "job-result"
EVENT_SIGNAL = "company-signal"

DEFAULTS = {
    "categories": ["all"],
    "stages": ["all"],
    "outputMode": "jobs",
    "functions": [],
    "seniorities": [],
    "regions": [],
    "workplace": "any",
    "titleKeywords": [],
    "excludeKeywords": [],
    "onlyNewRoles": False,
    "onlySignalCompanies": False,
    "minSalary": None,
    "maxCompanies": 60,
    "maxJobsPerCompany": 200,
    "concurrency": 6,
    "extraCompanies": [],
}


def _get(inp: dict[str, Any], key: str) -> Any:
    value = inp.get(key)
    return DEFAULTS[key] if value in (None, "", []) and key in DEFAULTS else value


def _lower_set(values: Any) -> set[str]:
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


def passes_filters(job: dict[str, Any], f: dict[str, Any]) -> bool:
    if f["functions"] and (job.get("function") or "").lower() not in f["functions"]:
        return False
    if f["seniorities"] and (job.get("seniority") or "").lower() not in f["seniorities"]:
        return False
    if f["regions"] and (job.get("region") or "").lower() not in f["regions"]:
        return False
    if f["workplace"] != "any" and job.get("workplace") != f["workplace"]:
        return False

    haystack = f"{job.get('title', '')} {job.get('description_excerpt', '')}".lower()
    if f["title_keywords"] and not any(k in haystack for k in f["title_keywords"]):
        return False
    if f["exclude_keywords"] and any(k in haystack for k in f["exclude_keywords"]):
        return False
    if f["only_new"] and not job.get("is_new"):
        return False
    if f["min_salary"]:
        top = job.get("salary_max") or job.get("salary_min")
        if not top or top < f["min_salary"]:
            return False
    return True


async def main() -> None:
    async with Actor:
        started = utcnow()
        inp = await Actor.get_input() or {}
        await Actor.charge(event_name=EVENT_START)

        output_mode = _get(inp, "outputMode")
        max_companies = int(_get(inp, "maxCompanies") or 60)
        max_jobs = int(_get(inp, "maxJobsPerCompany") or 200)
        concurrency = max(1, min(int(_get(inp, "concurrency") or 6), 12))
        only_signal_companies = bool(_get(inp, "onlySignalCompanies"))

        filters = {
            "functions": _lower_set(_get(inp, "functions")),
            "seniorities": _lower_set(_get(inp, "seniorities")),
            "regions": _lower_set(_get(inp, "regions")),
            "workplace": (_get(inp, "workplace") or "any").lower(),
            "title_keywords": _lower_set(_get(inp, "titleKeywords")),
            "exclude_keywords": _lower_set(_get(inp, "excludeKeywords")),
            "only_new": bool(_get(inp, "onlyNewRoles")),
            "min_salary": _get(inp, "minSalary"),
        }

        companies = select_companies(
            categories_filter=_get(inp, "categories"),
            stages_filter=_get(inp, "stages"),
            extra_companies=_get(inp, "extraCompanies"),
            limit=max_companies,
        )
        if not companies:
            await Actor.fail(status_message="No companies matched the selected filters.")
            return
        Actor.log.info("Selected %d companies from the AI/ML registry.", len(companies))

        # ---- load cross-run state + slug cache -------------------------------
        store = await Actor.open_key_value_store()
        state = prune_state(load_state(await store.get_value(STATE_KEY)), now=started)

        cache_store = await Actor.open_key_value_store(name=CACHE_STORE_NAME)
        slug_cache: dict[str, Any] = await cache_store.get_value(CACHE_KEY) or {}
        cache_size_before = len(slug_cache)

        jobs_pushed = 0
        signals_pushed = 0
        boards_ok = 0
        boards_failed: list[dict[str, Any]] = []

        async with make_client() as client:
            resolved = await resolve_all(
                client, companies, slug_cache, concurrency=concurrency
            )
            unresolved = len(companies) - len(resolved)
            if unresolved:
                Actor.log.info(
                    "%d companies have no public Greenhouse/Lever/Ashby board "
                    "(private ATS or Workday) — skipped.", unresolved
                )
            if len(slug_cache) != cache_size_before:
                await cache_store.set_value(CACHE_KEY, slug_cache)

            sem = asyncio.Semaphore(concurrency)

            async def handle(company: dict[str, Any]) -> None:
                nonlocal jobs_pushed, signals_pushed, boards_ok
                async with sem:
                    result = await fetch_board(
                        client,
                        company=company["name"],
                        ats=company["ats"],
                        slug=company["slug"],
                    )
                if not result.ok:
                    boards_failed.append({
                        "company": company["name"],
                        "ats": company["ats"],
                        "slug": company["slug"],
                        "error": result.error,
                    })
                    return
                boards_ok += 1

                jobs = [enrich(j) for j in result.jobs[:max_jobs]]
                for job in jobs:
                    job.update({
                        "company": company["name"],
                        "company_category": company.get("category"),
                        "company_stage": company.get("stage"),
                        "company_hq": company.get("hq"),
                        "ats": company["ats"],
                        "ats_slug": company["slug"],
                        "scraped_at": started.isoformat(),
                    })

                key = company_key(company["ats"], company["slug"])
                closed, signal, next_record = diff_company(
                    state["companies"].get(key), jobs, now=started
                )
                state["companies"][key] = next_record

                interesting = (
                    signal["gtm_signal"]
                    or signal["first_time_functions"]
                    or signal["new_roles_this_run"] > 0
                )
                if only_signal_companies and not interesting:
                    return

                if output_mode in ("jobs", "both"):
                    selected = [j for j in jobs if passes_filters(j, filters)]
                    for job in selected:
                        await Actor.push_data(job, charged_event_name=EVENT_JOB)
                    jobs_pushed += len(selected)

                if output_mode in ("signals", "both"):
                    await Actor.push_data({
                        "record_type": "company_signal",
                        "company": company["name"],
                        "company_category": company.get("category"),
                        "company_stage": company.get("stage"),
                        "company_hq": company.get("hq"),
                        "ats": company["ats"],
                        "ats_slug": company["slug"],
                        "board_url": f"https://{company['ats']}.io/{company['slug']}",
                        "scraped_at": started.isoformat(),
                        **signal,
                        "closed_roles": closed[:50],
                        "new_role_titles": [
                            j["title"] for j in jobs if j.get("is_new")
                        ][:50],
                    }, charged_event_name=EVENT_SIGNAL)
                    signals_pushed += 1

            await asyncio.gather(*(handle(c) for c in resolved))

        await store.set_value(STATE_KEY, state)

        duration = (utcnow() - started).total_seconds()
        summary = {
            "companies_selected": len(companies),
            "boards_resolved": len(resolved),
            "boards_fetched_ok": boards_ok,
            "boards_failed": len(boards_failed),
            "jobs_pushed": jobs_pushed,
            "company_signals_pushed": signals_pushed,
            "cached_slugs": len(slug_cache),
            "duration_seconds": round(duration, 1),
        }
        await store.set_value("RUN_SUMMARY", {**summary, "failures": boards_failed[:50]})
        Actor.log.info("Run summary: %s", summary)
        await Actor.set_status_message(
            f"{jobs_pushed} jobs and {signals_pushed} company signals "
            f"from {boards_ok} AI/ML boards in {duration:.0f}s."
        )