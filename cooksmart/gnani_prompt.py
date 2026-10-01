"""The Gnani agent's system prompt (Jinja2): load it, render it locally, check every variable is supplied."""
from __future__ import annotations

from pathlib import Path

import jinja2

from .cookbrief import CookBriefData, to_variables

PROMPT_PATH = Path(__file__).resolve().parent.parent / "gnani" / "prompt.j2"
CONFIG_PATH = PROMPT_PATH.with_name("agent_config.json")


def load_prompt(path: Path = PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def render(variables: dict, prompt: str | None = None) -> str:
    """Render with StrictUndefined so a variable the prompt needs but CookSmart doesn't send fails loudly here,
    not silently on a live call."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=False, autoescape=False)
    return env.from_string(prompt if prompt is not None else load_prompt()).render(**variables)


def sample_variables(call_type: str = "brief") -> dict:
    return to_variables(CookBriefData(call_type=call_type, cook_name="दीदी", people=4, dishes=["दाल तड़का और रोटी"]))
