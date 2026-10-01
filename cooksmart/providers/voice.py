"""Capability 5: delegated_voice_handshake. MOCK of voiceprint verification (e.g. Gnani VC embeddings).

A voiceprint is a spoofable signal, so it is only ever an *extra* check: if it fails, release falls
back to an SMS-style OTP sent to the owner. Never hand over to an unverified person.
"""
from __future__ import annotations

from typing import Protocol


class VoiceVerifier(Protocol):
    def verify(self, enrolled: bool, sample: str) -> bool: ...


class MockVoiceVerifier:
    """Sample 'cook' matches an enrolled voiceprint; anything else ('stranger', 'none') does not."""

    def verify(self, enrolled, sample):
        return enrolled and sample == "cook"
