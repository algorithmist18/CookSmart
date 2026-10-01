"""Capability 3: one_tap_payment_mandate. MOCK of Pine Labs Payment Links + On-Demand Mandate.

Rule: never capture above the mandate ceiling without a fresh tap from the owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .controls import MockControls


@dataclass
class PaymentResult:
    ok: bool
    ref: str | None = None
    reason: str | None = None


class PaymentProvider(Protocol):
    def payment_link(self, amount: float, summary: str) -> str: ...
    def charge(self, amount: float, mandate_ceiling: float, fresh_tap: bool) -> PaymentResult: ...


class MockPaymentProvider:
    def __init__(self, controls: MockControls):
        self.controls = controls
        self._n = 0

    def payment_link(self, amount, summary):
        self._n += 1
        return f"https://pay.mock/pl/{self._n:05d}?amt={amount:.0f}"

    def charge(self, amount, mandate_ceiling, fresh_tap):
        if amount > mandate_ceiling and not fresh_tap:
            return PaymentResult(False, reason=f"₹{amount:.0f} is above the mandate ceiling ₹{mandate_ceiling:.0f}; "
                                               "needs a fresh tap")
        if self.controls.payment_fails:
            return PaymentResult(False, reason="payment declined by the bank")
        self._n += 1
        return PaymentResult(True, ref=f"PAY-{self._n:05d}")
