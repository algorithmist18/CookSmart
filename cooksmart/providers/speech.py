"""Capability 1: vernacular_asr_intent (speech half).

Interfaces and the offline mock live here; the real Gnani client is in gnani.py. Wrapped in
ResilientSpeech so the kitchen never gets stuck: if the speech service fails, the cook is asked to repeat
or type, and nothing is acted on.
"""
from __future__ import annotations

from .. import trace

from dataclasses import dataclass
from typing import Protocol

from .controls import MockControls

LOW_CONFIDENCE = 0.6


class SpeechError(Exception):
    """The speech service failed (network, auth, bad response)."""


@dataclass
class Transcript:
    text: str
    confidence: float
    lang: str
    source: str = "mock"          # gnani | browser | mock
    error: str | None = None
    raw: str | None = None        # truncated raw response, kept when it could not be parsed


@dataclass
class VoiceNote:
    audio: bytes
    mime: str
    key: str                      # cache key: identical text is never synthesised twice


class SpeechProvider(Protocol):
    def transcribe(self, payload: str, lang: str) -> Transcript: ...
    def transcribe_audio(self, audio: bytes, mime: str, lang: str, hint: str | None = None) -> Transcript: ...
    def synthesize(self, text: str, lang: str) -> VoiceNote | None: ...
    def describe(self) -> dict: ...


class MockSpeechProvider:
    """No network. Typed text counts as the transcript; recorded audio needs the browser's own transcript as a
    hint (Chrome speech recognition), otherwise it is "unclear" and the agent asks the cook to repeat."""

    def __init__(self, controls: MockControls | None = None):
        self.controls = controls or MockControls()

    def _conf(self, base: float) -> float:
        return 0.35 if self.controls.stt_low_confidence else base

    def transcribe(self, payload, lang):
        return Transcript(payload, self._conf(0.95), lang, "mock")

    def transcribe_audio(self, audio, mime, lang, hint=None):
        req = {"note": "no Gnani key: nothing was sent", "audio_file": audio, "language_code": lang, "browser_transcript_hint": hint}
        if hint and hint.strip():
            trace.record("gnani", "Gnani STT (mock: browser transcript used)", req, {"text": hint.strip()})
            return Transcript(hint.strip(), self._conf(0.85), lang, "browser")
        trace.record("gnani", "Gnani STT (mock)", req, {"error": "no transcript available without a speech service"}, "error")
        return Transcript("", 0.0, lang, "mock", error="no transcript available without a speech service")

    def synthesize(self, text, lang):
        trace.record("gnani", "Gnani TTS (mock: browser voice)", {"note": "no Gnani key: nothing was sent", "text": text, "language": lang},
                     {"audio": None})
        return None               # the browser reads the text aloud instead

    def describe(self):
        return {"stt": "mock (browser speech hint)", "tts": "browser voice", "live": False}


class ResilientSpeech:
    """Primary (Gnani) with a safe fallback. Applies the 'cook's voice unclear' switch to any provider."""

    def __init__(self, primary: SpeechProvider, fallback: SpeechProvider, controls: MockControls | None = None):
        self.primary, self.fallback = primary, fallback
        self.controls = controls or MockControls()

    def _degrade(self, tr: Transcript) -> Transcript:
        if self.controls.stt_low_confidence:
            tr.confidence = min(tr.confidence, 0.35)
        return tr

    def transcribe(self, payload, lang):
        return self._degrade(self.fallback.transcribe(payload, lang))

    def transcribe_audio(self, audio, mime, lang, hint=None):
        try:
            return self._degrade(self.primary.transcribe_audio(audio, mime, lang, hint))
        except Exception as e:     # any failure: fall back, and say why
            tr = self.fallback.transcribe_audio(audio, mime, lang, hint)
            tr.error = f"{type(e).__name__}: {e}"[:300]
            return self._degrade(tr)

    def synthesize(self, text, lang):
        try:
            return self.primary.synthesize(text, lang)
        except Exception:
            return None

    def describe(self):
        d = self.primary.describe()
        d["fallback"] = "browser speech hint / browser voice"
        return d
