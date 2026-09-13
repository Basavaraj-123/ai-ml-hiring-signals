"""
Fixtures built from the REAL response shapes of each ATS, captured Sept 2026
(Greenhouse: anthropic, Ashby: openai, Lever: matchgroup). Field names and
types match production exactly.
"""

GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 4461450008,
            "title": "Account Executive, AI Native",
            "company_name": "Anthropic",
            "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/4461450008",
            "internal_job_id": 4147866008,
            "requisition_id": "3356",
            "location": {"name": "New York City, NY; San Francisco, CA"},
            "updated_at": "2026-08-21T21:32:54-04:00",
            "first_published": "2026-08-20T13:53:38-05:00",
            "language": "en",
            "metadata": [
                {"id": 1, "name": "Salary Range", "value": "$220,000 - $280,000",
                 "value_type": "short_text"},
                {"id": 2, "name": "Employment Type", "value": "Full-time",
                 "value_type": "short_text"},
            ],
            "content": "<p>Help enterprise customers adopt Claude. Hybrid, 3 days in office.</p>",
        },
        {
            "id": 4461450009,
            "title": "Senior Research Engineer, Interpretability",
            "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/4461450009",
            "location": {"name": "San Francisco, CA"},
            "updated_at": "2026-09-01T10:00:00-04:00",
            "first_published": "2026-07-15T10:00:00-04:00",
            "metadata": [],
            "content": "<p>Work on sparse autoencoders and model internals using PyTorch and JAX. "
                       "Compensation: $340,000 - $505,000 USD.</p>",
        },
        {
            "id": 4461450010,
            "title": "Machine Learning Intern, Inference",
            "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/4461450010",
            "location": {"name": "Remote - United States"},
            "updated_at": "2026-09-05T10:00:00-04:00",
            "first_published": "2026-09-05T10:00:00-04:00",
            "metadata": [],
            "content": "<p>Optimize vLLM serving throughput with CUDA kernels.</p>",
        },
    ]
}

ASHBY_PAYLOAD = {
    "jobs": [
        {
            "id": "8fb1615c-34bf-47c4-a1d1-b7b2f836bbd3",
            "title": "Technical Program Manager, Compute Infrastructure",
            "location": "San Francisco",
            "department": "Technical Program Management",
            "team": "Technical Program Management",
            "employmentType": "FullTime",
            "jobUrl": "https://jobs.ashbyhq.com/openai/8fb1615c",
            "publishedAt": "2026-03-12T16:38:15.322+00:00",
            "isListed": True,
            "isRemote": None,
            "compensation": "$257K – $335K + Equity",
            "descriptionPlain": "Drive GPU cluster programs across Kubernetes fleets.",
        },
        {
            "id": "unlisted-role-id",
            "title": "Confidential Executive Search",
            "location": "San Francisco",
            "jobUrl": "https://jobs.ashbyhq.com/openai/unlisted",
            "publishedAt": "2026-01-01T00:00:00.000+00:00",
            "isListed": False,
            "descriptionPlain": "",
        },
        {
            "id": "c11e2f00-aaaa-bbbb-cccc-ddddeeeeffff",
            "title": "Developer Advocate, Agents",
            "location": "Remote",
            "department": "Developer Relations",
            "team": "DevRel",
            "employmentType": "FullTime",
            "jobUrl": "https://jobs.ashbyhq.com/openai/c11e2f00",
            "publishedAt": "2026-09-10T09:00:00.000+00:00",
            "isListed": True,
            "isRemote": True,
            "compensation": None,
            "descriptionPlain": "Teach developers to build agentic workflows with MCP and tool use.",
        },
    ]
}

LEVER_PAYLOAD = [
    {
        "id": "7fca4a70-174c-41a2-b44b-7ff1cb9422e7",
        "text": "Staff Software Engineer, Platform",
        "categories": {
            "commitment": "Full-time",
            "department": "Engineering",
            "location": "Bengaluru, India",
            "team": "Platform",
        },
        "createdAt": 1787203369315,
        "country": "IN",
        "workplaceType": "hybrid",
        "hostedUrl": "https://jobs.lever.co/acme/7fca4a70",
        "applyUrl": "https://jobs.lever.co/acme/7fca4a70/apply",
        "descriptionPlain": "Build distributed systems in Go and Rust on Kubernetes.",
    },
    {
        "id": "aaaa1111-2222-3333-4444-555566667777",
        "text": "Head of Revenue Operations",
        "categories": {
            "commitment": "Full-time",
            "department": "Finance",
            "location": "Remote - EU",
        },
        "createdAt": 1788000000000,
        "country": "DE",
        "workplaceType": "remote",
        "hostedUrl": "https://jobs.lever.co/acme/aaaa1111",
        "descriptionPlain": "Own the revenue stack. €120,000 - €160,000.",
    },
]
