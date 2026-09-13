# Deploy & publish walkthrough

Everything below fits inside the Apify free plan ($5/month platform credit, 8 GB max RAM, 25 concurrent runs on the free tier at time of writing). This Actor makes plain JSON requests at 256 MB — a 60-company run costs a small fraction of one compute unit.

---

## 0. Which template to pick

**`python-empty`.**

The Console offers several Python templates. Here's the reasoning:

| Template | Verdict |
|---|---|
| **Python Empty** ✅ | Apify SDK wired up, nothing else. Exactly right — this Actor calls three JSON APIs with `httpx`. |
| One-Page HTML Scraper (BeautifulSoup) | Adds an HTML-parsing scaffold you'd delete. |
| Crawlee + BeautifulSoup / Parsel | Crawlee is a crawling framework — link queues, retries, session pools. You're hitting three known endpoints, not crawling. Extra memory, extra cold-start time. |
| Crawlee + Playwright / Camoufox | Launches a real browser. Roughly 10× the memory and compute for zero benefit — these APIs have no JavaScript and no anti-bot. Choosing this is the single easiest way to burn your free credit. |
| Python Standby | For Actors that stay warm and answer HTTP requests. Worth revisiting later if you expose this as a live API, but not for v1. |
| Python MCP server | Different product shape. (Genuinely worth building later — see "What to build next".) |

The code in this repo already contains everything the template would have given you, so you can skip template selection entirely and just `apify push` (step 2).

---

## 1. Install the CLI and log in

```bash
npm install -g apify-cli
apify login          # paste the API token from Console → Settings → Integrations
```

Verify Python 3.11+ locally:

```bash
python3 --version
pip install -r requirements.txt
```

---

## 2. Run it locally first

```bash
# offline: parsing, enrichment and signal logic
python -m tests.test_pipeline

# offline: full Actor run against mocked ATS responses
python -m tests.smoke_run

# real network: confirm every company's ATS and slug
python tools/verify_registry.py
python tools/verify_registry.py --write     # then commit the corrected registry
```

**Run `verify_registry.py --write` before your first publish.** The seed registry lists best-known slugs; the verifier confirms them against the live boards and drops companies with no public Greenhouse/Lever/Ashby board. It takes a couple of minutes and costs nothing.

Then a real local run:

```bash
apify run --purge --input '{
  "categories": ["foundation_model"],
  "outputMode": "both",
  "maxCompanies": 10
}'
```

Results land in `storage/datasets/default/`. Run it a second time to see the signal layer activate.

---

## 3. Push to the platform

```bash
apify push
```

This builds the Docker image on Apify and creates the Actor in your account. Then in Console:

1. Open the Actor → **Source** → confirm the build succeeded.
2. **Input** tab → the schema renders as a form. Click through it — if a field looks confusing to you, it will confuse a buyer.
3. Run it once with `maxCompanies: 10`. Check the **Storage → Dataset** tab; the two named views (`Open roles`, `Company hiring signals`) should render as tables.
4. Run it a **second time** and confirm `new_roles_this_run` and `closed_roles_this_run` populate. This is the feature nobody else has — make sure it works before anyone sees it.

Set **Memory: 256 MB** and **Timeout: 600s** in the Actor's default run options. Larger memory costs proportionally more compute units and buys nothing here.

---

## 4. Publish to Store

Actor → **Publication** tab.

- **Title**: `AI/ML Hiring Signals — Track Who AI Companies Are Hiring`
- **Description** (the ~150-char SEO line): *Track open roles at 98 verified AI companies across Greenhouse, Lever and Ashby. Get new/closed roles, hiring velocity, and first-hire go-to-market signals.*
- **Categories**: `Jobs`, `Business`, `Lead generation`
- **README**: the repo `README.md` is written as the Store listing — it's what ranks in Google and what converts a visitor into a run. Keep the comparison table and the "Who uses this" section; those do the selling.
- **Screenshots**: run it once, screenshot the dataset table view and the signals view. Two good screenshots beat a long description.

### On SEO, honestly

Search "greenhouse scraper apify" and you'll find a dozen near-identical actors. You will not win that keyword, and you shouldn't try. Your title targets a different query — people searching *"AI company job data"*, *"AI startup hiring tracker"*, *"who is hiring AI engineers"*. That's a smaller pool with far less competition and a clearer buyer.

---

## 5. Monetization

Start **free** for 2–4 weeks. Reviews and monthly-active-user count are what make a Store listing credible, and you can't get them at $0 users. Once you have ~5 reviews and a stable run history, switch on pay-per-event.

Apify pays developers **80%** of Actor revenue. Payout thresholds are $20 (PayPal) / $100 (bank transfer), processed monthly.

Set pricing in Console → **Monetization**. `.actor/pay_per_event.json` in this repo is a reference for the event names and suggested prices to enter there — the Actor's code already calls `Actor.charge()` with matching names:

| Event | Suggested price | Rationale |
|---|---|---|
| `actor-start` | $0.005 | Covers cold starts on tiny runs. |
| `job-result` | $0.002 | Competitors sit around $0.0015/record for raw listings. You're returning classified records with salary bands and tech tags, so a modest premium is defensible — but don't go 3× or you lose the price comparison. |
| `company-signal` | $0.02 | This is the differentiated product. One signal row can be worth a sales lead; price it like intelligence, not like a scraped row. |

The asymmetry is deliberate: cheap listings get you found, signals are where the margin is. A daily `onlySignalCompanies` run across 98 companies might emit 10–20 signal rows — around $0.30/day, $9/month, for a lead feed a GTM team would otherwise pay a data vendor hundreds for.

**Before enabling monetization:** `Actor.charge()` is a no-op until pay-per-event pricing is switched on (you'll see `Ignored attempt to charge for an event` in the logs — that's expected while free).

---

## 6. Schedule it

Console → **Schedules** → new schedule, cron `0 6 * * *` (daily 06:00 UTC = 11:30 IST), input:

```json
{"outputMode": "signals", "onlySignalCompanies": true, "categories": ["all"], "maxCompanies": 100}
```

Then Actor → **Integrations** → Slack or webhook on `Run succeeded`, so new signals land somewhere a human reads them. A scheduled Actor with a Slack digest is a product people keep paying for; a one-off scraper is not.

---

## What to build next

Two follow-ons that compound on this same registry, both cheap:

1. **An MCP server version.** Apify has flagged MCP tools as requested-but-underserved — far less competition than scraper categories. Wrap this as `find_ai_companies_hiring(function, region)` and it becomes something an AI agent calls, not just something a human runs. The `python-mcp-server` template covers the scaffolding; your `src/` modules drop in unchanged.
2. **Widen the registry, not the ATS list.** Adding Workable and SmartRecruiters gets you more companies of the same kind. Growing the curated AI universe from 98 → 400 companies makes the thing nobody can copy quickly larger. The registry is the moat; the fetching is not.