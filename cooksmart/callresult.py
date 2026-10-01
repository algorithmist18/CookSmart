"""Parse Gnani's post-call webhook and turn it into things CookSmart may act on.

Payload (snake_case, per Gnani's docs): conversation_id, STAGE_CODE, disposition_result, post_call_extraction_v2,
transcript, call_infra. The extraction fields are ones WE define in the console (see gnani/agent_config.json), so
the shape is parsed defensively. The one rule that matters: only items the cook CONFIRMED on the call are applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .recipes import ITEMS

REPORT_TYPES = {"used_up", "remaining", "spoiled", "low"}
PROBLEMS = {"stove", "cooker", "time", "ingredient"}
NO_ANSWER = {"RNR", "DND", "WRNG", "NOT_ANSWERED", "NO_ANSWER", "BUSY", "FAILED"}
OUR_KEYS = {"acknowledged", "reports", "problem", "leave_tomorrow", "safety_issue", "notes"}


def truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "y", "1", "haan", "हाँ", "हां", "confirmed"}
    return bool(v)


@dataclass
class CallOutcome:
    conversation_id: str | None
    reference_id: str | None
    disposition: str | None
    acknowledged: bool = False
    reports: list[dict] = field(default_factory=list)       # normalised, each with confirmed: bool
    problem: dict | None = None                              # {type, item, confirmed}
    leave_tomorrow: bool = False
    safety_issue: bool = False
    notes: str = ""
    ignored: list[str] = field(default_factory=list)         # things we could not understand

    @property
    def no_answer(self) -> bool:
        return (self.disposition or "").upper() in NO_ANSWER


def _unwrap(ex) -> dict:
    """Extraction may sit under a wrapper key; find the dict that has our fields."""
    if not isinstance(ex, dict):
        return {}
    if OUR_KEYS & set(ex):
        return ex
    for v in ex.values():
        if isinstance(v, dict):
            inner = _unwrap(v)
            if inner:
                return inner
    return {}


def parse_webhook(payload: dict) -> CallOutcome:
    disp = payload.get("disposition_result") or payload.get("disposition")
    if isinstance(disp, dict):
        disp = disp.get("disposition") or disp.get("code") or disp.get("name") or disp.get("result")
    oc = CallOutcome(
        conversation_id=payload.get("conversation_id") or payload.get("conversationId"),
        reference_id=payload.get("client_reference_id") or payload.get("clientReferenceId") or payload.get("reference_id"),
        disposition=str(disp).strip() if disp else None)
    ex = _unwrap(payload.get("post_call_extraction_v2") or payload.get("post_call_extraction") or {})
    oc.acknowledged = truthy(ex.get("acknowledged"))
    oc.leave_tomorrow = truthy(ex.get("leave_tomorrow"))
    oc.safety_issue = truthy(ex.get("safety_issue"))
    oc.notes = str(ex.get("notes") or "")[:300]
    for r in ex.get("reports") or []:
        item, typ = (r or {}).get("item"), (r or {}).get("type")
        if item not in ITEMS or typ not in REPORT_TYPES:
            oc.ignored.append(f"report {r!r}")
            continue
        qty = r.get("quantity", r.get("qty"))
        try:
            qty = float(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty = None
        if typ == "remaining" and qty is None:
            oc.ignored.append(f"remaining without a quantity: {item}")
            continue
        oc.reports.append({"type": typ, "item": item, "qty": qty, "unit": ITEMS[item]["unit"],
                           "confirmed": truthy(r.get("confirmed"))})
    p = ex.get("problem")
    if isinstance(p, dict) and p.get("type") in PROBLEMS:
        oc.problem = {"type": p["type"], "item": p.get("item"), "confirmed": truthy(p.get("confirmed"))}
    return oc


def to_intents(oc: CallOutcome) -> tuple[list[dict], list[dict]]:
    """-> (confirmed, unconfirmed) in the agent's intent vocabulary. Only the first list may change anything."""
    confirmed, unconfirmed = [], []
    for r in oc.reports:
        intent = {"type": r["type"], "item": r["item"]}
        if r["type"] == "remaining":
            intent.update(qty=r["qty"], unit=r["unit"])
        (confirmed if r["confirmed"] else unconfirmed).append(intent)
    if oc.problem and oc.problem["type"] in {"stove", "cooker", "time"}:
        intent = {"type": "cannot_cook", "reason": oc.problem["type"]}
        (confirmed if oc.problem["confirmed"] else unconfirmed).append(intent)
    return confirmed, unconfirmed


def pick_items(kind: str, menu: list[str], stocked: list[str]) -> list[str]:
    """Items a realistic simulated call talks about: something NOT in today's menu runs out (a finished menu item
    would rightly force a dish switch); the end-of-day report is about what the menu used."""
    if kind == "item_finished":
        spare = [i for i in ("paneer", *stocked) if i in stocked and i not in menu]
        return spare[:1] or menu[:1] or ["paneer"]
    return menu[:2] or ["paneer"]


def simulated_payload(kind: str, call: dict, items: list[str] | None = None) -> dict:
    """Webhook bodies shaped like Gnani's, for the simulator and tests. `kind` picks a story."""
    items = items or ["paneer"]
    base = {"conversation_id": f"sim-{call['reference_id']}", "client_reference_id": call["reference_id"],
            "STAGE_CODE": "COMPLETED", "transcript": "(simulated call)", "call_infra": {"provider": "simulated"}}
    ex: dict = {"acknowledged": True, "reports": [], "problem": {"type": "none", "confirmed": False},
                "leave_tomorrow": False, "safety_issue": False, "notes": ""}
    disp = "BRIEFED"
    if kind == "gas_problem":
        ex["problem"] = {"type": "stove", "confirmed": True}
        disp = "PROBLEM_REPORTED"
    elif kind == "cooker_problem":
        ex["problem"] = {"type": "cooker", "confirmed": True}
        disp = "PROBLEM_REPORTED"
    elif kind == "item_finished":
        ex["reports"] = [{"type": "used_up", "item": items[0], "confirmed": True}]
    elif kind == "unconfirmed":
        ex["reports"] = [{"type": "used_up", "item": items[0], "confirmed": False}]
    elif kind == "leave_tomorrow":
        ex["leave_tomorrow"] = True
        disp = "ON_LEAVE"
    elif kind == "safety":
        ex["safety_issue"] = True
        ex["notes"] = "gas smell"
        disp = "PROBLEM_REPORTED"
    elif kind == "no_answer":
        base["STAGE_CODE"] = "NOT_ANSWERED"
        disp, ex = "RNR", {}
    elif kind == "reconcile":
        ex["reports"] = [{"type": "used_up", "item": items[0], "confirmed": True}]
        if len(items) > 1:
            unit = ITEMS[items[1]]["unit"]
            ex["reports"].append({"type": "remaining", "item": items[1], "quantity": 2 if unit == "pcs" else 100,
                                  "confirmed": True})
        disp = "RECONCILED"
    base.update(disposition_result=disp, post_call_extraction_v2=ex)
    return base
