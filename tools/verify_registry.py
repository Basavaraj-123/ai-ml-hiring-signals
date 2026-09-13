"""
One-off registry verifier.

Probes every company in registry_seed.json across Greenhouse, Lever and Ashby,
then writes back the confirmed `ats` + `slug` and reports which companies have
no public board (they use Workday, SmartRecruiters, or a custom careers page).

Run it locally (needs plain internet access -- no Apify account required):

    python tools/verify_registry.py            # report only
    python tools/verify_registry.py --write    # update registry_seed.json

Re-run it every month or so; company boards migrate more often than you'd think.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ats import make_client, probe_slug  # noqa: E402
from src.registry import SEED_PATH, slug_variants  # noqa: E402

ATS_ORDER = ("greenhouse", "ashby", "lever")


async def verify_one(client, company: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        for slug in slug_variants(
            company["name"], company.get("slug"), company.get("aliases")
        ):
            for ats in ATS_ORDER:
                if await probe_slug(client, ats, slug):
                    return {**company, "ats": ats, "slug": slug, "_status": "ok"}
    return {**company, "_status": "no_public_board"}


async def run(write: bool, concurrency: int) -> int:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    companies = data["companies"]
    sem = asyncio.Semaphore(concurrency)

    async with make_client() as client:
        results = await asyncio.gather(
            *(verify_one(client, c, sem) for c in companies)
        )

    ok = [r for r in results if r["_status"] == "ok"]
    missing = [r for r in results if r["_status"] != "ok"]
    seeded = {c["name"]: c for c in companies}
    corrected = [
        r for r in ok
        if r["ats"] != seeded[r["name"]].get("ats")
        or r["slug"] != seeded[r["name"]].get("slug")
    ]

    print(f"\n  verified  {len(ok)}/{len(companies)}")
    print(f"  corrected {len(corrected)}")
    print(f"  no public board {len(missing)}\n")

    for r in corrected:
        print(f"  FIXED  {r['name']:<28} -> {r['ats']}/{r['slug']}")
    if missing:
        print("\n  No public Greenhouse/Lever/Ashby board (Workday or custom site):")
        for r in missing:
            print(f"         {r['name']}")

    if write:
        data["companies"] = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in results if r["_status"] == "ok"
        ]
        SEED_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"\n  registry_seed.json rewritten with {len(data['companies'])} verified companies.")
    else:
        print("\n  (dry run -- pass --write to update registry_seed.json)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--concurrency", type=int, default=5)
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args.write, args.concurrency)))
