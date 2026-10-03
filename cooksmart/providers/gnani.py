"""Gnani (Vachana) speech: STT (Prisma) and TTS (Timbre).

Contract, from Gnani's own curl examples:

  STT  POST https://api.vachana.ai/stt/v3                 header  X-API-Key-ID: <key>
       multipart: audio_file, language_code (hi-IN), format=transcribe, itn_native_numerals,
                  bias_list (JSON array of words), bias_score, enable_substitution, substitution_map
  TTS  POST https://api.vachana.ai/api/v1/tts/inference   header  X-API-Key-ID: <key>
       JSON: text, voice (e.g. Nalini), model (timbre-v2.5), language, speed, audio_config{...}

Not in those examples, so handled defensively: the *response* bodies. STT is parsed from the usual
transcript fields; TTS accepts raw audio bytes or JSON containing base64 audio. When a response cannot be
understood, a truncated copy is returned in Transcript.raw so the audit log shows the real shape.
"""
from __future__ import annotations

import base64
import hashlib
import re
import json

import httpx

from .. import trace

from ..recipes import ITEMS
from .speech import SpeechError, Transcript, VoiceNote

STT_URL = "https://api.vachana.ai/stt/v3"
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"
MAX_AUDIO_BYTES = 2_000_000          # REST is for short audio (about 60 s); 16 kHz mono PCM16 is ~1.9 MB/minute

TRANSCRIPT_KEYS = ("transcript", "text", "total_transcript", "transcription", "result", "output", "data")
AUDIO_KEYS = ("audioContent", "audio_content", "audio", "audio_base64", "data", "content")


def kitchen_vocabulary() -> list[str]:
    """Words the recogniser should favour (bias_list): ingredient names in Hindi and as spoken in Hinglish."""
    from ..recipes import ALIASES
    words: list[str] = []
    for item, meta in ITEMS.items():
        words.append(meta["hi"])
        words += [a for a in ALIASES[item] if a.isascii()]
    words += ["खत्म", "बचा", "बचे", "खराब", "गैस", "कुकर", "हाँ", "नहीं"]
    return list(dict.fromkeys(words))


def _find_text(obj) -> tuple[str | None, float | None]:
    """Locate a transcript (and a confidence, if present) anywhere in a parsed JSON response."""
    if isinstance(obj, str):
        return obj, None
    if isinstance(obj, dict):
        conf = next((float(obj[k]) for k in ("confidence", "score") if isinstance(obj.get(k), (int, float))), None)
        for k in TRANSCRIPT_KEYS:
            if k in obj:
                text, inner = _find_text(obj[k])
                if text is not None:
                    return text, inner if inner is not None else conf
        return None, conf
    if isinstance(obj, list):
        parts = [t for t, _ in (_find_text(x) for x in obj) if t]
        return (" ".join(parts) if parts else None), None
    return None, None


def _find_audio(obj) -> bytes | None:
    if isinstance(obj, dict):
        for k in AUDIO_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and len(v) > 100:
                try:
                    return base64.b64decode(v)
                except Exception:
                    continue
            if isinstance(v, (dict, list)):
                found = _find_audio(v)
                if found:
                    return found
    return None


_PICTO = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200d]")


def spoken_text(text: str) -> str:
    return re.sub(r"\s*\n+\s*", "। ", _PICTO.sub("", text)).replace("।।", "।").strip()


class GnaniSpeechProvider:
    def __init__(self, api_key: str, *, stt_url: str = STT_URL, tts_url: str = TTS_URL, voice: str = "Nalini",
                 model: str = "timbre-v2.5", sample_rate: int = 48000, bias_words: list[str] | None = None,
                 client: httpx.Client | None = None, timeout: float = 20.0):
        if not api_key:
            raise ValueError("GNANI_API_KEY is empty")
        self.api_key, self.stt_url, self.tts_url = api_key, stt_url, tts_url
        self.voice, self.model, self.sample_rate = voice, model, sample_rate
        self.bias = bias_words if bias_words is not None else kitchen_vocabulary()
        self.client = client or httpx.Client(timeout=timeout)
        self._tts_cache: dict[str, VoiceNote] = {}

    # ------------------------------------------------------------ STT
    def transcribe(self, payload, lang):                   # typed text: nothing to recognise
        return Transcript(payload, 0.95, lang, "gnani")

    def transcribe_audio(self, audio, mime, lang, hint=None):
        if len(audio) > MAX_AUDIO_BYTES:
            raise SpeechError("audio is longer than the REST limit; ask for a shorter voice note")
        data = {"language_code": lang, "format": "transcribe", "itn_native_numerals": "true",
                "bias_list": json.dumps(self.bias, ensure_ascii=False), "bias_score": "1"}
        req = {"url": self.stt_url, "form": {**data, "bias_list": f"{len(self.bias)} kitchen words"}, "audio_file": audio}
        with trace.timed() as t:
            try:
                r = self.client.post(self.stt_url, headers={"X-API-Key-ID": self.api_key}, data=data,
                                     files={"audio_file": ("voice.wav", audio, mime or "audio/wav")})
            except httpx.HTTPError as e:
                trace.record("gnani", "Gnani STT (speech to text)", req, {"error": str(e)}, "error", t.ms)
                raise SpeechError(f"could not reach Gnani STT: {e}") from e
        trace.record("gnani", "Gnani STT (speech to text)", req, {"status": r.status_code, "body": (r.text or "")[:600]},
                     "ok" if r.status_code < 400 else "error", t.ms)
        if r.status_code in (401, 403):
            raise SpeechError(f"Gnani rejected the API key (HTTP {r.status_code})")
        if r.status_code >= 400:
            raise SpeechError(f"Gnani STT HTTP {r.status_code}: {r.text[:200]}")
        try:
            body = r.json()
        except ValueError:
            body = r.text
        text, conf = _find_text(body)
        if text is None:
            return Transcript("", 0.0, lang, "gnani", error="unrecognised STT response shape",
                              raw=(r.text or "")[:600])
        text = text.strip()
        return Transcript(text, (conf if conf is not None else 0.9) if text else 0.0, lang, "gnani")

    # ------------------------------------------------------------ TTS
    def synthesize(self, text, lang):
        text = spoken_text(text)                          # icons and line breaks are for the screen, not the voice
        key = hashlib.sha1(f"{self.model}|{self.voice}|{lang}|{self.sample_rate}|{text}".encode()).hexdigest()
        if key in self._tts_cache:
            return self._tts_cache[key]
        body = {"text": text, "voice": self.voice, "model": self.model, "language": lang, "speed": 1,
                "audio_config": {"encoding": "linear_pcm", "container": "wav", "num_channels": 1,
                                 "sample_rate": self.sample_rate, "sample_width": 2}}
        with trace.timed() as t:
            try:
                r = self.client.post(self.tts_url, headers={"X-API-Key-ID": self.api_key}, json=body)
            except httpx.HTTPError as e:
                trace.record("gnani", "Gnani TTS (text to speech)", {"url": self.tts_url, "body": body}, {"error": str(e)}, "error", t.ms)
                raise SpeechError(f"could not reach Gnani TTS: {e}") from e
        trace.record("gnani", "Gnani TTS (text to speech)", {"url": self.tts_url, "body": body},
                     {"status": r.status_code, "content_type": r.headers.get("content-type", ""),
                      "body": f"<{len(r.content)} bytes of audio>" if r.content[:4] == b"RIFF" or r.headers.get("content-type", "").startswith("audio/") else (r.text or "")[:300]},
                     "ok" if r.status_code < 400 else "error", t.ms)
        if r.status_code >= 400:
            raise SpeechError(f"Gnani TTS HTTP {r.status_code}: {r.text[:200]}")
        ctype = r.headers.get("content-type", "")
        if ctype.startswith("audio/") or r.content[:4] == b"RIFF":
            audio = r.content
        else:
            try:
                audio = _find_audio(r.json())
            except ValueError:
                audio = None
            if not audio:
                raise SpeechError("unrecognised TTS response shape: " + (r.text or "")[:200])
        note = VoiceNote(audio, "audio/wav", key)
        self._tts_cache[key] = note
        return note

    def describe(self):
        return {"stt": "Gnani Prisma", "tts": f"Gnani Timbre ({self.voice})", "live": True}
