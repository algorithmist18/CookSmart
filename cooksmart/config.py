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
    speech: str = "auto"                 # auto (Gnani if a key is set) | gnani | mock
    gnani_stt_url: str = "https://api.vachana.ai/stt/v3"
    gnani_tts_url: str = "https://api.vachana.ai/api/v1/tts/inference"
    gnani_voice: str = "Nalini"
    gnani_model: str = "timbre-v2.5"
    inya_platform_key: str = ""          # Agent Builder Platform API key (header x-api-key)
    inya_bot_id: str = ""                # botId of the deployed cook-call agent
    inya_environment: str = "development"
    gnani_webhook_token: str = ""        # shared secret in the webhook/action URLs; endpoints are off without it


def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        db_path=os.environ.get("COOKSMART_DB", "cooksmart.db"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        model=os.environ.get("COOKSMART_MODEL", "claude-sonnet-5-5"),
        gnani_api_key=os.environ.get("GNANI_API_KEY", ""),
        whatsapp_verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN", "cooksmart-dev"),
        speech=os.environ.get("COOKSMART_SPEECH", "auto").lower(),
        gnani_stt_url=os.environ.get("GNANI_STT_URL", "https://api.vachana.ai/stt/v3"),
        gnani_tts_url=os.environ.get("GNANI_TTS_URL", "https://api.vachana.ai/api/v1/tts/inference"),
        gnani_voice=os.environ.get("GNANI_VOICE", "Nalini"),
        gnani_model=os.environ.get("GNANI_MODEL", "timbre-v2.5"),
        inya_platform_key=os.environ.get("INYA_PLATFORM_KEY", ""),
        inya_bot_id=os.environ.get("INYA_BOT_ID", ""),
        inya_environment=os.environ.get("INYA_ENVIRONMENT", "development"),
        gnani_webhook_token=os.environ.get("GNANI_WEBHOOK_TOKEN", ""),
    )
