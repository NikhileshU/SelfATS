"""Company slug lists for the ATS-backed adapters (greenhouse/lever/ashby).
Edit storage/company_boards.json to add or remove companies — no code
changes needed. See README for how to find a company's slug."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "storage" / "company_boards.json"


def load_slugs(platform: str) -> list[str]:
    data = json.loads(CONFIG_PATH.read_text())
    return data.get(platform, [])
