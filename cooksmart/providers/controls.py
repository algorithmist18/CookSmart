"""Failure switches for the mock rails, so every unhappy flow in the spec can be exercised on demand."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class MockControls:
    out_of_stock: set[str] = field(default_factory=set)   # item names unavailable at every store
    price_factor: float = 1.0                              # >1.5 => offers look overpriced
    eta_delay_min: int = 0                                 # added to every ETA (late groceries)
    payment_fails: bool = False                            # bank declines
    cancel_after_accept: bool = False                      # store cancels after accepting
    stt_low_confidence: bool = False                       # voice note is unclear / misheard

    def reset(self) -> None:
        self.out_of_stock = set()
        self.price_factor = 1.0
        self.eta_delay_min = 0
        self.payment_fails = False
        self.cancel_after_accept = False
        self.stt_low_confidence = False

    def update(self, data: dict) -> None:
        if "out_of_stock" in data:
            self.out_of_stock = set(data["out_of_stock"])
        for k in ("price_factor", "eta_delay_min", "payment_fails", "cancel_after_accept", "stt_low_confidence"):
            if k in data:
                setattr(self, k, type(getattr(self, k))(data[k]))

    def as_dict(self) -> dict:
        d = asdict(self)
        d["out_of_stock"] = sorted(self.out_of_stock)
        return d
