"""Quick-commerce price/ETA comparison + order placement. MOCK of Instamart/Zepto/BigBasket-style stores.

Real partner APIs are not confirmed to exist publicly; a real provider would implement the same
interface (quote / place / status) or fall back to prefilled cart deep links.
"""
from __future__ import annotations

import math
from typing import Protocol

from ..recipes import ITEMS
from .controls import MockControls

DELIVERY_MIN = 15      # every order arrives 15 minutes after it is placed (plus any delay set on the mock)

STORES = [
    # name, price multiplier, base ETA minutes, kind
    ("QuickCart", 1.10, DELIVERY_MIN, "hyperlocal"),
    ("FreshBasket", 1.00, DELIVERY_MIN, "hyperlocal"),
]
PARCEL_STORE = ("BulkParcel (via Delhivery)", 0.85, 0, "parcel")


class GroceryProvider(Protocol):
    def quote(self, items: list[dict], pincode: str) -> list[dict]: ...
    def quote_parcel(self, items: list[dict], pincode: str, eta_minutes: int) -> dict | None: ...
    def place(self, offer: dict) -> str: ...
    def status(self, provider_ref: str) -> str: ...


def build_offer(store: str, mult: float, eta: int, kind: str, items: list[dict], controls: MockControls) -> dict:
    lines, fair, missing = [], 0.0, []
    for it in items:
        meta = ITEMS[it["name"]]
        if it["name"] in controls.out_of_stock:
            missing.append(it["name"])
            continue
        packs = max(1, math.ceil(it["qty"] / meta["pack"] - 1e-9))
        fair_price = packs * meta["price"]
        price = round(fair_price * mult * controls.price_factor, 2)
        fair += fair_price
        lines.append({"name": it["name"], "qty": packs * meta["pack"], "unit": meta["unit"],
                      "packs": packs, "price": price})
    total = round(sum(line["price"] for line in lines), 2)
    return {"store": store, "kind": kind, "items": lines, "total": total, "fair_total": fair,
            "eta_minutes": eta + controls.eta_delay_min, "available": not missing, "missing": missing,
            "overpriced": False}


class MockGroceryProvider:
    def __init__(self, controls: MockControls):
        self.controls = controls
        self._orders: dict[str, str] = {}
        self._n = 0

    def quote(self, items, pincode):
        return [build_offer(n, m, e, k, items, self.controls) for n, m, e, k in STORES]

    def quote_parcel(self, items, pincode, eta_minutes):
        n, m, _, k = PARCEL_STORE
        return build_offer(n, m, eta_minutes, k, items, self.controls)

    def place(self, offer):
        self._n += 1
        ref = f"GRO-{self._n:05d}"
        self._orders[ref] = "cancelled" if self.controls.cancel_after_accept else "accepted"
        return ref

    def status(self, provider_ref):
        return self._orders.get(provider_ref, "accepted")

    def mark_delivered(self, provider_ref):
        self._orders[provider_ref] = "delivered"
