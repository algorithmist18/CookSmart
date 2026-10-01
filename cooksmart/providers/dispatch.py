"""Capability 4: grocery_dispatch. MOCK of Delhivery.

Delhivery has no hyperlocal product: next-day parcel only. The provider must never promise a window
it cannot serve, so same-hour needs are reported as NOT serviceable and the agent reroutes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

NEXT_DAY_MIN = 24 * 60


@dataclass
class Serviceability:
    serviceable: bool
    eta_minutes: int | None = None
    waybill: str | None = None
    reason: str | None = None


class DispatchProvider(Protocol):
    def check(self, pincode: str, weight_g: int, needed_within_min: int) -> Serviceability: ...


class MockDispatchProvider:
    def __init__(self):
        self._n = 0

    def check(self, pincode, weight_g, needed_within_min):
        if not (pincode.isdigit() and len(pincode) == 6) or pincode == "000000":
            return Serviceability(False, reason="pincode not serviceable")
        if needed_within_min < NEXT_DAY_MIN:
            return Serviceability(False, reason="no hyperlocal product; earliest delivery is next day")
        self._n += 1
        return Serviceability(True, eta_minutes=NEXT_DAY_MIN, waybill=f"DLV{self._n:07d}")
