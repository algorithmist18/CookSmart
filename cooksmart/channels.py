"""Chat channel abstraction. MockChannel stores messages (shown in the demo UI).

To go live, implement the same two methods against the WhatsApp Cloud API (two numbers: one for the
owner, one for the cook). Nothing else in the agent changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import repo
from .db import DB


@dataclass(frozen=True)
class CookMessage:
    """Everything the cook can ever receive. Built only from cookmsgs templates: no prices, stock,
    orders or owner conversation can reach this type."""
    text: str
    lang: str = "hi-IN"


class MessageChannel(Protocol):
    def send_owner(self, hid: str, text: str, buttons: list[str] | None = None) -> None: ...
    def send_cook(self, hid: str, msg: CookMessage) -> None: ...


class MockChannel:
    def __init__(self, db: DB):
        self.db = db

    def send_owner(self, hid, text, buttons=None):
        repo.add_message(self.db, hid, "owner", "agent", text, {"buttons": buttons} if buttons else None)

    def send_cook(self, hid, msg):
        repo.add_message(self.db, hid, "cook", "agent", msg.text, {"lang": msg.lang, "voice": True})
