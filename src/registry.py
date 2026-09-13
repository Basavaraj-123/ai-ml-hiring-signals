"""
The company registry -- the actual moat of this Actor.

Every competing ATS scraper on Apify Store makes the *user* supply company
slugs. That is the hard part of the job, and handing it back to the buyer is
why those actors are interchangeable. This Actor ships a curated AI/ML
company universe instead: the user picks a category, we already know who is
in it and where their board lives.

Slugs rot (companies migrate ATS, rename, get acquired), so the registry is
self-healing: unknown or broken entries go through `resolve_company`, which
probes candidate slugs across all three ATSes and caches the winner in a
named key-value store. Every scheduled run makes the dataset a little better.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Iterable

import httpx

from .ats import ASHBY, GREENHOUSE, LEVER, SUPPORTED_ATS, probe_slug

SEED_PATH = Path(__file__).with_name("registry_seed.json")
CACHE_STORE_NAME = "ats-slug-cache"
CACHE_KEY = "resolved"

_PUNCT = re.compile(r"[^a-z0-9]+")


def load_seed() -> list[dict[str, Any]]:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return [c for c in data.get("companies", []) if c.get("name")]


def categories() -> list[str]:
    return sorted({c.get("category", "other") for c in load_seed()})


def slug_variants(
    name: str,
    hint: str | None = None,
    aliases: list[str] | None = None,
) -> list[str]:
    """Candidate board slugs for a company name, most-likely first."""
    base = _PUNCT.sub("", name.lower())
    # "Cursor (Anysphere)" -> also try the parenthetical.
    inner = re.search(r"\(([^)]+)\)", name)
    words = _PUNCT.sub(" ", re.sub(r"\([^)]*\)", "", name).lower()).split()
    joined = "".join(words)
    hyphen = "-".join(words)
    first = words[0] if words else base

    candidates = [hint, *(aliases or []), joined, base, hyphen, first]
    if inner:
        candidates.append(_PUNCT.sub("", inner.group(1).lower()))
    # Strip common corporate suffixes: "Scale AI" -> "scale"
    for suffix in ("ai", "labs", "lab", "inc", "technologies", "tech", "hq", "io"):
        if joined.endswith(suffix) and len(joined) > len(suffix) + 2:
            candidates.append(joined[: -len(suffix)])

    seen: set[str] = set()
    out: list[str] = []
    for cand in candidates:
        if cand and cand not in seen and len(cand) >= 2:
            seen.add(cand)
            out.append(cand)
    return out


async def resolve_company(
    client: httpx.AsyncClient,
    company: dict[str, Any],
    cache: dict[str, Any],
    *,
    max_probes: int = 15,
) -> dict[str, Any] | None:
    """
    Work out which ATS + slug serves this company's board.

    Returns {'ats', 'slug'} or None if nothing matched. Results (including
    misses, so we don't re-probe every run) are written into `cache`.
    """
    name = company["name"]
    cached = cache.get(name)
    if isinstance(cached, dict):
        if cached.get("ats") in SUPPORTED_ATS and cached.get("slug"):
            return {"ats": cached["ats"], "slug": cached["slug"]}
        if cached.get("miss"):
            return None

    hinted_ats = company.get("ats")
    ats_order: Iterable[str] = (
        [hinted_ats, *(a for a in SUPPORTED_ATS if a != hinted_ats)]
        if hinted_ats in SUPPORTED_ATS
        else (GREENHOUSE, ASHBY, LEVER)
    )

    probes = 0
    for slug in slug_variants(name, company.get("slug"), company.get("aliases")):
        for ats in ats_order:
            if probes >= max_probes:
                break
            probes += 1
            if await probe_slug(client, ats, slug):
                cache[name] = {"ats": ats, "slug": slug}
                return {"ats": ats, "slug": slug}
        if probes >= max_probes:
            break

    cache[name] = {"miss": True}
    return None


async def resolve_all(
    client: httpx.AsyncClient,
    companies: list[dict[str, Any]],
    cache: dict[str, Any],
    *,
    concurrency: int = 6,
    on_progress=None,
) -> list[dict[str, Any]]:
    """Resolve a batch of companies concurrently; drops the unresolvable ones."""
    sem = asyncio.Semaphore(concurrency)
    resolved: list[dict[str, Any]] = []

    async def one(company: dict[str, Any]) -> None:
        async with sem:
            found = await resolve_company(client, company, cache)
        if found:
            resolved.append({**company, **found})
        if on_progress:
            on_progress(company["name"], found)

    await asyncio.gather(*(one(c) for c in companies))
    # Preserve seed order for deterministic output.
    order = {c["name"]: i for i, c in enumerate(companies)}
    resolved.sort(key=lambda c: order.get(c["name"], 1_000_000))
    return resolved


def select_companies(
    *,
    categories_filter: list[str] | None = None,
    stages_filter: list[str] | None = None,
    extra_companies: list[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Apply the user's input filters to the seed universe."""
    wanted_cat = {c.lower() for c in (categories_filter or []) if c and c.lower() != "all"}
    wanted_stage = {s.lower() for s in (stages_filter or []) if s and s.lower() != "all"}

    picked = []
    for company in load_seed():
        if wanted_cat and company.get("category", "").lower() not in wanted_cat:
            continue
        if wanted_stage and company.get("stage", "").lower() not in wanted_stage:
            continue
        picked.append(dict(company))

    # `limit` caps the *registry* slice only. Companies the user explicitly
    # listed are always tracked -- silently dropping them because the registry
    # slice was already full would be a nasty surprise.
    if limit:
        picked = picked[:limit]

    known = {c["name"].lower() for c in picked}
    for extra in extra_companies or []:
        if not isinstance(extra, dict):
            extra = {"name": str(extra)}
        name = (extra.get("name") or extra.get("slug") or "").strip()
        if not name or name.lower() in known:
            continue
        known.add(name.lower())
        picked.append({
            "name": name,
            "slug": extra.get("slug"),
            "ats": extra.get("ats"),
            "category": extra.get("category", "custom"),
            "stage": extra.get("stage", "unknown"),
            "hq": extra.get("hq"),
        })

    return picked
