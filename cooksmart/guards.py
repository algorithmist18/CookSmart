"""Hard rules enforced in code, not in prompts. Claude cannot talk its way past these.

An order can only be placed with an OrderAuthorization, and an authorization can only be minted by
authorize_owner_tap (the owner explicitly approved) or authorize_auto (owner-set policy, all limits hold).
Silence is never an authorization.
"""
from __future__ import annotations

from dataclasses import dataclass


class GuardViolation(Exception):
    pass


_TOKEN = object()


@dataclass(frozen=True)
class OrderAuthorization:
    kind: str            # 'owner_tap' | 'auto_policy'
    plan_id: int
    max_amount: float
    _token: object = None

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise GuardViolation("OrderAuthorization can only be created through guards.authorize_*")


def authorize_owner_tap(plan: dict, offer: dict) -> OrderAuthorization:
    """The owner tapped 'approve' on this exact offer; the tap covers exactly this amount."""
    if not offer or not offer.get("available"):
        raise GuardViolation("offer is not available")
    return OrderAuthorization("owner_tap", plan["id"], offer["total"], _TOKEN)


def auto_eligibility(household: dict, plan: dict, offer: dict) -> tuple[bool, str]:
    if household["order_mode"] != "auto":
        return False, "ordering mode is 'approve each order'"
    if not plan["reviewed"]:
        return False, "the owner has not reviewed this menu (silence never triggers an order)"
    if not offer.get("available"):
        return False, "offer is not fully available"
    if offer.get("overpriced"):
        return False, "offer looks overpriced"
    limit = min(household["auto_cap"], household["mandate_ceiling"])
    if offer["total"] > limit:
        return False, f"₹{offer['total']:.0f} is above your auto-order limit ₹{limit:.0f}"
    return True, "within auto-order limits"


def authorize_auto(household: dict, plan: dict, offer: dict) -> OrderAuthorization:
    ok, why = auto_eligibility(household, plan, offer)
    if not ok:
        raise GuardViolation(why)
    return OrderAuthorization("auto_policy", plan["id"], offer["total"], _TOKEN)


def assert_can_charge(auth: object, amount: float) -> None:
    if not isinstance(auth, OrderAuthorization):
        raise GuardViolation("no valid authorization to place an order")
    if amount > auth.max_amount + 1e-6:
        raise GuardViolation(f"₹{amount:.0f} exceeds the authorized ₹{auth.max_amount:.0f}")
