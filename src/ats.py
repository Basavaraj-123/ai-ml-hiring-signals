"""
Thin, dependency-light clients for the three public ATS job-board APIs.

All three endpoints are public JSON, need no API key, and are explicitly
published by the vendors for job-board embedding. No browser, no proxy,
no anti-bot handling required -- which is why this Actor runs for pennies.

Confirmed endpoint shapes (Sept 2026):

  Greenhouse  GET  https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
              -> {"jobs": [{id, title, absolute_url, location:{name},
                            updated_at, first_published, metadata:[...], content}]}

  Lever       GET  https://api.lever.co/v0/postings/{slug}?mode=json
              -> [{id, text, hostedUrl, applyUrl, createdAt(ms),
                   categories:{commitment, department, location, team, allLocations},
                   workplaceType, country, descriptionPlain, lists:[...]}]

  Ashby       GET  https://api.ashbyhq.com/posting-api/job-board/{slug}
                     ?includeCompensation=true
              -> {"jobs": [{id, title, location, department, team,
                            employmentType, jobUrl, publishedAt, isListed,
                            isRemote, compensation, descriptionPlain}]}
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

GREENHOUSE = "greenhouse"
LEVER = "lever"
ASHBY = "ashby"
SUPPORTED_ATS = (GREENHOUSE, LEVER, ASHBY)

USER_AGENT = "ai-hiring-signals/1.0 (+https://apify.com; public job-board API client)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass
class BoardResult:
    """Outcome of fetching one company's board."""

    company: str
    ats: str
    slug: str
    ok: bool
    jobs: list[dict[str, Any]] = field(default_factory=list)
    status: int | None = None
    error: str | None = None


def _iso(value: Any) -> str | None:
    """Normalise the three different date formats into ISO-8601 UTC."""
    if value in (None, "", 0):
        return None
    try:
        # Lever hands back epoch milliseconds as an int.
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


# --------------------------------------------------------------------------
# Per-ATS normalisers: each returns the SAME dict shape.
# --------------------------------------------------------------------------

def _norm_greenhouse(raw: dict[str, Any]) -> dict[str, Any]:
    meta = {}
    for item in raw.get("metadata") or []:
        name = (item or {}).get("name")
        if name:
            meta[str(name).strip().lower()] = item.get("value")
    return {
        "job_id": str(raw.get("id") or ""),
        "title": (raw.get("title") or "").strip(),
        "url": raw.get("absolute_url"),
        "apply_url": raw.get("absolute_url"),
        "location_raw": ((raw.get("location") or {}).get("name") or "").strip(),
        "department": None,
        "team": None,
        "employment_type": meta.get("employment type") or meta.get("job type"),
        "posted_at": _iso(raw.get("first_published")),
        "updated_at": _iso(raw.get("updated_at")),
        "description": raw.get("content") or "",
        "compensation_raw": meta.get("salary range") or meta.get("compensation"),
        "workplace_hint": None,
    }


def _norm_lever(raw: dict[str, Any]) -> dict[str, Any]:
    cats = raw.get("categories") or {}
    workplace = (raw.get("workplaceType") or "").strip().lower()
    return {
        "job_id": str(raw.get("id") or ""),
        "title": (raw.get("text") or "").strip(),
        "url": raw.get("hostedUrl"),
        "apply_url": raw.get("applyUrl") or raw.get("hostedUrl"),
        "location_raw": (cats.get("location") or "").strip(),
        "department": cats.get("department"),
        "team": cats.get("team"),
        "employment_type": cats.get("commitment"),
        "posted_at": _iso(raw.get("createdAt")),
        "updated_at": _iso(raw.get("createdAt")),
        "description": raw.get("descriptionPlain") or raw.get("description") or "",
        "compensation_raw": raw.get("salaryRange"),
        "workplace_hint": workplace if workplace in ("remote", "hybrid", "onsite") else None,
    }


def _norm_ashby(raw: dict[str, Any]) -> dict[str, Any]:
    comp = raw.get("compensation")
    if isinstance(comp, dict):
        comp = comp.get("compensationTierSummary") or comp.get("summary")
    return {
        "job_id": str(raw.get("id") or ""),
        "title": (raw.get("title") or "").strip(),
        "url": raw.get("jobUrl"),
        "apply_url": raw.get("applyUrl") or raw.get("jobUrl"),
        "location_raw": (raw.get("location") or "").strip(),
        "department": raw.get("department"),
        "team": raw.get("team"),
        "employment_type": raw.get("employmentType"),
        "posted_at": _iso(raw.get("publishedAt")),
        "updated_at": _iso(raw.get("updatedAt") or raw.get("publishedAt")),
        "description": raw.get("descriptionPlain") or raw.get("descriptionHtml") or "",
        "compensation_raw": comp if isinstance(comp, str) else None,
        "workplace_hint": "remote" if raw.get("isRemote") is True else None,
    }


_NORMALISERS = {
    GREENHOUSE: _norm_greenhouse,
    LEVER: _norm_lever,
    ASHBY: _norm_ashby,
}


def board_url(ats: str, slug: str, *, with_content: bool = True) -> str:
    if ats == GREENHOUSE:
        suffix = "?content=true" if with_content else ""
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs{suffix}"
    if ats == LEVER:
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"
    if ats == ASHBY:
        return (
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
            "?includeCompensation=true"
        )
    raise ValueError(f"unsupported ats: {ats}")


def extract_jobs(ats: str, payload: Any) -> list[dict[str, Any]]:
    """Pull the job array out of an ATS payload and normalise every entry."""
    if ats in (GREENHOUSE, ASHBY):
        rows = (payload or {}).get("jobs") if isinstance(payload, dict) else None
    else:
        rows = payload if isinstance(payload, list) else None
    if not rows:
        return []

    normalise = _NORMALISERS[ats]
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Ashby flags unlisted/internal roles; skip them.
        if ats == ASHBY and row.get("isListed") is False:
            continue
        job = normalise(row)
        if job["job_id"] and job["title"]:
            out.append(job)
    return out


async def fetch_board(
    client: httpx.AsyncClient,
    *,
    company: str,
    ats: str,
    slug: str,
    with_content: bool = True,
    retries: int = 2,
) -> BoardResult:
    """Fetch one company board. Never raises -- failures come back as BoardResult."""
    url = board_url(ats, slug, with_content=with_content)
    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                return BoardResult(company, ats, slug, False, status=404,
                                   error="board not found (wrong slug or ATS)")
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                last_error = "rate limited"
                continue
            resp.raise_for_status()
            jobs = extract_jobs(ats, resp.json())
            return BoardResult(company, ats, slug, True, jobs=jobs,
                               status=resp.status_code)
        except (httpx.HTTPError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
    return BoardResult(company, ats, slug, False, error=last_error)


async def probe_slug(client: httpx.AsyncClient, ats: str, slug: str) -> bool:
    """Cheap existence check used by the slug auto-resolver."""
    try:
        resp = await client.get(board_url(ats, slug, with_content=False))
    except httpx.HTTPError:
        return False
    if resp.status_code != 200:
        return False
    try:
        return bool(extract_jobs(ats, resp.json()))
    except ValueError:
        return False


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        limits=httpx.Limits(max_connections=12, max_keepalive_connections=12),
    )
