"""
Enrichment layer -- the part competitors don't have.

Turns a raw job row into a classified record: function, seniority, remote
status, normalised location, parsed salary band, and AI/ML tech tags.
Everything here is pure (no I/O), so it is fast and unit-testable.
"""

from __future__ import annotations

import re
from typing import Any

# --------------------------------------------------------------------------
# Job function classification
# Order matters: the first matching bucket wins, so put the narrow,
# high-signal functions (devrel, ml_research) above the broad ones.
# --------------------------------------------------------------------------

_FUNCTION_RULES: list[tuple[str, list[str]]] = [
    ("ml_research", [
        "research scientist", "research engineer", "member of technical staff",
        "research resident", "ai researcher", "research intern",
        "alignment", "interpretability", "post-training", "pretraining",
        "pre-training", "rl engineer", "reinforcement learning",
    ]),
    ("ml_engineering", [
        "machine learning", "ml engineer", "mle", "applied scientist",
        "applied ai", "ai engineer", "deep learning", "computer vision",
        "nlp engineer", "llm engineer", "model engineer", "inference",
        "forward deployed engineer", "mlops",
    ]),
    ("data", [
        "data engineer", "data scientist", "analytics engineer", "data analyst",
        "data platform", "business intelligence",
    ]),
    ("devrel", [
        "developer relations", "developer advocate", "devrel",
        "developer experience", "community manager", "developer educator",
        "technical evangelist",
    ]),
    # Program/product management sits above infrastructure so that
    # "Technical Program Manager, Compute Infrastructure" lands in `product`
    # rather than being captured by the word "infrastructure".
    ("product", [
        "product manager", "product lead", "technical program manager", "tpm",
        "program manager", "product operations", "head of product",
        "product owner", "group product",
    ]),
    ("infrastructure", [
        "infrastructure", "site reliability", "sre", "platform engineer",
        "devops", "cloud engineer", "kubernetes", "systems engineer",
        "gpu", "compute", "performance engineer",
    ]),
    ("security", [
        "security engineer", "appsec", "infosec", "trust and safety",
        "trust & safety", "security researcher", "red team", "grc",
    ]),
    ("engineering", [
        "software engineer", "swe", "backend", "back-end", "frontend",
        "front-end", "full stack", "fullstack", "mobile engineer",
        "ios engineer", "android engineer", "engineering manager",
        "developer", "architect", "qa engineer", "test engineer",
    ]),
    ("design", [
        "designer", "design lead", "ux", "ui ", "user research", "brand studio",
    ]),
    ("sales", [
        "account executive", "sales", "solutions engineer", "solutions architect",
        "business development", "bdr", "sdr", "revenue", "partnerships",
        "customer success", "account manager", "go-to-market", "gtm",
    ]),
    ("marketing", [
        "marketing", "growth", "demand generation", "content strategist",
        "brand", "communications", "public relations", "seo",
    ]),
    ("recruiting", [
        "recruiter", "recruiting", "talent acquisition", "sourcer",
        "people operations", "people partner", "hr business partner",
    ]),
    ("finance", [
        "finance", "accountant", "accounting", "controller", "fp&a",
        "treasury", "revenue operations", "revops", "procurement",
    ]),
    ("legal", [
        "counsel", "legal", "compliance", "privacy", "policy", "regulatory",
    ]),
    ("operations", [
        "operations", "chief of staff", "executive assistant", "workplace",
        "facilities", "office manager", "business operations", "bizops",
    ]),
    ("support", [
        "support engineer", "technical support", "customer support",
        "customer experience",
    ]),
]

# Functions whose FIRST appearance at a company is a meaningful business signal.
SIGNAL_FUNCTIONS = {
    "sales": "entering go-to-market motion",
    "marketing": "building demand generation",
    "devrel": "pushing developer adoption",
    "recruiting": "scaling headcount deliberately",
    "finance": "professionalising the back office",
    "legal": "preparing for enterprise or regulatory scrutiny",
    "support": "onboarding production customers",
    "security": "chasing enterprise/SOC2 readiness",
}

# --------------------------------------------------------------------------
# Seniority. Checked most-senior-first.
# --------------------------------------------------------------------------

_SENIORITY_RULES: list[tuple[str, list[str]]] = [
    ("executive", ["chief ", "cto", "ceo", "cfo", "coo", "cio", "ciso",
                   "vp ", "vp,", "vice president", "head of", "president"]),
    ("director", ["director", "senior manager", "group manager"]),
    ("manager", ["manager", "lead ", " lead", "team lead", "tech lead"]),
    ("principal", ["principal", "distinguished", "fellow", "architect"]),
    ("staff", ["staff", "l6", "l7"]),
    ("senior", ["senior", "sr.", "sr ", "iii", " iv"]),
    ("mid", ["ii", " 2"]),
    ("junior", ["junior", "jr.", "jr ", "associate", "early career",
                "new grad", "graduate", "entry level", "entry-level", " i "]),
    ("intern", ["intern", "internship", "co-op", "coop", "apprentice",
                "residency", "resident"]),
]

# --------------------------------------------------------------------------
# AI/ML tech tags -- what the vertical focus actually buys you.
# --------------------------------------------------------------------------

_TECH_TAGS: dict[str, list[str]] = {
    "pytorch": ["pytorch", "torch"],
    "jax": ["jax", "flax", "xla"],
    "cuda": ["cuda", "triton kernel", "nccl", "cutlass"],
    "vllm": ["vllm", "sglang", "tensorrt", "tgi"],
    "rag": ["retrieval augmented", "retrieval-augmented", " rag ", "vector database",
            "embeddings", "semantic search"],
    "agents": ["agentic", "ai agent", "llm agent", "tool use", "tool-use",
               "multi-agent", "mcp", "model context protocol"],
    "evals": ["eval", "benchmark", "red team", "red-team", "model evaluation"],
    "rlhf": ["rlhf", "reinforcement learning from human", "dpo",
             "preference optimization", "reward model"],
    "finetuning": ["fine-tun", "finetun", "lora", "peft", "distillation"],
    "kubernetes": ["kubernetes", "k8s", "terraform", "helm"],
    "ray": ["ray ", "raycluster", "slurm", "kubeflow"],
    "typescript": ["typescript", "react", "next.js", "nextjs"],
    "golang": ["golang", " go ", "rust"],
}

# --------------------------------------------------------------------------
# Location / remote
# --------------------------------------------------------------------------

# "distributed" is deliberately absent: "distributed systems" appears in half
# of all backend job descriptions and was producing false remote flags.
_REMOTE_PATTERNS = re.compile(
    r"\b(remote|fully remote|work from home|wfh|work from anywhere)\b", re.IGNORECASE
)
_HYBRID_PATTERNS = re.compile(r"\b(hybrid|in[- ]office|onsite|on[- ]site)\b", re.IGNORECASE)

_REGION_HINTS: list[tuple[str, list[str]]] = [
    # Two-letter state codes are anchored to ", XX" so that "Mars" no longer
    # matches " ma" and "Seoul" no longer matches " eu".
    ("US", ["united states", "usa", "u.s.", ", ca", ", ny", ", wa", ", tx",
            ", ma", ", il", ", co", ", ga", ", nc", ", va",
            "san francisco", "new york", "seattle", "austin", "boston",
            "palo alto", "mountain view", "los angeles", "chicago", "denver",
            "remote - us", "remote (us", "remote, us", "us remote",
            "north america", "americas", " usa", "u.s.a"]),
    ("UK", ["united kingdom", "london", " uk", "uk ", "england", "scotland",
            "cambridge, uk"]),
    ("EU", ["germany", "berlin", "munich", "france", "paris", "netherlands",
            "amsterdam", "spain", "madrid", "barcelona", "ireland", "dublin",
            "poland", "warsaw", "switzerland", "zurich", "sweden", "stockholm",
            "portugal", "lisbon", "europe", " eu ", "- eu", "(eu", "emea"]),
    ("IN", ["india", "bengaluru", "bangalore", "hyderabad", "mumbai", "delhi",
            "pune", "gurgaon", "noida", "chennai"]),
    ("APAC", ["singapore", "tokyo", "japan", "korea", "seoul", "australia",
              "sydney", "melbourne", "hong kong", "china", "beijing",
              "shanghai", "taiwan"]),
    ("CA", ["canada", "toronto", "vancouver", "montreal", "ontario"]),
    ("LATAM", ["brazil", "sao paulo", "são paulo", "mexico", "argentina",
               "colombia", "chile"]),
    ("MEA", ["israel", "tel aviv", "dubai", "uae", "abu dhabi", "south africa"]),
]

# --------------------------------------------------------------------------
# Salary parsing
# --------------------------------------------------------------------------

_MONEY = r"(?:USD\s*)?[\$£€]\s?(\d{1,3}(?:,\d{3})+|\d{2,7}(?:\.\d+)?\s*[kK]?)"
_SALARY_RANGE = re.compile(rf"{_MONEY}\s*(?:-|–|—|to)\s*{_MONEY}", re.IGNORECASE)
_CURRENCY_SYMBOL = re.compile(r"[\$£€]|USD|GBP|EUR", re.IGNORECASE)


def _money_to_int(token: str) -> int | None:
    token = token.strip().replace(",", "")
    multiplier = 1
    if token.lower().endswith("k"):
        multiplier = 1000
        token = token[:-1].strip()
    try:
        value = float(token) * multiplier
    except ValueError:
        return None
    if value < 1000:  # e.g. "$180" meaning 180k
        value *= 1000
    if not (10_000 <= value <= 5_000_000):
        return None
    return int(value)


def parse_salary(*sources: str | None) -> dict[str, Any]:
    """Find a salary band in any of the given strings. Returns {} if none."""
    for text in sources:
        if not text:
            continue
        snippet = str(text)[:6000]
        match = _SALARY_RANGE.search(snippet)
        if not match:
            continue
        low = _money_to_int(match.group(1))
        high = _money_to_int(match.group(2))
        if low is None or high is None or high < low:
            continue
        symbol = _CURRENCY_SYMBOL.search(match.group(0))
        currency = "USD"
        if symbol:
            token = symbol.group(0).upper()
            currency = {"$": "USD", "£": "GBP", "€": "EUR"}.get(token, token)
        return {
            "salary_min": low,
            "salary_max": high,
            "salary_currency": currency,
            "salary_midpoint": (low + high) // 2,
        }
    return {}


# Fallback when the title alone is ambiguous ("Analyst", "Associate") but the
# ATS gave us a department name.
_DEPARTMENT_MAP: dict[str, str] = {
    "research": "ml_research", "ai research": "ml_research",
    "machine learning": "ml_engineering", "ml": "ml_engineering", "ai": "ml_engineering",
    "data": "data", "data science": "data", "analytics": "data",
    "engineering": "engineering", "software": "engineering", "technology": "engineering",
    "infrastructure": "infrastructure", "platform": "infrastructure", "it": "infrastructure",
    "security": "security", "trust and safety": "security", "trust & safety": "security",
    "product": "product", "program management": "product",
    "design": "design", "brand studio": "design",
    "sales": "sales", "revenue": "sales", "customer success": "sales",
    "partnerships": "sales", "go to market": "sales", "go-to-market": "sales",
    "marketing": "marketing", "growth": "marketing", "communications": "marketing",
    "developer relations": "devrel", "devrel": "devrel", "community": "devrel",
    "recruiting": "recruiting", "people": "recruiting", "talent": "recruiting",
    "human resources": "recruiting",
    "finance": "finance", "accounting": "finance",
    "legal": "legal", "policy": "legal", "compliance": "legal",
    "operations": "operations", "business operations": "operations",
    "support": "support", "customer experience": "support",
}


def classify_function(title: str, department: str | None = None) -> str:
    haystack = f" {title.lower()} | {(department or '').lower()} "
    for name, keywords in _FUNCTION_RULES:
        if any(kw in haystack for kw in keywords):
            return name
    dept = (department or "").strip().lower()
    if dept in _DEPARTMENT_MAP:
        return _DEPARTMENT_MAP[dept]
    return "other"


def classify_seniority(title: str) -> str:
    haystack = f" {title.lower()} "
    for name, keywords in _SENIORITY_RULES:
        if any(kw in haystack for kw in keywords):
            return name
    return "mid"


def detect_remote(location: str, description: str, hint: str | None = None) -> str:
    """An explicit ATS field beats the location text, which beats the body text."""
    if hint in ("remote", "hybrid", "onsite"):
        return hint
    if _REMOTE_PATTERNS.search(location or ""):
        return "remote"
    if _HYBRID_PATTERNS.search(location or ""):
        return "hybrid"
    blob = description[:1500]
    if _HYBRID_PATTERNS.search(blob):
        return "hybrid"
    if _REMOTE_PATTERNS.search(blob):
        return "remote"
    return "unknown"


def detect_region(location: str) -> str | None:
    haystack = f" {(location or '').lower()} "
    for region, hints in _REGION_HINTS:
        if any(hint in haystack for hint in hints):
            return region
    return None


def detect_tech_tags(title: str, description: str) -> list[str]:
    haystack = f" {title.lower()} {description[:8000].lower()} "
    return sorted(
        tag for tag, keywords in _TECH_TAGS.items()
        if any(kw in haystack for kw in keywords)
    )


def enrich(job: dict[str, Any]) -> dict[str, Any]:
    """Add every derived field to a normalised job row. Mutates and returns it."""
    title = job.get("title") or ""
    description = job.get("description") or ""
    location = job.get("location_raw") or ""

    job["function"] = classify_function(title, job.get("department"))
    job["seniority"] = classify_seniority(title)
    job["workplace"] = detect_remote(location, description, job.get("workplace_hint"))
    job["region"] = detect_region(location)
    job["tech_tags"] = detect_tech_tags(title, description)
    job.update(parse_salary(job.get("compensation_raw"), description))

    # Description is huge; keep a usable excerpt, drop the rest before output.
    job["description_excerpt"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", description)).strip()[:600]
    job.pop("description", None)
    job.pop("workplace_hint", None)
    return job