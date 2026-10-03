"""Chat channel abstraction. MockChannel stores messages (shown in the demo UI).

To go live, implement the same two methods against the WhatsApp Cloud API (two numbers: one for the
owner, one for the cook). Nothing else in the agent changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import repo, trace
from .db import DB


@dataclass(frozen=True)
class CookMessage:
    """Everything the cook can ever receive. Built only from cookmsgs templates: no prices, stock,
    orders or owner conversation can reach this type."""
    text: str
    lang: str = "hi-IN"
    buttons: tuple = ()


class MessageChannel(Protocol):
    def send_owner(self, hid: str, text: str, buttons: list[str] | None = None) -> None: ...
    def send_cook(self, hid: str, msg: CookMessage) -> None: ...


class MockChannel:
    def __init__(self, db: DB, speech=None):
        self.db, self.speech = db, speech

    def send_owner(self, hid, text, buttons=None):
        repo.add_message(self.db, hid, "owner", "agent", text, {"buttons": buttons} if buttons else None)
        trace.record("message", "To owner", {"text": text, **({"buttons": buttons} if buttons else {})}, hid=hid)

    def send_cook(self, hid, msg):
        """The cook gets a voice note. If a speech service is configured the audio is synthesised (and cached);
        otherwise the UI reads the text aloud with the browser's voice."""
        payload = {"lang": msg.lang, "voice": True, "buttons": list(msg.buttons) or None}
        if self.speech is not None:
            try:
                note = self.speech.synthesize(msg.text, msg.lang)
            except Exception:
                note = None
            if note:
                payload["media"] = repo.add_media(self.db, hid, note.key, note.mime, note.audio)
        repo.add_message(self.db, hid, "cook", "agent", msg.text, payload)
        trace.record("message", "To cook (voice note)", {"text": msg.text, "language": msg.lang,
                                                            "voice": "Gnani audio" if payload.get("media") else "browser voice"}, hid=hid)
