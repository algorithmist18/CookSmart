"""Capability 1: vernacular_asr_intent (speech half). MOCK now; Gnani STT/TTS later.

In the mock UI the "voice note" is typed text; the transcript carries a confidence score so the
low-confidence / misheard path (Bengali-heard-as-Hindi style) can be tested.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .controls import MockControls

LOW_CONFIDENCE = 0.6


@dataclass
class Transcript:
    text: str
    confidence: float
    lang: str


class SpeechProvider(Protocol):
    def transcribe(self, payload: str, lang: str) -> Transcript: ...


class MockSpeechProvider:
    def __init__(self, controls: MockControls):
        self.controls = controls

    def transcribe(self, payload, lang):
        conf = 0.35 if self.controls.stt_low_confidence else 0.95
        return Transcript(payload, conf, lang)


class GnaniSpeechProvider:
    """Placeholder for the real integration (STT REST <=60s voice notes; hi-IN). Not wired yet:
    the Gnani docs were not reachable when this was scaffolded, so no endpoint is guessed here."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def transcribe(self, payload, lang):
        raise NotImplementedError("Wire Gnani STT here once the API docs are reviewed.")
