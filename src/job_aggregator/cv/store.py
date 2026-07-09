"""Persists the parsed CV profile to a single local JSON file, reused across
sessions until update_cv replaces it."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from job_aggregator.cv.models import CVProfile

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "storage" / "cv_profile.json"


def has_profile(path: Path | str = DEFAULT_PROFILE_PATH) -> bool:
    return Path(path).exists()


def load_profile(path: Path | str = DEFAULT_PROFILE_PATH) -> Optional[CVProfile]:
    path = Path(path)
    if not path.exists():
        return None
    return CVProfile.model_validate_json(path.read_text())


def save_profile(profile: CVProfile, path: Path | str = DEFAULT_PROFILE_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=2))
