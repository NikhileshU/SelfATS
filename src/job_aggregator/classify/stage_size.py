"""Company stage/size bucketing.

Priority order:
1. yc_companies enrichment table (authoritative for YC-backed companies —
   see adapters/yc_oss.py).
2. A curated list of well-known large/MNC employers, matched by name.
3. Funding-stage phrases self-reported in the listing text (common on HN
   and startup job posts: "Series B", "seed-funded", "YC-backed", etc).
4. "unknown" — no clean open data source exists for arbitrary mid/large/MNC
   companies without a paid API (see ADR "Consequences" — revisit with
   Crunchbase or similar if precision matters later).
"""
from __future__ import annotations

import re
from typing import Optional

from job_aggregator.storage.models import normalize_text

# Large/multinational employers unlikely to ever appear in yc-oss's directory.
# Matched against normalized company name (startswith, since job postings
# often append suffixes like "Inc" that normalize_text already strips).
MNC_COMPANIES = {
    "google", "alphabet", "microsoft", "amazon", "meta", "facebook", "apple",
    "ibm", "oracle", "sap", "accenture", "tata consultancy services", "tcs",
    "infosys", "wipro", "cognizant", "capgemini", "deloitte", "ey",
    "ernst young", "pwc", "kpmg", "mckinsey", "bain", "bcg", "samsung",
    "sony", "intel", "cisco", "salesforce", "adobe", "hcl", "hcltech",
    "tech mahindra", "jpmorgan", "jp morgan", "goldman sachs", "morgan stanley",
    "citi", "citibank", "wells fargo", "bank of america", "visa", "mastercard",
    "walmart", "target", "unilever", "procter gamble", "pepsico",
    "coca cola", "nestle", "johnson johnson", "pfizer", "novartis", "roche",
    "astrazeneca", "sanofi", "shell", "exxonmobil", "chevron", "toyota",
    "volkswagen", "siemens", "philips", "bosch", "ge", "general electric",
    "boeing", "airbus", "verizon", "att", "comcast", "disney",
    "netflix", "nvidia", "qualcomm", "dell", "hp", "hewlett packard",
    "linkedin", "uber", "spotify", "twitter", "x corp", "paypal",
}

_STAGE_PHRASE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpre-seed\b", re.I), "pre-seed"),
    (re.compile(r"\bseed[- ]stage\b|\bseed[- ]funded\b|\bseed round\b", re.I), "seed"),
    (
        re.compile(r"\bseries [ab]\b|\by\s?combinator\b|\byc[- ]backed\b|\bearly[- ]stage\b", re.I),
        "early-stage",
    ),
    (re.compile(r"\bseries [cd]\b|\bgrowth[- ]stage\b", re.I), "mid"),
    (
        re.compile(
            r"\bseries [ef]\b|\bunicorn\b|\blate[- ]stage\b|\bpre-ipo\b|"
            r"\bpublicly traded\b|\bnasdaq[:\s]|\bnyse[:\s]",
            re.I,
        ),
        "large",
    ),
]


def classify_stage(
    company: str, raw_description: str, yc_stage: Optional[str] = None
) -> str:
    if yc_stage:
        return yc_stage

    norm_company = normalize_text(company)
    if norm_company and any(
        norm_company == mnc or norm_company.startswith(mnc + " ") for mnc in MNC_COMPANIES
    ):
        return "mnc"

    for pattern, stage in _STAGE_PHRASE_PATTERNS:
        if pattern.search(raw_description):
            return stage

    return "unknown"
