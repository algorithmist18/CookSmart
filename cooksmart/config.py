from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    db_path: str
    anthropic_api_key: str
    model: str
    gnani_api_key: str
    whatsapp_verify_token: str


def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        db_path=os.environ.get("COOKSMART_DB", "cooksmart.db"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        model=os.environ.get("COOKSMART_MODEL", "claude-sonnet-5-5"),
        gnani_api_key=os.environ.get("GNANI_API_KEY", ""),
        whatsapp_verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN", "cooksmart-dev"),
    )
